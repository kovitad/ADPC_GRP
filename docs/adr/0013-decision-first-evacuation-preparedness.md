# ADR-0013: Make evacuation decisions and preparedness investment the primary workflow

**Status:** Accepted by Product Owner for incremental implementation  
**Date:** 20 September 2026

## Context

The Product Owner wants Planning to maximize decision value around two linked outcomes:

1. identify where vulnerable people could move during a selected flood scenario; and
2. build a credible, traceable case for preparedness funding.

A generic autonomous assistant or a hazard map alone does not answer either question. The current platform can display flood depth and evacuation centres, run one synthetic screening, and retrieve SIG screening evidence. It does not yet have approved vulnerability meanings, verified centre capacity/accessibility, safe-route analysis, multiple real hazard scenarios or approved investment templates.

Calling a centre “safe” from flood intersection alone would be misleading. A candidate may have lower mapped flood exposure while still being unsuitable because of capacity, building condition, accessibility, route conditions, services or hazards absent from the model.

## Decision

### Primary product output

Planning will build an **Evacuation Preparedness Decision Package** for a confirmed district or supported sub-district and scenario. It has two linked sections.

#### A. Movement options

- vulnerable groups and movement needs, with source year and known data gaps;
- candidate evacuation centres with lower mapped exposure under the selected scenario;
- potentially exposed and unable-to-assess centres;
- capacity, accessibility, essential services and route evidence when approved data exists;
- reasons, exclusions and unresolved checks for every candidate;
- a prominent statement that “candidate” does not mean certified safe.

#### B. Preparedness investment case

- planning problem and affected area;
- evidence-backed service, capacity, accessibility, route and data gaps;
- prioritized interventions tied to those gaps;
- expected beneficiaries only where an authoritative denominator exists;
- scenario comparison when compatible immutable hazard versions exist;
- cost assumptions supplied through an approved template, never invented by AI;
- source/version trace, limitations, readiness and review status;
- exportable brief and map after DEP-12 approval.

### Orchestration

Use a bounded decision workflow, not an unrestricted autonomous agent:

1. confirm purpose, AOI, scenario and Hub;
2. resolve access and compatible local inputs;
3. use locked GRP results when they can answer the question;
4. call SIG MCP only for complementary screening evidence that is actually needed;
5. run independent local and SIG retrieval concurrently where appropriate;
6. normalize evidence into typed, separately labelled GRP/SIG sections;
7. apply deterministic readiness, provenance and grounding checks;
8. let AI explain and structure only the supplied evidence;
9. require human review before export or public SIG receipt.

### Optimization objective

“Maximum result” means maximum **decision completeness and traceability**, not maximum tool calls, text length or claims. The workflow should expose a coverage matrix for:

- hazard;
- evacuation-centre location;
- capacity;
- accessibility and services;
- route condition;
- vulnerable groups/population;
- intervention and cost assumptions.

Each dimension is `available`, `partial`, `missing` or `blocked`, with a source or reason. Missing evidence becomes a funding/data-preparation gap; it is never filled with model inference.

### Delivery stages

1. **Current:** flood-depth context, evacuation-centre locations, synthetic classification, SIG screening and explicit gaps.
2. **Candidate movement screening:** real assessment after DEP-05 and pilot-area approval.
3. **Vulnerable groups and proximity:** after DEP-07 and approved indicator/distance methods.
4. **Investment case:** after intervention/cost fields and DEP-12 templates.
5. **Risk and route suitability:** only after approved methods and sources; independent of the red flood-depth palette.

## Consequences

- Workspace language prioritizes candidate movement and investment evidence rather than a general chatbot or decorative risk map.
- The product never promises a “safe place”; it presents candidate locations and the checks still required.
- SIG is complementary, not mandatory. Its latency or outage cannot block a valid local GRP result.
- AI cannot invent vulnerable-population totals, costs, benefits, centre capacities or recommendations unsupported by evidence.
- Sub-district support remains part of the target, but requires managed geometry, parent linkage and explicit assessment eligibility.
- The first implementation slice can improve purpose/AOI/configuration UX now, while unavailable scientific outputs remain visibly blocked.
