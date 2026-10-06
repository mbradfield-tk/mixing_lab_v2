# Modularization roadmap: FastAPI back end + React front end

Status date: 2026-10-06. This plan follows on from the "Option 2" refactor (Parts 1–4). **P0 is complete** (see the P0 section for what was delivered); P1 is next.

## Where we are

```mermaid
flowchart LR
    pages["pages/ (Taipy UI)"] --> services["core/services.py"]
    pages --> viz["viz/ (plotly, matplotlib)"]
    pages --> reports["reports/ (snapshots, PDF service)"]
    services --> core["core/ (domain, no UI)"]
    reports --> core
    reports --> viz
    core --> engine["utils/calculations, rom_registry, solvent_properties"]
```

**Done:**

- **Domain logic in `core/`** (Taipy-free):
  - operating point, envelope, solve/sweep/surface;
  - sensitivity rules, Bourne plan and I/O, scale-up, heat transfer, vessel import diff, miscibility.
- **Typed contracts.** `core/schemas.py` (pydantic) defines `PointRequest/Result`, `Solve/Sweep/Surface`, `ProtocolRequest/Result`, `ComparisonRequest`, `BourneReportRequest`, `HeatCoolRequest` and `ReactionProfileRequest`.
- **Stateless services.** `core/services.py` provides `evaluate`, `solve`, `sweep`, `surface`, `assess`, `compare`, `bourne_evaluation` and `heat_transfer_inputs`.
- **Structured output.** Rule output uses `Message`/`Finding`/`Action` objects, and enum codes are kept separate from display labels (`core/options.py`).
- **Charts.** Chart builders live in `viz/` and return `go.Figure`. `reports.service.figure_json` serialises them for react-plotly.
- **PDF reports.** All six reports go through `reports.service.render_report(kind, payload)`. When Chrome is missing, charts fall back to matplotlib.
- **Safety net.** Golden page outputs, golden report snapshots and contract tests: 787 tests in total.
- **P0 (2026-10-06).**
  - Every page computation has a service.
  - The databases go through validated repositories.
  - Admin login is server-side and fails closed.
  - Pages no longer import the calculation engine, and a test enforces the layer rules.
  - 812 tests in total.

**Still coupled to Taipy or not exposed as a service:**

| Area | Remaining coupling |
|---|---|
| Database pages (vessel, fluid, reaction, particle, recorded results) | ~~CRUD, validation, search and filtering live in page callbacks that call `save_csv`/`append_csv` directly. There are no record schemas and no repository layer.~~ **Resolved in P0:** `core/repositories.py` + record schemas. Pages keep only the Taipy table plumbing. |
| Interactive computations | ~~Pages still import the engine directly; HT, Bourne and fluid blend work have no contract.~~ **Resolved in P0:**<br>• `core/catalog.py`, `core/fluids.py` and new services in `core/services.py`.<br>• `tests/test_p0_seams.py::test_layer_boundaries` blocks direct engine imports from `pages/`. |
| Figures | Five pages still import plotly. Some figures are built in the page (for example the fluid blend phase figure and parts of the HT and Bourne pages). |
| Vessel media / schematic | Both return ready-made HTML (`pages/_vessel_media.py` builds iframe HTML; `viz/vessel_schematic.py` returns an `<img>` tag). React needs URLs or data instead. |
| Auth | ~~The admin gate is a username/password check inside the page, with a **hard-coded default password**.~~ **Resolved in P0:** `core/auth.py` reads credentials from the environment only and fails closed. Write permissions are enforced in the repositories. |
| Static and utility pages | The Unit Converter, Equations Reference and Home pages hold their logic or content inside Taipy Markdown. |
| `utils/` package | It mixes engine code (`calculations/`, `rom_registry`, `solvent_properties`), reporting (`report_builder.py`, 2,000+ lines), web plumbing (`usage.py`, Flask) and UI (`menu_icons.py`). |
| Server | `app.py` combines Flask, Taipy, usage logging, media `path_mapping` and CSS. There is no HTTP API. |

## Target architecture

