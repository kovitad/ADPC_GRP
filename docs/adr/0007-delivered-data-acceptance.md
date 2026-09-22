# ADR-0007: Treat the Data Science delivery as accepted source data

**Status:** Accepted by the product owner on 2026-09-19.

**Date:** 2026-09-19

**Deciders:** Product owner and architecture owner (Ole); Scientific and Data Authority delivery acknowledged by the product owner

## Context

The district preview called every delivered file “unapproved” and raised a blocker solely because a licence, edition and checksum had not yet been entered in GRP. The product owner confirmed that the files in `.local/data-in` were supplied by the Data Science team for this work and should be treated as the accepted source delivery.

That acceptance is different from a completed assessment. The preview reads files directly: GRP has not yet created immutable dataset versions, pinned their checksums to a job or applied an approved method. The flood no-value meaning is also unresolved and materially changes shelter classifications.

## Decision

- Treat the files delivered by the Data Science team as **accepted source data**.
- Label the Admin screens **Delivered source data** and **Delivered data preview**, not “unapproved data”.
- Do not report source acceptance as a blocker. If a source/provenance record is absent beside the files, report it as known ingestion setup work.
- At ingestion, register the provider, source approval, edition, licence terms, retrieval date and computed checksums in immutable dataset-version records. Missing registration prevents publication as evidence, but does not mean the delivered files themselves were rejected.
- Keep scientific-method questions separate. In particular, DEP-05 remains a blocker for a real result because no-value could mean either dry or never modelled. Shelter-coordinate mismatches remain data-quality problems, and the meanings of `สถา` and `รอง` remain pending under DEP-06.
- A preview remains not a GRP assessment: it does not classify shelters, run an approved method or send data to SIG.

## Consequences

- The UI accurately acknowledges the Data Science delivery instead of asking the owner to approve it again.
- The next work is registration and method definition, not re-approval of the files.
- Source acceptance alone does not authorize a scientific result or public evidence claim.

## Action items

- [x] Replace “unapproved” labels on Source data and District preview.
- [x] Remove the file-approval blocker from district-preview warnings.
- [x] Grade absent provenance metadata as known ingestion setup work.
- [ ] Add dataset-version ingestion that records approval, provenance and checksums.
- [ ] Resolve DEP-05 before classifying shelters from the flood raster.
- [ ] Confirm the shelter fields under DEP-06.
