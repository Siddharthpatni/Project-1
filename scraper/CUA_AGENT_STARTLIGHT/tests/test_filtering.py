import unittest

from tender_agent.filtering import score_candidate, select_important_documents
from tender_agent.models import DocumentCandidate


class FilteringTests(unittest.TestCase):
    def test_scores_tender_documents_high(self) -> None:
        candidate = DocumentCandidate(
            name="Technical Specification.pdf",
            url="https://example.com/docs/technical-specification.pdf",
            source_page="https://example.com/tender",
            extension=".pdf",
        )

        score, _ = score_candidate(candidate)
        self.assertGreaterEqual(score, 4)

    def test_rejects_unimportant_images(self) -> None:
        candidate = DocumentCandidate(
            name="Company Logo.png",
            url="https://example.com/assets/logo.png",
            source_page="https://example.com/tender",
            extension=".png",
        )

        score, _ = score_candidate(candidate)
        self.assertLess(score, 4)

    def test_deduplicates_same_url(self) -> None:
        candidates = [
            DocumentCandidate(
                name="BOQ.xlsx",
                url="https://example.com/files/boq.xlsx",
                source_page="https://example.com/tender",
                extension=".xlsx",
            ),
            DocumentCandidate(
                name="BOQ Copy.xlsx",
                url="https://example.com/files/boq.xlsx",
                source_page="https://example.com/tender",
                extension=".xlsx",
            ),
        ]

        selected, unique_count = select_important_documents(candidates)
        self.assertEqual(len(selected), 1)
        self.assertEqual(unique_count, 1)
        self.assertEqual(selected[0].priority, "high")

    def test_selects_german_tender_pack(self) -> None:
        candidate = DocumentCandidate(
            name="Vergabeunterlagen.zip",
            url="https://example.com/download/unterlagen?id=42",
            source_page="https://example.com/tender",
            extension=".zip",
        )

        score, _ = score_candidate(candidate)
        self.assertGreaterEqual(score, 4)

    def test_scores_download_style_document_urls(self) -> None:
        candidate = DocumentCandidate(
            name="Unterlagen",
            url="https://example.com/download.aspx?docid=123",
            source_page="https://example.com/tender",
            extension=".aspx",
        )

        score, reason = score_candidate(candidate)
        self.assertGreaterEqual(score, 4)
        self.assertIn("download-style url", reason)


if __name__ == "__main__":
    unittest.main()
