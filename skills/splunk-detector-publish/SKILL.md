---
name: splunk-detector-publish
description: >-
  Diff local splunk-configure detector specs against live Splunk Observability
  Cloud detectors and create only the confirmed gaps. Reads
  .observe/terraform/detectors.tf, fetches live detectors for the service via
  the Splunk O11y REST API (GET /v2/detector), classifies each local spec as
  COVERED / GAP / UNCERTAIN / AutoDetect-advisory, shows a confirmation diff,
  and creates only the GAPs using POST /v2/detector with if_not_exists logic.
  Writes .observe/detector-sync.md as an idempotent resume ledger. Use when the
  user types $splunk-detector-publish, asks to "sync detectors", "check which detectors are
  missing", "create missing monitors", or "push detector gaps to Splunk".
metadata:
  author: otel-studio
  version: 0.3.0
  category: observability
---

# Detector Publish -- Splunk O11y Detector Gap Analysis and Create

## Overview

Compare locally-generated `signalfx_detector` specs (from `$splunk-configure`)
against **live** Splunk Observability Cloud detectors for the same service.
Create only the genuine gaps; skip anything already covered. Write a persistent
ledger so re-runs are idempotent and auditable.

## When to Use

- After `$splunk-configure` has already produced `.observe/terraform/detectors.tf`
- When the user wants to push only the missing detectors to Splunk O11y without
  duplicating detectors that already exist
- When auditing which detectors are already live vs. which are still missing

**When NOT to use:** If no local spec exists yet, instruct the user to run
`$splunk-configure` first.

## Auth and API

> Shared reference: `../references/splunk-api.md` is the single source of truth
> for auth, the skip-on-500 paginated fetch loop, and HTTP-status handling used
> by all Splunk sync skills. The detector-specific concrete steps below restate
> the parts this skill depends on.

All Splunk O11y calls use the **Splunk REST API** directly — no MCP tool
required. Read credentials from the environment:

| Variable | Purpose |
|---|---|
| `SPLUNK_ACCESS_TOKEN` | Org access token; sent as `X-SF-Token` header |
| `SPLUNK_REALM` | Realm (e.g. `lab0`, `us0`, `us1`); builds the base URL |

Base URL: `https://api.${SPLUNK_REALM}.signalfx.com`

If either variable is missing, stop and tell the user to set them (they are also
used by obstudio for metrics and traces forwarding, so they should already be set).

**Important:** The `/v2/detector` list endpoint has a known server-side bug where
certain offset values return HTTP 500. Always skip-on-500 when paginating — do
not treat it as an auth or hard failure. See Step 3 for the pagination pattern.

## Process

### Step 1 -- Locate Local Specs

Look for `.observe/terraform/detectors.tf` in the repository root.

- If the file exists, proceed to Step 2.
- If the file is missing, stop and respond:

> No local detector spec found at `.observe/terraform/detectors.tf`. Please run
> `$splunk-configure` first to generate the detector Terraform.

Also read `.observe/detectors.md` if it exists — it provides the human summary
and classification rationale that helps resolve ambiguous UNCERTAIN cases.

### Step 2 -- Parse Local Specs

Parse every `signalfx_detector` resource block in `detectors.tf`. For each one
extract:

1. **HCL resource label** (e.g. `latency_http_server_request_duration`)
2. **name** — the string in the `name` field (may reference `${var.service_name}`)
3. **program_text** — the heredoc value of the `program_text` field
4. **rules** — each `rule` block: `severity`, `detect_label`, `notifications`
5. **metric_name** — the first `data('metric.name', ...)` argument in program_text
6. **service_filter** — the `filter('service.name', '...')` value in program_text;
   resolve `${var.service_name}` by reading `terraform.tfvars` (if present) or
   `terraform.tfvars.example` and prompting the user if still unresolvable

**HCL field name is `program_text`; live API field is `programText` — normalize
when comparing.**

Fail fast if the file is not parseable (malformed HCL) and tell the user.

#### Step 2a -- Normalize `program_text` to valid SignalFlow (required before create)

> Shared reference: `../references/terraform-normalization.md` documents this
> normalization (heredoc dedent + resolve every `${var.*}`) once for all sync
> skills. The detector-specific restatement below is what this skill applies.

The raw `program_text` value extracted from HCL is **not** valid SignalFlow and
**must** be normalized before it is sent in any `POST /v2/detector` body. The
Splunk API runs the string through the SignalFlow parser as-is and rejects it
with **HTTP 400** if either of the following is left unhandled. Do this once,
during parsing, and carry the normalized string forward:

