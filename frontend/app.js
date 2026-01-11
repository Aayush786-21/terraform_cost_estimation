/**
 * Terraform Cost Estimation UI
 * Redesigned with calm, insight-first approach
 */

// Global state for estimates and scenarios
let baseEstimate = null;
let currentScenario = null;
let currentIntentGraph = null;

// Common regions for comparison
const COMMON_REGIONS = [
    { code: 'us-east-1', name: 'US East (N. Virginia)' },
    { code: 'us-west-2', name: 'US West (Oregon)' },
    { code: 'eu-west-1', name: 'Europe (Ireland)' },
    { code: 'ap-south-1', name: 'Asia Pacific (Mumbai)' },
    { code: 'ap-southeast-1', name: 'Asia Pacific (Singapore)' },
];

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
function renderCostDrivers(lineItems, totalCost, scenarioDeltas = null) {
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
    
    // Calculate category deltas if scenario is active
    const categoryDeltas = scenarioDeltas ? calculateCategoryDeltas(lineItems, scenarioDeltas) : null;
    
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
        
        // Get delta for this category if scenario is active
        const categoryDelta = categoryDeltas && categoryDeltas[categoryData.category] 
            ? categoryDeltas[categoryData.category] 
            : null;
        
        card.innerHTML = `
            <div class="cost-driver-header">
                <div>
                    <div class="cost-driver-name">${getCategoryIcon(categoryData.category)} ${getCategoryName(categoryData.category)}</div>
                    <div class="cost-driver-amount">
                        ${formatCurrency(categoryData.totalCost)}
                        ${categoryDelta ? renderDeltaIndicator(categoryDelta.deltaUsd, categoryDelta.deltaPercent, 'small') : ''}
                    </div>
                </div>
                <div class="cost-driver-percentage">${formatPercentage(percentage / 100)}</div>
            </div>
            <div class="cost-driver-resources">
                ${categoryData.resourceCount} resource${categoryData.resourceCount !== 1 ? 's' : ''}
            </div>
            ${categoryData.category === 'compute' ? `
                <div class="autoscaling-control">
                    <label class="autoscaling-label">Average instances (assumption)</label>
                    <div class="autoscaling-input-group">
                        <input 
                            type="number" 
                            class="autoscaling-input" 
                            id="autoscaling-${categoryData.category}"
                            placeholder="Auto-detected"
                            min="0"
                            step="1"
                        />
                    </div>
                    <span class="autoscaling-helper">Used for estimation only</span>
                    <button class="apply-scenario-btn" data-scenario-type="autoscaling" data-category="${categoryData.category}">
                        Apply Scenario
                    </button>
                </div>
            ` : ''}
        `;
        
        card.addEventListener('click', (e) => {
            // Don't toggle if clicking on input or button
            if (e.target.closest('.autoscaling-control')) return;
            
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
        
        // Add event listener for apply scenario button
        const applyBtn = card.querySelector('.apply-scenario-btn');
        if (applyBtn) {
            applyBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const category = e.target.dataset.category;
                const input = card.querySelector(`#autoscaling-${category}`);
                const value = parseInt(input.value, 10);
                if (!isNaN(value) && value >= 0) {
                    await applyScenario({ autoscaling_average_override: value });
                }
            });
        }
        
        container.appendChild(card);
    });
}

/**
 * Calculate category deltas from scenario deltas
 */
function calculateCategoryDeltas(lineItems, deltas) {
    const categoryDeltas = {};
    const deltaMap = new Map();
    
    deltas.forEach(delta => {
        deltaMap.set(delta.resource_name, delta);
    });
    
    lineItems.forEach(item => {
        if (!item.category) return;
        const delta = deltaMap.get(item.resource_name);
        if (!delta) return;
        
        if (!categoryDeltas[item.category]) {
            categoryDeltas[item.category] = {
                deltaUsd: 0,
                baseCost: 0,
                scenarioCost: 0
            };
        }
        
        categoryDeltas[item.category].deltaUsd += delta.delta_usd || 0;
        categoryDeltas[item.category].baseCost += delta.base_monthly_cost_usd || 0;
        categoryDeltas[item.category].scenarioCost += delta.scenario_monthly_cost_usd || 0;
    });
    
    // Calculate percentages
    Object.keys(categoryDeltas).forEach(category => {
        const data = categoryDeltas[category];
        data.deltaPercent = data.baseCost > 0 
            ? (data.deltaUsd / data.baseCost) * 100 
            : null;
    });
    
    return categoryDeltas;
}

/**
 * Render delta indicator
 */
