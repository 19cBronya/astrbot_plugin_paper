"""Hugging Face Papers API 异步客户端。

通过 aiohttp 实现论文获取。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp

from astrbot.api import logger

from astrbot.api import logger

HUGGINGFACE_API_URL = "https://huggingface.co/api/papers"
_USER_AGENT = "AstrBot astrbot_plugin_paper/1.0"
_MAX_RETRIES = 3
_INITIAL_RETRY_DELAY_SECONDS = 1.0

# Hugging Face API 请求间隔
_API_DELAY_SECONDS = 1.0


def _normalize_proxy(proxy: str | None) -> str | None:
    if not proxy:
        return None
    proxy = proxy.strip()
    if not proxy:
        return None
    if not proxy.startswith(("http://", "https://", "socks5://", "socks4://", "socks://")):
        proxy = f"http://{proxy}"
    return proxy


@dataclass
class HuggingFacePaper:
    """表示一篇 Hugging Face 论文。"""

    id: str = ""
    title: str = ""
    authors: list[dict] = field(default_factory=list)
    summary: str = ""
    ai_summary: str = ""
    publishedAt: str = ""
    upvotes: int = 0
    projectPage: str = ""
    thumbnailUrl: str = ""
    organization: dict | None = None

    @property
    def arxiv_id(self) -> str:
        """兼容 ArxivPaper 的属性，返回 id。"""
        return self.id

    @property
    def abstract(self) -> str:
        """兼容 ArxivPaper 的属性，返回 summary。"""
        return self.summary

    @property
    def pdf_url(self) -> str:
        """兼容 ArxivPaper 的属性，返回 projectPage 或空。"""
        return self.projectPage or ""

    @property
    def abs_url(self) -> str:
        """兼容 ArxivPaper 的属性，返回 projectPage 或空。"""
        return self.projectPage or ""

    @property
    def categories(self) -> list[str]:
        """兼容 ArxivPaper 的属性，返回空列表。"""
        return []

    @property
    def published_date(self) -> str:
        """返回可读的发布日期字符串。"""
        try:
            dt = datetime.fromisoformat(self.publishedAt.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            return self.publishedAt


def _parse_paper_entry(entry: dict) -> HuggingFacePaper:
    """将单条 API 条目解析为 HuggingFacePaper 对象。"""
    return HuggingFacePaper(
        id=entry.get("id", ""),
        title=entry.get("title", ""),
        authors=entry.get("authors", []),
        summary=entry.get("summary", ""),
        ai_summary=entry.get("ai_summary", ""),
        publishedAt=entry.get("publishedAt", ""),
        upvotes=entry.get("upvotes", 0),
        projectPage=entry.get("projectPage", ""),
        thumbnailUrl=entry.get("thumbnailUrl", ""),
        organization=entry.get("organization"),
    )


async def _fetch_api_json(
    params: dict[str, object],
    timeout: int,
    proxy: str | None = None,
) -> list[dict]:
    headers = {"User-Agent": _USER_AGENT}
    backoff_seconds = _INITIAL_RETRY_DELAY_SECONDS
    proxy_url = _normalize_proxy(proxy)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    HUGGINGFACE_API_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    proxy=proxy_url,
                ) as resp:
                    if resp.status == 429 or 500 <= resp.status < 600:
                        if attempt == _MAX_RETRIES:
                            resp.raise_for_status()
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue

                    resp.raise_for_status()
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if proxy_url is not None:
                logger.warning(
                    "Hugging Face 请求代理 %s 失败，尝试直连: %s",
                    proxy_url,
                    exc,
                )
                proxy_url = None
                continue
            if attempt == _MAX_RETRIES:
                raise
            await asyncio.sleep(backoff_seconds)
            backoff_seconds *= 2

    raise RuntimeError("无法从 Hugging Face API 获取响应")


async def get_daily_papers(
    *,
    limit: int = 5,
    timeout: int = 30,
    proxy: str | None = None,
) -> list[HuggingFacePaper]:
    """获取 Hugging Face 每日论文。

    Args:
        limit: 最大返回结果数。
        timeout: HTTP 请求超时秒数。

    Returns:
        HuggingFacePaper 对象列表。
    """
    params = {
        "limit": limit,
        "sort": "trending",
    }

    data = await _fetch_api_json(params, timeout, proxy=proxy)
    await asyncio.sleep(_API_DELAY_SECONDS)

    papers: list[HuggingFacePaper] = []
    for entry in data:
        papers.append(_parse_paper_entry(entry))

    return papers


async def search_papers(
    query: str,
    *,
    limit: int = 5,
    timeout: int = 30,
    proxy: str | None = None,
) -> list[HuggingFacePaper]:
    """按关键词搜索 Hugging Face 论文。

    Args:
        query: 搜索关键词。
        limit: 最大返回结果数。
        timeout: HTTP 请求超时秒数。

    Returns:
        HuggingFacePaper 对象列表。
    """
    params = {
        "q": query,
        "limit": limit,
        "sort": "trending",
    }

    data = await _fetch_api_json(params, timeout, proxy=proxy)
    await asyncio.sleep(_API_DELAY_SECONDS)

    papers: list[HuggingFacePaper] = []
    for entry in data:
        papers.append(_parse_paper_entry(entry))

    return papers
