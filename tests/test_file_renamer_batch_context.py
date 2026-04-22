import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import file_renamer


class BatchRenameContextTests(unittest.TestCase):
    def test_prompt_context_marks_used_names_as_not_reusable(self):
        history = [
            {
                "original_name": "cassazione.pdf",
                "final_name": "20230217 - Slide webinar Riforma processo civile Avv. Greco.pdf",
                "date_str": "20230217",
                "description": "Slide webinar Riforma processo civile Avv. Greco",
            }
        ]

        block = file_renamer._build_rename_context_block(history)

        self.assertIn("NON riusare", block)
        self.assertIn("Nomi gia' assegnati", block)
        self.assertIn("20230217 - Slide webinar Riforma processo civile Avv. Greco", block)

    def test_uniqueness_guard_changes_duplicate_candidate(self):
        history = [
            {
                "original_name": "cassazione.pdf",
                "final_name": "20230217 - Slide webinar Riforma processo civile Avv. Greco.pdf",
                "date_str": "20230217",
                "description": "Slide webinar Riforma processo civile Avv. Greco",
            }
        ]

        unique_description = file_renamer._ensure_unique_description(
            date_str="20230217",
            description="Slide webinar Riforma processo civile Avv. Greco",
            original_filename="appello.pdf",
            rename_examples=history,
        )

        self.assertNotEqual(
            unique_description.lower().strip(),
            "slide webinar riforma processo civile avv. greco",
        )
        self.assertIn("appello", unique_description.lower())

    def test_batch_documents_context_contains_current_file_and_overview(self):
        docs = [
            {
                "doc_id": 1,
                "original_name": "cassazione.pdf",
                "ocr_preview_start": "Ricorso in cassazione contro sentenza n. 123",
                "keyword_hint": "cassazione, ricorso, sentenza",
                "profile_naming_hint": "Giudizio in Cassazione",
            },
            {
                "doc_id": 2,
                "original_name": "appello.pdf",
                "ocr_preview_start": "Atto di appello con richiesta sospensione esecutivita'",
                "keyword_hint": "appello, sospensione, impugnazione",
                "profile_naming_hint": "Giudizio di Appello",
            },
        ]

        block = file_renamer._build_batch_documents_context(
            original_filename="cassazione.pdf",
            batch_documents=docs,
            current_doc_id=1,
        )

        self.assertIn("Documento corrente: #1 - cassazione.pdf", block)
        self.assertIn("Panoramica documenti del batch", block)
        self.assertIn("appello.pdf", block)
        self.assertIn("Giudizio in Cassazione", block)
        self.assertIn("Giudizio di Appello", block)

    def test_strip_leading_date_prefix_from_description(self):
        cleaned = file_renamer._strip_leading_date_prefix(
            "20230217 - Slide Riforma Cartabia giudizio di appello"
        )
        self.assertEqual(cleaned, "Slide Riforma Cartabia giudizio di appello")

        cleaned_twice = file_renamer._strip_leading_date_prefix(
            "20230217 - 20230217 - Slide Riforma Cartabia giudizio di appello"
        )
        self.assertEqual(cleaned_twice, "Slide Riforma Cartabia giudizio di appello")

    def test_build_user_context_block(self):
        block = file_renamer._build_user_context_block(
            "Usa una nomenclatura breve e focalizzata sul capitolo principale."
        )
        self.assertIn("PRIORITA' MASSIMA", block)
        self.assertIn("capitolo principale", block)


if __name__ == "__main__":
    unittest.main()
