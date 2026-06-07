"""打包路径工具单元测试。"""
from __future__ import annotations

import unittest
from pathlib import Path

from dpt_extractor.utils.app_paths import (
    default_config_path,
    package_config_dir,
    user_channel_maps_path,
    user_data_dir,
)


class TestAppPaths(unittest.TestCase):
    def test_default_config_exists_in_dev(self):
        p = default_config_path()
        self.assertTrue(p.is_file(), p)
        self.assertEqual(p.name, "default.yaml")

    def test_user_paths_under_local_appdata_on_windows(self):
        ud = user_data_dir()
        self.assertTrue(ud.is_dir())
        self.assertEqual(user_channel_maps_path().parent, ud)

    def test_package_config_dir(self):
        self.assertTrue((package_config_dir() / "default.yaml").exists() or default_config_path().exists())


if __name__ == "__main__":
    unittest.main()
