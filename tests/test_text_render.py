"""Tests for text_render font handling and failure behaviour."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.astrbot_stubs import install

install()

import text_render


class FontLookupTest(unittest.TestCase):
    def test_user_font_path_tried_first(self):
        user_path = "/custom/fonts/MyCJK.ttf"
        calls: list[str] = []

        def fake_truetype(path, size, **kwargs):
            calls.append(path)
            if path == user_path:
                return object()
            raise OSError("no font")

        with patch.object(text_render.ImageFont, "truetype", side_effect=fake_truetype):
            font = text_render._get_font(22, font_path=user_path)
        self.assertIsNotNone(font)
        self.assertEqual(calls[0], user_path)

    def test_default_search_order_before_platform_candidates(self):
        calls: list[str] = []

        def fake_truetype(path, size, **kwargs):
            calls.append(path)
            if path == "/AstrBot/data/font.ttf":
                return object()
            raise OSError("no font")

        with patch.object(text_render.ImageFont, "truetype", side_effect=fake_truetype):
            font = text_render._get_font(22)
        self.assertIsNotNone(font)
        self.assertEqual(calls[0], "/AstrBot/data/font.ttf")

    def test_no_font_returns_none_without_load_default(self):
        with patch.object(
            text_render.ImageFont, "truetype", side_effect=OSError("no font")
        ) as mock_truetype, patch.object(
            text_render.ImageFont, "load_default"
        ) as mock_load_default:
            font = text_render._get_font(22, font_path="/nonexistent/font.ttf")
        self.assertIsNone(font)
        mock_truetype.assert_called()
        mock_load_default.assert_not_called()


class RenderAbstractImageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="paper_render_"))

    def test_no_cjk_font_returns_none_without_load_default(self):
        out = self._tmp / "abstract.png"
        with patch.object(
            text_render.ImageFont, "truetype", side_effect=OSError("no font")
        ), patch.object(
            text_render.ImageFont, "load_default"
        ) as mock_load_default:
            result = text_render.render_abstract_image(
                "基于深度学习的目标检测方法。", out
            )
        self.assertIsNone(result)
        mock_load_default.assert_not_called()
        self.assertFalse(out.exists())

    def test_empty_abstract_returns_none(self):
        out = self._tmp / "abstract.png"
        with patch.object(text_render.ImageFont, "truetype") as mock_truetype:
            result = text_render.render_abstract_image("", out)
        self.assertIsNone(result)
        mock_truetype.assert_not_called()

    def test_renders_image_when_system_cjk_font_available(self):
        out = self._tmp / "abstract.png"
        real_truetype = text_render.ImageFont.truetype

        def fake_truetype(path, size, **kwargs):
            if not Path(path).exists():
                raise OSError("no font")
            return real_truetype(path, size)

        with patch.object(
            text_render.ImageFont, "truetype", side_effect=fake_truetype
        ):
            result = text_render.render_abstract_image(
                "基于深度学习的目标检测方法。", out
            )
        self.assertEqual(result, out)
        self.assertTrue(out.exists())
        with open(out, "rb") as f:
            header = f.read(8)
        self.assertEqual(header, b"\x89PNG\r\n\x1a\n")

    def test_render_failure_returns_none(self):
        out = self._tmp / "abstract.png"
        with patch.object(
            text_render.ImageFont, "truetype", side_effect=OSError("no font")
        ):
            result = text_render.render_abstract_image("中文", out)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
