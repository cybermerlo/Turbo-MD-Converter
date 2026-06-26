"""Test per la feature di descrizione visiva dei video."""

import os
import struct
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from config.settings import AppConfig
from ocr.video_describer import VideoDescriber
from output.markdown_formatter import MarkdownFormatter
from pipeline.processor import DocumentProcessor
from utils.cost_tracker import CostTracker
from utils.ffmpeg_tools import get_ffmpeg_exe, strip_audio
from utils.media_duration import probe_duration_seconds


# ---------------------------------------------------------------------------
# Helper: costruzione di un MP4 minimale con atom moov/mvhd
# ---------------------------------------------------------------------------

def _atom(atom_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + atom_type + payload


def _make_mp4(duration: int, timescale: int) -> bytes:
    """MP4 minimo con un mvhd (versione 0) dai valori dati."""
    mvhd_payload = (
        bytes([0]) + bytes(3)            # version + flags
        + struct.pack(">I", 0)           # creation_time
        + struct.pack(">I", 0)           # modification_time
        + struct.pack(">I", timescale)   # timescale
        + struct.pack(">I", duration)    # duration
    )
    moov = _atom(b"moov", _atom(b"mvhd", mvhd_payload))
    ftyp = _atom(b"ftyp", b"isomisom")
    return ftyp + moov


class FakeTranscriber:
    model_id = "scribe_v2"

    def __init__(self, text="Buongiorno a tutti."):
        self.text = text

    def transcribe(self, path):
        return {
            "text": self.text,
            "duration_seconds": 12.0,
            "language_code": "ita",
            "speakers": ["speaker_0"],
            "segments": [
                {"speaker_id": "speaker_0", "start": 0.0, "end": 12.0,
                 "text": self.text},
            ],
        }


class FakeDescriber:
    model_id = "gemini-3.1-flash-lite"

    def __init__(self, text="Si vede una sala riunioni con quattro persone."):
        self.text = text
        self.last_resolution = None

    def resolution_for(self, duration_s):
        return ("<enum>", "LOW")

    def describe(self, path, media_resolution=None):
        self.last_resolution = media_resolution
        return {"text": self.text, "input_tokens": 100, "output_tokens": 20}


# ---------------------------------------------------------------------------
# Lettura durata
# ---------------------------------------------------------------------------

class MediaDurationTests(unittest.TestCase):
    def test_mp4_duration_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.mp4"
            path.write_bytes(_make_mp4(duration=600, timescale=1))  # 600 s
            self.assertAlmostEqual(probe_duration_seconds(path), 600.0, places=3)

    def test_mp4_duration_with_timescale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.mp4"
            path.write_bytes(_make_mp4(duration=90_000, timescale=1000))  # 90 s
            self.assertAlmostEqual(probe_duration_seconds(path), 90.0, places=3)

    def test_unreadable_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.mp4"
            path.write_bytes(b"non un mp4 valido")
            self.assertIsNone(probe_duration_seconds(path))


# ---------------------------------------------------------------------------
# Composizione corpo MD
# ---------------------------------------------------------------------------

class VideoBodyTests(unittest.TestCase):
    def test_both_sections(self):
        body = DocumentProcessor._build_video_body(
            "Testo audio.", "Testo visivo.", visual_attempted=True,
        )
        self.assertIn("## Trascrizione audio", body)
        self.assertIn("Testo audio.", body)
        self.assertIn("## Descrizione visiva", body)
        self.assertIn("Testo visivo.", body)
        # ordine: audio prima del visivo
        self.assertLess(body.index("Trascrizione audio"), body.index("Descrizione visiva"))

    def test_mute_video_placeholder(self):
        body = DocumentProcessor._build_video_body(
            "", "Testo visivo.", visual_attempted=True,
        )
        self.assertIn("_(nessuna traccia audio rilevata)_", body)
        self.assertIn("Testo visivo.", body)

    def test_visual_skipped_audio_only(self):
        body = DocumentProcessor._build_video_body(
            "Testo audio.", "", visual_attempted=False,
        )
        self.assertIn("## Trascrizione audio", body)
        self.assertNotIn("## Descrizione visiva", body)


# ---------------------------------------------------------------------------
# Formatter prerendered
# ---------------------------------------------------------------------------

class MarkdownPrerenderedTests(unittest.TestCase):
    def test_prerendered_skips_wrapper(self):
        md = MarkdownFormatter().format(
            extractions=[],
            source_filename="clip.mp4",
            total_pages=1,
            ocr_text="## Trascrizione audio\n\nCiao.",
            ocr_prerendered=True,
        )
        self.assertNotIn("## Contenuto del documento originale:", md)
        self.assertIn("## Trascrizione audio", md)

    def test_non_prerendered_keeps_wrapper(self):
        md = MarkdownFormatter().format(
            extractions=[],
            source_filename="doc.pdf",
            total_pages=1,
            ocr_text="Testo OCR.",
        )
        self.assertIn("## Contenuto del documento originale:", md)


# ---------------------------------------------------------------------------
# Routing video end-to-end (con fake)
# ---------------------------------------------------------------------------

class VideoRoutingTests(unittest.TestCase):
    def _processor(self, tmp, **overrides):
        cfg = AppConfig(
            gemini_api_key="k",
            elevenlabs_api_key="k",
            run_ocr=True,
            run_extraction=False,
            output_formats=["markdown"],
            **overrides,
        )
        proc = DocumentProcessor(cfg, lambda e: None)
        proc.audio_transcriber = FakeTranscriber()
        proc.video_describer = FakeDescriber()
        return proc

    def test_mp4_produces_two_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "riunione.mp4"
            path.write_bytes(_make_mp4(duration=30, timescale=1))  # 30 s
            proc = self._processor(tmp)

            success, _cost, _doc = proc.process_single(path, threading.Event())

            self.assertTrue(success)
            md = (Path(tmp) / "riunione.md").read_text(encoding="utf-8")
            self.assertIn("## Trascrizione audio", md)
            self.assertIn("Buongiorno a tutti.", md)
            self.assertIn("## Descrizione visiva", md)
            self.assertIn("sala riunioni", md)
            self.assertNotIn("## Contenuto del documento originale:", md)

    def test_long_video_skips_visual(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lungo.mp4"
            path.write_bytes(_make_mp4(duration=600, timescale=1))  # 10 min
            proc = self._processor(tmp, video_max_duration_min=5)  # cap 5 min

            success, _cost, _doc = proc.process_single(path, threading.Event())

            self.assertTrue(success)
            md = (Path(tmp) / "lungo.md").read_text(encoding="utf-8")
            self.assertIn("## Trascrizione audio", md)
            self.assertNotIn("## Descrizione visiva", md)

    def test_describe_disabled_audio_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "solo_audio.mp4"
            path.write_bytes(_make_mp4(duration=30, timescale=1))
            cfg = AppConfig(
                gemini_api_key="k",
                elevenlabs_api_key="k",
                run_ocr=True,
                run_extraction=False,
                output_formats=["markdown"],
                video_describe=False,
            )
            proc = DocumentProcessor(cfg, lambda e: None)
            proc.audio_transcriber = FakeTranscriber()
            # video_describer resta None perché video_describe=False
            self.assertIsNone(proc.video_describer)

            success, _cost, _doc = proc.process_single(path, threading.Event())

            self.assertTrue(success)
            md = (Path(tmp) / "solo_audio.md").read_text(encoding="utf-8")
            self.assertIn("## Trascrizione audio", md)
            self.assertNotIn("## Descrizione visiva", md)


# ---------------------------------------------------------------------------
# Cost tracker fase "video"
# ---------------------------------------------------------------------------

class CostTrackerVideoPhaseTests(unittest.TestCase):
    def test_video_phase_in_totals(self):
        tracker = CostTracker()
        tracker.add_call("gemini-3.1-flash-lite", 1_000_000, 0, phase="video")
        totals = tracker.get_totals()
        self.assertIn("video", totals)
        self.assertAlmostEqual(totals["video"]["cost_usd"], 0.25, places=4)
        # Il costo video confluisce nel totale aggregato.
        self.assertAlmostEqual(totals["total"]["cost_usd"], 0.25, places=4)


# ---------------------------------------------------------------------------
# Scelta risoluzione in base alla durata
# ---------------------------------------------------------------------------

class ResolutionChoiceTests(unittest.TestCase):
    def _describer(self, **env):
        with mock.patch.dict(os.environ, env, clear=False):
            # Rimuovi eventuali override residui se non passati esplicitamente.
            if "TURBOMD_VIDEO_MEDIA_RESOLUTION" not in env:
                os.environ.pop("TURBOMD_VIDEO_MEDIA_RESOLUTION", None)
            return VideoDescriber("k", high_quality_max_min=3)

    def test_short_video_high(self):
        d = self._describer()
        _, name = d.resolution_for(60)  # 1 min ≤ 3 min
        self.assertEqual(name, "HIGH")

    def test_long_video_low(self):
        d = self._describer()
        _, name = d.resolution_for(600)  # 10 min > 3 min
        self.assertEqual(name, "LOW")

    def test_unknown_duration_low(self):
        d = self._describer()
        _, name = d.resolution_for(None)
        self.assertEqual(name, "LOW")

    def test_env_force_overrides_duration(self):
        d = self._describer(TURBOMD_VIDEO_MEDIA_RESOLUTION="low")
        _, name = d.resolution_for(10)  # breve, ma forzato a LOW
        self.assertEqual(name, "LOW")


# ---------------------------------------------------------------------------
# Rimozione traccia audio (ffmpeg reale)
# ---------------------------------------------------------------------------

@unittest.skipUnless(get_ffmpeg_exe(), "ffmpeg non disponibile")
class StripAudioTests(unittest.TestCase):
    def _ffmpeg(self):
        return get_ffmpeg_exe()

    def _make_video_with_audio(self, path: Path) -> None:
        cmd = [
            self._ffmpeg(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
            "-shortest", "-pix_fmt", "yuv420p", str(path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    def _streams(self, path: Path) -> str:
        # `ffmpeg -i` stampa info sui flussi su stderr (ed esce con codice != 0).
        proc = subprocess.run(
            [self._ffmpeg(), "-i", str(path)],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        return proc.stderr

    def test_strip_removes_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "av.mp4"
            self._make_video_with_audio(src)
            self.assertIn("Audio:", self._streams(src))  # ha audio di partenza

            muted = strip_audio(src)
            self.assertIsNotNone(muted)
            self.assertTrue(muted.exists() and muted.stat().st_size > 0)
            streams = self._streams(muted)
            self.assertIn("Video:", streams)
            self.assertNotIn("Audio:", streams)  # audio rimosso
            muted.unlink(missing_ok=True)

    def test_strip_garbage_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.mp4"
            bad.write_bytes(b"non un video")
            self.assertIsNone(strip_audio(bad))


if __name__ == "__main__":
    unittest.main()
