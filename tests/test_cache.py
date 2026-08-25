"""Tests for PaperCache abstract-image renderer key handling."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.astrbot_stubs import install

install()

import paper_cache


class AbstractImageCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="paper_cache_"))
        self.cache = paper_cache.PaperCache(self._tmp, retention_days=30)
        self.png = self._tmp / "src.png"
        self.png.write_bytes(b"fake-png")

    def test_different_renderer_keys_produce_distinct_entries(self):
        abstract = "基于深度学习的目标检测方法。"
        legacy = self.cache.store_abstract_image(
            "arxiv:1", abstract_text=abstract, source_path=self.png
        )
        t2i = self.cache.store_abstract_image(
            "arxiv:1",
            abstract_text=abstract,
            source_path=self.png,
            renderer_key="t2i-v2",
        )
        pillow = self.cache.store_abstract_image(
            "arxiv:1",
            abstract_text=abstract,
            source_path=self.png,
            renderer_key="pillow-v2",
        )
        self.assertIsNotNone(legacy)
        self.assertIsNotNone(t2i)
        self.assertIsNotNone(pillow)
        self.assertNotEqual(legacy, t2i)
        self.assertNotEqual(t2i, pillow)
        self.assertNotEqual(legacy, pillow)

    def test_t2i_v2_does_not_hit_legacy_cache(self):
        abstract = "基于深度学习的目标检测方法。"
        legacy = self.cache.store_abstract_image(
            "arxiv:1", abstract_text=abstract, source_path=self.png
        )
        self.assertIsNotNone(legacy)
        got_t2i = self.cache.get_cached_abstract_image(
            "arxiv:1", abstract_text=abstract, renderer_key="t2i-v2"
        )
        self.assertIsNone(got_t2i)

    def test_each_renderer_key_roundtrips(self):
        abstract = "一些中文摘要 $E=mc^2$"
        for key in ("legacy", "t2i-v2", "pillow-v2"):
            stored = self.cache.store_abstract_image(
                "arxiv:1",
                abstract_text=abstract,
                source_path=self.png,
                renderer_key=key,
            )
            got = self.cache.get_cached_abstract_image(
                "arxiv:1", abstract_text=abstract, renderer_key=key
            )
            self.assertEqual(got, stored)

    def test_default_renderer_key_is_legacy(self):
        abstract = "默认 renderer_key 兼容。"
        stored = self.cache.store_abstract_image(
            "arxiv:1", abstract_text=abstract, source_path=self.png
        )
        got = self.cache.get_cached_abstract_image(
            "arxiv:1", abstract_text=abstract
        )
        self.assertEqual(got, stored)

    def test_pdf_translation_summary_cache_untouched(self):
        abstract = "基于深度学习的目标检测方法。"
        self.cache.store_abstract_image(
            "arxiv:1",
            abstract_text=abstract,
            source_path=self.png,
            renderer_key="t2i-v2",
        )
        self.cache.store_translation(
            "arxiv:1", abstract=abstract, provider_id="p", translated="译文"
        )
        self.cache.store_summary(
            "arxiv:1",
            source_fingerprint="fp",
            provider_id="p",
            prompt="prompt",
            summary="总结",
        )
        self.assertEqual(
            self.cache.get_cached_translation(
                "arxiv:1", abstract=abstract, provider_id="p"
            ),
            "译文",
        )
        self.assertEqual(
            self.cache.get_cached_summary(
                "arxiv:1",
                source_fingerprint="fp",
                provider_id="p",
                prompt="prompt",
            ),
            "总结",
        )
        record = self.cache._data["papers"]["arxiv:1"]
        self.assertIn("abstract_translations", record)
        self.assertIn("summaries", record)
        self.assertIn("abstract_images", record)


if __name__ == "__main__":
    unittest.main()
