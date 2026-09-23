import unittest

from batiforge.reconstruction.facade_pdf_evidence import _normalise_pages


class FacadePdfEvidenceTests(unittest.TestCase):
    def test_pages_are_one_based_deduplicated_and_ordered(self):
        self.assertEqual(_normalise_pages([5, 6, 5], 7), [5, 6])

    def test_page_outside_document_is_rejected(self):
        with self.assertRaises(ValueError):
            _normalise_pages([0], 7)
        with self.assertRaises(ValueError):
            _normalise_pages([8], 7)


if __name__ == "__main__":
    unittest.main()
