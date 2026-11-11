# Changelog

All notable changes to PaperNym. Versions follow [semantic versioning](https://semver.org).

## Unreleased

- Linux: a `.deb` package for Ubuntu 22.04+ and Debian 12+ on each release, with the tray
  app, the command line, an app-menu entry and icons. The tests now also run on Ubuntu.
- Linux pip/pipx installs add PaperNym to the app menu (`papernym menu-entry`, or
  automatically when the tray app starts).
- Linux: **Show in folder** selects the file in the file manager.
- Fixed: on a desktop without a tray, closing the window hid PaperNym with no way to bring
  it back; it now quits.
- Fixed: renaming failed on Linux drives without hard links (FAT/exFAT USB drives, some
  network shares).

## 0.1.3 — 2026-11-11

- README: install with `pip` or `pipx` from PyPI, PyPI version badge, uninstall for pip
  installs, and a layout that also renders correctly on the PyPI page.
- This changelog.

## 0.1.2 — 2026-11-11

First public release: the Windows installer on GitHub Releases and the package on PyPI.

- Tray app for Windows: watches folders and renames new paper PDFs from Crossref, doi.org,
  OpenAlex, Semantic Scholar and arXiv, with Activity, Needs attention, Folders, Naming,
  Sources, History, General and About tabs, light and dark themes, and Start at login.
- Command line `papernym` (scan, watch, undo, fix, reformat, formats, test-apis, compare
  and settings commands), sharing settings and history with the tray app.
- 15 name presets plus custom templates; undo for every rename; offline `_CHECK` naming
  that is fixed automatically later.
- API keys kept in the system credential store.
- Per-user Windows installer: always installs and registers the command line, optional
  Start at login, uninstaller that keeps your settings unless you ask.
- Update check against GitHub Releases (once a day; can be turned off).
- Fixed: reading the settings file while it is being saved could fail on Windows.
- Fixed: settings from the earlier prototype (`PaperRenamer`) with a title length stopped
  the app from starting.

## 0.1.1 and 0.1.0

Tagged but never published: their release builds failed in the test step. The fixes are in
0.1.2.