1. **Strip indented-heredoc whitespace (`<<-EOF`).** Terraform's `<<-EOF`
   "indented heredoc" deletes the leading whitespace of the *least-indented*
   line at apply time, but the raw bytes between the `<<-EOF` and `EOF` markers
   still carry the editor indentation. SignalFlow treats a leading-whitespace
   line as a syntax error, so reproduce Terraform's behavior: find the smallest
   leading-whitespace run across all non-blank lines and strip exactly that many
   leading characters from every line (i.e. `textwrap.dedent` after trimming the
   trailing marker line). Plain `<<EOF` (no dash) is already flush-left — leave
   it unchanged. Always `.strip()` the final result so a leading/trailing blank
   line never reaches the parser.

2. **Resolve every `${var.*}` reference, not just `service.name`.** Detector
   program text routinely interpolates thresholds, stddev counts, and windows —
   `threshold(${var.saturation_queue_depth_threshold})`,
   `fire_num_stddev=${var...._stddev}`, etc. A literal `${var...}` token is
   invalid SignalFlow. Resolve **all** of them, in this precedence order, before
   create:

   - a matching assignment in `terraform.tfvars` (then `*.auto.tfvars`, then
     `terraform.tfvars.example`), else
   - the `default` value of the matching `variable "<name>" { ... }` block in
     `variables.tf`, else
   - prompt the user for the value (do not guess, and do not POST with an
     unresolved token).

   Substitute the resolved literal for the whole `${var.<name>}` span. Numbers
   are emitted bare (`50.0`), strings keep their SignalFlow quoting as written
   in the surrounding program text.

```python
import re, textwrap

def dedent_heredoc(raw: str) -> str:
    # Mirrors Terraform <<-EOF: strip common leading whitespace, trim blank edges.
    return textwrap.dedent(raw).strip()

def resolve_vars(program_text: str, tf_vars: dict, var_defaults: dict) -> str:
    # tf_vars: name->value from terraform.tfvars / *.auto.tfvars / .example
    # var_defaults: name->default from variables.tf `variable` blocks
    unresolved = []

    def repl(m):
        name = m.group(1)
        if name in tf_vars:
            return str(tf_vars[name])
        if name in var_defaults:
            return str(var_defaults[name])
        unresolved.append(name)
        return m.group(0)

    out = re.sub(r"\$\{var\.([A-Za-z0-9_]+)\}", repl, program_text)
    if unresolved:
        raise ValueError(
            "Unresolved Terraform variables in program_text "
            f"(no tfvars assignment and no default): {sorted(set(unresolved))}. "
            "Prompt the user for these before POSTing the detector."
        )
    return out

# Per spec, during parsing:
program_text = resolve_vars(dedent_heredoc(raw_program_text), tf_vars, var_defaults)
```

Both transforms are pure-string and deterministic; the result is the exact
SignalFlow Splunk would have received had the Terraform been `terraform apply`-d.
Use this normalized `program_text` everywhere downstream — both for COVERED/GAP
comparison and for the create body in Step 6.

### Step 3 -- Fetch Live Detectors

Retrieve all live detectors in the org using the Splunk O11y REST API:

```python
import urllib.request, json, sys
from collections import defaultdict

token = "<SPLUNK_ACCESS_TOKEN>"
realm = "<SPLUNK_REALM>"
base  = f"https://api.{realm}.signalfx.com/v2/detector"

limit = 50          # keep small; large limits hit the 500 bug more often
offset = 0
all_detectors = []
seen_ids = set()
consecutive_empty = 0

while consecutive_empty < 5:
    url = f"{base}?limit={limit}&offset={offset}"
    req = urllib.request.Request(url, headers={"X-SF-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 500:
            # Skip-on-500: the API has a known bug at certain offsets.
            offset += limit
            consecutive_empty += 1
            continue
        raise RuntimeError(f"Splunk API error {e.code} fetching detectors: {e}") from e
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"Failed to fetch detectors: {e}") from e

    batch = data.get("results", [])
    if not batch:
        consecutive_empty += 1
        offset += limit
        continue

    consecutive_empty = 0
    for d in batch:
        if d["id"] not in seen_ids:
            seen_ids.add(d["id"])
            all_detectors.append(d)
    offset += limit
```

