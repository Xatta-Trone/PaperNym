"""Read temporary copies of local sample PDFs without changing the originals."""

import json
import os
import shutil
import tempfile
from pathlib import Path

from papernym.core.pdfread import find_dois, read_pdf


def main() -> int:
    source = Path(__file__).resolve().parents[1] / "sample_pdfs"
    if not source.is_dir():
        print("sample_pdfs/ is unavailable")
        return 1
    originals = sorted(source.rglob("*.pdf"))
    with tempfile.TemporaryDirectory(prefix="papernym-pdfread-") as work:
        root = Path(work)
        os.environ["PAPERNYM_HOME"] = str(root / "home")
        copies = root / "copies"
        copies.mkdir()
        print(f"COUNT {len(originals)}")
        for original in originals:
            copy = copies / original.name
            shutil.copy2(original, copy)
            info = read_pdf(copy)
            dois = info["md_dois"] or find_dois(info["text"])
            print(json.dumps({"file": original.name, "doi": dois[0] if dois else None,
                              "title": info["big_title"] or None,
                              "md_title": info["md_title"] or None}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
