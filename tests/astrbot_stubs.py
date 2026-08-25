"""AstrBot API stub for offline unit tests.

This module provides minimal fake implementations of the ``astrbot`` modules
that the plugin imports, so that the plugin source can be imported and tested
without a running AstrBot installation or t2i-service.
"""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path


class Plain:
    def __init__(self, text: str = "") -> None:
        self.type = "Plain"
        self.text = text

    def __repr__(self) -> str:
        return f"Plain({self.text!r})"


class Image:
    def __init__(self, file: str = "") -> None:
        self.type = "Image"
        self.file = file

    @classmethod
    def fromFileSystem(cls, path: str) -> "Image":
        return cls(path)

    def __repr__(self) -> str:
        return f"Image({self.file!r})"


class File:
    def __init__(self, name: str = "", file: str = "") -> None:
        self.type = "File"
        self.name = name
        self.file = file

    def __repr__(self) -> str:
        return f"File({self.name!r}, {self.file!r})"


class Node:
    def __init__(self, content=None, name: str = "", uin: str = "") -> None:
        self.type = "Node"
        self.content = content or []
        self.name = name
        self.uin = uin


class Nodes:
    def __init__(self, nodes=None) -> None:
        self.type = "Nodes"
        self.nodes = nodes or []


class MessageChain:
    def __init__(self, chain=None) -> None:
        self.chain = chain if chain is not None else []
        self.use_t2i_: bool | None = None
        self.use_markdown_: bool | None = None
        self.type: str | None = None

    def message(self, message: str) -> "MessageChain":
        self.chain.append(Plain(message))
        return self

    def derive(self, chain=None) -> "MessageChain":
        new = MessageChain(chain=chain if chain is not None else [])
        new.use_t2i_ = self.use_t2i_
        new.use_markdown_ = self.use_markdown_
        new.type = self.type
        return new


class MessageEventResult(MessageChain):
    def __init__(self, chain=None) -> None:
        super().__init__(chain)


class Context:
    pass


class StarTools:
    @staticmethod
    def get_data_dir(name: str) -> Path:
        return Path("/tmp/astrbot_plugin_paper_test_data") / name


def _register_decorator(*args, **kwargs):
    def wrapper(fn):
        return fn

    return wrapper


class _CommandGroupStub:
    """Mimics astrbot's RegisteringCommandable returned by command_group."""

    def command(self, command_name=None, sub_command=None, alias=None, **kwargs):
        return _register_decorator

    def group(self, command_group_name=None, sub_command=None, alias=None, **kwargs):
        return _register_decorator

    def custom_filter(self, custom_type_filter, *args, **kwargs):
        return _register_decorator

    def regex(self, *args, **kwargs):
        return _register_decorator

    def __call__(self, *args, **kwargs):
        return self


def _command_group(name=None, sub_command=None, alias=None, **kwargs):
    return _CommandGroupStub()


def _register_module_export(mod, names):
    for name in names:
        setattr(mod, name, _register_decorator)
    mod.command_group = _command_group


class Star:
    def __init__(self, context: Context, config: dict | None = None) -> None:
        self.context = context
        self.config = config or {}

    async def text_to_image(self, text: str, return_url: bool = True) -> str:
        raise NotImplementedError("stub text_to_image")


def _install_filter_module():
    mod = types.ModuleType("astrbot.api.event.filter")
    _register_module_export(
        mod,
        [
            "command",
            "command_class",
            "regex",
            "custom_filter",
            "event_message_type",
            "permission_type",
            "platform_adapter_type",
            "on_plugin_loaded",
            "on_plugin_unloaded",
            "on_astrbot_loaded",
            "on_decorating_result",
            "on_llm_request",
            "on_llm_response",
            "on_using_llm_tool",
            "on_llm_tool_respond",
            "on_platform_loaded",
            "on_plugin_error",
            "on_agent_begin",
            "on_agent_done",
        ],
    )
    return mod


def install() -> None:
    """Install the ``astrbot`` stub modules into ``sys.modules`` (idempotent)."""
    if "astrbot" in sys.modules and getattr(sys.modules["astrbot"], "_stub", False):
        return

    logger = logging.getLogger("astrbot")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.NullHandler())

    astrbot = types.ModuleType("astrbot")
    astrbot.logger = logger
    astrbot._stub = True

    # astrbot.api
    api = types.ModuleType("astrbot.api")
    api.logger = logger
    api.AstrBotConfig = dict

    # astrbot.api.event
    event = types.ModuleType("astrbot.api.event")
    event.AstrMessageEvent = type("AstrMessageEvent", (), {})
    event.MessageChain = MessageChain
    event.MessageEventResult = MessageEventResult
    event.filter = _install_filter_module()
    api.event = event

    # astrbot.api.message_components
    message_components = types.ModuleType("astrbot.api.message_components")
    message_components.Plain = Plain
    message_components.Image = Image
    message_components.File = File
    message_components.Node = Node
    message_components.Nodes = Nodes
    api.message_components = message_components

    # astrbot.api.star
    star = types.ModuleType("astrbot.api.star")
    star.Context = Context
    star.Star = Star
    star.StarTools = StarTools
    star.register = _register_decorator
    api.star = star

    # astrbot.core.message.message_event_result
    core_msr = types.ModuleType("astrbot.core.message.message_event_result")
    core_msr.MessageChain = MessageChain
    core_msr.MessageEventResult = MessageEventResult

    # astrbot.core.star.filter.command
    core_filter = types.ModuleType("astrbot.core.star.filter.command")
    core_filter.GreedyStr = str

    # astrbot.core.star (for completeness, in case deeper imports happen)
    core_star = types.ModuleType("astrbot.core.star")
    core_star.Star = Star
    core_star.Context = Context
    core_star.StarTools = StarTools

    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = event
    sys.modules["astrbot.api.message_components"] = message_components
    sys.modules["astrbot.api.star"] = star
    sys.modules["astrbot.core"] = types.ModuleType("astrbot.core")
    sys.modules["astrbot.core.message"] = types.ModuleType("astrbot.core.message")
    sys.modules["astrbot.core.message.message_event_result"] = core_msr
    sys.modules["astrbot.core.star"] = core_star
    sys.modules["astrbot.core.star.filter"] = types.ModuleType("astrbot.core.star.filter")
    sys.modules["astrbot.core.star.filter.command"] = core_filter

    _stub_optional_runtime_deps()


def _stub_optional_runtime_deps() -> None:
    """Provide inert fallbacks for runtime deps that may be absent in a bare CI env.

    Only installed when the real package is not importable; the stubs are never
    exercised by these tests (no real network / PDF work is performed).
    """
    for dep in ("feedparser", "aiohttp"):
        if dep in sys.modules:
            continue
        try:
            __import__(dep)
        except ImportError:
            sys.modules[dep] = types.ModuleType(dep)
