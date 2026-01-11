/**
 * Terraform Cost Estimation UI
 * Renders cost estimates with heatmap visualization
 */

// Sample data for initial display
const SAMPLE_ESTIMATE = {
    status: "ok",
    estimate: {
        currency: "USD",
        total_monthly_cost_usd: 234.56,
        region: "ap-south-1",
        pricing_timestamp: "2024-01-01T12:00:00",
        coverage: {
            aws: "partial",
            azure: "full",
            gcp: "not_supported_yet"
        },
        line_items: [
            {
                cloud: "aws",
                service: "EC2",
                resource_name: "web",
                terraform_type: "aws_instance",
                region: "ap-south-1",
                monthly_cost_usd: 120.45,
                pricing_unit: "hour",
                assumptions: [
                    "730 hours/month",
                    "$0.0825/hour × 2 instances"
                ],
                priced: true,
                confidence: "medium"
            },
            {
                cloud: "azure",
                service: "Virtual Machines",
                resource_name: "database",
                terraform_type: "azurerm_virtual_machine",
                region: "eastus",
                monthly_cost_usd: 89.12,
                pricing_unit: "hour",
                assumptions: [
                    "730 hours/month",
                    "Standard_B2s SKU"
                ],
                priced: true,
                confidence: "high"
            },
            {
                cloud: "aws",
                service: "RDS",
                resource_name: "db",
                terraform_type: "aws_db_instance",
                region: "ap-south-1",
                monthly_cost_usd: 24.99,
                pricing_unit: "hour",
                assumptions: [
                    "730 hours/month",
                    "db.t3.micro instance"
                ],
                priced: true,
                confidence: "high"
            }
        ],
        unpriced_resources: [
            {
                resource_name: "aws_cloudwatch_log_group",
                terraform_type: "aws_cloudwatch_log_group",
                reason: "Pricing not available for this resource type"
            },
            {
                resource_name: "gcp_compute_instance",
                terraform_type: "google_compute_instance",
                reason: "GCP pricing not fully implemented"
            }
        ]
    }
};

/**
 * Format currency value
 */
function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

/**
 * Render summary panel
 */
function renderSummary(estimate) {
    const totalCostEl = document.getElementById('total-cost');
    const regionEl = document.getElementById('region');
    const coverageBadgesEl = document.getElementById('coverage-badges');
    
    totalCostEl.textContent = formatCurrency(estimate.total_monthly_cost_usd);
    regionEl.textContent = estimate.region;
    
    // Render coverage badges
    coverageBadgesEl.innerHTML = '';
    const coverage = estimate.coverage || {};
    
    const clouds = [
        { name: 'aws', label: 'AWS' },
        { name: 'azure', label: 'Azure' },
        { name: 'gcp', label: 'GCP' }
    ];
    
    clouds.forEach(cloud => {
        const status = coverage[cloud.name] || 'unknown';
        const badge = document.createElement('span');
        badge.className = `coverage-badge ${status.replace('_', '-')}`;
        badge.textContent = `${cloud.label}: ${status.replace('_', ' ')}`;
        coverageBadgesEl.appendChild(badge);
    });
}

/**
 * Calculate cost heatmap intensity (0-1)
 */
function calculateCostIntensity(cost, maxCost) {
    if (cost === 0 || maxCost === 0) return 0;
    return cost / maxCost;
}

/**
 * Get cost row class based on intensity
 */
function getCostRowClass(intensity) {
    if (intensity === 0) return 'zero-cost';
    if (intensity >= 0.7) return 'high-cost';
    if (intensity >= 0.3) return 'medium-cost';
    return 'low-cost';
}

/**
 * Render confidence indicator
 */
function renderConfidence(confidence) {
    const indicator = document.createElement('span');
    indicator.className = `confidence-indicator ${confidence}`;
    
    const cell = document.createElement('div');
    cell.className = 'confidence-cell';
    cell.appendChild(indicator);
    cell.appendChild(document.createTextNode(confidence));
    
    return cell;
}

/**
 * Render cloud badge
 */
function renderCloudBadge(cloud) {
    const badge = document.createElement('span');
    badge.className = `cloud-badge ${cloud}`;
    badge.textContent = cloud.toUpperCase();
    return badge;
}

/**
 * Render assumptions list
 */
