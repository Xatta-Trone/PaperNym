"""M0 smoke test for the editable package install."""

from papernym import __version__


def test_package_imports_with_single_version_source():
    assert __version__ == "0.1.0"
