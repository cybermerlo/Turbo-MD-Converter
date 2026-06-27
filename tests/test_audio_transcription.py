"""Test per la trascrizione audio ElevenLabs Scribe v2: costruzione del
testo diarizzato, speaker distinti, costo a ora e identificazione interlocutori."""

import tempfile
import threading
import unittest
from pathlib import Path

from ocr.audio_transcriber import (
    AUDIO_MIME_TYPES,
    build_transcript,
    distinct_speakers,
    segments_from_words,
)
from ocr.speaker_id import pick_speaker_snippets, rewrite_transcript_in_md
from pipeline.constants import AUDIO_EXTENSIONS
from utils.cost_tracker import CostTracker


class _Word:
    def __init__(self, text, start, end, type="word", speaker_id="speaker_0"):
        self.text = text
        self.start = start
        self.end = end
        self.type = type
        self.speaker_id = speaker_id


class SegmentsFromWordsTests(unittest.TestCase):
    def test_groups_consecutive_words_by_speaker(self):
        words = [
            _Word("Ciao", 0.0, 0.4, speaker_id="speaker_0"),
            _Word(" ", 0.4, 0.45, type="spacing", speaker_id="speaker_0"),
            _Word("Anna", 0.45, 0.9, speaker_id="speaker_0"),
            _Word("Ciao", 1.2, 1.6, speaker_id="speaker_1"),
            _Word("Bene", 75.0, 75.4, speaker_id="speaker_0"),
        ]
        segs = segments_from_words(words)
        self.assertEqual(3, len(segs))
        self.assertEqual("speaker_0", segs[0]["speaker_id"])
        self.assertEqual("Ciao Anna", segs[0]["text"])
        self.assertEqual("speaker_1", segs[1]["speaker_id"])
        self.assertEqual("Bene", segs[2]["text"])

    def test_distinct_speakers_in_order(self):
        words = [
            _Word("a", 0, 1, speaker_id="speaker_1"),
            _Word("b", 1, 2, speaker_id="speaker_0"),
            _Word("c", 2, 3, speaker_id="speaker_1"),
        ]
        self.assertEqual(["speaker_1", "speaker_0"],
                         distinct_speakers(segments_from_words(words)))

    def test_empty_words(self):
        self.assertEqual([], segments_from_words([]))
        self.assertEqual([], segments_from_words(None))


class BuildTranscriptTests(unittest.TestCase):
    def test_single_speaker_is_plain_text(self):
        segs = [{"speaker_id": "speaker_0", "start": 0.0, "end": 2.0,
                 "text": "Una nota vocale."}]
        out = build_transcript(segs)
        self.assertEqual("Una nota vocale.", out)
        self.assertNotIn("[00:", out)  # nessun timestamp per speaker singolo

    def test_multi_speaker_has_timestamps_and_labels(self):
        segs = [
            {"speaker_id": "speaker_0", "start": 0.0, "end": 1.0, "text": "Pronto?"},
            {"speaker_id": "speaker_1", "start": 75.0, "end": 76.0, "text": "Sì."},
        ]
        out = build_transcript(segs)
        self.assertIn("[00:00] speaker_0: Pronto?", out)
        self.assertIn("[01:15] speaker_1: Sì.", out)

    def test_user_labels_applied(self):
        segs = [
            {"speaker_id": "speaker_0", "start": 0.0, "end": 1.0, "text": "Pronto?"},
            {"speaker_id": "speaker_1", "start": 2.0, "end": 3.0, "text": "Sì."},
        ]
        out = build_transcript(segs, {"speaker_0": "Mario", "speaker_1": "Anna"})
        self.assertIn("[00:00] Mario: Pronto?", out)
        self.assertIn("[00:02] Anna: Sì.", out)