Each detector object from the list endpoint includes `id`, `name`,
`programText`, `detectorOrigin`, and `rules`. That is sufficient for
classification — no second per-detector GET is required unless `programText`
is absent or truncated (in that case fetch `GET /v2/detector/{id}`).

If the org has zero detectors, all local specs are GAPs — proceed to Step 4
with an empty live list.

### Step 4 -- Classify Each Local Spec

Apply the coverage model from `references/coverage-model.md` (which builds on the
shared `../references/coverage-decision-tree.md` verdict vocabulary) to assign
each local spec one of four statuses:

**COVERED**
A live Standard (`detectorOrigin != "AutoDetect"`) detector's `programText`
references the same OTel metric name AND filters the same `service.name` or
`sf_service` value. Both conditions must hold simultaneously.

**GAP**
No live Standard detector matches on both the metric name AND the service
filter. This spec must be created.

**UNCERTAIN**
The metric name appears in a live detector's programText but the service filter
is absent, uses a different dimension key, or the filter value is ambiguous
(e.g. a wildcard). Show to the user; do not auto-create and do not auto-cover.

**Offline / fetch-unavailable fallback**
If the live detector list cannot be fetched (no network access, auth unavailable,
or the API is unreachable), treat every local spec as **GAP** — not UNCERTAIN.
UNCERTAIN requires evidence that the metric exists somewhere in a live detector
with an ambiguous filter; without a live list there is no such evidence, so the
safe default is GAP. Describe the POST /v2/detector payload you would send for
each, stop at the confirmation gate, and note that the user must confirm once
the API is reachable.

**AutoDetect advisory (informational only)**
For latency or error specs: note any live detector with
`detectorOrigin == "AutoDetect"` that references `service.request` metrics as a
*possible overlap* advisory line. AutoDetect detectors are org-wide and never
filter by `service.name`, so they cannot count as COVERED for a specific service.
They are advisory only and do NOT change the spec's classification.

Always include the `### AutoDetect Advisory` section in the confirmation diff,
even when offline or when no AutoDetect detectors were fetched. In offline
context, write: "Live inventory not fetched — AutoDetect detectors (if any)
are org-wide and advisory only; they would not count as COVERED for
service-specific specs." This section is required in every diff output.

See `references/coverage-model.md` for worked examples and edge cases.

### Step 5 -- Confirmation Diff

Print a structured diff table before any writes. Do not proceed until the user
explicitly confirms.

```
## Detector Publish Diff — <service-name>

### COVERED (N) — no action needed
| Local Spec | Metric | Matched Live Detector |
|------------|--------|----------------------|
| latency_<id> | <metric> | <live detector name (id)> |

### GAP (N) — will be created
| Local Spec | Metric | Severity | Why no match |
|------------|--------|----------|--------------|
| error_<id> | <metric> | Critical | no live detector with this metric + service filter |

### UNCERTAIN (N) — review manually
| Local Spec | Metric | Live Detector | Issue |
|------------|--------|---------------|-------|
| saturation_<id> | <metric> | <name> | service filter absent in live programText |

### AutoDetect Advisory (N) — informational
| Local Spec | Metric | AutoDetect Detector | Note |
|------------|--------|---------------------|------|
| latency_<id> | <metric> | <org-wide detector name> | org-wide AutoDetect, not service-scoped; does not substitute for a custom detector |

---
N GAPs will be created. N UNCERTAIN specs need manual review.
Confirm? (yes/no)
```

If there are zero GAPs and zero UNCERTAINs, respond:

> All N local detector specs are already COVERED by live Splunk detectors. Nothing
> to create. Ledger written to `.observe/detector-sync.md`.

Then skip to Step 7 (write the ledger).

### Step 6 -- Create GAPs

After the user confirms, for each GAP spec:

1. First offer a dry run: construct the POST body and print it without sending.
   If the user says "dry run first" or "preview", show the payload before creating.
2. POST to `https://api.${SPLUNK_REALM}.signalfx.com/v2/detector`:
   ```python
   body = {
       "name": resolved_name,           # ${var.service_name} substituted
       "programText": program_text,     # NORMALIZED per Step 2a: heredoc dedented
                                        # AND all ${var.*} resolved — never the raw
                                        # HCL value, or Splunk returns HTTP 400
       "rules": [
           {
               "severity": rule["severity"],
               "detectLabel": rule["detect_label"],
               "notifications": rule.get("notifications", []),
               "disabled": False,
           }
           for rule in rules
       ],
       "description": f"Created by splunk-detector-publish from {hcl_label}",
   }
   data = json.dumps(body).encode("utf-8")
   req = urllib.request.Request(
       f"https://api.{realm}.signalfx.com/v2/detector",
       data=data,
       method="POST",
       headers={"X-SF-Token": token, "Content-Type": "application/json"},
   )
   try:
       with urllib.request.urlopen(req, timeout=30) as resp:
           status = resp.status
           created = json.load(resp)
   except urllib.error.HTTPError as e:
       status = e.code          # branch on status below; do not raise blindly
       created = None
   ```
   Note: HCL uses `detect_label`; the REST API uses `detectLabel` — normalize.
   `urllib` raises `HTTPError` for any non-2xx response, so branch on `status`:
