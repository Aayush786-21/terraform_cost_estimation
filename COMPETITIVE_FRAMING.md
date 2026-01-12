# Competitive Framing

## Why This Category Exists

Cloud cost understanding happens in different phases of the infrastructure lifecycle. Existing tools excel at tracking costs *after* infrastructure is deployed, optimizing *existing* spend, or providing *post-deployment* insights.

This product exists because teams need cost understanding *before* deployment—during design and planning, when decisions can still be changed. It's not about replacing existing tools. It's about filling a gap in the timeline: the period between "we're designing infrastructure" and "we're tracking actual costs."

**The gap:** Honest cost conversations during design, with assumptions shown, without optimization pressure.

---

## 1. Cloud Provider Billing Tools

**Examples:** AWS Cost Explorer, Azure Cost Management, GCP Billing Console

### A) What These Tools Are Good At

- Tracking actual spending from real resource usage
- Showing historical cost trends and patterns
- Identifying unexpected cost spikes or anomalies
- Providing detailed billing breakdowns by service, region, and time period
- Budget alerts and cost forecasting based on actual usage
- Integration with cloud provider ecosystems

### B) When Teams Typically Use Them

- **Timing:** After infrastructure is deployed and running
- **Frequency:** Daily, weekly, or monthly reviews
- **Users:** Finance teams, DevOps leads, cost optimization teams
- **Context:** Monitoring ongoing spend, investigating billing questions, optimizing existing infrastructure

### C) Where They Fall Short (For This Problem)

These tools require infrastructure to be running before they can provide cost data. They answer "What did this cost?" not "What will this cost?"

During design and planning phases, when you're choosing regions, instance sizes, and services, billing tools can't help because there's no actual usage to track yet. They're built for post-deployment cost management, not pre-deployment cost understanding.

### D) How This Product Complements Them

**This product helps you understand costs *before* deployment, so you can make informed decisions during design.**

Billing tools track what happened. This product helps you understand what *will* happen.

**Typical workflow:**
1. Use this product during design to understand cost implications
2. Deploy infrastructure based on informed decisions
3. Use billing tools to track actual costs and optimize over time

They work together: this product for planning, billing tools for tracking.

---

## 2. Engineering Cost Estimation Tools

**Examples:** Infracost

### A) What These Tools Are Good At

- Estimating costs directly from Terraform configuration
- CI/CD integration for cost checks in pull requests
- Fast, automated cost calculations
- Preventing expensive infrastructure from being deployed
- Cost policy enforcement and guardrails

### B) When Teams Typically Use Them

- **Timing:** During code review, before merge/deploy
- **Frequency:** On every pull request or infrastructure change
- **Users:** Engineering teams, DevOps engineers
- **Context:** Preventing cost mistakes, enforcing cost policies, catching expensive changes

### C) Where They Fall Short (For This Problem)

These tools are optimized for *preventing* expensive deployments and *enforcing* cost policies. They're built for "stop bad things" not "understand trade-offs."

They excel at fast, automated checks but typically don't emphasize:
- Showing assumptions and uncertainty explicitly
- Scenario exploration without pressure to optimize
- Team conversations about cost trade-offs
- Understanding *why* costs are what they are

They're designed for enforcement and prevention, not exploration and understanding.

### D) How This Product Complements Them

**This product helps you explore and understand costs during design, so you can make informed decisions before code review.**

Infracost prevents expensive mistakes. This product helps you understand cost implications and explore alternatives.

**Typical workflow:**
1. Use this product during design to explore scenarios and understand costs
2. Make informed decisions about infrastructure choices
3. Use Infracost in CI/CD to catch mistakes and enforce policies

They work together: this product for exploration and understanding, Infracost for enforcement and prevention.

---

## 3. Spreadsheets / Manual Estimation

**Examples:** Google Sheets, Excel, internal documentation

### A) What These Tools Are Good At

- Complete flexibility in modeling and calculation
- Custom formulas and assumptions
- Team collaboration and commenting
- Integration with existing workflows
- No learning curve for teams already using spreadsheets
- Free and accessible

### B) When Teams Typically Use Them

- **Timing:** During planning, before deployment
- **Frequency:** Ad-hoc, when cost estimates are needed
- **Users:** Engineers, architects, finance teams
- **Context:** Budget planning, architecture reviews, stakeholder presentations

