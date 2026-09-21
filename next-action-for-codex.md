# Next action for Codex

**Written:** 21 September 2026, from an independent review of `codex/sig-embedded-flood-map` at `3039718`.

**Do first:** Slice 1 below, repository hygiene. It is small, it needs a decision from nobody, and it unblocks Linux verification of everything that comes after it.

**Read first:** `AGENTS.md`, then `handovers.md` Sections 1, 3 and 9. This file does not replace them; it names the next slice and the evidence behind it.

---

## 1. Verified starting point

Reproduced on Linux with Python 3.12 on 21 September, so "unchanged" has a number:

```bash
python -m pytest        # 293 passed, 2 skipped
python -m ruff check .  # All checks passed!
```

The two skips are `tests/contract/test_postgres_data_import.py`; they need `GRP_POSTGRES_TEST_URL_FILE`. The handover's claims match the code — nothing in it was found overstated.

**Slice 1 changes no behaviour.** The same 293 tests must pass at every commit in it. If a test needs editing beyond an import line or a new case, stop and say why.

---

## 2. Slice 1 — repository hygiene

### Task 1 — rename the `grp` package to `grpcli`

**Problem.** `grp` is the name of a Python standard-library module: the Unix group database. On CPython builds where it is compiled in, a built-in module beats every entry on `sys.path`, so a directory named `grp/` can never be imported, whatever the path order. Confirmed on 21 September for two interpreters — uv-managed CPython 3.12 and Debian's `/usr/bin/python3.12` — where `'grp' in sys.builtin_module_names` is `True`. `from grp.admin import ...` then raises:

```text
ModuleNotFoundError: No module named 'grp.admin'; 'grp' is not a package
```

and 14 test modules fail to collect. The suite cannot run at all.

**Why it has not bitten us yet.** Windows has no stdlib `grp`. In `python:3.12-slim` it is a shared extension rather than a built-in, and `deploy/Dockerfile` sets `WORKDIR /app` and does `COPY grp ./grp`, so the current working directory shadows the stdlib module at `sys.path[0]`.

**Why it is worth an hour now.** This is not only a CLI concern. `api/admin.py:11` and `api/platform.py:22` import `grp.admin` at application import time, so the API server itself depends on that name resolving to our package. Today it works because of a working-directory accident. A base image that compiles `grp` in, or a service started from another directory, turns it into an application that will not start. Meanwhile it already blocks any Linux contributor or agent on a statically linked interpreter from running the tests.

**What to change.** Rename the directory `grp/` to `grpcli/` and update every reference:

| Kind | Files |
|---|---|
| Application imports | `api/admin.py:11`, `api/platform.py:22` |
| Packaging | `pyproject.toml:36` — `include = ["api*", "core*", "grpcli*", "worker*"]` |
| Container | `deploy/Dockerfile` — `COPY grpcli ./grpcli` |
| Scripts | `scripts/docker-desktop.ps1:95,98,99,104`; `scripts/admin-local.ps1:14`; `scripts/run-local.ps1:16,19` |
| Tests | `tests/contract/test_permission_matrix.py:32`; `tests/fast/test_admin_access.py:17`, `test_configuration.py:3`, `test_dev_setup.py:3`, `test_identity_access.py:13`, `test_planning_chat.py:32`, `test_platform_admin.py:27`, `test_session_security.py:20`, `test_sig_service_login.py:19`; `tests/golden/test_planning_map.py:35-36`, `test_synthetic_rp100.py:37-38` |
| Docs | `README.md:66`; `docs/access-management.md:20,54,56,63,66`; `docs/adr/0002-interim-sig-mcp-client-login.md:13,40`; `handovers.md:189,191` |

Leave the system group named `grp` in `deploy/Dockerfile` alone — that is an OS group, unrelated to the module name.

**Done when.** `python -m pytest` collects and passes **293** on a Linux interpreter where `grp` is built in, `python -m ruff check .` is clean, and the Docker Desktop stack starts and serves `/api/v1/healthz` after a rebuild. Verify at least one of `python -m grpcli.admin ensure-hub` or `python -m grpcli.seed synthetic-rp100` inside the container, since those are the paths the scripts use.

### Task 2 — cover the data-library routes in the permission matrix

**Problem.** `AGENTS.md` requires the permission matrix test to cover new routes. The three `/data-library` operations are not in it. `tests/fast/test_data_library_api.py` overrides the principal to a Platform Admin and tests three happy paths only, so nothing proves that a Hub Admin, an NDMO Planner or a signed-out caller is refused `POST /api/v1/data-library/imports/boundaries`.

CSRF is **not** a gap here: it is enforced centrally in the principal dependency at `api/sessions.py:158`, so the new POST inherits it. Do not add a per-route check.

