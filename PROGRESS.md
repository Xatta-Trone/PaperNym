# PaperNym: Progress and Work Log

**Read this file first in every work session.** `SPEC.md` says what to build; this file says
how far the build has got.

Rules:

1. Work on the first unchecked task of the current milestone. One milestone at a time.
2. Tick a box only after its tests pass (`.venv` python, `pytest`).
3. After each task, append an entry to the work log at the bottom.
4. At the end of a milestone, update "Current state", then stop and report.
5. `sample_pdfs/` is read-only: always work on a temporary copy, never on the originals.

## Current state

- **Current milestone:** M3
- **Next task:** hand-renamed, moved, annotated, and copied files
- **Last test run:** `.venv\Scripts\python.exe -m pytest -q tests/test_engine.py` — 3 passed
- **Open questions for the owner:** none

## Milestones

### M0 Project setup
- [x] Create `.venv` in the project root; confirm `python --version` is 3.10+
- [x] `git init`; `.gitignore` (`.venv`, `sample_pdfs/`, `__pycache__`, `build`, `dist`, `*.egg-info`)
- [x] Move `paper_renamer.py`, `test_apis.py`, `compare_sources.py`, `compare_pdf_libs.py` into `prototype/` (read-only reference); leave `pdf_metadata.py` alone
- [x] `pyproject.toml` (name `papernym`, deps `pypdfium2`, `requests`, `watchdog`; extra `gui = ["PySide6"]`; dev extra `pytest`)
- [x] Package skeleton `src/papernym/` per SPEC section 3; `tests/`
- [x] Editable install into `.venv`; `pytest` passes with one placeholder test

### M1 Core, part 1
- [x] `core/config.py`: load, save (atomic), defaults, validation, env overrides
- [x] `core/db.py`: schema, WAL, queries, daily backup, corrupt-database handling
- [x] `core/db.py`: migration from the prototype's `state.json`, `history.csv`, `config.json`
- [x] `core/lock.py`: single-writer lock (Windows and Linux)
- [x] `core/naming.py`: tokens, field cleaning, non-Latin fallback
- [x] `core/naming.py`: the 15 fixed presets (SPEC section 7)
- [x] `core/naming.py`: custom templates with fixed text, and every validation rule
- [x] `core/naming.py`: length budget (255 name, Windows 259 path), whole-word cut
- [x] `core/naming.py`: collision rules (`_dupN` for the same paper, title extension for different papers)

### M2 Core, part 2
- [x] `core/pdfread.py` on `pypdfium2`: text, lines with font size, rotation, properties, extra keys, XMP
- [x] `core/pdfread.py`: title guess, author line, `paperish`, unreadable PDFs
- [x] `core/sources/`: crossref, doiorg, openalex, semanticscholar, arxiv with field mapping (both years)
- [x] Shared HTTP layer: timeout, retry, 401/403/429 handling, user agent
- [x] `core/identify.py`: DOI, arXiv and title-search paths with verification
- [x] `core/identify.py`: paper cache and `misses` table (no repeat lookups)
- [x] `core/identify.py`: outage handling and the offline fallback rules
- [x] `title_search` privacy switch honoured
- [x] Regression table in SPEC section 17 passes
- [x] Local check: `pdfread` on a copy of every file in `sample_pdfs/`; log the DOI and title guess found for each

### M3 Core, part 3
- [x] `core/engine.py`: per-file logic and all five statuses
- [ ] Hand-renamed, moved, annotated and copied files
- [ ] Exclude list
- [ ] Scan with progress events; prune
- [ ] Dry run (scan and reformat)
- [ ] Reformat, including `include_manual`
- [ ] Undo by batch and by last N
- [ ] Manual fix (by DOI, by edited fields) and refresh
- [ ] `core/watcher.py`: events, queue, start-up scan
- [ ] Watcher: settings reload, folder reconcile (unplugged drive), retry timer, pause
- [ ] Folder rules: overlap, reference-manager warning
- [ ] Every non-UI row of SPEC section 14 has a passing test

