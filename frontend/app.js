/**
 * TERRA-BUD UI
 * Redesigned with calm, insight-first approach
 */

// API base URL - use relative paths since frontend and backend are on same port
const API_BASE_URL = '';

// Helper function for API requests
function apiUrl(path) {
    return API_BASE_URL + path;
}

// Global state for estimates and scenarios
let baseEstimate = null;
let currentScenario = null;
let currentIntentGraph = null;
let uploadedFiles = [];
let originalTerraformText = null; // Store original Terraform text for re-estimation

// Time unit selector state
let currentTimeUnit = 'monthly';
let customValue = null; // For custom hours or users

// State for insight focus
let focusedInsightId = null;

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
            aws: "full",
            azure: "not_supported_yet",
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
 * Convert monthly cost to selected time unit
 */
function convertCost(monthlyCost, unit, customVal = null) {
    if (!monthlyCost || monthlyCost === 0) return 0;
    
    switch (unit) {
        case 'monthly':
            return monthlyCost;
        case 'hourly':
            return monthlyCost / 730; // 730 hours per month
        case 'daily':
            return monthlyCost / 30; // 30 days per month
        case 'hours':
            if (customVal && customVal > 0) {
                return (monthlyCost / 730) * customVal; // Cost for custom hours
            }
            return monthlyCost / 730; // Default to hourly if no custom value
        case 'users':
            if (customVal && customVal > 0) {
                return monthlyCost / customVal; // Cost per user
            }
            return monthlyCost; // Default to monthly if no custom value
        default:
            return monthlyCost;
    }
}

/**
 * Get unit label for display
 */
function getUnitLabel(unit, customVal = null) {
    switch (unit) {
        case 'monthly':
            return '/month';
        case 'hourly':
            return '/hour';
        case 'daily':
            return '/day';
        case 'hours':
            if (customVal && customVal > 0) {
                return `/${customVal} hours`;
            }
            return '/hour';
        case 'users':
            if (customVal && customVal > 0) {
                return `/user (${customVal} users)`;
            }
            return '/user';
        default:
            return '/month';
    }
}

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
 * NOTE: This section has been removed - cost drivers are now shown in detailed breakdown only
 */
