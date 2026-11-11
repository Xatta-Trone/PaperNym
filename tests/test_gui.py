"""Tray app tests: offscreen Qt, fake HTTP, fake observer, files under tmp_path."""

import os
import sys
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtNetwork import QLocalServer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from papernym.core import autostart  # noqa: E402
from papernym.core.config import add_folder, default_config, load_config, save_config  # noqa: E402
from papernym.core.lock import WriterLock  # noqa: E402
from papernym.gui import app as gui_app  # noqa: E402
from papernym.gui.app import Controller, server_name, signal_existing  # noqa: E402
from papernym.gui.dialogs import PreviewDialog, WelcomeWizard  # noqa: E402

from .test_cli import EXPECTED, fake_http, paper_pdf  # noqa: E402
from .test_watcher import FakeObserver  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def wait(qapp, condition, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return condition()


@pytest.fixture
def make_ctl(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("S2_API_KEY", raising=False)
    made = []

    def build(folder=None, *, first_run=False, http=fake_http, config=None):
        home = tmp_path / "home"
        settings = config or default_config()
        if folder is not None:
            settings = add_folder(settings, folder)
        save_config(settings, home)
        ctl = Controller(home, http_get=http, interactive=False, first_run=first_run,
                         worker_kwargs={"observer": FakeObserver(), "stable_fn": lambda _: True})
        ready = []
        ctl.worker.ready.connect(lambda: ready.append(True))
        assert wait(qapp, lambda: ready or ctl.worker.isFinished())
        made.append(ctl)
        return ctl

    yield build
    for ctl in made:
        if ctl.worker.isRunning():
            ctl.quit()


def call(qapp, ctl, function):
    box = {}
    ctl.worker.call(function, lambda result: box.setdefault("ok", result),
                    lambda message: box.setdefault("error", message))
    assert wait(qapp, lambda: box), "worker job did not finish"
    if "error" in box:
        raise AssertionError(box["error"])
    return box["ok"]


def test_startup_scan_shows_activity_history_and_undo(qapp, make_ctl, tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    paper_pdf(folder / "download.pdf")
    ctl = make_ctl(folder)
    assert wait(qapp, lambda: (folder / EXPECTED).exists())
    activity = ctl.window.activity.table
    assert wait(qapp, lambda: activity.model.rowCount() >= 1)
    first = activity.model.rows[0]
    assert first["status"] == "Renamed" and first["new"] == EXPECTED
    assert not ctl.window.activity.buttons[0].isEnabled()
    activity.view.selectRow(0)
    assert all(button.isEnabled() for button in ctl.window.activity.buttons)
    assert ctl.recent[0][1].endswith(EXPECTED)
    assert wait(qapp, lambda: ctl.window.history.tree.topLevelItemCount() == 1)
    batch = ctl.window.history.tree.topLevelItem(0)
    assert "1 rename(s)" in batch.text(0) and "undone" not in batch.text(0)
    assert batch.data(0, Qt.UserRole)  # the live history ids
    ctl.undo_last()
    assert wait(qapp, lambda: (folder / "download.pdf").exists())
    assert wait(qapp, lambda: "all undone" in ctl.window.history.tree.topLevelItem(0).text(0))
    assert ctl.tray_state()[0] == "watching"


def test_attention_list_badge_and_ignore(qapp, make_ctl, tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    pdf = paper_pdf(folder / "mystery.pdf", doi=False)
    ctl = make_ctl(folder)
    assert wait(qapp, lambda: ctl.attention_count == 1)
    assert ctl.tray_state() == ("attention", "1 file(s) need attention")
    assert "Needs attention (1)" in ctl.attention_action.text()
    table = ctl.window.attention.table
    assert table.model.data(table.model.index(0, 1)) == "Not identified"
    assert not ctl.window.attention.doi_button.isEnabled()
    table.view.selectRow(0)
    assert ctl.window.attention.doi_button.isEnabled()
    call(qapp, ctl, lambda w: w.engine.keep_name(str(pdf)))
    ctl.refresh_attention()
    assert wait(qapp, lambda: ctl.attention_count == 0)
    assert pdf.exists()
    call(qapp, ctl, lambda w: w.scan_now())
    assert pdf.exists() and ctl.attention_count == 0


def test_manual_fix_by_doi_from_attention(qapp, make_ctl, tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    pdf = paper_pdf(folder / "mystery.pdf", doi=False)
    ctl = make_ctl(folder)
    assert wait(qapp, lambda: ctl.attention_count == 1)
    result = call(qapp, ctl, lambda w: w.engine.fix(str(pdf), doi="10.1234/abcd.5678"))
    assert result.path.name == EXPECTED


def test_preview_ticked_renamed_unticked_kept(qapp, make_ctl, tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    ctl = make_ctl()
    a = paper_pdf(folder / "a.pdf")
    b = paper_pdf(folder / "b.pdf")
    folder_entry = add_folder(ctl.config, folder)["folders"][-1]
    items = call(qapp, ctl, lambda w: w.preview_folders([folder_entry]))
    assert sorted(os.path.basename(i["old_path"]) for i in items) == ["a.pdf", "b.pdf"]
    assert a.exists() and b.exists()
    dialog = PreviewDialog("t", "i", items)
    assert dialog.count.text() == "2 of 2 selected"
    dialog.tree.topLevelItem(1).setCheckState(0, Qt.Unchecked)
    assert dialog.selected() == [items[0]["old_path"]] and dialog.unselected() == [items[1]["old_path"]]
    config = add_folder(ctl.config, folder)
    counts = call(qapp, ctl, lambda w: w.apply_selection(dialog.selected(), dialog.unselected(), config))
    assert counts == {"renamed": 1, "kept": 1, "other": 0}
    assert (folder / EXPECTED).exists() and b.exists()
    call(qapp, ctl, lambda w: w.scan_now())
    assert b.exists(), "an unticked file must keep its name"
    assert load_config(ctl.home)["folders"][0]["path"] == str(folder.resolve())


def test_naming_tab_validation_and_reformat_preview(qapp, make_ctl, tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    paper_pdf(folder / "download.pdf")
    ctl = make_ctl(folder)
    assert wait(qapp, lambda: (folder / EXPECTED).exists())
    naming = ctl.window.naming
    assert not naming.save_button.isEnabled()
    naming.preset.setCurrentIndex(naming.preset.findData(None))
    assert not naming.template.isReadOnly()
    naming.template.setText("{year}_{bogus}")
    assert "cannot be saved" in naming.message.text() and not naming.save_button.isEnabled()
    naming.template.setText("[Lab] {author} {year}")
    assert naming.save_button.isEnabled() and "no title token" in naming.message.text()
    assert "[Lab] Smith 2025.pdf" in naming.preview.text()
    naming.preset.setCurrentIndex(naming.preset.findData("author_year_title"))
    assert "Smith_2025_Deep_learning" in naming.preview.text()
    saved = []
    ctl.save_settings({**ctl.config, "format": "author_year_title"}, saved.append)
    assert wait(qapp, lambda: saved)
    assert call(qapp, ctl, lambda w: w.tool_named_count()) == 1
    items = call(qapp, ctl, lambda w: w.preview_reformat(False))
    assert len(items) == 1 and os.path.basename(items[0]["new_path"]).startswith("Smith_2025_")


def test_banners_pause_and_folder_error_state(qapp, make_ctl, tmp_path):
    ctl = make_ctl()
    ctl.on_event({"type": "source_unavailable", "path": "", "source": "crossref",
                  "message": "crossref unavailable: offline"})
    assert not ctl.window.outage.isHidden() and "_CHECK" in ctl.window.outage.label.text()
    ctl.on_event({"type": "source_unavailable", "path": "", "source": "openalex",
                  "message": "openalex unavailable: HTTP 403: key rejected or access denied"})
    assert not ctl.window.sources.banner.isHidden()
    assert ctl.tray_state()[0] == "attention"
    ctl.toggle_pause()
    assert wait(qapp, lambda: ctl.config["paused"])
    assert ctl.tray_state()[0] == "paused" and "Resume" in ctl.pause_action.text()
    assert load_config(ctl.home)["paused"] is True
    ctl.config["folders"] = [{"path": str(tmp_path / "gone"), "recursive": True}]
    ctl.folder_states_changed({str(tmp_path / "gone"): False})
    assert ctl.tray_state()[0] == "error"


def test_scan_notifications_are_batched(qapp, make_ctl, monkeypatch):
    ctl = make_ctl()
    shown = []
    monkeypatch.setattr(ctl, "notify", lambda title, text, critical=False: shown.append(title))
    ctl.on_event({"type": "scan_started", "path": ".", "message": "", "total": 5})
    assert ctl.tray_state()[0] == "working"
    for index in range(5):
        ctl.on_event({"type": "renamed", "path": f"n{index}.pdf", "new_path": f"n{index}.pdf",
                      "old_path": f"o{index}.pdf", "source": "crossref", "message": ""})
    ctl.on_event({"type": "unidentified", "path": "x.pdf", "message": "paper not identified"})
    assert shown == []
    ctl.on_event({"type": "scan_finished", "path": ".", "message": "", "counts": {}})
    assert shown == ["5 papers renamed"]  # one toast, attention count included in its text
    for index in range(3):  # a burst outside a scan waits for a quiet spell
        ctl.on_event({"type": "renamed", "path": f"z{index}.pdf", "new_path": f"z{index}.pdf",
                      "old_path": f"y{index}.pdf", "source": "crossref", "message": ""})
    assert shown == ["5 papers renamed"] and ctl._toast_timer.isActive()
    ctl._flush_toast()
    assert shown == ["5 papers renamed", "3 papers renamed"]
    ctl.on_event({"type": "renamed", "path": "one.pdf", "new_path": "one.pdf", "old_path": "x.pdf",
                  "source": "crossref", "message": ""})
    ctl._flush_toast()
    assert shown[-1] == "Paper renamed"


def test_lock_held_elsewhere_is_fatal(qapp, tmp_path, monkeypatch):
    home = tmp_path / "home"
    save_config(default_config(), home)
    with WriterLock(home):
        ctl = Controller(home, interactive=False, first_run=False,
                         worker_kwargs={"observer": FakeObserver()})
        messages = []
        ctl.worker.fatal.connect(messages.append)
        assert wait(qapp, lambda: ctl.worker.isFinished())
        qapp.processEvents()
    assert ctl.quitting


def test_single_instance_signal(qapp, tmp_path):
    name = server_name(tmp_path)
    assert name == server_name(tmp_path) and name.startswith("PaperNym-")
    assert not signal_existing(name)
    server = QLocalServer()
    assert server.listen(name)
    received = []
    server.newConnection.connect(lambda: received.append(server.nextPendingConnection()))
    assert signal_existing(name)
    assert wait(qapp, lambda: received)
    server.close()


def test_sandbox_copies_samples(tmp_path, monkeypatch):
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "one.pdf").write_bytes(b"%PDF")
    (samples / "notes.txt").write_text("x")
    monkeypatch.setattr(gui_app, "REPO_SAMPLES", samples)
    home, papers, count = gui_app.make_sandbox()
    assert count == 1 and (papers / "one.pdf").exists() and home.is_dir()
    assert (samples / "one.pdf").exists()


def test_welcome_wizard_preview(qapp, tmp_path):
    wizard = WelcomeWizard([str(tmp_path)])
    assert wizard.folders() == [str(tmp_path)]
    wizard.preset.setCurrentIndex(wizard.preset.findData("citekey"))
    assert wizard.chosen_preset() == "citekey"
    assert "Smith2025DeepLearningForCrashSeverityPrediction.pdf" in wizard.preview.text()


def test_first_run_flag(qapp, make_ctl, tmp_path):
    ctl = make_ctl(first_run=True)
    assert ctl.first_run


def test_autostart_linux_desktop_file(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(autostart, "os", SimpleNamespace(name="posix", environ=os.environ))
    monkeypatch.setattr(autostart, "launch_command", lambda: '"python" -m papernym.gui')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    autostart.set_enabled(True)
    desktop = tmp_path / "autostart" / "papernym.desktop"
    assert "papernym.gui" in desktop.read_text(encoding="utf-8") and autostart.is_enabled()
    autostart.set_enabled(False)
    assert not desktop.exists() and not autostart.is_enabled()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")
def test_autostart_windows_registry(monkeypatch):
    values = {}

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    class FakeWinreg:
        HKEY_CURRENT_USER = 1
        REG_SZ = 1

        def CreateKey(self, *_):
            return Key()

        def OpenKey(self, *_):
            return Key()

        def SetValueEx(self, _key, name, _reserved, _kind, value):
            values[name] = value

        def DeleteValue(self, _key, name):
            del values[name]

        def QueryValueEx(self, _key, name):
            if name not in values:
                raise FileNotFoundError(name)
            return values[name], 1

    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg())
    autostart.set_enabled(True)
    assert "papernym.gui" in values["PaperNym"] and autostart.is_enabled()
    autostart.set_enabled(False)
    assert not autostart.is_enabled()


def test_first_run_preview_uses_chosen_format(qapp, make_ctl, tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    pdf = paper_pdf(folder / "download.pdf")
    ctl = make_ctl()
    config = add_folder({**ctl.config, "format": "author_year_title"}, folder)
    items = call(qapp, ctl, lambda w: w.preview_folders(config["folders"], config))
    expected = "Smith_2025_Graph_models_of_crash_severity_at_rural_intersections.pdf"
    assert [os.path.basename(item["new_path"]) for item in items] == [expected]
    assert pdf.exists() and ctl.worker.engine.config["format"] != "author_year_title"
    call(qapp, ctl, lambda w: w.apply_selection([str(pdf)], [], config))
    assert (folder / expected).exists()


def test_paged_table_search_filter_and_pages(qapp):
    from papernym.gui.table import PagedTable

    table = PagedTable([("Name", lambda r: r["name"]), ("Status", lambda r: r["status"])],
                       name="t", search_text=lambda r: r["name"], statuses=["A", "B"],
                       status_of=lambda r: r["status"], page_size=50)
    table.set_rows([{"name": f"paper_{i:04d}.pdf", "status": "A" if i % 2 else "B"} for i in range(1234)])
    assert table.model.rowCount() == 50 and "1-50 of 1234" in table.position.text()
    table._go("last")
    assert table.model.rowCount() == 34 and "Page 25 of 25" in table.position.text()
    table.search.setText("paper_12")
    assert len(table.matches) == 34 and table.page == 0  # 0120-0129 and 1200-1233
    table.status.setCurrentIndex(table.status.findData("A"))
    assert all(row["status"] == "A" for row in table.matches) and len(table.matches) == 17
    table.search.setText("nothing like this")
    assert table.model.rowCount() == 0 and "No matches" in table.position.text()


def test_sources_labels_have_no_literal_ampersand(qapp, make_ctl):
    from PySide6.QtWidgets import QLabel

    ctl = make_ctl()
    sources = ctl.window.sources
    labels = {label.buddy(): label for label in sources.findChildren(QLabel) if label.buddy()}
    assert labels[sources.openalex].text() == "&OpenAlex key"  # & marks the Alt key, not shown
    assert labels[sources.s2].text() == "Semantic &Scholar key"


def test_welcome_wizard_start_at_login_choice(qapp):
    assert WelcomeWizard([]).start_at_login() is True
    assert WelcomeWizard([], allow_login=False).start_at_login() is False


def test_activity_buttons_open_reveal_refresh_and_undo(qapp, make_ctl, tmp_path, monkeypatch):
    from papernym.gui import tabs

    opened, revealed = [], []
    monkeypatch.setattr(tabs, "open_path", opened.append)
    monkeypatch.setattr(tabs, "show_in_folder", revealed.append)
    folder = tmp_path / "papers"
    folder.mkdir()
    paper_pdf(folder / "download.pdf")
    ctl = make_ctl(folder)
    activity = ctl.window.activity
    assert wait(qapp, lambda: activity.table.model.rowCount() >= 1)
    activity.table.view.selectRow(0)
    open_button, reveal_button, undo_button, refresh_button = activity.buttons
    open_button.click()
    reveal_button.click()
    assert opened == revealed == [str(folder / EXPECTED)]
    refresh_button.click()
    assert wait(qapp, lambda: EXPECTED in ctl.window.statusBar().currentMessage()
                and "Refreshing" not in ctl.window.statusBar().currentMessage())
    activity.table.view.selectRow(0)
    undo_button.click()
    assert wait(qapp, lambda: (folder / "download.pdf").exists())
    assert wait(qapp, lambda: activity.table.model.rows[0]["status"] == "Undone")
    activity.table.view.selectRow(1)  # the original rename row can no longer be undone
    assert not undo_button.isEnabled() and open_button.isEnabled()
    open_button.click()  # the renamed file is gone: a message, not a silent failure
    assert "no longer there" in ctl.window.statusBar().currentMessage()
    assert len(opened) == 1


def test_added_folder_waits_for_its_preview(qapp, make_ctl, tmp_path):
    ctl = make_ctl()
    folder = tmp_path / "later"
    folder.mkdir()
    paper_pdf(folder / "download.pdf")
    config = add_folder(ctl.config, folder)
    saved = call(qapp, ctl, lambda w: w.add_held_folder(config))
    assert [f["path"] for f in saved["folders"]] == [str(folder.resolve())]  # listed at once
    call(qapp, ctl, lambda w: (w.watcher.enqueue(str(folder / "download.pdf")), w.watcher.tick(10**9)))
    qapp.processEvents()
    time.sleep(0.5)
    qapp.processEvents()
    assert (folder / "download.pdf").exists()  # held: no scan, no event processing
    items = call(qapp, ctl, lambda w: w.preview_held_folder(str(folder.resolve())))
    assert [os.path.basename(item["new_path"]) for item in items] == [EXPECTED]
    assert (folder / "download.pdf").exists()  # a preview renames nothing

    def confirm(w):
        counts = w.apply_selection([items[0]["path"]], [], None)
        w.release_folder(str(folder.resolve()))
        return counts

    assert call(qapp, ctl, confirm)["renamed"] == 1
    assert (folder / EXPECTED).exists() and not call(qapp, ctl, lambda w: w.watcher.held)


def test_closing_the_preview_removes_the_added_folder(qapp, make_ctl, tmp_path):
    ctl = make_ctl()
    folder = tmp_path / "maybe"
    folder.mkdir()
    paper_pdf(folder / "download.pdf")
    call(qapp, ctl, lambda w: w.add_held_folder(add_folder(ctl.config, folder)))
    saved = call(qapp, ctl, lambda w: w.drop_folder(str(folder.resolve())))
    assert saved["folders"] == [] and (folder / "download.pdf").exists()
    assert load_config(ctl.home)["folders"] == []


def test_second_sandbox_launch_shows_the_first(monkeypatch):
    asked = []
    monkeypatch.setattr(gui_app, "signal_existing", lambda name: asked.append(name) or True)
    monkeypatch.setattr(gui_app, "make_sandbox", lambda: pytest.fail("a second sandbox was created"))
    assert gui_app.main(["--sandbox"]) == 0
    assert asked == [gui_app.SANDBOX_SERVER]


def test_theme_switch_from_general_tab(qapp, make_ctl):
    ctl = make_ctl()
    general = ctl.window.general
    assert general.theme.currentData() == "system"
    general.theme.setCurrentIndex(general.theme.findData("dark"))
    assert wait(qapp, lambda: ctl.config["theme"] == "dark" and qapp.property("papernymDark") is True)
    assert load_config(ctl.home)["theme"] == "dark"
    general.theme.setCurrentIndex(general.theme.findData("light"))
    assert wait(qapp, lambda: qapp.property("papernymDark") is False)


def test_theme_setting_is_validated(tmp_path):
    from papernym.core.config import ConfigError, validate_config

    with pytest.raises(ConfigError):
        validate_config({**default_config(), "theme": "purple"})
    assert default_config()["theme"] == "system"


def test_update_check_shows_banner_tray_item_and_skip(qapp, make_ctl):
    release = {"tag_name": "v9.9.9", "html_url": "https://github.com/Xatta-Trone/papernym/releases/tag/v9.9.9"}

    def http(url, params=None, headers=None, kind="json"):
        return release if "api.github.com" in url else fake_http(url, params, headers, kind)

    ctl = make_ctl(http=http)
    ctl.check_updates(manual=True)
    assert wait(qapp, lambda: ctl.update_info is not None)
    assert ctl.update_action.isVisible() and "v9.9.9" in ctl.update_action.text()
    assert ctl.window.update_banner.isVisibleTo(ctl.window) and "9.9.9 is available" in ctl.window.update_banner.label.text()
    assert "9.9.9 is available" in ctl.window.about.update_status.text()
    ctl.window.update_banner.skip.click()
    assert wait(qapp, lambda: ctl.config["skipped_version"] == "9.9.9")
    ctl.window.update_banner.hide()
    ctl.update_info = None
    ctl.check_updates(manual=False)  # automatic check: the skipped version stays quiet
    assert wait(qapp, lambda: ctl.update_info is not None)
    assert not ctl.window.update_banner.isVisibleTo(ctl.window) and ctl.update_action.isVisible()


def test_update_check_failure_is_reported_only_on_the_about_tab(qapp, make_ctl):
    def offline(url, params=None, headers=None, kind="json"):
        if "api.github.com" in url:
            raise OSError("network unreachable")
        return fake_http(url, params, headers, kind)

    ctl = make_ctl(http=offline)
    ctl.check_updates(manual=True)
    assert wait(qapp, lambda: "Could not check" in ctl.window.about.update_status.text())
    assert ctl.window.about.check_button.isEnabled() and not ctl.update_action.isVisible()


def test_settings_folder_is_shown_only_in_debug_mode(qapp, make_ctl, monkeypatch):
    from PySide6.QtWidgets import QLabel, QPushButton

    ctl = make_ctl()
    texts = [w.text() for w in ctl.window.general.findChildren(QPushButton)] + [w.text() for w in ctl.window.general.findChildren(QLabel)]
    assert not any("settings folder" in t.lower() for t in texts)
    assert not any(str(ctl.home) in t for t in texts)
    ctl.debug = True
    from papernym.gui.tabs import GeneralTab
    debug_tab = GeneralTab(ctl)
    texts = [w.text() for w in debug_tab.findChildren(QPushButton)] + [w.text() for w in debug_tab.findChildren(QLabel)]
    assert any("settings folder" in t.lower() for t in texts)


def test_diagnostics_hide_keys_email_and_settings_path(tmp_path):
    from papernym.gui.tabs import mask_diagnostics

    home = tmp_path / "PaperNym"
    log = (f"GET /works?search=x&api_key=SECRET1 failed\nUser-Agent mailto:me@example.org\n"
           f"database at {home}" + "\\papers.db")
    masked = mask_diagnostics(log, home)
    assert "SECRET1" not in masked and "me@example.org" not in masked and str(home) not in masked
    assert "<settings>" in masked and "api_key=***" in masked


def test_sources_key_fields_are_hidden_and_say_where_keys_live(qapp, make_ctl):
    from PySide6.QtWidgets import QLineEdit

    ctl = make_ctl()
    sources = ctl.window.sources
    assert sources.openalex.echoMode() == QLineEdit.PasswordEchoOnEdit
    assert "not in the settings file" in sources.key_store.text()
