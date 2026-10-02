# ADR-0032: Hub members send data to Global Risk from GRP, and GRP follows it to the end

## Status

Accepted on 28 September 2026 by the Product Owner, who chose **planners too** (not only Hub
Admins) and **include weights**. Carries out the product half of
`docs/shared-sig-contribution-e2e-plan.md`, with those two choices replacing its "Admin-only".

## Context

Global Risk accepts data through `contribute_submit(kind, manifest)`. The runbook "Adding your
flood-preparedness sources" (saved 23 September 2026) and the Bang Bua Thong test
(24 September 2026, contribution `c66ade79bc2605ac`) established:

- Five kinds: `vector`, `raster`, `table`, `document`, `weights`. Global Risk downloads the file
  itself, so a link must return the file: a Google Drive share page or folder returns HTML. The
  direct form is `https://drive.google.com/uc?export=download&id=<FILE_ID>`, and Drive puts a
  virus-scan page in front of files over about 100 MB.
- The deployment **auto-approves**: a clean contribution is live for every Global Risk user at
  once, cited as "auto-approved, no human reviewed this layer". Auto-approve is for a session only;
  afterwards a contribution is **staged** until a reviewer approves it.
- A `weights` contribution changes flood risk levels for every Global Risk user.
- `contribute_status` lists only the caller's own contributions.
- The first `assemble_pack` in the test timed out at 180 s (D-07), so a submit may also go
  unanswered after it arrived.

The required fields per kind were read from Global Risk's gate on 28 September 2026 by sending an
empty manifest for `vector`, `raster`, `table` and `document`. All four were declined, and a
declined submission leaves no record. `weights` fields come from the runbook: `hazard`,
`weights` summing to 1.0, and `rationale`.

## Decision

1. **Who.** Any planning role (NDMO Planner, Hub Expert, Planner, Hub Admin) may send for a Hub
   it belongs to. Every member of the Hub sees the Hub's contributions. Only the sender can
   refresh one, because `contribute_status` answers only for the caller. Like the planning chat,
   the feature exists only where the SERVIR sign-in exists (ADR-0004); elsewhere it is not found.
2. **Check, then confirm.** `POST /api/v1/contributions` with `preview: true` checks the manifest
   against `core/contribution_rules.py` and returns the exact manifest, marking every problem on
   its field. The person then sees that manifest and a warning: it becomes public for all Global
   Risk users at once and cannot be withdrawn after approval. For weights, the warning says it
   changes risk levels for every Global Risk user. A tick box confirms it; only then does
   `preview: false` send.
3. **Links.** GRP converts a Drive file share link to the direct-download form and refuses a
   folder. Only `https` links are sent.
4. **A durable record.** GRP writes a `sig_contribution` row (migration `20260928_0021`) in state
   `submitting` before the call leaves. It keeps the exact manifest sent, the Global Risk
   contribution ID, the gate's problems, a safe subset of the reply (status, decision note,
   reviewer label, how to test, what Global Risk observed; never its server paths), the file
   SHA-256 and the point count. Every submission and result is in the audit log.
5. **Point files are read first.** Before sending a `vector`, a background task downloads the file
   from Google Drive or GitHub only (at most 50 MB, redirects only to those hosts). It requires a
   GeoJSON FeatureCollection of lon/lat points and **refuses any contact field** (phone, fax,
   email, contact, LINE ID, and their Thai names), so volunteer contact details never leave GRP.
6. **Never a blind retry.** If the submit is unanswered, the row becomes `checking` and GRP looks
   in `contribute_status` for the same kind and name made in the last two minutes. It records a
   match. With no match it says "It is safe to submit it again"; if it could not even look, it
   asks the person to check first.
7. **Telling the person.** The submission runs in the background. The top-bar job tracker shows it
   and raises a notice on any page when it lands or fails. A declined contribution maps Global
   Risk's `missing required field 'x'` lines onto the form and quotes the rest verbatim, and
   "Fix and send again" reloads the form. A staged one offers "Check on Global Risk".
8. **Using it.** A landed point layer or population grid is counted by `assemble_pack` in
   Planning answers. "Try it in Planning" puts a suggested question in the Planning box without
   sending it.
