# ADR-0029: The planning assistant keeps its evidence and conversation in the database

## Status

Accepted and implemented on 25 September 2026 (migration `20260925_0019`). Verified by fast tests,
the permission matrix, and a direct check of the new queries against the desktop PostgreSQL.

**Amends ADR-0004**, whose "Records" line said "Chat text is not stored". It is now stored, per
person and Hub, as set out below. ADR-0002 and ADR-0017 are unchanged: no SIG access or refresh
token is persisted. Only the evidence SIG returned is stored, never the credential that fetched it.

## Context

The Product Owner asked for the assistant to remember context, so that asking the same question
again does not return to SIG. Before this change it remembered much less than that:

| Memory | Where it lived | How long |
| --- | --- | --- |
| Identical question, same place | API process memory, per login session | 10 minutes |
| Assembled SIG pack (`assemble_pack`, 149 s of a 200 s answer) | API process memory, per login session | 5 minutes |
| Conversation and history | The browser tab's `sessionStorage` | Until the tab closed or the person signed out |

A restart of the API, a new sign-in or a closed tab each forgot everything. The 5-minute pack life
was also doing a second job: it kept a publishable receipt from resting on stale evidence. That
second job forced the first to be short.

## Decision

1. **Reading and publishing are separated.** A SIG pack answers questions for 60 minutes
   (`PACK_REUSE_SECONDS`). A public receipt is offered only when the pack was gathered within the
   last 5 minutes (`PACK_PUBLISH_MAX_AGE_SECONDS`). An older pack still produces a brief, but
   carries no publish token, and the response sets `publish_needs_fresh_evidence`, so the evidence
   panel offers "Gather fresh evidence to publish" instead. The publish token lives 15 minutes,
   longer than the window, so it carries the evidence's `assembled_at` and the publish step checks
   the age again (`PUBLISH_NEEDS_FRESH_EVIDENCE`). The browser applies the same rule to a card left
   open, but the server has the final say.
2. **Packs are stored in `planning_sig_pack`, one row per person, Hub and place.** They survive an
   API restart, a new sign-in and a closed tab. A reused pack needs no SIG token and opens no MCP
   connection, so a planner can keep asking about an area after a restart while SERVIR is
   disconnected. `refresh` always gathers anew.
3. **The conversation is stored in `planning_chat_message`, per person and Hub.** It keeps the
   newest 60 messages for up to 30 days. A tab with no `sessionStorage` state draws the
   conversation from `GET /api/v1/planning/conversation`. The restored `history` follows the
   same rules as the browser's (no empty turns, 1,200 characters, the last 8), so it always
   validates as the next request. A re-sent question (area confirmation, retry) carries
   `echo: false` and is not stored twice.
4. **What is never stored:** the publish token, the usage figures and the cached-answer flags.
   They belong to one login and one moment. Evidence cards larger than 250,000 characters are
   kept as text only.
5. **The identical-question cache stays in process memory and bound to the session**, because
   its answers carry a publish token bound to that login. It now lives as long as the evidence
   (60 minutes) and removes the publish token from an answer whose evidence has aged past the
   publish window.
6. **Starting over is one action.** `DELETE /api/v1/planning/conversation` forgets the person's
   conversation and reusable evidence in that Hub, and clears their session's answer cache. The
   chat header offers it as "New conversation", with a second click to confirm.
7. **Every reuse is visible.** A reused or restored evidence card states when the evidence was
   gathered and that no new SIG call was made, beside the "pulled live" count that would otherwise
   read as live now, and offers "Gather again from SIG".
8. **A failed memory write never costs the answer.** Pack and message writes run in a savepoint.
   Two lookups racing to store the same place lose one pack, not the planner's answer.

## Consequences

- The earlier rule "a new login evicts prior entries for that person" now holds only for the
  identical-question cache. Evidence and conversation deliberately outlive a login, because the
  owner asked for the assistant to remember. Access remains per person and per Hub:
  `planner_membership` guards both endpoints, a colleague asking about the same district gathers
  their own pack under their own SIG identity, and a Platform Admin with no planning membership
  has no conversation to read (permission matrix `read_conversation`, `clear_conversation`).
- Chat text is now stored server-side for up to 30 days. It is covered by the same database
  protections as audit data, and a person can delete it themselves. If a Hub needs a different
  retention period, `MESSAGE_MAX_AGE` is the one place to change it.
- A brief written from reused evidence can be up to an hour behind SIG. The card says so, and
  publishing requires fresh evidence, so nothing public rests on it.
- A new answer about a place still costs about 40 s of model time, even when no SIG call is made.
  Only an identical question in the same sign-in is instant.
- Known gap: a restored "Confirm the district" message comes back as plain text, without its
  confirm button, because the server does not know whether it was already confirmed. Asking again
  produces a fresh one.
