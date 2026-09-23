import unittest

from batiforge.reconstruction.lidar_context_fetch import (
    DEFAULT_LAYERS,
    _download_url_from_properties,
    _resource_name,
    crop_from_footprint,
)


class LidarContextFetchTests(unittest.TestCase):
    def test_crop_uses_metric_margin(self):
        footprint = {
            "bounds": {"min_x": 100.0, "min_y": 200.0, "max_x": 130.0, "max_y": 240.0}
        }
        self.assertEqual(crop_from_footprint(footprint, 25.0), (75.0, 175.0, 155.0, 265.0))

    def test_uses_current_unified_metadata_layer(self):
        self.assertEqual(DEFAULT_LAYERS, ("IGNF_LIDAR-HD_METADONNEE:metadata",))

    def test_prefers_current_url_npl_property(self):
        props = {
            "url_npl": "https://data.geopf.fr/telechargement/download/example/current.copc.laz",
            "url": "https://data.geopf.fr/telechargement/download/example/legacy.copc.laz",
        }
        self.assertEqual(_download_url_from_properties(props), props["url_npl"])

    def test_prefers_explicit_url_property_when_pointcloud(self):
        props = {
            "url": "https://data.geopf.fr/telechargement/download/example/tile.copc.laz",
            "other": "https://example.test/wrong.copc.laz",
        }
        self.assertEqual(_download_url_from_properties(props), props["url"])

    def test_does_not_take_non_pointcloud_url_before_laz(self):
        props = {
            "url": "https://example.test/catalogue/page",
            "url_npl": "https://example.test/tile.copc.laz",
        }
        self.assertEqual(_download_url_from_properties(props), props["url_npl"])

    def test_finds_copc_url_in_unknown_property(self):
        props = {"download": "https://example.test/tile.copc.laz"}
        self.assertEqual(_download_url_from_properties(props), props["download"])

    def test_name_download_is_preserved(self):
        props = {
            "name_download": "LHD_FXX_0940_6540_PTS_C_LAMB93_IGN69.copc.laz"
        }
        url = "https://example.test/a.copc.laz"
        self.assertEqual(_resource_name(props, url), props["name_download"])

    def test_plain_name_gets_copc_suffix(self):
        props = {"name": "LHD_FXX_0940_6540_PTS_C_LAMB93_IGN69"}
        self.assertEqual(
            _resource_name(props, "https://example.test/a"),
            "LHD_FXX_0940_6540_PTS_C_LAMB93_IGN69.copc.laz",
        )

    def test_url_filename_is_used_for_metadata_without_name(self):
        props = {"url_npl": "https://example.test/path/LHD_FXX_0940_6539_PTS_LAMB93_IGN69.copc.laz"}
        self.assertEqual(
            _resource_name(props, props["url_npl"]),
            "LHD_FXX_0940_6539_PTS_LAMB93_IGN69.copc.laz",
        )


if __name__ == "__main__":
    unittest.main()
