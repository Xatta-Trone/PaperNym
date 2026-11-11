"""Generate small text PDFs for offline tests using only the standard library."""


def make_pdf(path, pages, metadata=None, xmp=""):
    """pages: list of pages; each page has (text, size, x, y, rotated)."""
    metadata = metadata or {}
    objects = [None, None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for lines in pages:
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        stream = b"\n".join(
            (f"BT /F1 {size} Tf " +
             (f"0 1 -1 0 {x} {y} Tm " if rotated else f"1 0 0 1 {x} {y} Tm ") +
             f"({text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')}) Tj ET")
            .encode("latin-1")
            for text, size, x, y, rotated in lines
        )
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode())
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{n} 0 R' for n in page_ids)}] /Count {len(page_ids)} >>".encode()
    info_id = len(objects) + 1
    info = "<< " + " ".join(f"/{key} ({value})" for key, value in metadata.items()) + " >>"
    objects.append(info.encode("latin-1"))
    if xmp:
        packet = xmp.encode("utf-8")
        objects.append(f"<< /Type /Metadata /Subtype /XML /Length {len(packet)} >>\nstream\n".encode()
                       + packet + b"\nendstream")
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_id} 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    path.write_bytes(output)
    return path
