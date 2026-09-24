# Proposed Backend Architecture Approach

## 1. Architecture Direction

For the initial platform implementation, we propose using a **Modular Monolith with Clear Service Boundaries and Single Ownership of Data**.

The objective is to keep development and operations practical for our current small team, while establishing architectural boundaries that allow the platform to evolve later.

We should **not start with microservices unless there is a clear operational or scaling reason to do so**.

Instead, we establish service/module responsibilities now and retain the option to extract individual modules into independently deployed services later.

## 2. Modular Monolith vs. Microservices

| Area                   | Modular Monolith                                      | Microservices                                    |
| ---------------------- | ----------------------------------------------------- | ------------------------------------------------ |
| Application structure  | One application containing separated modules          | Multiple independent services                    |
| Deployment             | Primarily deployed as one application                 | Each service can be deployed independently       |
| Responsibility         | Clearly separated by module                           | Clearly separated by service                     |
| Communication          | Mostly internal interfaces/function calls             | API, RPC, events or messaging                    |
| Database               | May share one physical database with strict ownership | Commonly separate databases/data ownership       |
| Data writes            | One owning module writes to its domain/tables         | Owning service writes to its datastore           |
| Operational complexity | Lower                                                 | Higher                                           |
| Kubernetes requirement | Not required                                          | Often useful at larger scale                     |
| Independent scaling    | Limited initially                                     | Individual services can scale independently      |
| Small-team suitability | Strong                                                | Requires more DevOps/service-management overhead |
| Future evolution       | Modules can later be extracted                        | Already independently deployable                 |

For our current stage, the **Modular Monolith provides the simpler operational model while still allowing us to design proper service boundaries.**

---

# 3. Core Design Principle: Clear Ownership of Responsibility

Every business capability should have **one clearly identified owning module**.

For example:

```text
Platform
│
├── Identity / Access Module
│     Owns: users, roles, permissions
│
├── Dataset Module
│     Owns: datasets, metadata, catalog
│
├── Upload Module
│     Owns: upload workflow and validation
│
├── Job Module
│     Owns: jobs, execution status, results
│
├── Evidence Module
│     Owns: evidence, provenance, citations, receipts
│
└── Audit / Monitoring Module
      Owns: audit and operational records
```

The exact modules can evolve as requirements become clearer. The important architectural rule is the ownership boundary.

# 4. Single-Writer / Data Ownership Principle

Each business data domain must have **one owner**.

Only the owning module/service should modify the data it owns.

For example:

```text
                     Job Module
                  OWNER OF JOB DATA
                         │
                  INSERT / UPDATE
                         │
                         ▼
                     Job Tables
                         ▲
                         │
                  controlled access
                         │
             ┌───────────┴───────────┐
             │                       │
        MCP Module              Evidence Module
```

Therefore, we should avoid this:

```text
MCP Module ───────────────→ UPDATE job_table
Evidence Module ──────────→ UPDATE job_table
Admin Module ──────────────→ UPDATE job_table

                         ❌
```

Instead:

```text
MCP Module ──────┐
                 │
Evidence Module ─┼──→ Job Module ───→ Job Tables
                 │
Admin Module ────┘

                         ✓
```

The **Job Module is responsible for enforcing the rules around Job data**.

This rule should apply even when all modules currently use the same physical database.

# 5. Shared Database Does Not Mean Shared Ownership

Initially, we may use:

```text
              Modular Monolith
┌─────────────────────────────────────┐
│                                     │
│ Identity Module ───→ Identity data  │
│ Dataset Module ────→ Dataset data   │
│ Job Module ────────→ Job data       │
│ Evidence Module ───→ Evidence data  │
│                                     │
└──────────────────┬──────────────────┘
                   │
                   ▼
            Shared Database
```

Using one database is acceptable at this stage.

However:

> **A shared physical database must not become shared write ownership.**

Developers should not update another module's tables simply because they are technically accessible.

Cross-module changes should go through the owning module's defined interface.

# 6. Module Communication

Inside the modular monolith, communication can remain lightweight.