function renderAssumptions(assumptions) {
    if (!assumptions || assumptions.length === 0) {
        const empty = document.createElement('span');
        empty.className = 'assumptions-empty';
        empty.textContent = 'No assumptions';
        return empty;
    }
    
    const list = document.createElement('ul');
    list.className = 'assumptions-list';
    
    assumptions.forEach(assumption => {
        const item = document.createElement('li');
        item.textContent = assumption;
        list.appendChild(item);
    });
    
    return list;
}

/**
 * Render cost table
 */
function renderCostTable(lineItems) {
    const tbody = document.getElementById('cost-table-body');
    tbody.innerHTML = '';
    
    if (!lineItems || lineItems.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 7;
        cell.textContent = 'No cost line items available';
        cell.style.textAlign = 'center';
        cell.style.color = '#9ca3af';
        row.appendChild(cell);
        tbody.appendChild(row);
        return;
    }
    
    // Find max cost for heatmap scaling
    const maxCost = Math.max(...lineItems.map(item => item.monthly_cost_usd || 0));
    
    lineItems.forEach(item => {
        const row = document.createElement('tr');
        const intensity = calculateCostIntensity(item.monthly_cost_usd, maxCost);
        row.className = `cost-row ${getCostRowClass(intensity)}`;
        
        // Cloud
        const cloudCell = document.createElement('td');
        cloudCell.appendChild(renderCloudBadge(item.cloud || 'unknown'));
        row.appendChild(cloudCell);
        
        // Service
        const serviceCell = document.createElement('td');
        serviceCell.textContent = item.service || '-';
        row.appendChild(serviceCell);
        
        // Resource Name
        const nameCell = document.createElement('td');
        nameCell.textContent = item.resource_name || '-';
        row.appendChild(nameCell);
        
        // Region
        const regionCell = document.createElement('td');
        regionCell.textContent = item.region || '-';
        row.appendChild(regionCell);
        
        // Monthly Cost
        const costCell = document.createElement('td');
        costCell.className = 'cost-value';
        if (item.monthly_cost_usd === 0) {
            costCell.classList.add('zero');
        }
        costCell.textContent = formatCurrency(item.monthly_cost_usd || 0);
        row.appendChild(costCell);
        
        // Confidence
        const confidenceCell = document.createElement('td');
        confidenceCell.appendChild(renderConfidence(item.confidence || 'low'));
        row.appendChild(confidenceCell);
        
        // Assumptions
        const assumptionsCell = document.createElement('td');
        assumptionsCell.appendChild(renderAssumptions(item.assumptions));
        row.appendChild(assumptionsCell);
        
        tbody.appendChild(row);
    });
}

/**
 * Render unpriced resources
 */
function renderUnpricedResources(unpricedResources) {
    const container = document.getElementById('unpriced-resources');
    container.innerHTML = '';
    
    if (!unpricedResources || unpricedResources.length === 0) {
        const empty = document.createElement('p');
        empty.textContent = 'All resources were successfully priced.';
        empty.style.color = '#9ca3af';
        empty.style.fontStyle = 'italic';
        container.appendChild(empty);
        return;
    }
    
    unpricedResources.forEach(resource => {
        const item = document.createElement('div');
        item.className = 'unpriced-item';
        
        const header = document.createElement('div');
        header.className = 'unpriced-item-header';
        
        const name = document.createElement('span');
        name.className = 'unpriced-resource-name';
        name.textContent = resource.resource_name || 'Unknown';
        
        const type = document.createElement('span');
        type.className = 'unpriced-terraform-type';
        type.textContent = resource.terraform_type || 'unknown';
        
        header.appendChild(name);
        header.appendChild(type);
        
        const reason = document.createElement('div');
        reason.className = 'unpriced-reason';
        reason.textContent = resource.reason || 'No reason provided';
        
        item.appendChild(header);
        item.appendChild(reason);
        container.appendChild(item);
    });
}

/**
 * Render full estimate
 */
function renderEstimate(estimateData) {
    if (!estimateData || !estimateData.estimate) {
        console.error('Invalid estimate data');
        return;
    }
    
    const estimate = estimateData.estimate;
    
    renderSummary(estimate);
    renderCostTable(estimate.line_items || []);
    renderUnpricedResources(estimate.unpriced_resources || []);
}

/**
 * Initialize app
 */
function init() {
    // Render with sample data on load
    renderEstimate(SAMPLE_ESTIMATE);
    
    // In the future, this could fetch from the API:
    // fetch('/api/terraform/estimate', { method: 'POST', ... })
    //   .then(res => res.json())
    //   .then(data => renderEstimate(data));
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
