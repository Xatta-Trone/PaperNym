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

- **Current milestone:** M0
- **Next task:** move prototype scripts into `prototype/`
- **Last test run:** `git check-ignore .venv sample_pdfs` — both ignored (pass)
- **Open questions for the owner:** none

## Milestones

### M0 Project setup
- [x] Create `.venv` in the project root; confirm `python --version` is 3.10+
- [x] `git init`; `.gitignore` (`.venv`, `sample_pdfs/`, `__pycache__`, `build`, `dist`, `*.egg-info`)
- [ ] Move `paper_renamer.py`, `test_apis.py`, `compare_sources.py`, `compare_pdf_libs.py` into `prototype/` (read-only reference); leave `pdf_metadata.py` alone
- [ ] `pyproject.toml` (name `papernym`, deps `pypdfium2`, `requests`, `watchdog`; extra `gui = ["PySide6"]`; dev extra `pytest`)
- [ ] Package skeleton `src/papernym/` per SPEC section 3; `tests/`
- [ ] Editable install into `.venv`; `pytest` passes with one placeholder test

### M1 Core, part 1
- [ ] `core/config.py`: load, save (atomic), defaults, validation, env overrides
- [ ] `core/db.py`: schema, WAL, queries, daily backup, corrupt-database handling
- [ ] `core/db.py`: migration from the prototype's `state.json`, `history.csv`, `config.json`
- [ ] `core/lock.py`: single-writer lock (Windows and Linux)
- [ ] `core/naming.py`: tokens, field cleaning, non-Latin fallback
- [ ] `core/naming.py`: the 15 fixed presets (SPEC section 7)
- [ ] `core/naming.py`: custom templates with fixed text, and every validation rule
- [ ] `core/naming.py`: length budget (255 name, Windows 259 path), whole-word cut
- [ ] `core/naming.py`: collision rules (`_dupN` for the same paper, title extension for different papers)

### M2 Core, part 2
- [ ] `core/pdfread.py` on `pypdfium2`: text, lines with font size, rotation, properties, extra keys, XMP
- [ ] `core/pdfread.py`: title guess, author line, `paperish`, unreadable PDFs
- [ ] `core/sources/`: crossref, doiorg, openalex, semanticscholar, arxiv with field mapping (both years)
- [ ] Shared HTTP layer: timeout, retry, 401/403/429 handling, user agent
- [ ] `core/identify.py`: DOI, arXiv and title-search paths with verification
- [ ] `core/identify.py`: paper cache and `misses` table (no repeat lookups)
- [ ] `core/identify.py`: outage handling and the offline fallback rules
- [ ] `title_search` privacy switch honoured
- [ ] Regression table in SPEC section 17 passes
- [ ] Local check: `pdfread` on a copy of every file in `sample_pdfs/`; log the DOI and title guess found for each

### M3 Core, part 3
- [ ] `core/engine.py`: per-file logic and all five statuses
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
