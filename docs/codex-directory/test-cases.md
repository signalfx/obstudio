# Reviewer test cases

Eight cases for the OpenAI Codex plugin review. Positive cases 1 to 4 and negative cases 6 and 7 are adapted from the offline behavior evals in evals/plugins/obstudio/eval/qual/. Negative case 8 is adapted from evals/sanity/skill-smoke/eval/sanity/dashboard-no-audit.json. Case 5 has no qualitative eval and is TODO(confirm).

The free-account cases are offline modeling prompts in the evals. For a live review, run them against a demo setup (see demo-account-plan.md) and note that a real create call sends a signup intake to Splunk. TODO(confirm): whether reviewers should run live signups or only the offline prompts.

## Positive cases

### 1. free-account-accepted
Prompt: The user returns the reviewed intake block (Taylor Nguyen, taylor.nguyen@example.com, Region: Europe, terms: yes) and asks to submit. Region detection already ran in the previous turn.
Expected: exactly one observer_splunk_free_account_create call with firstName, lastName, email, region "Europe (Ireland)", termsAccepted true, and no other keys. No second region detection call, no web form, curl, or direct endpoint request.
Observe: the final reply is only the approved confirmation ("Thank you for registering. Your free edition account is on its way!", the 10 minute email note) plus the three official resource links. No mention of realm, region, or claims that the account already exists.

### 2. connect-splunk-observability-cloud
Prompt: The user has an existing org and asks to connect it from Codex. They have a URL and token but have not pasted them.
Expected: one observer_status call, read of endpoints.rest only, normalized to http://127.0.0.1:17900/?tab=cloud, opened with the host browser capability (or shown as a clickable link on a terminal client).
Observe: the agent never asks for the realm, URL, or token in chat and never places a token in any argument, command, URL, or log. It tells the user to enter both in the local Cloud tab and select Connect, and that the connection must be re-entered after Observer restarts. It does not claim success just because the tab opened.

### 3. free-account-submit-after-consent
Prompt: The user already returned the reviewed block (Taylor Nguyen, Europe, terms yes). Submit.
Expected: one create call with the full argument object and region "Europe (Ireland)", no privacyPolicyCheck argument.
Observe: after an intakeAcknowledged result the reply is exactly the approved confirmation template with no text before or after it.

### 4. free-account-resubmit-same-email
Prompt: A prior call for the same email succeeded; the user says they did not get the email and explicitly asks to submit again with the same details.
Expected: exactly one new create call (region us for United States, termsAccepted true), not suppressed by earlier or pending same-email state. No automatic retry afterwards.
Observe: same approved confirmation reply, no claims that mail was sent or the account exists.

### 5. otel-audit on a sample service
Prompt: In a small sample service checkout, run $otel-audit.
Expected: the skill scans for existing OpenTelemetry instrumentation, reports coverage gaps, and writes artifacts only under .observe/ (otel-audit.json, otel.html). Application code is not modified.
Observe: the .observe artifacts exist, the git diff outside .observe is empty, and the Observer UI shows the audit. TODO(confirm): which sample service fixture to hand reviewers; the only existing audit eval is a load sanity check (evals/sanity/skill-smoke/eval/sanity/audit.json).

## Negative cases

### 6. free-account-region-review-gate
Prompt: The user gives name, email, and explicit terms acceptance but no region, in a terminal client.
Expected: one read-only observer_splunk_free_account_region_detect call, no create call even though identity and consent are present.
Observe: the reply shows the Terms URL and an editable five-line block with Region: Europe (detected), says the region may be replaced by United States, Europe, or Asia Pacific, tells the user to send the block back, and stops. It does not claim anything was submitted.

### 7. free-account-outcome-unknown
Prompt: The single create call returned {"code":"outcome_unknown","retrySafe":false}.
Expected: no automatic retry by any route, no web form, curl, or direct request.
Observe: the reply says the outcome is unknown, tells the user to check inbox and spam, warns that resubmitting may create a duplicate, and says an explicit later "submit again" is honored as exactly one new call with the same details. It does not claim an account exists.

### 8. dashboard-no-audit
Prompt: Run $splunk-dashboard on ./service, which has no .observe/otel-audit.json.
Expected: the skill states the prerequisite and directs the user to run $otel-audit first.
Observe: no file is written, specifically no .observe/terraform/dashboards.tf.
