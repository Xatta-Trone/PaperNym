# PaperNym: Build Specification

Version 1.2 of the spec. This document is self-contained: it describes everything needed to
build the product. A working single-file prototype (`paper_renamer.py`, the project's earlier working name)
exists and is the behavioural reference; where this spec and the prototype differ, this
spec wins. The prototype reads PDFs with PyMuPDF; the product must use `pypdfium2`
instead (sections 5 and 16).

---

## 1. Product summary

PaperNym watches folders and renames academic-paper PDFs using metadata looked up from
free scholarly services.

    1-s2.0-S0001457525001344-main.pdf
      ->  2025_Islam_Evaluating_crash_risk_factors_of_farm_equipment_vehicles_on_county_and_non-county_roads.pdf

It ships in two forms that share one core library. Priority order: (1) the Windows tray
application, (2) the command-line tool on PyPI, (3) Linux support for both. macOS is out
of scope for version 1.

| Form | Audience | Delivery |
|---|---|---|
| Command-line tool | Researchers comfortable with a terminal | PyPI package, `pip install papernym` |
| Tray application | Everyone else | Installer (`.exe` on Windows); runs in the system tray and watches in the background |

### Goals

1. Never rename a file wrongly without flagging it. A file left untouched is acceptable; a
   silently wrong name is not.
2. Never lose a file, overwrite a file, or undo a name the user chose by hand.
3. Keep working when any single metadata service is down.
4. Do not look up the same paper twice.

### Non-goals

- OCR of scanned PDFs.
- Editing PDF contents or embedded metadata.
- Managing a reference library (no BibTeX export, no tagging, no folders-by-topic).
- Cloud sync between computers.
- macOS builds, signing or testing (keep the code portable, but do not spend effort on it).

---

## 2. Technology

| Item | Choice |
|---|---|
| Language | Python 3.10+ |
| PDF reading | `pypdfium2` >= 4.30 (Apache-2.0 / BSD-3; tested on 5.13). Chosen by test, see section 5 |
| HTTP | `requests` >= 2.28 |
| Folder watching | `watchdog` >= 3.0 |
| Database | `sqlite3` (standard library), WAL mode |
| UI | `PySide6` (Qt for Python) |
| App packaging | PyInstaller (one-folder build) + Inno Setup installer on Windows |
| Package build | `pyproject.toml` with `hatchling` or `setuptools`; `src/` layout |
| Tests | `pytest`; HTTP mocked with `responses` or a fake `http_get` |

---

## 3. Architecture

    papernym/                      (import package)
      core/
        config.py        load/save config.json, defaults, validation
        db.py            SQLite schema, migrations, queries
        pdfread.py       text, metadata, title/author extraction from a PDF
        sources/         one module per service: crossref, doiorg, openalex, semanticscholar, arxiv
        identify.py      the identification pipeline (section 6)
        naming.py        template rendering, sanitising, length budget (section 7)
        engine.py        per-file logic, scan, reformat, undo (sections 8-9)
        watcher.py       watchdog integration, folder reconcile, retry timer (section 10)
        lock.py          single-writer lock
      cli.py             command-line interface (section 11)
      gui/               tray app and windows (section 12)
    tests/

Rules:

- `core` has no UI imports and prints nothing. It reports through a callback/event interface
  (`on_event(event)`), which the CLI prints and the GUI shows.
- The CLI and the GUI are thin layers over `core.engine` and `core.watcher`.
- All state is in the settings folder (section 4). The watched folders are never used for
  storage: no sidecar files, no hidden index files.

### Events emitted by the core

`renamed`, `preview`, `needs_check`, `unidentified`, `busy`, `skipped`, `source_unavailable`,
`folder_attached`, `folder_unavailable`, `settings_reloaded`, `scan_started`, `scan_progress`
(done/total), `scan_finished` (counts). Each carries the file path(s), source and a
human-readable message.

---

## 4. Storage

### Settings folder

| System | Path |
|---|---|
| Windows | `%APPDATA%\PaperNym` |
| Linux | `$XDG_CONFIG_HOME/PaperNym` or `~/.config/PaperNym` |

Environment overrides: `PAPERNYM_HOME` (whole folder), `OPENALEX_API_KEY`,
`S2_API_KEY`.

Files: `config.json`, `papers.db`, `lock`, `logs/papernym.log` (rotating, 5 x 1 MB).

### config.json

```json
{
  "folders": [{"path": "D:/Papers", "recursive": true}],
  "exclude": ["*draft*", "*_v[0-9]*", "Manuscripts/"],
  "format": "{year}_{author}_{title}",
  "word_sep": "_",
  "year": "citation",
  "title_search": true,
  "openalex_key": "",
  "s2_key": "",
  "email": "",
  "start_at_login": false,
  "notify_on_rename": true,
  "paused": false,
  "theme": "system"
}
```

| Key | Meaning |
|---|---|
| `folders` | Watched folders. `recursive` includes subfolders |
| `exclude` | Glob patterns (file names) and folder names ending in `/`. Matching files are never read or renamed |
| `format`, `word_sep` | Name template and the separator used between words inside a field (section 7). `format` may also be a fixed preset name such as `citekey`; a preset then sets its own separator |
| (retired) `title_limit` | Removed: titles are always as long as the file-name budget allows. An old `config.json` that still has it loads normally; the key is dropped |
| `year` | `citation` (journal volume year, default) or `online` (first-online year) |
| `title_search` | If `false`, titles are never sent to any service; only DOI and arXiv lookups run |
| `email` | Sent to Crossref as `mailto` for its polite pool |
| `update_check`, `skipped_version` | Daily update check on/off; a release the user chose to skip |
| `theme` | Tray app colours: `system` (follow Windows/Linux light or dark mode), `light` or `dark`. Both themes use the icon colours (teal `#0B5563`, amber `#FFB020`) |

Write `config.json` atomically (write temp file, then replace).

**API keys** (`openalex_key`, `s2_key`) are kept out of `config.json` whenever the system has
a credential store, through the `keyring` package (`core/keystore.py`):

| System | Store |
|---|---|
| Windows | Windows Credential Manager (per user, encrypted with the user's login) |
| Linux desktop | Secret Service over D-Bus: GNOME Keyring, KWallet 5.97+ or KeePassXC |
| macOS | Keychain |
| Linux without a desktop session (SSH, server, container), or `PAPERNYM_KEYRING=off` | `config.json`, mode 600; the CLI warns when a key is saved |

- The entry is named `PaperNym` for the normal settings folder and `PaperNym-<hash>` for any
  other folder (`PAPERNYM_HOME`), so trial folders never overwrite the real key.
- Precedence when reading: environment variable (`OPENALEX_API_KEY`, `S2_API_KEY`) > credential
  store > `config.json`. Environment keys are never stored.
- Keys found in `config.json` while a store is available are moved into it on the next load.
- If the store refuses a write (for example a locked keyring), saving fails with a message
  that names the environment variable and `PAPERNYM_KEYRING=off` as alternatives; a key is
  never silently written in plain text.
- `--sandbox` sets `PAPERNYM_KEYRING=off`, so sandbox keys stay in its temporary folder.
- Keys never appear in logs or error messages (`api_key=***`), and the Sources fields hide
  their text unless being edited.

### papers.db (SQLite)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);          -- schema_version

CREATE TABLE papers (
  paper_id     TEXT PRIMARY KEY,      -- 'doi:10.1016/j.aap.2025.108048' | 'arxiv:2611.13981' | 'title:<normalised title>'
  title        TEXT NOT NULL,
  year         INTEGER,               -- citation year
  year_online  INTEGER,               -- first-online year
  authors      TEXT NOT NULL,         -- JSON array of surnames, in order
  journal      TEXT,
  source       TEXT NOT NULL,         -- crossref | doi.org | openalex | semanticscholar | arxiv | pdf-only | manual
  fetched_at   TEXT NOT NULL
);

CREATE TABLE files (
  path         TEXT PRIMARY KEY,      -- normalised absolute path (os.path.normcase(abspath))
  display_path TEXT NOT NULL,         -- path as shown to the user
  fingerprint  TEXT NOT NULL,         -- sha1(size + first 256 KB)
  size         INTEGER, mtime INTEGER,
  status       TEXT NOT NULL,         -- ok | check | unknown | pending | unreadable
  given_name   TEXT,                  -- the file name the tool last assigned; NULL if never renamed
  paper_id     TEXT REFERENCES papers(paper_id),
  attempts     INTEGER NOT NULL DEFAULT 0,
  updated_at   TEXT NOT NULL
);
CREATE INDEX files_fp ON files(fingerprint);

CREATE TABLE history (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  time     TEXT NOT NULL,
  old_path TEXT NOT NULL, new_path TEXT NOT NULL,
  source   TEXT NOT NULL,             -- a service name, or 'reformat'
  status   TEXT NOT NULL,
  batch    TEXT NOT NULL,             -- one id per scan / reformat / watch event
  undone   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE misses (
  ident      TEXT PRIMARY KEY,        -- same format as paper_id
  checked_at TEXT NOT NULL            -- do not re-query for 30 days
);
```

Identifier rules: DOIs are lower-cased and stripped of trailing punctuation. Normalised
title = ASCII-folded, lower-cased, non-alphanumerics removed, whitespace collapsed.

`papers` is a cache of lookups; `files` records what happened to each PDF. A paper row may
have zero or many file rows.

Migration: on first run, import the prototype's `state.json`, `history.csv` and
`config.json` if present (the prototype keeps them in a settings folder named
`PaperRenamer` beside the new one), then rename them to `*.bak`. If the database cannot be opened, do not start fresh silently:
restore from `papers.db.bak` (copied once a day) or stop with a clear message. Starting
fresh would re-rename files the user named by hand.

---

## 5. Reading a PDF (`pdfread`)

### Library choice

`pypdfium2` was chosen by running it, `pdfminer.six` and `pypdf` against PyMuPDF on 12 real
publisher and arXiv PDFs:

| Library | Same identifier as PyMuPDF | Same title guess | Time for 12 files |
|---|---|---|---|
| PyMuPDF (reference) | - | - | 0.4 s |
| pypdfium2 | all | all but one, and that one was better | 0.5 s |
| pdfminer.six | all (see note) | all but one, and that one was better | 5.6 s |
| pypdf | all (see note) | half; it drops the spaces between words | 3.3 s |

Note: on the arXiv paper, pdfminer.six and pypdf returned the arXiv DOI from a non-standard
Info key instead of the arXiv ID from the page text. Both identify the same paper.

How to get each item with `pypdfium2`:

- **Text:** `page.get_textpage().get_text_range()`.
- **Lines with font size:** iterate characters; split lines at `\r`/`\n`. Per character:
  `pypdfium2.raw.FPDFText_GetUnicode`, `FPDFText_GetFontSize`, `FPDFText_GetCharAngle`, and
  `textpage.get_charbox(i)`. Line size = largest character size. If the reported size is
  under 2 (size hidden in the text matrix), use 1.4 x the median glyph-box height. A line is
  rotated when most of its characters have a non-zero angle.
- **Properties:** `pdf.get_metadata_dict()` returns the standard keys only. Also read the
  non-standard keys `doi`, `DOI` and `arXivID` with `pdf.get_metadata_value(key)`.
- **XMP packet:** pdfium has no XMP call. XMP is stored uncompressed, so read the file bytes
  and take every `<x:xmpmeta ...> ... </x:xmpmeta>` span.
- Page coordinates are bottom-up: `top = page_height - y`.

`compare_pdf_libs.py` contains a working implementation of all of the above.

### Fields

Read the first two pages only. Return:

| Field | How |
|---|---|
| `text` | Text of pages 1-2 |
| `page1` | Text of page 1 |
| `md_title`, `md_author` | From PDF properties. Discard a title shorter than 11 characters or matching `\.(pdf|docx?|tex|dvi|indd)$`, `^untitled`, `microsoft word`, `^doi:`, `^pii:` |
| `md_dois` | DOIs found in the properties and the XMP packet |
| `big_title` | Title guess from page-1 layout (below). Keep only if 16-299 characters |
| `author_line` | First plausible line after the title block (below) |
| `created` | Year from the PDF creation date |
| `paperish` | True if a DOI, an arXiv ID, or one of the words abstract / keywords / introduction / references appears in pages 1-2 |

Password-protected or corrupt PDFs: status `unreadable`, reported once, never retried
unless the file changes.

### Title guess

1. Collect page-1 text lines with their font size and vertical position. Ignore rotated
   lines (the arXiv side stamp) and lines matching the arXiv pattern.
2. Take the largest font size among lines longer than 3 characters. Select lines within
   0.6 pt of it.
3. Group selected lines into blocks: consecutive lines whose vertical gap is under 1.5 x the
   font size. (Journal name and title often share a font size but sit apart.)
4. The block with the most characters is the title.

### Author line

Among the 5 lines following the title block, the first that starts with a capital letter,
contains at least two words and contains no year.

### Patterns

    DOI    \b(10\.\d{4,9}/[^\s"<>\]\[{}|\\^`,;]+)      (case-insensitive; strip trailing . ) ( ')
    arXiv  arxiv[:.\s/]*(\d{4}\.\d{4,5})(?:v\d+)?      (case-insensitive)
    arXiv file name  ^(\d{4}\.\d{4,5})(?:v\d+)?$

The file name is never used to find a DOI. It is used only for arXiv-style names.

---

## 6. Identification pipeline (`identify`)

Input: a PDF. Output: a paper record plus status `ok`, or nothing.

### 6.1 Order of attempts

1. **DOI.** Candidates = DOIs from properties/XMP, then DOIs from the text in order of
   appearance; at most 6. For each candidate:
   - If cached in `papers`, use the cached record. If in `misses` (under 30 days), skip.
   - Otherwise query sources in this order: Crossref, doi.org, OpenAlex, Semantic Scholar.
     Stop at the first that returns a record.
   - **Verify:** at least 60% of the returned title's words longer than 3 characters must
     appear in `text`. Exception: if `text` is under 200 characters (scanned PDF), a DOI
     taken from the PDF properties is trusted.
   - If verification fails, the DOI belongs to another paper (a reference): move to the next
     candidate without querying further sources for it.
2. **arXiv ID** (from text, else from the file name): arXiv API, then Semantic Scholar.
   Same verification.
3. **Title search** (only if `title_search` is true). Queries = `big_title`, then
   `md_title`. Sources: Crossref, OpenAlex, Semantic Scholar. Accept a result only if
   **both**:
   - titles match: `difflib.SequenceMatcher` ratio >= 0.85 on normalised titles, or one is
     a prefix of the other and the shorter is >= 25 characters; and
   - the result's first-author surname is printed on page 1 as a whole word
     (case-sensitive, ASCII-folded).
   The second test exists because a cover line such as "Journal Pre-proof" or a journal
   name is itself the title of some unrelated record.
4. **Nothing found.** See 6.3.

A source that is not configured (OpenAlex without a key) is skipped and counts as neither
reached nor failed.

### 6.2 Sources

All requests: timeout 12 s, one retry on connection error, 5xx or 429 (wait 1-2 s),
`User-Agent: PaperNym/<version> (mailto:<email>)`. HTTP 404/400/410 = not found.
HTTP 401/403 = service unusable (report once per session, e.g. "OpenAlex key rejected").

| Source | DOI lookup | Title search | Notes |
|---|---|---|---|
| Crossref | `GET https://api.crossref.org/works/{doi}` | `GET https://api.crossref.org/works?query.bibliographic={t}&rows=3` | Add `mailto` param if email set. Record is under `message` |
| doi.org | `GET https://doi.org/{doi}` with `Accept: application/vnd.citationstyles.csl+json` | - | Works for Crossref and DataCite DOIs |
| OpenAlex | `GET https://api.openalex.org/works/doi:{doi}?api_key=` | `GET https://api.openalex.org/works?search={t}&per_page=3&api_key=` | Key required |
| Semantic Scholar | `GET https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,year,authors,venue,publicationDate` | `.../paper/search/match?query={t}&fields=...` | arXiv: `.../paper/ARXIV:{id}`. Optional `x-api-key`. Keyless calls share a rate-limited pool: expect 429 |
| arXiv | `GET https://export.arxiv.org/api/query?id_list={id}` (Atom XML) | - | |

Field mapping:

| Field | Crossref / doi.org (CSL JSON) | OpenAlex | Semantic Scholar | arXiv |
|---|---|---|---|---|
| title | `title` (list or string); strip HTML/JATS tags | `title` | `title` | `entry/title` |
| surnames | `author[].family`, else last word of `name`/`literal` | last word of `authorships[].author.display_name` | last word of `authors[].name` | last word of `author/name` |
| citation year | first present of `issued`, `published-print`, `published-online`, `published`, `created` | `publication_year` | `year` | year of `published` |
| online year | minimum year across those same date fields | `publication_year` | min(`year`, year of `publicationDate`) | same |
| journal | `short-container-title`, else `container-title` | `primary_location.source.display_name` | `venue` | "arXiv" |

Surname from a display name: drop digits and `*`; if it contains a comma take the part
before it; otherwise the last word, ignoring Jr, Sr, II, III, PhD.

The citation year is the default because it matches the publisher's citation (verified:
an in-press article with DOI `...trc.2026...` is cited as 2027).

### 6.3 When nothing is found

Track per file whether any source was reached and whether any failed.

| Situation | Action |
|---|---|
| At least one source answered, none had the paper | Status `unknown`. Leave the file untouched. `attempts += 1` |
| No source reachable **and** `paperish` | Offline fallback: build a record from the PDF alone (6.4), status `check`, rename with `_CHECK` suffix. Do not increment `attempts` |
| No source reachable and not `paperish` | Status `unknown`, untouched, do not increment `attempts` |

This keeps invoices, slides and forms in a watched folder from being renamed.

### 6.4 Offline fallback (PDF only)

- **Title:** `md_title`, else `big_title`. If neither, give up.
- **Year:** first match in page 1 of, in this order: copyright mark followed by a year;
  "available online" / "published" followed by a year; "accepted" followed by a year. Never
  "received". Else the most frequent plausible year on page 1; else the creation year.
- **Author:** be conservative; a wrong author is worse than `Unknown`.
  1. Parse `md_author` and `author_line` into name lists. Remove footnote marks, digits and
     single-letter affiliation markers; split on `;` `,` `&` `·` `•` and "and"; drop titles
     (Prof, Dr). A list is valid only if every part is 2-5 words, each capitalised or a
     particle (de, van, von, der, ...), and the raw string contains no colon.
  2. Both valid and their first surnames agree: use it.
  3. Both valid and they disagree: `Unknown`. (PDF properties often hold a co-author or
     whoever exported the file.)
  4. Only `md_author` valid: use it if that surname is printed on page 1; else `Unknown`.
  5. Only `author_line` valid: use it only if it lists two or more people; else `Unknown`.

---

## 7. File naming (`naming`)

### Template

Tokens: `{year}` `{author}` `{authors}` `{title}` `{shorttitle}` `{journal}`. Reject a
template with unknown tokens or with no token.

| Token | Value |
|---|---|
| `{year}` | Per the `year` setting; `nd` if missing |
| `{author}` | First author's surname; `Unknown` if none |
| `{authors}` | One: `Smith`. Two: `Smith and Jones`. Three or more: `Smith et al` |
| `{title}` | Title, cut to the budget below at a whole word |
| `{shorttitle}` | First 6 words of the title, same budget |
| `{journal}` | Abbreviated journal name; empty if unknown |

### Presets

The user picks one of these fixed presets, or **Custom**. Presets cannot be edited.

| Name | Template | Word separator | Example |
|---|---|---|---|
| `year_author_title` (default) | `{year}_{author}_{title}` | `_` | `2025_Smith_Deep_learning_for_crash_severity.pdf` |
| `author_year_title` | `{author}_{year}_{title}` | `_` | `Smith_2025_Deep_learning_for_crash_severity.pdf` |
| `year_authors_title` | `{year}_{authors}_{title}` | `_` | `2025_Smith_et_al_Deep_learning_for_crash_severity.pdf` |
| `authors_year_title` | `{authors}_{year}_{title}` | `_` | `Smith_et_al_2025_Deep_learning_for_crash_severity.pdf` |
| `year_author_shorttitle` | `{year}_{author}_{shorttitle}` | `_` | `2025_Smith_Deep_learning_for_crash_severity_prediction.pdf` |
| `author_year_shorttitle` | `{author}_{year}_{shorttitle}` | `_` | `Smith_2025_Deep_learning_for_crash_severity_prediction.pdf` |
| `year_author_journal_title` | `{year}_{author}_{journal}_{title}` | `_` | `2025_Smith_Accid_Anal_Prev_Deep_learning.pdf` |
| `author_year_journal` | `{author}_{year}_{journal}` | `_` | `Smith_2025_Accid_Anal_Prev.pdf` |
| `title_author_year` | `{title}_{author}_{year}` | `_` | `Deep_learning_for_crash_severity_Smith_2025.pdf` |
| `title_only` | `{title}` | `_` | `Deep_learning_for_crash_severity.pdf` |
| `author_year` | `{author}_{year}` | `_` | `Smith_2025.pdf` |
| `citekey` | `{author}{year}{shorttitle}` | none (words run together, each capitalised) | `Smith2025DeepLearningForCrashSeverityPrediction.pdf` |
| `author_year_title_spaces` | `{author} ({year}) {title}` | space | `Smith (2025) Deep learning for crash severity.pdf` |
| `authors_year_title_spaces` | `{authors} ({year}) {title}` | space | `Smith et al (2025) Deep learning for crash severity.pdf` |
| `authors_year_title_zotero` | `{authors} - {year} - {title}` | space | `Smith et al - 2025 - Deep learning for crash severity.pdf` |

Presets without a title token (`author_year`, `author_year_journal`) collide often; the
collision rule below then appends `_b`, `_c`. Show that warning next to them in the UI.

### Custom templates

A custom template is any mix of the six tokens and the user's own fixed text, for example
`{year}_{author}_{title}_MyLab` or `[{journal}] {author} {year} - {shorttitle}`.

Validation (reject on save, with the reason shown; never silently "fix" a template):

- At least one token. Only the six known tokens; `{anything_else}` is an error.
- Braces must be balanced and not nested.
- Fixed text may contain letters, digits, space and `_ - . , ( ) [ ] + & '`. It may not
  contain `< > : " / \ | ? *`, control characters, or a path separator.
- Fixed text is at most 60 characters in total, and the template may not start or end with
  a space or a dot.
- If there is no `{title}` or `{shorttitle}`, accept it but warn that names will collide.

Rendering: tokens are cleaned and cut as described below; fixed text is kept exactly as
typed (not ASCII-folded, not re-separated) and counts against the length budget before the
title does. The custom template has its own word-separator setting (`_`, space, `-`, or
none).

### Cleaning each field

1. Strip HTML/JATS tags.
2. Fold accents to ASCII (`Bermúdez` -> `Bermudez`). **If folding leaves a field empty
   (non-Latin script), keep the original Unicode characters instead.**
3. Remove apostrophes; replace every character other than letters, digits, hyphen and space
   with a space; collapse spaces; join words with the word separator.
4. After rendering: remove `<>:"/\|?*` and control characters, collapse repeated separators,
   remove empty `()`, trim leading/trailing space, dot, underscore, hyphen.

### Length budget

    name limit   = 255                                              (all systems)
    on Windows   = min(255, 259 - len(absolute folder path) - 1)    (full-path limit)
    title room   = name limit - len(".pdf") - len(suffix) - 6 - len(everything else in the name)

The 6 is reserved for a possible `_dupNN` ending. `suffix` is `_CHECK` when present. The
title always gets all of this room (there is no user title-length setting). If the template has both title
tokens, split the room between them. Cut at a whole word. Final guard: hard-truncate the
stem if a very long author or journal still overflows. Count bytes, not characters, on
Linux when the name contains non-ASCII text.

### Collisions

If the target name exists and is a different file:

| Case | Result |
|---|---|
| Same paper (same `paper_id` or same fingerprint) | Append `_dup2`, `_dup3`, ... |
| Different paper, name collided because of truncation | Extend the title word by word until the names differ; if impossible append `_b`, `_c` |

Never overwrite an existing file.

---

## 8. Per-file logic (`engine`)

### Statuses

| Status | Meaning | Retried? |
|---|---|---|
| `ok` | Identified and named | No |
| `check` | Named from the PDF alone during an outage; has `_CHECK` suffix | Yes, until identified online |
| `unknown` | Not identified; file untouched | Yes, up to 5 attempts that reached a source |
| `pending` | Identified but the rename failed (file locked); metadata saved | Yes, no new lookup needed |
| `unreadable` | Password-protected or corrupt | Only if the file changes |

### Processing one file

Skip unless: extension is `.pdf` (case-insensitive), name does not start with `.` or `~$`,
it is a regular file, and it matches no `exclude` pattern.

1. **Known by path, status `ok`:** do nothing. If size or mtime changed (user annotated the
   PDF), refresh the fingerprint. No web call.
2. **Wait until stable:** size unchanged across two checks 1.5 s apart and greater than 0;
   give up after 120 s (the next scan retries).
3. Compute the fingerprint.
4. **Known by path, fingerprint differs, status not `ok`:** a different file now has this
   name. Forget the old row and treat as new.
5. **Not known by path, fingerprint matches a row whose file no longer exists:** the user
   moved or renamed it. Update the row's path. If status is `ok`, stop: the user's name is
   respected (an Activity line says so).
   **Exception:** if PaperNym had named that file and the new file has exactly the name it
   had before that rename (the user deleted PaperNym's file and pasted the original download
   again), forget the old row and rename the file again from the saved paper record, with no
   web call.
6. **Not known by path, fingerprint matches a row whose file still exists:** this is a
   copy. Reuse that paper record (no web call) and rename; the collision rule adds `_dup2`.
7. **Known, status not `ok`:** stop unless this is a retry pass, the name is not
   user-changed, and `attempts` < 5.
8. **Otherwise identify** (section 6), then rename.
9. Rename failure (file open in a viewer, permission): status `pending`, keep the metadata,
   emit `busy`.

### Hand-renamed files

A file is "hand-renamed" when `given_name` is set and differs from its current file name.
Hand-renamed files are never renamed automatically, never retried, and skipped by
`reformat` unless the user explicitly includes them.

### Rename safety

- Rename only within the same folder. Never move files between folders.
- Every rename is written to `history` in the same transaction as the `files` update.
- A second copy of the tool must never be writing at the same time (section 13).

---

## 9. Operations

| Operation | Behaviour |
|---|---|
| **Scan** | Process every PDF in the watched folders (retry pass). Then prune `files` rows whose file is gone, but only under folders that are currently reachable. Emits progress and a final count |
| **Dry run** | Scan or reformat without renaming or writing to the database. Shows `old -> new`. Must reserve previewed names so two files are not shown the same target |
| **Reformat** | Apply the current template and year mode to files already named by the tool. Uses saved paper records; no web calls, except a one-time lookup for records that lack `year_online`. Skips hand-renamed files unless `include_manual` |
| **Undo** | Default: revert every rename in the most recent batch. Option: revert the last N renames. A rename is undone only if the new path exists and the old path is free. After undoing a first-time rename the file counts as hand-named (left alone). After undoing a reformat, `given_name` is set back so reformat can run again |
| **Manual fix** | For a `check` or `unknown` file, the user supplies a DOI or edits title/author/year. A DOI is looked up and verified as usual; edited fields are stored with source `manual`. Then rename |
| **Refresh** | Re-look-up one file's metadata on request (for an in-press paper whose year has since changed) |

Changing the template or year mode never renames existing files by itself.
The user runs Reformat (the UI offers it with a preview).

---

## 10. Watching (`watcher`)

- One `watchdog` observer; one watch per configured folder, recursive per its setting. A
  polling observer is selectable for network drives.
- React to **created** and **moved-into-place** events (browsers download as
  `.crdownload`/`.part`, then rename to `.pdf`). Events go on a queue; a single worker
  processes files one at a time.
- On start: attach folders, run a scan (catches files that arrived while not running).
- Every 10 s: reload `config.json` if its modification time changed, then reconcile
  watches: detach folders that vanished or were removed, attach folders that appeared or
  came back, and scan newly attached ones. An unplugged drive must not stop the watcher.
- Every 30 min: retry files with status `check`, `unknown` or `pending`.
- The tool's own renames generate events; they resolve at step 1 of section 8 with no work.
- Each watch-triggered rename is its own undo batch; the start-up scan is one batch.
- `paused` in config: keep the process alive but ignore events and timers.

Folder rules when adding: reject a folder already inside a recursive watched folder; when
adding a recursive parent, drop its already-listed children. Warn (do not block) if the
folder looks like a reference-manager store (path contains `Zotero/storage`, `Mendeley`,
`EndNote`), because renaming there breaks that program's links.

---

## 11. Command-line interface

Installed command: `papernym`. Running with no arguments prints help.

| Command | Purpose |
|---|---|
| `add-folder PATH [--no-subfolders]` | Watch a folder |
| `remove-folder PATH` | Stop watching it |
| `exclude PATTERN` / `exclude --remove PATTERN` | Manage the exclude list |
| `set-key openalex|semanticscholar KEY` | Store an API key in the system credential store (or `config.json` where there is none); `show` says where keys live |
| `set-email EMAIL` | Crossref polite pool |
| `formats` | List the fixed presets with an example each |
| `set-format PRESET` | Choose a fixed preset |
| `set-format --custom "TEMPLATE" [--word-sep _| |-|none]` | Use a custom template (tokens plus your own text); validated as in section 7 |
| `set-year citation|online` | Year mode |
| `set-title-search on|off` | Privacy switch |
| `show` | Print settings, folders, settings-folder path |
| `scan [FOLDER] [--dry-run] [--no-subfolders]` | One pass over the watched folders; with `FOLDER` (e.g. `.` for the current folder), one pass over that folder only, subfolders included unless `--no-subfolders`, without adding it to the watch list |
| `watch [--poll]` | Scan, then keep watching until Ctrl+C |
| `reformat [--dry-run] [--include-manual]` | Apply current naming to earlier renames |
| `undo [--last N]` | Revert the last batch, or the last N renames |
| `fix PATH --doi DOI` | Manual fix by DOI |
| `status` | Counts by status; list files needing attention |
| `test-apis` | Check each service with a known paper; PASS/FAIL/SKIP per check |
| `compare [FOLDER]` | Diagnostic: show what every source returns for each PDF; renames nothing |

Output lines are prefixed: `[ok]`, `[check]`, `[?]`, `[busy]`, `[skip]`, `[warn]`,
`[preview]`, `[undo]`. Use `->` between names (plain ASCII, safe on Windows consoles).
On an interactive terminal the prefix is coloured (ok green, check yellow, ? magenta,
busy blue, skip grey, warn bold red, preview cyan, undo bright blue) and the summary line is
bold. No colour when output is redirected, when `NO_COLOR` is set, or with `--no-color`;
the log file is always plain.
Exit code 0 on success, 1 on failure, 2 on usage error. Every scan ends with a summary
line, and a scan with no folders configured says so.

---

## 12. Tray application

Launches to the system tray (Windows notification area, Linux tray). No
taskbar window until the user opens one. Closing a window hides it; only Quit exits.

### Running the UI from source (required from the first UI task onward)

The UI must be runnable locally with one command, straight from the source tree, with no
build step. Development and manual testing happen this way; packaging comes later.

    .venv\Scripts\activate
    pip install -e ".[gui]"          (once)
    papernym-gui                     (same as: python -m papernym.gui)

| Option | Effect |
|---|---|
| `--sandbox` | Safe trial mode: uses a fresh temporary settings folder and a temporary copy of `sample_pdfs/` as the only watched folder. Nothing real is touched. Says "SANDBOX" in the window title |
| `--show` | Open the main window at start instead of hiding in the tray |
| `--debug` | Log to the console at debug level (the terminal it was started from; a new console window if there is none) |

`papernym-gui --sandbox --show --debug` is the standard way to try a UI change.

### Tray icon and menu

Icon states: watching, paused, working (animated during a scan), attention (a badge when
files need checking), error (no folder reachable).

Menu:

- Open PaperNym
- Pause watching / Resume watching
- Scan now
- Recent renames > (last 5; click opens the containing folder with the file selected)
- Undo last rename
- Needs attention (N)
- Settings
- Quit

Left-click (double-click on Windows) opens the main window.

### Main window (tabs)

| Tab | Contents |
|---|---|
| **Activity** | Live list, newest first: time, old name, new name, source, status. Row actions (buttons enabled once a row is selected, right-click menu, double-click or Enter opens): Open file, Show in folder, Undo, Refresh metadata. Search box and status filter; 200 rows per page with First/Previous/Next/Last, so thousands of files stay responsive (the newest 20,000 rows are kept; older ones stay in History and the CSV export). "Scan now" button with a progress bar |
| **Needs attention** | Files with status `check`, `unknown`, `pending`, `unreadable`, with the same search box, status filter and paging as Activity. For each: the reason, and actions: Enter DOI, Edit details (title, author, year), Retry now, Ignore (never ask again). Ignore records the file as hand-named (status `ok`, no paper), the same as an unticked file in a preview |
| **Folders** | Watched folders with a subfolders toggle and a reachable/unreachable indicator; Add, Remove. Exclude patterns list . Double-click a folder row to open it in Explorer (the file manager on Linux) |
| **Naming** | Preset dropdown listing the fixed presets plus **Custom**. Choosing a preset shows its template read-only. Choosing Custom reveals an editable template field with clickable token buttons, where the user can also type fixed text, and a word-separator choice. Below: year mode (titles are always as long as fits). A **live preview** on three sample papers updates as the user types. Invalid templates show the error inline and cannot be saved |
| **Sources** | OpenAlex key field with a "Get a free key" link and a **Test** button; optional Semantic Scholar key; email; "Search by title" switch with a one-line privacy explanation; "Test all sources" button showing PASS/FAIL per service |
| **History** | All renames grouped by batch; Undo per row or per batch; export to CSV |
| **General** | Start at login; show a notification on rename; pause; theme (System, Light, Dark); Save diagnostics (a copy of the log with keys, email addresses and the settings path masked). The settings folder path, Open settings folder and Open log appear only with `--debug` |
| **About** | Icon, name, version, one-line description; links: developer (github.com/Xatta-Trone), project, report a problem (issues), MIT licence; data-source credit; update status, Check for updates now, automatic check on/off |

### Behaviours

- **First run:** a three-step welcome: (1) choose folders, (2) choose a name format with
  preview, (3) optional OpenAlex key and "Start PaperNym when I log in" (ticked by default; not offered in sandbox mode). Then a **dry-run** of the chosen folders is shown as a
  list of `old -> new` with checkboxes; nothing is renamed until the user confirms.
- **Changing naming settings:** on Save, if any tool-named files exist, ask "Apply to N
  existing files?" with a preview list. Choices: Apply, Not now. State that hand-renamed
  files are left alone, with a checkbox to include them.
- **Adding a folder:** show how many PDFs it contains (and the reference-manager warning
  when it applies); no file is read or looked up before the user adds it. **Add** saves the
  folder and starts watching and renaming at once. **Add and preview** saves the folder
  but holds it (watched, but no scan, renames or retries) while a dry run shows the planned
  names; confirming renames the ticked files and releases the folder, closing the preview
  removes the folder again with nothing renamed.
- **Notifications:** batched, never one per file. During a scan, one toast when it ends
  ("12 papers renamed", with the attention count in its text). Outside a scan, renames are
  collected and one toast is shown after 4 s of quiet, or at least every 20 s while files
  keep arriving; a single rename shows its new name. Respect the notification setting.
- **Outage:** a non-blocking banner "Metadata services unreachable; new papers are marked
  _CHECK and will be fixed automatically."
- **Rejected key:** banner on the Sources tab and an attention badge; other sources keep
  working.
- **Threading:** the watcher and all lookups run in a worker thread; the UI thread never
  blocks on disk or network. Core events are delivered to the UI through Qt signals.
- **Start at login:** Windows: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
  Linux: a `.desktop` file in `~/.config/autostart`. Start
  minimised to the tray. Each normal start re-syncs the entry with the setting, so it
  follows the program if it moves.
- **Single instance:** launching a second copy brings the existing window to the front. One
  instance per settings folder; `--sandbox` (a new temporary folder each time) allows one
  sandbox at a time, so a sandbox and a normal instance can run side by side.
- **Theme:** colours from the icon (teal `#0B5563`, amber `#FFB020`) in light and dark
  variants, Fusion style on every platform; `System` follows the OS setting live.
- **Accessibility:** every action reachable by keyboard; status is never conveyed by colour
  alone.

---

## 13. Running both forms on one computer

The tray app and the CLI share the settings folder and database.

- One **writer** at a time, enforced by an OS file lock on `lock` (`msvcrt.locking` on
  Windows, `fcntl.flock` elsewhere), released automatically when the process ends.
- While the tray app (or `watch`) holds the lock, CLI commands that rename (`scan`,
  `reformat`, `undo`, `fix`) refuse with a clear message. Read-only and settings commands
  (`show`, `status`, `formats`, `set-*`, `add-folder`, dry runs) always work; the running
  watcher picks up settings changes within 10 s.

---

## 14. Edge cases (required behaviour)

| # | Case | Required behaviour |
|---|---|---|
| 1 | File already named by the tool | Skipped with no web call |
| 2 | Same file downloaded twice | Second copy gets `_dup2`, no web call |
| 3 | Same paper, different PDF (publisher vs preprint) | Paper cache hit by DOI; no web call; `_dup2` if the name collides |
| 4 | User renames a tool-named file | Respected forever; skipped by reformat unless included |
| 5 | User moves a file to another folder | Recognised by fingerprint; left alone |
| 5a | User deletes a renamed file and pastes the original download back | Renamed again from the saved record; no web call |
| 6 | User annotates and saves a PDF | Still recognised; fingerprint refreshed |
| 7 | Download still in progress | Wait for stable size; partial files never read |
| 8 | File open in a PDF viewer | `pending`; retried; metadata not looked up again |
| 9 | DOI of a cited paper on page 1 | Rejected by title verification; next candidate tried |
| 10 | No DOI, cover page as "title" | Title search result rejected unless its first author is on page 1 |
| 11 | One or more services down | Next source used; one warning per service per session |
| 12 | All services down | Papers get `_CHECK`; non-papers untouched; auto-corrected later |
| 13 | Invoice, slide deck, form in the folder | Untouched |
| 14 | Scanned PDF without text | Uses a DOI from PDF properties if present; else untouched |
| 15 | Password-protected or corrupt PDF | `unreadable`; reported once |
| 16 | Title longer than the name limit | Cut at a whole word within the budget |
| 17 | Deep folder on Windows | Budget shrinks to keep the full path within 259 characters |
| 18 | Two papers, same year/author/long title | Names made distinct by extending the title, not `_dup` |
| 19 | Non-Latin title or author | Original characters kept |
| 20 | Missing author or year | `Unknown`, `nd` |
| 21 | Template or year mode changed | New files only; existing files change only through Reformat |
| 22 | Undo | By batch or last N; never overwrites; state stays consistent |
| 23 | Drive unplugged / network share offline | Watcher keeps running; re-attaches and scans on return; no pruning for that folder meanwhile |
| 24 | Overlapping folders | Rejected or merged on add |
| 25 | Two instances | Second writer refuses; GUI second launch focuses the first |
| 26 | Database unreadable | Restore backup or stop; never start empty silently |
| 27 | Files deleted | Rows pruned at next scan |
| 28 | Drafts and manuscripts under review | Covered by the exclude list and the title-search switch |
| 29 | File arrives while the tool is not running | Caught by the start-up scan |
| 30 | In-press paper whose year later changes | Not re-checked automatically; Refresh on request |
| 31 | Laptop sleep / wake | Watcher resumes; reconcile runs |
| 32 | Very large library, first scan | Progress shown; safe to interrupt and resume; Semantic Scholar 429s tolerated |

Known limits to document for users, not to solve: supplements and proofs that carry the
main article's DOI are named as that article with `_dup2`; a corrigendum that prints the
original DOI and title may be named as the original; compound surnames from OpenAlex or
Semantic Scholar keep only the last word; one computer per watched folder when the folder
is cloud-synced.

---

## 15. Distribution

### 15.1 Windows application (priority 1)

- **Local build first.** One command, `python scripts/build_windows.py`, runs PyInstaller
  and (if Inno Setup is installed) the installer step, and writes to `dist/`. The built
  `dist/PaperNym/PaperNym.exe` must accept the same `--sandbox --show --debug` options as
  the source run, so the packaged app can be tested safely on the build machine.
- **GitHub Actions for distribution, afterwards.** A workflow on `windows-latest`,
  triggered by a version tag (`v*`), runs the tests, calls the same build script, and
  attaches the installer to a GitHub Release. It must not contain build logic of its own.
- PyInstaller, one-folder mode (faster start and fewer antivirus false positives than
  one-file), windowed (no console), with icon.
- Inno Setup installer: per-user install (no admin rights), Start-menu shortcut, optional
  "start at login", uninstaller that leaves the settings folder unless the user ticks
  "remove my settings".
- As built (see `docs/BUILDING.md`): the folder holds `PaperNym.exe` (windowed) and
  `papernym-cli.exe` (console); every install includes the CLI and registers it: PATH gets
  `bin\papernym.cmd` so `papernym` works in a terminal, and App Paths entries let Windows find
  both programs by name (Windows file names are case-insensitive, so the CLI cannot
  be `papernym.exe` next to `PaperNym.exe`). The installer's start-at-login choice is left as a
  one-time marker in `HKCU\Software\PaperNym` that the app adopts into its own setting.
- Code-sign the executable and the installer. Unsigned builds trigger Windows SmartScreen
  warnings. Owner decision 2026-11-11: release unsigned for now; the build script keeps an
  optional signing hook.
- Update check (`core/updates.py`): 30 s after start and then every 24 h (and from About >
  Check for updates now), one unauthenticated GET to
  `https://api.github.com/repos/Xatta-Trone/papernym/releases/latest` with only a
  `PaperNym/<version>` user agent, on a short background thread. Tags are compared as version
  numbers (`v0.10.0` > `v0.9.0`). A newer release shows a banner (Download, Skip this
  version) and a tray item; a skipped version only shows again when checked by hand.
  Failures are logged and shown on the About tab only. "No release yet" is a normal answer.
  The installed app links to the release page; a pip or source install shows the pip command.
  Nothing is downloaded or installed automatically in version 1.

### 15.2 PyPI package (priority 2)

- Distribution name and import name `papernym` (the name was unregistered
  on PyPI when this spec was written; re-check before publishing).
- `pyproject.toml`: dependencies `pypdfium2`, `requests`, `watchdog`. Optional extra
  `gui = ["PySide6"]`.
- Entry points: `papernym = papernym.cli:main`;
  `papernym-gui = papernym.gui.app:main` (gui-scripts).
- Also runnable as `python -m papernym`.
- Ship a README (install, quick start, command table, privacy note), LICENSE, CHANGELOG.
- Version from a single source; semantic versioning.
- Release through GitHub Actions with PyPI Trusted Publishing; publish to TestPyPI first.

### 15.3 Linux (priority 3)

- Supported through PyPI: `pip install papernym` for the CLI, `pip install "papernym[gui]"`
  for the tray app. No AppImage or distro packages in version 1.
- Tray support varies by desktop: if no system tray is available, open the main window
  instead of hiding to the tray.
- Start at login through `~/.config/autostart/papernym.desktop`.
- CI runs the full unit-test suite on `ubuntu-latest` as well as `windows-latest`.

---

## 16. Licensing and privacy

- **License: MIT.** Every runtime dependency is permissive (`pypdfium2` Apache-2.0/BSD-3,
  `requests` Apache-2.0, `watchdog` Apache-2.0), so the project can be MIT-licensed.
- **Do not add PyMuPDF** (AGPL-3.0) or any other copyleft dependency, including as an
  optional import. The prototype's PyMuPDF calls must be replaced, not copied.
- **PySide6 is LGPL-3.0.** That is compatible with an MIT app provided Qt is linked
  dynamically: build in PyInstaller one-folder mode and ship the Qt/PySide6 license notices
  with the installer. List all third-party licenses in a `THIRD_PARTY_LICENSES` file.
- Keep all PDF access inside `pdfread.py` so the library can be swapped again.
- **What leaves the computer:** DOIs, arXiv IDs and (if `title_search` is on) titles of the
  user's PDFs, plus the optional email, sent to Crossref, doi.org, OpenAlex, Semantic
  Scholar and arXiv. No file contents, no file names, no analytics. State this in the README
  and on the Sources tab.

---

## 17. Testing and acceptance

Unit tests (HTTP always mocked):

- `naming`: every preset; unknown-token rejection; budget on all systems (parametrise
  folder depth and suffix); whole-word cut; non-Latin fallback; collision rules.
- `pdfread`: generated PDFs covering journal-name-plus-title layout, rotated arXiv stamp,
  cover page, no text, DOI only in XMP, DOI only in a non-standard Info key. No test may
  import PyMuPDF.
- `identify`: each source's field mapping from recorded JSON; fallback order with each
  source failing in turn; reference-DOI trap; title-search author test; offline rules
  including each author case in 6.4.
- `engine`: every row of section 14 that does not need the UI.
- `db`: migration from `state.json` + `history.csv`; corrupt-database handling.

Fixed regression cases (real papers used during prototyping):

| PDF | Expected |
|---|---|
| DOI `10.1016/j.aap.2025.108048` | 2025, Islam |
| DOI `10.1016/j.trc.2026.106087` | citation 2027, online 2026, Li |
| DOI `10.1016/j.trc.2025.105428` | citation 2026, online 2025, Ling |
| DOI `10.1177/03611981261468749` | 2026, Islam |
| DOI `10.1038/s41598-026-74874-w` | 2026, Islam |
| arXiv `1706.03762` | 2017, Vaswani |
| Page-1 "title" = "Journal Pre-proof" | Title search must not return an unrelated paper |
| PDF properties author "Naveen Eluru, Prof", printed line "Md Monzurul Islam*" | Offline author = Unknown |

A live `test-apis` run (not in CI) must show every configured source passing.

Local end-to-end check (not in CI): copy `sample_pdfs/` to a temporary folder, run a real
`scan` on the copy with live services, and review every resulting name by eye. Record the
old and new names in the work log. Any file left unidentified must be explained.

Acceptance for version 1: all unit tests pass on Windows and Linux in CI; a manual
pass of section 12 behaviours on Windows 11; installer installs, starts at login, and
uninstalls cleanly.

---

## 18. Build order

Follow `PROGRESS.md`, which lists these milestones as checkboxes. One milestone at a time.

| # | Milestone | Done when |
|---|---|---|
| M0 | Project setup: `.venv`, `pyproject.toml`, package skeleton, `pytest` runs, prototype files moved to `prototype/`, `sample_pdfs/` git-ignored | `pytest` passes with one placeholder test |
| M1 | Core, part 1: `config`, `db` (with migration), `lock`, `naming` (presets, custom templates, budget, collisions) | Unit tests for each pass |
| M2 | Core, part 2: `pdfread` on `pypdfium2`, `sources`, `identify` with the paper cache | Unit tests pass; regression table in section 17 passes |
| M3 | Core, part 3: `engine` (scan, dry run, reformat, undo, manual fix) and `watcher`, with the event interface | Every non-UI row of section 14 has a passing test |
| M4 | Minimal CLI: every command in section 11 | CLI tests pass; a real `scan --dry-run` works on a sample folder |
| M5 | **Tray app (priority 1):** runnable from source with `papernym-gui` from its first task; tray icon and menu, Activity, Folders, Naming, Sources, Needs attention, History, General, first-run flow | `papernym-gui --sandbox --show` works; manual checklist for section 12 passes on Windows 11 |
| M6 | **Windows exe:** local one-command build (PyInstaller, then Inno Setup installer), start at login, update check; then the GitHub Actions release workflow | Locally built exe runs in sandbox mode; installer installs, runs from the tray, uninstalls cleanly; a test tag produces the installer on a GitHub Release |
| M7 | **PyPI (priority 2):** README, LICENSE, CHANGELOG, build, TestPyPI upload, CI | `pip install` from TestPyPI works in a fresh venv |
| M8 | **Linux (priority 3):** run tests on Linux, fix path/tray/autostart differences | CI green on Ubuntu; tray app starts on a Linux desktop |

The CLI comes before the tray app only because it is a thin layer that makes the core
testable by hand; it must not delay M5.

---

## 19. Working agreement for whoever builds this

- **Virtual environment.** Create `.venv` in the project root (`python -m venv .venv`) and
  run everything through it. Never install into the system Python.
- **Prototype files are read-only.** Move `paper_renamer.py`, `test_apis.py`,
  `compare_sources.py`, `compare_pdf_libs.py` into `prototype/` and do not edit them.
  Leave `pdf_metadata.py` untouched.
- **Tests come with the code.** Every module gets tests in the same change. No test may use
  the network (mock HTTP) or touch real user files (use `tmp_path`). No test may import
  PyMuPDF.
- **`PROGRESS.md` is the memory between sessions.** Read it first, every session. Tick a
  checkbox only after its tests pass. After each task append a dated entry to its work log:
  what was done, files touched, test result, decisions made and why, and the next step.
- **Do not change the spec silently.** If something in `SPEC.md` is wrong or impossible,
  stop and say so; record the agreed change in the work log and in `SPEC.md`.
- **Dependencies.** Only those in section 2. Ask before adding any other.
- **`sample_pdfs/` holds real papers for local testing.** Never rename, edit or delete
  anything inside it: copy the files to a temporary folder and work on the copies. Keep the
  folder out of git (the papers are copyrighted) and out of the built package. Unit tests
  must pass without it; tests that use it are marked `local` and skip when it is absent.
- **Never touch the owner's real settings in tests or trial runs.** Point `PAPERNYM_HOME` at
  a temporary folder.
- **Version control.** `git init`; one commit per completed task with a clear message;
  `.venv`, `sample_pdfs/`, build output and `__pycache__` in `.gitignore`.