function renderCostDrivers(lineItems, totalCost, scenarioDeltas = null) {
    // Section removed - cost drivers are now shown in detailed breakdown only
    return;
    
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
        card.dataset.categoryName = getCategoryName(categoryData.category);
        
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
                        ${formatCurrency(convertCost(categoryData.totalCost, currentTimeUnit, customValue))}
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
            // Breakdown is always visible - no toggle needed
            if (breakdownContent) {
                breakdownContent.style.display = 'block';
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
 * Focus on an insight and highlight related cost elements
 */
function focusInsight(insightId, affectedResources, insightType) {
    // Clear previous focus
    clearInsightFocus();
    
    // Set new focus
    focusedInsightId = insightId;
    
    const insightCard = document.querySelector(`[data-insight-id="${insightId}"]`);
    if (!insightCard) return;
    
    // Mark insight card as active
    insightCard.classList.add('insight-active');
    
    // Show clear button
    const clearBtn = insightCard.querySelector('.clear-focus-btn');
    if (clearBtn) clearBtn.style.display = 'block';
    
    // Get all line items to check category-level insights
    const allRows = document.querySelectorAll('.cost-table tbody tr[data-resource-name]');
    const allCards = document.querySelectorAll('.cost-driver-card[data-category]');
    
    // Check if this is a category-level insight (e.g., high_cost_driver referring to compute)
    const isCategoryInsight = insightType === 'high_cost_driver' || 
                              insightType === 'region_comparison' ||
                              insightType === 'scaling_assumption';
    
    // Match resources
    const matchingRows = [];
    const matchingCards = new Set();
    
    affectedResources.forEach(resourceName => {
        // Find matching table rows by resource_name
        allRows.forEach(row => {
            const rowResourceName = row.dataset.resourceName;
            if (rowResourceName === resourceName) {
                matchingRows.push(row);
                
                // Also highlight the category card for this resource
                const category = row.dataset.category;
                if (category) {
                    matchingCards.add(category);
                }
            }
        });
        
        // For category-level insights, highlight entire categories
        if (isCategoryInsight) {
            // Try to infer category from resource name patterns
            // This is a fallback - ideally insights would include category info
            const resourceCategory = inferCategoryFromResource(resourceName, allRows);
            if (resourceCategory) {
                matchingCards.add(resourceCategory);
            }
        }
    });
    
    // If no specific resources matched but it's a category insight, try category matching
    if (matchingRows.length === 0 && isCategoryInsight) {
        // For high_cost_driver insights, we might want to highlight based on description
        // This is a heuristic - in production, insights should include category info
        if (insightType === 'high_cost_driver') {
            // Common patterns: compute, database, storage mentioned in description
            const insightCard = document.querySelector(`[data-insight-id="${insightId}"]`);
            const description = insightCard ? insightCard.querySelector('.insight-description')?.textContent.toLowerCase() : '';
            
            if (description.includes('compute') || description.includes('instance') || description.includes('ec2') || description.includes('vm')) {
                const computeCard = document.querySelector('.cost-driver-card[data-category="compute"]');
                if (computeCard) matchingCards.add('compute');
            }
            if (description.includes('database') || description.includes('db') || description.includes('rds')) {
                const dbCard = document.querySelector('.cost-driver-card[data-category="database"]');
                if (dbCard) matchingCards.add('database');
            }
            if (description.includes('storage') || description.includes('s3') || description.includes('bucket')) {
                const storageCard = document.querySelector('.cost-driver-card[data-category="storage"]');
                if (storageCard) matchingCards.add('storage');
            }
        }
    }
    
    // Apply highlights
    matchingRows.forEach(row => {
        row.classList.add('highlight-soft');
    });
    
    matchingCards.forEach(category => {
        const card = document.querySelector(`.cost-driver-card[data-category="${category}"]`);
        if (card) {
            card.classList.add('highlight-outline');
        }
    });
    
    // Check if detailed table is collapsed and show hint if needed
    const breakdownContent = document.getElementById('breakdown-content');
    const hasMatchingRows = matchingRows.length > 0;
    
    if (hasMatchingRows && breakdownContent && breakdownContent.style.display === 'none') {
        showTableHint(insightCard, matchingRows.length);
    }
}

/**
 * Infer category from resource name (fallback for category-level insights)
 */
function inferCategoryFromResource(resourceName, allRows) {
    // Find the row with this resource name
    for (const row of allRows) {
        if (row.dataset.resourceName === resourceName) {
            return row.dataset.category;
        }
    }
    return null;
}

/**
 * Clear insight focus and remove highlights
 */
function clearInsightFocus() {
    // Remove active state from all insights
    document.querySelectorAll('.insight-card').forEach(card => {
        card.classList.remove('insight-active');
        const clearBtn = card.querySelector('.clear-focus-btn');
        if (clearBtn) clearBtn.style.display = 'none';
    });
    
    // Remove highlights from table rows
    document.querySelectorAll('.cost-table tbody tr').forEach(row => {
        row.classList.remove('highlight-soft');
    });
    
    // Remove highlights from cost driver cards
    document.querySelectorAll('.cost-driver-card').forEach(card => {
        card.classList.remove('highlight-outline');
    });
    
    // Hide table hint
    hideTableHint();
    
    // Clear state
    focusedInsightId = null;
}

/**
 * Show hint when detailed table is collapsed but insight references it
 */
function showTableHint(insightCard, matchingCount) {
    // Remove existing hint if any
    hideTableHint();
    
    const hint = document.createElement('div');
    hint.className = 'table-hint';
    hint.innerHTML = `
        <span class="table-hint-text">
            This insight refers to ${matchingCount} item${matchingCount !== 1 ? 's' : ''} in the detailed breakdown.
        </span>
        <button class="table-hint-button" id="show-details-from-hint">Show Details</button>
    `;
    
    insightCard.appendChild(hint);
    
    // Add click handler to hint button
    const hintButton = hint.querySelector('#show-details-from-hint');
    if (hintButton) {
        hintButton.addEventListener('click', () => {
            const breakdownContent = document.getElementById('breakdown-content');
            // Breakdown is always visible - no toggle needed
            if (breakdownContent) {
                breakdownContent.style.display = 'block';
            }
            hideTableHint();
        });
    }
}

/**
 * Hide table hint
 */
function hideTableHint() {
    document.querySelectorAll('.table-hint').forEach(hint => hint.remove());
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
    const costUnitLabelEl = document.getElementById('cost-unit-label');
    const regionEl = document.getElementById('region');
    const coverageBadgesEl = document.getElementById('coverage-badges');
    
    if (totalCostEl) {
        // Clear any existing delta badges
        const existingDelta = totalCostEl.querySelector('.scenario-delta-badge');
        if (existingDelta) existingDelta.remove();
        
        // Convert cost to selected unit
        const convertedCost = convertCost(estimate.total_monthly_cost_usd, currentTimeUnit, customValue);
        totalCostEl.textContent = formatCurrency(convertedCost);
        
        // Update unit label
        if (costUnitLabelEl) {
            costUnitLabelEl.textContent = getUnitLabel(currentTimeUnit, customValue);
        }
        
        // Show delta if scenario is active (delta is always in monthly terms)
        if (scenario && baseEstimate) {
            const monthlyDelta = estimate.total_monthly_cost_usd - baseEstimate.total_monthly_cost_usd;
            const convertedDelta = convertCost(monthlyDelta, currentTimeUnit, customValue);
            const deltaPercent = baseEstimate.total_monthly_cost_usd > 0 
                ? (monthlyDelta / baseEstimate.total_monthly_cost_usd) * 100 
                : null;
            const deltaEl = document.createElement('span');
            deltaEl.className = 'scenario-delta-badge';
            deltaEl.innerHTML = renderDeltaIndicator(convertedDelta, deltaPercent);
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
            
            // Format status text for display
            let displayStatus = status.replace('_', ' ');
            if (status === 'full') {
                displayStatus = 'COMPLETED';
            } else if (status === 'partial') {
                displayStatus = 'PARTIAL';
            } else if (status === 'not_supported_yet') {
                displayStatus = 'NOT YET SUPPORTED';
            }
            
            badge.textContent = `${cloud.label}: ${displayStatus}`;
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
    
    // Convert costs to selected unit
    const convertedBaseCost = convertCost(baseEst.total_monthly_cost_usd, currentTimeUnit, customValue);
    const convertedScenarioCost = convertCost(scenarioEst.total_monthly_cost_usd, currentTimeUnit, customValue);
    const baseRegionEl = document.getElementById('base-region');
    const scenarioRegionEl = document.getElementById('scenario-region');
    const deltaEl = document.getElementById('scenario-delta');
    
    const baseEst = scenarioResult.base_estimate;
    const scenarioEst = scenarioResult.scenario_estimate;
    
    if (baseCostEl) {
        const convertedBaseCost = convertCost(baseEst.total_monthly_cost_usd, currentTimeUnit, customValue);
        baseCostEl.textContent = formatCurrency(convertedBaseCost);
    }
    
    if (scenarioCostEl) {
        const convertedScenarioCost = convertCost(scenarioEst.total_monthly_cost_usd, currentTimeUnit, customValue);
        scenarioCostEl.textContent = formatCurrency(convertedScenarioCost);
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
        // Handle case where maxCost is 0 to avoid NaN
        const intensity = maxCost > 0 ? calculateCostIntensity(item.monthly_cost_usd || 0, maxCost) : 0;
        row.className = `cost-row ${getCostRowClass(intensity)}`;
        
        // Add data attributes for insight linking
        if (item.resource_name) {
            row.dataset.resourceName = item.resource_name;
        }
        if (item.terraform_type) {
            row.dataset.terraformType = item.terraform_type;
        }
        if (item.category) {
            row.dataset.category = item.category;
        }
        
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
        costCell.style.textAlign = 'right';
        if (item.monthly_cost_usd === 0) {
            costCell.classList.add('zero');
        }
        const convertedCost = convertCost(item.monthly_cost_usd || 0, currentTimeUnit, customValue);
        costCell.textContent = formatCurrency(convertedCost);
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
                    const convertedDelta = convertCost(delta.delta_usd || 0, currentTimeUnit, customValue);
                    const deltaIndicator = renderDeltaIndicator(convertedDelta, delta.delta_percent, 'small');
                    if (deltaIndicator) {
                        const wrapper = document.createElement('div');
                        wrapper.style.display = 'flex';
                        wrapper.style.flexDirection = 'column';
                        wrapper.style.alignItems = 'flex-end';
                        wrapper.style.gap = '2px';
                        wrapper.innerHTML = `
                            <div>${formatCurrency(convertCost(item.monthly_cost_usd || 0, currentTimeUnit, customValue))}</div>
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
    const section = document.getElementById('unpriced-section');
    
    if (!container) return;
    
    container.innerHTML = '';
    
    // Hide section if no unpriced resources
    if (!unpricedResources || unpricedResources.length === 0) {
        if (section) {
            section.style.display = 'none';
        }
        return;
    }
    
    // Show section if there are unpriced resources
    if (section) {
        section.style.display = 'block';
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
    
    // Update export button state
    if (window.updateExportButtonState) {
        window.updateExportButtonState();
    }
    
    // Update share button state
    if (window.updateShareButtonState) {
        window.updateShareButtonState();
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
    
    insights.forEach((insight, index) => {
        const card = document.createElement('div');
        card.className = 'insight-card';
        card.dataset.insightId = `insight-${index}`;
        if (insight.type) {
            card.dataset.insightType = insight.type;
        }
        
        // Affected resources removed - no longer displayed
        
        card.innerHTML = `
            <div class="insight-header">
                <div class="insight-title">${insight.title}</div>
                <span class="insight-type">${insight.type.replace(/_/g, ' ')}</span>
            </div>
            <div class="insight-description">${insight.description}</div>
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
            <div class="insight-actions">
                <button class="clear-focus-btn" style="display: none;">Clear Focus</button>
            </div>
        `;
        
        // Add click handler for the entire card
        card.addEventListener('click', (e) => {
            // Don't trigger if clicking on clear button
            if (e.target.classList.contains('clear-focus-btn')) return;
            
            focusInsight(`insight-${index}`, [], insight.type);
        });
        
        // Resource tags removed - no click handlers needed
        
        // Add clear focus button handler
        const clearBtn = card.querySelector('.clear-focus-btn');
        if (clearBtn) {
            clearBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                clearInsightFocus();
            });
        }
        
        container.appendChild(card);
    });
}


/**
 * Initialize expandable breakdown section
 */
function initBreakdownToggle() {
    // Breakdown is always visible now - no toggle needed
    const breakdownContent = document.getElementById('breakdown-content');
    if (breakdownContent) {
            breakdownContent.style.display = 'block';
        }
}

/**
 * Initialize region dropdown
 */
function initRegionDropdown() {
    const regionPill = document.getElementById('region-pill');
    const regionDropdown = document.getElementById('region-dropdown');
    const regionOptions = document.getElementById('region-options');
    
    if (!regionPill || !regionDropdown || !regionOptions) return;
    
    // Populate region options (include all regions, highlight current)
    const currentRegionEl = document.getElementById('region');
    const currentRegion = currentRegionEl ? currentRegionEl.textContent.trim() : null;
    
    // Clear existing options
    regionOptions.innerHTML = '';
        
    COMMON_REGIONS.forEach(region => {
        const option = document.createElement('div');
        option.className = 'region-option';
        option.dataset.region = region.code;
        
        // Mark current region as selected
        if (currentRegion && region.code === currentRegion) {
            option.classList.add('selected');
        }
        
        option.innerHTML = `
            <div>${region.name}</div>
            <div style="font-size: 0.75rem; opacity: 0.7;">${region.code}</div>
        `;
        
        option.addEventListener('click', async (e) => {
            e.stopPropagation();
            
            const clickedRegion = region.code;
            
            // Don't re-estimate if clicking the same region
            if (currentRegion === clickedRegion) {
                regionPill.classList.remove('active');
                regionDropdown.style.display = 'none';
                return;
            }
            
            // Update selected state
            regionOptions.querySelectorAll('.region-option').forEach(opt => opt.classList.remove('selected'));
            option.classList.add('selected');
            
            // Close dropdown
            regionPill.classList.remove('active');
            regionDropdown.style.display = 'none';
            
            // Re-estimate with new region
            await reEstimateWithRegion(clickedRegion);
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
}

/**
 * Re-estimate costs with a new region
 */
async function reEstimateWithRegion(newRegion) {
    try {
        // Show loading state
        const totalCostEl = document.getElementById('total-cost');
        if (totalCostEl) {
            totalCostEl.textContent = 'Calculating...';
        }
        
        let data = null;

        // Preferred path for anonymous/local mode: re-call local estimate
        // using the original Terraform text and a JSON body so we can
        // pass region_override end-to-end.
        if (originalTerraformText) {
            const body = {
                terraform_files: [
                    {
                        path: 'main.tf',
                        content: originalTerraformText
                    }
                ],
                region_override: newRegion
            };

            const response = await fetch(apiUrl('/api/terraform/estimate/local'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-AI-API-Key': getAIAPIKey() || ''
                },
                body: JSON.stringify(body)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(errorData.detail || `Estimate failed: ${response.statusText}`);
            }

            data = await response.json();

            if (!(data && data.status === 'ok' && data.estimate)) {
                throw new Error('Invalid response from local estimate API');
            }

            // Update base estimate and intent graph from local endpoint
            baseEstimate = data.estimate;
            currentIntentGraph = data.intent_graph || currentIntentGraph;

            const estimateData = {
                estimate: data.estimate,
                scenario_result: null,
                insights: data.insights || null
            };

            renderEstimate(estimateData, false);
        } else if (currentIntentGraph) {
            // Fallback: use scenario endpoint with region_override when we
            // only have an intent graph (e.g., some authenticated flows).
            const requestBody = {
                intent_graph: currentIntentGraph,
                scenario: {
                    region_override: newRegion
                }
            };
            
            const response = await fetch(apiUrl('/api/terraform/estimate/scenario'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-AI-API-Key': getAIAPIKey() || ''
                },
                body: JSON.stringify(requestBody)
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(errorData.detail || `Estimate failed: ${response.statusText}`);
            }
            
            data = await response.json();
            
            if (data.status === 'ok' && data.scenario_result) {
                // Use the scenario estimate (which has the new region)
                baseEstimate = data.scenario_result.scenario_estimate;
                currentScenario = null; // Clear any scenario when changing region
                
                // Store updated intent graph if provided
                if (data.scenario_result.intent_graph) {
                    currentIntentGraph = data.scenario_result.intent_graph;
                }
                
                // Render the new estimate (use scenario estimate as base)
                const estimateData = {
                    estimate: data.scenario_result.scenario_estimate,
                    scenario_result: null,
                    insights: data.insights || null
                };
                
                renderEstimate(estimateData, false);
            } else {
                throw new Error('Invalid response from estimate API');
            }
        } else {
            throw new Error('No Terraform input or intent graph available for re-estimation');
        }
    } catch (error) {
        console.error('Failed to re-estimate with new region:', error);
        alert('Failed to update estimate for new region. Please try again.');
        
        // Restore previous estimate display
        if (baseEstimate) {
            const estimateData = {
                estimate: baseEstimate,
                scenario_result: null,
                insights: null
            };
            renderEstimate(estimateData, false);
        }
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
        
        // Use local endpoint if no auth (intent_graph available from local estimate)
        // Otherwise use authenticated endpoint
        const endpoint = currentIntentGraph 
            ? apiUrl('/api/terraform/estimate/scenario')
            : apiUrl('/api/terraform/estimate/scenario');
        
        // For anonymous mode, we need to make scenario endpoint work without auth
        // For now, we'll try the scenario endpoint (it may fail if auth required)
        // TODO: Make scenario endpoint work without auth, or create local scenario endpoint
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-AI-API-Key': getAIAPIKey() || ''
            },
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
    
    // Clear insight focus when resetting
    clearInsightFocus();
    
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
 * Escape CSV value
 */
function escapeCSV(value) {
    if (value === null || value === undefined) return '';
    const str = String(value);
    if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
}

/**
 * Format assumptions for CSV
 */
function formatAssumptionsForCSV(assumptions) {
    if (!assumptions || !Array.isArray(assumptions)) return '';
    return assumptions.join('; ');
}

/**
 * Export estimate as CSV
 */
function exportToCSV() {
    const estimate = currentScenario || baseEstimate;
    if (!estimate || !estimate.estimate) {
        alert('No estimate data available to export.');
        return;
    }

    const isScenario = !!currentScenario;
    const lineItems = estimate.estimate.line_items || [];
    const unpricedResources = estimate.estimate.unpriced_resources || [];
    
    // CSV headers
    const headers = [
        'cloud',
        'service',
        'resource_name',
        'terraform_type',
        'region',
        'monthly_cost_usd',
        'pricing_unit',
        'confidence',
        'assumptions',
        'scenario',
        'delta_usd',
        'delta_percent'
    ];
    
    // Calculate deltas if scenario is active
    let deltas = null;
    if (isScenario && baseEstimate) {
        deltas = calculateLineItemDeltas(baseEstimate.estimate.line_items || [], lineItems);
    }
    
    // Build CSV rows
    const rows = [headers.join(',')];
    
    lineItems.forEach(item => {
        const delta = deltas && deltas[item.resource_name] 
            ? deltas[item.resource_name] 
            : null;
        
        const row = [
            escapeCSV(item.cloud || ''),
            escapeCSV(item.service || ''),
            escapeCSV(item.resource_name || ''),
            escapeCSV(item.terraform_type || ''),
            escapeCSV(item.region || ''),
            escapeCSV(item.monthly_cost_usd || 0),
            escapeCSV(item.pricing_unit || ''),
            escapeCSV(item.confidence || ''),
            escapeCSV(formatAssumptionsForCSV(item.assumptions)),
            escapeCSV(isScenario ? 'scenario' : 'base'),
            escapeCSV(delta ? delta.deltaUsd : ''),
            escapeCSV(delta ? delta.deltaPercent : '')
        ];
        rows.push(row.join(','));
    });
    
    // Add unpriced resources
    if (unpricedResources.length > 0) {
        unpricedResources.forEach(resource => {
            const row = [
                escapeCSV(''),
                escapeCSV(''),
                escapeCSV(resource.resource_name || ''),
                escapeCSV(resource.terraform_type || ''),
                escapeCSV(''),
                escapeCSV(''),
                escapeCSV(''),
                escapeCSV('unpriced'),
                escapeCSV(resource.reason || 'Resource not priced'),
                escapeCSV(isScenario ? 'scenario' : 'base'),
                escapeCSV(''),
                escapeCSV('')
            ];
            rows.push(row.join(','));
        });
    }
    
    // Create CSV content
    const csvContent = rows.join('\n');
    
    // Create blob and download
    const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = isScenario ? 'cost-estimate-scenario.csv' : 'cost-estimate-base.csv';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

/**
 * Calculate line item deltas for CSV export
 */
function calculateLineItemDeltas(baseItems, scenarioItems) {
    const deltas = {};
    const baseMap = {};
    
    // Create map of base items by resource name
    baseItems.forEach(item => {
        if (item.resource_name) {
            baseMap[item.resource_name] = item;
        }
    });
    
    // Calculate deltas for scenario items
    scenarioItems.forEach(item => {
        if (item.resource_name) {
            const baseItem = baseMap[item.resource_name];
            if (baseItem) {
                const deltaUsd = (item.monthly_cost_usd || 0) - (baseItem.monthly_cost_usd || 0);
                const deltaPercent = baseItem.monthly_cost_usd > 0 
                    ? (deltaUsd / baseItem.monthly_cost_usd) * 100 
                    : 0;
                deltas[item.resource_name] = {
                    deltaUsd: deltaUsd.toFixed(2),
                    deltaPercent: deltaPercent.toFixed(1)
                };
            }
        }
    });
    
    return deltas;
}

/**
 * Export estimate as PDF (using print-to-PDF)
 */
function exportToPDF() {
    const estimate = currentScenario || baseEstimate;
    if (!estimate || !estimate.estimate) {
        alert('No estimate data available to export.');
        return;
    }

    const isScenario = !!currentScenario;
    const data = estimate.estimate;
    const lineItems = data.line_items || [];
    const unpricedResources = data.unpriced_resources || [];
    
    // Calculate category totals
    const { grouped } = groupByCategory(lineItems);
    const categories = Object.values(grouped).sort((a, b) => b.totalCost - a.totalCost);
    
    // Get top 10 most expensive items
    const topItems = [...lineItems]
        .filter(item => item.priced && item.monthly_cost_usd > 0)
        .sort((a, b) => (b.monthly_cost_usd || 0) - (a.monthly_cost_usd || 0))
        .slice(0, 10);
    
    // Calculate deltas if scenario
    let totalDelta = null;
    let totalDeltaPercent = null;
    if (isScenario && baseEstimate) {
        const delta = data.total_monthly_cost_usd - baseEstimate.total_monthly_cost_usd;
        totalDelta = delta;
        totalDeltaPercent = baseEstimate.total_monthly_cost_usd > 0 
            ? (delta / baseEstimate.total_monthly_cost_usd) * 100 
            : 0;
    }
    
    // Create printable content
    const printWindow = window.open('', '_blank');
    const now = new Date();
    const dateStr = now.toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
    
    printWindow.document.write(`
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Infrastructure Cost Estimate</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            color: #1f2937;
            background: white;
            padding: 40px;
            max-width: 800px;
            margin: 0 auto;
        }
        .pdf-header {
            border-bottom: 2px solid #e5e7eb;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }
        .pdf-title {
            font-size: 24px;
            font-weight: 600;
            color: #111827;
            margin-bottom: 8px;
        }
        .pdf-meta {
            font-size: 14px;
            color: #6b7280;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        .pdf-section {
            margin-bottom: 30px;
        }
        .pdf-section-title {
            font-size: 18px;
            font-weight: 600;
            color: #111827;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #e5e7eb;
        }
        .pdf-summary {
            background: #f9fafb;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .pdf-cost-large {
            font-size: 32px;
            font-weight: 600;
            color: #111827;
            margin-bottom: 8px;
        }
        .pdf-delta {
            font-size: 14px;
            color: #6b7280;
            margin-top: 8px;
        }
        .pdf-delta.positive {
            color: #dc2626;
        }
        .pdf-delta.negative {
            color: #059669;
        }
        .pdf-category-list {
            list-style: none;
        }
        .pdf-category-item {
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #f3f4f6;
        }
        .pdf-category-item:last-child {
            border-bottom: none;
        }
        .pdf-category-name {
            font-weight: 500;
            color: #374151;
        }
        .pdf-category-cost {
            font-family: 'SF Mono', 'Monaco', 'Courier New', monospace;
            color: #111827;
        }
        .pdf-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
        }
        .pdf-table th {
            text-align: left;
            padding: 10px;
            font-size: 12px;
            font-weight: 600;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 2px solid #e5e7eb;
        }
        .pdf-table td {
            padding: 10px;
            font-size: 14px;
            border-bottom: 1px solid #f3f4f6;
        }
        .pdf-table tr:last-child td {
            border-bottom: none;
        }
        .pdf-cost-value {
            font-family: 'SF Mono', 'Monaco', 'Courier New', monospace;
            text-align: right;
            font-weight: 500;
        }
        .pdf-confidence {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 6px;
        }
        .pdf-confidence.high {
            background: #10b981;
        }
        .pdf-confidence.medium {
            background: #f59e0b;
        }
        .pdf-confidence.low {
            background: #ef4444;
        }
        .pdf-assumptions {
            background: #f9fafb;
            border-left: 3px solid #6366f1;
            padding: 16px;
            margin-top: 20px;
            border-radius: 4px;
        }
        .pdf-assumptions-title {
            font-weight: 600;
            margin-bottom: 8px;
            color: #374151;
        }
        .pdf-assumptions-list {
            list-style: none;
            padding-left: 0;
        }
        .pdf-assumptions-list li {
            padding: 4px 0;
            color: #6b7280;
            font-size: 14px;
        }
        .pdf-disclaimer {
            background: #fef3c7;
            border: 1px solid #fcd34d;
            border-radius: 8px;
            padding: 20px;
            margin-top: 40px;
            font-size: 14px;
            line-height: 1.8;
            color: #78350f;
        }
        .pdf-disclaimer strong {
            color: #92400e;
        }
        .pdf-unpriced {
            margin-top: 20px;
        }
        .pdf-unpriced-list {
            list-style: none;
            padding-left: 0;
        }
        .pdf-unpriced-list li {
            padding: 8px 0;
            color: #6b7280;
            font-size: 14px;
            border-bottom: 1px solid #f3f4f6;
        }
        .pdf-unpriced-list li:last-child {
            border-bottom: none;
        }
        @media print {
            body {
                padding: 20px;
            }
            .pdf-section {
                page-break-inside: avoid;
            }
        }
    </style>
</head>
<body>
    <div class="pdf-header">
        <h1 class="pdf-title">Infrastructure Cost Estimate</h1>
        <div class="pdf-meta">
            <span>Date: ${dateStr}</span>
            <span>Region: ${data.region || 'N/A'}</span>
            ${isScenario ? '<span style="color: #6366f1; font-weight: 500;">Scenario Comparison</span>' : ''}
        </div>
    </div>
    
    <div class="pdf-section">
        <div class="pdf-summary">
            <div class="pdf-cost-large">${formatCurrency(data.total_monthly_cost_usd || 0)}</div>
            <div style="color: #6b7280; font-size: 14px;">Estimated Monthly Cost</div>
            ${totalDelta !== null ? `
                <div class="pdf-delta ${totalDelta >= 0 ? 'positive' : 'negative'}">
                    ${totalDelta >= 0 ? '+' : ''}${formatCurrency(totalDelta)} 
                    (${totalDeltaPercent >= 0 ? '+' : ''}${totalDeltaPercent.toFixed(1)}% vs base)
                </div>
            ` : ''}
            <div style="margin-top: 12px; font-size: 12px; color: #6b7280;">
                Coverage: 
                ${data.coverage?.aws ? `AWS: ${data.coverage.aws}` : ''}
                ${data.coverage?.azure ? ` | Azure: ${data.coverage.azure}` : ''}
                ${data.coverage?.gcp ? ` | GCP: ${data.coverage.gcp}` : ''}
            </div>
        </div>
    </div>
    
    <div class="pdf-section">
        <h2 class="pdf-section-title">Cost by Category</h2>
        <ul class="pdf-category-list">
            ${categories.map(cat => `
                <li class="pdf-category-item">
                    <span class="pdf-category-name">${getCategoryName(cat.category)}</span>
                    <span class="pdf-category-cost">${formatCurrency(cat.totalCost)} (${formatPercentage(cat.percentage / 100)})</span>
                </li>
            `).join('')}
        </ul>
    </div>
    
    ${topItems.length > 0 ? `
    <div class="pdf-section">
        <h2 class="pdf-section-title">Top 10 Most Expensive Resources</h2>
        <table class="pdf-table">
            <thead>
                <tr>
                    <th>Service</th>
                    <th>Resource</th>
                    <th>Cost</th>
                    <th>Confidence</th>
                </tr>
            </thead>
            <tbody>
                ${topItems.map(item => `
                    <tr>
                        <td>${item.service || 'N/A'}</td>
                        <td>${item.resource_name || 'N/A'}</td>
                        <td class="pdf-cost-value">${formatCurrency(item.monthly_cost_usd || 0)}</td>
                        <td>
                            <span class="pdf-confidence ${item.confidence || 'medium'}"></span>
                            ${(item.confidence || 'medium').charAt(0).toUpperCase() + (item.confidence || 'medium').slice(1)}
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    </div>
    ` : ''}
    
    ${isScenario && currentScenario?.assumptions ? `
    <div class="pdf-section">
        <h2 class="pdf-section-title">Scenario Assumptions</h2>
        <div class="pdf-assumptions">
            <div class="pdf-assumptions-title">Changes Applied:</div>
            <ul class="pdf-assumptions-list">
                ${Object.entries(currentScenario.assumptions).map(([key, value]) => `
                    <li>${key}: ${value}</li>
                `).join('')}
            </ul>
        </div>
    </div>
    ` : ''}
    
    <div class="pdf-section">
        <h2 class="pdf-section-title">Assumptions & Uncertainty</h2>
        <div class="pdf-assumptions">
            <div class="pdf-assumptions-title">Key Assumptions:</div>
            <ul class="pdf-assumptions-list">
                <li>Costs are based on publicly available pricing data as of ${data.pricing_timestamp ? new Date(data.pricing_timestamp).toLocaleDateString() : 'current date'}</li>
                <li>Autoscaling resources use average instance counts, not peak usage</li>
                <li>Some values are inferred when not explicitly specified in configuration</li>
                <li>Confidence indicators reflect certainty level: High (green), Medium (yellow), Low (red)</li>
                <li>Actual costs may vary based on real usage patterns, discounts, and provider-specific factors</li>
            </ul>
        </div>
    </div>
    
    ${unpricedResources.length > 0 ? `
    <div class="pdf-section pdf-unpriced">
        <h2 class="pdf-section-title">Unpriced Resources</h2>
        <ul class="pdf-unpriced-list">
            ${unpricedResources.map(resource => `
                <li>
                    <strong>${resource.resource_name || resource.terraform_type || 'Unknown'}</strong> 
                    (${resource.terraform_type || 'N/A'}) - ${resource.reason || 'Not priced'}
                </li>
            `).join('')}
        </ul>
    </div>
    ` : ''}
    
    <div class="pdf-disclaimer">
        <strong>Important:</strong> This document contains cost estimates based on infrastructure configuration,
        assumptions, and publicly available pricing information.
        It is <strong>NOT</strong> an official cloud provider bill.
        Actual costs may vary based on real usage, discounts, reserved capacity, and other factors.
    </div>
</body>
</html>
    `);
    
    printWindow.document.close();
    
    // Wait for content to load, then trigger print
    setTimeout(() => {
        printWindow.print();
    }, 250);
}

/**
 * Create share snapshot
 */
async function createShareSnapshot() {
    const estimate = currentScenario || baseEstimate;
    if (!estimate || !estimate.estimate) {
        showShareError('No estimate data available to share.');
        return;
    }

    try {
        // Prepare snapshot data
        const snapshotData = {
            base_estimate: baseEstimate ? baseEstimate.estimate : null,
            scenario_estimate: currentScenario ? estimate.estimate : null,
            deltas: null,
            insights: null,
            scenario_label: null,
            region: estimate.estimate.region || null
        };

        // Add scenario data if active
        if (currentScenario && baseEstimate) {
            // Calculate deltas for scenario
            const scenarioLineItems = estimate.estimate.line_items || [];
            const baseLineItems = baseEstimate.estimate.line_items || [];
            
            // Simple delta calculation
            const totalDelta = estimate.estimate.total_monthly_cost_usd - baseEstimate.total_monthly_cost_usd;
            const totalDeltaPercent = baseEstimate.total_monthly_cost_usd > 0 
                ? (totalDelta / baseEstimate.total_monthly_cost_usd) * 100 
                : 0;
            
            snapshotData.deltas = [{
                type: 'total',
                delta_usd: totalDelta,
                delta_percent: totalDeltaPercent
            }];
            
            snapshotData.scenario_label = `Scenario: ${estimate.estimate.region || 'Custom'}`;
        }

        // Add insights if available (only for base estimate)
        if (!currentScenario && window.SAMPLE_INSIGHTS) {
            snapshotData.insights = window.SAMPLE_INSIGHTS;
        }

        // Call API
        const response = await fetch(apiUrl('/api/share'), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(snapshotData)
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Failed to create share link' }));
            throw new Error(error.detail || 'Failed to create share link');
        }

        const data = await response.json();
        
        // Show share URL in modal
        const urlInput = document.getElementById('share-url-input');
        if (urlInput) {
            urlInput.value = data.share_url;
        }
        
        showShareSuccess('Share link created successfully!');
        
    } catch (error) {
        console.error('Failed to create share snapshot:', error);
        showShareError(error.message || 'Failed to create share link. Please try again.');
    }
}

/**
 * Show share success message
 */
function showShareSuccess(message) {
    const statusEl = document.getElementById('share-status');
    if (statusEl) {
        statusEl.textContent = message;
        statusEl.className = 'share-status success';
        statusEl.style.display = 'block';
        
        // Auto-hide after 3 seconds
        setTimeout(() => {
            statusEl.style.display = 'none';
        }, 3000);
    }
}

/**
 * Show share error message
 */
function showShareError(message) {
    const statusEl = document.getElementById('share-status');
    if (statusEl) {
        statusEl.textContent = message;
        statusEl.className = 'share-status error';
        statusEl.style.display = 'block';
    }
}

/**
 * Copy share URL to clipboard
 */
async function copyShareUrl() {
    const urlInput = document.getElementById('share-url-input');
    if (!urlInput || !urlInput.value) {
        showShareError('No share URL available. Please create a share link first.');
        return;
    }

    try {
        await navigator.clipboard.writeText(urlInput.value);
        showShareSuccess('Link copied to clipboard!');
    } catch (error) {
        // Fallback for older browsers
        urlInput.select();
        document.execCommand('copy');
        showShareSuccess('Link copied to clipboard!');
    }
}

/**
 * Show share modal
 */
function showShareModal() {
    const modal = document.getElementById('share-modal');
    if (!modal) return;
    
    // Reset form
    const urlInput = document.getElementById('share-url-input');
    if (urlInput) urlInput.value = '';
    const statusEl = document.getElementById('share-status');
    if (statusEl) statusEl.style.display = 'none';
    
    modal.style.display = 'flex';
    
    // Create snapshot
    createShareSnapshot();
    
    // Trap focus
    const focusableElements = modal.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const firstFocusable = focusableElements[0];
    if (firstFocusable) {
        firstFocusable.focus();
    }
    
    // Prevent body scroll
    document.body.style.overflow = 'hidden';
}

/**
 * Hide share modal
 */
function hideShareModal() {
    const modal = document.getElementById('share-modal');
    if (!modal) return;
    
    modal.style.display = 'none';
    
    // Restore body scroll
    document.body.style.overflow = '';
}

/**
 * Show rate limit modal
 */
function showRateLimitModal() {
    const modal = document.getElementById('rate-limit-modal');
    if (!modal) return;
    
    modal.style.display = 'flex';
    
    // Prevent body scroll
    document.body.style.overflow = 'hidden';
}

/**
 * Hide rate limit modal
 */
function hideRateLimitModal() {
    const modal = document.getElementById('rate-limit-modal');
    if (!modal) return;
    
    modal.style.display = 'none';
    
    // Restore body scroll
    document.body.style.overflow = '';
}

/**
 * Initialize share controls
 */
function initShareControls() {
    const shareBtn = document.getElementById('share-btn');
    const shareCloseBtn = document.getElementById('share-close-btn');
    const shareDismissBtn = document.getElementById('share-dismiss-btn');
    const copyUrlBtn = document.getElementById('copy-share-url-btn');
    const overlay = document.querySelector('.share-modal-overlay');
    
    if (!shareBtn) return;
    
    // Share button handler
    shareBtn.addEventListener('click', () => {
        if (baseEstimate) {
            showShareModal();
        } else {
            alert('No estimate available to share.');
        }
    });
    
    // Close button handler
    if (shareCloseBtn) {
        shareCloseBtn.addEventListener('click', hideShareModal);
    }
    
    // Dismiss button handler
    if (shareDismissBtn) {
        shareDismissBtn.addEventListener('click', hideShareModal);
    }
    
    // Copy URL button handler
    if (copyUrlBtn) {
        copyUrlBtn.addEventListener('click', copyShareUrl);
    }
    
    // Overlay click handler
    if (overlay) {
        overlay.addEventListener('click', hideShareModal);
    }
    
    // Escape key handler
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const modal = document.getElementById('share-modal');
            if (modal && modal.style.display !== 'none') {
                hideShareModal();
            }
        }
    });
    
    // Update button state based on estimate availability
    function updateShareButtonState() {
        const hasEstimate = baseEstimate !== null;
        if (shareBtn) {
            shareBtn.disabled = !hasEstimate;
        }
    }
    
    updateShareButtonState();
    window.updateShareButtonState = updateShareButtonState;
}

/**
 * Initialize export controls
 */
function initExportControls() {
    const exportBtn = document.getElementById('export-btn');
    const exportDropdown = document.getElementById('export-dropdown');
    const exportCsvBtn = document.getElementById('export-csv-btn');
    const exportPdfBtn = document.getElementById('export-pdf-btn');
    
    if (!exportBtn || !exportDropdown) return;
    
    // Toggle dropdown
    exportBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isVisible = exportDropdown.style.display !== 'none';
        exportDropdown.style.display = isVisible ? 'none' : 'block';
        
        // Close on outside click
        if (!isVisible) {
            setTimeout(() => {
                document.addEventListener('click', function closeDropdown() {
                    exportDropdown.style.display = 'none';
                    document.removeEventListener('click', closeDropdown);
                }, { once: true });
            }, 0);
        }
    });
    
    // CSV export
    if (exportCsvBtn) {
        exportCsvBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            exportDropdown.style.display = 'none';
            exportToCSV();
        });
    }
    
    // PDF export
    if (exportPdfBtn) {
        exportPdfBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            exportDropdown.style.display = 'none';
            exportToPDF();
        });
    }
    
    // Update button state based on estimate availability
    function updateExportButtonState() {
        const hasEstimate = baseEstimate !== null;
        if (exportBtn) {
            exportBtn.disabled = !hasEstimate;
        }
    }
    
    // Check state initially and on estimate changes
    updateExportButtonState();
    
    // Re-check when estimate is rendered (we'll call this from renderEstimate)
    window.updateExportButtonState = updateExportButtonState;
}


