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

- **Current milestone:** M6 built locally (exe, installer, release workflow); M5 manual checklist still open
- **Next task:** Owner: M5 checklist, push the repo to `Xatta-Trone/papernym`, choose a code-signing route; then the clean-account install test and the first tagged release
- **Last test run:** `.venv\Scripts\python.exe -m pytest -q` — 239 passed
- **Open questions for the owner:** code signing (Defender blocked an unsigned trial install that set start at login; see docs/BUILDING.md)

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
- [x] Hand-renamed, moved, annotated and copied files
- [x] Exclude list
- [x] Scan with progress events; prune
- [x] Dry run (scan and reformat)
- [x] Reformat, including `include_manual`
- [x] Undo by batch and by last N
- [x] Manual fix (by DOI, by edited fields) and refresh
- [x] `core/watcher.py`: events, queue, start-up scan
- [x] Watcher: settings reload, folder reconcile (unplugged drive), retry timer, pause
- [x] Folder rules: overlap, reference-manager warning
- [x] Every non-UI row of SPEC section 14 has a passing test

### M4 Minimal CLI
- [x] `cli.py`: settings commands (`add-folder`, `remove-folder`, `exclude`, `set-*`, `formats`, `show`)
- [x] `cli.py`: `scan`, `watch`, `reformat`, `undo`, `fix`, `status`
- [x] `cli.py`: `test-apis`, `compare`
- [x] Output prefixes, exit codes, lock behaviour
- [x] CLI tests
- [x] Local end-to-end check: real `scan` on a temporary copy of `sample_pdfs/` with `PAPERNYM_HOME` set to a temporary folder; log old and new names

### M5 Tray app (priority 1)
- [x] `papernym-gui` launches from source in `.venv` (editable install with the `gui` extra); options `--sandbox`, `--show`, `--debug`
- [x] App start, single instance, tray icon with states, tray menu
- [x] Worker thread running the watcher; core events delivered as Qt signals
- [x] Main window and Activity tab
- [x] Folders tab (with exclude list)
- [x] Naming tab: preset dropdown, Custom template editor, live preview, validation messages
- [x] "Apply to existing files?" flow with preview
- [x] Sources tab with Test buttons and the title-search switch
- [x] Needs attention tab with manual fix
- [x] History tab with undo and CSV export
- [x] General tab; notifications; outage and rejected-key banners
- [x] First-run welcome with dry-run confirmation
- [ ] Manual checklist for SPEC section 12 passes on Windows 11

