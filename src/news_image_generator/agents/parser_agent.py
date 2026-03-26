from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from news_image_generator.models import NewsArticle, ParseInput, ParseOutput


class ParserAgent:
    def run(self, payload: ParseInput) -> ParseOutput:
        input_path = Path(payload.input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        if input_path.suffix.lower() in {".json"}:
            articles = self._parse_json(input_path)
        elif input_path.suffix.lower() in {".md", ".markdown"}:
            articles = self._parse_markdown(input_path)
        else:
            raise ValueError("ParserAgent only supports .json, .md and .markdown files")

        warnings: list[str] = []
        if len(articles) > payload.max_articles:
            warnings.append(
                f"Received {len(articles)} items. Keeping first {payload.max_articles}."
            )
            articles = articles[: payload.max_articles]
        if len(articles) < 5:
            warnings.append(
                f"Expected 5-7 articles, but parsed {len(articles)}. Pipeline still executed."
            )

        return ParseOutput(articles=articles, warnings=warnings)

    def _parse_json(self, input_path: Path) -> list[NewsArticle]:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            items = raw.get("articles", [])
        elif isinstance(raw, list):
            items = raw
        else:
            raise ValueError("JSON input must be either a list or {'articles': [...]} object")

        articles: list[NewsArticle] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = self._first(item, ["title", "headline", "name"]) or ""
            summary = self._first(item, ["summary", "description", "body", "content"]) or ""
            if not title or not summary:
                continue
            articles.append(
                NewsArticle(
                    id=str(item.get("id") or uuid.uuid4()),
                    title=title.strip(),
                    summary=self._clean(summary),
                    imageUrl=(self._first(item, ["imageUrl", "image_url", "image", "thumbnail"]) or "").strip(),
                    sourceUrl=(self._first(item, ["sourceUrl", "source_url", "url", "link"]) or "").strip(),
                    sourceUrl2=(self._first(item, ["sourceUrl2", "source_url2", "url2", "link2"]) or "").strip(),
                )
            )
        return articles

    def _parse_markdown(self, input_path: Path) -> list[NewsArticle]:
        content = input_path.read_text(encoding="utf-8")
        heading_pattern = re.compile(r"(?m)^#{1,3}\s+(.+)$")
        matches = list(heading_pattern.finditer(content))

        if not matches:
            clean = self._clean(content)
            if not clean:
                return []
            return [
                NewsArticle(
                    id=str(uuid.uuid4()),
                    title="Untitled article",
                    summary=clean[:500],
                )
            ]

        results: list[NewsArticle] = []
        for index, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            block = content[start:end].strip()
            image_url = self._extract_image(block)
            source_url = self._extract_source(block)
            source_url2 = self._extract_source2(block)
            summary = self._extract_summary(block)
            if not summary:
                continue
            results.append(
                NewsArticle(
                    id=str(uuid.uuid4()),
                    title=title,
                    summary=summary,
                    imageUrl=image_url,
                    sourceUrl=source_url,
                    sourceUrl2=source_url2,
                )
            )
        return results

    @staticmethod
    def _extract_image(block: str) -> str:
        image_match = re.search(r"!\[[^\]]*]\(([^)]+)\)", block)
        return image_match.group(1).strip() if image_match else ""

    @staticmethod
    def _extract_source(block: str) -> str:
        source_match = re.search(r"(?im)\[source]\(([^)]+)\)", block)
        if source_match:
            return source_match.group(1).strip()
        source_match = re.search(r"(?im)^source:\s*(https?://\S+)\s*$", block)
        return source_match.group(1).strip() if source_match else ""

    @staticmethod
    def _extract_source2(block: str) -> str:
        source_match = re.search(r"(?im)\[source2]\(([^)]+)\)", block)
        if source_match:
            return source_match.group(1).strip()
        source_match = re.search(r"(?im)^source2:\s*(https?://\S+)\s*$", block)
        return source_match.group(1).strip() if source_match else ""

    def _extract_summary(self, block: str) -> str:
        text = re.sub(r"!\[[^\]]*]\(([^)]+)\)", "", block)
        text = re.sub(r"(?im)\[source]\(([^)]+)\)", "", text)
        text = re.sub(r"(?im)\[source2]\(([^)]+)\)", "", text)
        text = re.sub(r"(?im)^source:\s*(https?://\S+)\s*$", "", text)
        text = re.sub(r"(?im)^source2:\s*(https?://\S+)\s*$", "", text)
        text = self._clean(text)
        return text[:600]

    @staticmethod
    def _first(item: dict[str, Any], keys: list[str]) -> Any:
        for key in keys:
            if key in item and item[key]:
                return item[key]
        return None

    @staticmethod
    def _clean(value: str) -> str:
        return " ".join(value.replace("\n", " ").split()).strip()
