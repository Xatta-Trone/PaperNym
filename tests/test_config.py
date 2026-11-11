import json

import pytest

from papernym.core import config


def test_defaults_are_independent_and_do_not_create_files(tmp_path):
    first = config.load_config(tmp_path)
    first["folders"].append({"path": "X:/Papers", "recursive": True})
    assert config.load_config(tmp_path)["folders"] == []
    assert not list(tmp_path.iterdir())
    assert config.load_config(tmp_path)["format"] == "{year}_{author}_{title}"


def test_round_trip_and_environment_overrides(tmp_path, monkeypatch):
    saved = config.default_config()
    saved["folders"] = [{"path": "X:/Papers", "recursive": False}]
    saved["openalex_key"] = "stored"
    config.save_config(saved, tmp_path)
    monkeypatch.setenv("PAPERNYM_HOME", str(tmp_path))
    monkeypatch.setenv("OPENALEX_API_KEY", "env-key")
    monkeypatch.setenv("S2_API_KEY", "s2-env")
    loaded = config.load_config()
    assert loaded["folders"] == saved["folders"]
    assert loaded["openalex_key"] == "env-key"
    assert loaded["s2_key"] == "s2-env"
    assert json.loads((tmp_path / "config.json").read_text())["openalex_key"] == "stored"


@pytest.mark.parametrize("change", [
    {"title_limit": -1}, {"title_limit": True}, {"year": "maybe"},
    {"word_sep": "/"}, {"paused": "no"}, {"folders": [{"path": "x"}]},
    {"exclude": [1]}, {"format": "{bogus}"}, {"format": "plain"},
    {"format": "{year}/bad"}, {"format": "{year}" + "x" * 61},
])
def test_invalid_settings_rejected(change):
    with pytest.raises(config.ConfigError):
        config.validate_config(change)


def test_atomic_replace_failure_preserves_prior_settings(tmp_path, monkeypatch):
    config.save_config(config.default_config(), tmp_path)
    path = tmp_path / "config.json"
    original = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(config.os, "replace", fail_replace)
    changed = config.default_config()
    changed["paused"] = True
    with pytest.raises(OSError, match="simulated"):
        config.save_config(changed, tmp_path)
    assert path.read_bytes() == original
    assert len(list(tmp_path.iterdir())) == 1


def test_invalid_json_is_reported(tmp_path):
    (tmp_path / "config.json").write_text("{", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="cannot read"):
        config.load_config(tmp_path)


def test_folder_overlap_rejected_or_merged(tmp_path):
    parent = tmp_path / "Papers"
    child = parent / "Articles"
    child.mkdir(parents=True)
    cfg = config.add_folder(config.default_config(), parent)
    with pytest.raises(config.ConfigError, match="already inside"):
        config.add_folder(cfg, child)
    cfg = config.add_folder(config.default_config(), child)
    merged = config.add_folder(cfg, parent)
    assert merged["folders"] == [{"path": str(parent.resolve()), "recursive": True}]
    nonrecursive = config.add_folder(config.default_config(), parent, recursive=False)
    assert len(config.add_folder(nonrecursive, child)["folders"]) == 2


def test_reference_manager_warning_does_not_block(tmp_path):
    store = tmp_path / "Zotero" / "storage"
    store.mkdir(parents=True)
    warnings = []
    cfg = config.add_folder(config.default_config(), store, on_warning=warnings.append)
    assert cfg["folders"][0]["path"] == str(store.resolve())
    assert len(warnings) == 1