class PerHourCostTests(unittest.TestCase):
    def test_scribe_cost_is_duration_based(self):
        ct = CostTracker()
        # 30 minuti di audio a $0.22/ora = $0.11
        ct.add_call(model_id="scribe_v2", input_tokens=0, output_tokens=0,
                    phase="transcription", duration_seconds=1800.0)
        totals = ct.get_totals()
        self.assertAlmostEqual(0.11, totals["transcription"]["cost_usd"], places=4)
        self.assertAlmostEqual(0.11, totals["total"]["cost_usd"], places=4)

    def test_merge_preserves_duration_cost(self):
        a, b = CostTracker(), CostTracker()
        b.add_call(model_id="scribe_v2", input_tokens=0, output_tokens=0,
                   phase="transcription", duration_seconds=3600.0)  # 1h -> $0.22
        a.merge_from(b)
        self.assertAlmostEqual(0.22, a.get_totals()["transcription"]["cost_usd"],
                               places=4)


class SpeakerSnippetTests(unittest.TestCase):
    def test_picks_longest_per_speaker_in_time_order(self):
        segments = [
            {"speaker_id": "speaker_0", "start": 0.0, "end": 1.0, "text": "Sì."},
            {"speaker_id": "speaker_1", "start": 2.0, "end": 5.0,
             "text": "Una frase lunga e riconoscibile per lo speaker uno."},
            {"speaker_id": "speaker_0", "start": 6.0, "end": 9.0,
             "text": "Anche speaker zero ha una battuta piuttosto lunga qui."},
        ]
        snips = pick_speaker_snippets(segments, max_snippets=1)
        self.assertEqual(["speaker_0", "speaker_1"], list(snips))
        self.assertIn("piuttosto lunga", snips["speaker_0"][0]["text"])

    def test_truncates_long_text(self):
        seg = [{"speaker_id": "speaker_0", "start": 0, "end": 1, "text": "x" * 500}]
        out = pick_speaker_snippets(seg, max_chars=50)["speaker_0"][0]["text"]
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), 51)


class RewriteTranscriptTests(unittest.TestCase):
    def test_rewrites_provisional_labels_in_md(self):
        segments = [
            {"speaker_id": "speaker_0", "start": 0.0, "end": 1.0, "text": "Pronto?"},
            {"speaker_id": "speaker_1", "start": 2.0, "end": 3.0, "text": "Ciao."},
        ]
        md_body = build_transcript(segments)
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "call.md"
            md.write_text(f"# call\n\n## Trascrizione audio\n\n{md_body}\n", encoding="utf-8")
            changed = rewrite_transcript_in_md(
                md, segments, {"speaker_0": "Mario", "speaker_1": "Anna"})
            out = md.read_text(encoding="utf-8")
        self.assertTrue(changed)
        self.assertIn("] Mario:", out)
        self.assertIn("] Anna:", out)
        self.assertNotIn("] speaker_", out)

    def test_noop_without_labels(self):
        segments = [{"speaker_id": "speaker_0", "start": 0, "end": 1, "text": "Ciao."}]
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "x.md"
            md.write_text("contenuto", encoding="utf-8")
            self.assertFalse(rewrite_transcript_in_md(md, segments, {}))


