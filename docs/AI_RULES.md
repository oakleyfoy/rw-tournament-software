# AI_RULES

## Purpose
These rules are mandatory engineering constraints for all AI-assisted changes in this codebase.  
When rules conflict, prefer safety, determinism, and auditability.

---

## 1) Determinism and Reproducibility

1. All scheduling/draw algorithms must be deterministic for identical inputs.
2. Any sorting over DB/query results must use explicit stable keys.
3. Do not rely on implicit DB order.
4. Randomness is prohibited in production scheduling paths unless seeded and persisted.
5. Changes that alter ordering behavior must be documented and test-covered.

---

## 2) Idempotency and Re-entrancy

1. Endpoints and jobs that can be retried must be idempotent.
2. Rebuild/reschedule/schedule operations must not duplicate assignments or generate duplicate rows on repeat invocation.
3. Any “send” or “auto-trigger” logic must include dedupe keys to prevent repeated notifications.
4. Retry-safe operations must not require manual cleanup after partial failure.

---

## 3) No Silent Side Effects

1. No hidden writes in read endpoints.
2. Any mutation endpoint must clearly indicate what is changed.
3. No background mutation should occur without explicit trigger and logging.
4. If a fallback path modifies behavior, it must be explicit in logs and response.

---

## 4) Transaction and Rollback Safety

1. Multi-step critical flows (schedule policy runs, bulk assignment, rebuild apply) must be transactional where feasible.
2. On invariant failure, rollback must be complete and observable.
3. Partial commits are forbidden in hard-stop validation flows.
4. Error paths must leave data in a known-safe state.

---

## 5) Invariant Governance

1. Hard-stop invariants must be explicit and centralized.
2. Advisory checks must never silently become hard-stop checks.
3. Any change to invariant severity (hard-stop vs advisory) requires:
   - code comment
   - changelog note
   - test update
4. Invariant report output must remain structured and machine-readable.

---

## 6) API Contract Discipline

1. Do not remove or rename API fields without compatibility strategy.
2. New fields should be additive and optional when possible.
3. Keep response/error shapes stable; avoid ad-hoc error formats.
4. TypeScript contracts in `frontend/src/api/client.ts` must match backend behavior exactly.
5. Avoid introducing `any` where strong typing is available.

---

## 7) Runtime State Integrity

1. Match state transitions must be valid and explicit.
2. Upstream dependency resolution must never schedule impossible states.
3. Finalized results must not be implicitly overwritten by unrelated operations.
4. Lock semantics (match lock, slot lock, court state) must be honored in every scheduling path.

---

## 8) Scheduling and Assignment Rules

1. Never schedule unresolved dependency matches ahead of required feeder matches.
2. Slot generation/regeneration must be explicit about wipe vs non-wipe behavior.
3. Capacity calculations must be transparent (slots vs remaining matches).
4. “Force” modes must require explicit operator intent and be clearly labeled.
5. Weather/rebuild exceptions must be scoped only to intended paths.

---

## 9) SMS and Communication Compliance

1. No SMS send without valid E.164 normalization and validation.
2. Respect consent rules:
   - send only to opted-in recipients
   - honor opt-out immediately
3. Include STOP/HELP handling if required by region/carrier policies.
4. All sends must be logged (success/failure) with:
   - recipient
   - message type
   - trigger source
   - provider status/SID
5. Auto-SMS triggers must be deduped and retry-safe.
6. Manual blast operations must support preview/dry-run.
7. Never silently downgrade send failures; surface actionable errors.

---

## 10) Security and Secrets

1. Never hardcode credentials, API keys, or tokens.
2. Use environment variables for Twilio and external integrations.
3. Do not log secrets or full sensitive payloads.
4. Minimize PII in logs; log only what is necessary for operations/audit.

---

## 11) Observability and Auditability

1. Important actions must produce structured logs.
2. Policy runs and critical mutation flows should include input/output fingerprints where applicable.
3. User-visible failures must map to diagnosable backend logs.
4. Avoid noisy logs that obscure operational issues.

---

## 12) Testing Requirements

1. Every non-trivial behavior change needs tests.
2. Add regression tests for any bug fix that affected production behavior.
3. Invariant, scheduling, and SMS dedupe/compliance logic must be test-covered.
4. Keep tests deterministic and environment-agnostic.

---

## 13) Frontend Safety Rules

1. Build must stay TypeScript-clean (`tsc` passes).
2. Do not leave unused variables/imports in strict mode paths.
3. UI actions with destructive outcomes require confirmation.
4. Surface backend validation/invariant errors clearly to operators.

---

## 14) Deployment and Environment Rules

1. Keep runtime/tooling versions pinned for production stability.
2. Persistent database paths and disk assumptions must be explicit.
3. Startup must fail fast on critical misconfiguration and degrade safely on optional integrations.
4. Build/deploy scripts must remain reproducible and non-interactive.

---

## 15) Change Management

1. Prefer minimal, targeted diffs over broad refactors.
2. Do not alter unrelated behavior while fixing a focused issue.
3. Document operator-impacting behavior changes in plain language.
4. Preserve backward compatibility unless an explicit migration is provided.

---

## Non-Negotiable Summary

- Deterministic behavior
- Idempotent operations
- Explicit side effects
- Transactional safety
- Clear hard-stop vs advisory invariants
- Strict API/type contracts
- SMS compliance + audit logging
- No secrets in code/logs
- Test-backed changes only
