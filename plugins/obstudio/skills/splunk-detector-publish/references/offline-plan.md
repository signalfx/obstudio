# Offline Detector Publish Plan

Read this reference only when network access is unavailable, credentials are
placeholders, or the user requests a preview/dry run. This mode never reads
environment credentials, probes connectivity, calls the Splunk API, or creates,
updates, or deletes a remote detector.

## Parse And Normalize

Parse every `signalfx_detector` in `.observe/terraform/detectors.tf` in HCL
declaration order. Capture its HCL label, resolved name, rules (`severity`,
`detect_label`, notifications), metric, and resolved service filter.

Read `../../references/terraform-normalization.md`. Dedent each `<<-EOF`
`program_text`, trim blank edges, and resolve every `${var.*}` from tfvars and
variable defaults. This includes service name, threshold, stddev, and window
values. Fail rather than guess when HCL is malformed or a value cannot be
resolved.

Before the diff, provide concrete proof for every detector:

```markdown
### Normalized Detector Programs
| Local detector | Metric | Service filter | Exact normalized programText |
|---|---|---|---|
```

Print the complete resolved SignalFlow, not an ellipsis or placeholder. It must
contain no heredoc marker, leading indentation, or unresolved `${var.*}`.

## Offline Classification

Without a successful live inventory, no local detector can be proven present or
absent. Classify every otherwise-valid local spec `UNCERTAIN`, never `COVERED`
or `GAP`. Use a concrete reason such as:

`high_error_rate: live inventory not fetched; metric=checkout.payment.errors +
filter service.name=checkout + Standard origin were not compared, so coverage
or absence cannot be established.`

The detector label, metric, and resolved service filter must be inside each
Reason cell. Adjacent columns alone do not satisfy the reason requirement. If
the local spec is itself ambiguous, name that separate divergence.

Use the core diff shape and always include:

```markdown
### AutoDetect Advisory
Live inventory not fetched — AutoDetect detectors (if any) are org-wide and
advisory only; they would not count as COVERED for service-specific specs.
```

Do not invent live IDs or say the API was searched. A failed or forbidden fetch
is not the same as a successful empty live list.

## Planned Bodies And Future Order

Describe, but do not execute, the exact deterministic order a later online run
would use after fresh classification and confirmation: declaration order among
the rows that are then proven `GAP`. Make the condition explicit; the current
UNCERTAIN rows are not create candidates.

Show a planned body for every local detector with concrete values:

```json
{
  "name": "<resolved detector name>",
  "programText": "<complete normalized SignalFlow>",
  "rules": [
    {
      "severity": "<rule severity>",
      "detectLabel": "<resolved detect label>",
      "notifications": [],
      "disabled": false
    }
  ],
  "description": "Created by splunk-detector-publish from <HCL label>",
  "tags": ["obstudio"]
}
```

HCL `program_text` becomes REST `programText`; HCL `detect_label` becomes REST
`detectLabel`. Do not substitute `<...>` placeholders in the actual response:
each body must show the detector's resolved name, exact normalized program,
every rule severity/detect label, and literal `"tags": ["obstudio"]`.

The future live sequence is one `POST /v2/detector` per freshly confirmed GAP,
sequentially. Explain that 409 is resolved by GET/reuse as COVERED and that no
planned POST may run until an online fetch proves a GAP and the user confirms
that fresh mutation set.

## Stop Boundary And Response

End at the informational confirmation gate. State all of the following:

- no environment credential was read;
- no network call or remote create/update/delete occurred;
- all local verdicts remain UNCERTAIN because live state was not fetched;
- this preview and any answer to it cannot authorize later mutation; and
- a later online run must re-fetch, reclassify, show a new diff with exact GAP
  operations and realm source, then obtain explicit yes/no confirmation.

Do not write `.observe/detector-sync.md` as if it were a live-state ledger. The
offline plan may remain in the response; the later live run owns the resumable
ledger.
