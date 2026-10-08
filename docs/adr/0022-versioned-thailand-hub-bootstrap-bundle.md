# ADR-0022: Versioned Thailand Hub bootstrap bundle

**Status:** Accepted; implementation in progress

**Date:** 24 September 2026

**Deciders:** Product Owner, Scientific and Data Authority, Technical Lead, Platform Operations

## Context

The delivered `.local/data-in` tree is approximately 2.1 GB and includes administrative geography,
preparedness points, RP100 flood tiles and three vulnerability rasters. A fresh deployment currently
starts the application and synthetic seed but requires manual baseline imports. The product owner
wants a strong Thailand demonstration after deployment and accepts rebuilding the demo database,
provided administrator configuration is retained. Later users must be able to upload and choose
Hub-local dataset versions.

## Decision

Package the source data outside Git and container images as a checksum-pinned Thailand release
bundle. Add an idempotent bootstrap orchestrator that validates, converts, imports and atomically
activates compatible immutable dataset versions for the ADPC Hub. Persist only allow-listed admin
configuration outside the database for demo resets. Keep later Hub uploads as separate immutable
candidates and explicit category selections.

Preload vulnerability rasters as separate display-ready sources, not as an approved composite
calculation. Make local data sufficient for the primary planning workflow; use SIG optionally for
missing external evidence and explicit cross-Hub/public exchange.

The implementation plan is
[`docs/thailand-hub-bootstrap-data-plan.md`](../thailand-hub-bootstrap-data-plan.md).

## Options considered

| Option | Assessment |
|---|---|
| Commit data to Git | Rejected: size, provenance, licence and repository-operability problems |
| Bake data into the application image | Rejected: slow images, coupled releases and repeated transfer |
| Restore a prebuilt database dump | Rejected for the demo: opaque migrations, environment coupling and weak provenance |
| Versioned external bundle plus idempotent import | Chosen: traceable, repeatable and compatible with later object storage |
| Require SIG for every planning question | Rejected: unnecessary latency/dependency when approved local data exists |

## Amendment, 8 October 2026: assessment-core deployment profile

A resource-constrained pilot may install the independently valid assessment core without the
optional heavy context: administrative hierarchy excluding village points, DDPM shelters, six
RP100 tiles and the approved overlay method. The explicit `--assessment-core-only` CLI option and
`--bootstrap-thailand-assessment-core` Ubuntu option select this profile. They do not silently
weaken the complete release or relabel missing context as ready.

The three vulnerability rasters remain display-only under the approved method and are not an
assessment input. Volunteer centres, warning resources and village locations are also optional
context. Their absence must stay visible in Data Library, while the release card may separately say
**Assessment core ready** once boundaries, shelters and RP100 are active. The complete profile
remains the route to a fully ready Thailand release, and later imports do not change versions
pinned by existing assessments.

## Consequences

- Deployment requires a controlled source-bundle transfer or direct object-storage URL.
- Bootstrap takes longer because large rasters are transformed; progress and resume are mandatory.
- Data readiness remains independent from presence, preventing preloading from implying approval.
- Admin configuration becomes declarative and recoverable without preserving user activity.
- Production still requires database, object-storage and secret backups; the no-backup decision is
  limited to the current rebuildable demo environment.

## Action items

1. [ ] Confirm source/licence/authority metadata and checksums for the release manifest.
2. [ ] Measure transformed disk use and define bootstrap host preflight requirements.
3. [x] Implement the dependency-aware installer and exact-version activation for the existing
   district, shelter and RP100 importers; broader release-atomic activation follows with hierarchy.
4. [ ] Implement display-only vulnerability conversion without a composite method.
5. [ ] Implement allow-listed admin settings export/apply and rehearse a blank reset.
6. [ ] Add Hub override selections and prove historical assessment replay.