```mermaid
flowchart LR
    react["React SPA (Vite + TS)"] -- "JSON / PDF" --> api["api/ (FastAPI routers)"]
    taipy["Taipy pages (legacy, shrinking)"] --> services
    api --> services["core/services + repositories"]
    services --> domain["core/ domain + engine"]
    api --> reports["reports/ + viz/"]
    domain --> store["data store (CSV now, DB later)"]
```

**Rules:**

- `core/` never imports `taipy`, `plotly`, `fastapi` or `pages`.
- `api/` and `pages/` are thin adapters over the same services.
- Every response is JSON-serialisable through `core.serialize.jsonable` or a pydantic model.

## Plan, in priority order

Each step keeps the Taipy app working and the golden tests passing, so the migration can stop at any point.

### P0: finish the back-end seams (needed before any React work)

> **Status: done (2026-10-06).** Steps 1–3 below are complete. What was delivered is listed under each step. All golden page and report outputs are unchanged; the only intended behaviour changes are listed in [README_code_changes.md §14](README_code_changes.md).

**1. Service contracts for every remaining interactive computation.**

- **Heat Transfer.** Add requests and services for batch heat/cool, reaction profile, UA-vs-RPM and UA-vs-volume sweeps, and the U/UA surface. Reuse `heat_transfer_inputs`.
- **Bourne Protocol.** Move the page's private helpers (condition tables, KPI assessment, summary) behind services:
  - `bourne_plan(system)`
  - `bourne_test_conditions(test_n, ...)`
  - `kpi_assessment` (already partly done)
  - `bourne_outcome`
- **Fluid DB blend.** Add `blend_properties(components)`, `blend_phases(components)` (already in `core.miscibility`) and `property_curves`.
- **Vessel Comparison.** Expose the heat-balance and correlation-source availability (`available_modes_multi`) through `core/services`.
- **Remove direct engine imports from `pages/`.** Drop `utils.calculations`, `utils.rom_registry` and `utils.solvent_properties` imports. Option lists such as `list_solvents` and `available_modes` become `core/services.options_*()` functions.
- **Tests.** Add a contract test per service that is checked against `tests/golden/page_outputs.json`, as `tests/test_contracts.py` already does.
- **Lock it in.** Add an import-rule test (or `import-linter`) that fails if `pages/` imports `utils.calculations`, or if `core/` imports `taipy` or `plotly`.

*Delivered:*

| Area | Services (`core/services.py`) | Contracts (`core/schemas.py`) | Logic moved out of the page |
|---|---|---|---|
| Heat Transfer | `heat_cool`, `reaction_profile`, `ua_surface` | `HeatCoolResult`, `ReactionProfileResult`, `UaSurfaceRequest/Result`, `Coefficients`, `Resistance`, `HeatTransferResolved` | Sweep-parameter map, now `core.heat_transfer.SWEEP_PARAMETERS` |
| Bourne Protocol | `bourne_plan`, `bourne_assess` (and the existing `bourne_evaluation`) | `BournePlanRequest/Result`, `BourneAssessRequest/Result`, `BourneTestOut`, `SpeedSetpoint`. `BourneReportRequest` now extends `BourneAssessRequest`. | Per-test verdict text and the decision-tree summary, now `rules.bourne_test_verdict` and `rules.bourne_summary_md` |
| Fluid DB | `solvent_state`, `blend` | `SolventStateRequest`, `BlendRequest/Result`, `BlendPair` | The whole blend calculation (mixing rules, pair miscibility, settled phases, dispersion screen), now `core/fluids.py`. The page only formats. |
| Vessel Comparison | `scale_up_match` | `ScaleUpRequest/Result`, `ScaleUpRow` | Scale-up matching and the heat summary, now `scale_up.scale_up_match` and `scale_up.heat_summary_data` |
| Option lists | `options()` | `OptionsResult`, `OptionItem` (code + label for every `core.options` enum) | `core/catalog.py`: reactor, reaction, fluid and particle names, plus solvent lookups and correlation sources. `options()` reads them live; the Taipy pages still build their lists once at import. |

