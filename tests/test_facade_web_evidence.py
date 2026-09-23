import unittest

from batiforge.reconstruction.facade_web_evidence import (
    _safe_name,
    discover_page_image_assets,
    validate_manifest,
)


class FacadeWebEvidenceTests(unittest.TestCase):
    def test_safe_name_normalises_simple_filename(self):
        self.assertEqual(_safe_name(" facade photo 01.jpg "), "facade-photo-01.jpg")

    def test_manifest_requires_rights(self):
        manifest = {
            "schema_version": 1,
            "sources": [
                {
                    "id": "x",
                    "kind": "page",
                    "page_url": "https://example.test/x",
                }
            ],
        }
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_download_source_requires_asset_and_filename(self):
        manifest = {
            "schema_version": 1,
            "sources": [
                {
                    "id": "x",
                    "kind": "image",
                    "page_url": "https://example.test/x",
                    "download": True,
                    "rights": "test",
                }
            ],
        }
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_page_asset_discovery_resolves_relative_and_deduplicates(self):
        html = """
        <html><head><meta property="og:image" content="/hero.jpg"></head>
        <body><img src="/hero.jpg"><img data-src="images/facade.png"></body></html>
        """
        assets = discover_page_image_assets(html, "https://example.test/place/page")
        self.assertEqual(
            assets,
            [
                "https://example.test/hero.jpg",
                "https://example.test/place/images/facade.png",
            ],
        )

    def test_example_shape_is_valid(self):
        manifest = {
            "schema_version": 1,
            "sources": [
                {
                    "id": "x",
                    "kind": "pdf",
                    "page_url": "https://example.test/x.pdf",
                    "asset_url": "https://example.test/x.pdf",
                    "filename": "x.pdf",
                    "download": True,
                    "rights": "reference only",
                },
                {
                    "id": "y",
                    "kind": "page",
                    "page_url": "https://example.test/y",
                    "download": False,
                    "discover_assets": True,
                    "rights": "catalogue only",
                },
            ],
        }
        validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