/**
 * Initialize rate limit modal
 */
function initRateLimitModal() {
    const modal = document.getElementById('rate-limit-modal');
    const closeBtn = document.getElementById('rate-limit-close-btn');
    const dismissBtn = document.getElementById('rate-limit-dismiss-btn');
    const overlay = modal?.querySelector('.rate-limit-modal-overlay');
    
    if (!modal) return;
    
    // Close button handler
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            hideRateLimitModal();
        });
    }
    
    // Dismiss button handler
    if (dismissBtn) {
        dismissBtn.addEventListener('click', () => {
            hideRateLimitModal();
        });
    }
    
    // Overlay click handler (close on outside click)
    if (overlay) {
        overlay.addEventListener('click', () => {
            hideRateLimitModal();
        });
    }
    
    // ESC key handler
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.style.display !== 'none') {
            hideRateLimitModal();
        }
    });
}

/**
 * Initialize Terraform input section
 */
function initTerraformInput() {
    // Support both landing.html and index.html structures
    const pasteTab = document.querySelector('[data-tab="paste"]');
    const uploadTab = document.querySelector('[data-tab="upload"]');
    const pasteContent = document.getElementById('paste-tab');
    const uploadContent = document.getElementById('upload-tab');
    const textarea = document.getElementById('terraform-textarea');
    const fileInput = document.getElementById('terraform-file-input');
    const fileUploadArea = document.getElementById('file-upload-area');
    const fileList = document.getElementById('file-list');
    const estimateFromTextBtn = document.getElementById('estimate-from-text-btn');
    const estimateFromFilesBtn = document.getElementById('estimate-from-files-btn');
    
    // Tab switching
    if (pasteTab && uploadTab) {
        pasteTab.addEventListener('click', () => {
            pasteTab.classList.add('active');
            uploadTab.classList.remove('active');
            pasteContent.classList.add('active');
            uploadContent.classList.remove('active');
        });
        
        uploadTab.addEventListener('click', () => {
            uploadTab.classList.add('active');
            pasteTab.classList.remove('active');
            uploadContent.classList.add('active');
            pasteContent.classList.remove('active');
        });
    }
    
    // File upload handling
    if (fileUploadArea && fileInput) {
        fileUploadArea.addEventListener('click', () => fileInput.click());
        
        fileUploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            fileUploadArea.classList.add('dragover');
        });
        
        fileUploadArea.addEventListener('dragleave', () => {
            fileUploadArea.classList.remove('dragover');
        });
        
        fileUploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            fileUploadArea.classList.remove('dragover');
            const files = Array.from(e.dataTransfer.files);
            handleFiles(files);
        });
        
        fileInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            // When webkitdirectory is used, all files in the selected folder are included
            // Filter will handle .tf files from folders or individually selected files
            handleFiles(files);
        });
    }
    
    function handleFiles(files) {
        // Filter for .tf files (when folder is selected, all files in folder are included)
        // Also allow .zip files
        uploadedFiles = files.filter(f => {
            const fileName = f.name.toLowerCase();
            return fileName.endsWith('.tf') || fileName.endsWith('.zip');
        });
        
        if (uploadedFiles.length === 0) {
            alert('Please select .tf files or a folder containing .tf files');
            return;
        }
        
        // Display file list
        if (fileList) {
            fileList.innerHTML = '';
            fileList.style.display = 'block';
            
            uploadedFiles.forEach((file, index) => {
                const item = document.createElement('div');
                item.className = 'file-item';
                item.innerHTML = `
                    <span class="file-item-name">${file.name}</span>
                    <button class="file-item-remove" data-index="${index}">×</button>
                `;
                
                const removeBtn = item.querySelector('.file-item-remove');
                removeBtn.addEventListener('click', () => {
                    uploadedFiles.splice(index, 1);
                    if (uploadedFiles.length === 0) {
                        // Hide estimate button and file list when no files (analyze repo button stays visible)
                        if (estimateFromFilesBtn) {
                            estimateFromFilesBtn.style.display = 'none';
                        }
                        if (fileList) {
                            fileList.style.display = 'none';
                        }
                    } else {
                    handleFiles(uploadedFiles);
                    }
                });
                
                fileList.appendChild(item);
            });
        }
        
        // Show estimate button when files are selected (analyze repo button is always visible)
        if (estimateFromFilesBtn) {
            estimateFromFilesBtn.style.display = 'block';
        }
    }
    
    // Real-time estimation DISABLED - user must click "Estimate Cost" button
    // Debounce timer was causing issues where estimates would disappear after being displayed
    if (textarea) {
        // Show results section immediately when user starts typing
        const resultsSection = document.getElementById('results-section');
        if (resultsSection) {
            resultsSection.style.display = 'block';
        }
        
        // Only clear estimate if textarea becomes empty
        textarea.addEventListener('input', async (e) => {
            const text = e.target.value.trim();
            
            // If empty or too short, clear estimate
            if (!text || text.length < 10) {
                // Clear estimate display
                const totalCostEl = document.getElementById('total-cost');
                if (totalCostEl) {
                    totalCostEl.textContent = '$0.00';
                    totalCostEl.style.opacity = '1';
                }
                
                // Clear results
                baseEstimate = null;
                currentIntentGraph = null;
                
                // Clear the cost table
                const tbody = document.getElementById('cost-table-body');
                if (tbody) {
                    tbody.innerHTML = '';
                }
                
                // Clear unpriced resources
                const unpricedContainer = document.getElementById('unpriced-resources');
                if (unpricedContainer) {
                    unpricedContainer.innerHTML = '';
                }
            }
        });
    }
    
    // Keep estimate button as fallback (optional)
    if (estimateFromTextBtn) {
        estimateFromTextBtn.addEventListener('click', async () => {
            const text = textarea?.value.trim();
            if (!text) {
                alert('Please paste some Terraform code');
                return;
            }
            
            // Scroll to results section immediately for better UX
            const resultsSection = document.getElementById('results-section');
            if (resultsSection) {
                resultsSection.style.display = 'block';
                // Small delay to ensure section is visible before scrolling
                setTimeout(() => {
                    resultsSection.scrollIntoView({ 
                        behavior: 'smooth', 
                        block: 'start',
                        inline: 'nearest'
                    });
                }, 50);
            }
            
            await estimateFromLocal(text);
        });
    }
    
    // Estimate from files
    if (estimateFromFilesBtn) {
        estimateFromFilesBtn.addEventListener('click', async () => {
            if (uploadedFiles.length === 0) {
                alert('Please upload at least one file');
                return;
            }
            
            // Scroll to results section immediately for better UX
            const resultsSection = document.getElementById('results-section');
            if (resultsSection) {
                resultsSection.style.display = 'block';
                // Small delay to ensure section is visible before scrolling
                setTimeout(() => {
                    resultsSection.scrollIntoView({ 
                        behavior: 'smooth', 
                        block: 'start',
                        inline: 'nearest'
                    });
                }, 50);
            }
            
            await estimateFromLocal(null, uploadedFiles);
        });
    }
}

