# Demo recording shot list

Target length about 6 minutes, recorded in Codex. TODO(confirm): required length, format, and whether the reviewer wants narration.

1. Install (0:00). Show the plugin listing, install Splunk Observability Studio, and trust the SessionStart hook when prompted. Narrate that the hook downloads a checksum-validated Observer release and starts it locally. Note the python3 prerequisite.
2. First run (0:45). Run $observer-status, then $observer-open. Show the local Studio at http://127.0.0.1:17900/. Mention it listens on localhost only.
3. Audit a sample service (1:30). Run $otel-audit in the sample service. Show the findings in the Studio and the .observe artifacts. Show that application code is untouched.
4. Connect an org without exposing a token (3:00). Run $connect-splunk-observability-cloud. Show the agent calling observer_status, then opening the Cloud tab (?tab=cloud). Type the realm or URL and the access token into the local Cloud tab only, never in chat, and select Connect. Call out that the transcript contains no token. Mention it must be re-entered after an Observer restart. Use a throwaway demo token that is revoked after recording.
5. Free Edition signup flow (4:00). Run $create-splunk-free-account with name, email, and terms. Show the region review block and the agent stopping for confirmation. Return the block, show the single create call and the approved confirmation text. Use a demo mailbox. TODO(confirm): whether to show a live signup or a mocked one.
6. Negative case (5:00). Run $splunk-dashboard in a folder with no audit. Show it directing to $otel-audit and writing no files. Optionally repeat with a signup that returns outcome_unknown if a fixture exists. TODO(confirm).
7. Close (5:40). Show $observer-stop and summarize data handling, pointing at PRIVACY.md.
