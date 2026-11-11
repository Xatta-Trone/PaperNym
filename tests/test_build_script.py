import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("build_windows", ROOT / "scripts" / "build_windows.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_matches_the_package():
    import papernym

    assert load().version() == papernym.__version__


def test_version_file_has_four_numbers(tmp_path, monkeypatch):
    build = load()
    monkeypatch.setattr(build, "BUILD", tmp_path)
    text = build.version_file("1.2.3").read_text(encoding="utf-8")
    assert "filevers=(1, 2, 3, 0)" in text and "StringStruct('ProductVersion', '1.2.3')" in text


def test_clean_path_keeps_only_python_and_windows(monkeypatch):
    build = load()
    monkeypatch.setenv("PATH", r"C:\Users\me\anaconda3\Library\bin;C:\msys64\usr\bin")
    path = build.clean_path().lower()
    assert "anaconda" not in path and "msys" not in path
    assert str(Path(sys.executable).parent).lower() in path


def test_tag_must_match_version(monkeypatch):
    build = load()
    monkeypatch.setattr(sys, "argv", ["build_windows.py", "--expected-version", "v99.0.0"])
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(SystemExit, match="version mismatch"):
        build.main()