/**
 * Estimate costs from local Terraform input
 */
async function estimateFromLocal(terraformText = null, files = null, silent = false) {
    try {
        // Show loading state (only if not in silent mode)
        if (!silent) {
        const estimateBtn = terraformText 
            ? document.getElementById('estimate-from-text-btn')
            : document.getElementById('estimate-from-files-btn');
        if (estimateBtn) {
            estimateBtn.disabled = true;
            estimateBtn.textContent = 'Calculating...';
            }
            
            // Store previous cost value and show calculating state
            const totalCostEl = document.getElementById('total-cost');
            if (totalCostEl) {
                // Store current value if it's not already "Calculating..."
                if (totalCostEl.textContent !== 'Calculating...') {
                    totalCostEl.dataset.previousValue = totalCostEl.textContent;
                }
                totalCostEl.textContent = 'Calculating...';
                totalCostEl.style.opacity = '0.6';
            }
        }
        
        let response;
        
        if (terraformText) {
            // Send as form data
            const formData = new FormData();
            formData.append('terraform_text', terraformText);
            
            response = await fetch(apiUrl('/api/terraform/estimate/local'), {
                method: 'POST',
                body: formData,
                headers: {
                    'X-AI-API-Key': getAIAPIKey() || ''
                }
            });
        } else if (files && files.length > 0) {
            // Send files as form data
            const formData = new FormData();
            
            if (files.length === 1 && files[0].name.endsWith('.zip')) {
                formData.append('terraform_file', files[0]);
            } else {
                // For multiple files, create a ZIP (simplified: just send first file for now)
                // In production, you might want to create a ZIP client-side
                formData.append('terraform_file', files[0]);
            }
            
            response = await fetch(apiUrl('/api/terraform/estimate/local'), {
                method: 'POST',
                body: formData,
                headers: {
                    'X-AI-API-Key': getAIAPIKey() || ''
                }
            });
        } else {
            throw new Error('No Terraform input provided');
        }
        
        if (!response.ok) {
            const errorBody = await response.json().catch(() => ({ detail: 'Failed to estimate costs' }));
            const message = errorBody.detail || errorBody.message || 'Failed to estimate costs';
            const error = new Error(message);
            // Tag rate limit errors so we can show a friendlier message
            if (response.status === 429 || errorBody.error === 'rate_limited') {
                error.name = 'RateLimitError';
            }
            throw error;
        }
        
        const data = await response.json();
        
        if (data.status === 'ok') {
            // Store intent graph for scenario API calls
            currentIntentGraph = data.intent_graph;
            
            // Store original Terraform text/files for re-estimation
            if (terraformText) {
                originalTerraformText = terraformText;
            } else if (files && files.length > 0) {
                // Store files for re-estimation
                uploadedFiles = files;
            }
            
            // Render estimate
            const estimateData = {
                estimate: data.estimate,
                insights: data.insights || []
            };
            
            renderEstimate(estimateData);
            
            // Show results section (keep input visible for real-time updates)
            const resultsSection = document.getElementById('results-section');
            if (resultsSection) {
                resultsSection.style.display = 'block';
            }
            
            // Restore opacity
            const totalCostEl = document.getElementById('total-cost');
            if (totalCostEl) {
                totalCostEl.style.opacity = '1';
            }
            
            // Scroll to results section if not in silent mode (but keep input section visible)
            if (!silent) {
                // Scroll to results section with a small delay to ensure DOM is updated
                setTimeout(() => {
            if (resultsSection) {
                        resultsSection.scrollIntoView({ 
                            behavior: 'smooth', 
                            block: 'start',
                            inline: 'nearest'
                        });
                    }
                }, 100);
            }
        }
    } catch (error) {
        console.error('Failed to estimate costs:', error);
        
        // Clear the detailed breakdown table on error
        const tbody = document.getElementById('cost-table-body');
        if (tbody) {
            tbody.innerHTML = '';
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 7;
            cell.textContent = 'Unable to load cost data. Please try again.';
            cell.style.textAlign = 'center';
            cell.style.color = '#9ca3af';
            cell.style.padding = '2rem';
            row.appendChild(cell);
            tbody.appendChild(row);
        }
        
        // Clear unpriced resources section
        const unpricedContainer = document.getElementById('unpriced-resources');
        if (unpricedContainer) {
            unpricedContainer.innerHTML = '';
        }
        
        if (!silent) {
            if (error.name === 'RateLimitError') {
                showRateLimitModal();
            } else {
        alert(`Failed to estimate costs: ${error.message}`);
            }
        }
        
        // Reset cost display on error
        const totalCostEl = document.getElementById('total-cost');
        if (totalCostEl) {
            // Reset to previous value or default to $0.00
            const previousValue = totalCostEl.dataset.previousValue;
            if (previousValue && previousValue !== 'Calculating...') {
                totalCostEl.textContent = previousValue;
            } else {
                // If no previous value or it was calculating, show $0.00
                totalCostEl.textContent = '$0.00';
            }
            totalCostEl.style.opacity = '1';
        }
    } finally {
        // Reset button state (only if not in silent mode)
        if (!silent) {
        const estimateBtn = terraformText 
            ? document.getElementById('estimate-from-text-btn')
            : document.getElementById('estimate-from-files-btn');
        if (estimateBtn) {
            estimateBtn.disabled = false;
            estimateBtn.textContent = 'Estimate Costs';
            }
        }
    }
}

