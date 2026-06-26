"""Test dell'estrazione testo dagli archivi (pipeline/archive_sources.py)."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from pipeline.archive_sources import extract_archive_text, is_archive_path


def _read_member(path: Path) -> str:
    """process_member di prova: legge il file come testo UTF-8."""
    return path.read_text(encoding="utf-8", errors="replace")


class IsArchivePathTests(unittest.TestCase):
    def test_recognizes_common_archives(self):
        self.assertTrue(is_archive_path(Path("x.zip")))
        self.assertTrue(is_archive_path(Path("x.7z")))
        self.assertTrue(is_archive_path(Path("x.tar")))
        self.assertTrue(is_archive_path(Path("x.tgz")))
        self.assertTrue(is_archive_path(Path("backup.tar.gz")))

    def test_rejects_non_archive(self):
        self.assertFalse(is_archive_path(Path("documento.pdf")))


class ExtractZipTests(unittest.TestCase):
    def _make_zip(self, tmpdir: Path, entries: dict[str, str]) -> Path:
        zip_path = tmpdir / "archivio.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        return zip_path

    def test_concatenates_member_text(self):
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            zip_path = self._make_zip(
                tmpdir, {"a.txt": "Alfa", "b.txt": "Beta"}
            )
            out = extract_archive_text(
                zip_path, _read_member, lambda m, lvl="INFO": logs.append((m, lvl))
            )
            self.assertIn("Alfa", out)
            self.assertIn("Beta", out)
            self.assertIn("--- FILE 1: a.txt ---", out)

    def test_hidden_and_metadata_files_skipped(self):
        # Il filtro guarda il basename: scarta i nomi che iniziano con ".", "__"
        # o "~" (file nascosti, metadati macOS "._*", temporanei).
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            zip_path = self._make_zip(
                tmpdir,
                {
                    "vero.txt": "Contenuto",
                    ".nascosto": "segreto",
                    "__MACOSX/._vero.txt": "fork",
                    "~temp.txt": "temporaneo",
                },
            )
            out = extract_archive_text(
                zip_path, _read_member, lambda m, lvl="INFO": None
            )
            self.assertIn("Contenuto", out)
            self.assertNotIn("segreto", out)
            self.assertNotIn("fork", out)
            self.assertNotIn("temporaneo", out)

    def test_empty_archive_returns_empty_and_warns(self):
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            zip_path = self._make_zip(tmpdir, {})
            out = extract_archive_text(
                zip_path, _read_member, lambda m, lvl="INFO": logs.append((m, lvl))
            )
            self.assertEqual(out, "")
            self.assertTrue(any(lvl == "WARNING" for _, lvl in logs))

    def test_duplicate_basenames_do_not_collide(self):
        # Due file con lo stesso basename in cartelle diverse: entrambi devono
        # essere elaborati (il secondo viene scritto come "N_nome").
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            zip_path = self._make_zip(
                tmpdir, {"dir1/nota.txt": "Uno", "dir2/nota.txt": "Due"}
            )
            out = extract_archive_text(
                zip_path, _read_member, lambda m, lvl="INFO": None
            )
            self.assertIn("Uno", out)
            self.assertIn("Due", out)

    def test_corrupt_archive_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            bad = tmpdir / "rotto.zip"
            bad.write_bytes(b"non e' uno zip")
            with self.assertRaises(RuntimeError):
                extract_archive_text(bad, _read_member, lambda m, lvl="INFO": None)


if __name__ == "__main__":
    unittest.main()