3. On HTTP 200: record `created["id"]` and `created["name"]` plus
   `https://app.${SPLUNK_REALM}.signalfx.com/#/detector/{id}` for the ledger.
4. On HTTP 409 or a duplicate-name response: reclassify as COVERED in the ledger
   (race condition between diff and create). Not an error.
5. On HTTP 403: token lacks detector-write scope. Stop and tell the user.
6. On any other error: record the failure and continue with remaining GAPs.
   Report all failures in the final summary.

Create GAPs sequentially, not in parallel, to make progress visible and errors
attributable.

### Step 7 -- Write Ledger

> Shared reference: `../references/ledger-template.md` defines the resumable
> ledger shape (summary counts + per-item status table with a required non-empty
> **Reason** column) used by all sync skills. The detector ledger below follows
> it.

Write or overwrite `.observe/detector-sync.md` after every run (success, partial
failure, or zero-gap no-op):

```markdown
# Detector Publish Ledger: <service-name>

**Date:** <YYYY-MM-DD>
**Local spec:** `.observe/terraform/detectors.tf`
**Service filter resolved to:** `<service_name_value>`

## Summary

| Status | Count |
|--------|-------|
| COVERED | N |
| GAP → Created | N |
| GAP → Failed | N |
| UNCERTAIN | N |
| AutoDetect Advisory | N |

## Detector Status

| Local Spec | Metric | Status | Detector ID | Link | Notes |
|------------|--------|--------|-------------|------|-------|
| latency_<id> | <metric> | COVERED | <id> | | matched live detector "<name>" |
| error_<id> | <metric> | CREATED | <id> | <link> | |
| saturation_<id> | <metric> | UNCERTAIN | | | service filter absent in live programText |
| latency_<id2> | <metric> | AutoDetect Advisory | | | org-wide AutoDetect detector noted |

---
*Generated by splunk-detector-publish on <YYYY-MM-DD>*
```

A re-run on a fully-synced service will re-read the live state and produce an
all-COVERED ledger — it will not re-create anything because the GAP check is
re-evaluated fresh.

### Step 8 -- Chat Summary

After the ledger is written, present a concise summary:

```
## Detector Publish Complete — <service-name>

| Status | Count |
|--------|-------|
| Already covered | N |
| Created | N |
| Uncertain (manual review) | N |
| AutoDetect advisory | N |

Ledger: `.observe/detector-sync.md`
```

If any GAPs failed to create, list them explicitly with the error message.
If UNCERTAIN specs remain, recommend running `$splunk-detector-publish` again after
reviewing and resolving the ambiguous live detectors manually.

## Red Flags

- `.observe/terraform/detectors.tf` missing — run `$splunk-configure` first
- `SPLUNK_ACCESS_TOKEN` or `SPLUNK_REALM` not set — stop and tell the user
- `service_name` not resolvable from `terraform.tfvars` or `.example` — prompt
  the user before fetching live detectors
- All offsets returning HTTP 500 continuously (not intermittent) — likely an
  auth failure masquerading as 500; verify the token is valid
- A live detector has `programText` missing or empty — treat as not-a-match
  (cannot verify service filter); classify as UNCERTAIN, not COVERED
- POST returns HTTP 403 — token lacks detector-write scope; tell the user and
  stop
- POST returns HTTP 400 with "Unrecognized field" — field name casing mismatch;
  check `programText` vs `program_text` and `detectLabel` vs `detect_label`
- POST returns HTTP 400 with a SignalFlow parse/syntax error (not a field-name
  error) — the `program_text` was sent un-normalized. Re-check Step 2a: the
  `<<-EOF` heredoc must be dedented and **every** `${var.*}` (thresholds, stddev,
  windows — not just `service.name`) must be resolved before the POST. A literal
  `${var...}` token or a leading-whitespace program line both parse-fail as 400.