/**
 * Check if we're in share mode (via URL parameter)
 */
function checkShareMode() {
    const urlParams = new URLSearchParams(window.location.search);
    const shareId = urlParams.get('share');
    
    if (shareId) {
        // Load shared snapshot
        loadSharedSnapshot(shareId);
        return true;
    }
    
    // Check if URL path is /share/{id}
    const pathMatch = window.location.pathname.match(/\/share\/([a-f0-9-]+)/);
    if (pathMatch) {
        loadSharedSnapshot(pathMatch[1]);
        return true;
    }
    
    return false;
}

/**
 * Load shared snapshot data
 */
async function loadSharedSnapshot(snapshotId) {
    try {
        const response = await fetch(apiUrl(`/api/share/${snapshotId}`));
        if (!response.ok) {
            throw new Error('Failed to load shared estimate');
        }
        
        const data = await response.json();
        
        // Hide input section, show results
        const inputSection = document.getElementById('terraform-input-section');
        const resultsSection = document.getElementById('results-section');
        if (inputSection) inputSection.style.display = 'none';
        if (resultsSection) resultsSection.style.display = 'block';
        
        // Add read-only banner
        addReadOnlyBanner();
        
        // Render the estimate
        if (data.estimate) {
            renderEstimate({
                estimate: data.estimate,
                insights: data.insights || [],
                scenario_result: data.scenario_result || null
            });
        }
        
        // Scroll to results
        resultsSection?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
        console.error('Failed to load shared estimate:', error);
        alert('Failed to load shared estimate. The link may have expired or is invalid.');
    }
}

