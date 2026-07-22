# Service follow-ups

- Publish OpenAPI definitions for every task route and add contract linting in CI.
- Replace the placeholder service-catalog runbook and ownership links.
- Decide the maximum task-list page size and the rejection response when a
  request exceeds that limit.
- Choose retry, timeout, cache, and fallback behavior for failed dependency
  calls.
- Decide liveness/readiness traffic-routing and deployment rollout policy.
- Add a behavior-only test for the page-limit rejection response.
