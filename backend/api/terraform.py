"""
API routes for Terraform file operations.
"""
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
import httpx

from backend.services.github_client import GitHubClient
from backend.services.terraform_interpreter import TerraformInterpreter, TerraformInterpreterError
from backend.services.cost_estimator import CostEstimator, CostEstimatorError
from backend.services.cost_insights import CostInsightsService, CostInsightsError
from backend.services.mistral_client import MistralAPIError
from backend.domain.scenario_models import ScenarioInput
from backend.domain.cost_models import CostEstimate
from backend.domain.scenario_models import ScenarioEstimateResult
from backend.utils.fs import extract_and_scan_terraform_files


router = APIRouter()


class TerraformFilesRequest(BaseModel):
    """Request model for fetching Terraform files from a repository."""
    owner: str = Field(..., description="Repository owner (username or organization)")
    repo: str = Field(..., description="Repository name")
    branch: str = Field(default="main", description="Branch name (default: main)")


class TerraformFile(BaseModel):
    """Model for a single Terraform file."""
    path: str = Field(..., description="File path relative to repository root")
    content: str = Field(..., description="Raw Terraform file content")


class TerraformInterpretRequest(BaseModel):
    """Request model for interpreting Terraform files."""
    files: List[TerraformFile] = Field(..., description="List of Terraform files to interpret")


class CostEstimateScenario(BaseModel):
    """Scenario parameters for cost estimation."""
    autoscaling_average_override: Optional[int] = Field(None, description="Override for autoscaling average count")


class TerraformEstimateRequest(BaseModel):
    """Request model for cost estimation."""
    intent_graph: Dict[str, Any] = Field(..., description="Intent graph from Terraform interpretation")
    region_override: Optional[str] = Field(None, description="Optional region override for pricing")
    scenario: Optional[CostEstimateScenario] = Field(None, description="Optional scenario parameters")


class ScenarioModelRequest(BaseModel):
    """Request model for scenario modeling."""
    intent_graph: Dict[str, Any] = Field(..., description="Intent graph from Terraform interpretation")
    scenario: Dict[str, Any] = Field(..., description="Scenario input parameters")


class InsightsRequest(BaseModel):
    """Request model for cost insights."""
    intent_graph: Dict[str, Any] = Field(..., description="Intent graph from Terraform interpretation")
    base_estimate: Dict[str, Any] = Field(..., description="Base cost estimate")
    scenario_result: Optional[Dict[str, Any]] = Field(None, description="Optional scenario comparison result")


def get_access_token_from_session(request: Request) -> str:
    """
    Extract GitHub access token from session.
    
    Validates session expiry and extends idle timeout if valid.
    
    Args:
        request: FastAPI request object
    
    Returns:
        GitHub access token string
    
    Raises:
        HTTPException: If session is missing, expired, or token is not found
    """
    from backend.auth.session_utils import get_access_token_from_session as get_token
    session = request.session
    token = get_token(session)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please sign in again."
        )
    return token


@router.post("/api/terraform/files")
async def get_terraform_files(
    request: Request,
    file_request: TerraformFilesRequest
) -> Dict[str, Any]:
    """
    Fetch all Terraform files from a GitHub repository.
    
    Downloads the repository archive for the specified branch,
    extracts it, scans for .tf files, and returns their paths and contents.
    
    Requires authentication via GitHub OAuth.
    
    Args:
        request: FastAPI request object
        file_request: Request body with owner, repo, and branch
    
    Returns:
        JSON response with Terraform files and metadata
    
    Raises:
        HTTPException: If authentication fails, repo/branch not found,
                       no Terraform files found, or other errors occur
    """
    try:
        # Validate input
        if not file_request.owner or not file_request.repo:
            raise HTTPException(
                status_code=400,
                detail="Owner and repo are required"
            )
        
        if not file_request.branch:
            raise HTTPException(
                status_code=400,
                detail="Branch is required"
            )
        
        # Authenticate and get token
        access_token = get_access_token_from_session(request)
        github_client = GitHubClient(access_token)
        
        # Download repository archive
        try:
            archive_data = await github_client.download_repository_archive(
                owner=file_request.owner,
                repo=file_request.repo,
                ref=file_request.branch
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Repository {file_request.owner}/{file_request.repo} or branch '{file_request.branch}' not found"
                ) from error
            raise HTTPException(
                status_code=error.response.status_code,
                detail="Failed to download repository archive"
            ) from error
        
        # Extract and scan for Terraform files
        try:
            terraform_files = extract_and_scan_terraform_files(
                zip_data=archive_data,
                owner=file_request.owner,
                repo=file_request.repo
            )
        except ValueError as error:
            # No Terraform files found
            if "No Terraform files found" in str(error):
                raise HTTPException(
                    status_code=404,
                    detail=str(error)
                ) from error
            raise HTTPException(
                status_code=400,
                detail=str(error)
            ) from error
        
        # Build response
        return {
            "status": "ok",
            "repo": f"{file_request.owner}/{file_request.repo}",
            "branch": file_request.branch,
            "terraform_file_count": len(terraform_files),
            "files": terraform_files,
        }
    
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503,
            detail="Failed to connect to GitHub API"
        ) from error
    except Exception as error:
        # Log error in production, but don't expose details to client
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while fetching Terraform files"
        ) from error


