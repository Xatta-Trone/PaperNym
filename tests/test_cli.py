"""Command-line interface tests. HTTP is always faked; files live under tmp_path."""

import json
import os
import time

import pytest

from papernym.cli import main
from papernym.core.config import load_config
from papernym.core.db import Database
from papernym.core.lock import WriterLock
from papernym.core.naming import PRESETS
from papernym.core.sources.http import NetError

from .pdf_factory import make_pdf


DOI = "10.1234/abcd.5678"
TITLE = "Graph models of crash severity at rural intersections"
CSL = {"title": [TITLE], "issued": {"date-parts": [[2025]]},
       "author": [{"given": "Ann", "family": "Smith"}, {"family": "Jones"}],
       "container-title": ["Journal of Testing"]}


def fake_http(url, params=None, headers=None, kind="json"):
    if url == f"https://api.crossref.org/works/{DOI}":
        return {"message": CSL}
    return None


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("PAPERNYM_HOME", str(path))
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("S2_API_KEY", raising=False)
    return path


@pytest.fixture
def papers(tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    return folder


def run(capsys, *argv, http=fake_http):
    code = main(list(argv), http_get=http)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def paper_pdf(path, *, doi=True, title=TITLE):
    lines = [(title, 18, 72, 700, False), ("Ann Smith and Bob Jones", 11, 72, 670, False),
             ("Abstract. We study crash severity with graph models.", 10, 72, 640, False)]
    if doi:
        lines.append((f"https://doi.org/{DOI}", 9, 72, 60, False))
    make_pdf(path, [lines])
    old = time.time() - 3600  # settled file: no stability wait
    os.utime(path, (old, old))
    return path


EXPECTED = "2025_Smith_Graph_models_of_crash_severity_at_rural_intersections.pdf"


# Usage and help -----------------------------------------------------------------

def test_no_arguments_prints_help(home, capsys):
    code, out, _ = run(capsys)
    assert code == 0
    assert "add-folder" in out and "test-apis" in out


@pytest.mark.parametrize("argv", [["bogus"], ["set-year", "later"], 
                                  ["fix", "a.pdf"], ["undo", "--last", "0"]])
def test_usage_errors_exit_2(home, capsys, argv):
    code, _, _ = run(capsys, *argv)
    assert code == 2


# Settings commands --------------------------------------------------------------

def test_add_and_remove_folder(home, papers, capsys):
    code, out, _ = run(capsys, "add-folder", str(papers))
    assert code == 0 and out.startswith("[ok] watching ")
    assert load_config(home)["folders"] == [{"path": str(papers.resolve()), "recursive": True}]
    child = papers / "sub"
    child.mkdir()
    code, _, err = run(capsys, "add-folder", str(child))
    assert code == 1 and "already inside" in err and err.startswith("[warn]")
    code, _, _ = run(capsys, "remove-folder", str(papers))
    assert code == 0 and load_config(home)["folders"] == []
    code, _, err = run(capsys, "remove-folder", str(papers))
    assert code == 1 and "not a watched folder" in err
    code, _, _ = run(capsys, "add-folder", str(child), "--no-subfolders")
    assert code == 0 and load_config(home)["folders"][0]["recursive"] is False


def test_add_missing_folder_fails(home, tmp_path, capsys):
    code, _, err = run(capsys, "add-folder", str(tmp_path / "nope"))
    assert code == 1 and "not a folder" in err


def test_reference_manager_folder_warns(home, tmp_path, capsys):
    store = tmp_path / "Zotero" / "storage"
    store.mkdir(parents=True)
    code, out, _ = run(capsys, "add-folder", str(store))
    assert code == 0 and "[warn] Reference-manager" in out


def test_exclude_add_remove(home, capsys):
    assert run(capsys, "exclude", "Drafts/")[0] == 0
    assert "Drafts/" in load_config(home)["exclude"]
    code, out, _ = run(capsys, "exclude", "Drafts/")
    assert code == 0 and out.startswith("[skip]")
    assert run(capsys, "exclude", "--remove", "Drafts/")[0] == 0
    assert "Drafts/" not in load_config(home)["exclude"]
    assert run(capsys, "exclude", "--remove", "Drafts/")[0] == 1


def test_set_key_and_environment_keys_never_saved(home, capsys, monkeypatch):
    code, out, _ = run(capsys, "set-key", "openalex", "abc123")
    assert code == 0 and "saved in" in out and "abc123" not in out
    monkeypatch.setenv("S2_API_KEY", "from-env")
    code, out, _ = run(capsys, "set-key", "semanticscholar", "stored")
    assert "takes precedence" in out
    run(capsys, "set-year", "online")
    raw = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert raw["openalex_key"] == "" and raw["s2_key"] == ""  # keys live in the credential store
    stored = load_config(home, apply_env=False)
    assert stored["openalex_key"] == "abc123" and stored["s2_key"] == "stored"
    assert "set (in" in run(capsys, "show")[1]
    run(capsys, "set-key", "semanticscholar", "")
    assert load_config(home, apply_env=False)["s2_key"] == ""  # the environment key was not stored


def test_set_key_without_a_credential_store_warns_and_keeps_config(home, capsys, monkeypatch):
    monkeypatch.setenv("PAPERNYM_KEYRING", "off")
    code, out, _ = run(capsys, "set-key", "openalex", "abc123")
    assert code == 0 and "no system credential store" in out
    assert json.loads((home / "config.json").read_text(encoding="utf-8"))["openalex_key"] == "abc123"


def test_set_email(home, capsys):
    assert run(capsys, "set-email", "me@example.org")[0] == 0
    assert load_config(home)["email"] == "me@example.org"
    assert run(capsys, "set-email", "not-an-email")[0] == 1
    assert run(capsys, "set-email", "")[0] == 0
    assert load_config(home)["email"] == ""


def test_formats_lists_every_preset(home, capsys):
    code, out, _ = run(capsys, "formats")
    assert code == 0
    for name in PRESETS:
        assert name in out
    assert "* year_author_title" in out
    assert "Smith2025DeepLearningForCrashSeverityPrediction.pdf" in out


def test_set_format_preset_and_custom(home, capsys):
    code, out, _ = run(capsys, "set-format", "citekey")
    assert code == 0 and load_config(home)["format"] == "citekey"
    code, out, _ = run(capsys, "set-format", "author_year")
    assert code == 0 and "[warn]" in out
    code, out, _ = run(capsys, "set-format", "--custom", "[{journal}] {author} {year}", "--word-sep", "space")
    assert code == 0 and "[warn]" in out  # no title token
    config = load_config(home)
    assert config["format"] == "[{journal}] {author} {year}" and config["word_sep"] == " "
    _, out, _ = run(capsys, "formats")
    assert "* custom: [{journal}] {author} {year}" in out
    assert run(capsys, "set-format", "--custom", "{year}_{bogus}")[0] == 1
    assert run(capsys, "set-format", "nonsense")[0] == 1
    assert run(capsys, "set-format", "title_only", "--word-sep", "-")[0] == 1
    assert run(capsys, "set-format")[0] == 1
    assert load_config(home)["format"] == "[{journal}] {author} {year}"


def test_other_settings_and_show(home, papers, capsys):
    assert run(capsys, "set-year", "online")[0] == 0
    assert run(capsys, "set-title-search", "off")[0] == 0
    run(capsys, "add-folder", str(papers))
    config = load_config(home)
    assert (config["year"], config["title_search"]) == ("online", False)
    assert "title_limit" not in config
    code, out, _ = run(capsys, "show")
    assert code == 0
    assert f"Settings folder: {home}" in out
    assert str(papers.resolve()) in out
    assert "Title search: off" in out


def test_invalid_config_reports_failure(home, capsys):
    home.mkdir()
    (home / "config.json").write_text("{broken", encoding="utf-8")
    code, _, err = run(capsys, "show")
    assert code == 1 and "cannot read" in err


# Renaming commands --------------------------------------------------------------

def test_menu_entry_on_linux(home, tmp_path, capsys, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    entry = tmp_path / "share" / "applications" / "papernym.desktop"
    code, out, _ = run(capsys, "menu-entry")
    if code == 0:  # PySide6 installed (the test environment has it)
        assert entry.is_file() and "app menu" in out
    code, out, _ = run(capsys, "menu-entry", "--remove")
    assert code == 0 and not entry.exists()


def test_menu_entry_is_linux_only(home, capsys, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    code, _, err = run(capsys, "menu-entry")
    assert code == 1 and "Linux" in err


def test_scan_without_folders_says_so(home, capsys):
    code, out, _ = run(capsys, "scan")
    assert code == 0
    assert "no folders configured" in out and "Summary: 0 PDFs" in out


def test_dry_run_then_scan_then_undo(home, papers, capsys):
    pdf = paper_pdf(papers / "download.pdf")
    run(capsys, "add-folder", str(papers))
    code, out, _ = run(capsys, "scan", "--dry-run")
    assert code == 0
    assert f"[preview] download.pdf -> {EXPECTED}" in out
    assert "Summary: 1 PDFs, 1 would be renamed" in out
    assert pdf.exists()
    code, out, _ = run(capsys, "scan")
    assert code == 0
    assert f"[ok] download.pdf -> {EXPECTED}" in out
    assert out.strip().splitlines()[-1].startswith("Summary: 1 PDFs, 1 named")
    assert (papers / EXPECTED).exists() and not pdf.exists()
    assert f"[ok] download.pdf -> {EXPECTED}" in (home / "logs" / "papernym.log").read_text(encoding="utf-8")
    code, out, _ = run(capsys, "undo")
    assert code == 0 and f"[undo] {EXPECTED} -> download.pdf" in out
    assert pdf.exists()
    code, out, _ = run(capsys, "undo")
    assert code == 0 and "[skip] nothing to undo" in out


def test_undo_last_n(home, papers, capsys):
    paper_pdf(papers / "a.pdf")
    run(capsys, "add-folder", str(papers))
    run(capsys, "scan")
    code, out, _ = run(capsys, "undo", "--last", "1")
    assert code == 0 and "[undo]" in out and (papers / "a.pdf").exists()


def test_reformat_preview_and_apply(home, papers, capsys):
    paper_pdf(papers / "download.pdf")
    run(capsys, "add-folder", str(papers))
    run(capsys, "scan")
    run(capsys, "set-format", "author_year_title")
    new = "Smith_2025_Graph_models_of_crash_severity_at_rural_intersections.pdf"
    code, out, _ = run(capsys, "reformat", "--dry-run")
    assert code == 0 and f"[preview] {EXPECTED} -> {new}" in out
    assert "1 would be renamed" in out and (papers / EXPECTED).exists()
    code, out, _ = run(capsys, "reformat")
    assert code == 0 and f"[ok] {EXPECTED} -> {new}" in out and "1 renamed" in out
    assert (papers / new).exists()


def test_writer_lock_blocks_renaming_but_not_reads(home, papers, capsys):
    pdf = paper_pdf(papers / "download.pdf")
    run(capsys, "add-folder", str(papers))
    with WriterLock(home):
        for argv in (["scan"], ["reformat"], ["undo"], ["fix", str(pdf), "--doi", DOI]):
            code, _, err = run(capsys, *argv)
            assert code == 1 and "already running" in err, argv
        code, out, _ = run(capsys, "scan", "--dry-run")
        assert code == 0 and "[preview]" in out
        assert run(capsys, "set-year", "online")[0] == 0
        code, out, _ = run(capsys, "status")
        assert code == 0 and "Watcher: running" in out
        assert run(capsys, "show")[0] == 0
    assert pdf.exists()


def test_unknown_file_status_and_fix_by_doi(home, papers, capsys):
    pdf = paper_pdf(papers / "mystery.pdf", doi=False)
    run(capsys, "add-folder", str(papers))
    code, out, _ = run(capsys, "scan")
    assert code == 0 and "[?] mystery.pdf: paper not identified" in out
    assert "1 unidentified" in out
    code, out, _ = run(capsys, "status")
    assert code == 0 and "1 unidentified" in out
    assert f"[?] {pdf}" in out and "papernym fix" in out
    code, out, _ = run(capsys, "fix", str(pdf), "--doi", f"https://doi.org/{DOI.upper()}")
    assert code == 0 and f"[ok] mystery.pdf -> {EXPECTED}" in out
    assert (papers / EXPECTED).exists()
    code, out, _ = run(capsys, "status")
    assert "Nothing needs attention." in out


def test_fix_failures(home, papers, capsys):
    pdf = paper_pdf(papers / "mystery.pdf", doi=False)
    code, _, err = run(capsys, "fix", str(pdf), "--doi", DOI)
    assert code == 1 and "no record" in err
    run(capsys, "add-folder", str(papers))
    run(capsys, "scan")
    code, _, err = run(capsys, "fix", str(pdf), "--doi", "not-a-doi")
    assert code == 1 and "invalid DOI" in err
    code, out, _ = run(capsys, "fix", str(pdf), "--doi", "10.9999/unknown.1")
    assert code == 1 and "[?] mystery.pdf: DOI could not be verified" in out
    assert pdf.exists()


def test_outage_reports_source_warning(home, papers, capsys):
    paper_pdf(papers / "download.pdf")
    run(capsys, "add-folder", str(papers))

    def down(*_args, **_kwargs):
        raise NetError("offline")

    code, out, _ = run(capsys, "scan", http=down)
    assert code == 0
    assert "[warn] crossref unavailable: offline" in out
    assert "[check]" in out and "_CHECK.pdf" in out


# Diagnostics --------------------------------------------------------------------

S2 = {"title": "Mastering the game of Go with deep neural networks and tree search", "year": 2016,
      "authors": [{"name": "David Silver"}], "venue": "Nature", "publicationDate": "2016-01-27"}
S2_ARXIV = {"title": "Attention is all you need", "year": 2017,
            "authors": [{"name": "Ashish Vaswani"}], "venue": "NeurIPS", "publicationDate": "2017-06-12"}
GO_CSL = {"title": [S2["title"]], "issued": {"date-parts": [[2016]]}, "author": [{"family": "Silver"}]}
ARXIV_CSL = {"title": "Attention is all you need", "issued": {"date-parts": [[2017]]},
             "author": [{"family": "Vaswani"}]}
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Attention is all you need</title>
<published>2017-06-12T00:00:00Z</published><author><name>Ashish Vaswani</name></author></entry></feed>"""


def healthy_http(url, params=None, headers=None, kind="json"):
    if url == "https://api.crossref.org/works/10.1038/nature16961":
        return {"message": GO_CSL}
    if url == "https://api.crossref.org/works":
        return {"message": {"items": [GO_CSL]}}
    if url == "https://doi.org/10.1038/nature16961":
        return GO_CSL
    if url == "https://doi.org/10.48550/arXiv.1706.03762":
        return ARXIV_CSL
    if url.endswith("ARXIV:1706.03762"):
        return S2_ARXIV
    if url.endswith("search/match"):
        return {"data": [S2]}
    if "semanticscholar" in url:
        return S2
    if "export.arxiv.org" in url:
        return ATOM
    return None


def test_test_apis_pass_and_skip(home, capsys):
    code, out, _ = run(capsys, "test-apis", http=healthy_http)
    assert code == 0, out
    assert out.count("[ok] PASS") == 8 and out.count("[skip] SKIP") == 2
    assert "Summary: 8 passed, 0 failed, 2 skipped" in out


def test_test_apis_failures(home, capsys):
    def denied(*_args, **_kwargs):
        raise NetError("HTTP 403: key rejected or access denied", 403)

    code, out, _ = run(capsys, "test-apis", http=denied)
    assert code == 1
    assert "[warn] FAIL" in out and "key rejected" in out
    assert "everything failed" in out


def test_compare_renames_nothing(home, papers, capsys, monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "x")  # avoid the keyless rate-limit pause
    pdf = paper_pdf(papers / "download.pdf")
    code, out, _ = run(capsys, "compare", str(papers))
    assert code == 0
    assert f"DOIs found:   {DOI}" in out
    assert "crossref         2025 | Smith | Graph models" in out
    assert "openalex         skipped (no key)" in out
    assert pdf.exists() and not (home / "papers.db").exists()


def test_compare_without_folders_fails(home, capsys):
    code, _, err = run(capsys, "compare")
    assert code == 1 and "no folders configured" in err


def test_watch_stops_cleanly_on_ctrl_c(home, papers, capsys, monkeypatch):
    import papernym.core.watcher as watcher_module

    calls = []

    class FakeWatcher:
        def __init__(self, engine, *, poll=False):
            calls.append(("init", poll))

        def start(self):
            calls.append("start")

        def process_next(self, timeout=0):
            raise KeyboardInterrupt

        def tick(self):
            pass

        def stop(self):
            calls.append("stop")

    monkeypatch.setattr(watcher_module, "Watcher", FakeWatcher)
    run(capsys, "add-folder", str(papers))
    code, out, _ = run(capsys, "watch", "--poll")
    assert code == 0
    assert calls == [("init", True), "start", "stop"]
    assert "press Ctrl+C" in out and "[ok] stopped" in out


def test_watch_refuses_when_another_writer_runs(home, papers, capsys):
    run(capsys, "add-folder", str(papers))
    with WriterLock(home):
        code, _, err = run(capsys, "watch", "--poll")
    assert code == 1 and "already running" in err


def test_scan_one_folder_without_watching_it(home, papers, capsys, monkeypatch):
    sub = papers / "sub"
    sub.mkdir()
    paper_pdf(sub / "download.pdf")
    monkeypatch.chdir(papers)
    code, out, _ = run(capsys, "scan", ".", "--dry-run")
    assert code == 0 and "(with subfolders)" in out and f"[preview] download.pdf -> {EXPECTED}" in out
    code, out, _ = run(capsys, "scan", ".", "--no-subfolders")
    assert code == 0 and "Summary: 0 PDFs" in out and (sub / "download.pdf").exists()
    code, out, _ = run(capsys, "scan", ".")
    assert code == 0 and f"[ok] download.pdf -> {EXPECTED}" in out
    assert (sub / EXPECTED).exists()
    assert load_config(home)["folders"] == []
    code, out, _ = run(capsys, "undo")
    assert code == 0 and (sub / "download.pdf").exists()


def test_scan_folder_errors(home, tmp_path, capsys):
    code, _, err = run(capsys, "scan", str(tmp_path / "missing"))
    assert code == 1 and "not a folder" in err
    assert run(capsys, "scan", "--no-subfolders")[0] == 2


def test_scan_folder_respects_writer_lock(home, papers, capsys):
    pdf = paper_pdf(papers / "download.pdf")
    with WriterLock(home):
        code, _, err = run(capsys, "scan", str(papers))
    assert code == 1 and "already running" in err and pdf.exists()


class FakeTerminal:
    def __init__(self):
        self.parts = []

    def write(self, text):
        self.parts.append(text)

    def flush(self):
        pass

    def isatty(self):
        return True

    @property
    def text(self):
        return "".join(self.parts)


def test_colored_prefixes_on_terminal(home, papers, capsys):
    from papernym.cli import Output

    term = FakeTerminal()
    out = Output(term, term, color=True)
    out.line("a.pdf -> b.pdf", "ok")
    out.line("Summary: 1 PDFs, 1 named")
    out.error("broken")
    assert "\033[32m[ok]\033[0m a.pdf -> b.pdf" in term.text
    assert "\033[1mSummary: 1 PDFs, 1 named\033[0m" in term.text
    assert "\033[1;31m[warn]\033[0m broken" in term.text


def test_color_disabled_by_pipe_no_color_and_flag(home, papers, capsys, monkeypatch):
    from papernym.cli import use_color

    assert not use_color(FakeTerminal(), disabled=True)
    monkeypatch.setenv("NO_COLOR", "1")
    assert not use_color(FakeTerminal())
    monkeypatch.delenv("NO_COLOR")
    assert run(capsys, "show", "--no-color")[0] == 0
    assert run(capsys, "scan", "--no-color", "--dry-run")[0] == 0
    code, out, err = run(capsys, "--no-color", "show")
    assert code == 0 and "\033[" not in out
    paper_pdf(papers / "download.pdf")
    code, out, _ = run(capsys, "scan", str(papers))  # captured output is not a terminal
    assert code == 0 and "\033[" not in out and "[ok] download.pdf" in out
    assert "\033[" not in (home / "logs" / "papernym.log").read_text(encoding="utf-8")
