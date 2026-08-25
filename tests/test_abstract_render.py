"""Tests for the abstract-image renderer dispatch in main.py."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_PLUGIN_ROOT)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from tests.astrbot_stubs import install

install()

from astrbot_plugin_paper import main as plugin_main
from astrbot_plugin_paper.arxiv_client import ArxivPaper
from astrbot_plugin_paper.huggingface_client import HuggingFacePaper
from astrbot_plugin_paper.main import ArxivPlugin


def _make_plugin(config_overrides: dict | None = None) -> ArxivPlugin:
    config = {
        "arxiv_config": {
            "categories": ["cs.AI"],
            "max_results": 1,
            "timeout_seconds": 10,
        },
        "huggingface_config": {"max_results": 1, "timeout_seconds": 10},
        "network_config": {"proxy": ""},
        "send_config": {
            "push_time": "09:00",
            "huggingface_push_time": "10:00",
            "push_timezone": "Asia/Shanghai",
            "target_sessions": [],
            "use_forward": False,
            "bot_name": "ArXiv Bot",
            "arxiv_bot_name": "ArXiv Bot",
            "huggingface_bot_name": "Hugging Face Bot",
            "send_abstract": True,
            "attach_pdf": False,
            "screenshot_pdf": False,
            "screenshot_dpi": 150,
            "max_pdf_size_mb": 20,
            "history_retention_days": 30,
        },
        "llm_config": {
            "abstract_mode": "original",
            "llm_summarize": False,
            "llm_provider_id": "",
            "llm_summary_prompt": "",
        },
    }
    for section, overrides in (config_overrides or {}).items():
        config[section].update(overrides)
    plugin = ArxivPlugin(context=MagicMock(), config=config)
    plugin._temp_dir = Path(tempfile.mkdtemp(prefix="paper_test_"))
    plugin._cache = None
    return plugin


def _make_arxiv_paper() -> ArxivPaper:
    return ArxivPaper(
        arxiv_id="2501.12345",
        title="A Test Paper",
        authors=["Alice", "Bob"],
        abstract="基于深度学习的目标检测方法。",
        categories=["cs.CV"],
        published="2025-01-01T00:00:00Z",
        updated="2025-01-01T00:00:00Z",
        pdf_url="",
        abs_url="https://arxiv.org/abs/2501.12345",
    )


def _make_hf_paper() -> HuggingFacePaper:
    return HuggingFacePaper(
        id="papers/huggingface/test",
        title="A HF Paper",
        authors=[{"name": "Alice"}],
        summary="基于深度学习的目标检测方法。",
        publishedAt="2025-01-01T00:00:00Z",
        projectPage="https://huggingface.co/papers/test",
    )


def _has_plain_abstract(chains) -> bool:
    for chain in chains:
        for comp in chain.chain:
            if comp.type == "Plain" and str(comp.text).startswith("📝 摘要:"):
                return True
    return False


def _has_image(chains) -> bool:
    for chain in chains:
        for comp in chain.chain:
            if comp.type == "Image":
                return True
    return False


class AbstractImageDefaultTest(unittest.TestCase):
    def test_abstract_as_image_defaults_to_false(self):
        plugin = _make_plugin()
        self.assertNotIn("abstract_as_image", plugin._send_cfg)
        self.assertFalse(plugin._send_cfg.get("abstract_as_image", False))

        async def run():
            with patch.object(
                plugin, "text_to_image", new=AsyncMock()
            ) as mock_t2i:
                chains = await plugin._process_single_paper(_make_arxiv_paper())
            mock_t2i.assert_not_awaited()
            self.assertTrue(_has_plain_abstract(chains))
            self.assertFalse(_has_image(chains))

        self._async_run(run())

    def test_schema_declares_abstract_as_image_default_false(self):
        schema_path = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        schema_path = schema_path / "_conf_schema.json"
        import json

        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        item = schema["send_config"]["items"]["abstract_as_image"]
        self.assertIs(item["default"], False)

    def test_default_config_sends_plain_abstract(self):
        async def run():
            plugin = _make_plugin()
            with patch.object(
                plugin, "text_to_image", new=AsyncMock(return_value="")
            ):
                chains = await plugin._process_single_paper(_make_arxiv_paper())
            self.assertTrue(_has_plain_abstract(chains))
            self.assertFalse(_has_image(chains))

        self._async_run(run())

    def _async_run(self, awaitable):
        import asyncio

        return asyncio.get_event_loop().run_until_complete(awaitable)


class AbstractImageT2iTest(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="paper_t2i_"))
        self.png = self._tmp / "result.png"
        self.png.write_bytes(b"fake-png")
        self.plugin = _make_plugin(
            {
                "send_config": {
                    "abstract_as_image": True,
                    "abstract_image_renderer": "t2i",
                }
            }
        )

    def _run(self, awaitable):
        import asyncio

        return asyncio.get_event_loop().run_until_complete(awaitable)

    def test_t2i_success_uses_existing_file_and_not_pillow(self):
        out = self.plugin._temp_dir / "abstract.png"
        with patch.object(
            self.plugin, "text_to_image", new=AsyncMock(return_value=str(self.png))
        ), patch.object(
            plugin_main.text_render, "render_abstract_image"
        ) as mock_pillow:
            path, key = self._run(
                self.plugin._render_abstract_image("基于深度学习的目标检测方法。", out)
            )
        self.assertEqual(key, "t2i-v2")
        self.assertEqual(path, self.png)
        self.assertTrue(path.exists() and path.is_file())
        mock_pillow.assert_not_called()

    def test_t2i_exception_returns_none_and_not_pillow(self):
        out = self.plugin._temp_dir / "abstract.png"
        with patch.object(
            self.plugin,
            "text_to_image",
            new=AsyncMock(side_effect=RuntimeError("t2i down")),
        ), patch.object(
            plugin_main.text_render, "render_abstract_image"
        ) as mock_pillow:
            path, key = self._run(
                self.plugin._render_abstract_image("基于深度学习的目标检测方法。", out)
            )
        self.assertIsNone(path)
        self.assertEqual(key, "t2i-v2")
        mock_pillow.assert_not_called()

    def test_t2i_exception_upper_layer_builds_plain(self):
        async def run():
            with patch.object(
                self.plugin,
                "text_to_image",
                new=AsyncMock(side_effect=RuntimeError("t2i down")),
            ), patch.object(
                plugin_main.text_render, "render_abstract_image"
            ) as mock_pillow:
                chains = await self.plugin._process_single_paper(_make_arxiv_paper())
            self.assertTrue(_has_plain_abstract(chains))
            self.assertFalse(_has_image(chains))
            mock_pillow.assert_not_called()

        self._run(run())

    def test_t2i_empty_result_returns_none(self):
        out = self.plugin._temp_dir / "abstract.png"
        with patch.object(
            self.plugin, "text_to_image", new=AsyncMock(return_value="")
        ), patch.object(
            plugin_main.text_render, "render_abstract_image"
        ) as mock_pillow:
            path, key = self._run(
                self.plugin._render_abstract_image("基于深度学习的目标检测方法。", out)
            )
        self.assertIsNone(path)
        self.assertEqual(key, "t2i-v2")
        mock_pillow.assert_not_called()

    def test_t2i_nonexistent_result_returns_none(self):
        out = self.plugin._temp_dir / "abstract.png"
        missing = self._tmp / "missing.png"
        with patch.object(
            self.plugin, "text_to_image", new=AsyncMock(return_value=str(missing))
        ):
            path, key = self._run(
                self.plugin._render_abstract_image("基于深度学习的目标检测方法。", out)
            )
        self.assertIsNone(path)
        self.assertEqual(key, "t2i-v2")

    def test_hf_path_uses_unified_renderer(self):
        async def run():
            with patch.object(
                ArxivPlugin, "_render_abstract_image", new=AsyncMock()
            ) as mock_render:
                mock_render.return_value = (self.png, "t2i-v2")
                chains = await self.plugin._process_hf_html_analysis(
                    _make_hf_paper(),
                    index=1,
                    paper_key="huggingface:test",
                    warnings=[],
                )
            self.assertTrue(_has_image(chains))
            mock_render.assert_awaited_once()
            self.assertEqual(mock_render.await_args[0][0], "基于深度学习的目标检测方法。")

        self._run(run())

    def test_arxiv_path_uses_unified_renderer(self):
        async def run():
            with patch.object(
                ArxivPlugin, "_render_abstract_image", new=AsyncMock()
            ) as mock_render:
                mock_render.return_value = (self.png, "t2i-v2")
                chains = await self.plugin._process_single_paper(_make_arxiv_paper())
            self.assertTrue(_has_image(chains))
            mock_render.assert_awaited_once()

        self._run(run())

    def test_unknown_renderer_falls_back_to_t2i(self):
        plugin = _make_plugin(
            {
                "send_config": {
                    "abstract_as_image": True,
                    "abstract_image_renderer": "bogus",
                }
            }
        )
        self.assertEqual(plugin._abstract_renderer(), "t2i")
        self.assertEqual(plugin._abstract_renderer_key(), "t2i-v2")


class AbstractImagePillowTest(unittest.TestCase):
    def test_pillow_passes_font_path(self):
        plugin = _make_plugin(
            {
                "send_config": {
                    "abstract_as_image": True,
                    "abstract_image_renderer": "pillow",
                    "abstract_font_path": "/AstrBot/data/fonts/NotoSansCJK-Regular.ttc",
                }
            }
        )
        out = plugin._temp_dir / "abstract.png"
        with patch.object(
            plugin_main.text_render,
            "render_abstract_image",
            return_value=out,
        ) as mock_render:
            path, key = plugin._render_abstract_image_via_pillow("纯中文摘要。", out)
        self.assertEqual(key, "pillow-v2")
        self.assertEqual(path, out)
        mock_render.assert_called_once_with(
            "纯中文摘要。",
            out,
            font_path="/AstrBot/data/fonts/NotoSansCJK-Regular.ttc",
        )

    def test_pillow_without_font_path_passes_none(self):
        plugin = _make_plugin(
            {
                "send_config": {
                    "abstract_as_image": True,
                    "abstract_image_renderer": "pillow",
                }
            }
        )
        out = plugin._temp_dir / "abstract.png"
        with patch.object(
            plugin_main.text_render,
            "render_abstract_image",
            return_value=None,
        ) as mock_render:
            path, key = plugin._render_abstract_image_via_pillow("纯中文摘要。", out)
        self.assertIsNone(path)
        self.assertEqual(key, "pillow-v2")
        self.assertEqual(mock_render.call_args.kwargs["font_path"], None)

    def test_pillow_failure_falls_back_to_plain(self):
        async def run():
            plugin = _make_plugin(
                {
                    "send_config": {
                        "abstract_as_image": True,
                        "abstract_image_renderer": "pillow",
                    }
                }
            )
            with patch.object(
                plugin_main.text_render,
                "render_abstract_image",
                return_value=None,
            ):
                chains = await plugin._process_single_paper(_make_arxiv_paper())
            self.assertTrue(_has_plain_abstract(chains))
            self.assertFalse(_has_image(chains))

        import asyncio

        asyncio.get_event_loop().run_until_complete(run())


class UseT2IFlagTest(unittest.TestCase):
    def test_make_result_disables_t2i(self):
        from tests.astrbot_stubs import MessageChain

        chain = MessageChain()
        chain.chain.append("dummy")
        result = ArxivPlugin._make_result(chain)
        self.assertIs(result.use_t2i_, False)
        self.assertEqual(result.chain, chain.chain)


if __name__ == "__main__":
    unittest.main()
