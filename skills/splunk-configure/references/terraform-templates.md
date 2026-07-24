# Detector Terraform Core

Read for every detector Terraform run. This file is self-contained for generic
RED detectors; do not load `../../references/signalflow-patterns.md` for the
normal detector path.

## Files and provider

Create `detectors.tf`, `variables.tf`, `terraform.tfvars.example`, and
`.gitignore`. Pin the provider source `splunk-terraform/signalfx` to a compatible
major version. Configure `auth_token = var.api_token` and API/app URLs from
`var.realm`. `realm` is provider routing only; never use `var.realm` as a
SignalFlow telemetry filter.

Declare `realm`, sensitive `api_token`, `service_name`, and
`notification_channel` as string variables without credential defaults.
Declare one numeric threshold/baseline variable per detector. Sanitize HCL
labels by replacing dots/hyphens with underscores and preventing a leading
digit; preserve the original metric name inside `data(...)`.

## Detector resource shape

Every resource uses this shape and exactly one published detect label:

```hcl
resource "signalfx_detector" "<category>_<metric_id>" {
  name         = "${var.service_name} <Category> - <metric_name>"
  description  = "<source-backed purpose>"
  program_text = <<-EOF
    <program>
  EOF

  rule {
    description   = "<condition>"
    severity      = "<Critical|Major|Warning>"
    detect_label  = "<Alert Label>"
    notifications = [var.notification_channel]
  }
}
```

The `detect_label` must exactly match the label published by the detection
statement. Every stream must aggregate before `.publish(...)`. Use only exact
source-backed low-cardinality filters/group-bys; never raw prompts/content,
secrets, URLs, or user/session/request/trace IDs.

## Generic RED programs

Use the exact OTel metric and always filter by `service.name`:

```text
# Latency histogram
A = data('<metric>', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')
detect(when(A > threshold(${var.<id>_threshold}))).publish('P99 Latency Too High')

# Error counter
from signalfx.detectors.against_recent import against_recent
A = data('<metric>', filter=filter('service.name', '${var.service_name}')).sum().publish(label='Error Rate')
against_recent.detector_mean_std(stream=A, current_window='5m', historical_window='1h', fire_num_stddev=${var.<id>_stddev}, clear_num_stddev=2.5, orientation='above', ignore_extremes=True, calculation_mode='vanilla').publish('Error Rate Anomaly')

# Throughput counter
from signalfx.detectors.against_recent import against_recent
A = data('<metric>', filter=filter('service.name', '${var.service_name}')).sum().publish(label='Throughput')
against_recent.detector_mean_std(stream=A, current_window='5m', historical_window='1h', fire_num_stddev=${var.<id>_stddev}, clear_num_stddev=2.5, orientation='out_of_band', ignore_extremes=True, calculation_mode='vanilla').publish('Throughput Anomaly')

# Saturation gauge (only with a source-backed safe threshold)
A = data('<metric>', filter=filter('service.name', '${var.service_name}')).mean().publish(label='Saturation')
detect(when(A > threshold(${var.<id>_threshold}))).publish('Saturation Too High')
```

Default severity is Warning for latency/saturation, Critical for error, and
Major for throughput. A 1-second latency or 3-standard-deviation baseline may
be an initial tunable default. Use 85 only for a proven normalized percentage;
raw counts require a source-backed capacity/SLO threshold.

## Route-group variants

When `detector-classification.md` merges same-route counters into a duration
histogram, the latency detector remains the percentile program above. Error and
throughput read the histogram's count rollup:

```text
# Error: route plus proven failure-only outcome
A = data('<histogram>', filter=filter('service.name', '${var.service_name}') and filter('<route-key>', '<route>') and filter('<failure-key>', '<failure-value>'), rollup='count').sum(by=['<failure-key>']).publish(label='Error Rate')

# Throughput: every outcome for the route
A = data('<histogram>', filter=filter('service.name', '${var.service_name}') and filter('<route-key>', '<route>'), rollup='count').sum().publish(label='Throughput')
```

Append the matching static or `against_recent` detection statement. Never add
an outcome filter to throughput. `.count()` counts reporting time series, not
histogram observations; use `rollup='count'` plus `.sum()`. Never wildcard a
response-status key; only `error.type='*'` or another proven failure-only
attribute may use existence matching.

## Specialized routes

If an incident or GenAI classification reference was loaded, also read
`readiness-detector-templates.md`. If dashboards are requested and evidenced,
read `dashboard-terraform-contract.md` and `dashboard-output-contract.md`.
Neither reference belongs on a generic detector-only path.

## Local files

`terraform.tfvars.example` contains empty `realm`, `api_token`, and
`notification_channel`, plus the service name. Never write real credentials.
Generate:

```gitignore
.terraform/
*.tfstate
*.tfstate.*
terraform.tfvars
```

Retain `.terraform.lock.hcl` after a successful init. Terraform apply/publish is
outside configure; hand reviewed detectors to `$splunk-detector-publish` or the
user's chosen Terraform workflow.
