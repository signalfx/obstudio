---
name: observe
description: >-
  Full observability workflow -- audit, instrument, verify, and
  provision. Chains the four sub-skills in sequence. Use when the user
  types /observe or asks for end-to-end observability on a service.
---

# Observe -- Composite Orchestrator

## Overview

Run the complete observability workflow by invoking `/audit`,
`/instrument`, `/verify`, and `/provision` in sequence. Detects which
sub-skills need to run based on the current state of
`.observe/inventory.md` and skips completed phases.

## When to Use

- User types `/observe` or asks for "full observability"
- User says "instrument this service" without a prior audit
- Starting from scratch on a new service

**When NOT to use:** If the user wants a specific phase only, use the
individual skill directly (`/audit`, `/instrument`, `/verify`, or
`/provision`).

## Process

### Step 1 -- Detect State

Check the current state of `.observe/inventory.md`:

1. **Missing** -- no `.observe/` directory exists.
   Run: audit -> instrument -> verify -> provision.
2. **Exists, has blank Status rows** -- audit done, gaps remain.
   Run: instrument -> verify -> provision.
3. **All Status=OK, has blank Verified rows** -- instrumented but not
   validated.
   Run: verify -> provision.
4. **All Verified=OK, no `.tf` files** -- verified but not provisioned.
   Run: provision.

### Step 2 -- Execute Skills

For each skill in the determined sequence:

1. **Invoke the skill** by following its SKILL.md process.
2. **Present findings** to the user after the skill completes.
3. **Before `/instrument`**: if coming from `/audit`, prompt:
   > "The audit found N gaps. Ready to implement instrumentation?"
4. **Before `/verify`**: prompt:
   > "Instrumentation complete. Want me to validate telemetry against
   > the Observer?"
5. **Before `/provision`**: prompt:
   > "Telemetry verified. Want me to generate Terraform dashboards,
   > detectors, and alert rules?"

Only proceed to the next skill if the user confirms. If the user
declines at any point, stop and summarize what was completed.

### Step 3 -- Final Summary

After all skills have run (or the user stopped early), present:

- What was audited (components, fault domains, KPI count)
- What was instrumented (KPIs implemented, SDK init location)
- What was verified (coverage percentage)
- What was provisioned (dashboard/detector/alert counts)
- Location of all artifacts in `.observe/`
