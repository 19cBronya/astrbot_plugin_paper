"""arXiv API 异步客户端。

通过 aiohttp + feedparser 实现论文搜索和最新论文获取。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp
import feedparser

from astrbot.api import logger

ARXIV_API_URL = "https://export.arxiv.org/api/query"
_USER_AGENT = "AstrBot astrbot_plugin_paper/1.0"
_MAX_RETRIES = 3
_INITIAL_RETRY_DELAY_SECONDS = 1.0

# arXiv API 请求间隔（遵守官方礼貌策略）
_API_DELAY_SECONDS = 3.0


def _normalize_proxy(proxy: str | None) -> str | None:
    if not proxy:
        return None
    proxy = proxy.strip()
    if not proxy:
        return None
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", proxy):
        proxy = f"http://{proxy}"
    return proxy


# 常见 arXiv 学科分类及其中文说明
ARXIV_CATEGORIES: dict[str, str] = {
    # 计算机科学
    "cs.AI": "人工智能",
    "cs.CL": "计算语言学 (NLP)",
    "cs.CV": "计算机视觉",
    "cs.LG": "机器学习",
    "cs.CR": "密码学与安全",
    "cs.DB": "数据库",
    "cs.DS": "数据结构与算法",
    "cs.IR": "信息检索",
    "cs.NE": "神经与进化计算",
    "cs.RO": "机器人学",
    "cs.SE": "软件工程",
    "cs.SI": "社交与信息网络",
    # 电气工程与系统
    "eess.AS": "音频与语音处理",
    "eess.IV": "图像与视频处理",
    "eess.SP": "信号处理",
    # 数学
    "math.CO": "组合数学",
    "math.OC": "优化与控制",
    "math.PR": "概率论",
    "math.ST": "统计理论",
    # 统计学
    "stat.ML": "机器学习 (统计)",
    "stat.ME": "方法论",
    # 物理学
    "physics.comp-ph": "计算物理",
    "quant-ph": "量子物理",
    "hep-th": "高能物理 - 理论",
    "cond-mat.stat-mech": "统计力学",
    # 定量生物学
    "q-bio.BM": "生物分子",
    "q-bio.GN": "基因组学",
    # 定量金融
    "q-fin.ST": "统计金融",
}


@dataclass
class ArxivPaper:
    """表示一篇 arXiv 论文。"""

    arxiv_id: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    categories: list[str] = field(default_factory=list)
    published: str = ""
    updated: str = ""
    pdf_url: str = ""
    abs_url: str = ""

    @property
    def published_date(self) -> str:
        """返回可读的发布日期字符串。"""
        try:
            dt = datetime.fromisoformat(self.published.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            return self.published


def _normalize_query_terms(value: list[str] | str | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = re.split(r"[\n,]+", value)
    terms = [str(term).strip() for term in value if str(term).strip()]
    return terms or None


def _build_search_query(
    *,
    query: str = "",
    categories: list[str] | None = None,
    tags: list[str] | None = None,
) -> str:
    """构建 arXiv API 搜索查询字符串。

    将自由文本查询、分类过滤和关键词标签组合为一个 arXiv API 接受的查询字符串。
    """
    parts: list[str] = []

    if query:
        parts.append(f"all:{query}")

    categories = _normalize_query_terms(categories)
    tags = _normalize_query_terms(tags)

    if categories:
        cat_parts = [f"cat:{cat}" for cat in categories]
        if len(cat_parts) == 1:
            parts.append(cat_parts[0])
        else:
            parts.append("+OR+".join(f"({part})" for part in cat_parts))

    if tags:
        tag_parts = [f"all:{tag}" for tag in tags]
        if len(tag_parts) == 1:
            parts.append(tag_parts[0])
        else:
            parts.append("+OR+".join(f"({part})" for part in tag_parts))

    return "+AND+".join(parts) if parts else "all:*"


def _parse_feed_entry(entry: dict) -> ArxivPaper:
    """将单条 feedparser 条目解析为 ArxivPaper 对象。"""
    # 从条目 ID URL 中提取 arXiv ID
    arxiv_id = entry.get("id", "")
    if "/abs/" in arxiv_id:
        arxiv_id = arxiv_id.split("/abs/")[-1]

    # 提取 PDF 链接
    pdf_url = ""
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            pdf_url = link.get("href", "")
            break
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    # 确保 PDF URL 以 .pdf 结尾且使用 https
    if pdf_url:
        if pdf_url.startswith("http://"):
            pdf_url = pdf_url.replace("http://", "https://", 1)
        if not pdf_url.endswith(".pdf"):
            pdf_url += ".pdf"

    # 提取作者列表
    authors = [a.get("name", "") for a in entry.get("authors", [])]

    # 提取分类标签
    categories = [t.get("term", "") for t in entry.get("tags", [])]

    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=entry.get("title", "").replace("\n", " ").strip(),
        authors=authors,
        abstract=entry.get("summary", "").strip(),
        categories=categories,
        published=entry.get("published", ""),
        updated=entry.get("updated", ""),
        pdf_url=pdf_url,
        abs_url=entry.get("id", ""),
    )


async def _fetch_api_text(
    params: dict[str, object],
    timeout: int,
    proxy: str | None = None,
) -> str:
    headers = {"User-Agent": _USER_AGENT}
    backoff_seconds = _INITIAL_RETRY_DELAY_SECONDS
    proxy_url = _normalize_proxy(proxy)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    ARXIV_API_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(
                        total=timeout,
                        sock_connect=min(15, timeout),
                    ),
                    proxy=proxy_url,
                ) as resp:
                    if resp.status == 429 or 500 <= resp.status < 600:
                        if attempt == _MAX_RETRIES:
                            resp.raise_for_status()
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue

                    resp.raise_for_status()
                    return await resp.text()
        except asyncio.TimeoutError:
            # 超时：服务端响应慢，降级重试无意义
            if proxy_url is not None:
                logger.warning(
                    "arXiv 请求代理 %s 超时，尝试直连",
                    proxy_url,
                )
                proxy_url = None
                continue
            # 直连也超时，不再重试
            raise
        except aiohttp.ClientError as exc:
            # 连接错误：可能是暂时性网络问题，可以重试
            if proxy_url is not None:
                logger.warning(
                    "arXiv 请求代理 %s 失败，尝试直连: %s",
                    proxy_url,
                    exc,
                )
                proxy_url = None
                await asyncio.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            if attempt == _MAX_RETRIES:
                raise
            await asyncio.sleep(backoff_seconds)
            backoff_seconds *= 2

    raise RuntimeError("无法从 arXiv API 获取响应文本")


async def get_paper_by_id(
    arxiv_id: str,
    *,
    timeout: int = 60,
    proxy: str | None = None,
) -> ArxivPaper | None:
    """通过 arXiv ID 获取单篇论文。

    Args:
        arxiv_id: arXiv 论文 ID，如 ``2501.12345`` 或 ``cs/0601001``。
        timeout: HTTP 请求超时秒数。

    Returns:
        ArxivPaper 对象，未找到时返回 None。
    """
    params = {
        "id_list": arxiv_id,
        "max_results": 1,
    }

    text = await _fetch_api_text(params, timeout, proxy=proxy)
    await asyncio.sleep(_API_DELAY_SECONDS)

    feed = feedparser.parse(text)
    if not feed.entries:
        return None
    return _parse_feed_entry(feed.entries[0])


async def search_papers(
    query: str,
    *,
    max_results: int = 5,
    timeout: int = 60,
    proxy: str | None = None,
) -> list[ArxivPaper]:
    """按关键词搜索 arXiv 论文。

    Args:
        query: 搜索关键词。
        max_results: 最大返回结果数。
        timeout: HTTP 请求超时秒数。

    Returns:
        ArxivPaper 对象列表。
    """
    search_query = _build_search_query(query=query)
    return await _fetch_papers(
        search_query=search_query,
        max_results=max_results,
        sort_by="relevance",
        timeout=timeout,
        proxy=proxy,
    )


async def get_latest_papers(
    *,
    categories: list[str] | None = None,
    tags: list[str] | None = None,
    max_results: int = 5,
    timeout: int = 60,
    proxy: str | None = None,
) -> list[ArxivPaper]:
    """获取匹配分类和标签的最新论文。

    Args:
        categories: arXiv 分类代码列表，如 ["cs.AI", "cs.LG"]。
        tags: 额外的关键词标签，用于模糊匹配。
        max_results: 最大返回结果数。
        timeout: HTTP 请求超时秒数。

    Returns:
        按提交日期降序排列的 ArxivPaper 对象列表。
    """
    search_query = _build_search_query(categories=categories, tags=tags)
    return await _fetch_papers(
        search_query=search_query,
        max_results=max_results,
        sort_by="submittedDate",
        timeout=timeout,
        proxy=proxy,
    )


async def _fetch_papers(
    *,
    search_query: str,
    max_results: int,
    sort_by: str,
    timeout: int,
    proxy: str | None = None,
) -> list[ArxivPaper]:
    """底层 arXiv API 请求方法。"""
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    text = await _fetch_api_text(params, timeout, proxy=proxy)
    # 遵守 arXiv API 礼貌延迟
    await asyncio.sleep(_API_DELAY_SECONDS)

    feed = feedparser.parse(text)
    papers: list[ArxivPaper] = []
    for entry in feed.entries:
        papers.append(_parse_feed_entry(entry))

    return papers
