"""
Test for local Terraform estimation endpoint.
Verifies that the endpoint handles errors gracefully and doesn't return 500 for expected failures.
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture
def client():
    """Test client for FastAPI app."""
    return TestClient(app)


@pytest.fixture
def sample_terraform():
    """Sample Terraform code for testing."""
    return 'resource "aws_instance" "web" { instance_type = "t3.micro" }'


@pytest.mark.asyncio
async def test_local_estimate_returns_200_with_valid_terraform(client, sample_terraform):
    """Local estimate endpoint returns 200 OK with valid Terraform input."""
    # Mock the TerraformInterpreter to avoid requiring actual AI API
    with patch('backend.api.terraform.TerraformInterpreter') as mock_interpreter_class:
        mock_interpreter = Mock()
        mock_interpreter.interpret = AsyncMock(return_value={
            "providers": ["aws"],
            "resources": [{
                "cloud": "aws",
                "category": "compute",
                "service": "EC2",
                "terraform_type": "aws_instance",
                "name": "web",
                "file": "main.tf",
                "region": {"source": "provider_default", "value": None},
                "count_model": {"type": "fixed", "value": 1, "confidence": "high"},
                "size": {"instance_type": "t3.micro"},
                "usage": {"hours_per_month": 730},
                "unresolved_inputs": []
            }],
            "summary": {"total_resources": 1, "has_autoscaling": False, "has_unknowns": False}
        })
        mock_interpreter_class.return_value = mock_interpreter
        
        # Mock CostEstimator
        with patch('backend.api.terraform.CostEstimator') as mock_estimator_class:
            from backend.domain.cost_models import CostEstimate, CostLineItem, UnpricedResource
            from datetime import datetime
            
            mock_estimator = Mock()
            mock_estimate = CostEstimate(
                currency="USD",
                total_monthly_cost_usd=10.0,
                line_items=[],
                unpriced_resources=[
                    UnpricedResource(
                        resource_name="web",
                        terraform_type="aws_instance",
                        reason="Pricing not available for this resource type"
                    )
                ],
                region="us-east-1",
                pricing_timestamp=datetime.now(),
                coverage={"aws": "partial", "azure": "partial", "gcp": "not_supported_yet"}
            )
            mock_estimator.estimate = AsyncMock(return_value=mock_estimate)
            mock_estimator_class.return_value = mock_estimator
            
            # Mock CostInsightsService to avoid AttributeError
            with patch('backend.api.terraform.CostInsightsService') as mock_insights_class:
                from backend.domain.insight_models import InsightResponse, Insight, AffectedResource
                
                mock_insights = Mock()
                mock_insights.generate_insights_from_dicts = AsyncMock(return_value=InsightResponse(
                    insights=[
                        Insight(
                            type="unpriced_resource",
                            title="Test insight",
                            description="Test description",
                            affected_resources=[AffectedResource(resource_name="web", terraform_type="aws_instance")],
                            confidence="low",
                            assumptions_referenced=[],
                            suggestions=[],
                            disclaimer="Test disclaimer"
                        )
                    ]
                ))
                mock_insights_class.return_value = mock_insights
                
                # Make request
                response = client.post(
                    "/api/terraform/estimate/local",
                    data={"terraform_text": sample_terraform},
                    headers={"Content-Type": "multipart/form-data"}
                )
                
                # Verify response
                assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
                data = response.json()
                assert data["status"] == "ok"
                assert "estimate" in data
                assert "intent_graph" in data
                assert "insights" in data


def test_local_estimate_handles_missing_input(client):
    """Local estimate endpoint returns 400 for missing input."""
    response = client.post("/api/terraform/estimate/local")
    
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data


def test_insights_service_handles_dict_input():
    """CostInsightsService.generate_insights_from_dicts works with dict input."""
    from backend.services.cost_insights import CostInsightsService
    from unittest.mock import Mock, AsyncMock
    
    # Create service with mocked Mistral client
    mock_mistral = Mock()
    mock_mistral.chat_completion = AsyncMock(return_value={
        "choices": [{
            "message": {
                "content": '{"insights": []}'
            }
        }]
    })
    
    service = CostInsightsService(mistral_client=mock_mistral)
    
    # Test that _extract_resource_summary_from_dict exists and works
    estimate_dict = {
        "line_items": [
            {
                "resource_name": "web",
                "terraform_type": "aws_instance",
                "cloud": "aws",
                "service": "EC2",
                "region": "us-east-1",
                "monthly_cost_usd": 10.0,
                "confidence": "high",
                "assumptions": []
            }
        ],
        "total_monthly_cost_usd": 10.0,
        "region": "us-east-1",
        "unpriced_resources": []
    }
    
    # This should not raise AttributeError
    resources = service._extract_resource_summary_from_dict(estimate_dict)
    assert isinstance(resources, list)
    assert len(resources) == 1
    assert resources[0]["resource_name"] == "web"
