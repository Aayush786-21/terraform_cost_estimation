/**
 * Terraform Cost Estimation UI
 * Redesigned with calm, insight-first approach
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
                category: "compute",
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
                category: "compute",
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
                category: "database",
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

// Sample insights data
const SAMPLE_INSIGHTS = [
    {
        type: "high_cost_driver",
        title: "Compute resources dominate costs",
        description: "Your compute instances (EC2 and Azure VMs) account for approximately 89% of total estimated costs.",
        affected_resources: ["web", "database"],
        suggestions: [
            "Consider reviewing instance sizes - are current specifications necessary for your workload?",
            "Investigate spot instances or reserved capacity options for predictable workloads"
        ],
        disclaimer: "These are advisory suggestions. Actual savings depend on your specific use case."
    },
    {
        type: "general_best_practice",
        title: "Review unpriced resources",
        description: "Some resources in your configuration could not be priced. These may include additional costs not reflected in the estimate.",
        affected_resources: ["aws_cloudwatch_log_group", "gcp_compute_instance"],
        suggestions: [
            "Check cloud provider documentation for pricing on unpriced resources",
            "Consider contacting support for accurate pricing estimates"
        ],
        disclaimer: "Unpriced resources are excluded from the total estimate."
    }
];

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
 * Format percentage
 */
function formatPercentage(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'percent',
        minimumFractionDigits: 1,
        maximumFractionDigits: 1
    }).format(value);
}

/**
 * Get category display name
 */
function getCategoryName(category) {
    const names = {
        compute: "Compute",
        database: "Database",
        storage: "Storage",
        networking: "Networking",
        load_balancing: "Load Balancing",
        container: "Container",
        analytics: "Analytics",
        messaging: "Messaging",
        identity: "Identity",
        unknown: "Other"
    };
    return names[category] || "Other";
}

/**
 * Get category icon (simple text for now)
 */
function getCategoryIcon(category) {
    const icons = {
        compute: "⚡",
        database: "💾",
        storage: "📦",
        networking: "🌐",
        load_balancing: "⚖️",
        container: "📦",
        analytics: "📊",
        messaging: "💬",
        identity: "🔐",
        unknown: "❓"
    };
    return icons[category] || "❓";
}

/**
 * Calculate cost intensity level
 */
function getCostIntensityLevel(percentage) {
    if (percentage >= 50) return "high-impact";
    if (percentage >= 20) return "medium-impact";
    return "low-impact";
}

/**
 * Group line items by category
 */
function groupByCategory(lineItems) {
    const grouped = {};
    let totalCost = 0;
    
    lineItems.forEach(item => {
        if (!item.priced || item.monthly_cost_usd === 0) return;
        
        const category = item.category || "unknown";
        if (!grouped[category]) {
            grouped[category] = {
                category: category,
                items: [],
                totalCost: 0,
                resourceCount: 0
            };
        }
        
        grouped[category].items.push(item);
        grouped[category].totalCost += item.monthly_cost_usd || 0;
        grouped[category].resourceCount += 1;
        totalCost += item.monthly_cost_usd || 0;
    });
    
    // Calculate percentages
    Object.keys(grouped).forEach(category => {
        grouped[category].percentage = totalCost > 0 
            ? (grouped[category].totalCost / totalCost) * 100 
            : 0;
    });
    
    return { grouped, totalCost };
}

/**
 * Render cost driver cards
 */