@router.post("/api/terraform/interpret")
async def interpret_terraform_files(
    request: Request,
    interpret_request: TerraformInterpretRequest
) -> Dict[str, Any]:
    """
    Interpret Terraform files into structured cost-intent representation.
    
    Uses Mistral AI to analyze Terraform resources and extract structured
    information including cloud provider, service type, resource counts,
    and usage dimensions. Does NOT calculate prices.
    
    Requires authentication via GitHub OAuth.
    
    Args:
        request: FastAPI request object
        interpret_request: Request body with list of Terraform files
    
    Returns:
        JSON response with intent graph and confidence level
    
    Raises:
        HTTPException: If authentication fails, invalid input,
                       Mistral API fails, or other errors occur
    """
    try:
        # Authenticate
        get_access_token_from_session(request)
        
        # Validate input
        if not interpret_request.files:
            raise HTTPException(
                status_code=400,
                detail="At least one Terraform file is required"
            )
        
        # Convert Pydantic models to dicts for interpreter
        terraform_files = [
            {"path": file.path, "content": file.content}
            for file in interpret_request.files
        ]
        
        # Initialize interpreter and interpret
        interpreter = TerraformInterpreter()
        try:
            intent_graph = await interpreter.interpret(terraform_files)
        except TerraformInterpreterError as error:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to interpret Terraform files: {str(error)}"
            ) from error
        except MistralAPIError as error:
            raise HTTPException(
                status_code=502,
                detail="Mistral AI service unavailable"
            ) from error
        
        # Calculate overall confidence level
        confidence_level = interpreter.calculate_confidence_level(intent_graph)
        
        # Build response
        return {
            "status": "ok",
            "intent_graph": intent_graph,
            "confidence_level": confidence_level,
        }
    
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as error:
        # Log error in production, but don't expose details to client
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while interpreting Terraform files"
        ) from error


@router.post("/api/terraform/estimate")
async def estimate_terraform_costs(
    request: Request,
    estimate_request: TerraformEstimateRequest
) -> Dict[str, Any]:
    """
    Estimate costs from Terraform intent graph.
    
    Uses official cloud pricing APIs (AWS, Azure, GCP) to calculate
    monthly costs for resources in the intent graph.
    
    Requires authentication via GitHub OAuth.
    
    Args:
        request: FastAPI request object
        estimate_request: Request body with intent graph and optional overrides
    
    Returns:
        JSON response with cost estimate and line items
    
    Raises:
        HTTPException: If authentication fails, invalid input,
                       pricing API fails, or other errors occur
    """
    try:
        # Authenticate
        get_access_token_from_session(request)
        
        # Validate input
        intent_graph = estimate_request.intent_graph
        if not intent_graph:
            raise HTTPException(
                status_code=400,
                detail="Intent graph is required"
            )
        
        if "resources" not in intent_graph:
            raise HTTPException(
                status_code=422,
                detail="Intent graph must contain 'resources' field"
            )
        
        # Extract scenario parameters
        scenario = estimate_request.scenario
        autoscaling_average_override = None
        if scenario:
            autoscaling_average_override = scenario.autoscaling_average_override
        
        # Initialize estimator and estimate costs
        estimator = CostEstimator()
        try:
            cost_estimate = await estimator.estimate(
                intent_graph=intent_graph,
                region_override=estimate_request.region_override,
                autoscaling_average_override=autoscaling_average_override
            )
        except CostEstimatorError as error:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to estimate costs: {str(error)}"
            ) from error
        
        # Build response
        return {
            "status": "ok",
            "estimate": cost_estimate.to_dict()
        }
    
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as error:
        # Log error in production, but don't expose details to client
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while estimating costs"
        ) from error