*Tests:* [tests/test_p0_seams.py](../tests/test_p0_seams.py) contains:

- service consistency checks against the core calculations;
- the `test_layer_boundaries` import rules:
  - `pages/` must not import `utils.calculations`, `utils.rom_registry` or `utils.solvent_properties`;
  - `core/` must not import `taipy`, `plotly`, `matplotlib`, `pages`, `viz`, `reports` or `fastapi`;
  - `viz/` and `reports/` must not import `taipy` or `pages`.

**2. Data layer: record schemas and repositories.**

- **Record schemas.** Add pydantic models in `core/schemas.py`: `Reactor`, `Reaction`, `Particle`, `Fluid` and `RecordedResult`.
  - Fields mirror the CSV columns.
  - Friendly labels come from the existing column maps.
  - Validation reuses `utils/validation.py`.
- **Repositories.** Add `core/repositories.py` with `list`, `get`, `create`, `update`, `delete`, `search(field, op, value)` and `import_preview`/`import_apply`, built on `core.csv_store` and `core.vessel_import`.
  - The mtime cache and atomic writes stay as they are.
  - The rest of the code depends only on the repository interface, so switching to SQLite or Postgres later only changes one module.
- **Move page logic into the repositories:**
  - search/filter (`filter_rows`, `_numeric_series`, and stripping thousands separators);
  - ID assignment and `search_name` generation;
  - recorded-results append and clear.
- **Fix the option-list snapshot limit.** Option lists come from repository calls, so they are no longer frozen at import time.

*Delivered:*

- **[core/tables.py](../core/tables.py).** The framework-free frame helpers moved here from `pages/_db_common.py`:
  - tolerant CSV import (now also accepts raw upload bytes);
  - inline edit, delete and add-blank;
  - `search(df, query, columns, op)`, with numeric `= < <= > >=` comparisons that tolerate thousands separators;
  - the friendly column labels.

  `pages/_db_common.py` re-exports these helpers, so the existing imports keep working.
- **[core/repositories.py](../core/repositories.py).** Instances `reactors`, `reactions`, `particles`, `fluids` and `results` provide:
  - `load`, `shared` (the mtime-cached frame), `names`, `get`, `index_of` and `search`;
  - `create` (validated; rejects duplicate names; custom fluids may not reuse a library solvent name);
  - `edit`, `update`, `delete`, `add_blank` and `replace` (import).

  `ReactorRepository` keeps reactor IDs and search names in step and adds `import_changes`/`apply_import`. `ResultsRepository` adds `append`/`clear`, plus `filter_results`/`result_counts`.
- **Errors.** `ValueError` means invalid input (422), `LookupError` an unknown name (404), and `PermissionError` a refused write (403).
- **Record schemas.** `ParticleRecord`, `ReactionRecord`, `FluidRecord` and `ReactorRecord` (extra columns allowed) live in `core/schemas.py`. `validation_message()` turns a pydantic error into one readable line with the friendly field label.
  - `ReactionRecord` derives `t_rxn_s` from k (and C0) the way the old add-form did.
  - Particle sizes must satisfy d10 ≤ d50 ≤ d90.
- **Pages rewired.** All four database pages and Recorded Results now go through the repositories, and so do the Vessel Assessment and Vessel Comparison “save result” actions.
- **Option lists.** The analysis pages read their option lists from `core/catalog.py` instead of their own `pd.read_csv` calls.
- **Not yet:**
  - The RecordedResult schema. Rows are still free-form dicts from the two save actions; define the schema when the `/results` endpoint is designed.
  - Live option lists in the Taipy pages. The lists come from the repositories but are still built once at import. React and the API get live lists through `options()`, so this is not worth fixing in Taipy.

**3. Server-side authentication and authorisation.**

- Remove the hard-coded default admin password. Require the env vars and fail closed if they are missing.
- Define one `authorize(user, action)` hook in the service layer. Write operations (DB edits, imports, clearing recorded results) must call it.
- For the API, use a session or JWT, or the corporate SSO/reverse-proxy identity header. Never trust a client-side flag.

