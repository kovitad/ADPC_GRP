# ADR-0042: Officer reviews are time-bound human evidence, kept apart from the engine

## Status

Accepted on 3 October 2026 for a local demo (Gate A). This is slice 5b of the Bangkok flood pilot
plan, and the pilot's first write path. The Product Owner earlier decided that Hub operators can
verify.

## Context

- **Spec §11 (CCTV) and Epic J** want operators to record what they saw: confirms, contradicts or
  inconclusive. That human verification is stored separately from model inference.
- **The integration tweak** reserves `access_disrupted_confirmed` for an officer, and requires
  human approval before any high-consequence claim.
- **Officer observations age like any other evidence.** A check at 10:00 must not keep a flooded
  street "verified" at 22:00. Floodboard re-cuts segments, so an incident can change underneath a
  review.

## Decision

1. **One table, `flood_review`** (migration `20261003_0025`). Each row holds:
   - pilot, Hub, officer;
   - target kind (`incident` or `facility`) and target;
   - action and optional camera;
   - a note of at most 500 characters;
   - the incident's road keys at review time;
   - the creation time, `expires_at` (3 hours later) and `withdrawn_at`.
2. **Incident actions:** `flooding_seen`, `dry_seen` and `cannot_tell`. A review applies only
   while it is unexpired, and only while the incident still contains a road the officer reviewed.
   A re-cut, merged or split incident therefore never inherits a review silently.
3. **The engine's confidence is never changed.** The incident gains a separate `verification`
   (`unverified`, `officer_saw_flooding`, `officer_saw_dry`, `officer_could_not_tell`) with its
   validity window. The check-first order changes as follows:
   - `officer_saw_dry` goes to the top, next to conflict;
   - incidents not yet seen by an officer come before seen ones.

   Each review is also an `officer_review` incident event.
4. **Facility actions:** `access_disrupted` sets `access_disrupted_confirmed` until it expires,
   and `withdraw` ends it. There is no action meaning "accessible", and the API refuses any other
   action.
5. **A camera named in a review must be real.** It must be registered, not a placeholder, and
   have a viewer. Placeholder cameras are refused.
6. **Who may write.**
   - Members, in any role, of a Hub listed for the pilot. The review is recorded against that
     Hub.
   - **A Platform Admin with no pilot-Hub membership can read but not write**, because there is
     no Hub to act for.
   - Another Hub's members are refused.
7. **Request protection:**
   - The existing session check enforces the CSRF header and per-person rate limit on every
     POST.
   - Request bodies are typed, with `Literal` actions and length limits.
   - Every review writes an `AuditEvent` (`flood_pilot.incident_review` or
     `flood_pilot.facility_access`) with the action, camera and note length. The note itself
     stays out of the audit log.
   - Notes and reviewer names are shown as text only.
8. **Routes,** both `protected`:
   - `POST /api/v1/pilot/flood/{pilot_id}/incidents/{incident_id}/reviews`;
   - `POST /api/v1/pilot/flood/{pilot_id}/facilities/access`, with the asset ID in the body
     because OSM IDs contain `/`.

## Consequences

- **The incident card now shows:**
  - the current officer state and its validity window;
  - three buttons with an optional note, and a camera choice once real cameras exist;
  - the officer-check history, with a note when an entry no longer counts.
- **The facility card** has "Access is cut (I saw it)" and "Withdraw confirmation".
- **Reviewer display names are visible to other operators** in the pilot, for accountability.
- **Tests:**
  - the review is recorded, shown and audited;
  - no CSRF header means 403 and nothing stored;
  - other Hubs and a non-member Platform Admin are refused;
  - bad actions, long notes and placeholder cameras are refused;
  - facility confirm, withdraw and no "accessible";
  - 3-hour expiry, no inheritance after a road change, and dry-first ordering.
- **Not verified:** a signed-in POST on the real stack. The renders used a stubbed sign-in.
