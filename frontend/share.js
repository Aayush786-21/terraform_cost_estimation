/**
 * Shared view for read-only cost estimates.
 * 
 * Fetches snapshot data and renders using the same components as main app.
 */

// Extract snapshot ID from URL
function getSnapshotId() {
    const path = window.location.pathname;
    const match = path.match(/\/share\/([a-f0-9-]+)/);
    return match ? match[1] : null;
}

// Format currency
function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

// Format percentage
function formatPercentage(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'percent',
        minimumFractionDigits: 1,
        maximumFractionDigits: 1
    }).format(value);
}

// Get category display name
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

// Get category icon
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

// Group line items by category
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

// Render cost drivers
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
        card.className = 'cost-driver-card';
        card.dataset.category = categoryData.category;
        
        const percentage = categoryData.percentage;
        
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
        
        container.appendChild(card);
    });
}

// Render cost table
function renderCostTable(lineItems) {
    const tbody = document.getElementById('cost-table-body');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    if (!lineItems || lineItems.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="6" style="text-align: center; color: #9ca3af; padding: var(--space-xl);">No cost data available</td>';
        tbody.appendChild(row);
        return;
    }
    
    lineItems.forEach(item => {
        const row = document.createElement('tr');
        row.className = 'cost-row';
        
        const confidenceClass = item.confidence || 'medium';
        const confidenceDot = `<span class="confidence-indicator ${confidenceClass}"></span>`;
        const confidenceText = (item.confidence || 'medium').charAt(0).toUpperCase() + (item.confidence || 'medium').slice(1);
        
        row.innerHTML = `
            <td>${renderCloudBadge(item.cloud)}</td>
            <td>${item.service || 'N/A'}</td>
            <td><code>${item.resource_name || 'N/A'}</code></td>
            <td>${item.region || 'N/A'}</td>
            <td class="cost-value">${formatCurrency(item.monthly_cost_usd || 0)}</td>
            <td>${confidenceDot} ${confidenceText}</td>
        `;
        
        tbody.appendChild(row);
    });
}

// Render cloud badge
function renderCloudBadge(cloud) {
    const badges = {
        aws: '<span class="cloud-badge aws">AWS</span>',
        azure: '<span class="cloud-badge azure">Azure</span>',
        gcp: '<span class="cloud-badge gcp">GCP</span>'
    };
    return badges[cloud?.toLowerCase()] || cloud || 'N/A';
}

// Render unpriced resources
function renderUnpricedResources(unpricedResources) {
    const section = document.getElementById('unpriced-section');
    const container = document.getElementById('unpriced-resources');
    
    if (!section || !container) return;
    
    if (!unpricedResources || unpricedResources.length === 0) {
        section.style.display = 'none';
        return;
    }
    
    section.style.display = 'block';
    container.innerHTML = '';
    
    unpricedResources.forEach(resource => {
        const item = document.createElement('div');
        item.className = 'unpriced-item';
        item.innerHTML = `
            <div class="unpriced-resource-name"><code>${resource.resource_name || resource.terraform_type || 'Unknown'}</code></div>
            <div class="unpriced-resource-type">${resource.terraform_type || 'N/A'}</div>
            <div class="unpriced-reason">${resource.reason || 'Not priced'}</div>
        `;
        container.appendChild(item);
    });
}

// Render insights
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

// Render summary
function renderSummary(estimate) {
    const totalCostEl = document.getElementById('total-cost');
    const regionEl = document.getElementById('region');
    const coverageBadgesEl = document.getElementById('coverage-badges');
    
    if (totalCostEl) {
        totalCostEl.textContent = formatCurrency(estimate.total_monthly_cost_usd || 0);
    }
    
    if (regionEl) {
        regionEl.textContent = estimate.region || 'N/A';
    }
    
    if (coverageBadgesEl) {
        coverageBadgesEl.innerHTML = '';
        const coverage = estimate.coverage || {};
        
        const clouds = [
            { key: 'aws', label: 'AWS', value: coverage.aws || 'full' },
            { key: 'azure', label: 'Azure', value: coverage.azure },
            { key: 'gcp', label: 'GCP', value: coverage.gcp }
        ].filter(cloud => cloud.value);
        
        clouds.forEach(cloud => {
            const badge = document.createElement('span');
            badge.className = `coverage-badge ${cloud.value}`;
            
            // Format status text for display
            let displayStatus = cloud.value;
            if (cloud.value === 'full') {
                displayStatus = 'COMPLETED';
            } else if (cloud.value === 'partial') {
                displayStatus = 'PARTIAL';
            } else if (cloud.value === 'not_supported_yet') {
                displayStatus = 'NOT YET SUPPORTED';
            }
            
            badge.textContent = `${cloud.label}: ${displayStatus}`;
            coverageBadgesEl.appendChild(badge);
        });
    }
}

// Load and render snapshot
async function loadSnapshot() {
    const snapshotId = getSnapshotId();
    if (!snapshotId) {
        document.body.innerHTML = '<div style="padding: 40px; text-align: center;"><h1>Invalid Share Link</h1><p>The share link is invalid or malformed.</p></div>';
        return;
    }
    
    try {
        const response = await fetch(`/api/share/${snapshotId}`);
        
        if (!response.ok) {
            if (response.status === 404) {
                document.body.innerHTML = '<div style="padding: 40px; text-align: center;"><h1>Share Link Not Found</h1><p>This share link has expired or does not exist. Share links expire after 24 hours.</p></div>';
            } else {
                throw new Error('Failed to load snapshot');
            }
            return;
        }
        
        const data = await response.json();
        const snapshot = data.snapshot;
        
        // Determine which estimate to show
        const estimate = snapshot.scenario_estimate || snapshot.base_estimate;
        
        if (!estimate) {
            document.body.innerHTML = '<div style="padding: 40px; text-align: center;"><h1>Invalid Snapshot</h1><p>The snapshot data is invalid.</p></div>';
            return;
        }
        
        // Render all sections
        renderSummary(estimate);
        renderCostDrivers(estimate.line_items || [], estimate.total_monthly_cost_usd || 0);
        renderCostTable(estimate.line_items || []);
        renderUnpricedResources(estimate.unpriced_resources || []);
        
        // Render insights if available
        if (snapshot.insights && snapshot.insights.length > 0) {
            renderInsights(snapshot.insights);
        } else {
            const container = document.getElementById('insights-container');
            if (container) {
                container.innerHTML = '<p style="color: #9ca3af; font-style: italic;">No insights available for this snapshot.</p>';
            }
        }
        
    } catch (error) {
        console.error('Failed to load snapshot:', error);
        document.body.innerHTML = '<div style="padding: 40px; text-align: center;"><h1>Error Loading Snapshot</h1><p>Failed to load the shared estimate. Please try again later.</p></div>';
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadSnapshot);
} else {
    loadSnapshot();
}
