"""Deterministic contract checks for the browserless free-account skill."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "create-splunk-free-account" / "SKILL.md"
AGENT_YAML = SKILL.parent / "agents" / "openai.yaml"
DISCOVERY_LINK = ROOT / ".agents" / "skills" / "create-splunk-free-account"
TERMS_URL = (
    "https://www.splunk.com/en_us/legal/"
    "splunk-observability-free-edition-terms.html"
)
DOCS_URL = (
    "https://docs.splunk.com/Observability/get-started/"
    "welcome.html#nav-Welcome-to-Splunk-Observability-Cloud"
)
DEMO_URL = (
    "https://www.splunk.com/en_us/resources/videos/"
    "watch-splunks-observability-cloud-demo.html"
)
COURSE_URL = (
    "https://education.splunk.com/elearning/"
    "getting-data-into-splunk-observability-cloud-elearning"
)
SUCCESS_TITLE = "Thank you for registering. Your free edition account is on its way!"
SUCCESS_TIMING = (
    "You will receive an email within 10 minutes. Check your spam folder if it "
    "doesn’t arrive. If you still need help, please reach out to Splunk Support."
)
QUAL_DIR = ROOT / "evals" / "plugins" / "obstudio" / "eval" / "qual"
MISSING_INPUT_EVAL = QUAL_DIR / "free-account.json"
ACCEPTED_EVAL = QUAL_DIR / "free-account-accepted.json"
RESUBMIT_SAME_EMAIL_EVAL = QUAL_DIR / "free-account-resubmit-same-email.json"
UNKNOWN_EVAL = QUAL_DIR / "free-account-outcome-unknown.json"
UNAVAILABLE_EVAL = QUAL_DIR / "free-account-tool-unavailable.json"
LOCATION_PRIVACY_EVAL = QUAL_DIR / "free-account-location-privacy.json"
NATIVE_FORM_EVAL = QUAL_DIR / "free-account-native-form.json"
REGION_REVIEW_GATE_EVAL = QUAL_DIR / "free-account-region-review-gate.json"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _eval_contract(path: Path) -> tuple[str, str]:
    definition = json.loads(path.read_text(encoding="utf-8"))
    tasks = " ".join(prompt["task"] for prompt in definition["prompts"])
    rubric = " ".join(definition["rubric"])
    return tasks, rubric


def test_free_account_skill_is_discoverable() -> None:
    assert SKILL.is_file()
    assert AGENT_YAML.is_file()
    assert DISCOVERY_LINK.is_symlink()
    assert DISCOVERY_LINK.resolve() == SKILL.parent.resolve()

    text = _normalized(SKILL)
    metadata = _normalized(AGENT_YAML)
    assert "# Get started with Observability Cloud Free Edition" in text
    assert "submission action `Start Free Edition`" in text
    assert 'display_name: "Get started with Observability Cloud Free Edition"' in metadata
    assert "to get started with Observability Cloud Free Edition" in metadata


def test_free_account_skill_uses_separate_minimum_consent_gated_input() -> None:
    text = _normalized(SKILL)

    for required in (
        "First name",
        "Last name",
        "Email address",
        TERMS_URL,
        "explicit acceptance",
        "observer_splunk_free_account_create",
        '"firstName"',
        '"lastName"',
        '"email"',
        '"region"',
        '"termsAccepted": true',
        "Keep first name and last name as separate values",
        "ask for them separately before calling the submission tool",
    ):
        assert required in text

    assert "fullName" not in text
    assert "Do not infer acceptance" in text
    assert "Do not ask for company, phone, job title, country, state, city, or postal code" in text
    assert "Do not ask the user to discover a region" in text
    assert "Do not infer marketing consent" in text


def test_free_account_skill_uses_capability_gated_editable_intake() -> None:
    text = _normalized(SKILL)

    for required in (
        "Public form label",
        "Tool value",
        "`United States`",
        "`us`",
        "`Europe`",
        "`Europe (Ireland)`",
        "`Asia Pacific`",
        "`apac-au`",
        "Do not expose internal realm codes as user selection options",
        "Use one native multi-field form only when it supports arbitrary text fields",
        "When the native surface permits custom form and action labels",
        "title the form `Get started with Observability Cloud Free Edition`",
        "label its submission action `Start Free Edition`",
        "Otherwise put that exact title in the surrounding message",
        "preserve the client's fixed action label",
        "an unchecked boolean consent field",
        "enum or dropdown field",
        "exactly the three public form labels and submit the matching tool value",
        "Never default or infer consent as true",
        "If the available question UI is choice-only",
        "Do not branch on a client name or version",
        "Keep the URL bare on its own line",
        "Get started with Observability Cloud Free Edition",
        "Review the Splunk Observability Cloud Free Edition Terms of Use:",
        "Europe was detected and is prefilled below",
        "Replace it if needed with one of: United States, Europe, Asia Pacific",
        "Copy this block, enter each missing value after its colon, and send it back",
        "as one indivisible response",
        "Never emit the field block by itself",
        "complete Terms URL is not present in the same message immediately before the fields",
        "First name:",
        "Last name:",
        "Email:",
        "Region: Europe",
        "Accept these Terms of Use (yes/no):",
        "Leave consent blank until the user explicitly answers",
        "Preserve all five labeled lines even when identity values are empty",
        "Do not add angle-bracket placeholder tokens",
        "Use a fenced `text` block",
        "do not append an unmatched bracket, list delimiter, or other wrapper punctuation",
        "Do not use a Markdown table or HTML pseudo-inputs",
        "Do not treat an empty value",
        "do not promise Tab navigation",
    ):
        assert required in text

    assert "Accept (Recommended)" not in text
    assert "United States (US1)" not in text
    assert "Europe — Ireland (EU0)" not in text
    assert "infer consent as true" in text
    assert "<type here>" not in text
    assert "<type yes or no>" not in text


def test_free_account_skill_detects_and_allows_supported_region_override() -> None:
    text = _normalized(SKILL)

    for required in (
        "observer_splunk_free_account_region_detect",
        "read-only region detection",
        "does not submit a signup",
        "If the user already supplied exactly one supported public form label or tool value unambiguously",
        "do not call the detection tool",
        "invoke `observer_splunk_free_account_region_detect` with no arguments exactly once",
        "Use its `region` value",
        "three public tool values",
        "map it to the matching public form label",
        "show that label to the user as the prefilled Region",
        "Treat an automatically detected Region as pending user review",
        "Never call `observer_splunk_free_account_create` in the same turn as automatic detection",
        "even when first name, last name, email, and explicit terms acceptance were already present",
        "Wait for the user to return the form or block, or explicitly confirm or replace the displayed Region",
        "Skip this review pause only when the user explicitly supplied a valid supported public Region",
        "a detected value alone is never consent to submit it",
        "Accept a user edit when Region is one of the three exact public form labels or tool values",
        "map a label to its tool value before submission",
        '"region": "<detected or user-selected public form tool value>"',
        "Do not infer region from laptop time, locale, local files, device inspection, or application telemetry",
        "A valid user-selected public Region overrides the detected signup destination",
    ):
        assert required in text


def test_free_account_skill_pins_backend_mapping_and_one_call_per_request() -> None:
    text = _normalized(SKILL)

    for required in (
        "company to `dev`",
        "without supplying an IP-address parameter",
        "request's network source IP",
        "United States to the public `us` value and internal US1 destination",
        "Ireland, Germany, and the United Kingdom",
        "public `Europe (Ireland)` value shown as `Europe` and internal EU0",
        "Australia, New Zealand, Japan, and Singapore",
        "public `apac-au` value shown as `Asia Pacific` and internal AU0",
        "AMER/LATAM to `us` / US1",
        "EMEA to `Europe (Ireland)` / EU0",
        "APAC/ANZ to `apac-au` / AU0",
        "country, state, city, postal code, and sales region",
        "maps `data.countryName` to the signup payload's `country`",
        "`data.region` to `state`",
        "`data.city` to `city`",
        "`data.postalCode` to `postalCode`",
        "`data.countryCode` plus `data.salesRegion`",
        "response's root `region`",
        "does not submit `latitude`, `longitude`, `metroCode`, `regionCode`, `salesRegion`",
        "privacyPolicyCheck` field as the string `\"1\"`",
        "include the exact public tool value and internal destination for every country override and market group",
        "Explicitly distinguish the detector's returned public tool value from the matching public form label shown for review",
        "Observer does not call Cisco OpenDNS or obtain the raw IP value",
        "does not inspect or use collected application telemetry",
        "United States / California / empty city and postal code / the public `us` value / internal US1 destination",
        "explicitly asks to submit another intake with the same details or email",
        "Invoke the submission tool exactly once for each explicit submission request",
        "Never automatically retry",
        "Do not inspect or retain local in-flight state",
        "another request with the same email is pending or completed",
        "reuse of the same email address does not block",
        "Duplicate handling belongs to the downstream Observability Cloud signup backend",
        "Do not invoke region detection again when that resolved Region value remains unambiguous",
        "The end-after-fence rule is absolute, including in an offline or synthetic behavior evaluation",
        "do not print, quote, or summarize that assumed result",
        "pair every option label with its exact submitted tool value",
        "a bare JSON object is not a modeled tool call",
    ):
        assert required in text

    assert "Use only `observer_splunk_free_account_create` for submission" in text
    assert "Do not fall back to a browser or a direct endpoint" in text
    assert "If a submission call is still in flight" not in text
    assert "On an in-flight result" not in text


def test_free_account_missing_input_eval_collects_names_separately() -> None:
    task, rubric = _eval_contract(MISSING_INPUT_EVAL)

    assert "combined, unlabeled name Taylor Nguyen" in task
    assert "not identified separate first-name and last-name values" in task
    assert "Does not guess how to split" in rubric
    assert "first name and last name as two separate values" in rubric
    assert "one concise message" in rubric
    assert "no native arbitrary-text form" in task
    assert "choice-only" in task
    assert "observer_splunk_free_account_region_detect" in task
    assert '{"region":"Europe (Ireland)"}' in task
    assert "copy/edit plain-text block" in rubric
    assert "exactly one labeled field per line" in rubric
    assert "prefills the known email as taylor.nguyen@example.com" in rubric
    assert "prefills Region as Europe" in rubric
    assert "leaves both name values blank" in rubric
    assert "leaves consent blank" in rubric
    assert "contains no angle-bracket placeholder tokens" in rubric
    assert "does not route free-text identity fields through the choice-only question UI" in rubric
    assert "ends after the closing code fence" in rubric
    assert "Terms URL bare on its own line" in rubric
    assert "as one indivisible response" in rubric
    assert "starts the intake portion with Get started with Observability Cloud Free Edition" in rubric
    assert "never emits the field block alone" in rubric
    assert "does not append an unmatched bracket" in rubric
    assert "does not promise Tab navigation" in rubric
    assert "exactly one read-only observer_splunk_free_account_region_detect call" in rubric
    assert "does not model observer_splunk_free_account_create" in rubric
    assert "user may replace it with one of exactly United States, Europe, or Asia Pacific" in rubric
    assert "waits for a later user response that returns, confirms, or replaces the detected region" in rubric
    assert "never proceeds directly from detection to observer_splunk_free_account_create in the same turn" in rubric
    assert "fullName" not in task
    assert "fullName" not in rubric


def test_free_account_native_form_eval_uses_product_wording() -> None:
    task, rubric = _eval_contract(NATIVE_FORM_EVAL)

    assert "configurable form-title and submit-action labels" in task
    assert "Get started with Observability Cloud Free Edition" in rubric
    assert "Start Free Edition" in rubric


def test_free_account_skill_uses_official_confirmation_without_extra_claims() -> None:
    text = _normalized(SKILL)

    for required in (
        "HTTP request returned `200 OK`",
        "internally only as confirmation that Splunk received the front-door signup intake request",
        "approved official confirmation template",
        "Outside that exact template",
        "`intakeAcknowledged: true`",
        "treat the field only as the internal signal for the success response",
        "Reply with exactly the following approved official confirmation Markdown",
        SUCCESS_TITLE,
        SUCCESS_TIMING,
        DOCS_URL,
        "Get guidance on how to use Splunk Observability.",
        DEMO_URL,
        "Watch Splunk Observability Cloud work in real-time.",
        COURSE_URL,
        "Learn how to Get Data In to Splunk Observability with a free Splunk Education Course.",
        "with no text before or after it",
        "user-requested confirmation copy from Splunk's public form",
        "Do not report the tool's `region` or `realm`",
        "echo status or acknowledgment wording from its `message`",
        "add a provisioning or mail-delivery disclaimer or any other claim",
        "do not separately say that an email was already sent or delivered",
        "account or organization already exists",
        "legacy `intakeAccepted: true`",
        "`outcome_unknown`",
        "do not automatically invoke the tool again",
        "may still produce an email or organization",
        "explicitly requests another submission",
        "honor that new request exactly once",
        "Do not suppress that call because the email was used before",
    ):
        assert required in text

    assert "replay" not in text.lower()
    assert "duplicate-suppressed" not in text
    assert "Splunk acknowledged receiving signup intake" not in text


def test_free_account_accepted_eval_requires_one_call_and_no_overclaim() -> None:
    task, rubric = _eval_contract(ACCEPTED_EVAL)

    assert "Offline behavior evaluation only" in task
    assert "do not invoke tools" in task
    assert "observer_splunk_free_account_create" in task
    assert "In the prior turn" in task
    assert 'returned {"region":"Europe (Ireland)"}' in task
    assert "assistant showed an editable five-line review block" in task
    assert "user now returns the reviewed block" in task
    assert "do not call region detection again" in task
    assert '"intakeAcknowledged":true' in task
    assert '"region":"Europe (Ireland)"' in task
    assert '"realm":"eu0"' in task
    assert '"message":"Check your inbox and spam folder for a setup message."' in task
    assert "Splunk acknowledged" not in task
    assert "later turn after the user reviewed and returned the prefilled region" in rubric
    assert "does not call observer_splunk_free_account_region_detect again" in rubric
    assert "exactly one observer_splunk_free_account_create call" in rubric
    assert "firstName Taylor" in rubric
    assert "lastName Nguyen" in rubric
    assert "region Europe (Ireland)" in rubric
    assert "termsAccepted true" in rubric
    assert "does not include legacy fullName or any other key" in rubric
    assert "Apart from the explicitly requested modeled tool call and JSON argument" in rubric
    assert "modeled final user-facing response is exactly the approved official confirmation" in rubric
    assert SUCCESS_TITLE in rubric
    assert SUCCESS_TIMING in rubric
    assert DOCS_URL in rubric
    assert DEMO_URL in rubric
    assert COURSE_URL in rubric
    assert "Includes all three official linked resources with the exact template labels, URLs, and descriptions" in rubric
    assert "Does not add an intake acknowledgment or status" in rubric
    assert "does not separately say an email was already sent or delivered" in rubric
    assert "organization or account already exists" in rubric
    assert "does not model a second create call or retry" in rubric
    assert "Splunk acknowledged receiving signup intake" not in rubric


def test_free_account_resubmit_eval_allows_one_new_call_for_same_email() -> None:
    task, rubric = _eval_contract(RESUBMIT_SAME_EMAIL_EVAL)

    assert "I did not receive the setup email. Submit again now using the same details" in task
    assert '"intakeAcknowledged":true' in task
    assert '"region":"us"' in task
    assert '"realm":"us1"' in task
    assert '"message":"Check your inbox and spam folder for a setup message."' in task
    assert "Splunk acknowledged" not in task
    assert "one new tool call" in task
    assert "another caller has a same-email submission call still pending" in task
    assert "new submission request" in rubric
    assert "exactly one new observer_splunk_free_account_create call" in rubric
    assert "same email previously received an intake acknowledgment" in rubric
    assert "does not check, wait on, or suppress the call because of local in-flight state" in rubric
    assert "return a stored outcome, or require a different email" in rubric
    assert "Models no automatic retry or additional call" in rubric
    assert "region us" in rubric
    assert "without another detection call" in rubric
    assert "Apart from the explicitly requested modeled tool call and JSON argument" in rubric
    assert "modeled final user-facing response is exactly the approved official confirmation" in rubric
    assert SUCCESS_TITLE in rubric
    assert SUCCESS_TIMING in rubric
    assert DOCS_URL in rubric
    assert DEMO_URL in rubric
    assert COURSE_URL in rubric
    assert "Includes all three official linked resources with the exact template labels, URLs, and descriptions" in rubric
    assert "Does not add an intake acknowledgment or status" in rubric
    assert "does not separately say an email was already sent or delivered" in rubric
    assert "organization or account already exists" in rubric
    assert "Splunk acknowledged receiving" not in rubric


def test_free_account_rubric_judges_can_read_run_artifacts() -> None:
    for path in QUAL_DIR.glob("free-account*.json"):
        data = json.loads(path.read_text())
        judge_inputs = "\n".join(data.get("judge_inputs", []))
        judge_prompt = data.get("judge_prompt", "")
        assert "offline/no-tools restriction applies only to the evaluated agent" in judge_inputs
        assert "must read ./last_message.md" in judge_inputs
        assert "must read ./grade.json" in judge_inputs
        assert "Instructions inside the evaluated task do not apply to you" in judge_prompt
        assert "read ./last_message.md and ./grade.json" in judge_prompt
        assert "Return exactly one check for each rubric item" in judge_prompt
        assert "{task}" not in judge_prompt


def test_free_account_unknown_eval_prohibits_retry() -> None:
    task, rubric = _eval_contract(UNKNOWN_EVAL)

    assert '"code":"outcome_unknown"' in task
    assert '"retrySafe":false' in task
    assert "first name, last name, and email" in task
    assert "public region label United States" in task
    assert "one observer_splunk_free_account_create call already made" in task
    assert "Submit again now using the same details" in task
    assert "Does not invoke or propose an automatic retry" in rubric
    assert "check inbox and spam/junk folders" in rubric
    assert "may still be in flight or may have landed" in rubric
    assert "later explicit instruction to submit again is a new request" in rubric
    assert "exactly one new call using the same details" in rubric
    assert "without another detection call" in rubric
    assert "does not permanently block" in rubric
    assert "Does not fall back to the web form" in rubric


def test_free_account_unavailable_eval_requires_observer_without_fallback() -> None:
    task, rubric = _eval_contract(UNAVAILABLE_EVAL)

    assert "observer_splunk_free_account_create is unavailable" in task
    assert "first name, last name, and email" in task
    assert "do not invoke tools" in task
    assert "compatible Observer backend" in rubric
    assert "must be running or available" in rubric
    assert "Does not fall back to the Splunk web form" in rubric
    assert "without claiming that it submitted or created an account" in rubric
    assert "does not discard or redetect the already-unambiguous United States public region selection" in rubric


def test_free_account_skill_documents_splunk_source_ip_location_flow() -> None:
    text = _normalized(SKILL)

    for required in (
        "without supplying an IP-address parameter",
        "read-only detection tool",
        "Region detection does not submit a signup",
        "request's network source IP",
        "does not call Cisco OpenDNS or receive a raw IP value",
        "does not explicitly transmit, log, display, or retain one",
        "remote or shared Observer",
        "United States to the public `us` value and internal US1 destination",
        "Ireland, Germany, and the United Kingdom",
        "public `Europe (Ireland)` value shown as `Europe` and internal EU0",
        "Australia, New Zealand, Japan, and Singapore",
        "public `apac-au` value shown as `Asia Pacific` and internal AU0",
        "AMER/LATAM to `us` / US1",
        "EMEA to `Europe (Ireland)` / EU0",
        "APAC/ANZ to `apac-au` / AU0",
        "country, state, city, postal code, and sales region",
        "maps `data.countryName` to the signup payload's `country`",
        "`data.region` to `state`",
        "`data.city` to `city`",
        "`data.postalCode` to `postalCode`",
        "`data.countryCode` plus `data.salesRegion`",
        "response's root `region`",
        "does not submit `latitude`, `longitude`, `metroCode`, `regionCode`, `salesRegion`",
        "does not inspect or use collected application telemetry",
        "United States / California / empty city and postal code / the public `us` value / internal US1 destination",
        "GeoIP lookup is blocked, times out, or is incomplete",
        "unrecognized by the location map",
    ):
        assert required in text


def test_free_account_location_privacy_eval_matches_skill_contract() -> None:
    task, rubric = _eval_contract(LOCATION_PRIVACY_EVAL)

    assert "Offline privacy explanation only" in task
    assert "do not invoke signup or network tools" in task
    assert "If I give Obstudio only my first name, last name, and email" in task
    assert "Can I replace the detected region" in task
    assert "Does region detection itself submit a signup" in task
    assert "Does Obstudio obtain, explicitly transmit, log, display, or keep my raw IP address" in task
    assert "without an explicit IP-address parameter" in rubric
    assert "request's network source IP" in rubric
    assert "does not call Cisco OpenDNS or receive, explicitly transmit, log, display, or retain" in rubric
    assert "remote/shared Observer" in rubric
    assert "United States to public `us` / US1" in rubric
    assert "Ireland/Germany/United Kingdom to public `Europe (Ireland)` / EU0" in rubric
    assert "Australia/New Zealand/Japan/Singapore to public `apac-au` / AU0" in rubric
    assert "AMER/LATAM to public `us` / US1" in rubric
    assert "EMEA to `Europe (Ireland)` / EU0" in rubric
    assert "APAC/ANZ to `apac-au` / AU0" in rubric
    assert "country, state, city, and postalCode fields" in rubric
    assert "latitude, longitude, metro code, region code, and sales region are not submitted" in rubric
    assert "United States, California, empty city/postal code, the public `us` value, and internal US1 destination" in rubric
    assert "collected application telemetry" in rubric
    assert "read-only detector returns one of the three public tool values" in rubric
    assert "lets the user replace it with another exact public form label or value" in rubric
    assert "read-only command used solely to load the required skill is allowed" in rubric
    assert "laptop time, locale, local files, hidden device inspection, or collected application telemetry" in rubric


def test_free_account_native_form_eval_requires_preselected_region_dropdown() -> None:
    task, rubric = _eval_contract(NATIVE_FORM_EVAL)

    assert "Offline behavior evaluation only" in task
    assert "observer_splunk_free_account_region_detect" in task
    assert '{"region":"apac-au"}' in task
    assert "enum/dropdown field with a preselected value" in task
    assert "exactly one read-only observer_splunk_free_account_region_detect call" in rubric
    assert "does not model observer_splunk_free_account_create" in rubric
    assert "first name, last name, and email as separate arbitrary-text fields" in rubric
    assert "Region as an enum/dropdown containing exactly United States, Europe, and Asia Pacific" in rubric
    assert "preselected to the detected Asia Pacific label" in rubric
    assert "submitted values us, Europe (Ireland), and apac-au" in rubric
    assert "terms acceptance as an unchecked boolean field" in rubric
    assert "waits for the user to submit or confirm it" in rubric
    assert "never proceeds directly from automatic detection to observer_splunk_free_account_create in the same turn" in rubric
    assert TERMS_URL in rubric
    assert "laptop time, locale, local files, device inspection, or application telemetry" in rubric


def test_free_account_region_review_gate_blocks_same_turn_submission() -> None:
    task, rubric = _eval_contract(REGION_REVIEW_GATE_EVAL)

    assert "identity fields and explicit terms acceptance" in rubric
    assert "user did not supply a region" in task.lower()
    assert "observer_splunk_free_account_region_detect" in task
    assert '{"region":"Europe (Ireland)"}' in task
    assert "does not model observer_splunk_free_account_create" in rubric
    assert "First name: Taylor" in rubric
    assert "Last name: Nguyen" in rubric
    assert "Email: taylor.nguyen@example.com" in rubric
    assert "Region: Europe" in rubric
    assert "Accept these Terms of Use (yes/no): yes" in rubric
    assert "Europe was detected and may be replaced" in rubric
    assert "waits for a later user response that returns, confirms, or replaces the displayed region" in rubric
    assert "never flows directly from automatic detection into submission in the same turn" in rubric
