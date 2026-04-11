---
name: splunk-provision
description: >-
  Generate Terraform dashboards, SignalFx detectors, and alert rule
  definitions from verified KPIs in .observe/inventory.md. Populates
  .observe/terraform/ and .observe/alerts/. Use when the user types
  /splunk-provision, asks for "dashboards", "detectors", "alert configs",
  "generate terraform", "create alerts", or "build monitoring config".
  Do NOT use if no verified KPIs exist -- use /splunk-verify first.
metadata:
  author: splunk-inc
  version: 0.0.1
  category: observability
---

# Provision -- Infrastructure Provisioning

## Overview

Read the verified signals from the Spans, Metrics, and Logs tables in
`.observe/inventory.md`, generate Terraform configurations for Splunk
Observability Cloud dashboards and detectors, and produce alert rule
definitions for Prometheus, Grafana, and PagerDuty. Also populates the
Alerts and Dashboard Recommendations sections in `inventory.md`. All
output goes into the existing `.observe/` directory.

## When to Use

- After `/splunk-verify` confirms telemetry is flowing
- User asks for "dashboards", "detectors", "alerts", or "terraform"
- Regenerating IaC after signal changes

**When NOT to use:** If `.observe/inventory.md` does not exist or has
no Verified=OK rows across the Spans, Metrics, and Logs tables, tell
the user to run `/splunk-audit`, `/splunk-instrument`, and `/splunk-verify`
first. Provisioning without verified signals produces configs that
reference non-existent telemetry.

## Process

**Before starting, prompt the user for confirmation:**

> "I'll generate Terraform dashboards, detectors, and alert rules
> based on the N verified KPIs in your inventory. This will populate
> `.observe/terraform/` and `.observe/alerts/`. Proceed?"

Only continue if the user confirms.

### Step 1 -- Read Verified Signals

1. Read `.observe/inventory.md`.
2. Parse the Spans, Metrics, and Logs tables. Extract rows where
   Verified=OK.
3. For each signal, note: Signal Name, Component, Category (OOB /
   Custom / Derived), and for metrics the Type column (Counter,
   Histogram, Gauge).
4. If no Verified=OK rows across any table, stop: "No verified
   signals to provision."

### Step 2 -- Generate Terraform

Create or update files in `.observe/terraform/`:

#### `provider.tf`

```hcl
terraform {
  required_providers {
    signalfx = {
      source  = "splunk-terraform/signalfx"
      version = "~> 9.0"
    }
  }
}

provider "signalfx" {
  auth_token = var.signalfx_auth_token
  api_url    = var.signalfx_api_url
}
```

#### `variables.tf`

Define configurable thresholds and metadata:
- `service_name` -- from inventory Service Overview
- `environment` -- deployment environment (default: `production`)
- `signalfx_auth_token` -- sensitive, no default
- `signalfx_api_url` -- default Splunk endpoint
- Per-SLI threshold variables (e.g., `latency_p99_warning_ms`)

#### `dashboards.tf`

For each component group in the inventory:
- Create a `signalfx_dashboard_group` resource
- Create a `signalfx_dashboard` with charts sourced from the Metrics
  table:
  - Counters -> line chart showing rate
  - Histograms -> line chart showing p50/p95/p99
  - Gauges -> single-value chart with thresholds

#### `detectors.tf`

For each verified metric, create a `signalfx_detector` resource.
Use the SLIs column to determine the golden signal type for threshold
selection:
- **Latency SLIs**: static threshold on p99 (warning), p99 (critical)
- **Error SLIs**: percentage threshold (>5% warning, >50% critical)
- **Saturation SLIs**: threshold on gauge value (>80% warning, >90%
  critical)
- **Traffic SLIs**: sudden change detector (drop >50%)
- Use `var.*` references for all threshold values

### Step 3 -- Generate Alert Rules

Create or update files in `.observe/alerts/`:

#### `prometheus-rules.yaml`

```yaml
groups:
  - name: <service-name>
    rules:
      - alert: <AlertName>
        expr: <PromQL expression using signal name>
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "<description>"
          runbook: "<brief response action>"
```

Generate one rule per verified metric using the same threshold logic as detectors.

#### `grafana.yaml`

Grafana alert rule definitions matching the Prometheus rules, formatted
for Grafana provisioning API.

#### `pagerduty.yaml`

PagerDuty service integration templates referencing the alert names
and severity mappings.

### Step 4 -- Update Inventory

1. Populate the **Alerts** section (section 10) in
   `.observe/inventory.md` with a table:

   | Alert Name | SLI | Condition | Severity | Runbook |
   |------------|-----|-----------|----------|---------|

2. Populate the **Dashboard Recommendations** section (section 11) with
   concrete chart specs derived from the generated dashboards.

3. Present summary: N dashboards, N detectors, N alert rules generated.

## Examples

### Example 1: Provision dashboards for a verified Flask service

**User says:** "Generate terraform dashboards for this service"

**Actions:**
1. Read inventory: 3 Spans, 6 Metrics, 1 Log with Verified=OK
2. Prompt user for confirmation
3. Generate `provider.tf`, `variables.tf` with threshold variables
4. Generate `dashboards.tf` with 2 dashboard groups (HTTP, Business) from Metrics table
5. Generate `detectors.tf` with detectors per verified metric (latency p99, error %, etc.)
6. Generate `prometheus-rules.yaml`, `grafana.yaml`, `pagerduty.yaml`
7. Update inventory sections 10-11

**Result:** `.observe/terraform/` and `.observe/alerts/` populated. `terraform validate` passes.

### Example 2: Regenerate after adding new verified KPIs

**User says:** "I verified 3 new KPIs, update the terraform"

**Actions:**
1. Read inventory: 3 new Verified=OK signals across Metrics and Spans tables
2. Add new detectors to `detectors.tf`, new charts to `dashboards.tf`
3. Append new alert rules to each alert file
4. Update inventory Alerts and Dashboard tables

**Result:** Existing configs preserved, new KPIs added incrementally.

## Red Flags

- Terraform references a metric name not present in the Metrics table
- Detector thresholds hardcoded instead of using variables
- Alert rules missing severity labels
- Dashboard charts with no data source (signal name mismatch)
- Provisioning run without any Verified=OK signals

## Troubleshooting

**Error:** `terraform validate` fails with "unknown resource type"
**Cause:** The `signalfx` provider is not configured or the version constraint is wrong.
**Solution:** Ensure `provider.tf` includes the `splunk-terraform/signalfx` source with a valid version constraint. Run `terraform init` before `validate`.

**Error:** Alert rules reference a metric name not in the Metrics table
**Cause:** Signal name was changed in the inventory after initial provisioning.
**Solution:** Re-read the inventory and regenerate the affected detector/alert. Use the current Signal Name column value from the Metrics table.

**Error:** No Verified=OK signals found
**Cause:** Provisioning was attempted before verification.
**Solution:** Run `/splunk-verify` first to confirm telemetry is flowing before generating configs.

## Verification

- [ ] `terraform validate` passes on `.observe/terraform/`
- [ ] Alert YAML files parse without errors
- [ ] Every Verified=OK metric has at least one detector/alert rule
- [ ] Alerts section in `inventory.md` is populated (not placeholder)
- [ ] Dashboard Recommendations section is populated
- [ ] All threshold values use variables, not hardcoded numbers