### M4 Minimal CLI
- [ ] `cli.py`: settings commands (`add-folder`, `remove-folder`, `exclude`, `set-*`, `formats`, `show`)
- [ ] `cli.py`: `scan`, `watch`, `reformat`, `undo`, `fix`, `status`
- [ ] `cli.py`: `test-apis`, `compare`
- [ ] Output prefixes, exit codes, lock behaviour
- [ ] CLI tests
- [ ] Local end-to-end check: real `scan` on a temporary copy of `sample_pdfs/` with `PAPERNYM_HOME` set to a temporary folder; log old and new names

### M5 Tray app (priority 1)
- [ ] `papernym-gui` launches from source in `.venv` (editable install with the `gui` extra); options `--sandbox`, `--show`, `--debug`
- [ ] App start, single instance, tray icon with states, tray menu
- [ ] Worker thread running the watcher; core events delivered as Qt signals
- [ ] Main window and Activity tab
- [ ] Folders tab (with exclude list)
- [ ] Naming tab: preset dropdown, Custom template editor, live preview, validation messages
- [ ] "Apply to existing files?" flow with preview
- [ ] Sources tab with Test buttons and the title-search switch
- [ ] Needs attention tab with manual fix
- [ ] History tab with undo and CSV export
- [ ] General tab; notifications; outage and rejected-key banners
- [ ] First-run welcome with dry-run confirmation
- [ ] Manual checklist for SPEC section 12 passes on Windows 11

### M6 Windows exe
- [ ] `scripts/build_windows.py`: one command for the PyInstaller one-folder build (windowed, icon) into `dist/`
- [ ] Locally built `PaperNym.exe` runs with `--sandbox --show`
- [ ] Inno Setup installer (per-user, Start-menu shortcut, uninstaller), built by the same script
- [ ] Start at login
- [ ] Update check against the latest release
- [ ] `THIRD_PARTY_LICENSES` file
- [ ] Install, run, uninstall on a clean Windows account
- [ ] GitHub Actions release workflow: on a `v*` tag, run tests, call the build script, attach the installer to a GitHub Release

### M7 PyPI (priority 2)
- [ ] README (install, quick start, commands, privacy note), LICENSE (MIT), CHANGELOG
- [ ] Build sdist and wheel; `twine check`
- [ ] Upload to TestPyPI; install from it in a fresh venv
- [ ] GitHub Actions: tests on `windows-latest` and `ubuntu-latest`; release workflow

### M8 Linux (priority 3)
- [ ] Full test suite green on Ubuntu
- [ ] Settings folder, lock, autostart `.desktop` file
- [ ] Tray app starts; falls back to a window when no tray is available

## Work log

Newest entry at the bottom. Use this shape:

    ### YYYY-MM-DD  Mx  short title
    - Done:
    - Files:
    - Tests: (command and result)
    - Decisions: (what and why)
    - Next:

### 2026-11-10  pre-M0  Specification prepared
- Done: prototype written and run on 12 real PDFs; `SPEC.md` v1.2 and `SYSTEM_REQUIREMENTS.md` written.
- Decisions: name PaperNym; `pypdfium2` instead of PyMuPDF (license and test results); citation year as the default; SQLite storage; MIT license; macOS out of scope.
- Project folder: `F:\papernym`. Eleven real papers in `sample_pdfs/` for local testing (not in git).
- Next: M0.