*Delivered:*

- **[core/auth.py](../core/auth.py).**
  - Credentials come only from `MIXING_LAB_ADMIN_USER` / `MIXING_LAB_ADMIN_PW`, compared in constant time.
  - With either variable unset, admin login is **disabled** and the page says so.
  - `login()` returns a `Principal`; `authorize(principal, table)` raises `PermissionError`.
- **Write policy.** `PROTECTED_TABLES = {reactors, reactions}`, which matches the previous UI gates. Particles, custom fluids and recorded results stay open.
  - The repositories enforce the policy, so it now also covers the Reaction “Add reaction” form, which previously bypassed the lock.
  - **Decision needed before P1:** should particles, fluids and the recorded-results “clear all” also require admin?
- **Taipy gotcha found along the way.** Taipy resolves `state.<var>` from the *calling module's* frame. Shared helpers in `pages/_db_common.py` therefore must not read or write `state`. They return values (`unlock_attempt`, `as_principal`), and each page's `on_admin_unlock` / `on_admin_lock` assigns them.

### P1: HTTP API alongside Taipy

**4. FastAPI skeleton (`api/`).**

- **Routers** (all reuse the existing pydantic contracts):

| Router | Purpose |
|---|---|
| `/vessels` | Database pages |
| `/fluids` | Database pages |
| `/reactions` | Database pages |
| `/particles` | Database pages |
| `/results` | Recorded results |
| `/assessment` | Point, solve, sweep, surface |
| `/comparison` | Vessel comparison |
| `/bourne` | Bourne protocol |
| `/sensitivity` | Mixing sensitivity |
| `/heat-transfer` | Heat transfer |
| `/reports/{kind}` | `render_report`, returns `application/pdf` |
| `/options` | Enums and labels from `core/options.py` |

- **Error mapping:** `LookupError` maps to 404 and `ValueError` maps to 422. Add CORS settings, a health check and a version endpoint.
- **Media:** serve `images/` and `assets/` as static files with the same cache headers that `app.py` sets today.
- **Usage logging:** port it to middleware (`utils/usage.py` is Flask-specific).
- **Hosting:** run it as its own uvicorn process, or mount it next to Taipy behind the reverse proxy (`/api/*` to FastAPI, everything else to Taipy).
- **Tests:** use `TestClient` to replay every golden scenario through HTTP and assert parity.
- **Types for React:** export the OpenAPI schema and generate TypeScript types with `openapi-typescript`. Commit the generated file or regenerate it in CI.

**5. Charts as data.**

- Move the remaining in-page figure code (fluid blend phase figure, HT and Bourne leftovers) into `viz/`. After that, no page imports plotly.
- Chart endpoints return `figure_json(fig)` (react-plotly.js renders it directly). Optionally they can return raw series and let React build the figure.
- Keep `env-rows-N` and height hints in the response metadata, not in CSS class names.

**6. Media and schematic as data.**

- `pages/_vessel_media.py` should be split:
  - the media lookup (`find_vessel_media`, caption) goes into a core function that returns `{kind: "3d"|"image", url, caption}`;
  - the HTML builders stay in Taipy-only code.
  - React then renders `<model-viewer>` or `<img>` itself.
- `viz/vessel_schematic.py`: separate the geometry (outline points, liquid level, impeller and baffle boxes, the `brim_volume` capacity curve) into `core/` from the matplotlib rendering. The API can then return JSON geometry (drawn as SVG in React) or a PNG/SVG file.

**7. Reorganise the `utils/` package.**

| Current | New location |
|---|---|
| `utils/calculations/`, `rom_registry`, `rom_templates`, `solvent_properties`, `validation`, `bourne_kpi` | `core/engine/` (or keep as-is, but treat as core: no UI imports) |
| `utils/report_builder.py` | `reports/pdf/` (split per report: assessment, comparison, protocol, bourne, heat transfer) |
| `utils/usage.py` | `api/middleware/usage.py` (plus a Taipy adapter until retirement) |
| `utils/menu_icons.py` | `pages/` (Taipy-only) |

