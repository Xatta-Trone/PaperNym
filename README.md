<p align="center">
  <img src="assets/papernym-icon-1024.png" alt="PaperNym icon" width="112">
</p>

<h1 align="center">PaperNym</h1>

<p align="center">
  <b>Your research papers, named properly — automatically.</b><br>
  PaperNym watches your folders and renames academic PDFs from their real publication metadata.
</p>

<p align="center">
  <a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/licence-MIT-0B5563"></a>
  <img alt="Windows 10 and 11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0B5563">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-FFB020">
</p>

```text
1-s2.0-S0001457525001344-main.pdf
  ->  2025_Islam_Evaluating_crash_risk_factors_of_farm_equipment_vehicles_on_county_and_non-county_roads.pdf
```

Publisher downloads arrive with names like `1-s2.0-S0001457525001344-main.pdf`,
`nihms-1234567.pdf` or `2403.01234v2.pdf`. PaperNym finds each paper's DOI or arXiv ID,
looks it up in free scholarly databases, checks that the record really belongs to the PDF,
and gives the file a name you can read, sort and search.

## Contents

- [Features](#features)
- [Install](#install)
- [Getting started](#getting-started)
- [Name formats](#name-formats)
- [How a paper is identified](#how-a-paper-is-identified)
- [Safety](#safety)
- [Privacy](#privacy)
- [API keys](#api-keys)
- [Command-line reference](#command-line-reference)
- [Settings and data](#settings-and-data)
- [Uninstall](#uninstall)
- [Development](#development)
- [Roadmap](#roadmap)
- [Licence and credits](#licence-and-credits)

## Features

- **Hands-off.** Lives in the system tray and renames new PDFs as soon as they land in a
  watched folder, such as Downloads or your papers folder.
- **Accurate.** Uses Crossref, doi.org, OpenAlex, Semantic Scholar and arXiv, and verifies
  every result against the PDF's own text. A file is left alone rather than given a wrong name.
- **Works offline.** When no service can be reached, papers are named from the PDF alone,
  marked `_CHECK`, and fixed automatically once the services are back.
- **Your names win.** A file you rename by hand is never renamed again.
- **Undo anything.** Every rename is recorded; undo the last one, a whole batch, or any
  rename from History.
- **15 name formats, or your own.** Year–author–title, citekeys, Zotero style, or a custom
  template with your own text, with a live preview.
- **Preview first.** Dry runs show `old -> new` with checkboxes before anything is renamed.
- **Each paper is looked up once.** Lookups are cached, and copies of a known paper are named
  without a web call.
- **Tray app and command line.** One install gives you both, sharing the same settings and
  history.
- **Light and dark themes**, a keyboard-friendly interface, batched notifications, and
  Start at login.

## Install

### Windows (recommended)

1. Download `PaperNym-Setup-<version>.exe` from the
   [latest release](https://github.com/Xatta-Trone/papernym/releases/latest).
2. Run it. It installs for your user account only (no administrator rights) into
   `%LOCALAPPDATA%\Programs\PaperNym`.
3. PaperNym opens and walks you through choosing folders and a name format.

> [!NOTE]
> The installer is not code-signed yet, so Windows SmartScreen may say
> "Windows protected your PC". Choose **More info → Run anyway**. You can check the
> download against the `.sha256` file published with each release:
> `certutil -hashfile PaperNym-Setup-<version>.exe SHA256`

The installer always includes the command line. It adds `papernym` to your user `PATH`
(open a new terminal afterwards) and registers both programs with Windows. You can also
choose **Start PaperNym when I log in** and a desktop shortcut.

Requirements: Windows 10 or 11 (64-bit) and an internet connection for lookups.

### From source (any platform with Python 3.10+)

```bash
git clone https://github.com/Xatta-Trone/papernym.git
cd papernym
python -m venv .venv
.venv\Scripts\activate            # Linux: source .venv/bin/activate
pip install -e ".[gui]"           # drop [gui] for the command line only
```

This gives you `papernym` (command line) and `papernym-gui` (tray app). A PyPI package and
tested Linux support are on the [roadmap](#roadmap).

## Getting started

### Tray app

On first start a short welcome asks for:

1. **Folders to watch**, with or without subfolders.
2. **A name format**, with a preview on sample papers.
3. **An optional OpenAlex key** and whether to start at login.

PaperNym then shows a dry run of the PDFs already in those folders. Untick anything you
want to keep as it is, then confirm. From then on new PDFs are renamed as they arrive.

The main window, opened from the tray icon, has these tabs:

| Tab | What it is for |
|---|---|
| Activity | Live list of renames with search, filters and paging; open, show in folder, undo, refresh |
| Needs attention | Papers that could not be identified: enter a DOI, edit the details, retry, or ignore |
| Folders | Watched folders, subfolder switch, exclude patterns; double-click a row to open it |
| Naming | Preset or custom format, year mode, live preview; can re-apply to earlier renames |
| Sources | API keys, contact email, the title-search switch, and a test of every service |
| History | Every rename, grouped by batch, with undo and CSV export |
| General | Start at login, notifications, theme, diagnostics |
| About | Version, links and the update check |

Closing the window keeps PaperNym running in the tray; use **Quit** in the tray menu to exit.

### Command line

```bash
papernym scan . --dry-run          # preview names for the PDFs in this folder
papernym scan .                    # rename them (one pass; the folder is not watched)
```

To watch folders:

```bash
papernym add-folder "D:\Papers"
papernym set-format year_author_title
papernym scan --dry-run
papernym watch                     # scan, then keep watching until Ctrl+C
```

If a batch is not what you wanted:

```bash
papernym undo
```

## Name formats

Pick one of the fixed presets (`papernym formats` lists them all with examples):

| Preset | Example |
|---|---|
| `year_author_title` (default) | `2025_Smith_Deep_learning_for_crash_severity.pdf` |
| `author_year_title` | `Smith_2025_Deep_learning_for_crash_severity.pdf` |
| `year_authors_title` | `2025_Smith_et_al_Deep_learning_for_crash_severity.pdf` |
| `authors_year_title` | `Smith_et_al_2025_Deep_learning_for_crash_severity.pdf` |
| `year_author_shorttitle` | `2025_Smith_Deep_learning_for_crash_severity_prediction.pdf` |
| `author_year_shorttitle` | `Smith_2025_Deep_learning_for_crash_severity_prediction.pdf` |
| `year_author_journal_title` | `2025_Smith_Accid_Anal_Prev_Deep_learning.pdf` |
| `author_year_journal` | `Smith_2025_Accid_Anal_Prev.pdf` |
| `title_author_year` | `Deep_learning_for_crash_severity_Smith_2025.pdf` |
| `title_only` | `Deep_learning_for_crash_severity.pdf` |
| `author_year` | `Smith_2025.pdf` |
| `citekey` | `Smith2025DeepLearningForCrashSeverityPrediction.pdf` |
| `author_year_title_spaces` | `Smith (2025) Deep learning for crash severity.pdf` |
| `authors_year_title_spaces` | `Smith et al (2025) Deep learning for crash severity.pdf` |
| `authors_year_title_zotero` | `Smith et al - 2025 - Deep learning for crash severity.pdf` |

Or write a **custom template** from the tokens `{year}` `{author}` `{authors}` `{title}`
`{shorttitle}` `{journal}` plus your own text:

```bash
papernym set-format --custom "[{journal}] {author} {year} - {shorttitle}" --word-sep " "
```

Notes:

- Titles are kept as long as the file name allows. That includes Windows' full-path limit,
  so names never break in deep folders.
- Accents are folded to plain letters (`Bermúdez` → `Bermudez`). Titles in non-Latin
  scripts are kept as they are.
- **Year mode:** `citation` (default) uses the year the publisher cites; `online` uses the
  first online date. Set it with `papernym set-year`.
- Existing files are never overwritten. If two different papers would get the same name,
  the title is lengthened until the names differ, or `_b`, `_c` is added. A second copy of
  the same paper gets `_dup2`.

## How a paper is identified

1. **DOI.** DOIs from the PDF's properties and text are tried in order. Each is looked up
   in Crossref, doi.org, OpenAlex and Semantic Scholar until one answers. The returned title
   must match the PDF's text; a DOI that belongs to a cited reference is rejected.
2. **arXiv ID.** From the text or the file name, looked up in arXiv and Semantic Scholar.
3. **Title search.** Optional and on by default; see [Privacy](#privacy). A result is
   accepted only if the title matches closely *and* the first author's surname is printed
   on page 1.
4. **Nothing found.** The file is left untouched and listed under Needs attention, where
   you can enter the DOI yourself.

Files that are clearly not papers, such as invoices, slides and forms, are left alone.

## Safety

- Files are only ever **renamed in place**. They are never moved, overwritten, edited or
  deleted.
- Every rename is recorded in History before it counts, and it can be undone.
- A name you give a file by hand is respected from then on.
- Files that are still downloading are waited for; files open in another program are
  retried later.
- The tray app and the command line never rename at the same time. While the tray app is
  running, the command line's renaming commands politely refuse.

## Privacy

PaperNym has no account, no analytics and no telemetry. The only things that leave your
computer are:

| Sent | To | When |
|---|---|---|
| DOIs and arXiv IDs found in your PDFs | Crossref, doi.org, OpenAlex, Semantic Scholar, arXiv | Every lookup |
| Paper titles | Crossref, OpenAlex, Semantic Scholar | Only while **Search by title** is on (`papernym set-title-search off` to stop) |
| Your email address | Crossref, as its "polite pool" contact | Only if you set one |
| Version number | GitHub, to check for a newer release | Once a day; can be turned off under About |

File contents and file names are never sent.

## API keys

All keys are optional. PaperNym works without any.

| Service | Why add a key | Where to get it |
|---|---|---|
| OpenAlex | Adds OpenAlex as a source; it is skipped without a key | [openalex.org/settings/api](https://openalex.org/settings/api) (free) |
| Semantic Scholar | Avoids the shared rate limit of keyless calls | [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api) |

Add them on the **Sources** tab, or from the command line:

```bash
papernym set-key openalex YOUR_KEY
papernym set-key semanticscholar YOUR_KEY
papernym set-email you@university.edu     # optional, for Crossref
```

Keys are kept in the system credential store: Windows Credential Manager, the Secret
Service (GNOME Keyring or KWallet) on Linux, or the Keychain on macOS. They are not
written to the settings file. Where no credential store exists, PaperNym falls back to the
settings file (readable only by you) and says so. The environment variables
`OPENALEX_API_KEY` and `S2_API_KEY` override stored keys.

## Command-line reference

| Command | What it does |
|---|---|
| `scan [FOLDER] [--dry-run] [--no-subfolders]` | One pass over the watched folders, or over `FOLDER` only |
| `watch [--poll]` | Scan, then keep watching until Ctrl+C |
| `add-folder PATH [--no-subfolders]` / `remove-folder PATH` | Manage watched folders |
| `exclude PATTERN` / `exclude --remove PATTERN` | Skip matching files; a pattern ending in `/` skips folders |
| `formats` / `set-format PRESET` | List presets, or choose one |
| `set-format --custom "TEMPLATE" [--word-sep _\|" "\|-\|none]` | Use your own template |
| `set-year citation\|online` | Year mode |
| `set-title-search on\|off` | Allow or stop title searches |
| `set-key openalex\|semanticscholar KEY` / `set-email EMAIL` | Keys and contact email |
| `reformat [--dry-run] [--include-manual]` | Re-apply the current format to earlier renames |
| `undo [--last N]` | Revert the last batch, or the last N renames |
| `fix PATH --doi DOI` | Name a file from a DOI you supply |
| `status` | Counts by status and the files needing attention |
| `show` | Settings, folders and where keys are stored |
| `test-apis` | Check every metadata service with a known paper |
| `compare [FOLDER]` | Show what each source returns for each PDF; renames nothing |

Each output line starts with a tag: `[ok]` renamed, `[check]` named offline (marked
`_CHECK`), `[?]` not identified, `[busy]` file in use, `[skip]`, `[warn]`, `[preview]` or
`[undo]`. Colours are switched off when the output is redirected, when `NO_COLOR` is set,
or with `--no-color`. Exit codes: `0` success, `1` failure, `2` usage error.

## Settings and data

| | Windows | Linux |
|---|---|---|
| Settings, history and cache | `%APPDATA%\PaperNym` | `~/.config/PaperNym` (or `$XDG_CONFIG_HOME/PaperNym`) |

Set `PAPERNYM_HOME` to use a different folder. The tray app and the command line share it,
so a folder added in one shows up in the other.

To try PaperNym without touching your real settings or files:

```bash
papernym-gui --sandbox --show      # installed app: PaperNym.exe --sandbox --show
```

The sandbox uses a temporary settings folder and a temporary copy of some sample papers.

## Uninstall

Use **Settings → Apps → Installed apps → PaperNym → Uninstall**. The uninstaller removes
the program, its Start-menu and login entries, and the `PATH` entry. It asks whether to
remove your settings, history and saved keys too (the default is to keep them). Your PDFs
are never touched.

## Development

```bash
pip install -e ".[gui,dev]"
python -m pytest -q
papernym-gui --sandbox --show --debug     # run the tray app from source
```

- [`docs/SPEC.md`](docs/SPEC.md) is the full specification: behaviour, naming rules, edge cases.
- [`docs/BUILDING.md`](docs/BUILDING.md) covers building the Windows exe and installer, and releasing.
- [`docs/PROGRESS.md`](docs/PROGRESS.md) is the work log and milestone checklist.

Bug reports and ideas are welcome in
[Issues](https://github.com/Xatta-Trone/papernym/issues). For a misnamed paper, include its
DOI and the output of `papernym compare` on that file, if you can.

## Roadmap

- [x] Windows tray app, command line and installer
- [ ] Code-signed Windows releases
- [ ] PyPI package (`pip install papernym` / `pipx install papernym`)
- [ ] Tested Linux support for the tray app and the command line

## Licence and credits

PaperNym is released under the [MIT licence](LICENSE) © 2026
[Xatta-Trone](https://github.com/Xatta-Trone). The Windows build bundles Qt for Python
(PySide6, LGPL-3.0), linked dynamically. Licences of all bundled components ship in
`THIRD_PARTY_LICENSES.txt`.

Metadata is provided by [Crossref](https://www.crossref.org),
[DOI.org](https://www.doi.org), [OpenAlex](https://openalex.org),
[Semantic Scholar](https://www.semanticscholar.org) and [arXiv](https://arxiv.org).
Thank you to these services for keeping scholarly metadata open.
