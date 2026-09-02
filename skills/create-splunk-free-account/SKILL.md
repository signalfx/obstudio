---
name: create-splunk-free-account
description: >-
  Submit a consent-gated Splunk Observability Cloud Free Edition signup intake
  in a detected or user-selected supported signup region through Observer's
  browserless MCP backend. Use when a user asks to create, provision, register,
  start, or sign up for a free Splunk Observability Cloud, Splunk O11y, or
  SignalFx account or organization, or explicitly asks to submit another
  intake with the same details or email, including requests to avoid the Splunk
  web form.
---

# Get started with Observability Cloud Free Edition

Help the user get started with Observability Cloud Free Edition by submitting a
consent-gated intake through Observer. The Observer backend supplies the
non-user fields and performs the external request.

## Guardrails

- Treat submission as an external write. Call the submission tool only after
  the user asks to create the account and explicitly accepts the linked terms.
- Do not infer acceptance from the signup request, a prior unrelated “yes,” or
  silence. Do not set `termsAccepted` to `true` on the user's behalf.
- Never submit directly with `curl`, a reconstructed JSON request, or the web
  form. Use only `observer_splunk_free_account_create` for submission and
  `observer_splunk_free_account_region_detect` for read-only region detection.
- Invoke the submission tool exactly once for each explicit submission
  request. Never automatically retry a rejection, timeout, transport failure,
  or ambiguous result.
- Do not inspect or retain local in-flight state, prior outcomes, or email
  history to suppress or delay an explicit submission request. Each explicit
  request gets one tool call even when another request with the same email is
  pending or completed; reuse of the same email address does not block a call.
  Duplicate handling belongs to the downstream Observability Cloud signup
  backend.
- Treat a success-like response internally only as confirmation that Splunk
  received the front-door signup intake request. Use the approved official
  confirmation template under **Interpret and report the result** as the one
  user-facing exception. Outside that exact template, do not claim that an
  organization exists, provisioning began or completed, or an email was sent
  or delivered merely because the tool succeeded or an upstream HTTP request
  returned `200 OK`.

## Detect region and collect minimum input

Resolve the signup region before presenting the intake fields:

- The public form has three supported signup region options. Their display
  labels and tool values are:

  | Public form label | Tool value |
  | --- | --- |
  | `United States` | `us` |
  | `Europe` | `Europe (Ireland)` |
  | `Asia Pacific` | `apac-au` |

  Treat these labels and values as the public signup contract. Do not expose
  internal realm codes as user selection options.
- If the user already supplied exactly one supported public form label or tool
  value unambiguously for this request, use it and do not call the detection
  tool. Map a label to its corresponding tool value deterministically. The
  values `us`, `Europe (Ireland)`, and `apac-au` are accepted as tool values.
  Preserve the exact spelling and capitalization of the public labels.
- Otherwise, invoke `observer_splunk_free_account_region_detect` with no
  arguments exactly once for the current intake. This is a read-only lookup and
  does not submit a signup. Use its `region` value only when it is one of the
  three public tool values, map it to the matching public form label, and show
  that label to the user as the prefilled Region.
- Treat an automatically detected Region as pending user review. After
  detection, always present the native form or complete editable text block and
  stop. Never call `observer_splunk_free_account_create` in the same turn as
  automatic detection, even when first name, last name, email, and explicit
  terms acceptance were already present. Wait for the user to return the form
  or block, or explicitly confirm or replace the displayed Region.
- Treat the Region as reviewed only after that later user response. Skip this
  review pause only when the user explicitly supplied a valid supported public
  Region for this request before detection; a detected value alone is never
  consent to submit it.
- If region detection is required but the tool is unavailable or returns no
  supported public value, stop and explain that a compatible Observer backend
  is required. Do not infer region from laptop time, locale, local files,
  device inspection, or application telemetry.

Obtain these values from the user:

