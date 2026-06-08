"""打包路径工具单元测试。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dpt_extractor.utils.app_paths import (
    configure_numba_cache_dir,
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

    def test_configure_numba_cache_preserves_existing_env(self):
        cache = Path("D:/already-configured/cache")
        with patch.dict(os.environ, {"NUMBA_CACHE_DIR": str(cache)}):
            self.assertEqual(configure_numba_cache_dir(), cache)

    def test_configure_numba_cache_sets_user_cache_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("NUMBA_CACHE_DIR", None)
                with patch(
                    "dpt_extractor.utils.app_paths.user_data_dir",
                    return_value=root,
                ):
                    cache = configure_numba_cache_dir()
            self.assertEqual(cache, root / "numba_cache")
            self.assertTrue(cache.is_dir())


if __name__ == "__main__":
    unittest.main()
