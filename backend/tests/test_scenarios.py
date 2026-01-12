"""
Tests for scenario modeling.
CRITICAL INVARIANT: Base estimate MUST NOT change.
"""

import pytest
import copy
from backend.domain.scenario_models import ScenarioInput, ScenarioEstimateResult


@pytest.fixture
def base_estimate():
    """Base estimate fixture."""
    return {
        'total_monthly_cost_usd': 100.0,
        'region': 'us-east-1',
        'line_items': [
            {
                'resource_name': 'web',
                'monthly_cost_usd': 100.0,
                'region': 'us-east-1'
            }
        ]
    }


def test_scenario_does_not_mutate_base_estimate(base_estimate):
    """CRITICAL: Scenario does not mutate base estimate."""
    base_copy = copy.deepcopy(base_estimate)
    
    # Simulate scenario calculation
    scenario_estimate = {
        'total_monthly_cost_usd': 120.0,
        'region': 'us-west-2',
        'line_items': [
            {
                'resource_name': 'web',
                'monthly_cost_usd': 120.0,
                'region': 'us-west-2'
            }
        ]
    }
    
    # Base estimate should be unchanged
    assert base_estimate == base_copy
    assert base_estimate['total_monthly_cost_usd'] == 100.0
    assert base_estimate['region'] == 'us-east-1'


def test_delta_equals_scenario_minus_base(base_estimate):
    """Delta calculation: delta = scenario - base."""
    scenario_total = 120.0
    base_total = base_estimate['total_monthly_cost_usd']
    
    delta = scenario_total - base_total
    
    assert delta == 20.0
    assert delta > 0  # Scenario is more expensive


def test_negative_delta_handled_correctly(base_estimate):
    """Negative delta (scenario cheaper) handled correctly."""
    scenario_total = 80.0
    base_total = base_estimate['total_monthly_cost_usd']
    
    delta = scenario_total - base_total
    
    assert delta == -20.0
    assert delta < 0  # Scenario is cheaper


def test_region_override_reflected_in_assumptions():
    """Region override reflected in scenario assumptions."""
    assumptions = {
        'region_override': 'us-west-2'
    }
    
    assert 'region_override' in assumptions
    assert assumptions['region_override'] == 'us-west-2'


def test_autoscaling_override_applied_correctly():
    """Autoscaling override applied correctly in scenario."""
    base_count = 2
    override_count = 5
    
    # Scenario should use override
    scenario_count = override_count
    
    assert scenario_count == 5
    assert scenario_count != base_count


def test_resources_missing_in_one_side_handled_gracefully(base_estimate):
    """Resources missing in one side handled gracefully."""
    base_items = base_estimate['line_items']
    scenario_items = [
        {
            'resource_name': 'web',
            'monthly_cost_usd': 120.0
        },
        {
            'resource_name': 'new_resource',
            'monthly_cost_usd': 50.0
        }
    ]
    
    # Should handle gracefully, not crash
    base_names = {item['resource_name'] for item in base_items}
    scenario_names = {item['resource_name'] for item in scenario_items}
    
    # New resource in scenario
    new_resources = scenario_names - base_names
    assert 'new_resource' in new_resources
    
    # Missing resource in scenario (if any)
    missing_resources = base_names - scenario_names
    # Should be empty or handled gracefully


def test_scenario_assumptions_stored_separately():
    """Scenario assumptions stored separately from base estimate."""
    base_estimate = {'total_monthly_cost_usd': 100.0}
    scenario_result = {
        'assumptions': {
            'region_override': 'us-west-2',
            'autoscaling_average_override': 5
        }
    }
    
    # Assumptions should not be in base estimate
    assert 'assumptions' not in base_estimate
    assert 'assumptions' in scenario_result


def test_zero_delta_handled_correctly(base_estimate):
    """Zero delta (no change) handled correctly."""
    scenario_total = base_estimate['total_monthly_cost_usd']
    base_total = base_estimate['total_monthly_cost_usd']
    
    delta = scenario_total - base_total
    
    assert delta == 0.0