### M6 Windows exe
- [x] `scripts/build_windows.py`: one command for the PyInstaller one-folder build (windowed, icon) into `dist/`
- [x] Locally built `PaperNym.exe` runs with `--sandbox --show`
- [x] Inno Setup installer (per-user, Start-menu shortcut, uninstaller), built by the same script
- [x] Start at login
- [x] Update check against the latest release
- [x] `THIRD_PARTY_LICENSES` file
- [ ] Install, run, uninstall on a clean Windows account (silent trial on the owner's account: install and uninstall verified; launching the installed copy was blocked by Defender, see the work log)
- [ ] GitHub Actions release workflow: on a `v*` tag, run tests, call the build script, attach the installer to a GitHub Release (written; not run yet because the repository is not on GitHub)
- [ ] Code signing (SPEC 15.1); the build signs when `SIGN_PFX` / `SIGN_PFX_BASE64` is provided

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

### 2026-11-10  M3  Respect file history and copies
- Done: Recognized moved and hand-renamed files by fingerprint, refreshed annotation fingerprints without lookup, and reused saved metadata for copies with `_dupN` names.
- Files: `src/papernym/core/engine.py`, `src/papernym/core/db.py`, `tests/test_engine.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_engine.py` — 5 passed; a test fixture initially used identical bytes for two distinct cases and was corrected.
- Decisions: Preserve `given_name` when a file moves so manual names remain protected; use an atomic database path relocation without adding a tool-rename history entry.
- Next: Apply exclude patterns before reading files.

### 2026-11-10  M3  Apply exclude list
- Done: Skipped configured filename globs and folder-name patterns before opening PDFs.
- Files: `src/papernym/core/engine.py`, `tests/test_engine.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_engine.py` — 6 passed; excluded temporary PDFs were never read or stored.
- Decisions: Match folder exclusions against path components and file exclusions against the basename.
- Next: Scan watched folders with progress events and prune missing file rows safely.

### 2026-11-10  M3  Scan and prune
- Done: Added configured-folder scans with start/progress/finish events, one batch per scan, and pruning only within reachable watched folders.
- Files: `src/papernym/core/engine.py`, `tests/test_engine.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_engine.py` — 7 passed; an unavailable folder's row survived pruning.
- Decisions: Finish processing the scan before pruning so moved files can be recognized first.
- Next: Add database-free dry runs for scan and reformat.

### 2026-11-10  M3  Preview scans and reformatting
- Done: Added dry-run scan and reformat paths with reserved target names and preview events, leaving PDFs, file rows, and history unchanged.
- Files: `src/papernym/core/engine.py`, `src/papernym/core/identify.py`, `tests/test_engine.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_engine.py` — 9 passed.
- Decisions: Identification can read the cache in preview mode while suppressing cache writes; previews reserve names so two files never show one target.
- Next: Complete saved-metadata reformatting and the manual-name option.

### 2026-11-10  M3  Reformat saved papers
- Done: Applied current naming settings to saved paper records, skipped hand-renamed files unless included, and added a one-time online-year refresh for older records.
- Files: `src/papernym/core/engine.py`, `src/papernym/core/identify.py`, `tests/test_engine.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_engine.py` — 11 passed.
- Decisions: Refresh a missing online year when the online year mode is requested; track that attempt in SQLite `meta` to avoid repeat lookups.
- Next: Add safe undo by batch and by last N history rows.

### 2026-11-10  M3  Undo safely
- Done: Added undo for the latest batch or last N history rows, skipped occupied or missing paths, and kept file rows and `undone` history flags consistent.
- Files: `src/papernym/core/engine.py`, `src/papernym/core/db.py`, `tests/test_engine.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_engine.py` — 13 passed.
- Decisions: An undone first rename retains the last tool-given name so the original name counts as user-chosen; undoing a reformat restores the earlier tool-given name.
- Next: Add manual DOI/field fixes and metadata refresh.

### 2026-11-10  M3  Fix and refresh metadata
- Done: Added DOI-only manual verification, edited-field fixes for attention files, and forced metadata refresh for known files while preserving names if lookup fails.
- Files: `src/papernym/core/engine.py`, `src/papernym/core/identify.py`, `tests/test_engine.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_engine.py tests/test_identify.py` — 40 passed. One test DOI initially violated the 4-digit registrant rule and was corrected.
- Decisions: Reject malformed manual DOIs and avoid renaming hand-chosen names during a metadata refresh.
- Next: Build the watcher event queue and startup scan.

### 2026-11-10  M3  Watch queued file events
- Done: Added watchdog created/moved event handling, a single queue worker, a startup scan, watch-triggered batches, and writer-lock ownership.
- Files: `src/papernym/core/watcher.py`, `tests/test_watcher.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_watcher.py` — 1 passed with a fake observer and temporary files.
- Decisions: Keep observer work on a queue so files are processed one at a time; each event receives its own undo batch.
- Next: Add periodic settings reload, folder reconciliation, retry timer, and pause.

### 2026-11-10  M3  Reconcile watcher state
- Done: Added ten-second settings reload and folder reconciliation, reattachment scans, thirty-minute retry passes, and pause/resume behavior.
- Files: `src/papernym/core/watcher.py`, `src/papernym/core/identify.py`, `tests/test_watcher.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_watcher.py` — 5 passed; an initial pause test exposed an in-memory config mutation and the watcher now tracks the prior pause state explicitly.
- Decisions: Keep the last valid settings and existing watches if a reload is malformed; leave database rows alone while a folder is unavailable.
- Next: Validate folder overlaps and warn about reference-manager storage.

### 2026-11-10  M3  Validate watched folders
- Done: Added shared folder-add logic that rejects paths already covered by a recursive watch, merges child watches into a new recursive parent, and warns about reference-manager stores.
- Files: `src/papernym/core/config.py`, `tests/test_config.py`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_config.py` — 17 passed.
- Decisions: Return a validated config copy from `add_folder`; leave the caller responsible for saving it and showing any warning.
- Next: Audit and test every non-UI edge case in SPEC section 14.

### 2026-11-10  M3  Audit edge cases and complete milestone
- Done: Added cross-module tests for same-DOI different PDFs, `_CHECK` correction, partial downloads, five-attempt limits, scanned-property DOI trust, non-paper PDFs, interrupted scans, naming changes, cache-free previews, and rollback after a database failure. Mapped all 32 SPEC section 14 rows to tests in `tests/EDGE_CASE_MATRIX.md`; GUI focus behavior in row 25 remains an M5 task.
- Files: `src/papernym/core/engine.py`, `tests/test_edge_cases.py`, `tests/EDGE_CASE_MATRIX.md`, `PROGRESS.md`.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/test_edge_cases.py` — 10 passed; `$env:PAPERNYM_HOME = Join-Path $env:TEMP ('papernym-m3-full-' + [guid]::NewGuid().ToString('N')); .\.venv\Scripts\python.exe -m pytest -q` — 151 passed. `git diff --check` — clean. `git diff --name-only -- prototype pdf_metadata.py` — empty; `git ls-files sample_pdfs` — empty.
- Decisions: Use an exclusive, same-folder move on Linux and the Windows no-replace rename path; restore the original file path if the database transaction fails after a physical rename.
- Next: Await the owner's instruction before M4 CLI work.

### 2026-11-10  Assets  Add app and tray icons
- Done: Inspected all six supplied icons. The app PNG is 1024×1024, the ICO has seven sizes from 16×16 through 256×256, both tray PNGs are 1568×960, and both SVGs parse with matching view boxes. Visually checked the PNGs and a Windows-decoded ICO frame. Removed six trailing-space lines from the tray SVG.
- Files: `assets/papernym-icon-1024.png`, `assets/papernym-icon.ico`, `assets/papernym-icon.svg`, `assets/papernym-tray-preview.png`, `assets/papernym-tray-sheet.png`, `assets/papernym-tray-sheet.svg`, `PROGRESS.md`.
- Tests: `$env:PAPERNYM_HOME = Join-Path $env:TEMP ('papernym-assets-test-' + [guid]::NewGuid().ToString('N')); .\.venv\Scripts\python.exe -m pytest -q` — 151 passed.
- Decisions: Keep the supplied source and rendered artwork together for later tray and installer work; no milestone checkbox changed.
- Next: Begin M4 CLI settings commands when the owner requests the next milestone.

### 2026-11-10  M4  CLI commands, tests, and local end-to-end check
- Done: Implemented every SPEC section 11 command in `cli.py` as a thin layer over config/engine/watcher: settings commands (`add-folder`, `remove-folder`, `exclude`, `set-key`, `set-email`, `formats`, `set-format` preset/custom, `set-title-length`, `set-year`, `set-title-search`, `show`); `scan`, `watch`, `reformat`, `undo`, `fix`, `status`; diagnostics `test-apis` and `compare`. Core events map to the `[ok] [check] [?] [busy] [skip] [warn] [preview] [undo]` prefixes with `->` between names; scans end with a `Summary:` line and say when no folders are configured. Exit codes: 0 success, 1 failure, 2 usage. Renaming commands take the writer lock and refuse with a clear message while the tray app or `watch` runs; dry runs, `status`, `show` and settings commands always work. Rename-type commands also write `logs/papernym.log` (rotating, 5 x 1 MB).
- Files: `src/papernym/cli.py`, `src/papernym/core/config.py`, `src/papernym/core/engine.py`, `tests/test_cli.py`, `tests/test_config.py`, `tests/test_engine.py`, `SPEC.md`, `PROGRESS.md`.
- Tests: `$env:PAPERNYM_HOME = <temp>; .\.venv\Scripts\python.exe -m pytest -q` — 184 passed (33 new: 30 CLI, 2 config, 1 engine). A first run exposed the log handler staying bound to the first settings folder; it now rebinds when the folder changes.
- Local end-to-end (live services, no API keys, `PAPERNYM_HOME` and the papers both in a temp folder, sample_pdfs/ only copied): `scan --dry-run` previewed 11/11; real `scan` renamed 11/11 (`Summary: 11 PDFs, 11 named`), none unidentified:
  - `1-s2.0-S0001457517300842-main.pdf` -> `2019_Imprialou_Crash_data_quality_for_road_safety_research_Current_state_and_future_directions.pdf`
  - `1-s2.0-S0001457525001344-main.pdf` -> `2025_Islam_Evaluating_crash_risk_factors_of_farm_equipment_vehicles_on_county_and_non-county_roads_using_interpretable_tabular_deep_learning_TabNet.pdf`
  - `1-s2.0-S0957417426008080-main-2 (2).pdf` -> `2026_Bermudez_Supervised_clustering_using_SOM_for_severity-based_pattern_detection_in_urban_traffic_crashes.pdf`
  - `1-s2.0-S0968090X25002256-main.pdf` -> `2025_Cao_Dry_bulk_terminal_operations_A_critical_review_of_models_and_optimization_methods.pdf`
  - `1-s2.0-S0968090X25004322-main (1).pdf` -> `2026_Ling_A_review_of_knowledge_graph_construction_using_large_language_models_in_transportation_Problems_methods_and_challenges.pdf`
  - `1-s2.0-S0968090X2600255X-main.pdf` -> `2026_Hu_A_review_of_learning-based_motion_planning_toward_a_data-driven_optimal_control_approach.pdf`
  - `1-s2.0-S0968090X26005735-main.pdf` -> `2027_Li_Short-term_demand_forecasting_in_mobility-on-demand_systems_A_systematic_literature_review_and_research_agenda.pdf`
  - `1-s2.0-S2213665726000394-main.pdf` -> `2026_Yan_Understanding_the_determinants_of_multi-vehicle_crash_types_at_ramp_terminals_insights_from_a_partially_constrained_temporal_modeling_approach.pdf`
  - `97770f42-85cc-4285-b189-98a823efa6b1.pdf` -> `2024_Gao_Uncertainty-aware_probabilistic_graph_neural_networks_for_road-level_traffic_crash_prediction.pdf`
  - `islam-et-al-2026-crash-risk-analysis-of-non-motorists-using-interpretable-tabular-deep-learning.pdf` -> `2026_Islam_Crash_Risk_Analysis_of_Non-Motorists_using_Interpretable_Tabular_Deep_Learning.pdf`
  - `mohammadi-et-al-2026-lidar-based-pavement-marking-detection-for-construction-engineering-a-systematic-review-of-methods.pdf` -> `2026_Mohammadi_LiDAR-Based_Pavement_Marking_Detection_for_Construction_Engineering_A_Systematic_Review_of_Methods_and_Applications.pdf`
  Then: `status` (11 named, nothing needs attention); `reformat --dry-run` with `authors_year_title_zotero` previewed 11 renames (e.g. `Islam et al - 2026 - Crash Risk Analysis ... .pdf`); `undo` restored all 11 original names; a re-scan left them alone (undone first-time renames count as hand-named, SPEC 9). `test-apis`: 8 PASS, 2 SKIP (no OpenAlex key), 0 FAIL. `watch` on an empty temp folder: a second `scan` was refused (exit 1) and `status` showed the watcher running; a sample copied in as `download.part` then renamed to `download.pdf` was renamed to `2024_Gao_Uncertainty-aware_...pdf` live.
- Decisions: (1) `format` in config.json may hold a preset name (`citekey` needs its own capitalisation, which a plain template cannot express); `set-format PRESET` stores the name. Recorded in SPEC section 4. (2) `load_config(apply_env=False)` for settings commands so `OPENALEX_API_KEY`/`S2_API_KEY` are never written to disk. (3) `stable_file` skips the 1.5 s two-check wait for files untouched for 30 s (scans of large existing libraries were 1.5 s per file); fresh downloads still get the full check. (4) `fix` follows the spec (`--doi` only); edited-field fixes stay a GUI feature. (5) `test-apis` reports unexpected values as FAIL, so its output is strictly PASS/FAIL/SKIP.
- Next: Await the owner's instruction to begin M5 (tray app).

### 2026-11-10  M4  Scan one folder on request (owner request)
- Done: Added `scan [FOLDER] [--no-subfolders]`. `papernym scan .` renames the PDFs in the current folder (and its subfolders) once, without adding it to the watched folders. `--dry-run` previews; the writer lock still applies. `--no-subfolders` without a FOLDER is a usage error (exit 2). Confirmed that `papernym add-folder .` already adds the current folder.
- Files: `src/papernym/cli.py`, `tests/test_cli.py`, `SPEC.md`, `PROGRESS.md`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` — 187 passed (3 new). Live: `scan . --dry-run` then `scan .` in a temp copy of sample_pdfs/ with a temp `PAPERNYM_HOME` named 11/11 files; `show` still listed no watched folders.
- Decisions: The owner chose to keep plain `papernym` printing help rather than scanning the current folder, so an accidental run never renames anything. Subfolders are included by default, as with `add-folder`. SPEC section 11 updated.
- Next: Await the owner's instruction to begin M5 (tray app).

### 2026-11-10  M4  Coloured output (owner request)
- Done: Coloured the output prefix on interactive terminals (ok green, check yellow, ? magenta, busy blue, skip grey, warn bold red, preview cyan, undo bright blue) and made `Summary:` lines bold. ANSI handling is switched on for the Windows console with `ctypes` (`SetConsoleMode`), so no new dependency. Colour is off when output is piped or redirected, when `NO_COLOR` is set, or with `--no-color` (accepted before or after the command). The log file stays plain.
- Files: `src/papernym/cli.py`, `tests/test_cli.py`, `SPEC.md`, `PROGRESS.md`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` — 189 passed (2 new). Manual: dry run, scan, `undo --last 2`, a bad folder and a `--no-color` dry run in a Windows PowerShell terminal tab, with a temp `PAPERNYM_HOME` and a temp copy of sample_pdfs/; no stray escape codes appeared.
- Note: the owner ran `papernym scan .` from `F:\papernym` (with the trial `PAPERNYM_HOME`), which renamed the files inside `sample_pdfs/`. They were restored afterwards; `sample_pdfs/` again holds the 11 original names, and no real `%APPDATA%\PaperNym` folder exists.
- Next: Await the owner's instruction to begin M5 (tray app).

### 2026-11-10  M5  Tray application
- Done: Built the PySide6 tray app, runnable from source with `papernym-gui [--sandbox] [--show] [--debug]` (same as `python -m papernym.gui`). A worker `QThread` owns the database, engine and watcher; the UI sends it jobs and receives core events and results as Qt signals, so the UI thread never touches PaperNym files or the network. Tray icon with five states (watching, paused, working animated during a scan, attention, error) plus a text tooltip; the SPEC menu (Open, Pause/Resume, Scan now, Recent renames, Undo last rename, Needs attention (N), Settings, Quit). Single instance through a per-settings-folder `QLocalServer`; a second launch brings the window forward. Main window with Activity, Needs attention, Folders, Naming, Sources, History, General tabs; outage and rejected-key banners; batched notifications; first-run welcome (folders, format with preview, optional OpenAlex key) followed by a dry-run preview with checkboxes; "Apply to N existing files?" with a hand-renamed checkbox after naming changes; add-folder flow with PDF count, reference-manager warning and Preview first. Start at login writes the HKCU Run key (or a Linux autostart file); disabled in sandbox. Tray icons were cropped from the supplied sheet by `scripts/make_tray_icons.py` into `src/papernym/gui/icons/` (package data).
- Core changes: `Engine.keep_name` (Ignore and unticked preview files: recorded as hand-named), `Engine.undo_ids` / `undo_path` (undo a History row, a batch, or an Activity row), `core/apitest.py` (shared by `papernym test-apis` and the Sources tab), `core/logsetup.py` (shared log file), `core/autostart.py`, `config.with_env`. Fixed an engine bug: names planned during a dry run were kept afterwards, so a later real rename in the same process got `_dup` endings; `scan` and `reformat` now clear plans when they finish (regression test added). The CLI never hit it because each command is a new process.
- Files: `src/papernym/gui/{app,worker,window,tabs,dialogs,common}.py`, `src/papernym/gui/icons/*`, `src/papernym/core/{engine,config,apitest,logsetup,autostart}.py`, `src/papernym/cli.py`, `scripts/make_tray_icons.py`, `pyproject.toml`, `tests/test_gui.py`, `tests/test_engine.py`, `tests/EDGE_CASE_MATRIX.md`, `docs/M5_MANUAL_CHECKLIST.md`, `SPEC.md`, `PROGRESS.md`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` — 205 passed (16 new: 15 GUI with offscreen Qt, fake HTTP and a fake observer; 1 engine). Offscreen walkthrough with the real sample copies and live services: sandbox first run -> welcome (format author_year_title) -> preview of 11 with one unticked -> 10 renamed as `Author_Year_Title`, the unticked file kept; tab screenshots checked for layout. Real launch: `papernym-gui --sandbox --show --debug` started, the window titled `PaperNym  [SANDBOX]`, debug log printed in the launching terminal.
- Problems found and fixed during the walkthrough: History showed live batches as "all undone" (Qt returned a copy of the stored id list); the first-run preview and renames used the old default format instead of the chosen one (the preview and the confirmed renames now run with the candidate settings, all in one worker job so the watcher cannot scan in between); `--debug` printed nothing because pip's windowed launcher has no console (it now attaches to the nearest ancestor console, else opens one); Activity rows wrapped onto two lines.
- Decisions: Ignore uses the existing `ok` status with no paper rather than a new status (recorded in SPEC section 12). "Check for updates" is shown disabled until the M6 release exists. "Get a free key" links to `https://openalex.org/settings/api` (not verified live). Start at login is implemented now (M6 keeps its own checkbox for the installed exe path).
- Not done: the manual checklist (`docs/M5_MANUAL_CHECKLIST.md`) needs the owner on Windows 11: real tray icon and menu, toasts, Explorer selection, keyboard pass.
- Next: Owner runs the checklist; fix anything found; then M6.

### 2026-11-11  M5  Owner feedback: Activity actions, paging, search, toasts, login
- Done: Activity and Needs attention now use a shared `PagedTable` (`src/papernym/gui/table.py`): a model/view table with a search box, status filter, 200 rows per page and First/Previous/Next/Last with "1-200 of N (filtered from M)". Activity keeps the newest 20,000 rows; the app loads 5,000 history rows at start. Activity buttons are disabled until a row is selected (with a hint), each action reports in the status bar (including "no longer there" for moved files), and rows also have a right-click menu and double-click/Enter to open. Rename notifications are batched into one toast (end of scan, after 4 s of quiet, or every 20 s). Sources labels no longer show a literal `&` (real buddy labels). The welcome step 3 offers "Start PaperNym when I log in", ticked by default (not in sandbox), and each normal start re-syncs the Run key.
- Cause of "buttons not working": no row was selected (the screenshot shows only a hovered cell), and the actions returned silently.
- Files: `src/papernym/gui/{table,tabs,app,dialogs}.py`, `tests/test_gui.py`, `SPEC.md`, `PROGRESS.md`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` — 209 passed (4 new: paging/search/filter over 1,234 rows, Activity buttons end to end on a real renamed file, Sources labels, welcome login choice; 3 updated).
- Not done: the owner's manual checklist on Windows 11.

### 2026-11-11  M5  Owner feedback: one sandbox, add folder first, icon-colour theme
- Done: Two tray icons came from two sandbox launches: each sandbox has a new temporary settings folder, so the per-folder instance name never matched. `--sandbox` now uses one fixed instance name, checked before the sandbox folder is created (a real launch confirmed the second exits and the first stays). Adding a folder no longer looks anything up first: **Add** saves it and starts at once; **Add and preview** saves it held (the watcher attaches but skips scans, events and retries there) while the dry run runs, then confirm renames the ticked files and releases it, or closing removes it again. New theme (`gui/theme.py`): icon teal and amber, light and dark palettes on Fusion, `theme` setting (`system`/`light`/`dark`) on the General tab, applied live; System follows the OS scheme change. Tables use alternating rows instead of grid lines.
- Files: `src/papernym/gui/{theme,app,worker,tabs,table,window}.py`, `src/papernym/core/{watcher,config}.py`, `tests/test_gui.py`, `SPEC.md`, `docs/M5_MANUAL_CHECKLIST.md`, `PROGRESS.md`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` — 214 passed (5 new: held folder waits for its preview, closing the preview removes the folder, second sandbox launch, theme switch, theme validation). Offscreen screenshots of Activity and General checked in both themes.
- Problem found: restyling the application on every new Controller crashed Qt in the test run (access violation while repolishing); the theme is now applied only when light/dark actually changes.

### 2026-11-11  M5  Owner feedback: re-added originals, light theme polish
- Cause: after the owner deleted the renamed files and pasted the original downloads back, PaperNym saw known content whose named file was gone and applied rule 5 (moved or hand-renamed: keep the user's name), silently. Both the watcher and Scan now skipped them. Rule 5 now has an exception: when the new name is exactly the name PaperNym renamed that file from, the old row is dropped and the file is renamed again from the saved record (no web call). Genuine moves and hand renames are still respected and now show a "your name is kept" line in Activity.
- Theme: the active tab is teal with white text in both modes; checkboxes (including the Folders list) show a white tick on teal; combo boxes have a chevron arrow and themed list; progress text is readable (light teal bar with dark text in light mode); spin boxes keep the native style. SVG assets added to `src/papernym/gui/icons/` and package data.
- Files: `src/papernym/core/engine.py`, `src/papernym/gui/theme.py`, `src/papernym/gui/icons/*.svg`, `pyproject.toml`, `tests/test_engine.py`, `SPEC.md`, `PROGRESS.md`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` — 215 passed (1 new engine test). Offscreen screenshots of Activity, Folders, Naming and General checked in light and dark.
- Note: a sandbox that already skipped the pasted originals keeps them as hand-named; start a new sandbox to retry.

### 2026-11-11  M5  Owner request: keys in the credential store, About tab, update check
- Done: API keys moved out of config.json into the system credential store through `keyring` (`core/keystore.py`): Windows Credential Manager, Linux Secret Service (GNOME Keyring / KWallet / KeePassXC), macOS Keychain. Headless Linux or `PAPERNYM_KEYRING=off` keeps them in config.json with mode 600 and a CLI warning; environment variables still win and are never stored; existing plain-text keys migrate on load; a non-default settings folder uses its own entry name; `--sandbox` never touches the real store. Keys are masked in request errors and logs, and the Sources fields hide them unless edited. General no longer shows the settings folder (path, Open settings folder, Open log) unless `--debug`; Save diagnostics writes a masked log copy instead. New About tab (Ctrl+8, tray "About PaperNym"): version, description, developer link (github.com/Xatta-Trone), project, issues, MIT licence, data credits, update status. Update check (`core/updates.py`) as agreed with the owner: GitHub releases API, 30 s after start then daily, background thread, banner with Download / Skip this version, tray item, no automatic download. MIT `LICENSE`; project URLs, licence and the `keyring` dependency in `pyproject.toml`. Links follow the theme colour (`LinkLabel`).
- Checked for real: a save, read and delete round trip against Windows Credential Manager with a temporary settings folder (entry `PaperNym-<hash>`, removed afterwards; `cmdkey /list` shows no PaperNym entries).
- Files: `src/papernym/core/{keystore,updates,config}.py`, `src/papernym/core/sources/http.py`, `src/papernym/cli.py`, `src/papernym/gui/{app,tabs,window,common,dialogs}.py`, `tests/conftest.py` (in-memory keyring for every test), `tests/test_updates.py`, `tests/{test_gui,test_cli,test_config,test_http}.py`, `LICENSE`, `pyproject.toml`, `SPEC.md`, `docs/M5_MANUAL_CHECKLIST.md`, `PROGRESS.md`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` — 233 passed (18 new). Offscreen screenshots of About and Sources checked in light and dark.
- Note: the repository has no git remote yet; the update check answers that no release has been published until `Xatta-Trone/papernym` has one.

### 2026-11-11  M5  Owner request: open folders by double-click, no title length
- Done: Folders tab: double-clicking a folder row opens it in Explorer (not on the Subfolders checkbox column; an unreachable folder gets a status message). Title length removed everywhere: the Naming tab control, the CLI `set-title-length` command and the `show` line, and the `title_limit` setting. Titles are always as long as the file-name budget allows. Old `config.json` files with `title_limit` load normally and the key is dropped on the next save.
- Files: `src/papernym/core/{config,engine}.py`, `src/papernym/cli.py`, `src/papernym/gui/tabs.py`, `tests/{test_cli,test_config,test_gui}.py`, `SPEC.md`, `PROGRESS.md`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` — 233 passed (3 new; 3 title-length cases removed with the setting).

### 2026-11-11  Docs  Move Markdown files into docs/
- Done: `SPEC.md`, `PROGRESS.md` and `SYSTEM_REQUIREMENTS.md` moved from the repository root to `docs/` (git history kept with `git mv`). No code referred to them. Read `docs/PROGRESS.md` first in each session.

### 2026-11-11  M6  Windows exe, installer and release workflow
- Done: `scripts/build_windows.py` (one command): writes Windows version info, runs PyInstaller with `packaging/papernym.spec`, checks both programs exist, copies `LICENSE.txt`, generates `THIRD_PARTY_LICENSES.txt` from the bundled packages' metadata, smoke-tests the CLI against a temporary settings folder, signs if `SIGN_PFX` is set, then runs Inno Setup (`packaging/papernym.iss`) and writes a SHA256 file. One folder holds two programs: `PaperNym.exe` (windowed) and `papernym-cli.exe` (console). Windows names are case-insensitive, so `papernym.exe` would collide with `PaperNym.exe`; the installer adds `bin\papernym.cmd` to PATH instead. Installer: per-user (`%LOCALAPPDATA%\Programs\PaperNym`, no admin), Start-menu shortcut, optional desktop icon, Start at login (Run key plus a one-time `HKCU\Software\PaperNym\InstallerStartAtLogin` marker that the app adopts into its settings, so its own sync does not undo the choice), Add to PATH, launch after install; the uninstaller stops the app, removes the Run value (also when the app set it), PATH entry and shortcuts, and asks before removing settings, history and keys (default No). `.github/workflows/windows-release.yml`, modelled on the owner's avista-dl-desktop workflow: `v*` tag or manual run, tag must equal `__version__`, tests, `choco install innosetup`, optional signing from secrets, the same build script, artifact upload, `gh release create/upload --clobber`. `pyproject.toml` gains a `build` extra (`pyinstaller`). The sandbox finds sample papers through `PAPERNYM_SAMPLES` or `./sample_pdfs` when frozen. `docs/BUILDING.md` explains build, installer and release.
- Problems found and fixed: (1) the packaged GUI failed with "DLL load failed while importing QtCore": PyInstaller had bundled Anaconda's `icuuc.dll` (ICU 73), found through the user PATH, which shadowed the Windows one; the build now runs PyInstaller with a clean PATH and the spec drops stray ICU DLLs. (2) `keyring`'s Windows backend needed all of `win32ctypes` bundled. (3) Unused Qt parts (software OpenGL, virtual keyboard with Qt Quick/QML, Qt PDF, translations) dropped: 174 MB to 89 MB; installer 30 MB.
- Checked for real: the packaged CLI renamed 3 sample copies with live lookups (temporary home, keyring off) and found Windows Credential Manager when allowed; the packaged GUI started in sandbox mode with a clean log. Silent trial install (owner approved) into `%TEMP%\PaperNym-trial-install` with Start at login and PATH: files, `papernym` shim (exit codes pass through), Run value, marker, shortcut all present; silent uninstall removed folder, Run value, `HKCU\Software\PaperNym`, the PATH entry (PATH identical to before) and the shortcut, and kept the settings folder.
- Problem not solved: Microsoft Defender blocked starting the installed copy: `Behavior:Win32/Persistence.A!ml` (an unsigned new exe under `%TEMP%` registering itself at login). `dist\PaperNym\PaperNym.exe` still runs. Code signing is the real fix (SPEC 15.1 already requires it); `docs/BUILDING.md` lists options. Not retried, to avoid further alerts on the owner's machine.
- Files: `scripts/build_windows.py`, `packaging/{papernym.spec,papernym.iss,papernym.cmd,launch_gui.py,launch_cli.py}`, `.github/workflows/windows-release.yml`, `src/papernym/core/autostart.py`, `src/papernym/gui/{app,dialogs}.py`, `tests/test_build_script.py`, `tests/test_gui.py`, `pyproject.toml`, `docs/BUILDING.md`, `docs/SPEC.md`, `docs/PROGRESS.md`. Inno Setup 6.7.3 installed for the owner's user with winget (approved).
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` — 239 passed (6 new).
- Next: owner pushes to GitHub and picks a signing route; tag `v0.1.0` to run the workflow; clean-account install test with a signed build.