function renderDeltaIndicator(deltaUsd, deltaPercent, size = 'normal') {
    if (deltaUsd === 0) return '';
    
    const isPositive = deltaUsd > 0;
    const sign = isPositive ? '+' : '';
    const percentStr = deltaPercent !== null && deltaPercent !== undefined
        ? ` (${sign}${formatPercentage(deltaPercent / 100)})`
        : '';
    const sizeClass = size === 'small' ? 'small' : '';
    
    return `<span class="delta-indicator ${isPositive ? 'positive' : 'negative'} ${sizeClass}">${sign}${formatCurrency(deltaUsd)}${percentStr}</span>`;
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
function renderSummary(estimate, scenario = null) {
    const totalCostEl = document.getElementById('total-cost');
    const regionEl = document.getElementById('region');
    const coverageBadgesEl = document.getElementById('coverage-badges');
    
    if (totalCostEl) {
        // Clear any existing delta badges
        const existingDelta = totalCostEl.querySelector('.scenario-delta-badge');
        if (existingDelta) existingDelta.remove();
        
        totalCostEl.textContent = formatCurrency(estimate.total_monthly_cost_usd);
        
        // Show delta if scenario is active
        if (scenario && baseEstimate) {
            const delta = estimate.total_monthly_cost_usd - baseEstimate.total_monthly_cost_usd;
            const deltaPercent = baseEstimate.total_monthly_cost_usd > 0 
                ? (delta / baseEstimate.total_monthly_cost_usd) * 100 
                : null;
            const deltaEl = document.createElement('span');
            deltaEl.className = 'scenario-delta-badge';
            deltaEl.innerHTML = renderDeltaIndicator(delta, deltaPercent);
            totalCostEl.appendChild(deltaEl);
        }
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
 * Render scenario comparison section
 */
function renderScenarioComparison(estimateData) {
    const section = document.getElementById('scenario-comparison-section');
    if (!section) return;
    
    const scenarioResult = estimateData.scenario_result;
    if (!scenarioResult) return;
    
    section.style.display = 'block';
    
    const baseCostEl = document.getElementById('base-cost');
    const scenarioCostEl = document.getElementById('scenario-cost');
    const baseRegionEl = document.getElementById('base-region');
    const scenarioRegionEl = document.getElementById('scenario-region');
    const deltaEl = document.getElementById('scenario-delta');
    
    const baseEst = scenarioResult.base_estimate;
    const scenarioEst = scenarioResult.scenario_estimate;
    
    if (baseCostEl) {
        baseCostEl.textContent = formatCurrency(baseEst.total_monthly_cost_usd);
    }
    
    if (scenarioCostEl) {
        scenarioCostEl.textContent = formatCurrency(scenarioEst.total_monthly_cost_usd);
    }
    
    if (baseRegionEl) {
        baseRegionEl.textContent = baseEst.region || '-';
    }
    
    if (scenarioRegionEl) {
        scenarioRegionEl.textContent = scenarioEst.region || '-';
    }
    
    if (deltaEl) {
        const totalDelta = scenarioEst.total_monthly_cost_usd - baseEst.total_monthly_cost_usd;
        const totalDeltaPercent = baseEst.total_monthly_cost_usd > 0 
            ? (totalDelta / baseEst.total_monthly_cost_usd) * 100 
            : null;
        deltaEl.innerHTML = `
            <div class="delta-label">Total Change:</div>
            <div>${renderDeltaIndicator(totalDelta, totalDeltaPercent) || '<span style="color: var(--color-neutral);">No change</span>'}</div>
        `;
    }
}

/**
 * Render scenario banner
 */
function renderScenarioBanner(scenarioResult) {
    const banner = document.getElementById('scenario-banner');
    if (!banner) return;
    
    banner.style.display = 'block';
    
    const assumptionsEl = document.getElementById('scenario-assumptions');
    if (assumptionsEl && scenarioResult.assumptions) {
        assumptionsEl.innerHTML = '';
        scenarioResult.assumptions.forEach(assumption => {
            const item = document.createElement('div');
            item.className = 'scenario-assumption';
            item.textContent = assumption;
            assumptionsEl.appendChild(item);
        });
    }
}

/**
 * Hide scenario views
 */
function hideScenarioViews() {
    const banner = document.getElementById('scenario-banner');
    const comparisonSection = document.getElementById('scenario-comparison-section');
    
    if (banner) banner.style.display = 'none';
    if (comparisonSection) comparisonSection.style.display = 'none';
}

/**
 * Render cost table
 */
function renderCostTable(lineItems, deltas = null) {
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
        
        // Add delta indicator if scenario is active
        if (deltas) {
            const delta = deltas.find(d => d.resource_name === item.resource_name);
            if (delta && delta.delta_usd !== 0) {
                const costCell = row.querySelector('.cost-value');
                if (costCell) {
                    const baseText = costCell.textContent;
                    const deltaIndicator = renderDeltaIndicator(delta.delta_usd, delta.delta_percent, 'small');
                    if (deltaIndicator) {
                        const wrapper = document.createElement('div');
                        wrapper.style.display = 'flex';
                        wrapper.style.flexDirection = 'column';
                        wrapper.style.alignItems = 'flex-end';
                        wrapper.style.gap = '2px';
                        wrapper.innerHTML = `
                            <div>${formatCurrency(item.monthly_cost_usd || 0)}</div>
                            <div>${deltaIndicator}</div>
                        `;
                        costCell.innerHTML = '';
                        costCell.appendChild(wrapper);
                    }
                }
            }
        }
        
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
 * Render full estimate (base or scenario)
 */
function renderEstimate(estimateData, isScenario = false) {
    if (!estimateData || !estimateData.estimate) {
        console.error('Invalid estimate data');
        return;
    }
    
    const estimate = estimateData.estimate;
    
    // Store base estimate
    if (!isScenario && !baseEstimate) {
        baseEstimate = estimate;
    }
    
    // Render summary with scenario indicator if active
    renderSummary(estimate, isScenario ? currentScenario : null);
    
    // Render cost drivers with deltas if scenario is active
    const deltas = isScenario && estimateData.scenario_result ? estimateData.scenario_result.deltas : null;
    renderCostDrivers(estimate.line_items || [], estimate.total_monthly_cost_usd, deltas);
    
    // Render cost table (always show base, highlight scenario changes if active)
    renderCostTable(estimate.line_items || [], deltas);
    renderUnpricedResources(estimate.unpriced_resources || []);
    
    // Render scenario comparison if active
    if (isScenario && currentScenario && estimateData.scenario_result) {
        renderScenarioComparison(estimateData);
        renderScenarioBanner(estimateData.scenario_result);
    } else {
        hideScenarioViews();
    }
    
    // Render insights if available (only for base estimate to avoid confusion)
    if (!isScenario && estimateData.insights) {
        renderInsights(estimateData.insights);
    }
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
 * Initialize region dropdown
 */
function initRegionDropdown() {
    const regionPill = document.getElementById('region-pill');
    const regionDropdown = document.getElementById('region-dropdown');
    const regionOptions = document.getElementById('region-options');
    const compareBtn = document.getElementById('compare-region-btn');
    const selectedRegionName = document.getElementById('selected-region-name');
    
    if (!regionPill || !regionDropdown || !regionOptions) return;
    
    let selectedRegion = null;
    
    // Populate region options (exclude current region)
    const currentRegionEl = document.getElementById('region');
    const currentRegion = currentRegionEl ? currentRegionEl.textContent.trim() : null;
    
    COMMON_REGIONS.forEach(region => {
        // Skip current region
        if (currentRegion && region.code === currentRegion) return;
        
        const option = document.createElement('div');
        option.className = 'region-option';
        option.dataset.region = region.code;
        option.innerHTML = `
            <div>${region.name}</div>
            <div style="font-size: 0.75rem; opacity: 0.7;">${region.code}</div>
        `;
        
        option.addEventListener('click', () => {
            // Remove selected from all
            regionOptions.querySelectorAll('.region-option').forEach(opt => opt.classList.remove('selected'));
            option.classList.add('selected');
            selectedRegion = region.code;
            
            // Show compare button
            if (compareBtn && selectedRegionName) {
                compareBtn.style.display = 'block';
                selectedRegionName.textContent = region.name;
            }
        });
        
        regionOptions.appendChild(option);
    });
    
    // Toggle dropdown
    regionPill.addEventListener('click', (e) => {
        e.stopPropagation();
        const isActive = regionPill.classList.contains('active');
        
        if (isActive) {
            regionPill.classList.remove('active');
            regionDropdown.style.display = 'none';
        } else {
            regionPill.classList.add('active');
            regionDropdown.style.display = 'block';
        }
    });
    
    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!regionPill.contains(e.target) && !regionDropdown.contains(e.target)) {
            regionPill.classList.remove('active');
            regionDropdown.style.display = 'none';
        }
    });
    
    // Compare button handler
    if (compareBtn) {
        compareBtn.addEventListener('click', async () => {
            if (selectedRegion) {
                await applyScenario({ region_override: selectedRegion });
                regionPill.classList.remove('active');
                regionDropdown.style.display = 'none';
            }
        });
    }
}

/**
 * Apply scenario with given parameters
 */
async function applyScenario(scenarioParams) {
    if (!currentIntentGraph) {
        console.error('No intent graph available');
        return;
    }
    
    // Get users input if provided
    const usersInput = document.getElementById('users-input');
    if (usersInput && usersInput.value) {
        const users = parseInt(usersInput.value, 10);
        if (!isNaN(users) && users >= 0) {
            scenarioParams.users = users;
        }
    }
    
    try {
        // Show loading state
        const compareBtn = document.querySelector('.compare-button');
        const applyBtns = document.querySelectorAll('.apply-scenario-btn');
        [...applyBtns, compareBtn].forEach(btn => {
            if (btn) {
                btn.disabled = true;
                btn.textContent = 'Calculating...';
            }
        });
        
        const response = await apiRequest('/api/terraform/estimate/scenario', {
            method: 'POST',
            body: JSON.stringify({
                intent_graph: currentIntentGraph,
                scenario: scenarioParams
            })
        });
        
        if (!response.ok) {
            throw new Error(`Scenario API error: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.status === 'ok' && data.scenario_result) {
            currentScenario = scenarioParams;
            
            // Create estimate data structure with scenario result
            const estimateData = {
                estimate: data.scenario_result.scenario_estimate,
                scenario_result: data.scenario_result,
                insights: null // Can be populated later
            };
            
            renderEstimate(estimateData, true);
        }
    } catch (error) {
        console.error('Failed to apply scenario:', error);
        alert('Failed to calculate scenario. Please try again.');
    } finally {
        // Reset button states
        const compareBtn = document.querySelector('.compare-button');
        const applyBtns = document.querySelectorAll('.apply-scenario-btn');
        [...applyBtns, compareBtn].forEach(btn => {
            if (btn) {
                btn.disabled = false;
                if (btn.dataset.scenarioType) {
                    btn.textContent = 'Apply Scenario';
                } else {
                    btn.textContent = `Compare with ${btn.querySelector('#selected-region-name')?.textContent || 'region'}`;
                }
            }
        });
    }
}

/**
 * Reset scenario to base estimate
 */
function resetScenario() {
    currentScenario = null;
    
    // Hide scenario views
    hideScenarioViews();
    
    if (baseEstimate) {
        const estimateData = {
            estimate: baseEstimate,
            insights: SAMPLE_INSIGHTS // Restore insights for base estimate
        };
        renderEstimate(estimateData, false);
    }
    
    // Reset inputs
    const usersInput = document.getElementById('users-input');
    if (usersInput) usersInput.value = '';
    
    document.querySelectorAll('.autoscaling-input').forEach(input => {
        input.value = '';
    });
    
    // Reset region dropdown
    const regionPill = document.getElementById('region-pill');
    const regionDropdown = document.getElementById('region-dropdown');
    const compareBtn = document.getElementById('compare-region-btn');
    if (regionPill) regionPill.classList.remove('active');
    if (regionDropdown) regionDropdown.style.display = 'none';
    if (compareBtn) compareBtn.style.display = 'none';
    
    // Clear selected region
    const regionOptions = document.getElementById('region-options');
    if (regionOptions) {
        regionOptions.querySelectorAll('.region-option').forEach(opt => opt.classList.remove('selected'));
    }
}

/**
 * Initialize reset button
 */
function initResetButton() {
    const resetBtn = document.getElementById('reset-scenario-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', resetScenario);
    }
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
    
    // Create sample intent graph (for scenario API calls)
    // In real app, this would come from the interpret API
    currentIntentGraph = {
        providers: ['aws', 'azure'],
        resources: sampleData.estimate.line_items.map(item => ({
            cloud: item.cloud,
            category: item.category || 'compute',
            service: item.service,
            terraform_type: item.terraform_type,
            name: item.resource_name,
            region: { source: 'explicit', value: item.region },
            count_model: { type: 'fixed', value: 1 }
        }))
    };
    
    renderEstimate(sampleData);
    
    // Initialize interactive components
    initBreakdownToggle();
    initRegionDropdown();
    initResetButton();
    
    // In the future, this could fetch from the API:
    // apiRequest('/api/terraform/estimate', { method: 'POST', ... })
    //   .then(res => res.json())
    //   .then(data => {
    //       currentIntentGraph = data.intent_graph; // Store from interpret
    //       renderEstimate(data);
    //   });
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}