### 2026-11-10  M0  Create virtual environment
- Done: Created the project `.venv` and confirmed Python 3.14.3, above the 3.10 minimum.
- Files: `.venv/`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe --version` — pass (Python 3.14.3).
- Decisions: Use the available Python 3.14 interpreter; all subsequent Python commands will use `.venv`.
- Next: Initialise git and add `.gitignore`.

### 2026-11-10  M0  Initialise repository
- Done: Initialised git and ignored the environment, real sample PDFs, caches, and build artifacts.
- Files: `.gitignore`, `PROGRESS.md`, `.git/`.
- Tests: `git check-ignore .venv sample_pdfs` — pass; both paths are ignored.
- Decisions: Track the existing specification and reference files in the first commit so later moves are visible in history.
- Next: Move the four prototype scripts into `prototype/` without editing them.

### 2026-11-10  M0  Archive prototype scripts
- Done: Moved all four prototype scripts to `prototype/` without changing their contents; left `pdf_metadata.py` in place.
- Files: `prototype/paper_renamer.py`, `prototype/test_apis.py`, `prototype/compare_sources.py`, `prototype/compare_pdf_libs.py`, `PROGRESS.md`.
- Tests: `git diff --cached --summary` — pass; git reports four 100% renames. `git diff -- pdf_metadata.py` — empty.
- Decisions: Keep prototype code solely as reference, as required by the specification.
- Next: Add `pyproject.toml` with the specified dependencies and entry points.

### 2026-11-10  M0  Add packaging metadata
- Done: Added a setuptools `src/` package configuration, specified runtime and optional dependencies, and declared CLI and GUI entry points.
- Files: `pyproject.toml`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -c "...tomllib assertions..."` — pass; parsed name, runtime dependencies, and extras.
- Decisions: Use setuptools, one of the two build backends allowed by SPEC section 2. Read the version from `papernym.__version__` as the single source.
- Next: Create the package skeleton and tests directory.

### 2026-11-10  M0  Create package skeleton
- Done: Added the `papernym`, `core`, `core.sources`, `gui`, and test package layout specified in SPEC section 3.
- Files: `src/papernym/`, `tests/__init__.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -c "...16 module imports..."` — pass; all skeleton modules import from `src/`.
- Decisions: Keep future modules as docstring stubs so M1–M5 implement and test each feature in milestone order. Set initial version in `papernym.__version__`.
- Next: Install the package in editable mode and add the first pytest smoke test.

### 2026-11-10  M0  Install and verify package
- Done: Installed PaperNym in editable mode into `.venv` with the dev extra, added the first smoke test, and completed M0.
- Files: `tests/test_smoke.py`, `PROGRESS.md`; installation artifacts stay inside ignored `.venv/`.
- Tests: `$env:PAPERNYM_HOME = Join-Path $env:TEMP ('papernym-m0-' + [guid]::NewGuid().ToString('N')); .\.venv\Scripts\python.exe -m pytest -q` — pass, 1 test.
- Decisions: Use a temporary `PAPERNYM_HOME` for the test run; the smoke test imports the installed package without network or sample PDFs.
- Next: Await the owner's instruction before starting M1 `core/config.py`.

### 2026-11-10  M1  Implement configuration
- Done: Added defaults, settings-path selection, validation, atomic JSON writes, and in-memory API-key environment overrides.
- Files: `src/papernym/core/config.py`, `tests/test_config.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_config.py` — 15 passed, with a temporary `PAPERNYM_HOME`.
- Decisions: Invalid settings raise `ConfigError` rather than silently resetting; API-key overrides are never written to disk.
- Next: Implement SQLite schema, queries, backup, and corrupt-database handling.

### 2026-11-10  M1  Implement SQLite storage
- Done: Added the specified schema, WAL and foreign-key settings, basic queries, atomic rename history writes, daily SQLite backup, and corruption recovery or clear failure.
- Files: `src/papernym/core/db.py`, `tests/test_db.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_db.py` — 4 passed with temporary databases. An initial failure exposed an open backup connection on Windows; fixed and reran successfully.
- Decisions: Use SQLite's backup API for a consistent backup; refuse an unreadable database when no valid backup exists.
- Next: Import the prototype state, history, and config on first run.

### 2026-11-10  M1  Migrate prototype data
- Done: Added first-run import of prototype state, history, and settings from the adjacent `PaperRenamer` folder, then renamed imported files to `.bak`.
- Files: `src/papernym/core/db.py`, `tests/test_db.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_db.py` — 7 passed, including both state formats and malformed input.
- Decisions: Use `title:<normalised title>` IDs for legacy records because the prototype state did not retain DOI IDs; preserve originals if parsing fails.
- Next: Implement the cross-platform single-writer lock.