**What to change.** Add to `tests/contract/test_permission_matrix.py`:

- `GET /api/v1/data-library` — Platform Admin and Hub Admin allowed; Planner and Hub Expert refused.
- `POST /api/v1/data-library/imports/boundaries` — Platform Admin only; every other role refused, including Hub Admin.
- `GET /api/v1/data-library/imports/{import_id}` — Admins allowed; an unknown ID returns 404, not a confirmation that the job exists.

**Done when.** Each of the three appears in the matrix with at least one allowed and one refused role, and removing the `PlatformAdmin` dependency from `import_boundaries` makes a test fail.

### Task 3 — make the matrix fail when a route is added without an entry

**Problem.** The matrix is a hand-maintained dictionary with no completeness check, which is why the omission above went unnoticed. Measured on 21 September: the application declares **40 protected operations** and the matrix file mentions **14** of them. `tests/contract/test_route_access.py` does not catch this — it only asserts that every operation declares `x-grp-access`.

**Do not try to write 26 new matrix entries in this slice.** That is a slice of its own, and some of those routes are covered by other test modules.

**What to change.** Add a ratchet: a test that reads `app.openapi()`, collects every operation declaring `x-grp-access: protected`, and asserts that each one is either exercised by the matrix or named in an explicit `KNOWN_UNCOVERED` set with a one-line reason per entry. Seed that set with the 26 currently uncovered operations. A newly added route is in neither place, so the test fails until someone chooses.

**Done when.** Adding a protected route without touching the test file makes the suite fail, and the set of exemptions is visible in one place so it can be burned down later.

---

## 3. Explicitly not in this slice

- **Do not touch `is_current` or `is_supported`.** That is Slice 3 and it needs a product-owner decision about which districts are supported. See Section 5.
- **Do not start the shelter loader in the same change.** Hygiene should merge on its own so it can be reviewed in minutes.
- **Do not add browser upload, enable a real flood assessment, or import the vulnerability rasters.** All three remain gated (ADR-0008, DEP-05, DEP-07).

---

## 4. What comes after, in order

| # | Slice | Size | Blocked by |
|---|---|---|---|
| 2 | DDPM shelter loader: membership by geometry, the 1,139 mismatches reported at load time and never silently accepted, reusing the proven staging and promotion pipeline | 2–4 days | Nothing. DEP-06 gates *showing* `สถา` and `รอง`, not loading geometry |
| 3 | Activation path: Platform Admin marks specific districts supported and a version current, audited, writing `hub_dataset_selection` | 1–2 days | Owner decision on which districts |
| 4 | RP100 six-tile logical manifest, ordered and checksummed, landing in `waiting_for_method` | 2–3 days | Nothing. Classification stays blocked by DEP-05 |
| 5 | Docker Desktop acceptance with measured time, memory and disk; then a pull request to `main` | 1 day | Nothing |

Three things are not code and have the longest lead time. They should be moving in parallel from today: the DDPM data-quality counts (1,139 of 10,303 shelters in a different district from the one they name, 255 districts with no shelter), the DEP-05 no-data decision put as the concrete Pua question from `docs/dataset-proof-results.md`, and the DEP-06 confirmation of the shelter layer and its truncated Thai columns.

---

## 5. Kept on record: the imported baseline is unreachable

This is the largest finding of the review. It is not Slice 1 work, but it should not be rediscovered later.

All 928 districts imported successfully and no planner can see any of them. `promote_import_version` sets `is_current=False` (`core/data_import_jobs.py:246`) and the boundary loader sets `is_supported=False` (`core/boundary_import.py:195`). Every consumer filters on exactly those two flags — `api/catalog.py:25` and `:59`, `api/planning.py:433`, `api/maps.py:60`, `core/assessment_jobs.py:90`. Nothing in the repository sets either to `True` except `grp/seed.py` (`grpcli/seed.py` after Task 1) for the synthetic case. `HubDatasetSelection` is defined in `core/data_library_models.py:100` and is neither read nor written by any code.

Failing closed is the right default. The gap is that there is no path out of it, so every further loader adds more data that nobody can use. Slice 3 exists to close it, and it is what will let the product owner pick a real Thai district in the app instead of the synthetic one.

---

## 6. Working rules for this slice

- Follow `AGENTS.md`. Commit subjects are `feat:`, `fix:`, `docs:` or `test:`, imperative and scoped.
- Slice 1 is `refactor`-shaped but behaviour-preserving: use `fix:` for the rename and `test:` for Tasks 2 and 3, in separate commits.
- Never commit `.env`, keys, tokens, `.local/`, captures with secrets, or the specification `.docx`.
- Run `python -m pytest` and `python -m ruff check .` before every push, and say in the pull request which interpreter proved Task 1 — the rename is only proved on a build where `grp` is built in.