1. First name.
2. Last name.
3. Email address.
4. Explicit acceptance of the
   [Splunk Observability Cloud Free Edition Terms of Use](https://www.splunk.com/en_us/legal/splunk-observability-free-edition-terms.html).

Ask for all missing items in one concise message. Quote the terms link in that
message and ask the user to state that they accept those terms. If the user
provides first name, last name, and email but no explicit acceptance, stop and
ask for acceptance before calling the submission tool. Keep first name and
last name as separate values. If the user supplies only a combined name without
identifying the two values, ask for them separately before calling the
submission tool.

Present missing values with the best input surface the current client actually
exposes:

- Use one native multi-field form only when it supports arbitrary text fields
  and an unchecked boolean consent field. Put the terms link in the surrounding
  message. When the native surface permits custom form and action labels, title
  the form `Get started with Observability Cloud Free Edition` and label its
  submission action `Start Free Edition`. Otherwise put that exact title in the
  surrounding message and preserve the client's fixed action label. Prefill
  only unambiguous first name, last name, or email values that the user already
  supplied. Prefill Region with the detected or supplied public form label.
  When the client supports an enum or dropdown field, use it for Region with
  exactly the three public form labels and submit the matching tool value for
  the selected label. When describing or modeling that native form, pair every
  option label with its exact submitted tool value; a labels-only option list is
  incomplete. Explicitly tell the user that the detected label is preselected,
  that they may choose any other listed label, and that the form is waiting for
  their review and submission or confirmation. Otherwise use an editable Region
  text field. Never default or infer consent as true. Keep it unchecked until
  the user explicitly accepts the linked terms; if that acceptance was already
  explicit for this request, the review form may reflect the known value. Treat
  a declined or dismissed form as a stop, not as acceptance.
- Do not force first name, last name, or email through a multiple-choice prompt
  or an `Other` option. If the available question UI is choice-only, or no
  native form is available, use the copy/edit block below. Do not branch on a
  client name or version.

Use this exact compact lead-in. Keep the URL bare on its own line so terminal
clients do not leave Markdown-link punctuation behind:

```text
Get started with Observability Cloud Free Edition

Review the Splunk Observability Cloud Free Edition Terms of Use:
https://www.splunk.com/en_us/legal/splunk-observability-free-edition-terms.html

Europe was detected and is prefilled below. Replace it if needed with one of: United States, Europe, Asia Pacific.

Copy this block, enter each missing value after its colon, and send it back:
```

```text
First name:
Last name:
Email:
Region: Europe
Accept these Terms of Use (yes/no):
```

Replace both instances of the example `Europe` with the actual detected public
form label. If the user supplied
the region, say `Selected region is prefilled below` instead of claiming it was
detected. Treat the title, lead-in, bare Terms URL, region sentence, instruction
sentence, and field block as one indivisible response. Never emit the field
block by itself. If the complete Terms URL is not present in the same message
immediately before the fields, do not request consent or call the submission
tool; correct the intake message first.

Put an already-known, unambiguous name or email value after its colon, and put
the detected or selected public form label after `Region:`. Leave consent blank
until the user explicitly answers; when that acceptance is already explicit for
this request, put `yes` rather than inferring a new answer. Preserve all five
labeled lines even when identity values are empty. Do not add angle-bracket
placeholder tokens. Use a fenced `text` block so spacing survives rendering.
End the intake message after the closing fence; do not append an unmatched
bracket, list delimiter, or other wrapper punctuation. Do not use a Markdown
table or HTML pseudo-inputs. Do not treat an empty value or a prior unrelated “yes” as input
or consent. Accept a user edit when Region is one of the three exact public form
labels or tool values; map a label to its tool value before submission. If the
edit is not an exact supported label or value, show the same editable block
again with the allowed labels. Do not lowercase public labels. If the terminal
explicitly exposes an external-editor
shortcut, a one-line hint may mention that detected shortcut; do not promise
Tab navigation or hardcode a shortcut based only on the client name.

The end-after-fence rule is absolute, including in an offline or synthetic
behavior evaluation. When such an evaluation asks to model the preceding
detection call, show that model before the intake lead-in as one plain sentence
with inline code, not as a separate fenced block. The editable intake must be
the response's only fenced block. End the entire response at that intake
block's closing fence without a trailing explanation.

Do not ask for company, phone, job title, country, state, city, or postal code. Do not
ask the user to discover a region; detect and prefill it, then let the user
replace that value if needed. The backend fixes the company to `dev`. For
location, the read-only detection tool causes Observer to call Splunk's GeoIP
endpoint without supplying an IP-address parameter. Splunk derives a coarse
country, state, city, postal code, and sales region from the request's network
source IP. Observer maps `data.countryName` to the signup payload's `country`,
`data.region` to `state`, `data.city` to `city`, and `data.postalCode` to
`postalCode`. It uses `data.countryCode` plus `data.salesRegion` (falling back
to the response's root `region`) only to preselect the hosting region. It does
not submit `latitude`, `longitude`, `metroCode`, `regionCode`, `salesRegion`,
`countryCode`, or the root `region` as signup payload fields. Observer does not
call Cisco OpenDNS or receive a raw IP value, so it does not explicitly
transmit, log, display, or retain one. Splunk still processes the normal
request source IP. Region detection does not submit a signup. Realm selection
does not inspect or use collected application telemetry. A remote or shared
Observer can therefore reflect that Observer host's network rather than the
user's laptop.

The backend applies supported country overrides first: United States to the
public `us` value and internal US1 destination; Ireland, Germany, and the United
Kingdom to the public `Europe (Ireland)` value shown as `Europe` and internal
EU0; and Australia, New Zealand, Japan, and Singapore to the public `apac-au`
value shown as `Asia Pacific` and internal AU0. All other recognized countries
follow Splunk's global market groups: AMER/LATAM to `us` / US1, EMEA to
`Europe (Ireland)` / EU0, and APAC/ANZ to `apac-au` / AU0. If Splunk's GeoIP
lookup is blocked, times out, or is incomplete, or the returned values are
unrecognized by the location map, the backend atomically falls back to United
States / California / empty city and postal code / the public `us` value /
internal US1 destination. Do not infer marketing consent. A valid user-selected
public Region overrides the detected signup destination; it does not replace
the backend-derived country, state, city, or postal-code values.

When the user asks how location mapping works, include the exact public tool
value and internal destination for every country override and market group
above. Do not substitute the display label `United States` for `us`,
`Europe` for `Europe (Ireland)`, or `Asia Pacific` for `apac-au` when naming a
tool value. Explicitly distinguish the detector's returned public tool value
from the matching public form label shown for review, and state that reviewing
or replacing that label or value still does not submit a signup. Explicitly
name `latitude`, `longitude`, `metroCode`, `regionCode`, `salesRegion`,
`countryCode`, and the root `region` as GeoIP response fields that are not
submitted as signup payload fields. Also state that Observer does not call
Cisco OpenDNS or obtain the raw IP value, while Splunk still processes the
request's normal source IP for its GeoIP result.

## Submit once per explicit request

After all four user inputs are present and the Region was either explicitly
supplied for this request or reviewed in a later user response after detection,
call
`observer_splunk_free_account_create` exactly once for that explicit request
with:

```json
{
  "firstName": "<user-provided first name>",
  "lastName": "<user-provided last name>",
  "email": "<user-provided email>",
  "region": "<detected or user-selected public form tool value>",
  "termsAccepted": true
}
```

The Observer backend validates `termsAccepted: true` and then sends the public
form's upstream `privacyPolicyCheck` field as the string `"1"`. Do not ask the
user for that internal field or pass it as an additional tool argument.

If the submission tool is unavailable, stop and explain that the compatible
Observer backend must be available. Do not fall back to a browser or a direct
endpoint.

If the user later explicitly asks to submit again, call the submission tool
exactly once for that new request, even when the email is unchanged and a prior
result was an intake acknowledgment, definite error, or `outcome_unknown`.
Reuse the previously supplied inputs, resolved public Region value, and
explicit terms acceptance when they remain unambiguous in the current
conversation. Do not invoke region detection again when that resolved Region
value remains unambiguous. Do not require a different email, and do not turn
one user instruction into repeated calls.

## Interpret and report the result

- On `intakeAcknowledged: true`, treat the field only as the internal signal for
  the success response. Reply with exactly the following approved official
  confirmation Markdown, with no text before or after it:

  ```markdown
  **Thank you for registering. Your free edition account is on its way!**

  You will receive an email within 10 minutes. Check your spam folder if it doesn’t arrive. If you still need help, please reach out to Splunk Support.

  [Observability Docs.](https://docs.splunk.com/Observability/get-started/welcome.html#nav-Welcome-to-Splunk-Observability-Cloud) Get guidance on how to use Splunk Observability.

  [Observability Cloud Demo.](https://www.splunk.com/en_us/resources/videos/watch-splunks-observability-cloud-demo.html) Watch Splunk Observability Cloud work in real-time.

  [Getting Data into Splunk Observability Cloud.](https://education.splunk.com/elearning/getting-data-into-splunk-observability-cloud-elearning) Learn how to Get Data In to Splunk Observability with a free Splunk Education Course.
  ```

  This is the user-requested confirmation copy from Splunk's public form. Do not
  report the tool's `region` or `realm`, echo status or acknowledgment wording
  from its `message`, or add a provisioning or mail-delivery disclaimer or any
  other claim. In particular, do not separately say that an email was already
  sent or delivered or that an account or organization already exists. Treat
  legacy `intakeAccepted: true` results the same way; the older field name still
  represents only an intake acknowledgment.

  In an offline or synthetic behavior evaluation that supplies an assumed raw
  success result, do not print, quote, or summarize that assumed result. If the
  evaluation asks to model the submission call, explicitly name
  `observer_splunk_free_account_create` with its one JSON argument object first;
  a bare JSON object is not a modeled tool call. Then emit only the exact
  approved confirmation above as the modeled final response.
- On `outcome_unknown` or an equivalent ambiguous timeout/transport result, say
  that the outcome is unknown, do not automatically invoke the tool again for
  that request, and tell the user to check inbox and spam/junk folders before
  taking further action. Explain that the request may still be in flight or may
  have landed, so a later submission could duplicate an intake. If the user
  nevertheless explicitly requests another submission, honor that new request
  exactly once.
- On a definite validation error or rejection, explain the actionable reason
  and wait. Never retry automatically; honor a later explicit submission
  request exactly once, using corrected input when the user provides it.

If the user only reports that no setup email arrived after an acknowledgment,
do not infer a request to submit again. Explain that the browserless client
cannot determine downstream provisioning or mail status from the intake
acknowledgment, and ask the user to check spam/junk folders. If the user
explicitly asks to submit again, warn that the prior request may still produce
an email or organization, then make exactly one new tool call. Do not suppress
that call because the email was used before; the downstream backend owns
duplicate handling.

Keep the final response concise and avoid repeating the user's email address
unless it is needed to resolve an error.