### 2026-11-10  M1  Add single-writer lock
- Done: Added a nonblocking OS file lock with Windows and Linux paths, context-manager use, and reliable release.
- Files: `src/papernym/core/lock.py`, `tests/test_lock.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_lock.py` — 2 passed; a second process could not acquire a held lock.
- Decisions: Keep the lock file in the settings folder and let the OS release it if the process exits.
- Next: Implement naming tokens and field cleaning.

### 2026-11-10  M1  Add naming fields
- Done: Added the six token values, accent folding, HTML removal, separator handling, and a Unicode fallback for wholly non-Latin fields.
- Files: `src/papernym/core/naming.py`, `tests/test_naming.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_naming.py` — 3 passed.
- Decisions: Use the journal text provided by metadata sources; Crossref's short-container-title is already preferred by the source mapping.
- Next: Add the 15 fixed naming presets.

### 2026-11-10  M1  Add naming presets
- Done: Added all 15 fixed preset templates, including the concatenated citation key and space-based formats.
- Files: `src/papernym/core/naming.py`, `tests/test_naming.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_naming.py` — 18 passed, including one exact-name case per preset.
- Decisions: Store presets as immutable template/separator pairs in code; the length budget is the later M1 task.
- Next: Add custom templates and all validation rules.

### 2026-11-10  M1  Validate custom templates
- Done: Added custom token/fixed-text rendering, strict brace and character validation, the 60-character fixed-text limit, and collision warnings when no title token is present. Configuration now uses the same validator.
- Files: `src/papernym/core/naming.py`, `src/papernym/core/config.py`, `tests/test_naming.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_naming.py tests/test_config.py` — 48 passed.
- Decisions: Return a warning for valid templates without title tokens, while invalid templates raise `TemplateError` with a reason.
- Next: Enforce name and path budgets with whole-word title cuts.

### 2026-11-10  M1  Enforce filename budgets
- Done: Added whole-word title cutting, the 255-name limit, the Windows 259-character full-path limit, a six-character duplicate reserve, suffix accounting, and Linux UTF-8 byte accounting.
- Files: `src/papernym/core/naming.py`, `tests/test_naming.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_naming.py` — 37 passed, including deep-path and non-Latin cases.
- Decisions: Raise `NameBudgetError` when a folder path itself leaves no room for a PDF name; hard-cut overlong non-title fields as the specification requires.
- Next: Distinguish same-paper and different-paper name collisions.

### 2026-11-10  M1  Resolve collisions and complete milestone
- Done: Added collision-safe path selection: `_dupN` for another copy of the same paper, title extension for different papers, and `_b`, `_c` when no title extension fits. Strengthened recovery to reject backups without PaperNym's schema and corrected short titles containing HTML tags.
- Files: `src/papernym/core/naming.py`, `src/papernym/core/db.py`, `tests/test_naming.py`, `tests/test_db.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_naming.py` — 40 passed before the final audit; `$env:PAPERNYM_HOME = Join-Path $env:TEMP ('papernym-m1-full-' + [guid]::NewGuid().ToString('N')); .\.venv\Scripts\python.exe -m pytest -q` — 66 passed after the fixes. `git diff --check` — clean.
- Decisions: Check both existing filesystem paths and planned/database identities before choosing a name; treat untracked files as different papers so they can never be overwritten.
- Next: Await the owner's instruction before M2 PDF reading.

### 2026-11-10  M2  Extract PDF text and metadata
- Done: Added pypdfium2 extraction for the first two pages, page-1 lines with font size and rotation, standard and non-standard properties, and uncompressed XMP.
- Files: `src/papernym/core/pdfread.py`, `tests/pdf_factory.py`, `tests/test_pdfread.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_pdfread.py` — 2 passed, using generated PDFs in temporary folders.
- Decisions: Keep all PDF access in `pdfread.py`; generate fixtures with the standard library so tests use no additional package.
- Next: Derive title, author line, paperish status, and unreadable handling.