@router.post("/api/terraform/estimate/scenario")
async def estimate_scenario(
    request: Request,
    scenario_request: ScenarioModelRequest
) -> Dict[str, Any]:
    """
    Estimate costs with scenario modeling and delta comparison.
    
    Runs base estimate, then scenario estimate with overrides,
    and calculates deltas between them.
    
    Supports:
    - Region override (compare costs in different regions)
    - Autoscaling average override (compare with different scaling assumptions)
    - Users override (for request-based services, placeholder for now)
    
    Requires authentication via GitHub OAuth.
    
    Args:
        request: FastAPI request object
        scenario_request: Request body with intent graph and scenario parameters
    
    Returns:
        JSON response with base estimate, scenario estimate, and deltas
    
    Raises:
        HTTPException: If authentication fails, invalid input,
                       pricing API fails, or other errors occur
    """
    try:
        # Authenticate
        get_access_token_from_session(request)
        
        # Validate input
        intent_graph = scenario_request.intent_graph
        if not intent_graph:
            raise HTTPException(
                status_code=400,
                detail="Intent graph is required"
            )
        
        if "resources" not in intent_graph:
            raise HTTPException(
                status_code=422,
                detail="Intent graph must contain 'resources' field"
            )
        
        scenario_dict = scenario_request.scenario
        if not scenario_dict:
            raise HTTPException(
                status_code=400,
                detail="Scenario parameters are required"
            )
        
        # Build ScenarioInput from request
        try:
            scenario_input = ScenarioInput(
                region_override=scenario_dict.get("region_override"),
                autoscaling_average_override=scenario_dict.get("autoscaling_average_override"),
                users=scenario_dict.get("users")
            )
        except (TypeError, ValueError) as error:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scenario parameters: {str(error)}"
            ) from error
        
        # Validate scenario inputs
        if scenario_input.autoscaling_average_override is not None:
            if scenario_input.autoscaling_average_override < 0:
                raise HTTPException(
                    status_code=422,
                    detail="Autoscaling average override must be non-negative"
                )
        
        if scenario_input.users is not None:
            if scenario_input.users < 0:
                raise HTTPException(
                    status_code=422,
                    detail="Users must be non-negative"
                )
        
        # Initialize estimator and run scenario estimation
        estimator = CostEstimator()
        try:
            scenario_result = await estimator.estimate_with_scenario(
                intent_graph=intent_graph,
                scenario_input=scenario_input
            )
        except CostEstimatorError as error:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to estimate scenario: {str(error)}"
            ) from error
        
        # Build response
        return {
            "status": "ok",
            "scenario_result": scenario_result.to_dict()
        }
    
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as error:
        # Log error in production, but don't expose details to client
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while estimating scenario"
        ) from error


@router.post("/api/terraform/insights")
async def generate_cost_insights(
    request: Request,
    insights_request: InsightsRequest
) -> Dict[str, Any]:
    """
    Generate AI-powered cost insights and optimization suggestions.
    
    Uses Mistral AI to analyze cost estimates and provide advisory insights.
    This is advisory-only and NEVER modifies cost estimates or calculations.
    
    Supports:
    - High cost driver identification
    - Region comparison insights (if scenario provided)
    - Scaling assumption analysis
    - Unpriced resource warnings
    - Missing input identification
    - General best practice suggestions
    
    Requires authentication via GitHub OAuth.
    
    Args:
        request: FastAPI request object
        insights_request: Request body with intent graph, base estimate, and optional scenario
    
    Returns:
        JSON response with cost insights
    
    Raises:
        HTTPException: If authentication fails, invalid input,
                       Mistral API fails, or other errors occur
    """
    try:
        # Authenticate
        get_access_token_from_session(request)
        
        # Validate input
        intent_graph = insights_request.intent_graph
        if not intent_graph:
            raise HTTPException(
                status_code=400,
                detail="Intent graph is required"
            )
        
        base_estimate_dict = insights_request.base_estimate
        if not base_estimate_dict:
            raise HTTPException(
                status_code=400,
                detail="Base estimate is required"
            )
        
        # Parse scenario result if provided
        scenario_result = None
        if insights_request.scenario_result:
            scenario_result = insights_request.scenario_result
        
        # Generate insights using dict-based method
        insights_service = CostInsightsService()
        try:
            insight_response = await insights_service.generate_insights_from_dicts(
                intent_graph=intent_graph,
                base_estimate_dict=base_estimate_dict,
                scenario_result_dict=scenario_result
            )
        except CostInsightsError as error:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to generate insights: {str(error)}"
            ) from error
        except MistralAPIError as error:
            raise HTTPException(
                status_code=502,
                detail="Mistral AI service unavailable"
            ) from error
        
        # Build response
        return {
            "status": "ok",
            "insights": insight_response.to_dict()["insights"]
        }
    
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as error:
        # Log error in production, but don't expose details to client
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while generating insights"
        ) from error
