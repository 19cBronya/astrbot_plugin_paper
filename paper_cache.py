"""论文处理缓存。

持久化缓存论文处理结果，避免重复下载 PDF、重复 LLM 翻译/总结。
缓存按论文维度存储，并支持部分命中（例如仅已有翻译或仅已有 PDF）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any


class PaperCache:
    """论文处理缓存管理器。"""

    _VERSION = 1

    def __init__(self, data_dir: Path, retention_days: int = 30) -> None:
        self._root = data_dir / "paper_cache"
        self._files_dir = self._root / "files"
        self._index_file = self._root / "index.json"
        self._retention_days = max(1, int(retention_days))
        self._data: dict[str, Any] = {"version": self._VERSION, "papers": {}}
        self._load()

    def _load(self) -> None:
        if not self._index_file.exists():
            return
        try:
            with open(self._index_file, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("papers"), dict):
                self._data = loaded
        except (OSError, json.JSONDecodeError):
            self._data = {"version": self._VERSION, "papers": {}}

    def _save(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp_path = self._index_file.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        tmp_path.replace(self._index_file)

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def _safe_name(text: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in text)
        return cleaned[:120] or "paper"

    def _get_or_create_record(self, paper_key: str) -> dict[str, Any]:
        papers = self._data.setdefault("papers", {})
        now = time.time()
        record = papers.get(paper_key)
        if not isinstance(record, dict):
            record = {
                "updated_at": now,
                "last_accessed_at": now,
                "pdf": {},
                "screenshots": {},
                "abstract_translations": {},
                "summaries": {},
                "abstract_images": {},
                "paper": {},
            }
            papers[paper_key] = record
        record["last_accessed_at"] = now
        return record

    def touch_paper_info(self, paper_key: str, info: dict[str, Any]) -> None:
        record = self._get_or_create_record(paper_key)
        record["paper"] = info
        record["updated_at"] = time.time()
        self._save()

    def get_linked_arxiv_id(self, paper_key: str) -> str | None:
        record = self._get_or_create_record(paper_key)
        linked = str(record.get("linked_arxiv_id", "")).strip()
        return linked or None

    def store_linked_arxiv_id(self, paper_key: str, arxiv_id: str) -> None:
        arxiv_id = (arxiv_id or "").strip()
        if not arxiv_id:
            return
        record = self._get_or_create_record(paper_key)
        record["linked_arxiv_id"] = arxiv_id
        record["updated_at"] = time.time()
        self._save()

    def get_arxiv_payload(self, paper_key: str) -> dict[str, Any] | None:
        record = self._get_or_create_record(paper_key)
        payload = record.get("arxiv_payload")
        if isinstance(payload, dict) and payload.get("arxiv_id"):
            return payload
        return None

    def store_arxiv_payload(self, paper_key: str, payload: dict[str, Any]) -> None:
        if not payload or not str(payload.get("arxiv_id", "")).strip():
            return
        record = self._get_or_create_record(paper_key)
        record["arxiv_payload"] = payload
        record["updated_at"] = time.time()
        self._save()

    def get_cached_pdf(self, paper_key: str, *, pdf_url: str) -> Path | None:
        record = self._get_or_create_record(paper_key)
        pdf_meta = record.get("pdf", {})
        if not isinstance(pdf_meta, dict):
            return None

        if pdf_url and pdf_meta.get("url") and pdf_meta.get("url") != pdf_url:
            return None

        rel = str(pdf_meta.get("path", "")).strip()
        if not rel:
            return None

        path = self._root / rel
        if path.exists() and path.is_file():
            return path

        record["pdf"] = {}
        self._save()
        return None

    def store_pdf(self, paper_key: str, *, pdf_url: str, source_path: Path) -> Path | None:
        if not source_path.exists() or not source_path.is_file():
            return None

        self._files_dir.mkdir(parents=True, exist_ok=True)
        suffix = source_path.suffix if source_path.suffix else ".pdf"
        name = f"{self._safe_name(paper_key)}_pdf_{self._hash_text(pdf_url)[:10]}{suffix}"
        dest = self._files_dir / name
        shutil.copy2(source_path, dest)

        record = self._get_or_create_record(paper_key)
        record["pdf"] = {
            "url": pdf_url,
            "path": str(dest.relative_to(self._root)),
            "updated_at": time.time(),
        }
        record["updated_at"] = time.time()
        self._save()
        return dest

    def get_cached_screenshot(
        self,
        paper_key: str,
        *,
        dpi: int,
        source_fingerprint: str,
    ) -> Path | None:
        record = self._get_or_create_record(paper_key)
        screenshots = record.get("screenshots", {})
        if not isinstance(screenshots, dict):
            return None

        entry = screenshots.get(str(int(dpi)))
        if isinstance(entry, str):
            rel = entry.strip()
            source_hash = ""
        elif isinstance(entry, dict):
            rel = str(entry.get("path", "")).strip()
            source_hash = str(entry.get("source_hash", "")).strip()
        else:
            rel = ""
            source_hash = ""

        if not rel:
            return None

        expected_hash = self._hash_text(source_fingerprint)
        if source_hash and source_hash != expected_hash:
            return None

        path = self._root / rel
        if path.exists() and path.is_file():
            return path

        screenshots.pop(str(int(dpi)), None)
        self._save()
        return None

    def store_screenshot(
        self,
        paper_key: str,
        *,
        dpi: int,
        source_path: Path,
        source_fingerprint: str,
    ) -> Path | None:
        if not source_path.exists() or not source_path.is_file():
            return None

        self._files_dir.mkdir(parents=True, exist_ok=True)
        suffix = source_path.suffix if source_path.suffix else ".png"
        name = f"{self._safe_name(paper_key)}_shot_{int(dpi)}{suffix}"
        dest = self._files_dir / name
        shutil.copy2(source_path, dest)

        record = self._get_or_create_record(paper_key)
        screenshots = record.setdefault("screenshots", {})
        if not isinstance(screenshots, dict):
            screenshots = {}
            record["screenshots"] = screenshots
        screenshots[str(int(dpi))] = {
            "path": str(dest.relative_to(self._root)),
            "source_hash": self._hash_text(source_fingerprint),
            "updated_at": time.time(),
        }
        record["updated_at"] = time.time()
        self._save()
        return dest

    def get_cached_abstract_image(self, paper_key: str, *, abstract_text: str) -> Path | None:
        if not abstract_text:
            return None
        record = self._get_or_create_record(paper_key)
        images = record.get("abstract_images", {})
        if not isinstance(images, dict):
            return None

        key = self._hash_text(abstract_text)
        meta = images.get(key)
        if not isinstance(meta, dict):
            return None

        rel = str(meta.get("path", "")).strip()
        if not rel:
            return None

        path = self._root / rel
        if path.exists() and path.is_file():
            return path

        images.pop(key, None)
        self._save()
        return None

    def store_abstract_image(
        self,
        paper_key: str,
        *,
        abstract_text: str,
        source_path: Path,
    ) -> Path | None:
        if not abstract_text or not source_path.exists() or not source_path.is_file():
            return None

        self._files_dir.mkdir(parents=True, exist_ok=True)
        suffix = source_path.suffix if source_path.suffix else ".png"
        text_hash = self._hash_text(abstract_text)
        name = f"{self._safe_name(paper_key)}_abs_{text_hash[:10]}{suffix}"
        dest = self._files_dir / name
        shutil.copy2(source_path, dest)

        record = self._get_or_create_record(paper_key)
        images = record.setdefault("abstract_images", {})
        if not isinstance(images, dict):
            images = {}
            record["abstract_images"] = images
        images[text_hash] = {
            "path": str(dest.relative_to(self._root)),
            "updated_at": time.time(),
        }
        record["updated_at"] = time.time()
        self._save()
        return dest

    def get_cached_translation(
        self,
        paper_key: str,
        *,
        abstract: str,
        provider_id: str,
    ) -> str | None:
        if not abstract:
            return None
        record = self._get_or_create_record(paper_key)
        translations = record.get("abstract_translations", {})
        if not isinstance(translations, dict):
            return None

        key = f"{provider_id or 'default'}|{self._hash_text(abstract)}"
        meta = translations.get(key)
        if not isinstance(meta, dict):
            return None

        text = str(meta.get("text", "")).strip()
        return text or None

    def store_translation(
        self,
        paper_key: str,
        *,
        abstract: str,
        provider_id: str,
        translated: str,
    ) -> None:
        if not abstract or not translated:
            return

        record = self._get_or_create_record(paper_key)
        translations = record.setdefault("abstract_translations", {})
        if not isinstance(translations, dict):
            translations = {}
            record["abstract_translations"] = translations

        key = f"{provider_id or 'default'}|{self._hash_text(abstract)}"
        translations[key] = {"text": translated, "updated_at": time.time()}
        record["updated_at"] = time.time()
        self._save()

    def get_cached_summary(
        self,
        paper_key: str,
        *,
        source_fingerprint: str,
        provider_id: str,
        prompt: str,
    ) -> str | None:
        if not source_fingerprint:
            return None

        record = self._get_or_create_record(paper_key)
        summaries = record.get("summaries", {})
        if not isinstance(summaries, dict):
            return None

        key = self._make_summary_key(
            source_fingerprint=source_fingerprint,
            provider_id=provider_id,
            prompt=prompt,
        )
        meta = summaries.get(key)
        if not isinstance(meta, dict):
            return None

        text = str(meta.get("text", "")).strip()
        return text or None

    def store_summary(
        self,
        paper_key: str,
        *,
        source_fingerprint: str,
        provider_id: str,
        prompt: str,
        summary: str,
    ) -> None:
        if not source_fingerprint or not summary:
            return

        record = self._get_or_create_record(paper_key)
        summaries = record.setdefault("summaries", {})
        if not isinstance(summaries, dict):
            summaries = {}
            record["summaries"] = summaries

        key = self._make_summary_key(
            source_fingerprint=source_fingerprint,
            provider_id=provider_id,
            prompt=prompt,
        )
        summaries[key] = {
            "text": summary,
            "updated_at": time.time(),
        }
        record["updated_at"] = time.time()
        self._save()

    def _make_summary_key(
        self,
        *,
        source_fingerprint: str,
        provider_id: str,
        prompt: str,
    ) -> str:
        return "|".join(
            [
                self._hash_text(source_fingerprint),
                provider_id or "default",
                self._hash_text(prompt),
            ]
        )

    def cleanup_old(self) -> int:
        papers = self._data.get("papers", {})
        if not isinstance(papers, dict):
            return 0

        cutoff = time.time() - self._retention_days * 86400
        removed = 0

        for paper_key in list(papers.keys()):
            record = papers.get(paper_key)
            if not isinstance(record, dict):
                papers.pop(paper_key, None)
                removed += 1
                continue

            last_accessed = float(record.get("last_accessed_at", 0.0) or 0.0)
            updated_at = float(record.get("updated_at", 0.0) or 0.0)
            ts = last_accessed or updated_at
            if ts and ts < cutoff:
                self._delete_record_files(record)
                papers.pop(paper_key, None)
                removed += 1

        if removed:
            self._save()
        return removed

    def _delete_record_files(self, record: dict[str, Any]) -> None:
        candidates: list[str] = []

        pdf_meta = record.get("pdf", {})
        if isinstance(pdf_meta, dict):
            rel = str(pdf_meta.get("path", "")).strip()
            if rel:
                candidates.append(rel)

        for entry in (record.get("screenshots", {}) or {}).values():
            if isinstance(entry, str) and entry.strip():
                candidates.append(entry.strip())
                continue
            if isinstance(entry, dict):
                rel = str(entry.get("path", "")).strip()
                if rel:
                    candidates.append(rel)

        for meta in (record.get("abstract_images", {}) or {}).values():
            if isinstance(meta, dict):
                rel = str(meta.get("path", "")).strip()
                if rel:
                    candidates.append(rel)

        for rel in candidates:
            path = self._root / rel
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