### 2026-11-10  M2  Derive PDF identification hints
- Done: Added page-layout title blocks, nearby author-line detection, metadata-title filtering, DOI and arXiv hints, `paperish`, and clear corrupt/password errors.
- Files: `src/papernym/core/pdfread.py`, `tests/test_pdfread.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_pdfread.py` — 6 passed on generated PDFs and a mocked password failure.
- Decisions: Raise `PdfReadError` for unreadable input so the later engine records the `unreadable` status once per unchanged file.
- Next: Implement service adapters and both-year metadata mapping.

### 2026-11-10  M2  Map scholarly sources
- Done: Added Crossref, doi.org, OpenAlex, Semantic Scholar, and arXiv adapters with citation and online year mapping, surname extraction, and service-specific request parameters.
- Files: `src/papernym/core/sources/`, `tests/test_sources.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_sources.py` — 4 passed with injected fake HTTP responses.
- Decisions: Keep adapters independent of transport; the shared HTTP layer supplies timeout, retries, and user-agent headers in the next task.
- Next: Implement the shared HTTP request layer.

### 2026-11-10  M2  Add shared HTTP transport
- Done: Added a 12-second timeout, one retry for connection errors/429/5xx, explicit rejected-key errors, not-found handling, and the PaperNym user agent.
- Files: `src/papernym/core/sources/http.py`, `tests/test_http.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_http.py` — 10 passed with fake sessions and no network.
- Decisions: Keep transport injectable so service and identification tests never make live requests.
- Next: Implement and verify DOI, arXiv, and title-search identification paths.

### 2026-11-10  M2  Identify papers online
- Done: Added ordered DOI, arXiv, and title lookup paths with title-in-text verification, author-on-page checks, and one warning per unavailable source per session.
- Files: `src/papernym/core/identify.py`, `tests/test_identify.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_identify.py` — 5 passed with fake source responses.
- Decisions: Reject a mismatched DOI immediately and continue with the next candidate; keep service failure counts for offline decisions.
- Next: Add paper-cache and 30-day miss-cache handling.

### 2026-11-10  M2  Cache papers and misses
- Done: Connected accepted records to SQLite and added a 30-day negative cache for DOI, arXiv, and title identifiers.
- Files: `src/papernym/core/identify.py`, `tests/test_identify.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_identify.py` — 7 passed with temporary databases.
- Decisions: Do not cache a miss when a service failed during that identifier's lookup; cached misses count as previously reached sources for later offline decisions.
- Next: Add outage outcomes and conservative PDF-only fallback.

### 2026-11-10  M2  Handle outages and offline metadata
- Done: Added `ok`, `unknown`, and `_CHECK` identification outcomes, attempt accounting, conservative author selection, and offline year priority.
- Files: `src/papernym/core/identify.py`, `tests/test_identify.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_identify.py` — 20 passed, including outage, author, and year cases.
- Decisions: Return explicit outcomes for the engine to record later; offline metadata stays marked `pdf-only` and is not put into the online cache.
- Next: Verify the title-search privacy setting.

### 2026-11-10  M2  Verify title-search privacy
- Done: Confirmed the disabled title-search setting sends no title query while DOI lookups continue.
- Files: `tests/test_identify.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_identify.py` — 21 passed.
- Decisions: Keep the switch in the identification pipeline so every caller inherits the same privacy behavior.
- Next: Verify the fixed regression cases in SPEC section 17.

### 2026-11-10  M2  Add fixed regression fixtures
- Done: Added network-free fixtures for the five DOI year/author cases, arXiv Vaswani, the Journal Pre-proof title trap, and the conflicting PDF-author fallback.
- Files: `tests/test_regression.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_regression.py` — 8 passed.
- Decisions: Keep the fixture responses in tests so CI passes without live services or copyrighted sample files; the next local check separately reads copies of the real PDFs.
- Next: Run `pdfread` on temporary copies of all sample PDFs and log each DOI and title guess.

