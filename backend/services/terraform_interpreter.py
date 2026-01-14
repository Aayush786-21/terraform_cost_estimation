"""
Terraform interpreter service using OpenAI with Mistral fallback.
Interprets Terraform files into structured cost-intent representation.
"""
from typing import Dict, Any, List, Optional
import json
import logging

from backend.services.mistral_client import MistralClient, MistralAPIError
from backend.services.openai_client import OpenAIClient, OpenAIAPIError
from backend.core.config import config


logger = logging.getLogger(__name__)


class TerraformInterpreterError(Exception):
    """Raised when Terraform interpretation fails."""
    pass


class TerraformInterpreter:
    """Service for interpreting Terraform files using Mistral AI with OpenAI fallback."""
    
    def __init__(
        self, 
        mistral_client: MistralClient = None,
        openai_client: OpenAIClient = None,
        ai_api_key: Optional[str] = None
    ):
        """
        Initialize Terraform interpreter.
        
        Args:
            mistral_client: Mistral client instance (creates new if None)
            openai_client: OpenAI client instance (creates new if None, used as fallback)
            ai_api_key: Optional API key to use for both clients (from X-AI-API-Key header)
        """
        self.ai_api_key = ai_api_key
        self.mistral_client = mistral_client or MistralClient(api_key=ai_api_key)
        self.openai_client = openai_client or OpenAIClient(api_key=ai_api_key)
        self.last_used_provider = None  # Track which provider was used successfully
    
    def _build_interpretation_prompt(self, terraform_files: List[Dict[str, str]]) -> str:
        """
        Build prompt for Mistral AI to interpret Terraform files.
        
        Prompt design principles:
        - Explicitly forbid price calculations
        - Emphasize uncertainty preservation
        - Provide clear schema requirements
        - Include examples of what to extract
        
        Args:
            terraform_files: List of dicts with 'path' and 'content' keys
        
        Returns:
            Formatted prompt string
        """
        files_text = "\n\n".join([
            f"## File: {file['path']}\n```hcl\n{file['content']}\n```"
            for file in terraform_files
        ])
        
        prompt = f"""You are a Terraform interpreter. Your task is to analyze Terraform configuration files and extract structured resource information for cost estimation purposes.

CRITICAL RULES:
1. DO NOT calculate prices or costs
2. DO NOT guess or invent values
3. DO NOT resolve Terraform expressions fully
4. Preserve uncertainty explicitly in the output
5. Mark confidence levels (high/medium/low) based on source
6. Extract unresolved variables and expressions

INPUT:
{files_text}

TASK:
For each Terraform resource, extract the following information:

1. Cloud Provider: aws | azure | gcp | unknown
2. Category: compute | database | storage | networking | load_balancing | container | analytics | messaging | identity | unknown
3. Service Name: e.g., EC2, RDS, GCE, Azure VM
4. Terraform Type: e.g., aws_instance, azurerm_virtual_machine
5. Logical Name: The resource name (e.g., "web", "db")
6. File Path: Source file path
7. Region:
   - source: explicit | variable | provider_default | unknown
   - value: actual value if explicit, null otherwise
8. Count Model:
   - type: fixed | for_each | autoscaling | unknown
   - value: numeric value if fixed and known
   - min/max/desired: if autoscaling
   - confidence: high (literal) | medium (variable) | low (expression)
9. Size Hint:
   - instance_type, sku, or tier if present
10. Usage Dimensions:
    - hours_per_month: if applicable (default 730 if running 24/7)
    - storage_gb: if applicable
    - requests_per_month: if applicable
    - data_transfer_gb: if applicable
11. Unresolved Inputs: List of variables/expressions that block certainty

OUTPUT FORMAT:
Return a valid JSON object with this exact structure:
{{
  "providers": ["aws"],
  "resources": [
    {{
      "cloud": "aws",
      "category": "compute",
      "service": "EC2",
      "terraform_type": "aws_instance",
      "name": "web",
      "file": "main.tf",
      "region": {{
        "source": "variable",
        "value": null
      }},
      "count_model": {{
        "type": "fixed",
        "value": 2,
        "confidence": "high"
      }},
      "size": {{
        "instance_type": "t3.micro"
      }},
      "usage": {{
        "hours_per_month": 730
      }},
      "unresolved_inputs": ["var.region"]
    }}
  ],
  "summary": {{
    "total_resources": 1,
    "has_autoscaling": false,
    "has_unknowns": true
  }}
}}

Return ONLY valid JSON, no markdown, no explanation, no code blocks."""
        
        return prompt
    
    def _validate_output_schema(self, output: Dict[str, Any]) -> None:
        """
        Validate that the AI output matches expected schema.
        
        Args:
            output: Parsed JSON output from Mistral
        
        Raises:
            TerraformInterpreterError: If schema validation fails
        """
        required_keys = ["providers", "resources", "summary"]
        for key in required_keys:
            if key not in output:
                raise TerraformInterpreterError(
                    f"Invalid output schema: missing '{key}' field"
                )
        
        if not isinstance(output["resources"], list):
            raise TerraformInterpreterError(
                "Invalid output schema: 'resources' must be a list"
            )
        
        if not isinstance(output["summary"], dict):
            raise TerraformInterpreterError(
                "Invalid output schema: 'summary' must be a dictionary"
            )
        
        required_summary_keys = ["total_resources", "has_autoscaling", "has_unknowns"]
        for key in required_summary_keys:
            if key not in output["summary"]:
                raise TerraformInterpreterError(
                    f"Invalid output schema: missing 'summary.{key}' field"
                )
    
    async def interpret(
        self,
        terraform_files: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Interpret Terraform files into structured cost-intent representation.
        
        Args:
            terraform_files: List of dictionaries with 'path' and 'content' keys
        
        Returns:
            Structured interpretation with resources and metadata
        
        Raises:
            TerraformInterpreterError: If interpretation fails
            MistralAPIError: If Mistral API call fails
        """
        if not terraform_files:
            raise TerraformInterpreterError("No Terraform files provided")
        
        # Build prompt
        prompt = self._build_interpretation_prompt(terraform_files)
        
        # Prepare messages for Mistral API
        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        # Try OpenAI first, then fall back to Mistral if OpenAI fails
        response = None
        last_error = None
        
        # Try OpenAI API first
        try:
            logger.info("Attempting Terraform interpretation with OpenAI")
            response = await self.openai_client.chat_completion(
                messages=messages,
                temperature=0.1,  # Low temperature for deterministic output
                response_format={"type": "json_object"}  # Enforce JSON response
            )
            self.last_used_provider = "openai"
            logger.info("Successfully interpreted Terraform with OpenAI")
        except OpenAIAPIError as error:
            last_error = error
            logger.warning(f"OpenAI API failed: {error}. Attempting fallback to Mistral...")
            
            # Fallback to Mistral
            try:
                logger.info("Attempting Terraform interpretation with Mistral (fallback)")
                response = await self.mistral_client.chat_completion(
                    messages=messages,
                    temperature=0.1,  # Low temperature for deterministic output
                    response_format={"type": "json_object"}  # Enforce JSON response
                )
                self.last_used_provider = "mistral"
                logger.info("Successfully interpreted Terraform with Mistral (fallback)")
            except MistralAPIError as mistral_error:
                # Both providers failed
                logger.error(f"Both OpenAI and Mistral failed. OpenAI: {error}, Mistral: {mistral_error}")
                raise TerraformInterpreterError(
                    f"Failed to interpret Terraform files: OpenAI failed ({str(error)}), Mistral fallback also failed ({str(mistral_error)})"
                ) from mistral_error
        
        if not response:
            raise TerraformInterpreterError(
                f"Failed to interpret Terraform files: {str(last_error)}"
            ) from last_error
        
        # Extract content from response
        choices = response.get("choices", [])
        if not choices:
            raise TerraformInterpreterError("Empty response from Mistral API")
        
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise TerraformInterpreterError("No content in Mistral API response")
        
        # Parse JSON response
        try:
            # Remove markdown code blocks if present
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            if content.startswith("```json"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            
            parsed_output = json.loads(content)
        except json.JSONDecodeError as error:
            raise TerraformInterpreterError(
                f"Failed to parse JSON response from Mistral: {str(error)}"
            ) from error
        
        # Validate schema
        self._validate_output_schema(parsed_output)
        
        return parsed_output
    
    def calculate_confidence_level(self, intent_graph: Dict[str, Any]) -> str:
        """
        Calculate overall confidence level based on resource confidence values.
        
        Args:
            intent_graph: Parsed intent graph from AI
        
        Returns:
            Overall confidence: "high", "medium", or "low"
        """
        resources = intent_graph.get("resources", [])
        if not resources:
            return "low"
        
        confidence_counts = {"high": 0, "medium": 0, "low": 0}
        
        for resource in resources:
            count_model = resource.get("count_model", {})
            confidence = count_model.get("confidence", "low")
            if confidence in confidence_counts:
                confidence_counts[confidence] += 1
        
        total = len(resources)
        high_ratio = confidence_counts["high"] / total
        medium_ratio = confidence_counts["medium"] / total
        
        if high_ratio >= 0.7:
            return "high"
        elif high_ratio + medium_ratio >= 0.7:
            return "medium"
        else:
            return "low"
