from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import MagicMock, patch

from dpt_extractor.io.wfm_scope_display import (
    read_wfm_vertical_scale_per_div,
    scope_vdiv_by_logical,
    scope_y_position_by_logical,
)
from dpt_extractor.models.bridge_profile import make_profile
from dpt_extractor.models.waveform import TekMetadata


class TestScopeDisplayMapping(unittest.TestCase):
    def test_upper_bridge_vdiv_mapping(self):
        profile = make_profile("U", "upper")
        meta = TekMetadata(
            channel_vdiv={
                "CH1": 5.0,
                "CH2": 200.0,
                "CH3": 200.0,
                "CH4": 200.0,
                "CH5": 200.0,
                "CH6": 5.0,
            },
            channel_y_position={
                "CH1": -0.6,
                "CH2": -3.54,
            },
        )
        vdiv = scope_vdiv_by_logical(meta, profile)
        self.assertEqual(vdiv["vge"], 5.0)
        self.assertEqual(vdiv["vce"], 200.0)
        self.assertEqual(vdiv["ic"], 200.0)
        self.assertEqual(vdiv["irr"], 200.0)
        ypos = scope_y_position_by_logical(meta, profile)
        self.assertEqual(ypos["vge"], -0.6)
        self.assertEqual(ypos["vce"], -3.54)


class TestReadWfmVerticalScale(unittest.TestCase):
    def test_reads_dim_scale_times_graticule_factor(self):
        exp_dim = MagicMock()
        exp_dim.first.scale = 5.0 / 6400.0
        formatted = MagicMock()
        formatted.explicit_dimensions = exp_dim
        formatted.explicit_user_view = None
        endian_key = b"AB"
        wfm_file = MagicMock()
        wfm_file._ENDIAN_PREFIX_LOOKUP = {endian_key: MagicMock(struct=">")}
        string8 = MagicMock()
        string8.unpack.return_value = "3.0"
        version_number = MagicMock()
        wfm_format = MagicMock(return_value=formatted)

        with (
            patch("dpt_extractor.io.wfm_scope_display.struct.unpack", return_value=(endian_key,)),
            patch(
                "dpt_extractor.io.wfm_scope_display._wfm_dependencies",
                return_value=(wfm_file, wfm_format, string8, version_number),
            ),
            patch("pathlib.Path.open", mock.mock_open()),
        ):
            scale = read_wfm_vertical_scale_per_div("dummy.wfm")
        self.assertEqual(scale, 5.0)

    def test_invalid_dim_scale_returns_none(self):
        exp_dim = MagicMock()
        exp_dim.first.scale = 0.0
        formatted = MagicMock()
        formatted.explicit_dimensions = exp_dim
        endian_key = b"AB"
        wfm_file = MagicMock()
        wfm_file._ENDIAN_PREFIX_LOOKUP = {endian_key: MagicMock(struct=">")}
        string8 = MagicMock()
        string8.unpack.return_value = "3.0"
        version_number = MagicMock()
        wfm_format = MagicMock(return_value=formatted)

        with (
            patch("dpt_extractor.io.wfm_scope_display.struct.unpack", return_value=(endian_key,)),
            patch(
                "dpt_extractor.io.wfm_scope_display._wfm_dependencies",
                return_value=(wfm_file, wfm_format, string8, version_number),
            ),
            patch("pathlib.Path.open", mock.mock_open()),
        ):
            self.assertIsNone(read_wfm_vertical_scale_per_div("dummy.wfm"))


if __name__ == "__main__":
    unittest.main()