Make each move with `git mv` plus import updates, and require the golden tests to pass after every move.

**8. Static and utility pages.**

- **Equations Reference:** serve `data/equations_reference.json` as-is from `/equations`.
- **Unit Converter:** move the conversion tables and functions into `core/units.py` and expose `/units/convert`. React can also convert on the client.
- **Home:** becomes static React content. `APP_VERSION` comes from `/version`.

### P2: React migration (strangler pattern)

**9. Make services fully stateless and fast enough to call per interaction.**

- Replace per-session Taipy caches (`_va_cache`, `_vc_cache`, `_ms_cache`) with caches keyed by input hash (`functools.lru_cache` on frozen request models, or Redis on the server).
- Long-running work (3D surfaces, multi-vessel comparisons, PDFs with kaleido) runs as `POST` → job id → poll, or with FastAPI `BackgroundTasks`. Add timeouts.
- **File uploads.** Vessel import, Bourne CSV and DB imports become multipart endpoints that return a preview diff, followed by a separate apply call. This matches the current approve/skip dialog.

**10. Build React pages one at a time, starting with the lowest risk.**

| Order | Page | Reason |
|---|---|---|
| 1 | Home, Equations Reference, Unit Converter | Static or read-only; proves routing, theming (Takeda palette), auth and deployment |
| 2 | Particle, Reaction, Fluid DB (tables + CRUD) | Exercises repositories, validation and the admin gate |
| 3 | Vessel DB (+ import review, 3D viewer, schematic) | Uploads, diff review, media |
| 4 | Recorded Results | Filters plus CSV download |
| 5 | Vessel Assessment | Main computation page; point, envelope, surfaces, solve-for, PDF |
| 6 | Vessel Comparison | Multi-vessel, scale-up matching |
| 7 | Heat Transfer | Many charts and sweeps |
| 8 | Bourne Protocol | Multi-step workflow, editable KPI tables |
| 9 | Mixing Sensitivity | 8-step decision tree; depends on Bourne CSV import |
| — | Crystallization Sensitivity | Still a placeholder; build it directly in React when ready |

- Each React page goes live behind the reverse proxy (`/app/<page>`), while the Taipy version stays reachable until users sign off.
- **Front-end stack:** Vite + React + TypeScript, generated API types, TanStack Query for data fetching and caching, react-plotly.js, `@google/model-viewer`, and a table component that supports inline editing (for example AG Grid or TanStack Table).
- **Acceptance per page:** same numbers as the golden scenarios (the API parity tests already guarantee this), PDF parity, and side-by-side UX review.

**11. Retire Taipy.**

- Delete `pages/` and the Taipy parts of `app.py`, and drop `taipy-gui` from `requirements.txt`.
- Move deployment from gunicorn with gevent-websocket to uvicorn/gunicorn with uvicorn workers. No WebSocket is needed unless jobs push progress.
- Keep the `.taipyignore` lesson: serve only explicit static folders, never the repo root.

## Cross-cutting items (do these alongside the steps above)

- **CI:** run pytest, pyflakes or ruff, the import-rule test, and the OpenAPI schema diff on every push.
- **Versioning:** version the API (`/api/v1`) and the report snapshot schema, so PDFs and React stay compatible.
- **Data:** decide whether to stay on CSV (single writer, file lock) or move to SQLite or Postgres before multi-user React editing. The repository layer from step 2 makes this a single-module change.
- **Security (OWASP):**
  - validate every input with pydantic;
  - set size limits on uploads;
  - prevent path traversal in media lookups (keep the `images/` root check);
  - never put user input into a file path;
  - require auth on write endpoints;
  - avoid leaking stack traces in 500 responses.
- **Docs:** generate API docs from OpenAPI (`/docs`). Keep `docs/README_code_changes.md` for behaviour changes only.

## Suggested next increment

Steps 1 and 3 can start right away and are independent. Do step 1 first, Heat Transfer and then Bourne, because those pages carry the most non-service logic. Step 2 (repositories) then unblocks both the database API and the first React CRUD pages.