/**
 * Add read-only banner for shared views
 */
function addReadOnlyBanner() {
    // Remove existing banner if any
    const existingBanner = document.getElementById('read-only-banner');
    if (existingBanner) {
        existingBanner.remove();
    }
    
    // Create banner
    const banner = document.createElement('div');
    banner.id = 'read-only-banner';
    banner.className = 'read-only-banner';
    banner.innerHTML = `
        <div class="read-only-banner-content">
            <span class="read-only-icon">🔒</span>
            <span class="read-only-text">Read-only shared estimate</span>
        </div>
    `;
    
    // Insert at top of body
    document.body.insertBefore(banner, document.body.firstChild);
    
        // Hide interactive controls (support both landing.html and index.html)
        const controlsToHide = [
            '#terraform-input-section',
            '.try-it',
            '.hero-actions',
            '.region-comparison-control',
            '.traffic-assumptions',
            '.autoscaling-control',
            '#ai-key-section'
        ];
    
    controlsToHide.forEach(selector => {
        const elements = document.querySelectorAll(selector);
        elements.forEach(el => {
            el.style.display = 'none';
        });
    });
}

/**
 * Initialize traffic assumptions input with real-time updates
 * NOTE: Traffic assumptions removed per user request - this function is kept for compatibility but does nothing
 */
