"""Plain-text extraction for document formats that need no OCR."""

import re
from pathlib import Path


def extract_docx_text(file_path: Path) -> str:
    import docx

    doc = docx.Document(file_path)
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def extract_html_text(file_path: Path) -> str:
    from bs4 import BeautifulSoup

    html_content = file_path.read_text(encoding="utf-8", errors="replace")
    parts: list[str] = []

    saved_url_match = re.search(
        r'<!--\s*saved from url=\(\d+\)(.*?)\s*-->',
        html_content,
    )
    if saved_url_match:
        parts.append(f"Source URL: {saved_url_match.group(1).strip()}")

    soup = BeautifulSoup(html_content, "html.parser")

    if soup.title and soup.title.string:
        parts.append(f"Title: {soup.title.string.strip()}")

    for meta_name in ("description", "author", "keywords"):
        meta_tag = soup.find("meta", attrs={"name": lambda x: x and x.lower() == meta_name})
        if meta_tag and meta_tag.get("content"):
            parts.append(f"{meta_name.capitalize()}: {meta_tag.get('content').strip()}")

    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href") and not saved_url_match:
        parts.append(f"Canonical URL: {canonical.get('href').strip()}")

    if parts:
        parts.append("\n--- TESTO DEL SITO ---")

    parts.append(soup.get_text(separator="\n", strip=True))
    return "\n".join(parts)


def extract_rtf_text(file_path: Path) -> str:
    from striprtf.striprtf import rtf_to_text

    rtf_content = file_path.read_text(encoding="utf-8", errors="replace")
    return rtf_to_text(rtf_content)


def extract_xml_text(file_path: Path) -> str:
    """Estrae il testo leggibile da un file XML.

    Prova il parser XML della stdlib (ElementTree, testo dei nodi in ordine di
    documento); in fallback usa BeautifulSoup in modalita' lenient; ultimo
    fallback: contenuto grezzo. Nessuna dipendenza nuova.
    """
    raw = file_path.read_text(encoding="utf-8", errors="replace")

    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(raw)
        parts = [t.strip() for t in root.itertext() if t and t.strip()]
        text = "\n".join(parts)
        if text.strip():
            return text
    except Exception:
        pass

    try:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(raw, "html.parser").get_text("\n", strip=True)
        if text.strip():
            return text
    except Exception:
        pass

    return raw


def extract_doc_text(file_path: Path) -> str:
    """Estrae il testo da un file Word 97-2003 binario (.doc) legacy.

    python-docx apre solo il formato OOXML (.docx), non il vecchio .doc binario
    OLE2. Qui leggiamo direttamente lo stream ``WordDocument`` + la piece table
    (CLX/Pcdt) tramite ``olefile`` — gia' presente nel bundle come dipendenza di
    ``extract-msg``, pure-python e senza richiedere Word o LibreOffice. Se il file
    e' cifrato, danneggiato o in un layout non gestito, solleviamo un errore
    chiaro che invita a risalvarlo come .docx/.rtf.
    """
    import struct

    import olefile

    def _clean(text: str) -> str:
        for src, dst in (
            ("\r", "\n"), ("\x07", "\n"), ("\x0b", "\n"), ("\x0c", "\n"),
            ("\x1e", "-"), ("\xa0", " "),
            ("\x13", ""), ("\x14", ""), ("\x15", ""),
        ):
            text = text.replace(src, dst)
        text = re.sub(r'\s*HYPERLINK\s+("[^"]*"|\\l\s+"[^"]*"|\\h)\s*', " ", text)
        text = "".join(c for c in text if c >= " " or c in "\t\n")
        return re.sub(r"[ \t]{2,}", " ", text).strip()

    if not olefile.isOleFile(str(file_path)):
        raise RuntimeError(
            "Il file .doc non e' un documento Word 97-2003 valido (OLE2)."
        )

    ole = olefile.OleFileIO(str(file_path))
    try:
        if ole.exists("EncryptedPackage") or ole.exists("Encryption"):
            raise RuntimeError("documento .doc cifrato")
        if not ole.exists("WordDocument"):
            raise RuntimeError("stream WordDocument assente")

        wd = ole.openstream("WordDocument").read()
        if wd[:2] != b"\xec\xa5":  # magic 0xA5EC della FIB
            raise RuntimeError("intestazione FIB non valida")

        flags = struct.unpack_from("<H", wd, 0x000A)[0]
        if flags & 0x0100:  # fEncrypted
            raise RuntimeError("documento .doc cifrato")
        fc_min = struct.unpack_from("<i", wd, 0x0018)[0]
        fc_mac = struct.unpack_from("<i", wd, 0x001C)[0]
        table_name = "1Table" if (flags & 0x0200) else "0Table"

        text = ""
        if ole.exists(table_name):
            tbl = ole.openstream(table_name).read()
            fc_clx = struct.unpack_from("<i", wd, 0x01A2)[0]
            lcb_clx = struct.unpack_from("<i", wd, 0x01A6)[0]
            clx = tbl[fc_clx:fc_clx + lcb_clx]

            pcdt = None
            i = 0
            while i < len(clx):
                if clx[i] == 0x02:  # blocco Pcdt (piece table)
                    cb = struct.unpack_from("<I", clx, i + 1)[0]
                    pcdt = clx[i + 5:i + 5 + cb]
                    break
                if clx[i] == 0x01:  # Prc da saltare
                    cb = struct.unpack_from("<H", clx, i + 1)[0]
                    i += 3 + cb
                else:
                    break

            if pcdt:
                n = (len(pcdt) - 4) // 12
                cps = [struct.unpack_from("<I", pcdt, k * 4)[0] for k in range(n + 1)]
                base = (n + 1) * 4
                chunks = []
                for k in range(n):
                    fcf = struct.unpack_from("<I", pcdt, base + k * 8 + 2)[0]
                    compressed = bool(fcf & 0x40000000)
                    fc = fcf & 0x3FFFFFFF
                    length = cps[k + 1] - cps[k]
                    if compressed:  # cp1252, offset dimezzato
                        chunks.append(
                            wd[fc // 2: fc // 2 + length].decode("cp1252", "replace")
                        )
                    else:  # UTF-16LE
                        chunks.append(
                            wd[fc: fc + length * 2].decode("utf-16-le", "replace")
                        )
                text = "".join(chunks)

        if not text and 0 <= fc_min < fc_mac <= len(wd):
            # Documento non "complex" (nessuna piece table): testo contiguo cp1252.
            text = wd[fc_min:fc_mac].decode("cp1252", "replace")
    finally:
        ole.close()

    cleaned = _clean(text)
    # Se quasi tutto e' illeggibile, meglio un errore chiaro che testo-spazzatura.
    if not cleaned or cleaned.count("�") > len(cleaned) // 3:
        raise RuntimeError(
            "Impossibile estrarre testo leggibile dal .doc legacy (forse cifrato, "
            "danneggiato o in un formato non gestito). Salvalo come .docx o .rtf e "
            "riprova."
        )
    return cleaned
