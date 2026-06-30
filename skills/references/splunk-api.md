# Splunk Observability Cloud REST API — auth, paginated fetch, status handling

Shared reference for every skill that talks to the Splunk Observability Cloud
REST API directly (no MCP tool required): `splunk-sync`, `splunk-dashboard-sync`,
and any future sync skill. The auth, pagination, and HTTP-status rules are
identical regardless of which object type (detector, dashboard, chart, group) is
being synced — this file is the single source of truth for them.

## Auth

Read credentials from the environment — never hard-code them, never log them:

| Variable | Purpose |
|---|---|
| `SPLUNK_ACCESS_TOKEN` | Org access token; sent as the `X-SF-Token` request header |
| `SPLUNK_REALM` | Realm (e.g. `lab0`, `us0`, `us1`, `eu0`); builds the base URL |

Base API URL: `https://api.${SPLUNK_REALM}.signalfx.com`
App (browser) URL for deep links: `https://app.${SPLUNK_REALM}.signalfx.com`

If either variable is missing, **stop** and tell the user to set them. These same
two variables drive obstudio's metrics/traces forwarding, so they are usually
already present in the environment.

Treat `SPLUNK_ACCESS_TOKEN` as a secret: never echo it, never write it into a
report/ledger, never place it in prompt context or a Terraform `*.tfvars` example
with a real value. In Terraform the matching variable is always
`sensitive = true`.

## Paginated fetch — skip-on-500

The Splunk list endpoints (`GET /v2/detector`, `GET /v2/dashboard`,
`GET /v2/dashboardgroup`, `GET /v2/chart`) share a known server-side bug: certain
`offset` values return **HTTP 500**. This is *not* an auth failure and *not* a
hard error — skip that page and continue. Stop only after several consecutive
empty/again-500 pages, deduping by object `id`:

```python
import urllib.request, urllib.error, json

token = "<SPLUNK_ACCESS_TOKEN>"   # from env; never logged
realm = "<SPLUNK_REALM>"
base  = f"https://api.{realm}.signalfx.com/v2/<object>"   # detector|dashboard|dashboardgroup|chart

limit = 50          # keep small; large limits hit the 500 bug more often
offset = 0
results = []
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
            # Skip-on-500: known offset bug. Advance and keep going.
            offset += limit
            consecutive_empty += 1
            continue
        raise RuntimeError(f"Splunk API error {e.code}: {e}") from e
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"Failed to fetch from Splunk: {e}") from e

    batch = data.get("results", [])
    if not batch:
        consecutive_empty += 1
        offset += limit
        continue

    consecutive_empty = 0
    for obj in batch:
        if obj["id"] not in seen_ids:
            seen_ids.add(obj["id"])
            results.append(obj)
    offset += limit
```

Only HTTP 500 is skipped. Every other status is surfaced. Do **not** wrap the
loop in a bare `except Exception` that swallows everything — that would hide auth
and parse failures behind the 500 skip and silently under-report live objects
(producing false GAPs). Catch the specific exception classes shown above only.

If the org has zero objects of that type, the live list is empty and every local
spec is a GAP — proceed with the empty list, do not error.

## HTTP status handling on create (POST)

`urllib` raises `HTTPError` for any non-2xx response, so branch on the status
code rather than letting it raise blindly:

| Status | Meaning | Action |
|---|---|---|
| 200 / 201 | Created | Record the returned `id`, `name`, and app deep link in the ledger |
| 409 / duplicate-name | Already exists (diff↔create race) | Reclassify as COVERED in the ledger; not an error |
| 400 "Unrecognized field" | Field-name casing mismatch | Check camelCase wire names (`programText`, `detectLabel`, `chartId`, `groupId`) vs HCL snake_case |
| 400 SignalFlow parse/syntax | `program_text` was sent un-normalized | Re-normalize per `terraform-normalization.md`: dedent `<<-EOF`, resolve every `${var.*}` |
| 403 | Token lacks write scope | **Stop** and tell the user; do not retry |
| 401 | Token invalid/expired | **Stop** and tell the user |
| other | Unexpected | Record the failure, continue with remaining items, report all failures in the summary |

Create items sequentially (not in parallel) so progress is visible and any
failure is attributable to a specific local spec.

## Red flags

- `SPLUNK_ACCESS_TOKEN` or `SPLUNK_REALM` unset — stop and tell the user.
- **All** offsets returning HTTP 500 continuously (not intermittent) — likely an
  auth failure masquerading as 500; verify the token is valid.
- A live object has `programText` missing or empty — treat as not-a-match (cannot
  verify the filter); classify UNCERTAIN, never COVERED.
- POST returns 403 — token lacks write scope; stop.
- POST returns 400 — distinguish a field-name casing error from a SignalFlow
  parse error (see the table); they have different fixes.
