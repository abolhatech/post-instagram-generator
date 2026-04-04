from __future__ import annotations

import json
import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - runtime dependency guard
    BeautifulSoup = None

try:
    from psycopg import connect, sql
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - runtime dependency guard
    connect = None
    sql = None
    dict_row = None

from news_image_generator.models import ensure_dir


@dataclass
class DailyInputPrepareResult:
    output_path: str
    references_dir: str
    selected_count: int
    target_date: str


class DailyInputPreparer:
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    )

    def run(
        self,
        *,
        database_url: str,
        output_path: str,
        target_date: str | None = None,
        timezone_name: str = "America/Sao_Paulo",
        table_name: str = "posts",
        limit: int = 1,
    ) -> DailyInputPrepareResult:
        zone = ZoneInfo(timezone_name)
        selected_date = (
            datetime.strptime(target_date, "%Y-%m-%d").date()
            if target_date
            else datetime.now(zone).date()
        )
        output = Path(output_path)
        ensure_dir(output.parent)
        references_dir = ensure_dir(output.parent / "reference_images")

        normalized_database_url = self._normalize_database_url(database_url)

        rows = self._fetch_posts(
            database_url=normalized_database_url,
            table_name=table_name,
            selected_date=selected_date,
            timezone_name=timezone_name,
            limit=limit,
        )
        if not rows:
            raise RuntimeError(
                f"No rows found in '{table_name}' for {selected_date.isoformat()} ({timezone_name})."
            )

        session = requests.Session()
        session.headers.update({"User-Agent": self.USER_AGENT})

        articles: list[dict[str, Any]] = []
        for row in rows:
            source_url = self._source_url_from_row(row)
            segments = self._build_segments_from_row(row)
            if not row.get("title") or not segments:
                continue

            image_candidates = self._extract_image_candidates(session, source_url)
            downloaded_paths = self._download_candidates(
                session=session,
                image_urls=image_candidates,
                destination_dir=references_dir,
                item_id=str(row["id"]),
            )
            primary_ref = downloaded_paths[0] if downloaded_paths else ""
            secondary_ref = downloaded_paths[1] if len(downloaded_paths) > 1 else primary_ref

            for index, segment in enumerate(segments, start=1):
                articles.append(
                    {
                        "id": f'{row["id"]}-{index}',
                        "title": segment["title"],
                        "summary": segment["summary"][:600],
                        "sourceUrl": primary_ref,
                        "sourceUrl2": secondary_ref,
                        "imageUrl": source_url,
                        "journal": self._journal_label_from_row(row, source_url),
                        "publishedAt": self._serialize_datetime(row.get("published_at") or row.get("created_at")),
                    }
                )

        if not articles:
            raise RuntimeError("Rows were found, but none could be converted into valid news.json items.")

        output.write_text(json.dumps(articles, indent=2, ensure_ascii=False), encoding="utf-8")
        return DailyInputPrepareResult(
            output_path=str(output),
            references_dir=str(references_dir),
            selected_count=len(articles),
            target_date=selected_date.isoformat(),
        )

    def _fetch_posts(
        self,
        *,
        database_url: str,
        table_name: str,
        selected_date: date,
        timezone_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if connect is None or dict_row is None or sql is None:
            raise RuntimeError(
                "Missing dependency 'psycopg'. Run 'pip install -e .' again to install the new dependencies."
            )
        try:
            conn = connect(database_url, row_factory=dict_row)
        except Exception as exc:
            raise RuntimeError(
                "Could not connect to Postgres. Check --database-url/DATABASE_URL. "
                "If you copied the Neon connection string, make sure it is a single line, "
                "without surrounding quotes, and includes the database name."
            ) from exc

        with conn:
            columns = self._fetch_table_columns(conn, table_name)
            with conn.cursor() as cur:
                timestamp_expr = self._timestamp_expression(columns)
                order_by_expr = self._order_by_expression(columns)
                cur.execute(
                    sql.SQL(
                        """
                        SELECT *
                        FROM {table}
                        WHERE ({timestamp_expr} AT TIME ZONE %s)::date = %s
                        ORDER BY {order_by_expr}
                        LIMIT %s
                        """
                    ).format(
                        table=self._qualified_identifier(table_name),
                        timestamp_expr=timestamp_expr,
                        order_by_expr=order_by_expr,
                    ),
                    [timezone_name, selected_date, limit],
                )
                return list(cur.fetchall())

    def _fetch_table_columns(self, conn: Any, table_name: str) -> set[str]:
        parts = [part.strip() for part in table_name.split(".") if part.strip()]
        schema = "public"
        table = parts[0]
        if len(parts) >= 2:
            schema, table = parts[-2], parts[-1]

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                [schema, table],
            )
            return {str(row["column_name"]) for row in cur.fetchall()}

    @staticmethod
    def _timestamp_expression(columns: set[str]) -> sql.SQL:
        has_published = "published_at" in columns
        has_created = "created_at" in columns
        if has_published and has_created:
            return sql.SQL("COALESCE(published_at, created_at)")
        if has_published:
            return sql.SQL("published_at")
        if has_created:
            return sql.SQL("created_at")
        raise RuntimeError("The selected table must contain 'published_at' or 'created_at'.")

    @staticmethod
    def _order_by_expression(columns: set[str]) -> sql.SQL:
        parts: list[sql.SQL] = []
        if "rank_position" in columns:
            parts.append(sql.SQL("rank_position ASC NULLS LAST"))
        if "score" in columns:
            parts.append(sql.SQL("score DESC NULLS LAST"))
        if "published_at" in columns and "created_at" in columns:
            parts.append(sql.SQL("COALESCE(published_at, created_at) DESC"))
        elif "published_at" in columns:
            parts.append(sql.SQL("published_at DESC"))
        elif "created_at" in columns:
            parts.append(sql.SQL("created_at DESC"))
        return sql.SQL(", ").join(parts) if parts else sql.SQL("1")

    @staticmethod
    def _qualified_identifier(name: str) -> sql.Composed | sql.Identifier:
        parts = [part.strip() for part in name.split(".") if part.strip()]
        if not parts:
            raise ValueError("Table name must not be empty.")
        if len(parts) == 1:
            return sql.Identifier(parts[0])
        return sql.SQL(".").join(sql.Identifier(part) for part in parts)

    def _extract_image_candidates(self, session: requests.Session, article_url: str) -> list[str]:
        if BeautifulSoup is None:
            raise RuntimeError(
                "Missing dependency 'beautifulsoup4'. Run 'pip install -e .' again to install the new dependencies."
            )
        if not article_url:
            return []
        if self._looks_like_image_url(article_url):
            return [article_url]

        try:
            response = session.get(article_url, timeout=30)
            response.raise_for_status()
        except Exception:
            return []

        content_type = (response.headers.get("content-type") or "").lower()
        if content_type.startswith("image/"):
            return [article_url]

        soup = BeautifulSoup(response.text, "html.parser")
        candidates: dict[str, int] = {}

        def add_candidate(raw_url: str | None, score: int) -> None:
            normalized = self._normalize_image_url(base_url=article_url, candidate=raw_url)
            if not normalized:
                return
            previous = candidates.get(normalized, -10**9)
            if score > previous:
                candidates[normalized] = score

        for selector, score in [
            ('meta[property="og:image"]', 200),
            ('meta[property="og:image:url"]', 195),
            ('meta[property="og:image:secure_url"]', 190),
            ('meta[name="twitter:image"]', 180),
            ('meta[name="twitter:image:src"]', 175),
            ('meta[itemprop="image"]', 170),
            ('link[rel="image_src"]', 160),
        ]:
            for node in soup.select(selector):
                add_candidate(node.get("content") or node.get("href"), score)

        for node in soup.find_all("img"):
            raw_url = (
                node.get("src")
                or node.get("data-src")
                or node.get("data-lazy-src")
                or self._first_src_from_srcset(node.get("srcset") or node.get("data-srcset"))
            )
            score = 40
            class_value = node.get("class")
            if isinstance(class_value, list):
                class_value = " ".join(str(part) for part in class_value)
            descriptor = " ".join(
                str(value) for value in [node.get("alt"), class_value, node.get("id")] if value
            ).lower()
            if any(keyword in descriptor for keyword in ("hero", "featured", "article", "cover", "lead")):
                score += 25
            if any(keyword in descriptor for keyword in ("avatar", "logo", "icon", "author", "sprite")):
                score -= 40
            try:
                width = int(node.get("width") or 0)
                height = int(node.get("height") or 0)
                if width >= 600 or height >= 400:
                    score += 12
            except ValueError:
                pass
            add_candidate(raw_url, score)

        ordered = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
        return [url for url, _score in ordered[:6]]

    def _download_candidates(
        self,
        *,
        session: requests.Session,
        image_urls: list[str],
        destination_dir: Path,
        item_id: str,
    ) -> list[str]:
        downloaded: list[str] = []
        for index, image_url in enumerate(image_urls[:2], start=1):
            try:
                response = session.get(image_url, timeout=45)
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                extension = mimetypes.guess_extension(content_type) or Path(urlparse(image_url).path).suffix or ".jpg"
                if extension == ".jpe":
                    extension = ".jpg"
                destination = destination_dir / f"{item_id}_{index}{extension}"
                destination.write_bytes(response.content)
                downloaded.append(str(destination.resolve()))
            except Exception:
                continue
        return downloaded

    def _build_segments_from_row(self, row: dict[str, Any]) -> list[dict[str, str]]:
        title = self._clean_text(str(row.get("title") or ""))
        summary = self._clean_text(str(row.get("summary") or self._raw_item_value(row, "summary") or ""))
        content = str(row.get("content") or "")

        sections = self._split_content_sections(content)
        if len(sections) <= 1:
            fallback_summary = summary or self._clean_text(content)
            if not title or not fallback_summary:
                return []
            return [{"title": title, "summary": fallback_summary[:600]}]

        segments: list[dict[str, str]] = []
        for section in sections:
            cleaned_section = self._clean_text(section)
            if not cleaned_section:
                continue
            segment_title = self._segment_title(cleaned_section)
            segments.append(
                {
                    "title": segment_title,
                    "summary": cleaned_section[:600],
                }
            )
        return segments

    @staticmethod
    def _split_content_sections(content: str) -> list[str]:
        normalized = content.replace("\r\n", "\n")
        normalized = re.sub(r"\n[ \t]*—[^\n]+$", "", normalized.strip(), flags=re.MULTILINE)
        parts = re.split(r"\n\s*---\s*\n", normalized)
        cleaned_parts = [part.strip() for part in parts if part and part.strip()]
        return cleaned_parts

    @staticmethod
    def _raw_item_value(row: dict[str, Any], key: str) -> Any:
        raw_item = row.get("raw_item_json")
        if isinstance(raw_item, dict):
            return raw_item.get(key)
        return None

    @staticmethod
    def _segment_title(section: str, max_length: int = 110) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", section.strip())
        base = sentences[0].strip() if sentences else section.strip()
        base = re.sub(r"^[—\-•\s]+", "", base)
        if len(base) <= max_length:
            return base
        truncated = base[: max_length - 1].rsplit(" ", 1)[0].strip()
        return f"{truncated}…" if truncated else base[:max_length]

    @staticmethod
    def _normalize_image_url(*, base_url: str, candidate: str | None) -> str | None:
        if not candidate:
            return None
        value = candidate.strip()
        if not value or value.startswith("data:"):
            return None
        resolved = urljoin(base_url, value)
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"}:
            return None
        path = parsed.path.lower()
        if any(token in path for token in ("/logo", "/avatar", "/icon", "/favicon", "/sprite")):
            return None
        if path.endswith(".svg"):
            return None
        return resolved

    @staticmethod
    def _first_src_from_srcset(srcset: str | None) -> str | None:
        if not srcset:
            return None
        first = srcset.split(",")[0].strip()
        if not first:
            return None
        return first.split(" ")[0].strip() or None

    @staticmethod
    def _looks_like_image_url(url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))

    @staticmethod
    def _clean_text(value: str) -> str:
        value = re.sub(r"\n\s*---\s*\n", " ", value)
        value = value.replace("\r", " ").replace("\n", " ")
        return " ".join(value.split()).strip()

    @staticmethod
    def _journal_from_url(url: str) -> str:
        hostname = urlparse(url).netloc.lower()
        hostname = re.sub(r"^www\.", "", hostname)
        return hostname

    @staticmethod
    def _serialize_datetime(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _source_url_from_row(self, row: dict[str, Any]) -> str:
        return (
            self._clean_text(
                str(
                    row.get("source_url")
                    or row.get("url")
                    or self._raw_item_value(row, "url")
                    or ""
                )
            )
        )

    def _journal_label_from_row(self, row: dict[str, Any], source_url: str) -> str:
        source_label = self._clean_text(str(row.get("source_label") or self._raw_item_value(row, "sourceLabel") or ""))
        if source_label:
            return source_label
        source = self._clean_text(str(row.get("source") or self._raw_item_value(row, "source") or ""))
        if source:
            return source
        return self._journal_from_url(source_url)

    @staticmethod
    def _normalize_database_url(value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise RuntimeError("Empty database URL. Provide --database-url or set DATABASE_URL/NEON_DATABASE_URL.")

        if (
            (normalized.startswith('"') and normalized.endswith('"'))
            or (normalized.startswith("'") and normalized.endswith("'"))
        ):
            normalized = normalized[1:-1].strip()

        normalized = normalized.replace("\n", "").replace("\r", "")
        normalized = re.sub(r"\s+", " ", normalized).strip()

        if "postgresql://" in normalized and not normalized.startswith("postgresql://"):
            normalized = normalized[normalized.index("postgresql://") :]
        elif "postgres://" in normalized and not normalized.startswith("postgres://"):
            normalized = normalized[normalized.index("postgres://") :]

        return normalized


def prepare_daily_input_from_env(
    *,
    output_path: str,
    target_date: str | None,
    timezone_name: str,
    table_name: str,
    limit: int,
    database_url: str | None = None,
) -> DailyInputPrepareResult:
    resolved_database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("NEON_DATABASE_URL")
    if not resolved_database_url:
        raise RuntimeError("Provide --database-url or set DATABASE_URL/NEON_DATABASE_URL.")
    preparer = DailyInputPreparer()
    return preparer.run(
        database_url=resolved_database_url,
        output_path=output_path,
        target_date=target_date,
        timezone_name=timezone_name,
        table_name=table_name,
        limit=limit,
    )