### 2026-11-10  M2  Check sample copies and complete milestone
- Done: Copied all 11 sample PDFs to a temporary folder, read the copies, and recorded the first DOI and page-layout title guess. Added explicit failover tests for each DOI source.
- Files: `scripts/check_pdfread_samples.py`, `tests/test_identify.py`, `PROGRESS.md`; `sample_pdfs/` remained untouched.
- Tests: `.\.venv\Scripts\python.exe scripts\check_pdfread_samples.py` — 11/11 temporary copies read successfully with a temporary `PAPERNYM_HOME`. The first ad-hoc console run stopped while printing a Unicode symbol; the reusable script uses ASCII-safe JSON and completed. `$env:PAPERNYM_HOME = Join-Path $env:TEMP ('papernym-m2-full-' + [guid]::NewGuid().ToString('N')); .\.venv\Scripts\python.exe -m pytest -q` — 119 passed. `git diff --check` — clean.
- Local results (file — DOI — title guess):
  - `1-s2.0-S0001457517300842-main.pdf` — `10.1016/j.aap.2017.02.022` — Crash data quality for road safety research: Current state and future directions.
  - `1-s2.0-S0001457525001344-main.pdf` — `10.1016/j.aap.2025.108048` — Evaluating crash risk factors of farm equipment vehicles on county and non-county roads using interpretable tabular deep learning (TabNet).
  - `1-s2.0-S0957417426008080-main-2 (2).pdf` — `10.1016/j.eswa.2026.131895` — Supervised clustering using SOM for severity-based pattern detection in urban traffic crashes.
  - `1-s2.0-S0968090X25002256-main.pdf` — `10.1016/j.trc.2025.105221` — Dry bulk terminal operations: A critical review of models and optimization methods.
  - `1-s2.0-S0968090X25004322-main (1).pdf` — `10.1016/j.trc.2025.105428` — A review of knowledge graph construction using large language models in transportation: Problems, methods, and challenges (trailing star symbol in PDF text).
  - `1-s2.0-S0968090X2600255X-main.pdf` — `10.1016/j.trc.2026.105767` — A review of learning-based motion planning: toward a data-driven optimal control approach.
  - `1-s2.0-S0968090X26005735-main.pdf` — `10.1016/j.trc.2026.106087` — Short-term demand forecasting in mobility-on-demand systems: A systematic literature review and research agenda.
  - `1-s2.0-S2213665726000394-main.pdf` — `10.1016/j.amar.2026.100456` — Journal Pre-proof (embedded title correctly gives Understanding the determinants of multi-vehicle crash types at ramp terminals: insights from a partially constrained temporal modeling approach).
  - `97770f42-85cc-4285-b189-98a823efa6b1.pdf` — `10.1016/j.aap.2024.107801` — Uncertainty-aware probabilistic graph neural networks for road-level traffic crash prediction.
  - `islam-et-al-2026-crash-risk-analysis-of-non-motorists-using-interpretable-tabular-deep-learning.pdf` — `10.1177/03611981261468749` — Crash Risk Analysis of Non-Motorists (embedded title contains the rest of the title).
  - `mohammadi-et-al-2026-lidar-based-pavement-marking-detection-for-construction-engineering-a-systematic-review-of-methods.pdf` — `10.1061/jcemd4.coeng-18256` — LiDAR-Based Pavement Marking Detection for Construction Engineering: A Systematic Review of Methods and Applications.
- Decisions: Use the embedded title as a later title-search candidate when the page-layout guess is a cover label; always verify a title-search result against the printed first author.
- Next: Await the owner's instruction before M3 engine work.

### 2026-11-10  M3  Process one PDF
- Done: Added fingerprinting, file stability checks, per-file identification, safe target selection, transactional history recording, and the five database statuses.
- Files: `src/papernym/core/engine.py`, `tests/test_engine.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_engine.py` — 3 passed after correcting a test event-list helper.
- Decisions: Keep PDF extraction and identification injectable for offline tests; keep failed renames as `pending` with metadata for lookup-free retry.
- Next: Handle hand renames, moves, annotations, and copies.
