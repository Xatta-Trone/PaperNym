"""M0 smoke test for the editable package install."""

import re

from papernym import __version__


def test_package_imports_with_single_version_source():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
