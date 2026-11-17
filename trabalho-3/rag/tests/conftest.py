import pytest


def write_pdf(path, pages):
    # PDF mínimo com fonte padrão e uma linha de texto por página.
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for text in pages:
        number = len(objects) + 1
        page_ids.append(f"{number} 0 R")
        objects.append((
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {number + 1} 0 R >>"
        ).encode())
        stream = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode() if text else b""
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects[1] = f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(page_ids)}] >>".encode()
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(pdf)


@pytest.fixture(scope="module")
def pdf_corpus(tmp_path_factory):
    data = tmp_path_factory.mktemp("corpus")
    raw = data / "raw"
    raw.mkdir()
    write_pdf(raw / "Massas e bolos.PDF", ["Panqueca de milho. Ingredientes: milho e leite.", "", "Bolo de cenoura com farinha."])
    write_pdf(raw / "Ovos.pdf", ["Omelete. Ingredientes: ovos e queijo. Bata os ovos."])
    (raw / "Ignorar.html").write_text("<html>Fonte antiga</html>", encoding="utf-8")
    return data
