"""PDF 下载、体积校验、文本提取和首页截图模块。

使用 aiohttp 进行异步下载，pymupdf (fitz) 进行 PDF 处理。
PyMuPDF 为软依赖 —— 若未安装则相关功能优雅降级。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import aiohttp

from astrbot.api import logger

# 尝试导入 pymupdf，未安装则标记为不可用
try:
    import fitz  # pymupdf

    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    logger.info("pymupdf 未安装，PDF 截图和文本提取功能将被禁用。")

_PLAYWRIGHT_INSTALL_LOCK = asyncio.Lock()
_PLAYWRIGHT_INSTALL_STATE: dict[str, object] = {
    "status": "never",
    "last_attempt": 0.0,
    "last_message": "",
}
_PLAYWRIGHT_INSTALL_RETRY_COOLDOWN_SECONDS = 300.0


@dataclass
class _WebpageScreenshotError:
    code: str
    message: str


def _normalize_proxy(proxy: str | None) -> str | None:
    if not proxy:
        return None
    proxy = proxy.strip()
    if not proxy:
        return None
    if not proxy.startswith(("http://", "https://", "socks5://", "socks4://", "socks://")):
        proxy = f"http://{proxy}"
    return proxy


async def download_pdf(
    url: str,
    save_dir: Path,
    *,
    timeout: int = 30,
    max_size_mb: int = 20,
    proxy: str | None = None,
) -> Path | None:
    """下载 PDF 文件，支持体积限制。

    Args:
        url: PDF 下载链接。
        save_dir: 保存目录。
        timeout: HTTP 超时秒数。
        max_size_mb: 最大允许文件大小（MB）。

    Returns:
        下载成功返回文件路径，失败或超出大小限制返回 None。
    """
    max_bytes = max_size_mb * 1024 * 1024
    save_dir.mkdir(parents=True, exist_ok=True)

    # 从 URL 推导文件名
    filename = url.rstrip("/").split("/")[-1]
    if not filename.endswith(".pdf"):
        filename += ".pdf"
    save_path = save_dir / filename

    proxy_url = _normalize_proxy(proxy)
    max_attempts = 2 if proxy_url else 1
    downloaded = 0

    try:
        async with aiohttp.ClientSession() as session:
            for attempt in range(1, max_attempts + 1):
                try:
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=timeout),
                        allow_redirects=True,
                        proxy=proxy_url,
                    ) as resp:
                        resp.raise_for_status()

                        # 检查响应类型，拒绝 HTML 响应
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            logger.warning(
                                "PDF %s 返回了 HTML 而非 PDF (Content-Type: %s)",
                                url,
                                content_type,
                            )
                            return None

                        # 优先检查 Content-Length 头
                        content_length = resp.headers.get("Content-Length")
                        if content_length and int(content_length) > max_bytes:
                            logger.warning(
                                "PDF %s 超出大小限制: %s 字节 > %s 字节",
                                url,
                                content_length,
                                max_bytes,
                            )
                            return None

                        # 流式下载，实时校验大小
                        downloaded = 0
                        with open(save_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(8192):
                                downloaded += len(chunk)
                                if downloaded > max_bytes:
                                    logger.warning(
                                        "PDF %s 在下载过程中超出大小限制。",
                                        url,
                                    )
                                    f.close()
                                    save_path.unlink(missing_ok=True)
                                    return None
                                f.write(chunk)
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    if proxy_url is not None:
                        logger.warning(
                            "PDF 下载代理 %s 失败，尝试直连: %s",
                            proxy_url,
                            exc,
                        )
                        proxy_url = None
                        continue
                    raise

        # 验证下载的文件是否为有效 PDF（检查文件头魔数）
        with open(save_path, "rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            logger.warning(
                "PDF %s 下载的文件不是有效的 PDF (文件头: %r)",
                url,
                header,
            )
            save_path.unlink(missing_ok=True)
            return None

        logger.info("PDF 下载成功: %s (%d 字节)", save_path.name, downloaded)
        return save_path

    except Exception:
        logger.exception("从 %s 下载 PDF 失败", url)
        save_path.unlink(missing_ok=True)
        return None


async def resolve_pdf_url_from_webpage(
    url: str,
    *,
    timeout: int = 30,
    proxy: str | None = None,
) -> str | None:
    """从网页页面解析 PDF 链接，返回首个匹配的直接 PDF URL。"""
    proxy_url = _normalize_proxy(proxy)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
                proxy=proxy_url,
            ) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type.lower():
                    return None
                html = await resp.text()
                base_url = str(resp.url)
    except Exception:
        logger.exception("解析网页 PDF 链接失败: %s", url)
        return None

    candidates: list[str] = []
    candidates.extend(
        re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', html, flags=re.I)
    )
    if not candidates:
        candidates.extend(
            re.findall(r'(https?://[^"\'>\s]+\.pdf[^"\'>\s]*)', html, flags=re.I)
        )

    for href in candidates:
        if href.startswith("//"):
            href = "https:" + href
        full_url = urljoin(base_url, href)
        if full_url.lower().startswith(("http://", "https://")):
            return full_url

    return None


def screenshot_first_page(
    pdf_path: Path,
    output_dir: Path,
    *,
    dpi: int = 150,
) -> Path | None:
    """将 PDF 第一页渲染为 PNG 图片。

    Args:
        pdf_path: PDF 文件路径。
        output_dir: 截图保存目录。
        dpi: 渲染分辨率（每英寸点数），建议 72~300。

    Returns:
        截图文件路径，pymupdf 不可用或渲染失败返回 None。
    """
    if not PYMUPDF_AVAILABLE:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{pdf_path.stem}_page1.png"

    try:
        doc = fitz.open(str(pdf_path))
        if len(doc) == 0:
            doc.close()
            return None

        page = doc[0]
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        pix.save(str(output_path))
        doc.close()

        return output_path

    except Exception:
        logger.exception("PDF 首页截图失败: %s", pdf_path)
        return None


async def screenshot_webpage(
    url: str,
    output_dir: Path,
    *,
    timeout: int = 30,
    proxy: str | None = None,
    auto_install_browser: bool = False,
    install_timeout_seconds: int = 180,
) -> tuple[Path | None, str]:
    """对网页进行全页截图。

    Returns:
        (截图路径, 错误提示)。成功时错误提示为空字符串。
    """
    if not url:
        return None, "网页截图失败：URL 为空。"

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return (
            None,
            "网页截图失败：缺少 Playwright 依赖，请安装 playwright 并执行 playwright install。",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", url)[:80].strip("_") or "webpage"
    output_path = output_dir / f"{safe_name}_page.png"
    proxy_url = _normalize_proxy(proxy)
    proxy_attempts: list[str | None] = [proxy_url, None] if proxy_url else [None]
    install_timeout_seconds = max(10, int(install_timeout_seconds))

    async def _capture_once() -> tuple[Path | None, _WebpageScreenshotError | None]:
        for current_proxy in proxy_attempts:
            browser = None
            try:
                async with async_playwright() as p:
                    launch_kwargs: dict = {
                        "headless": True,
                    }
                    if current_proxy:
                        launch_kwargs["proxy"] = {"server": current_proxy}

                    browser = await p.chromium.launch(**launch_kwargs)
                    page = await browser.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                    await page.wait_for_timeout(1000)
                    await page.screenshot(path=str(output_path), full_page=True)
                    return output_path, None
            except Exception as exc:
                if _is_missing_playwright_browser_error(exc):
                    logger.info("网页截图检测到 Playwright 浏览器缺失: %s", exc)
                    return None, _WebpageScreenshotError(
                        code="missing_browser",
                        message="网页截图失败：检测到 Playwright 浏览器未安装。",
                    )

                if current_proxy:
                    logger.warning(
                        "网页截图代理 %s 失败，尝试直连: %s",
                        current_proxy,
                        exc,
                    )
                    continue

                logger.exception("网页截图失败: %s", url)
                return None, _WebpageScreenshotError(
                    code="render_failed",
                    message=f"网页截图失败：无法渲染 {url}",
                )
            finally:
                if browser:
                    await browser.close()

        return None, _WebpageScreenshotError(
            code="render_failed",
            message=f"网页截图失败：无法渲染 {url}",
        )

    screenshot_path, screenshot_error = await _capture_once()
    if screenshot_path:
        return screenshot_path, ""

    if not screenshot_error:
        return None, f"网页截图失败：无法渲染 {url}"

    if screenshot_error.code != "missing_browser":
        return None, screenshot_error.message

    if not auto_install_browser:
        return None, "网页截图失败：检测到 Playwright 浏览器未安装，请执行 playwright install。"

    installed, install_msg = await _ensure_playwright_browser_installed(
        timeout_seconds=install_timeout_seconds
    )
    if not installed:
        return (
            None,
            "网页截图失败：Playwright 浏览器自动安装失败。"
            f"{install_msg} 请手动执行 playwright install。",
        )

    logger.info("Playwright 浏览器安装成功，重试网页截图: %s", url)
    screenshot_path, screenshot_error = await _capture_once()
    if screenshot_path:
        return screenshot_path, ""
    if screenshot_error:
        return None, screenshot_error.message
    return None, f"网页截图失败：无法渲染 {url}"


def _is_missing_playwright_browser_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "executable doesn't exist" in text
        or "please run the following command to download new browsers" in text
        or "playwright install" in text
    )


async def _ensure_playwright_browser_installed(*, timeout_seconds: int) -> tuple[bool, str]:
    now = asyncio.get_running_loop().time()

    async with _PLAYWRIGHT_INSTALL_LOCK:
        status = str(_PLAYWRIGHT_INSTALL_STATE.get("status", "never"))
        last_attempt = float(_PLAYWRIGHT_INSTALL_STATE.get("last_attempt", 0.0))
        last_message = str(_PLAYWRIGHT_INSTALL_STATE.get("last_message", ""))

        if (
            status == "failed"
            and (now - last_attempt) < _PLAYWRIGHT_INSTALL_RETRY_COOLDOWN_SECONDS
        ):
            return False, f"（最近一次失败：{last_message}）"

        try:
            proc = await asyncio.create_subprocess_exec(
                "playwright",
                "install",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            msg = f"无法启动安装命令: {exc}"
            _PLAYWRIGHT_INSTALL_STATE.update(
                {"status": "failed", "last_attempt": now, "last_message": msg}
            )
            logger.warning("Playwright 浏览器自动安装失败: %s", msg)
            return False, f"（{msg}）"

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            msg = f"安装超时（>{timeout_seconds}s）"
            _PLAYWRIGHT_INSTALL_STATE.update(
                {"status": "failed", "last_attempt": now, "last_message": msg}
            )
            logger.warning("Playwright 浏览器自动安装超时。")
            return False, msg

        stdout_text = stdout.decode("utf-8", errors="ignore").strip()
        stderr_text = stderr.decode("utf-8", errors="ignore").strip()
        if proc.returncode == 0:
            _PLAYWRIGHT_INSTALL_STATE.update(
                {"status": "success", "last_attempt": now, "last_message": ""}
            )
            logger.info("Playwright 浏览器自动安装成功。")
            if stdout_text:
                logger.info("playwright install 输出: %s", stdout_text[-500:])
            return True, ""

        msg = stderr_text or stdout_text or f"退出码 {proc.returncode}"
        _PLAYWRIGHT_INSTALL_STATE.update(
            {"status": "failed", "last_attempt": now, "last_message": msg[:500]}
        )
        logger.warning("Playwright 浏览器自动安装失败: %s", msg[:500])
        return False, f"（{msg[:200]}）"


def extract_text(pdf_path: Path, max_pages: int = 10) -> str:
    """从 PDF 文件中提取文本内容。

    Args:
        pdf_path: PDF 文件路径。
        max_pages: 最大提取页数。

    Returns:
        提取的文本字符串，pymupdf 不可用或提取失败返回空字符串。
    """
    if not PYMUPDF_AVAILABLE:
        return ""

    try:
        doc = fitz.open(str(pdf_path))
        texts: list[str] = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            texts.append(page.get_text())
        doc.close()
        return "\n".join(texts)

    except Exception:
        logger.exception("从 PDF 提取文本失败: %s", pdf_path)
        return ""