class DiarizationPipelineTests(unittest.TestCase):
    """Un audio con più speaker emette SpeakerDiarizationEvent e l'.md è rietichettabile."""

    def test_multispeaker_emits_event_and_md_relabel(self):
        from config.settings import AppConfig
        from pipeline.events import SpeakerDiarizationEvent
        from pipeline.processor import DocumentProcessor

        segments = [
            {"speaker_id": "speaker_0", "start": 0.0, "end": 1.0, "text": "Pronto?"},
            {"speaker_id": "speaker_1", "start": 2.0, "end": 4.0, "text": "Sono Anna."},
        ]

        class MultiTranscriber:
            model_id = "scribe_v2"

            def transcribe(self, path):
                return {
                    "text": build_transcript(segments),
                    "duration_seconds": 5.0,
                    "language_code": "ita",
                    "speakers": distinct_speakers(segments),
                    "segments": segments,
                }

        events = []
        cfg = AppConfig(
            elevenlabs_api_key="k", gemini_api_key="k",
            run_ocr=True, run_extraction=False, video_describe=False,
            identify_speakers=True, output_formats=["markdown"],
        )
        proc = DocumentProcessor(cfg, events.append)
        proc.audio_transcriber = MultiTranscriber()

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "call.mp3"
            audio.write_bytes(b"ID3 fake audio")
            ok, _cost, _doc = proc.process_single(audio, threading.Event())
            self.assertTrue(ok)

            diar = [e for e in events if isinstance(e, SpeakerDiarizationEvent)]
            self.assertEqual(1, len(diar))
            self.assertEqual(2, len(diar[0].segments))
            self.assertEqual(audio, diar[0].input_path)

            md = Path(tmp) / "call.md"
            self.assertTrue(md.exists())
            self.assertIn("speaker_0:", md.read_text(encoding="utf-8"))

            changed = rewrite_transcript_in_md(
                md, segments, {"speaker_0": "Mario", "speaker_1": "Anna"})
            self.assertTrue(changed)
            out = md.read_text(encoding="utf-8")
            self.assertIn("Mario:", out)
            self.assertNotIn("speaker_0:", out)

    def test_single_speaker_no_event(self):
        from config.settings import AppConfig
        from pipeline.events import SpeakerDiarizationEvent
        from pipeline.processor import DocumentProcessor

        class SingleTranscriber:
            model_id = "scribe_v2"

            def transcribe(self, path):
                return {"text": "Una nota.", "duration_seconds": 3.0,
                        "language_code": "ita", "speakers": ["speaker_0"],
                        "segments": [{"speaker_id": "speaker_0", "start": 0.0,
                                      "end": 3.0, "text": "Una nota."}]}

        events = []
        cfg = AppConfig(elevenlabs_api_key="k", gemini_api_key="k",
                        run_ocr=True, run_extraction=False, video_describe=False,
                        identify_speakers=True, output_formats=["markdown"])
        proc = DocumentProcessor(cfg, events.append)
        proc.audio_transcriber = SingleTranscriber()
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "nota.mp3"
            audio.write_bytes(b"ID3")
            proc.process_single(audio, threading.Event())
        self.assertEqual(
            [], [e for e in events if isinstance(e, SpeakerDiarizationEvent)])


class AudioConstantsTests(unittest.TestCase):
    def test_opus_registered(self):
        self.assertIn(".opus", AUDIO_EXTENSIONS)
        self.assertEqual("audio/ogg", AUDIO_MIME_TYPES[".opus"])


class AudioRetryPolicyTests(unittest.TestCase):
    """Gli errori client 4xx (es. video senza audio) non vanno ritentati."""

    def test_status_code_400_not_retried(self):
        from ocr.audio_transcriber import _is_non_retryable

        class Err(Exception):
            status_code = 400

        self.assertTrue(_is_non_retryable(Err("could not be decoded")))

    def test_message_based_400(self):
        from ocr.audio_transcriber import _is_non_retryable
        self.assertTrue(_is_non_retryable(
            Exception("API error occurred: Status 400. Body: could not be decoded")))

    def test_429_is_retryable(self):
        from ocr.audio_transcriber import _is_non_retryable

        class Err(Exception):
            status_code = 429

        self.assertFalse(_is_non_retryable(Err("rate limit")))

    def test_500_is_retryable(self):
        from ocr.audio_transcriber import _is_non_retryable

        class Err(Exception):
            status_code = 500

        self.assertFalse(_is_non_retryable(Err("server error")))


class UndecodableAudioTests(unittest.TestCase):
    """Un video senza traccia audio è una condizione attesa, non un errore."""

    def test_detects_could_not_be_decoded(self):
        from ocr.audio_transcriber import _is_undecodable_audio
        self.assertTrue(_is_undecodable_audio(
            Exception('Status 400. Body: {"message":"Audio input could not '
                      'be decoded. ","type":"invalid_request_file","code":"3310"}')))

    def test_detects_code_attribute(self):
        from ocr.audio_transcriber import _is_undecodable_audio

        class Err(Exception):
            code = "3310"

        self.assertTrue(_is_undecodable_audio(Err("boom")))

    def test_other_errors_not_flagged(self):
        from ocr.audio_transcriber import _is_undecodable_audio
        self.assertFalse(_is_undecodable_audio(Exception("rate limit")))
        self.assertFalse(_is_undecodable_audio(None))


if __name__ == "__main__":
    unittest.main()