function initTrafficInput() {
    // Traffic assumptions feature removed - function kept for compatibility
    return;
}

/**
 * Initialize time unit selector
 */
function initTimeUnitSelector() {
    const timeUnitSelect = document.getElementById('time-unit');
    const customValueInput = document.getElementById('custom-value-input');
    
    if (!timeUnitSelect) return;
    
    // Show/hide custom value input based on selection
    function updateCustomInputVisibility() {
        const selectedUnit = timeUnitSelect.value;
        if (customValueInput) {
            if (selectedUnit === 'hours' || selectedUnit === 'users') {
                customValueInput.style.display = 'inline-block';
                customValueInput.placeholder = selectedUnit === 'hours' ? 'Hours' : 'Users';
                if (!customValueInput.value) {
                    customValueInput.value = selectedUnit === 'hours' ? '730' : '100';
                    customValue = parseInt(customValueInput.value, 10);
                }
            } else {
                customValueInput.style.display = 'none';
                customValue = null;
            }
        }
    }
    
    // Handle unit change
    timeUnitSelect.addEventListener('change', (e) => {
        currentTimeUnit = e.target.value;
        updateCustomInputVisibility();
        
        // Update estimate display if we have an estimate
        if (baseEstimate) {
            renderSummary(baseEstimate, currentScenario);
            // Re-render cost drivers and table
            if (baseEstimate.line_items) {
                renderCostDrivers(baseEstimate.line_items, baseEstimate.total_monthly_cost_usd);
                renderCostTable(baseEstimate.line_items);
            }
        }
    });
    
    // Handle custom value change (debounced)
    if (customValueInput) {
        let debounceTimer = null;
        customValueInput.addEventListener('input', (e) => {
            if (debounceTimer) {
                clearTimeout(debounceTimer);
            }
            
            debounceTimer = setTimeout(() => {
                const value = parseInt(e.target.value, 10);
                if (!isNaN(value) && value > 0) {
                    customValue = value;
                    
                    // Update estimate display if we have an estimate
                    if (baseEstimate) {
                        renderSummary(baseEstimate, currentScenario);
                        // Re-render cost drivers and table
                        if (baseEstimate.line_items) {
                            renderCostDrivers(baseEstimate.line_items, baseEstimate.total_monthly_cost_usd);
                            renderCostTable(baseEstimate.line_items);
                        }
                    }
                }
            }, 300);
        });
    }
    
    // Initialize visibility
    updateCustomInputVisibility();
}

