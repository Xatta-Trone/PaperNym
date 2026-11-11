import argparse
import json
import re
from pathlib import Path

import fitz  # PyMuPDF


def inspect_pdf(pdf_path, show_xmp=False):
    pdf_path = Path(pdf_path).expanduser()

    if not pdf_path.is_file():
        print(f"File not found: {pdf_path}")
        return

    with fitz.open(pdf_path) as doc:
        if not doc.is_pdf:
            print("The specified file is not a PDF.")
            return

        if doc.needs_pass:
            print("The PDF is password-protected.")
            return

        print("\n" + "=" * 65)
        print(f"FILE: {pdf_path.name}")
        print("=" * 65)
        print(f"\nPages: {doc.page_count}")
        print(f"File size: {pdf_path.stat().st_size / 1024:.2f} KB")

        print("\n--- EMBEDDED PDF METADATA ---")
        metadata = doc.metadata or {}
        print(json.dumps(metadata, indent=2, ensure_ascii=False))

        print("\n--- DOI CANDIDATES (FIRST TWO PAGES) ---")
        text = "\n".join(
            doc[i].get_text("text")
            for i in range(min(2, doc.page_count))
        )

        doi_pattern = r"10\.\d{4,9}/[^\s<>\"'\[\]{}]+"
        dois = re.findall(doi_pattern, text, re.IGNORECASE)
        dois = list(dict.fromkeys(
            doi.rstrip(".,;)]") for doi in dois
        ))

        if dois:
            for doi in dois:
                print(f"DOI candidate: {doi}")
        else:
            print("No DOI detected in the first two pages.")

        if show_xmp:
            print("\n--- XMP METADATA ---")
            xmp = doc.get_xml_metadata()
            print(xmp if xmp else "No XMP metadata available.")

        print("\n--- FIRST-PAGE TEXT PREVIEW ---")
        if doc.page_count:
            lines = doc[0].get_text("text").splitlines()
            for line in lines[:25]:
                print(line)

        print("\n" + "=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Inspect metadata of a research PDF."
    )
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument(
        "--xmp",
        action="store_true",
        help="Display the full XMP metadata"
    )

    args = parser.parse_args()
    inspect_pdf(args.pdf, args.xmp)