9. **Amended 29 September 2026: a name is sent once.** Global Risk's main runbook (section 14)
   says "Contributions never overwrite existing entries", and `contribute_submit` has no update.
   So GRP refuses, on preview and again on send, a `layer` (vector and raster share one
   namespace) or `dataset` name that is taken:
   - any Hub's GRP row in `submitting`, `checking`, `staged` or `approved`, or `failed` with
     `SUBMIT_UNCONFIRMED`. Names are global on Global Risk, so every Hub counts. Another Hub's
     row is reported only as "sent from GRP by another Hub", without its details;
   - a layer counted in the newest stored Planning evidence for any place in the last 30 days.
     This is how GRP learns of a layer sent from Claude Desktop.

   The page shows a dialog that says Global Risk cannot update a contribution, and how to replace
   one: removal by the Global Risk team, by name and ID, then one submit under the same name. It
   never suggests a new name. Weights are not guarded, because submitting weights again for the
   same hazard is Global Risk's documented way to adjust them. Documents are not guarded either.
   The sender can now "Check on Global Risk" for an approved row too, so a reviewer's withdrawal
   frees the name. The shared names live in `api/global_risk_layers.py`.

   Limitation: a layer removed with the Global Risk team's server command (`remove-raster`,
   `remove-feed`) may still read `approved` in `contribute_status`; `action="audit"` exists to
   catch "approved but not served". The GRP row then never turns withdrawn and the name stays
   refused. So the dialog asks for a reviewer's withdrawal with `contribute_review`, which
   changes the record.
10. **Amended 1 October 2026: everything my sign-in sent, from any app.**
    - **New section.** The page's "On Global Risk now" section lists every contribution of the
      signed-in person's SERVIR account. It calls `contribute_status` with no arguments, through
      `GET /api/v1/contributions/on-global-risk`. Contributions sent from Claude Desktop or
      another agent now show beside those sent from this page.
    - **What Global Risk records.** Its record holds whose sign-in sent a contribution
      (`contributor_label`), not which app sent it. So the "Sent from" column says "This page
      (GRP)" only when the contribution ID matches a GRP row of this same person. Every other row
      says "Another app or agent".
    - **What each row shows:**
      - the layer, with a TEST tag for `_test_` names or TEST titles;
      - the status;
      - "Used in answers", meaning Global Risk landed the file;
      - the point count;
      - the review, with auto-approval named;
      - the date;
      - the contribution ID.
    - **What is never returned:** Global Risk's server paths (`staged_file`, `local_path`,
      `landing.file`) and the account label.
    - **Limits.** The call is read-only and rate limited like an evidence read. A colleague's
      contributions are not listed: `contribute_status` answers only for the caller.

## Consequences

- A planner can publish a layer, or change flood risk weights, that every Global Risk user sees at
  once. This is the owner's decision; the confirmation step and the audit log are the controls.
- The record survives restarts, but the running task does not: a restart mid-submit leaves the row
  `submitting`, and "Check on Global Risk" reconciles it.
- Raster, table and document files are not read by GRP; Global Risk's own checks apply.
- **Before real uploads:** decide whether to withdraw the test layer `c66ade79bc2605ac`
  (`evacuation_centres_th_test`). It is live, unreviewed, and holds the mislocated record found in
  the Bang Bua Thong test. A real evacuation-centre layer beside it would double-count.

## Verification

- `tests/fast/test_contributions.py`: Drive link conversion and folder refusal; required fields
  per kind; the population-grid legend exception; weights summing to 1 and never weighting a count;
  preview sends nothing; an approved submit is recorded with ID, SHA-256 and count; a decline maps
  fields; contact fields stop a point file before Global Risk; an unanswered submit is found rather
  than resent, or declared safe to resend; only the sender refreshes; another Hub cannot see it; a
  SERVIR sign-in is required.
- `tests/fast/test_contributions.py` also covers the repeated-name guard: this Hub's name, with
  its ID and the way to replace it, and nothing sent; another Hub's without details; declined,
  rejected and withdrawn names free; an unconfirmed submit holding its name; the raster and point
  layer namespace shared; weights re-sendable; a name counted in evidence taken until newer
  evidence for that place drops it; an approved row checked as withdrawn freeing its name.
- `tests/fast/test_contributions.py` also covers the "On Global Risk now" list:
  - every record is listed and marked by where it was sent;
  - server paths and the account label are stripped;
  - a colleague's GRP row is not marked as mine;
  - it needs a SERVIR sign-in;
  - it says when Global Risk is down.
- `tests/contract/test_permission_matrix.py` lists all five routes.
- No real contribution was sent while building this. The first is the owner's.