/**
 * Update estimate with new users value
 */
async function updateEstimateWithUsers(users) {
    if (!currentIntentGraph || !baseEstimate) {
        return;
    }
    
    try {
        // Show subtle loading indicator
        const totalCostEl = document.getElementById('total-cost');
        const originalText = totalCostEl ? totalCostEl.textContent : '';
        if (totalCostEl) {
            totalCostEl.style.opacity = '0.6';
        }
        
        // Call scenario API with users parameter
        const endpoint = apiUrl('/api/terraform/estimate/scenario');
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                intent_graph: currentIntentGraph,
                scenario: {
                    users: users
                }
            })
        });
        
        if (!response.ok) {
            throw new Error(`Scenario API error: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.status === 'ok' && data.scenario_result) {
            // Update current scenario
            currentScenario = { users: users };
            
            // Create estimate data structure with scenario result
            const estimateData = {
                estimate: data.scenario_result.scenario_estimate,
                scenario_result: data.scenario_result,
                insights: null
            };
            
            renderEstimate(estimateData, true);
        }
        
        // Restore opacity
        if (totalCostEl) {
            totalCostEl.style.opacity = '1';
        }
    } catch (error) {
        console.error('Failed to update estimate with users:', error);
        // Silently fail - don't show alert for real-time updates
        // Restore opacity
        const totalCostEl = document.getElementById('total-cost');
        if (totalCostEl) {
            totalCostEl.style.opacity = '1';
        }
    }
}

/**
 * Initialize app
 */
function init() {
    // Check if we're in share mode first
    if (checkShareMode()) {
        // Share mode - don't initialize input controls
        return;
    }
    
    // Initialize Terraform input section first
    initTerraformInput();
    
    // Initialize interactive components
    initBreakdownToggle();
    initRegionDropdown();
    initResetButton();
    initTrafficInput();
    initTimeUnitSelector();
    initExportControls();
    initShareControls();
    initRateLimitModal();
    
    // Don't render sample data on load - wait for user input
    // Results section starts hidden (support both landing.html and index.html)
    const resultsSection = document.getElementById('results-section');
    if (resultsSection) {
        resultsSection.style.display = 'none';
    }
    
    // Add smooth scroll behavior for anchor links (landing page)
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            const href = this.getAttribute('href');
            if (href !== '#' && href.startsWith('#')) {
                e.preventDefault();
                const target = document.querySelector(href);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
        });
    });
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}