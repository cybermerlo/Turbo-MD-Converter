"""Test degli estrattori di testo per i formati a lettura diretta
(pipeline/text_extractors.py): nuovi formati .xml e .doc legacy."""

import tempfile
import unittest
from pathlib import Path

from pipeline.text_extractors import extract_doc_text, extract_xml_text

_FIXTURE_DOC = Path(__file__).parent / "fixtures" / "sample_legacy.doc"


class ExtractXmlTests(unittest.TestCase):
    def test_extracts_node_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "dati.xml"
            p.write_text(
                "<?xml version='1.0'?>\n<root><a>Alfa</a><b>Beta</b></root>",
                encoding="utf-8",
            )
            text = extract_xml_text(p)
        self.assertIn("Alfa", text)
        self.assertIn("Beta", text)

    def test_malformed_xml_falls_back_to_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "rotto.xml"
            # XML non ben formato: il fallback lenient/raw deve comunque dare testo.
            p.write_text("<root><a>Contenuto</b></root", encoding="utf-8")
            text = extract_xml_text(p)
        self.assertIn("Contenuto", text)

    def test_namespaced_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ns.xml"
            p.write_text(
                "<n:doc xmlns:n='urn:x'><n:t>Testo con namespace</n:t></n:doc>",
                encoding="utf-8",
            )
            text = extract_xml_text(p)
        self.assertIn("Testo con namespace", text)


class ExtractDocLegacyTests(unittest.TestCase):
    def test_non_ole_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "finto.doc"
            p.write_bytes(b"questo non e' un file OLE2")
            with self.assertRaises(RuntimeError):
                extract_doc_text(p)

    @unittest.skipUnless(
        _FIXTURE_DOC.exists(),
        "fixture sample_legacy.doc assente",
    )
    def test_extracts_real_binary_doc(self):
        # Fixture: testWORD.doc di Apache Tika (Apache-2.0), un vero Word 97-2003.
        text = extract_doc_text(_FIXTURE_DOC)
        self.assertIn("Sample Word Document", text)
        self.assertIn("Heading Level 1", text)
        # Il testo delle celle di tabella viene estratto (flatten, come per .docx).
        self.assertIn("nested table", text.lower())
        # Nessun marcatore di campo grezzo (0x13/0x14/0x15) nell'output.
        self.assertNotIn("\x13", text)
        self.assertNotIn("\x14", text)
        self.assertNotIn("\x15", text)


if __name__ == "__main__":
    unittest.main()
