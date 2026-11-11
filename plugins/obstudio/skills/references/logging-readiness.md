# Application logging readiness

Read this reference when auditing or changing an application logging path.
These rules extend the local-log contract; they do not authorize new sinks,
sensitive-data capture, a custom SDK, or changes outside the selected scope.

For audit, instrumentation and verification, read only the detected stack's
**Logging Readiness Checks** section in the existing language guide, following
its bridge/provider ownership references as needed. Those guides describe runtime-specific context, record and lifecycle pitfalls;
resolve concrete SDK APIs and settings from the detected implementation. The
common rules and acceptance obligations below still apply. A guide's setup
examples do not authorize application changes in an audit or verification task.
The logging checks are self-contained for each declared consumer; audit and
verification do not require a sibling instrumentation skill to be installed.

| Detected stack | Existing language reference |
|---|---|
| Java | [Java logging checks](languages/java.md#logging-readiness-checks) |
| Python | [Python logging checks](languages/python.md#logging-readiness-checks) |
| Go | [Go logging checks](languages/go.md#logging-readiness-checks) |
| Node.js | [Node.js logging checks](languages/node.md#logging-readiness-checks) |

## Source and applicability

Use three related worklists before finalizing the normal report. This is a local
completeness method, not an additional OTel implementation requirement. Keep the
work proportional to the selected application path and claims. In the worklists
and source-clause obligations below, applicability means a clause needed to
assess selected application behavior, supplied operator policy, app-owned or
changed configuration, a source-backed risk, or an actual capability claim.
An unchanged delegated default needs accurate versioned source/default evidence;
it does not select every parser input, record shape or upstream conformance test.
Unselected SDK/receiver duties need no per-application clause ledger. Compact
owner/default/unsupported/unverified facts may explain relevant delegated behavior
without enumerating sibling duties. Such facts never close a critical selected
invariant or an unproven runtime claim.

An exhaustive OTel clause inventory and source-to-skill coverage review belongs
to skill maintenance when requested; it is not an additional deliverable for
every normal application audit, instrumentation or verification report.

1. **Contract:** extract each applicable primary-source clause and its distinct
   conditions, strength, maturity and actual owner. Distinguish the specification's
   status from each selected installed/proposed SDK, API and bridge's stated
   stability; a stable data model does not establish component maturity. Retain
   a source-backed status or explicit unknown/not-inspected disposition for those
   components, without inventing a beta label or upgrade requirement. Keep SDK, receiver and library duties distinct from
   application wiring and retain precise delegated capability dispositions.
2. **Capability:** resolve mechanisms necessary to selected application/operator
   invariants and every actual capability claim. Follow relevant parser, default,
   normalization, diagnostic and retry/deadline delegates to their consuming
   operation. “Not run” describes execution, not source capability; it cannot
   substantiate a source-contradicted claim. Resolve accessible facts for proposed
   dependencies too, or retain the exact access boundary and conditional check.
3. **Acceptance:** combine selected source-clause controls, operator policy and
   every promised telemetry item/field, then map each condition to an assertion
   or precise conditional resolution step. The
   `required-controls` helper inventories audit promises only; its output
   excludes source-clause and acceptance controls. Add those independently.

Keep `required_fix` to the smallest authorized application change. Put delegated
defaults and optional capability facts in evidence with their owner/disposition;
do not turn them into new application configuration promises. Each independently
selectable finding's acceptance must be executable using its own repair and
transitive prerequisites. Check the changes each assertion needs, not only its
scenario's listed IDs: a dependent's repair cannot establish its prerequisite's
acceptance. Bind shared whole-path integration checks to their actual owner.

Derive a named configuration inventory independently from application-owned or
new overrides, supplied selected settings, and dependencies necessary to the
claimed logging behavior. Include relevant Resource, propagation/sampling,
bridge/provider activation, filtering/SDK-disabled, limits and lifecycle paths.
For a promised optional mode, identify its actual named activation setting or
source-proven default; an instruction to enable the mode is not its wiring.
Inspect key/option declarations and actual readers; a declaration alone does not
prove consumption. Key entries by owner/reader as well as setting name, since
consumers can apply different defaults and diagnostics. A queried startup key
is read even if absent, and an eagerly evaluated default expression can read a
value that is ultimately ignored. Separate reading from effective consumption.

Do not expand an application task into exhaustive upstream SDK certification.
Mere transitive consumption does not require enumerating every unused SDK
setting or input permutation. Ordinary delegated defaults can retain precise
source/default ownership and scoped unverified effects without runtime claims.
An SDK/library conformance task or repository-owned component has a different
scope. This distinction cannot excuse ignored operator values, a false exact
claim, or an unresolved critical application invariant. Environment support is
optional and may belong to an SDK, individual component or autoconfigurator;
establish support and the active owner before imposing its parsing contract.

Populate the value-case table for required settings now in existing report/
evidence fields. Derive cases from the actual selected operator/environment
reader or precise input-behavior claim. A fixed typed public option requires
proof of its applied value, units, native API, startup consumption and operator
preservation; it does not select malformed serialized inputs that cannot reach
that path. Resolve whether a proposed value uses an option or an active reader;
keep genuinely unresolved wiring explicit. Accessible facts needed for a selected
guarantee cannot be deferred as an instruction to resolve them later. Share
parameterized cases only with an explicit setting-name → case/default/outcome
map; a primitive-type label or “all settings” does not identify its members:

| Consumed setting and owner | Input case | Actual source outcome | Upstream disposition | Acceptance |
|---|---|---|---|---|
| Selected name and configuration source | Concrete intended input/representation | Effective value, fallback/error and diagnostic; cite parser, conversion and validation/delegate | Applicable source strength, supported/default/partial/unsupported/unverified and reason | Exact field/operation assertion or checked missing capability step |

Keep each setting's valid range, default and conversion distinct even when it
shares a primitive parser with another setting. Trace the complete resolution:
raw input or omission → reader → conversion → precedence/fallback → validation
or default factory → consuming operation. An intermediate null, sentinel or
conversion error is not the effective value. Retain the intermediate values
through secondary defaults, unit conversions and clamps to the terminal consumer;
report that terminal outcome. Compute each setting's chain from its own owner,
rather than copying a different family's fallback or overflow result. Resolve
symbolic constants to their actual values; a constant's name is not its serialized spelling. Include
fallback settings needed to resolve the selected outcome. For a required application
reader or explicit selected fallback promise, save `input state → expected final value/tuple
and winning source → named assertion`. Give each claimed higher-priority absent,
empty and invalid state with a valid nondefault lower-priority value, and both
absent, an addressable case; one generic-only example cannot represent them all.
A shared parameterized assertion is sufficient when its named cases and expected
results are explicit. Exercise each caller's actual fallback values; a helper
tested with different defaults does not prove application initialization.
Derive application fallbacks and delegated SDK defaults
from their actual owners rather than assuming universal inheritance. A delegated source-only fact remains source evidence, not an invented runtime test requirement. Resolve negative, zero, fractional,
malformed/overflow and enum/Boolean cases only where those inputs reach that
reader or the corresponding behavior is claimed; fixed typed options do not
select an upstream parser suite. Naming a required group is not its expected
outcome. A Boolean control for one flag does not allocate another flag or
numeric/enum branches. Future runtime status can be Not run while source
behavior is already known.

For every exact API, default, absence or enforcement claim, retain the selected
subject, declaring symbol and consuming implementation with an addressable source
slice. An interface contract alone does not establish a concrete implementation's
parameters or behavior; one reader/helper does not establish another's fallback,
sentinel or diagnostic route. Follow delegates and returned values through callers
that update state, retry, aggregate results or issue diagnostics. Keep each
negative claim bounded to the components, conditions and paths actually inspected.

Reconcile repairs against effective startup and the selected authority: argument
names/units, explicit options, active loader and runner CLI/environment precedence, activation,
forwarding and normalization. Preserving bytes is not preserving their effect.
An intentional higher-precedence choice can be valid; name inactive settings and
why that authority satisfies policy. Resolve conflicting native-output/operator
requirements or retain the concrete conflict and conditional repair. Allocate
assertions for selected effects, without testing unreachable delegated parsers.
For deadlines, locate creation, propagation and consumption relative to retries.
Distinguish documented contract, implementation enforcement, diagnostic level/
routing and observed runtime output; retain conflicts with their actual owner.
Accessible source contradictions cannot become correct by being labeled Not run.
A public-boundary probe proves its tested scope, not application execution or
unselected sibling conformance.
Use the relevant source boundary rather than stopping at the options class:

| Claimed capability | Source to reconcile |
|---|---|
| Supported setup/API | Actual public declaration, argument/result shape and construction path; a remembered symbol or unrelated example is insufficient. |
| Activation and ownership | Entry point that registers/starts the provider or bridge on normal startup; constructing a configuration object alone may not activate it. |
| Record limits | Record creation/update path and the final normalization helper, including supported value shapes, replacement/drop accounting and diagnostic calls. |
| Transport limits/deadlines | Actual encoding/decompression, bounded-read and error branches; identify where the deadline is created, propagated and consumed relative to retries. |
| Diagnostic cadence | All emission paths for one affected record, including warnings and per-value loops; value truncation alone cannot establish the diagnostic count. |

Reconcile rules with the installed SDK/bridge's public APIs and current official
documentation. Record package versions, source URLs/date, applicable stability
of the language's Logs signal and individual features, and unsupported features.
Development or release-candidate status calls for capability verification, not
an automatic upgrade or a reason to skip that language. SDK-author,
instrumentation-library release and semantic-convention-author duties are not
automatically missing application code. A supported SDK default can satisfy a
rule. If the repository owns the selected instrumentation library, assess its
own obligations there; do not reimplement an upstream SDK merely for visibility.

The [log data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/),
[Logs API](https://opentelemetry.io/docs/specs/otel/logs/api/),
[Logs SDK](https://opentelemetry.io/docs/specs/otel/logs/sdk/),
[SDK configuration](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/),
[common configuration types](https://opentelemetry.io/docs/specs/otel/configuration/common/),
[resource merging](https://opentelemetry.io/docs/specs/otel/resource/sdk/),
[event/attribute naming](https://opentelemetry.io/docs/specs/semconv/general/naming/),
[log registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/log/),
[common attribute limits](https://opentelemetry.io/docs/specs/otel/common/#attribute-limits),
[exception log conventions](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/),
[trace context in non-OTLP formats](https://opentelemetry.io/docs/specs/otel/compatibility/logging_trace_context/),
[logging context guidance](https://opentelemetry.io/docs/specs/otel/logs/supplementary-guidelines/),
[OTLP delivery](https://opentelemetry.io/docs/specs/otlp/),
[OTLP exporter retries](https://opentelemetry.io/docs/specs/otel/protocol/exporter/#retry),
[error handling](https://opentelemetry.io/docs/specs/otel/error-handling/), and
[sensitive-data guidance](https://opentelemetry.io/docs/security/handling-sensitive-data/)
are primary sources; the security page is non-normative guidance. Check
individual development features rather than
describing an entire language or exception convention as stable.

Resolve the effective configuration owner before applying environment-based
recipes. A supported, active `OTEL_CONFIG_FILE` loader (or its deprecated
`OTEL_EXPERIMENTAL_CONFIG_FILE` alias) ignores flat SDK environment settings
except variables referenced for substitution; inspect application overlays too.
Do not infer loader support from a variable's presence. Otherwise follow the
installed distribution's environment, programmatic and agent precedence; empty
environment values are unset. Check effective `OTEL_SDK_DISABLED`, native/SDK
filters and resource merge results before diagnosing a missing pipeline.
For supported standard `OTEL_SDK_DISABLED`, the no-op setting covers SDK signals
but has no effect on configured `OTEL_PROPAGATORS`. Inspect startup branches and
plan that disabled-SDK/retained-propagation conjunction; disabled export alone
does not prove it. Preserve the actual SDK limitation and owner when its startup
also bypasses propagator configuration, rather than inventing app wiring proof.
In application-owned initialization, keep selected propagation setup outside
the branch that skips SDK signal providers/bridges. Preserve existing configured
propagators and carrier formats; use the same-path control below rather than
inferring propagation from provider registration.
For supported environment Boolean settings, only case-insensitive `true` means
true; `1` and `yes` do not disable the SDK. Other values resolve false, with a
warning recommended for invalid nonempty values. Let the actual config owner
parse settings; do not apply flat-environment rules to an active file loader.
`OTEL_LOG_LEVEL` controls SDK diagnostics, not application log severity.
User-provided resources take precedence over `OTEL_RESOURCE_ATTRIBUTES` in the
standard SDK merge; preserve operator identity when adding defaults by avoiding
conflicting code values, not by assuming the environment wins. Check decoding
errors and actual merge order rather than replacing the existing provider.
An existing `service.name` in the effective resource configuration is valid
operator identity even when `OTEL_SERVICE_NAME` is absent. Do not add a higher-
precedence Make, shell, CLI, `.env`, launch profile, image or JVM fallback that
replaces it. Resolve resource values with the installed SDK's supported detector/merge, apply new
application defaults underneath supplied values, and inspect the actual merge
order. These local preservation controls exercise the supported selected owner:

| Control | Input and required observation |
|---|---|
| Resource-only identity | Supply `service.name` through the Resource configuration with `OTEL_SERVICE_NAME` and conflicting loader/profile overrides absent; assert that identity in received SDK Resource through the normal launcher. |
| Explicit identity override | Supply the selected higher-priority identity and a different lower-priority value; assert the actual documented winner through normal startup. |
| Absent identity | Remove supplied identity from the actual child environment and active loader/profile; assert the supported default without changing unrelated supplied Resource attributes. |
| Disabled SDK, retained propagation | Through the same disabled initialization, prove effective no-op SDK signals, the selected app-owned provider/bridge activation policy, preserved native output, and actual carrier operations for the configured propagator's selected directions and fields. A separate enabled-path helper test cannot establish this conjunction. |

These are identity/activation controls, not an exhaustive SDK input suite. Build
each child environment explicitly and check key presence and active configuration
before launch. Clearing the parent environment alone does not remove values
reloaded by `.env` or launch profiles. Use an isolated project/configuration copy;
do not delete operator-owned settings. Helper results alone cannot prove normal-
launch identity, and a compound service-name-plus-Resource trial cannot replace
resource-only or absent-identity cases.
These preservation checks are local workflow; SDK configuration defines each
setting's precedence, and an active file loader retains its own contract. Include resource
encodings accepted by that installed configuration owner, such as whitespace
around resource entries where supported. A shell substring match is not SDK
parsing: appending a default after a supplied key the substring test missed can
overwrite operator identity when later duplicate keys win. Preserve the supplied resource
configuration intact when no supported lower-priority defaults mechanism exists.

Let the installed exporter parse OTLP header environment values using its
supported `key=value,key2=value2` encoding. W3C Baggage-style semicolon metadata
is not supported here. Do not introduce a custom parser, print header values
or silently rewrite operator credentials to make a local recipe work.
Preserve selected signal-specific local log headers through that SDK path.
An inherited generic cloud credential conflict does not make an intentional
signal-specific local header a conflict, or authorize an empty header override.

Follow an existing file/stdout forwarding route through its parser, Collector
processors and destination before adding an SDK bridge. It can be operator-owned
coverage; context strings alone cannot prove that route exports canonical OTLP
records. Preserve one collection owner per record. A Collector redaction/filter/
transform processor can satisfy an approved downstream processing boundary,
but cannot close a policy requiring sanitization before SDK or writer capture.
Name the boundary and prove the values at it; local storage before a later
redactor still counts as capture.

For a selected privacy policy, include framework/access/error renderers captured
by that path, not only application logger calls. Preserving sinks, levels,
permitted diagnostic categories and safe formatting does not require retaining
policy-forbidden content. If a selected probe exposes it, inspect a supported
native hook at the boundary the policy requires and rerun the probe; dependency
ownership alone does not make that captured path unselected. Preserve application
behavior and permitted diagnostics instead of disabling all framework logging
or replacing the provider. If no supported hook exists at that boundary, record
the exact limitation and leave coverage unresolved. These are selected privacy
workflow rules supported by the non-normative sensitive-data guidance, not a
universal OTel payload prohibition. Preserve the permitted diagnostic category
at each selected output boundary; retaining it only in native output does not
justify replacing the exported category with a generic redaction label.
An input or attribute that source evidence shows cannot reach the selected
logging path may be not applicable; do not add a capture path just to test it.
A control already required by the bound scenario must still be executed or
retained as not proven, not silently removed from the contract. Inspect all
framework records captured by the selected application bridge, not only a
fixed-message or application-logger allowlist. A framework record observed in
the normal pipeline cannot be excluded from its privacy assessment merely
because the original call-site inventory listed only application messages.
Keep separately routed SDK self-diagnostics distinct from those framework records.
Start from every selected negative trigger covered by a privacy/content assertion.
Resolve its actual outcome and handled or escaping error branch, then inspect
the resolved dependency's logging call before selecting an action or a
source-supported no-action disposition. Reuse a producer trail across triggers
only when its source branch and covered outputs support that parameterization.
In the existing finding/scenario, retain `trigger → resolved producer/symbol and version → native
event/message parameters or throwable → supported policy-boundary action → later
renderers → policy-covered outputs`. Resolve whether the action transforms,
replaces or only denies a record; denial alone cannot preserve a required
category. Apply the action before SDK/writer capture when the selected policy
requires it. Bind forbidden-sentinel absence AND permitted category at every
covered output, preserving application responses and original sinks.
For an unresolved link, name its exact producer/event/API edge and owner, then
the next source symbol or supported probe AND the observation that would decide
support or coverage. A framework name or instruction to find a hook is not that
resolution. Audit records source facts and concrete future controls; runtime
success requires later execution. Reference the trail from each selected logging/
privacy operation it serves, directly or through complete shared parameterization.

### Configuration value types

Resolve a setting's accepted representation as well as its unit. Keep a raw
serialized assignment distinct from a display quantity with a unit label; check
the actual assignment, not prose displaying its interpreted duration. Validate the
actual proposed value against the selected configuration source's declared type,
range and parser. A unit label does not authorize a unit suffix or a different
serialization. Native APIs can use language-specific typed values; inspect their
conversion rather than copying environment syntax into a constructor or vice versa.

For supported standard configuration sources, retain the applicable
[common type rules](https://opentelemetry.io/docs/specs/otel/configuration/common/)
and the [standard environment type rules](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/#type-specific-guidance)
where that source is supported; resolve their selected implementation separately:

| Setting class | Upstream contract to preserve | Capability and conditional acceptance branches |
|---|---|---|
| Boolean, supported flat environment configuration | Only case-insensitive `true` MUST resolve true; other values, including empty/unset, MUST resolve false. Unrecognized nonempty values SHOULD produce a warning. Safe-false naming/defaults are recommended. A rename requires a major version; a default change also requires one except for the specified security allowance. | Resolve actual SDK-disabled/filter parser behavior for true casing, false casing, empty/unset and other nonempty values, including numeric-looking strings. Keep warnings and safe fallback distinct from enabling/disabling effects and original native sinks. Apply the active loader's own contract when flat settings are ignored. |
| Duration and timeout | Values MUST represent non-negative integer milliseconds; negative values MUST generate a warning and be ignored, using a default when defined. Timeout zero SHOULD mean no limit, which MAY use a sufficiently large internal duration. | Identify the actual parser, accepted serialized representation, conversion and effective fallback. Distinguish ordinary duration zero from timeout-zero semantics. Resolve or plan positive, zero, negative, fractional, malformed and representability/overflow cases; an accepted fraction is not integer-millisecond conformance. |
| Integer | Support SHOULD cover 0 through 2^31-1 and MAY extend it, subject to the setting's valid range. Unparseable or out-of-range numeric settings SHOULD be warned about and ignored; retain the post-stabilization compatibility qualification and its MUST treatment for new implementations. | Resolve actual accepted range, boundary, out-of-range, overflow, fractional and malformed behavior, including warning and fallback. A rejected value falling back to a default does not prove the proposed bound is effective. |
| Enum | Sources MAY extend supported values. If an enum accepts a null/no-op choice, its name MUST be `none`. Standard environment enums SHOULD be case-insensitive; unknown values MUST generate a warning and be ignored. | Resolve supported values/extensions and actual case handling; carry supported, differently cased, unknown, empty/unset and applicable no-op branches. An unrelated Boolean test cannot establish enum behavior. |
| Environment/code equivalence | Environment configuration MUST have a direct code equivalent. | Identify the corresponding public configuration path and conversion for each selected setting. Compare equivalent intended values and effective results; preserve native typed API capabilities without imposing serialized-environment syntax on them. |

Apply the branches above to actual selected operator/environment readers and
precise input-behavior claims. For a fixed typed public option, prove its applied
value, units, native API, startup consumption and operator preservation without
selecting unreachable serialized input permutations. Preserve versioned
source/default dispositions for ordinary delegated settings; neither path
requires application parser code or certification of unused SDK inputs. Where
necessary source is genuinely unavailable, retain the missing implementation
and conditional check. A group label or another type's scenario cannot prove
a selected branch.
The common specification's SHOULD to show the original value in configuration
errors supports diagnosis; retain any privacy constraint instead of exposing a
forbidden value. Preserve adequate defaults and report unsupported capability.

## LOG-SPEC-CLOSURE -- Reconcile sources, implementation and proof

Begin with the applicable official source sections, not only this guide's rule
names or a keyword search. Record source URL, version/date or supplied snapshot,
requirement level, applicability and owner (SDK, bridge, instrumentation library,
semantic-convention author, application, collector or operator). Attribute
requirement levels bind the instrumentation library; inspect its ownership
before assigning an application fix. Supplementary guidance adds no normative
SDK requirements.
Follow applicable normative references imported by those sections, including
common type and value rules. Record inherited obligations with their source,
strength and owner; reading a referring page alone does not establish coverage
of its referenced contract. Keep this traversal scoped to the selected path.
Separate upstream requirements, optional/development capabilities and the
repository's local destination/privacy policy. If current sources are unavailable,
name the snapshot and leave unsupported conclusions unverified.
Apply **Source and applicability** above to the selected path's record/time/
severity/value semantics, context/propagation, Resource/scope, initialization,
filtering, privacy, limits, delivery, diagnostics and lifecycle. Keep a compact
source-to-evidence matrix in existing schema fields; do not add JSON keys or
artifact types. For a selected normative/conformance claim, bind necessary primary
and imported clauses exactly: a parent topic or downloaded file is not a
child-clause binding. This layout makes those selected bindings addressable:
Record source/config/default evidence, disposition, finding/scenario IDs where
needed and the actual proof boundary for each required row.

| Source and exact clause binding | Strength, conditions, applicability and specification/component maturity | Owner | Current capability/evidence | Finding/control and actual proof |
|---|---|---|---|---|
| Retained excerpt with hash/lines, or precise clause text with source/date | Preserve each distinct duty, permission and qualifier | Actual component | Supported/default/unsupported/unverified with current evidence | Selected mapping, executed boundary or concrete future check |

A grouped retained excerpt (file/hash plus lines or an addressable snippet) can
bind several clauses when each owner, disposition, condition and strength remains
addressable. Shorter summaries and generic "see audit" links cannot replace those
bindings. Instrumentation/verification should reuse unchanged bindings by exact
immutable audit evidence row, then reconcile current dependency capability and
executed receipts separately. Re-extract when source/applicability changes;
never inherit installed capability or runtime success from the audit. Without an
audit, use the normal direct instrumentation report, not a fabricated audit or
extra artifact.

A source binding preserves a requirement, not proof that its mapped control
exercises it. Match selected promises and claims to assertions for their distinct
conditions, input branches, fields and operations. A related control or delegated
disposition cannot close a critical invariant; retain its concrete missing check
or conditional resolution rather than a blanket future label.

Preserve each applicable clause's condition, action, strength and owner when
condensing source text. Recommendations, permissions and failure fallbacks do
not substitute for one another. Keep applicability qualifiers and cross-cutting
configuration duties addressable, either in each affected row or an explicitly
referenced shared row. Read the saved rows against retained source bindings,
not only a page title or draft summary. This is a local completeness check,
not an additional OTel implementation requirement.
Keep the direction of conditional requirements intact: an obligation when A
is present does not imply the reverse obligation when B is present. Preserve
the original conjunctions, exceptions and subject when condensing a clause.

For a selected OTel requirement, read the actual cited primary-source slice or
heading and match its subject/operation, conditions, strength and action to the
claim. A correct file/topic with an unrelated range does not support that claim;
implementation or an option comment is capability evidence, not the normative
source. Correct the binding or retain the unsupported claim as unverified, without
inventing a stronger rule or importing unrelated sibling clauses. Apply the same
claim-to-slice check to implementation evidence and its terminal caller effect.

For audit, emit concrete application-owned gaps through the normal findings and
acceptance flow. For instrumentation, implement the authorized ones and retain
unselected gaps. For verification, independently reconcile the matrix with real
call sites and the selected contract; report omitted obligations and unproven
wiring without editing the app or rebinding prior evidence. Source review,
SDK/bridge probes, application startup, receiver receipt and backend joins are
different proof boundaries. Passing one cannot close the others. A rule mention,
schema check, total test count or supplied ID strings cannot establish full
guideline coverage. Any omitted applicable row leaves that claim incomplete.

Before finalizing, perform a per-scenario check of every required assertion and
control named by its trigger and acceptance criteria, including negative controls.
Keep missing checks not proven rather than completing a row from related passes.
Choose each executed scenario and instrumentation item result's `proof_mode`
from the actual path, not its test filename, package, suite command or audit level:

| Actual evidence path | Runtime proof mode |
|---|---|
| Isolated SDK/bridge records inspected in memory | `unit` |
| Isolated real SDK/bridge/exporter with decoded loopback OTLP receipts | `unit+otlp` |
| Actual application-owned setup, helper or lifecycle exercised by an application test | `app_test` |
| Claimed event traverses normal application startup/entrypoint and call site to the observed boundary | `full_runtime` |
| Source review, contract-only assessment or an unexecuted plan | Applicable `static`, `contract_only` or `not_run`; no runtime credit |

A test stored in an application package can still be a pure SDK fixture.
Conversely, a focused test of an actual app helper can legitimately be `app_test`.
Do not map every `focused call-site` audit row to `app_test`, or label every
item `full_runtime` because another scenario starts the app. Retain the scope
of each claimed property and do not imply receiver receipt from in-memory proof.
Audit uses a different field: choose `proof_level` `focused call-site` for a
focused capability test, or `either` when its contract allows both focused and
application proof; do not label an isolated SDK/bridge fixture `full runtime`.
Reserve that audit level for normal application execution, including agent or
preload startup, framework-resolved routes, automatic metrics or installed log export.
Audit plans these checks; instrumentation and verification reconcile actual
results. These are local report-contract checks, not new normative SDK requirements.
During audit planning, group controls by the boundary actually needed to prove
each claim before assigning stable scenario IDs. A dependency's presence or an
application package location cannot promote an isolated capability check to
application proof. Use `either` only when one identical contract genuinely permits
alternative adequate proof. Keep each grouped claim's owner and disposition
explicit. Application scenarios may reference focused prerequisites without
claiming that their execution occurred through the application path.
Map every selected finding's promised operation/outcome, including its
`expected_telemetry` and acceptance text, to an addressable planned trigger and
acceptance control. Classify each control's execution path first,
then group compatible controls and assign IDs, environments and `proof_level`.
That scalar level applies to every trigger/acceptance assertion in its row; a
prose caveat cannot give one subcase a different level. Give differing paths
separate scenario IDs and reference their relationship. An identical contract
may use `either` only when either boundary independently supplies adequate proof.
Before serializing, compare promised outcomes, allocated controls and row levels
to find omitted operations or mixed scopes without changing the selected scope.
A related SDK/exporter or receiver acceptance check does not transfer that
owner's duty to application code; retain unsupported/unverified capability and
conditional future checks rather than proposing application substitutes.

Expand each bound scenario's trigger AND acceptance criteria into individual
controls in existing evidence fields or a Markdown checklist. Prefer doing this
before authoring targeted probes; the required outcome is a complete, independently
contract-derived reconciliation, not a particular tool-call order. Include list members, input variants, requested operations and event
orders: scenario ID/control text, expected input/outcome, effective launch/exporter
configuration, named test/subtest or assertion, planned command, proof boundary
and an evidence-derived verdict. Initial discovery or tests can precede the
inventory. A later inventory is valid when it independently covers the complete
required contract and reconciles actual assertions, receipts and missing proof.
Do not derive the required control set from only the tests that happened to pass. A grouped display is valid when it references a parameterized case table,
test or assertion/output that makes every input, operation and event order
individually addressable. One physical report row per control is not required.
Copying a whole acceptance paragraph into one cell without those bindings is
still only a scenario inventory. Preserve a required
conjunction on one owned path as joint assertions; do not split it into unrelated
passing probes. One invocation can supply several controls, but
link each result to its own assertion and concrete output/receipt. A suite's zero
exit proves only the assertions present in that suite, not every bound control.
Preserve the bound audit IDs and schema. Derive scenario and item verdicts from
their complete required-control sets; initialize unmatched controls Not run/Not
proven. A blanket Working/default-true assignment plus a short exception list
cannot establish assertions that lack direct evidence. An opt-out run cannot prove delivery through an
enabled pipeline. An overall Partial result does not make an incompletely tested
individual Working row accurate.
For each item, read its own change/name/`product_view` back against the direct
assertions. A configuration item promising bridge, batching and lifecycle cannot
be Working from opt-out tests alone when its final drain is unproven. Bind the
item's required claims explicitly instead of selecting a passing scenario by
item type or copying the first scenario's mode/visibility. Direct item proof may
coexist with incomplete related scenario coverage: do not downgrade a directly
proven claim merely because an attached ancillary probe is focused or incomplete.
State that narrower item claim and the ancillary boundaries in existing evidence;
do not present their combined observations as all proven at the strongest mode.
Derive failures from each control's own contract too: another control's gap is not
this control's failure unless it is a necessary prerequisite.
Later stages retain those bound IDs and distinguish observations in existing
fields; do not promote a focused error seam to full runtime in a parent row.
If a frozen row's controls have different observed boundaries, name those
boundaries in its existing evidence/observations. Do not give the whole row the
strongest mode from one control. Keep incomplete required-scope closure not
proven without rebinding the audit to accept different proof.
Derive working status from those individual results, not a total test count or
an automated finalizer that marks every selected scenario working together.

For a claim combining properties, bind its evidence to the same owned path and
operation. Separate passing unit tests for context copying and synchronous
real-span receipt do not prove an asynchronous log-to-span join. Mark that
combined claim partial until one scenario traverses the owned handoff and
joins that worker/callback log to its actual SDK span at the claimed receiver.
Apply the same reasoning to other combined claims: do not assemble end-to-end
coverage from unrelated paths or independent probes.

## LOG-RECORD -- Preserve record meaning

Check the real bridge's numeric severity mapping, source severity text, body,
logger/scope and timestamps. Common single-level mappings are DEBUG=5, INFO=9,
WARN=13 and ERROR=17; finer source levels can use their documented range.
These range labels do not prescribe `SeverityText` or its casing. Preserve the
selected bridge's actual source-text mapping; do not uppercase it to match a
numeric band name. The [data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/#field-severitytext)
allows a short-name substitution when SeverityText is absent, not replacement
of a present source value.
Never copy a source logger's numeric level directly into SeverityNumber.
Unknown severity in a source with a level concept may remain 0/absent; do not
invent an ERROR classification. If an event is known erroneous and its source
has no severity concept, the data model recommends ERROR=17 during mapping.
Keep that recommendation and its preconditions distinct from a universal MUST.

Preserve the event's occurrence Timestamp when available; ObservedTimestamp
represents collection time. Do not replace an older event time with export
time or assert that the two clocks must be equal. Treat nanoseconds/seconds
conversion explicitly and preserve 64-bit nanosecond precision. Optional
absent fields alone are not defects. Preserve
structured values rather than turning an entire structured record into an
opaque string. EventName is an event classification when applicable, not a
mandatory field on ordinary application messages.
The language's supported empty value (null/None/nil), zero, false, empty strings
and empty arrays are meaningful AnyValues. Assert presence and type separately
from truthiness/nonemptiness. Preserve accepted null array entries and their
positions; an exporter unable to export null may substitute zero, false or an
empty string. Check that capability before accepting a substitution; dropping
an entry is different from retaining its position. Check the selected
bridge's supported conversion before claiming preservation; a direct SDK test
does not prove the bridge handles every value, or authorize replacing it.
For selected semantic events, keep EventName free of per-occurrence IDs; put
permitted varying values in attributes. Reuse applicable semantic attributes;
new application keys should use a nonconflicting application/company namespace,
and new `otel.*` keys require specification approval. New names MUST be valid
Unicode; lowercase, dot namespaces and snake_case components are naming SHOULDs.
An established ecosystem concatenated form SHOULD take precedence over underscores;
an individual API/SDK symbol's spelling alone is not that evidence. Preserve
existing semantic conventions and consumers; these recommendations do not require renaming native
messages, established keys or dependency-owned mappings. Where call-site fields are
selected, check the installed bridge's convention version and current `code.*`
keys before changing deprecated mappings; do not upgrade or rewrite its SDK.
Keep scope identity consistent rather than attaching conflicting scope attributes
to the same Logger identity. Optional development `log.iostream`,
`log.record.original` and `log.record.uid` are not mandatory on every record.
When `log.iostream` is supplied, the applicable known `stdout` or `stderr` value
MUST be used; a different stream MAY use a custom value. The registry permits
`log.record.original` when the original was string-like AND Body does not already
contain that value; this conditional MAY is not a converse prohibition. Bound
and sanitize original content before constructing it. Two distinguishable records
MUST NOT share a supplied UID. A trace ID is not a per-record UID.

For a newly selected event definition, document when it occurs, its name,
occurrence timestamp, default severity and permitted attributes, including
sensitive, expensive or large fields. Reuse relevant attributes without copying
every span attribute; failure outcomes use applicable `error.type` conventions.
A named event represents a timestamped occurrence, a span a duration, and span
attributes properties of the whole operation. Ordinary diagnostic messages
remain ordinary logs; events can occur outside a trace without inventing a span.
For a semantic-event definition you author, the Development conventions MUST NOT
prescribe ObservedTimestamp or SeverityText; a Body definition is permitted only
for a string display message. These are definition-author restrictions, not a
ban on SDK-populated observation/severity fields or structured ordinary LogRecord
Body. On a supported new event path, use the canonical EventName field rather
than the deprecated `event.name` attribute. Resolve existing bridge/version migration
policy before changing an older mapping; do not upgrade solely for this example.

## LOG-CONTEXT -- Correlate without inventing or leaking context

Use the execution context at the log call, not a remembered last span. Check
top-level TraceId, SpanId and TraceFlags, including a valid unsampled context
and concurrent/asynchronous work. Restore/detach context after a request;
outside-span logs must not inherit the preceding request's IDs. An unsampled
span can still supply valid correlation even when no span is exported.
When a record includes SpanId, the data model says TraceId SHOULD be present
too; it does not imply the inverse recommendation for every TraceId.
If preservation of other carrier/context fields is promised, bind each to its
own assertion at the real context or carrier surface. A general propagation
scenario or canonical log-ID assertion cannot prove every promised field, and
does not authorize inventing additional top-level log fields.

For a cross-process join, also check the installed propagator against the actual
peer carrier. A locally correct logger cannot repair a rejected incoming
`traceparent`. Record the peer's emitted flags and extracted context through
supported APIs; distinguish a propagator capability limit from missing logger
wiring. Resolve compatible official dependencies within the existing runtime
constraints, or leave the affected join explicitly unsupported/unproven. Do not
strip peer flags, copy IDs manually, replace the provider or silently raise the
runtime floor to make the test pass. This is a compatibility verification
workflow grounded in the [Propagators API](https://opentelemetry.io/docs/specs/otel/context/api-propagators/).
Its W3C parsing/validation requirements bind the propagator implementation.
Rejecting a valid peer carrier is a dependency conformance gap to resolve or
report, not optional covered behavior or a repair to application logger wiring.

Do not introduce sampled-only filtering as a log baseline. Inspect explicit
operator filtering first: newer SDKs can offer development `trace_based`
filtering, defaulting to false. Preserve an explicitly selected supported
policy and test its intended drops separately. Do not fabricate or force-sample
a span to make correlation pass. Test both sampled and unsampled contexts and
a no-context call, checking exact IDs and flags rather than nonempty strings.
Where supported, development `LoggerConfig.enabled` should default true and
`minimum_severity` defaults to 0; severity-0 records bypass that threshold.
A disabled SDK/logger is a no-op for that path, not proof of a missing bridge
or permission to suppress other native sinks. Test selected filters separately
from missing wiring, including severity-0 and no-context bypasses. Configuration
changes may become visible eventually; do not demand instantaneous SDK updates.

Trace the actual tracer/context manager, provider initialization, log bridge and
record call site. When tracing is configured, prove correlation with SDK-created
spans: emit through the application's logger inside a real parent and child
span, including owned asynchronous handoff. At the claimed receiver/backend
boundary, join each sampled log's canonical top-level TraceId and SpanId to the
exact received span and check parentage plus source-backed resource identity.
Compare TraceFlags with the actual SDK context, preserving its defined bits;
do not assume a sampled SDK context has only a single flag bit. Injected
non-recording contexts remain useful unit controls, but cannot prove tracer
startup, span export or an end-to-end join. Do not manufacture IDs, add a second
provider or invent spans for unowned operations merely to satisfy a test.

For each call, derive the expected SpanId from the bridge/API's selected context,
including explicit caller-side capture when used. That span may be an INTERNAL
framework/handler child. Verify its ancestry to the correct request separately;
do not require the log to use a SERVER ancestor's SpanId or replace valid context
merely to satisfy a test. A SERVER-only target needs evidence that this is the
associated span on that path.

Where the application owns an async boundary, require at least one combined
scenario: capture a real SDK parent/child context, traverse that boundary,
emit through the worker/callback's application logger and join that record to
the exact received SDK span, checking flags, parentage and resource. A child
may start before dispatch or inside the worker according to the actual path.
Reuse existing spans/propagation; controlled test spans stay within the existing
provider and do not justify new production instrumentation or unowned work.
Label the joint scenario explicitly in the handoff. A known-ID async test plus
a separate synchronous real-span test cannot replace it.

Keep valid unsampled context separate from missing context: sampling may
intentionally prevent its span from being exported. For an exact context claim,
compare canonical TraceId/SpanId/TraceFlags with independently observed SDK
context selected by the logging/bridge API for that record, including explicit
context or caller-side capture, through supported APIs or a test seam. A later
queue/export worker's ambient context is not a substitute for that selected context. A matching
trace, nonempty SpanId or agreement between two logs is not that expected value.
Do not require an exported unsampled span, force sampling, manufacture IDs or
add production identifier fields for a test. During audit, choose a feasible
focused, application-test or normal-runtime observation before binding the
control. If exact state is observable only at a focused boundary, plan separate
focused exact-value and normal-runtime behavior controls without promoting one
to the other. A required combined application join still needs its own same-path
proof. Once acceptance is bound, missing proof cannot be closed by a later
boundary downgrade. Outside-span logs may legitimately have no context. Ordinary attributes or strings named
`trace_id`/`span_id` are not the OTLP record's canonical context fields. If the
selected collection path is a non-OTLP JSON/text sink, check its supported
context injection and customary top-level `trace_id`, `span_id`, `trace_flags`
representation separately; OTLP receipt alone cannot prove formatted stdout
correlation. Preserve existing sinks and explicit format policy.

## LOG-ASYNC-HANDOFF -- Capture before scheduling and restore after work

For each owned asynchronous boundary, identify where the log record and its
OTel context are captured relative to executor, callback and logging queues.
Capture the caller's context per work item before scheduling. Reuse verified
framework/agent propagation; do not add a second wrapper merely by language.
Use the detected language guide's supported handoff and cleanup mechanism,
including separate handling for approved application context fields.

A standalone bridge after a logging queue can observe the queue worker's
context instead of the caller's. Preserve a supported context-capturing queue
path, or keep the existing bridge on the caller side beside the original
asynchronous sink and use the SDK batch processor. Never duplicate bridges.
Test sampled/unsampled context, exact request pairing under concurrency, and
caller detach/restore across the selected handoff.
For a promised reuse control, observe the same execution unit handling distinct
work-item contexts and then context-free work, checking each record against that
item's actual SDK context; fresh concurrent work sharing one context is not reuse
or cross-request isolation proof. If source owns only fresh work items, audit may
scope application reuse as not applicable and separately select a focused helper/
bridge capability probe; do not add production worker behavior merely for proof.
Any focused reuse already promised remains required at its bound boundary.
A selected missing-propagation control must actually omit capture/transfer on
that handoff path while retaining the other relevant inputs, not merely emit an
outside-context record directly. Its expected loss demonstrates the unsafe path,
not acceptable production configuration. Exercise error/cancellation cleanup only
where owned behavior supports it, or keep a separately selected SDK probe focused.
Do not add business cancellation behavior; ending a span or detaching context is
not cancellation of scheduled work. Keep the bound audit unchanged downstream.
Link the combined real-span async scenario required by LOG-CONTEXT; independent
handoff and join scenarios alone leave that combined obligation unproven.

## LOG-EXCEPTION -- Preserve exception semantics within privacy policy

Where exception details are already collected or explicitly selected, use
the supported bridge/SDK exception mapping and `exception.type`,
`exception.message`, and `exception.stacktrace` as applicable. Do not export
an exception object's arbitrary serialization under invented keys. Minimize
and sanitize message, stack, nested structured values and formatter/MDC fields
before the exporting processor; truncation alone is not redaction.
Hashing a small, predictable input does not establish anonymization either.
Follow the selected privacy policy and capture boundary rather than declaring
a hashed identifier safe by algorithm name.

The exception-log convention explicitly excludes logging bridges from its
instrumentation-specific recording guidance. Do not force every bridged error
to add EventName, change severity, emit a second event, or migrate existing
span exceptions. Preserve bridge semantics and versioned opt-ins. For newly
selected instrumentation exception events, check the applicable conventions
and stability, associate the actual operation context, and choose severity
from impact. No policy permission to collect a message/stack means omit it
and retain permitted type/category evidence, not enable capture for a test.
For a selected instrumentation exception event, the convention requires type
or message when the other is unavailable; if policy permits neither, report the
semantic limitation without capturing forbidden content. Do not apply this floor
to ordinary bridged messages. Instrumentation should avoid artificial exceptions
used only to represent an unsuccessful status; this development recommendation
does not forbid an application's intentional error log. Where an installed Emit
API derives exception attributes, explicit user attributes take precedence.
Prefer a supported exception-instance Emit API for selected instrumentation
only when policy permits that capture; otherwise retain just permitted fields.
For a selected exception event, check the versioned recommendation for an
operation-specific `.exception` name or generic `exception` handler name.
Check deprecation/version policy for `exception.escaped`; do not migrate span
exception behavior or delete approved compatibility fields merely by keyword.

Apply a selected exception-field allowlist to canonical fields and custom
aliases alike. Compatibility alone does not authorize an excluded representation.
When policy permits only type/category evidence, omit prohibited message, stack
and equivalent aliases, and assert their absence. Do not pass the raw exception to a bridge
and rely on truncation to hide its contents. Preserve an alias only when the
applicable policy explicitly permits it; do not remove unrelated application
metadata merely because it is not an exception attribute.

## LOG-LIMITS -- Bound record cost

Inspect effective log attribute count/value limits and existing operator
values; SDK defaults may already suffice. `OTEL_LOGRECORD_ATTRIBUTE_COUNT_LIMIT`
and `OTEL_LOGRECORD_ATTRIBUTE_VALUE_LENGTH_LIMIT` are signal-specific settings.
Resolve the selected SDK's actual inputs, fallbacks and defaults; apply the
conditional model/general precedence below when both families are implemented.
Span limits do not configure log limits. When the selected implementation and configuration are
available, resolve and report their effective values or unlimited behavior,
precedence and source evidence now. A future boundary test does not substitute
for accessible configuration facts; keep those facts separate from unexecuted
runtime behavior. If resolution is genuinely unavailable, state the exact
missing source/configuration and its future check.
Attribute length limits do not bound Body, nested
payloads carried in Body or all exception formatting: use a reviewed application
or processor policy for these surfaces when required. Avoid arbitrary new limits
without a source-backed need. When current messages are bounded and no Body
policy or size problem is established, preserve them and record that a new Body
cap is not applicable; do not import GenAI capture thresholds into ordinary logs.
Exercise selected oversized attributes/body, retained
identity/context, dropped-attribute accounting where supported, and privacy
after processing. Do not promise lossless export after truncation/drops.
Resource attributes SHOULD be exempt from common attribute limits; log-record
limits do not configure Resource limits. Preserve source-backed identity rather
than applying a record attribute-count budget to its Resource.

When constructing Body or attributes is expensive, use the detected native
logger's supported enablement query before that work. Check at the actual log
call, including inside an owned worker/callback, rather than caching a decision
across configuration changes. The OTel `Logger.Enabled` API is an optional
optimization for direct OTel emits; a cheap emit does not require a guard.
An OTel-only disabled result must not suppress an enabled original native sink.
Keep filtering independent of this optimization: callers may emit directly,
and processor `OnEmit` must still apply its configured filter. Do not add
unsupported queries, new filtering policy or a provider to copy an example.

Name the setting or public option that implements the selected count/value
policy; a promise such as "supported log limits" followed by numbers is not a
repair mechanism. Resolve the installed/project-compatible API first and apply
it to the existing provider owner. Use the public count/value options in the
detected language guide as capability leads, not new-provider or
dependency-upgrade requirements. Do not copy another language's configuration
shape into this provider. Preserve its resource, scope and existing processors.

Keep the Body/privacy policy separate from these options. For each selected
limit, specify below-limit, exactly-at-limit and above-limit inputs with units
and expected preservation/truncation/drop behavior. Include non-ASCII input
when the policy measures UTF-8 bytes. Preserve an adequate verified default;
preserve independent operator policies and unselected scopes.

State boundary outcomes, not only test sizes: below/at the selected limit
preserves permitted input; above a count limit retains at most that count and
accounts for discarded attributes; above a string-value limit truncates to at
most that length. Use explicit ASCII-character inputs for an unambiguous
string-length boundary, then check the installed SDK's Unicode behavior before
claiming broader character handling. Body overflow follows the separately
selected application policy, such as valid UTF-8 truncation or dropping, with
its own expected outcome and loss accounting. These common attribute requirements
are conditional on the selected SDK implementing the corresponding limit.
SDKs SHOULD apply default truncation according to the upstream configurable
parameters. Preserve the following distinct clauses from the
[common attribute rules](https://opentelemetry.io/docs/specs/otel/common/#attribute-limits):

| Implemented attribute-limit surface | Required behavior and capability evidence |
|---|---|
| Value length | Strings longer than the limit MUST be truncated counting each character as one; byte arrays MUST be truncated counting each byte as one. Apply the limit separately and recursively to string arrays, AnyValue arrays and map values. Other value types MUST NOT be truncated. Follow the actual normalizer and distinguish supported, unsupported and unresolved shapes, including actual Unicode handling. |
| Count | Count top-level attributes only, not nested map entries. Above the limit the added attribute MUST be discarded; otherwise it MUST NOT be discarded. Resolve actual drop accounting and preservation of identity/context. |
| Depth | Count the top-level value at depth 1 and increment when descending into arrays/maps. Arrays/maps beyond the limit MUST become an empty value; otherwise values MUST NOT change because of depth. Resolve implemented/unsupported depth handling and corresponding boundary outcomes; absence of a public option alone is not enforcement proof. |
| Configuration | Implemented limits MUST be programmatically configurable; option names SHOULD match the specification. If both model-specific and general limits are implemented, resolution MUST try model-specific, then general, then the model-specific default and finally the general default. Inspect that exact selected-component chain instead of assuming every SDK has general fallback. |
| Diagnostics | A limit diagnostic MAY be emitted for truncation/discard/replacement, but MUST NOT occur more than once per affected record. Resolve the actual per-record behavior across all emission paths; the Logs SDK discard-diagnostic SHOULD remains a separate clause. |

These attribute limits do not cap Body. Resource's SHOULD exemption and the
separate metric attribute rules retain their own scope. Do not add application
normalizers, provider replacements or forced SDK upgrades to imitate an
unsupported upstream feature; retain its exact capability disposition and
conditional test. An options builder proves configuration, not normalization.
If already selected, the development external-content `_ref` convention needs
a registry-defined base attribute and a string reference (preferably an absolute
URI); it does not authorize new storage or moving forbidden content elsewhere.

## LOG-DELIVERY -- Bound buffering and make loss visible

Identify the existing processor first. For an OTLP batch path, use the existing
provider's batch processor and check supported log-specific
queue, batch, schedule and timeout settings (`OTEL_BLRP_*` where supported);
`OTEL_BSP_*` configures spans. SDK defaults can be suitable; record the effective
values, keep batch size within queue size, and use public APIs when a language
does not consume those environment variables. A bounded queue may drop logs
when full. Do not promise durable or exactly-once delivery from an in-memory
batch processor; the one-record acceptance check is a healthy-path duplicate
check, not an OTLP network delivery guarantee.
The built-in simple and batching processors [MUST synchronize calls to the
exporter's `Export`](https://opentelemetry.io/docs/specs/otel/logs/sdk/#built-in-processors)
so those calls are not invoked concurrently. Assess that processor/exporter
invocation boundary using the selected SDK's asynchronous completion contract;
concurrent transport requests/retries inside the exporter are a separate concern.
Supported built-in synchronization is coverage, not an app mutex requirement.
For an owned custom processor, include concurrent emit/flush/export acceptance;
retain a genuine SDK limitation with its owner rather than replacing the SDK.

An SDK stdout/console exporter may legitimately use a simple processor; batch
and queue settings then do not apply. Assess synchronous cost instead, preserve
the operator-owned branch, and do not confuse that exporter with a native
console sink. Its [unspecified format](https://opentelemetry.io/docs/specs/otel/logs/sdk_exporters/stdout/)
is not a production format contract.

Exercise the selected receiver-fault/operation combinations, bounded shutdown
after final logs, and overload when the application has a source-backed risk.
For each exercised fault/operation, assert its application outcome, own native
records, bounded secret-free diagnostics and configured unrelated-signal
progress against that trial's raw outputs. One operation under a stall cannot
supply another selected operation or a selected refusal case. An HTTP 200 with
OTLP partial-success rejected records is not full acceptance. Report attempted,
received, rejected and dropped evidence separately; never infer receipt from a
successful enqueue or flush call alone.
For each selected stop control, save a compact plan:
`request kind → recipient/process or process group → launcher forwarding →
effective application handler/finalizer; permitted outcome; budget/source`.
Name how that path and order will be observed through normal startup; stopping
a launcher or cleaning up a child alone does not prove application drain.
A drain claim needs a genuine pending-record witness when the selected lifecycle
owner enters provider drain, possibly after the stop request and finalizer logging,
and that record's receipt attributable to shutdown before process exit. A pre-stop
emit may already have exported; holding a receiver response may show only an
in-flight export. Resolve queue/interval or equivalent supported evidence and
the actual shutdown/export order. Reuse an existing real application operation/
log where possible; do not add production logging solely for a test.
Assert the final record's own selector/predicate, body/severity/count/time,
Resource and associated or legitimately absent context, and receipt/exit order.
Check per-body/identity multiplicities, both trace and span IDs (or their required
absence), and this stop cycle's time interval. An aggregate count can hide one
missing record plus a duplicate. A shared predicate or global scan is valid when
it actually evaluates those fields on this final record and phase; another
trial or earlier record cannot supply them.
If repeated stops are selected, resolve effective handler registration after the
first request, including listener removal and default fallback; a finalizer guard
alone does not establish the next request's path. Name the selected second request
and recipient and deliver it to the same process during active final logging/drain.
Assert the selected policy's outcome and budget: uninterrupted-drain policy requires
non-interruption and once-only finalization; allowed forced termination is a separate
control and cannot establish graceful drain or imply final-record receipt. Keep
independently observed receipts accurate without imposing unselected request
combinations. Repeated/forced semantics remain N/A when unselected.
Where implemented, [development SDK log metrics](https://opentelemetry.io/docs/specs/semconv/otel/sdk-metrics/) can supply
creation, queue-pressure, processed and exported counts. Record each instrument's
stage and retry/rejection semantics; created/processed is not receiver acceptance.
Do not add duplicate application metrics or assume unavailable instruments exist.
For a selected application-owned extension callback, bind a compact operation
contract in existing evidence: applicable source clause and conditions/strength,
actual owner, callback actions/assumptions, and assertion or exact limitation.
A selected processor `OnEmit` runs synchronously on the emitting thread and SHOULD NOT block or throw;
synchronous alone does not establish those recommendations. For directly
registered processors, record mutations MUST reach subsequent processors.
Keep SDK dispatch/visibility duties distinct from the app callback's behavior,
and reconcile these selected conditions before calling its plan complete.
Do not expand this into every unselected SDK operation. For selected asynchronous
processing, retain a supported snapshot/clone rather than mutating an unsafe
shared ReadWriteLogRecord after `OnEmit`, and verify concurrent isolation.
Built-in processors need no replacement. A selected event-to-span bridge must
still forward the log record; independent filtering retains its own conditions.

Compose the complete export/retry deadline rather than assuming a per-request
timeout bounds the entire operation. Test a receiver that stalls as well as one
that fails immediately. Use the existing SDK processor/caller deadline or a
supported public option to satisfy the selected overall budget; preserve a
verified adequate default. A client timeout does not prove zero receiver
acceptance: a receiver can accept after the caller stops waiting. Keep delivery
unknown until receipt evidence resolves it.
For HTTP full success, the server MUST respond with HTTP 200 and a conforming
ExportLogsServiceResponse in the selected encoding, with `partial_success` unset.
For a known N-record request, that full-success response acknowledges all N
accepted and zero rejected; it does not establish backend persistence. A generic
HTTP 200 with an invalid/unrelated body is not this protocol control. Where
response classification is selected or claimed, retain this positive control
alongside its partial/warning/failure controls in the source matrix and saved
acceptance assertions.
Inspect the actual status/body handling before describing the SDK's capability.
A success result alone does not prove that the client decoded a conforming body
or interpreted partial rejections. Retain source-known defaults/checks separately
from an unresolved adapter link and unexecuted runtime enforcement.
When an OTLP response has populated
`partial_success`, the client MUST NOT retry that request, including an inferred
rejected subset; this also covers warning-only responses with zero rejections.
Keep request-attempt counts, received/accepted/rejected record counts and local
drops distinct; receiver rejection is not evidence of a local queue drop.
Account for every received batch/attempt rather than only the last captured
request. Retain each trial's client terminal outcome, including partial and
warning-only responses, beside its complete request/response evidence.
For protocol response-classification proof, keep the exporter's retry mechanism
capable of another attempt and include a retryable-response positive control
under that same retry policy. Disabling retries, allowing only one attempt or
exhausting the budget before a retry is possible proves that policy/budget,
not that the response was classified non-retryable. Preserve operator settings:
if they preclude this distinction, retain the scoped application result and use
an explicitly separate supported SDK control or leave classification unproven.
This is a test-validity rule, not an OTel requirement to enable retries in every
application.

A completed negative OTLP response is a known protocol failure, not a request
still awaiting a response from a stalled server. Record the response and any
observed retry exhaustion. Keep acceptance uncertainty where the protocol leaves
it unspecified or evidence does not resolve it: after an oversized partial-success
response fails, OTLP explicitly leaves acceptance unspecified. Backend persistence
is a separate boundary. For a valid partial-success response with known request
count N and rejected count R (0 <= R <= N), report acknowledged accepted N-R and
rejected R separately from SDK emissions, attempts and received copies. Controlled
receiver rejection policy or observed late acceptance can resolve more counts;
neither a client failure result nor received bytes alone proves persisted loss
or success. Unknown accepted counts can be valid after a completed negative
response: the protocol does not always return per-record counts. They do not
make a known failure response pending. Record the observed response and terminal
retry decision separately, such as non-retryable HTTP 400 or a completed HTTP 503
whose server wait cannot fit the remaining export budget. Assess that evidence
across the report and raw observations; do not invent zero acceptance or rejection
counts merely to fill a field. A receiver recording that it wrote HTTP 503 does
not prove the client observed a completed 503 response. Match each batch to the
SDK's actual terminal result and timing: a client deadline may have expired first.
Retain server response intent and client timeout/failure as separate observations.
Use one ledger row per batch/attempt in the existing Markdown evidence section;
join retries by the decoded batch fingerprint before calculating record totals:

| Batch/attempt and raw evidence | Decoded N | Server status/intent | Client terminal result and measured scope | Received / acknowledged accepted / rejected / unresolved |
|---|---|---|---|---|
| Actual batch identity, attempt number and receipt/client evidence links | Actual decoded count | Observed server behavior | Completed response, timeout or other observed result; export/caller timing | Evidence-derived counts, preserving unknowns |

This is an evidence layout, not example execution or new JSON fields. Never
combine a timed-out batch with a different completed-503 batch under one
completed-response count. A server response log supplies the server column;
match client evidence before filling the terminal-result column.

For the local evidence report, reconcile per-batch request and response counts
before summing a multi-batch trial. Save per-outcome attempted, received,
acknowledged accepted, rejected and unresolved counts with durable raw-receipt links in
the canonical runtime report's existing `evidence`/`observed_telemetry` fields,
or its Markdown evidence section. A compact shared fault test may cover multiple
outcomes; do not mark the mixed fault scenario `otlp_accepted` because one
healthy or partial-success subtrial was acknowledged. Split the observations or
explain each outcome using an existing visibility state; do not invent a mixed
visibility enum or new JSON keys. The [shared report contract](scripts/observe_report_core.py)
defines `proof_mode`, `visibility` and the existing evidence fields. Receipt alone,
completed failure, a stall and protocol acknowledgement retain distinct meanings.
For subtrials all confined to an owned receiver fixture without Explorer proof,
`not_explorer_visible` can be the accurate shared visibility while per-outcome
acknowledgements remain in evidence. If a shared row cannot support one stronger
visibility claim, keep that claim `not_proven` with the corresponding status and
explain the individual outcomes; do not change bound audit IDs or invent an enum.
Read N from each actual decoded request, not a shared fixture constant. Check
acknowledged accepted/rejected arithmetic against that N before serializing the
report: full success N/0, valid partial (N-R)/R, with 0 <= R <= N.
Never reuse another trial's input count.
Construct the batch/attempt observations before trial totals. During report
readback, join each actual decoded request to its client/receiver observations
and derive totals and visibility from those rows. Different decoded record sets do not establish retry lineage; bind batch
and attempt identities from actual client/request observations. A generic SDK error or another export's
deadline test cannot identify a batch's terminal result: retain an unmatched
result as unknown, with its evidence, rather than assigning server response
intent or inferring acknowledgement. Keep known completed responses distinct
from stalls; a combined "503/timeout" label loses that distinction. A row with
unknown acceptance or no observed acknowledgement cannot claim log
`otlp_accepted`; retain a known completed client error as completed even when
its accepted record count remains unknown.

The [OTLP exporter retry contract](https://opentelemetry.io/docs/specs/otel/protocol/exporter/#retry)
requires transient-error handling with exponential backoff and jitter (MUST).
Assess the existing exporter's transport-specific eligibility and actual policy;
this is not a new application retry loop or numeric tuning prescription.
The standard OTLP exporter timeout covers a whole batch export, including all
attempts and retry waits; it must not restart for each attempt, and an earlier
caller deadline takes precedence. Keep that specification contract separate
from an arbitrary SDK option named timeout. If the installed path only bounds
one request, report its SDK/capability limitation and verify a supported whole
deadline through the existing owner rather than claiming the standard contract
is satisfied or reimplementing the SDK.
For the selected transport, distinguish server throttling (`Retry-After` or
gRPC `RetryInfo`) from client backoff, within the same whole-export deadline.
HTTP `Retry-After` uses integer delay-seconds or an HTTP-date, never a value
such as `100ms`; gRPC retry durations use their own protocol representation.
If the server wait exceeds the remaining export/caller budget, end within the
earlier deadline instead of retrying early or requiring another attempt.
Derive throttling input, expected wait and request count from the selected
transport and actual remaining budget; retain measured waits and outcomes.
OTLP/HTTP responses 429, 502, 503 and 504 SHOULD be retried; other 4xx/5xx
MUST NOT be retried. Preserve the operator's selected retry policy.
Check installed exporter behavior with a controlled receiver before claiming
conformance; do not add an application retry loop around an SDK exporter.
First identify the app-owned/changed bound, supplied operator policy,
source-backed size/decompression risk, or precise related capability/conformance
claim that selects a transport-bound obligation. Ordinary delegated HTTP export,
endpoint/timeout setup, or a status/body-handling limitation alone does not select
every sibling request/response-size or decompression duty. For selected duties,
record only the necessary byte-bound clauses and owners separately from Body/
attribute limits. Retain applicable [OTLP clauses](https://opentelemetry.io/docs/specs/otlp/);
unchanged delegated defaults can use compact versioned ownership evidence:

| Protocol surface / owner | Upstream clauses to bind when selected or claimed | Recommended default |
|---|---|---|
| Receiver request parsing | MUST bound, including after decompression; exceeded bound requires HTTP 413 | 64 MiB |
| Exporter request body | SHOULD bound, including before compression; above an active bound MUST NOT send and SHOULD record the discard | 64 MiB |
| Exporter response parsing | MUST bound, including after decompression; exceeded bound is non-retryable and client SHOULD record the discard | 4 MiB |
| Receiver response body | MUST bound, including before compression; for an oversized partial response SHOULD reduce size without changing semantics when possible and practical; MAY trim optional diagnostic fields; if it still cannot fit MUST return HTTP 500, with acceptance unspecified | 4 MiB |
| All four limit surfaces | Implementations SHOULD allow these limits to be configured | Recommended numbers are not mandatory application settings |

For those selected obligations or precise conformance claims, carry the
applicable clause groups with capability, owner, disposition and exact binding;
they can share one transport row when each selected clause remains addressable.
Other unchanged SDK/default duties need no per-service sibling-clause ledger.
The SDK's OTLP exporter configuration
documentation describes available settings; it is not a substitute source for
the OTLP protocol's decompression, oversize, response-reduction and configurability
clauses. An excerpt containing only configuration settings cannot bind those
protocol requirements. Mark an unresolved clause unverified explicitly rather
than replacing all missing dispositions with "newer transport clauses".
For selected gRPC bound obligations or conformance claims, assess corresponding
message limits and non-retryable size-limit `RESOURCE_EXHAUSTED` outcomes rather than
copying HTTP status codes. A common client response-receive default of 4 MiB is
acceptable; the recommended request default is 64 MiB. Acceptance after an
unrepresentable partial response fails remains unspecified for gRPC too.

These are exporter/receiver duties. Resolve the selected transport and retain
accurate ownership, installed defaults/capability or scoped unverified effects.
Missing public configuration alone does not prove a missing built-in bound.
An external receiver's complete conformance is not an ordinary application
acceptance prerequisite. Require below/at/above-bound and decompression/failure
checks when the component is owned/selected for conformance, a bound is changed,
or a concrete guarantee is claimed. A synthetic receiver establishes the tested
client interaction, not the real receiver's implementation. No unverified external
capability closes a critical application delivery/safety invariant. Do not add
an application parser, retry loop or forced dependency upgrade to imitate an
SDK-owned limit. Keep oversized-failure acceptance uncertainty explicit. If
several destinations are configured, assess each selected queue/ack/retry
boundary independently; one success does not prove another.

A maximum attempt count is a ceiling, not a requirement to reach that many
attempts during every failure. An earlier deadline can end retries first.
Receiver request counts prove received requests, not every client connection
or interrupted attempt. Resolve whether the SDK option covers one attempt or
the whole export, including retry waits and jitter; do not infer its scope
from its name or add a separate full timeout for each retry without evidence.

Keep configured/effective timeout values separate from measured export duration.
A shutdown wall time proves the lifecycle boundary, not each batch's client
execution budget. Measure a supported export/caller boundary, retain its timing
source and scope, or keep that runtime-duration claim unproven; source inspection
and focused timing probes retain their own evidence level.

Record the observed per-attempt timeout, retry/backoff duration and enclosing
caller/processor deadline with units and source evidence, including an absent
deadline. Then state the proposed or retained mechanism and composed budget
separately. A generic instruction to "bound retries" or a new timeout number
does not explain the current failure or establish which wait it bounds.

### Resolve deadline mechanisms

Classify a retry elapsed setting from the actual loop: a check after failure or
before scheduling another attempt can be an eligibility threshold rather than a
cancellation deadline. Follow the full selected wait, including jitter and server
throttling, and the next attempt. A check of one wait component alone does not
cap the other components or an in-flight request. State the condition under which
the configured elapsed value can be exceeded; only a verified enclosing deadline
supplies the corresponding whole-operation bound. Retain that SDK behavior and
its owner without adding application retry logic or inventing a stricter guarantee.

A concrete repair plan names the supported public mechanism selected for the
actual project, with its scope, units and effective configuration. Resolve the
installed/project-compatible SDK first instead of prescribing one constructor,
method, timeout or dependency release for every application. Keep an unresolved
mechanism unverified with its future capability check. Record checked library versions in
the task's evidence artifacts rather than pinning a release recipe in this guide.
Leave time for encoding/draining within the selected whole-operation budget
and verify it against a stalled receiver rather than assuming a timeout knob
proves the bound. Keep exporter attempts, processor waits and caller lifecycle
deadlines distinct; a caller that stops waiting may not cancel delivery.

## LOG-DIAGNOSTICS -- Keep diagnostics outside their own bridge

Trace SDK/exporter diagnostic routing through handlers, appenders, transports
and HTTP-client instrumentation. Avoid returning a log exporter failure to
the same application bridge recursively. Prefer the SDK's suppression and
separate diagnostic mechanism; preserve the ordinary application sink.
Prove bounded diagnostics, no recursive export storm and continued application
work under an exporter fault. Existing safe routing is coverage, not a reason
to add another error handler.
Name the actual routing/suppression mechanism in the repair and handoff, not
only a desired zero-recursion outcome.
Under the [common attribute-limit rules](https://opentelemetry.io/docs/specs/otel/common/#attribute-limits),
an SDK MAY emit a diagnostic for truncation, discard or replacement. Such
diagnostics MUST NOT occur more than once per affected record. Separately, the
[Logs SDK limits](https://opentelemetry.io/docs/specs/otel/logs/sdk/#logrecord-limits)
SHOULD report discarded attributes, with the same MUST ceiling of one message per
LogRecord, not per dropped attribute. Count the installed SDK's actual diagnostic
paths against individual records; passing truncation/count assertions does not
prove this cadence. Classify each message's cause before applying this ceiling:
it counts diagnostics for changes **due to a limit**. Invalid-key validation,
uniqueness enforcement or other independent SDK diagnostics are not automatically
limit diagnostics, even when they also discard data. Configuration validation
warnings about a limit option are also distinct from a diagnostic for record data
actually changed by a limit. Do not classify solely from a message containing
the word "limit" or its location in a normalization function. Follow the branch
to its returned/stored value: a warning followed by unchanged data does not
establish truncation, discard or replacement due to a limit. Aggregate all messages
actually caused by limits for one record; independent once guards do not imply
a shared per-record budget. Preserve the separate applicable diagnostic policies. Preserve an observed upstream limitation as such without
replacing SDK diagnostic internals or claiming an application suppression fixes it.

## LOG-VERIFY-FRESH -- Bind each verdict to its own execution evidence

This is a repository verification rule, not an upstream SDK requirement.
Give each repetition fresh report storage and bind it to the tested fixture or
application revision, dependency versions and command. Count actual successful,
failed, errored and skipped cases; a zero exit status or an old XML `tests`
total is insufficient. Missing reports, skipped cases, unexpected counts,
source changes during a run and missing runtime dependencies cannot pass.
Prepare dependencies using the project's supported manifests and lockfiles.

Persist per-trial results as they finish. On timeout, preserve available output,
mark the trial failed, clean up owned processes and retain the partial matrix;
continue independent trials where safe. Mark interruption separately. Keep
negative-control assertions distinct from safe configurations. Do not upgrade
SDK/in-memory results to application, agent, receiver or cloud proof. For
plan-only tasks, save acceptance requirements and leave execution Not run.

## Audit and instrumentation evidence

Audit each applicable rule as covered, partial, missing, unverified or not
applicable, citing source/config/installed capability or explicitly scoped
fixture evidence. A search miss is not runtime proof. Distinguish missing
source wiring from unavailable execution evidence and SDK-owned defaults.
Promote only concrete app-owned gaps into selectable findings and map their
acceptance scenarios. Instrument only authorized gaps using the existing
bridge and provider; retain supported operator settings and scope exclusions.
During instrumentation, an executable selected control left Not proven is
remaining work: use the smallest supported test or repair and rerun it while
within the authorized scope. Retain an actual blocker or unsupported boundary
when execution cannot be completed. A live snapshot and cleanup are not a
substitute for a selected final-record drain test.

Use the detected language guide for bridge mapping, propagation, log limits,
deadline APIs and diagnostic routing. Test normal operation, explicit opt-out and a fault case;
distinguish focused SDK/bridge proof from full application/receiver proof.

## Acceptance handoff completeness

Use addressable assertions in existing scenario acceptance/evidence fields,
not another report or new schema keys. Define compatible shared record-contract
predicates once: record selector, expected body/severity/scope, occurrence versus
observation time with source precision, and supplied/default Resource values.
Then map each promised operation, including failure/finalization branches, as
`operation/record selector → predicate label + parameters → own context/privacy
assertions → proof boundary`. The referenced predicate must actually assert the
promised fields for that record; a list of test names or another record's pass
is insufficient. Context may be legitimately absent; do not invent a span.
Share only compatible clauses, not proof credit across paths, and do not add
SDK value-shape tests for unpromised native messages. Share an outage scenario
where the owned path and boundary match. Keep proposed/default settings distinct
from installed capability; unexecuted controls retain concrete expected counts
and conditions with Not run/Not proven outcomes, not inherited success.
When protocol response classification is selected or claimed, save each of
these assertions explicitly in its own canonical report, including direct
instrumentation without an audit. Do not assume an earlier audit holds the
plan or let the warning-only retry assertion stand in for the separate
partial-rejection case. Otherwise retain accurate delegated capability and
ownership without selecting a protocol conformance suite merely by using OTLP:

| Future valid response control | Count assertion for each known N-record batch | Retry assertion |
|---|---|---|
| Full success, conforming selected encoding and `partial_success` unset | N acknowledged accepted, 0 rejected; persistence separate | Successful response completes that export; do not count unrelated fault attempts as this control |
| Populated partial success, 0 < R <= N rejected | N-R acknowledged accepted, R rejected | MUST NOT retry that request, including an inferred rejected subset |
| Populated warning-only partial success, R=0 | N acknowledged accepted, 0 rejected | MUST NOT retry that request |

| Rule | Required acceptance detail |
|---|---|
| LOG-SPEC-CLOSURE | Source obligations and precise claims for the selected application scope, with strength, owner, evidence, disposition, necessary finding/scenario mapping and proof boundary. Unchanged delegated defaults may retain compact versioned source/ownership facts. Reconcile every bound scenario assertion and negative control using the appropriate audit proof_level and runtime proof_mode. Combined claims need evidence from the same owned path; unrelated passing probes cannot establish end-to-end coverage. Unmapped selected obligations or missing proof keep the relevant completeness claim partial. |
| LOG-RECORD | Name the detected/proposed bridge and verified version or unverified capability; specify source occurrence value/precision, observation time separately, source level to numeric severity, actual SeverityText/casing independently of the numeric band name, and actual body/category. |
| LOG-CONTEXT | Exact sampled/unsampled/outside IDs and SDK flags; real SDK-created sampled parent/child spans joined to their logs at the claimed boundary, with parentage/resource checks. Explicitly name one joint scenario traversing an owned async handoff and joining that worker/callback log to its received real span; separate known-ID async and synchronous join tests are insufficient. Separate unsampled non-export and outside-span controls, canonical OTLP fields from ordinary attributes, and non-OTLP formatter proof where selected. |
| LOG-ASYNC-HANDOFF | Caller capture before scheduling; exact request pairing, permitted MDC handling where applicable, worker cleanup and bridge placement relative to queues. Link the joint real-span async scenario, supported propagation and expected-loss controls. |
| LOG-EXCEPTION | Allowed exception fields and excluded sensitive fields, with bridge/event convention applicability and optional-field decisions. |
| LOG-LIMITS | Name effective/proposed count/value settings and implemented depth support separately from Body policy. Reconcile the record-normalization and diagnostic implementation for supported shapes, not only public option declarations. Specify below/at/above-limit inputs, units, expected outcomes and supported drop accounting; generic limits plus numbers are insufficient. For an expensive construction path, name the supported native/direct-OTel enablement query, check current policy inside the owned worker, and prove construction/output counts across disabled/enabled/disabled states. Preserve cheap direct emits and original sinks when the OTel path is disabled. |
| LOG-DELIVERY | Save two compact plans where selected. **Stop:** request/recipient/launcher→handler path, permitted outcome, budget/source, observable order and own final-record predicate; distinguish healthy drain, fault and policy-selected repeated/forced outcomes. **Retry:** for a selected bounded-retry/recovery claim, name a source-supported retryable response or connection event, batch/trial identity, existing SDK policy and wait source (backoff/jitter, or a separately supplied server-wait value), remaining export/caller budget, expected measured wait/range and terminal result. Retain applicable no-early-retry conditions under that policy. State whether recovery means the failed batch later succeeds or only newly emitted batches are healthy; the latter cannot prove recovery of the failed batch. Separately identify persistent failure ending by the actual deadline/eligibility rule or a stall. A generic immediate-failure label does not specify a retry stimulus. Server throttling and full protocol certification remain unselected unless separately promised. Resolve these through supported existing settings, not an application retry loop. Bind each plan to its assertions and raw request/response/client outcome. Retain effective queue/batch/schedule/export limits and batch<=queue (or selected simple-processor cost). Apply the response/count table above per decoded batch before trial totals, keeping attempts, received copies, acknowledgements, rejections, drops and unknown persistence separate. Preserve selected compression/size ownership, unresolved acceptance after timeout/oversize, source/runtime boundaries and accurate per-outcome visibility; a completed failure is not pending merely because accepted count is unknown. |
| LOG-DIAGNOSTICS | Name the supported separate routing or suppression mechanism. One exporter-fault scenario asserts bounded diagnostic volume and export attempts, application progress, original sink output, and continued operation of each other configured signal. Explicitly mark absent signals not configured; preserving configuration alone is not operation proof. |
| LOG-VERIFY-FRESH | Unique report storage for each trial; planned manifest/lockfile dependency preparation; binding to source, command and dependency versions; actual success/failure/error/skip counts; preserved timeout console output, failed timeout verdict, owned-process cleanup and incremental structured partial results; explicit evidence scope. |

### Report readback

The `required-controls` inventory also returns `unmatched_attribute_literals` and
case-sensitive substring matches against each finding's bound scenario acceptance
text. Review these omission hints before finalizing. A miss can have a legitimate
semantic alias/conditional explanation, and a hit can occur in a denial or other
non-assertion: neither is a semantic coverage verdict. Resolve each promise to its
actual assertion or missing proof; do not add field names merely to satisfy text
matching. A conditionally supplied Resource field needs its supplied-value
preservation assertion or justified applicability, without inventing metadata.
The helper also returns `unknown_finding_id_literals` with report locations for
unallocated numeric `OTEL-*` tokens and slash shorthand across the entire
canonical report, even when inventorying a selection. It retains the original
literal. These are lexical hints: a historical/external
reference can be intentional, and a known ID can still identify the wrong owner.
Resolve text mappings against the actual final findings and controls; the helper
does not evaluate reference meaning or repair canonical bindings.
Controls from selected source obligations and precise claims remain independently
required; these hints neither enumerate them nor expand scenario paragraphs into
tests. Unselected sibling SDK clauses do not become application controls merely
because the source inventory contains them.

Read this section immediately before generating/finalizing logging results.
The read-only `source-settings` helper can discover `OTEL_*` and `otel.*` name
spellings in selected implementation files/directories, with file hashes and
line locations. For a draft report, it surfaces names with no exact spelling or
unverified separator-normalization hint in that report. Choose sources by the
selected behavior and claims. Include installed or proposed SDK/bridge/bootstrap
sources needed to resolve them as well as application files; scanning only an
uninstrumented application cannot inventory SDK configuration. Do not use the
report itself as the source inventory.

```sh
python3 -I "<directory-containing-loaded-SKILL.md>/../references/scripts/observe_report.py" source-settings --source <implementation-path> --report <saved-report>
```

Repeat `--source` for other selected roots. Retained `source_roots` show the
requested scan scope even when no candidates are found. Use the calling stage's existing
JSON or Markdown report. This is lexical discovery: declarations/comments are
candidates, normalized spellings are not verified aliases, and a report mention
can be a denial rather than an assertion. Resolve actual consumption, separate
readers and effective behavior yourself. Computed names, native public options,
nonmatching namespaces and skipped files need independent inspection. The helper
writes no reports, resolves no dynamic names and evaluates no coverage or runtime.
An equivalent complete source-derived inventory remains valid.

Apply **Source and applicability** to the saved claims and configuration cases:
read their retained slices against the exact subject and terminal consumer, then
check applied values, authority and their own assertions. Include the identity/
disabled-init controls when supported and selected. Keep missing source access,
wiring and proof distinct; lexical discovery neither selects unused defaults nor
establishes runtime behavior. Shared parameterized controls are valid when every
condition and execution boundary is addressable. Reuse the independent-finding
acceptance closure above; helper-only or different-path results cannot close a
normal-launch or same-path conjunction.
For an existing canonical audit, the read-only report helper can enumerate the
promises directly, including every `expected_telemetry[].attributes` member:

```sh
python3 -I "<directory-containing-loaded-SKILL.md>/../references/scripts/observe_report.py" required-controls .observe/otel-audit.json
```

Use `--ids` only to restrict that inventory to an already chosen scope; it does
not approve a selection or add dependencies. Its candidate scenario IDs do not
assert that those scenarios test each field. Match the inventory's owning item,
field and operation to real acceptance assertions yourself. The command writes
no report and evaluates neither coverage nor runtime. An equivalent complete
reconciliation is valid. With no audit, derive the same set from the direct
instrumentation scope/report; never manufacture an audit to use this command.
Build the required set independently from the final findings' promised
operations/fields and applicable source/policy conditions. Compare it to the
assertions actually saved in the scenarios, using owning operation, field,
condition and proof scope as the match key. Start from the promises and clauses,
not just existing scenarios; a scenario-to-owner list cannot expose an omitted
promise. A parameterized table may carry the matches. Retain each unmatched
member as unresolved with its concrete missing control/resolution, and reconcile
all referenced finding/scenario IDs against the final allocated IDs.
Apply LOG-SPEC-CLOSURE's per-control verdict and immutable source-binding rules:
initialize unmatched controls Not proven, then join each to its named assertion and actual
output. Preserve directly proven item scope beside incomplete
related scenarios. Reconcile current capability and executed receipts separately;
never inherit runtime success, weaken a selected clause or label executed proof
future-only. Source and applicability above defines delegated facts and the
separate skill-maintenance inventory; no additional per-service ledger is needed.

Before finalizing, compare the saved scenarios against these obligations and
the selected source/policy. An omitted obligation leaves that handoff partial;
unexecuted acceptance never becomes a passing runtime result.
Preserve the concrete obligations when shortening a report. Share scenarios by
ID and let the authoritative structured report own their detail, with a compact
Markdown summary where that artifact is permitted; do not duplicate the full
plan in both formats or delete settings, expected outcomes, dependency setup,
evidence bindings or fault assertions to meet a prose budget. Read back the
saved handoff and reconcile every applicable acceptance row before claiming
completeness. For unknown/optional SDK capabilities, give a concrete future
source/API-resolution step and conditional test, preserving the unverified
state; do not force an unselected development feature into application code.
Readback must check the conjunction: the owned async log itself joins its
received real SDK span in one scenario. Finding "async" and "real span" in
different scenarios is not that proof.
Before publishing the saved reports, resolve every local execution-evidence
reference and read the actual artifact. Planned future paths are not executed
evidence. Associate `trace_ids` with that scenario's own operation/receipt, or
leave the field empty when no such trace is proven; never copy the first IDs
from an unrelated runtime trial into every row. Refresh current capability and
proof dispositions after installation/probes while leaving the audit immutable.
A copied "not installed/executed" baseline row does not describe a newly tested
exporter, and passing value truncation does not prove discard-diagnostic cadence.
Keep trial storage distinct on the actual filesystem. Do not rely only on
capitalization to distinguish cases on a case-insensitive host. Use a distinct stable case ID or separate run directory,
retain the original input in its metadata, and check that each referenced result
belongs to the claimed trial. Two paths to the same overwritten file do not
prove two input variants. This is local evidence integrity, not an OTel naming rule.
Finally compare status, proof mode, visibility, direct assertions and linked
controls for each scenario/item; schema validity alone does not reconcile them.
Plan-only restrictions prohibit executing setup, not specifying it: retain the
future dependency-preparation and unique-storage steps explicitly in the saved
handoff. Do not replace a named setting/public option or bridge with outcome
assertions alone.
