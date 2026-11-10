# Reviewer demo account plan

Goal: give the reviewer a working Splunk Observability Cloud Free Edition org so connect, publish, and Studio export flows can be exercised.

## Getting an org
1. A Splunk-side owner runs $create-splunk-free-account with a dedicated team mailbox (for example a shared alias, TODO(confirm) address), accepts the Free Edition terms, confirms the detected region, and submits once.
2. Wait for the setup email (the confirmation says up to 10 minutes; check spam). If the outcome is unknown, do not resubmit blindly; check the mailbox first.
3. Complete setup from the email, then create an access token in the org: an ingest token for sending telemetry, and an API token scoped only to what the publish skills need. TODO(confirm) minimum scopes.
4. Pre-load a small sample service with telemetry (the otel-audit sample) so dashboards and detectors have data.

Free Edition limits and expiry: TODO(confirm). Plan the org lifetime to cover the whole review period, and confirm one org per email is acceptable.

## What to hand the reviewer
- Realm and org URL.
- A reviewer-specific access token, delivered through the review submission's credentials field or another secret channel, never in chat, the repo, or the demo video.
- The sample service checkout and the test-cases.md file.
- Reviewer-facing login if they need the UI. TODO(confirm) whether a user seat is needed.

## What must not be shared
- The org admin credentials or the mailbox login.
- Org-admin or broad-scope API tokens; use least privilege tokens only.
- Any token in screenshots, recordings, logs, or this repository.
- Real customer data or telemetry in the demo org.
- Internal Splunk tooling details, Jira links, or Slack content.

## After review
Revoke the reviewer tokens, rotate the ingest token, and decide whether to keep or delete the org. TODO(confirm) owner and date.