We do **not** need to create HTTP APIs between every internal module just to imitate microservices.

For example:

```text
MCP Module
     │
     │ internal interface
     ▼
Job Service
     │
     ▼
Job Repository
     │
     ▼
Database
```

The important boundary is:

```text
Other Module
     │
     ▼
Public Module Interface
     │
──────── MODULE BOUNDARY ────────
     │
Business Logic
     │
Repository
     │
Owned Tables
```

Other modules should depend on the **public interface**, not the internal repository or database implementation.

# 7. Why This Helps Us Later

Suppose Job processing eventually becomes computationally heavy and needs independent scaling.

Today:

```text
MODULAR MONOLITH

Platform
│
├── Dataset Module
├── Evidence Module
├── Job Module
└── Other Modules
        │
        ▼
    Shared DB
```

Later, we could extract Job processing:

```text
Platform
│
├── Dataset Module
├── Evidence Module
└── Job Client
       │
       │ API / Event / Queue
       ▼
┌──────────────────┐
│    Job Service   │
│                  │
│ Job logic        │
│ Job workers      │
└────────┬─────────┘
         │
         ▼
      Job DB
```

Because Job already had a clear responsibility and ownership boundary, this change should require less restructuring of business logic.

The architecture therefore supports an evolutionary approach:

```text
NOW
Small Team

Modular Monolith
      │
      │ growth / operational need
      ▼
Containerized Application
      │
      │ scaling / availability need
      ▼
Kubernetes
      │
      │ specific modules require
      │ independent lifecycle/scale
      ▼
Selective Microservices
```

**Microservices are therefore an option, not our starting requirement.**

# 8. Kubernetes Strategy

Kubernetes should also be treated as an **operational evolution**, rather than something that dictates our application architecture today.

Initially we can package the platform as a container:

```text
Application
     ↓
Docker Image
     ↓
Container Runtime
```

Later the same application can be deployed through Kubernetes:

```text
                 Kubernetes
                     │
              ┌──────┴──────┐
              │             │
          Platform       Workers
            Pod(s)          Pod(s)
              │             │
              └──────┬──────┘
                     │
                  Database
```

Kubernetes does **not require microservices**.

A modular monolith can run perfectly well in Kubernetes and can have multiple replicas when the application is designed appropriately.

If a particular capability later requires independent scaling, we can then extract it.

For example:

```text
                Kubernetes

     ┌─────────────────────────────┐
     │                             │
 Platform Pods               Job Worker Pods
     │                             │
     │                         scale 1..N
     │                             │
     └──────────────┬──────────────┘
                    │
               Data / Queue
```

This allows infrastructure complexity to grow **when there is a real requirement for it**.

# 9. Development Rules

The development team should follow these rules:

1. **One business capability = one clearly defined owning module.**

2. **One data domain = one writer/owner.**

3. A module must not directly modify another module's owned tables.

4. Cross-module operations must use the owning module's defined interface.

5. Internal repositories and implementation details should not be exposed across module boundaries.

6. A shared database is acceptable initially, but database access must respect logical ownership.

7. Avoid unnecessary network calls between modules while they are part of the same application.

8. Avoid premature microservice decomposition.

9. Keep modules sufficiently independent that important capabilities can be extracted into services later if there is a justified requirement.

10. Infrastructure choices such as Kubernetes should not force unnecessary application complexity today.

# 10. Proposed Architecture Principle

The overall principle is:

> **Start simple operationally, but design strong boundaries from the beginning.**

For our current team and platform stage, the preferred starting architecture is therefore:

**Modular Monolith + Clear Service Boundaries + Single Data Ownership + Container-Ready Deployment**

This gives us a practical development model today while preserving a path toward:

**Kubernetes deployment → independent workers/services → selective microservices**

when scale, availability, organizational structure, or operational requirements justify those changes.

The goal is **not to design a temporary architecture that will later be thrown away**.

The goal is to establish the correct business and data ownership boundaries now, while postponing distributed-system complexity until we actually need it.
