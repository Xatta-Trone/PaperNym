# PaperNym: System Requirements

PaperNym watches folders and renames paper PDFs from their metadata, for example
`1-s2.0-S0001457525001344-main.pdf` to `2025_Islam_Evaluating_crash_risk_factors_....pdf`.

Status key: **Built** = in the current prototype scripts, **Planned** = specified in
`SPEC.md` but not yet coded.

## 1. Platform

| Item | Requirement |
|---|---|
| Operating system | Windows 10/11 (priority 1), Linux (priority 3). macOS is out of scope for version 1 |
| Language | Python 3.10 or newer (developed on 3.13) |
| Internet | Needed for metadata lookups. Without it, papers are tagged `_CHECK` and retried later |
| Disk | Under 100 MB for Python packages; the database is a few MB per thousand papers |

One language throughout: the core, the command line and the tray app are all Python.

## 2. Python packages

Install with `pip install pypdfium2 requests watchdog`.

| Package | Minimum | Tested | Used for | License |
|---|---|---|---|---|
| `pypdfium2` | 4.30 | 5.13 | Reading PDF text, font sizes and embedded metadata | Apache-2.0 / BSD-3 |
| `requests` | 2.28 | 2.34 | Calls to the metadata services | Apache-2.0 |
| `watchdog` | 3.0 | 6.0 | Detecting new files in watched folders | Apache-2.0 |
| `PySide6` (tray app only) | 6.5 | not yet | Tray icon and windows | LGPL-3.0 |

Build and test tools: `pytest`, `pyinstaller`, Inno Setup (Windows installer).

From the Python standard library (nothing to install): `sqlite3`, `argparse`, `pathlib`,
`hashlib`, `json`, `csv`, `difflib`, `re`, `unicodedata`, `threading`, `queue`,
`xml.etree`, and `msvcrt` (Windows) or `fcntl` (Linux) for the single-instance lock.

### Why pypdfium2

Chosen by test against PyMuPDF on 12 real publisher and arXiv PDFs:

| Library | License | Same identifier as PyMuPDF | Same title guess | Time for 12 files |
|---|---|---|---|---|
| PyMuPDF (reference) | AGPL-3.0 | - | - | 0.4 s |
| **pypdfium2** | Apache-2.0 / BSD-3 | all | all but one, and that one was better | 0.5 s |
| pdfminer.six | MIT | all | all but one, and that one was better | 5.6 s |
| pypdf | BSD-3 | all | half; it drops the spaces between words | 3.3 s |

PyMuPDF is not used in the product: its AGPL license would prevent an MIT release.
The prototype scripts still use it and are for personal use only.

## 3. Metadata services

All are free. Only OpenAlex needs an account.

| Service | Key | Used for | Order |
|---|---|---|---|
| Crossref | None (an email address is optional and gives the polite pool) | DOI lookup, title search | 1 |
| doi.org content negotiation | None | DOI lookup, including DataCite DOIs | 2 |
| OpenAlex | Free key from openalex.org/settings/api | DOI lookup, title search | 3 |
| Semantic Scholar | None (a free key is optional and avoids shared rate limits) | DOI, arXiv ID, title search | 4 |
| arXiv API | None | arXiv ID lookup | First for arXiv papers |

Not used: Scopus (requires an institutional subscription).

## 4. Storage

Everything lives in one per-user settings folder:

| System | Folder |
|---|---|
| Windows | `%APPDATA%\PaperNym` |
| Linux | `~/.config/PaperNym` |

| File | Format | Holds | Status |
|---|---|---|---|
| `config.json` | JSON | Watched folders, exclude list, name format, year mode, title length, API keys, email | Built (prototype) |
| `papers.db` | SQLite | Tables `papers`, `files`, `history`, `misses` | Planned |
| `lock` | Lock file | Prevents two instances changing files at once | Built (prototype) |
| `logs/papernym.log` | Text, rotating | Diagnostics | Planned |

The prototype keeps `state.json` and `history.csv` in a folder named `PaperRenamer`;
PaperNym imports them on first run.

Overrides: `PAPERNYM_HOME` moves the settings folder; `OPENALEX_API_KEY` supplies the key
without storing it in `config.json`.

## 5. Deliverables

| Deliverable | Form | Command or entry |
|---|---|---|
| 1. Tray application | Windows installer built with PyInstaller + Inno Setup | Starts in the system tray; optional start at login |
| 2. Command-line tool | PyPI package `papernym` | `papernym` (also `python -m papernym`) |
| 3. Linux | Same PyPI package; tray app through `pip install "papernym[gui]"` | Tested in CI on Ubuntu |

Both share one core library, one settings folder and one database.

## 6. Prototype files (reference only)

| File | Purpose |
|---|---|
| `paper_renamer.py` | Working prototype of the engine and command line |
| `test_apis.py` | Checks that each metadata service is reachable |
| `compare_sources.py` | Shows what each service returns for every PDF in a folder |
| `compare_pdf_libs.py` | The PDF-library comparison; contains the working `pypdfium2` reader to port |

## 7. Development setup

- A virtual environment `.venv` in the project root; everything runs through it.
- `PROGRESS.md` holds the milestone checklist and the work log; it is read at the start of
  every work session.
- Tests with `pytest`; no network and no real user files in tests.

## 8. Constraints to know

- **License.** The product can be MIT: every runtime dependency is permissive. PySide6 is
  LGPL, which is compatible when Qt is shipped as separate files (PyInstaller one-folder
  mode) with its license notices. Do not add PyMuPDF or any other copyleft dependency.
- **Code signing.** An unsigned Windows installer triggers SmartScreen warnings; signing
  needs a paid certificate.
- **File name length.** Names are kept within 255 characters, and on Windows within the
  260-character full-path limit.
- **Scanned PDFs.** Files with no text layer are not identified (no OCR).
- **Reference-manager folders.** Do not watch Zotero, Mendeley or EndNote storage folders;
  renaming files there breaks their links.
- **Testing so far.** Prototype logic tested on Linux with simulated services and run for
  real on Windows 11.
