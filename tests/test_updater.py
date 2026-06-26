"""Test del confronto versioni per l'auto-aggiornamento (utils/updater.py)."""

import unittest

from utils.updater import _version_tuple, is_newer


class VersionTupleTests(unittest.TestCase):
    def test_parses_dotted_version(self):
        self.assertEqual(_version_tuple("2026.06.09.1"), (2026, 6, 9, 1))

    def test_strips_leading_v(self):
        self.assertEqual(_version_tuple("v1.2.3"), (1, 2, 3))

    def test_malformed_falls_back_to_zero(self):
        self.assertEqual(_version_tuple("non-una-versione"), (0,))


class IsNewerTests(unittest.TestCase):
    def test_strictly_greater(self):
        self.assertTrue(is_newer("2026.06.10.0", "2026.06.09.1"))

    def test_equal_is_not_newer(self):
        self.assertFalse(is_newer("2026.06.09.1", "2026.06.09.1"))

    def test_older_is_not_newer(self):
        self.assertFalse(is_newer("2026.06.09.0", "2026.06.09.1"))

    def test_unequal_segment_count_extra_segment_wins(self):
        # Il bug storico: tuple di lunghezza diversa venivano confrontate senza
        # padding, così "2026.6.9.1" NON risultava più recente di "2026.6.9".
        self.assertTrue(is_newer("2026.6.9.1", "2026.6.9"))

    def test_unequal_segment_count_trailing_zero_is_equal(self):
        # "2026.6.9" e "2026.6.9.0" devono essere equivalenti (nessuno è più recente).
        self.assertFalse(is_newer("2026.6.9", "2026.6.9.0"))
        self.assertFalse(is_newer("2026.6.9.0", "2026.6.9"))

    def test_v_prefixed_tag_vs_plain(self):
        self.assertTrue(is_newer("v2027.1.1", "2026.12.31"))


if __name__ == "__main__":
    unittest.main()