### C) Where They Fall Short (For This Problem)

Spreadsheets require manual work: looking up pricing, calculating costs, maintaining formulas, updating when pricing changes. They're time-consuming and error-prone.

They also don't automatically:
- Pull current pricing from cloud provider APIs
- Show confidence levels or uncertainty
- Handle complex scenarios (region comparisons, autoscaling assumptions)
- Provide structured cost breakdowns from Terraform
- Generate shareable, read-only views

Most importantly, spreadsheets hide assumptions. It's hard to see what assumptions went into a calculation, and those assumptions can become outdated or forgotten.

### D) How This Product Complements Them

**This product automates cost estimation from Terraform and makes assumptions explicit, so you can focus on decisions instead of calculations.**

Spreadsheets give you flexibility. This product gives you automation and clarity.

**Typical workflow:**
1. Use this product to get automated cost estimates with explicit assumptions
2. Export to CSV for further analysis in spreadsheets if needed
3. Share read-only links for team discussions

They work together: this product for automated estimation and assumption clarity, spreadsheets for custom analysis and reporting.

---

## Comparison Summary

### Quick Reference Table

| Tool Category | When It's Used | What It Answers | What It Doesn't Answer |
|--------------|----------------|-----------------|----------------------|
| **Cloud Provider Billing Tools** | After deployment | "What did this cost?"<br>"Why did costs spike?"<br>"How can we optimize?" | "What will this cost?"<br>"What are the cost implications of this design?" |
| **Engineering Cost Estimation Tools** | During code review | "Is this too expensive?"<br>"Does this violate our cost policy?" | "What are the cost trade-offs?"<br>"How do scenarios compare?" |
| **Spreadsheets / Manual** | During planning | "What's our budget estimate?"<br>"What if we change X?" | "What are current prices?"<br>"What assumptions are hidden?" |
| **This Product** | Before deployment, during design | "What will this cost?"<br>"What assumptions drive this?"<br>"How do scenarios compare?" | "What did this cost?"<br>"How can we optimize?"<br>"Is this too expensive?" |

---

## Positioning Summary

### When to Use This Product

**Use this product when:**
- You're designing new infrastructure from Terraform
- You need to understand cost implications before deployment
- You want to explore scenarios and compare alternatives
- You need to have cost conversations with your team
- You want assumptions and uncertainty shown explicitly

**Do NOT use this product when:**
- You need to track actual spending (use billing tools)
- You need to enforce cost policies in CI/CD (use Infracost)
- You need custom financial modeling (use spreadsheets)
- Infrastructure is already deployed (use billing tools)

### The Mental Model

**This product is for understanding and conversation.**

- Billing tools are for tracking and optimizing
- Infracost is for preventing and enforcing
- Spreadsheets are for custom analysis
- This product is for exploring and understanding

They're not competitors. They're complementary tools for different phases and purposes.

---

## Key Messaging Points

### For Landing Pages

"Designed for cost understanding *before* deployment, when decisions can still be changed. Works alongside billing tools (for tracking), Infracost (for enforcement), and spreadsheets (for custom analysis)."

### For Sales Conversations

"This product fills a gap in the timeline: the period between designing infrastructure and tracking actual costs. It's not about replacing existing tools. It's about understanding costs during design, so you can make informed decisions before deployment."

### For Documentation

"Use this product during design and planning. Use billing tools for tracking actual costs. Use Infracost for CI/CD enforcement. Use spreadsheets for custom analysis. They work together."

---

## Tone Checklist

✅ **Calm** — No urgency, no fear-based language  
✅ **Respectful** — Acknowledge strengths of other tools  
✅ **Non-defensive** — Not "we're better," but "we're different"  
✅ **Factual** — Focus on timing and use cases  
✅ **Complementary** — Emphasize coexistence, not replacement  

---

## Usage Guidelines

This framing should be used for:
- **Landing page comparison section** — Use the comparison table
- **Sales conversations** — Use the positioning summary
- **Documentation / README** — Use the "When to Use" section
- **Early user onboarding** — Use the mental model section

**Key principle:** Frame around timing and intent, not superiority. Help users understand when to use which tool, not which tool is "better."
