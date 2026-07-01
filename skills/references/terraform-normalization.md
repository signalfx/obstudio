# Normalizing Terraform `program_text` to valid SignalFlow

Shared reference for every skill that POSTs a Terraform-authored `program_text`
(detector or chart) to the Splunk Observability Cloud REST API:
`splunk-detector-publish`, `splunk-dashboard-publish`, and `splunk-dashboard`
(which writes already-normalized
`programText` into its preview sidecar).

The raw `program_text` value extracted from HCL is **not** valid SignalFlow and
**must** be normalized before it is sent in any POST body or written as a
resolved `programText`. The Splunk API runs the string through the SignalFlow
parser as-is and rejects it with **HTTP 400** if either hazard below is left
unhandled. Do this once, during parsing, and carry the normalized string forward
for both coverage comparison and the create body.

## 1. Strip indented-heredoc whitespace (`<<-EOF`)

Terraform's `<<-EOF` "indented heredoc" deletes the leading whitespace of the
*least-indented* line at apply time, but the raw bytes between the `<<-EOF` and
`EOF` markers still carry the editor indentation. SignalFlow treats a
leading-whitespace line as a syntax error, so reproduce Terraform's behavior:
find the smallest leading-whitespace run across all non-blank lines and strip
exactly that many leading characters from every line (i.e. `textwrap.dedent`
after trimming the trailing marker line). Plain `<<EOF` (no dash) is already
flush-left — leave it unchanged. Always `.strip()` the final result so a
leading/trailing blank line never reaches the parser.

## 2. Resolve every `${var.*}` reference, not just `service.name`

Program text routinely interpolates more than the service name — thresholds,
stddev counts, percentiles, and windows: `threshold(${var.latency_..._threshold})`,
`fire_num_stddev=${var..._stddev}`, etc. A literal `${var...}` token is invalid
SignalFlow. Resolve **all** of them, in this precedence order, before create:

- a matching assignment in `terraform.tfvars` (then `*.auto.tfvars`, then
  `terraform.tfvars.example`), else
- the `default` value of the matching `variable "<name>" { ... }` block in
  `variables.tf`, else
- prompt the user for the value (do not guess, and do not POST with an
  unresolved token).

Substitute the resolved literal for the whole `${var.<name>}` span. Numbers are
emitted bare (`50.0`); strings keep their SignalFlow quoting as written in the
surrounding program text.

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
            "Prompt the user for these before POSTing."
        )
    return out

# Per spec, during parsing:
program_text = resolve_vars(dedent_heredoc(raw_program_text), tf_vars, var_defaults)
```

Both transforms are pure-string and deterministic; the result is the exact
SignalFlow Splunk would have received had the Terraform been `terraform apply`-d.
Use this normalized `program_text` everywhere downstream — coverage comparison,
the REST create body, and (for `splunk-dashboard`) the resolved `programText`
written into `.observe/dashboards.preview.json`.

## Field-name normalization (HCL ↔ REST)

The local HCL uses snake_case attribute names; the live REST API uses camelCase
wire names. Normalize when comparing or building a POST body:

| HCL attribute | REST wire field |
|---|---|
| `program_text` | `programText` |
| `detect_label` | `detectLabel` |
| `dashboard_group` | `groupId` (on the dashboard create body) |
| `chart_id` | `chartId` |

A 400 "Unrecognized field" almost always means a snake_case name leaked into the
JSON body.