function renderCostDrivers(lineItems, totalCost) {
    const container = document.getElementById('cost-drivers');
    if (!container) return;
    
    container.innerHTML = '';
    
    if (!lineItems || lineItems.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'cost-driver-card';
        empty.textContent = 'No cost data available';
        empty.style.textAlign = 'center';
        empty.style.color = '#9ca3af';
        container.appendChild(empty);
        return;
    }
    
    const { grouped } = groupByCategory(lineItems);
    const categories = Object.values(grouped).sort((a, b) => b.totalCost - a.totalCost);
    
    if (categories.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'cost-driver-card';
        empty.textContent = 'No priced resources found';
        empty.style.textAlign = 'center';
        empty.style.color = '#9ca3af';
        container.appendChild(empty);
        return;
    }
    
    categories.forEach(categoryData => {
        const card = document.createElement('div');
        card.className = `cost-driver-card ${getCostIntensityLevel(categoryData.percentage)}`;
        card.dataset.category = categoryData.category;
        
        const percentage = categoryData.percentage;
        const intensity = getCostIntensityLevel(percentage);
        card.style.setProperty('--cost-color', intensity === 'high-impact' 
            ? '#ef4444' 
            : intensity === 'medium-impact' 
                ? '#f59e0b' 
                : '#10b981');
        
        card.innerHTML = `
            <div class="cost-driver-header">
                <div>
                    <div class="cost-driver-name">${getCategoryIcon(categoryData.category)} ${getCategoryName(categoryData.category)}</div>
                    <div class="cost-driver-amount">${formatCurrency(categoryData.totalCost)}</div>
                </div>
                <div class="cost-driver-percentage">${formatPercentage(percentage / 100)}</div>
            </div>
            <div class="cost-driver-resources">
                ${categoryData.resourceCount} resource${categoryData.resourceCount !== 1 ? 's' : ''}
            </div>
        `;
        
        card.addEventListener('click', () => {
            // Toggle active state
            document.querySelectorAll('.cost-driver-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            
            // Expand breakdown and scroll to it
            const breakdownContent = document.getElementById('breakdown-content');
            const toggleButton = document.getElementById('toggle-breakdown');
            if (breakdownContent && toggleButton && breakdownContent.style.display === 'none') {
                breakdownContent.style.display = 'block';
                toggleButton.setAttribute('aria-expanded', 'true');
                toggleButton.querySelector('.button-text').textContent = 'Hide Details';
            }
            
            // Highlight category rows in table
            highlightCategoryInTable(categoryData.category);
        });
        
        container.appendChild(card);
    });
}

/**
 * Highlight category rows in table
 */
function highlightCategoryInTable(category) {
    const rows = document.querySelectorAll('.cost-table tbody tr');
    rows.forEach(row => {
        row.classList.remove('highlighted');
        const categoryCell = row.querySelector('[data-category]');
        if (categoryCell && categoryCell.dataset.category === category) {
            row.classList.add('highlighted');
            row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    });
    
    // Remove highlight after 3 seconds
    setTimeout(() => {
        rows.forEach(row => row.classList.remove('highlighted'));
    }, 3000);
}

/**
 * Render hero summary
 */
function renderSummary(estimate) {
    const totalCostEl = document.getElementById('total-cost');
    const regionEl = document.getElementById('region');
    const coverageBadgesEl = document.getElementById('coverage-badges');
    
    if (totalCostEl) {
        totalCostEl.textContent = formatCurrency(estimate.total_monthly_cost_usd);
    }
    
    if (regionEl) {
        regionEl.textContent = estimate.region;
    }
    
    if (coverageBadgesEl) {
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
    if (!tbody) return;
    
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
        
        // Add category data attribute for highlighting
        if (item.category) {
            row.querySelectorAll('td').forEach(cell => {
                cell.setAttribute('data-category', item.category);
            });
        }
        
        tbody.appendChild(row);
    });
}

/**
 * Render unpriced resources
 */
function renderUnpricedResources(unpricedResources) {
    const container = document.getElementById('unpriced-resources');
    if (!container) return;
    
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
 * Render insights
 */
function renderInsights(insights) {
    const container = document.getElementById('insights-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    if (!insights || insights.length === 0) {
        const empty = document.createElement('p');
        empty.textContent = 'No insights available.';
        empty.style.color = '#9ca3af';
        empty.style.fontStyle = 'italic';
        container.appendChild(empty);
        return;
    }
    
    insights.forEach(insight => {
        const card = document.createElement('div');
        card.className = 'insight-card';
        
        card.innerHTML = `
            <div class="insight-header">
                <div class="insight-title">${insight.title}</div>
                <span class="insight-type">${insight.type.replace(/_/g, ' ')}</span>
            </div>
            <div class="insight-description">${insight.description}</div>
            ${insight.affected_resources && insight.affected_resources.length > 0 ? `
                <div class="insight-resources">
                    <div class="insight-resources-label">Affected Resources:</div>
                    ${insight.affected_resources.map(resource => 
                        `<span class="insight-resource-tag">${resource}</span>`
                    ).join('')}
                </div>
            ` : ''}
            ${insight.suggestions && insight.suggestions.length > 0 ? `
                <div class="insight-suggestions">
                    <div class="insight-suggestions-title">Suggestions</div>
                    <ul class="insight-suggestions-list">
                        ${insight.suggestions.map(suggestion => 
                            `<li>${suggestion}</li>`
                        ).join('')}
                    </ul>
                </div>
            ` : ''}
            ${insight.disclaimer ? `
                <div class="insight-disclaimer">${insight.disclaimer}</div>
            ` : ''}
        `;
        
        container.appendChild(card);
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
    renderCostDrivers(estimate.line_items || [], estimate.total_monthly_cost_usd);
    renderCostTable(estimate.line_items || []);
    renderUnpricedResources(estimate.unpriced_resources || []);
    
    // Render insights if available
    if (estimateData.insights) {
        renderInsights(estimateData.insights);
    }
}

/**
 * Initialize expandable breakdown section
 */
function initBreakdownToggle() {
    const toggleButton = document.getElementById('toggle-breakdown');
    const breakdownContent = document.getElementById('breakdown-content');
    
    if (!toggleButton || !breakdownContent) return;
    
    toggleButton.addEventListener('click', () => {
        const isExpanded = toggleButton.getAttribute('aria-expanded') === 'true';
        
        if (isExpanded) {
            breakdownContent.style.display = 'none';
            toggleButton.setAttribute('aria-expanded', 'false');
            toggleButton.querySelector('.button-text').textContent = 'Show Details';
        } else {
            breakdownContent.style.display = 'block';
            toggleButton.setAttribute('aria-expanded', 'true');
            toggleButton.querySelector('.button-text').textContent = 'Hide Details';
        }
    });
}

/**
 * Get AI API key from input field
 * Never stored, never logged, only read when needed
 */
function getAIAPIKey() {
    const input = document.getElementById('ai-api-key');
    if (!input) return null;
    const key = input.value.trim();
    return key || null;
}

/**
 * Make API request with optional AI key header
 */
async function apiRequest(url, options = {}) {
    const headers = options.headers || {};
    
    // Add AI API key header if provided (only for AI endpoints)
    const aiKey = getAIAPIKey();
    if (aiKey && (url.includes('/interpret') || url.includes('/insights'))) {
        headers['X-AI-API-Key'] = aiKey;
    }
    
    return fetch(url, {
        ...options,
        headers: {
            ...headers,
            'Content-Type': 'application/json'
        }
    });
}

/**
 * Initialize app
 */
function init() {
    // Render with sample data on load
    const sampleData = {
        ...SAMPLE_ESTIMATE,
        insights: SAMPLE_INSIGHTS
    };
    renderEstimate(sampleData);
    
    // Initialize breakdown toggle
    initBreakdownToggle();
    
    // In the future, this could fetch from the API:
    // apiRequest('/api/terraform/estimate', { method: 'POST', ... })
    //   .then(res => res.json())
    //   .then(data => renderEstimate(data));
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}