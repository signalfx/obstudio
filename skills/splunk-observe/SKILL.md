---
name: splunk-observe
description: >-
  Full observability workflow -- audit, instrument, and verify. Chains
  the three sub-skills in sequence. Use when the user types
  /splunk-observe, asks for "end-to-end observability", "make this
  service observable", "add full monitoring", or "instrument and verify
  this service". Do NOT use if only one phase is needed -- use the
  individual skill (/splunk-audit, /splunk-instrument, or
  /splunk-verify) instead.
metadata:
  author: splunk-inc
  version: 0.0.1
  category: observability
---

# Observe -- Composite Orchestrator

## Overview

Run the complete observability workflow by invoking `/splunk-audit`,
`/splunk-instrument`, and `/splunk-verify` in sequence. Detects which
sub-skills need to run based on the current state of
`.observe/inventory.md` and skips completed phases.

## When to Use

- User types `/splunk-observe` or asks for "full observability"
- User says "instrument this service" without a prior audit
- Starting from scratch on a new service

**When NOT to use:** If the user wants a specific phase only, use the
individual skill directly (`/splunk-audit`, `/splunk-instrument`, or
`/splunk-verify`).

## Process

### Step 1 -- Detect State

Check the current state of `.observe/inventory.md` by inspecting the
Spans, Metrics, and Logs tables:

1. **Missing** -- no `.observe/` directory exists.
   Run: audit -> instrument -> verify.
2. **Exists, has blank Status rows in any signal table** -- audit done,
   gaps remain.
   Run: instrument -> verify.
3. **All Status=OK across all signal tables, has blank Verified rows**
   -- instrumented but not validated.
   Run: verify.

### Step 2 -- Execute Skills

For each skill in the determined sequence:

1. **Invoke the skill** by following its SKILL.md process.
2. **Present findings** to the user after the skill completes.
3. **Before `/splunk-instrument`**: if coming from `/splunk-audit`, prompt:
   > "The audit found N gaps. Ready to implement instrumentation?"
4. **Before `/splunk-verify`**: prompt:
   > "Instrumentation complete. Want me to validate telemetry against
   > the Observer?"

Only proceed to the next skill if the user confirms. If the user
declines at any point, stop and summarize what was completed.

### Step 3 -- Final Summary

After all skills have run (or the user stopped early), present:

- What was audited (components, fault domains, SLI count)
- What was instrumented (KPIs implemented, SDK init location)
- What was verified (coverage percentage)
- Location of all artifacts in `.observe/`

## Examples

### Example 1: Full pipeline from scratch

**User says:** "Make this Flask service observable"

**Actions:**
1. No `.observe/` directory -- run full pipeline
2. `/splunk-audit`: detect Python+Flask+SQLAlchemy, identify 8 SLIs, generate signal tables (3 Spans, 8 Metrics, 1 Log)
3. Prompt user: "Found 12 signal gaps. Instrument?" -- user confirms
4. `/splunk-instrument`: install OTel libraries, create `otel_setup.py`, set all Status=OK
5. Prompt user: "Verify telemetry?" -- user confirms
6. `/splunk-verify`: start app, exercise APIs, confirm all signals flowing, set Verified=OK

**Result:** Service goes from zero to fully observable in one session.

### Example 2: Resume from partial state

**User says:** "Continue instrumenting this service"

**Actions:**
1. `.observe/inventory.md` exists, 4 blank Status rows across Metrics and Logs tables -- skip audit
2. `/splunk-instrument`: implement 4 remaining signal gaps
3. Prompt user for verify as usual

**Result:** Pipeline resumes from where it left off.

## Red Flags

- Skipping the audit phase when `.observe/inventory.md` does not exist
- Running all three phases without prompting the user between each
- State detection incorrectly identifies completed phases
- Final summary omits a phase that was executed
- User declines a phase but the orchestrator continues anyway

## Verification

- [ ] Correct phase sequence determined from inventory state
- [ ] User prompted before each phase transition
- [ ] Each sub-skill's SKILL.md process followed completely
- [ ] Final summary includes all phases that ran
- [ ] Orchestrator stops when user declines a phase
