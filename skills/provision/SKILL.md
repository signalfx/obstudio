---
name: provision
description: >-
  Generate Terraform dashboards, SignalFx detectors, and alert rule
  definitions from verified KPIs in .observe/inventory.md. Populates
  .observe/terraform/ and .observe/alerts/. Use when the user types
  /provision or asks for dashboards, detectors, or alert configs.
---

# Provision -- Infrastructure Provisioning

## Overview

Read the verified KPIs from `.observe/inventory.md`, generate Terraform
configurations for Splunk Observability Cloud dashboards and detectors,
and produce alert rule definitions for Prometheus, Grafana, and
PagerDuty. Also populates the Alerts and Dashboard Recommendations
sections in `inventory.md`. All output goes into the existing
`.observe/` directory.

## When to Use

- After `/verify` confirms telemetry is flowing
- User asks for "dashboards", "detectors", "alerts", or "terraform"
- Regenerating IaC after KPI changes

**When NOT to use:** If `.observe/inventory.md` does not exist or has
no Verified=OK rows, tell the user to run `/audit`, `/instrument`, and
`/verify` first. Provisioning without verified signals produces configs
that reference non-existent telemetry.

## Process

**Before starting, prompt the user for confirmation:**

> "I'll generate Terraform dashboards, detectors, and alert rules
> based on the N verified KPIs in your inventory. This will populate
> `.observe/terraform/` and `.observe/alerts/`. Proceed?"

Only continue if the user confirms.

### Step 1 -- Read Verified KPIs

1. Read `.observe/inventory.md`.
2. Extract KPI rows where Verified=OK.
3. For each KPI, note: Signal Name, Component, metric type (counter,
   histogram, gauge), and whether it is Standard or Business class.
4. If no Verified=OK rows, stop: "No verified KPIs to provision."

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
- Per-KPI threshold variables (e.g., `latency_p99_warning_ms`)

#### `dashboards.tf`

For each component group in the inventory:
- Create a `signalfx_dashboard_group` resource
- Create a `signalfx_dashboard` with charts for each KPI:
  - Counters -> line chart showing rate
  - Histograms -> line chart showing p50/p95/p99
  - Gauges -> single-value chart with thresholds

#### `detectors.tf`

For each KPI, create a `signalfx_detector` resource:
- **Latency KPIs**: static threshold on p99 (warning), p99 (critical)
- **Error KPIs**: percentage threshold (>5% warning, >50% critical)
- **Saturation KPIs**: threshold on gauge value (>80% warning, >90%
  critical)
- **Traffic KPIs**: sudden change detector (drop >50%)
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

Generate one rule per KPI using the same threshold logic as detectors.

#### `grafana.yaml`

Grafana alert rule definitions matching the Prometheus rules, formatted
for Grafana provisioning API.

#### `pagerduty.yaml`

PagerDuty service integration templates referencing the alert names
and severity mappings.

### Step 4 -- Update Inventory

1. Populate the **Alerts** section (section 7) in
   `.observe/inventory.md` with a table:

   | Alert Name | KPI | Condition | Severity | Runbook |
   |------------|-----|-----------|----------|---------|

2. Populate the **Dashboard Recommendations** section (section 8) with
   concrete chart specs derived from the generated dashboards.

3. Present summary: N dashboards, N detectors, N alert rules generated.

## Red Flags

- Terraform references a metric name not present in the inventory
- Detector thresholds hardcoded instead of using variables
- Alert rules missing severity labels
- Dashboard charts with no data source (signal name mismatch)
- Provisioning run without any Verified=OK KPIs

## Verification

- [ ] `terraform validate` passes on `.observe/terraform/`
- [ ] Alert YAML files parse without errors
- [ ] Every Verified=OK KPI has at least one detector/alert rule
- [ ] Alerts section in `inventory.md` is populated (not placeholder)
- [ ] Dashboard Recommendations section is populated
- [ ] All threshold values use variables, not hardcoded numbers
