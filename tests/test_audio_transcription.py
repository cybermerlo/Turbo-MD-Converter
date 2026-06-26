"""Test per la trascrizione audio ElevenLabs Scribe v2: costruzione del
testo diarizzato, speaker distinti e costo a ora."""

import unittest

from ocr.audio_transcriber import (
    build_transcript,
    distinct_speakers,
    segments_from_words,
)
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


if __name__ == "__main__":
    unittest.main()
