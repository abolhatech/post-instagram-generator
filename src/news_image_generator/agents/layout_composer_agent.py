from __future__ import annotations

import base64
import html
import io
import textwrap
from urllib.parse import urlparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from news_image_generator.models import (
    ComposedImageItem,
    CopyItem,
    GeneratedImageItem,
    LayoutComposerInput,
    LayoutComposerOutput,
    NewsArticle,
    ensure_dir,
)


class LayoutComposerAgent:
    DEFAULT_CANVAS_BY_FORMAT = {
        "story": (1080, 1920),
        "feed": (1080, 1350),
    }
    CREATOR_HANDLE = "@abolhatech.ia"
    BRAND_NAME = "A Bolha Tech - IA"
    CREATOR_AVATAR_PATH = "/Users/adriano/Pictures/channels4_profile.jpg"

    def run(self, payload: LayoutComposerInput) -> LayoutComposerOutput:
        out_dir = ensure_dir(Path(payload.output_dir) / "composed")
        plans_dir = ensure_dir(out_dir / "plans")
        article_by_id: dict[str, NewsArticle] = {item.id: item for item in payload.articles}
        copy_by_id: dict[str, CopyItem] = {item.id: item for item in payload.copies}
        results: list[ComposedImageItem] = []
        canvas_width, canvas_height = self.DEFAULT_CANVAS_BY_FORMAT.get(
            payload.publish_format,
            self.DEFAULT_CANVAS_BY_FORMAT["story"],
        )

        for generated in payload.images:
            article = article_by_id.get(generated.id)
            copy = copy_by_id.get(generated.id)
            if not article or not copy:
                continue
            headline_text = (article.title or "").strip() or copy.viralHeadline
            destination = out_dir / f"{generated.id}_thumb.png"
            plan_path = plans_dir / f"{generated.id}_plan.json"
            plan_path.write_text(
                self._composition_plan_json(
                    headline=headline_text,
                    canvas_width=canvas_width,
                    canvas_height=canvas_height,
                    publish_format=payload.publish_format,
                ),
                encoding="utf-8",
            )

            composed_ok = self._compose_with_playwright(
                image_path=generated.imagePath,
                headline=headline_text,
                source_url=article.sourceUrl,
                destination=destination,
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                publish_format=payload.publish_format,
            )

            # Keeps pipeline resilient while we iterate on the Playwright renderer setup.
            if not composed_ok:
                self._compose_fallback(
                    image_path=generated.imagePath,
                    headline=headline_text,
                    destination=destination,
                    font_path=payload.font_path,
                    canvas_width=canvas_width,
                    canvas_height=canvas_height,
                    publish_format=payload.publish_format,
                )
            results.append(
                ComposedImageItem(
                    id=generated.id,
                    headline=headline_text,
                    sourceUrl=article.sourceUrl,
                    baseImagePath=generated.imagePath,
                    composedImagePath=str(destination),
                )
            )

        return LayoutComposerOutput(composed=results)

    def _compose_with_playwright(
        self,
        *,
        image_path: str,
        headline: str,
        source_url: str,
        destination: Path,
        canvas_width: int,
        canvas_height: int,
        publish_format: str,
    ) -> bool:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:  # noqa: BLE001
            return False

        try:
            image_data_url = self._image_to_data_url(image_path, canvas_width, canvas_height)
            headline_clean = html.escape(headline.strip())
            source_label = html.escape(self._source_badge_label(source_url))
            avatar_data_url = self._avatar_data_url(size=48)
            markup = self._build_html(
                image_data_url=image_data_url,
                headline=headline_clean,
                source_label=source_label,
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                creator_handle=self.CREATOR_HANDLE,
                brand_name=self.BRAND_NAME,
                avatar_data_url=avatar_data_url,
                publish_format=publish_format,
            )
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": canvas_width, "height": canvas_height})
                page.set_content(markup)
                page.locator(".canvas").screenshot(path=str(destination))
                browser.close()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _compose_fallback(
        self,
        *,
        image_path: str,
        headline: str,
        destination: Path,
        font_path: str | None,
        canvas_width: int,
        canvas_height: int,
        publish_format: str,
    ) -> None:
        image = Image.open(image_path).convert("RGBA")
        image = image.resize((canvas_width, canvas_height))
        width, height = image.size

        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        start_y = int(height * 0.45)
        for y in range(start_y, height):
            alpha = int(20 + 205 * ((y - start_y) / max(height - start_y, 1)))
            draw_overlay.line((0, y, width, y), fill=(0, 0, 0, alpha))

        composed = Image.alpha_composite(image, overlay)
        draw = ImageDraw.Draw(composed)
        headline_font = self._load_font(font_path, int(width * 0.07))
        badge_font = self._load_font(font_path, int(width * 0.03))
        brand_font = self._load_font(font_path, int(width * 0.034))

        draw.rectangle((24, 24, 250, 96), fill=(230, 76, 22, 220))
        draw.text((38, 42), "@a2dev", fill=(255, 255, 255), font=badge_font)
        avatar = self._load_avatar_image(size=44)
        if avatar is not None:
            composed.alpha_composite(avatar, (40, int(height * 0.622)))
        else:
            draw.ellipse((40, int(height * 0.622), 84, int(height * 0.622) + 44), fill=(230, 120, 22, 230))
        draw.text((96, int(height * 0.56)), "A Bolha Tech - IA", fill=(255, 255, 255), font=brand_font)

        wrapped = self._wrap_text(draw, headline, headline_font, width - 80)
        draw.multiline_text(
            (40, int(height * 0.585)),
            wrapped,
            fill=(255, 255, 255),
            font=headline_font,
            spacing=6,
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )
        composed.convert("RGB").save(destination, format="PNG")

    @staticmethod
    def _image_to_data_url(image_path: str, width: int, height: int) -> str:
        image = Image.open(image_path).convert("RGB")
        image = image.resize((width, height))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90, optimize=True)
        b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    @staticmethod
    def _build_html(
        *,
        image_data_url: str,
        headline: str,
        source_label: str,
        canvas_width: int,
        canvas_height: int,
        creator_handle: str,
        brand_name: str,
        avatar_data_url: str | None,
        publish_format: str,
    ) -> str:
        headline_size = LayoutComposerAgent._headline_font_size(headline, publish_format=publish_format)
        is_feed = publish_format == "feed"
        branding_bottom = 225 if is_feed else 405
        source_bottom = 198 if is_feed else 362
        headline_bottom = 96 if is_feed else 120
        headline_max_height = 620 if is_feed else 880
        brand_font_size = 44 if is_feed else 48
        avatar_node = (
            f'<img class="brand-avatar" src="{avatar_data_url}" alt="avatar" />'
            if avatar_data_url
            else '<div class="brand-dot"></div>'
        )
        return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      width: {canvas_width}px;
      height: {canvas_height}px;
      overflow: hidden;
      background: #0b0d12;
    }}
    .canvas {{
      width: {canvas_width}px;
      height: {canvas_height}px;
      position: relative;
      overflow: hidden;
      border: 2px solid #000;
      background-image: url("{image_data_url}");
      background-size: cover;
      background-position: center;
    }}
    .noise {{
      position: absolute;
      inset: 0;
      background-image: radial-gradient(rgba(255,255,255,0.06) 1px, transparent 1px);
      background-size: 3px 3px;
      mix-blend-mode: soft-light;
      opacity: 0.15;
    }}
    .topbar {{
      position: absolute;
      top: 44px;
      left: 50px;
      right: 50px;
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      align-items: center;
      font-size: 20px;
      font-weight: 600;
      color: rgba(255,255,255,0.92);
      text-shadow: 0 2px 10px rgba(0,0,0,0.45);
      z-index: 3;
      gap: 16px;
    }}
    .topbar span {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }}
    .top-left {{
      text-align: left;
    }}
    .top-center {{
      text-align: center;
    }}
    .top-right {{
      text-align: right;
    }}
    .bottom-gradient {{
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 56%;
      background: linear-gradient(
        to bottom,
        rgba(6, 8, 12, 0.05) 0%,
        rgba(6, 8, 12, 0.74) 58%,
        rgba(2, 4, 8, 0.98) 100%
      );
      z-index: 2;
    }}
    .branding {{
      position: absolute;
      left: 72px;
      bottom: {branding_bottom}px;
      z-index: 4;
      display: flex;
      align-items: center;
      gap: 14px;
      color: rgba(255,255,255,0.95);
    }}
    .brand-dot {{
      width: 44px;
      height: 44px;
      border-radius: 999px;
      background: linear-gradient(140deg, #f97316, #ea580c);
      box-shadow: 0 8px 24px rgba(234, 88, 12, 0.5);
    }}
    .brand-avatar {{
      width: 44px;
      height: 44px;
      border-radius: 999px;
      object-fit: cover;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
      border: 2px solid rgba(255, 255, 255, 0.75);
    }}
    .brand-text {{
      font-size: {brand_font_size}px;
      font-weight: 700;
      letter-spacing: -0.8px;
    }}
    .source {{
      position: absolute;
      left: 72px;
      bottom: {source_bottom}px;
      z-index: 4;
      font-size: 34px;
      color: rgba(255,255,255,0.8);
      max-width: calc(100% - 140px);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .headline {{
      position: absolute;
      left: 72px;
      right: 72px;
      bottom: {headline_bottom}px;
      z-index: 4;
      color: #ffffff;
      font-size: {headline_size}px;
      line-height: 1.04;
      font-weight: 800;
      letter-spacing: -1.9px;
      display: -webkit-box;
      -webkit-line-clamp: 5;
      -webkit-box-orient: vertical;
      overflow: hidden;
      text-shadow: 0 6px 30px rgba(0,0,0,0.65);
      max-height: {headline_max_height}px;
    }}
  </style>
</head>
<body>
  <div class="canvas">
    <div class="noise"></div>
    <div class="topbar">
      <span class="top-left">{creator_handle}</span>
      <span class="top-center"></span>
      <span class="top-right">Copyright © 2026</span>
    </div>
    <div class="bottom-gradient"></div>
    <div class="branding">
      {avatar_node}
      <div class="brand-text">{brand_name}</div>
    </div>
    
    <div class="headline">{headline}</div>
  </div>
</body>
</html>
"""

    @staticmethod
    def _composition_plan_json(*, headline: str, canvas_width: int, canvas_height: int, publish_format: str) -> str:
        return (
            "{\n"
            f'  "canvas": "{canvas_width}x{canvas_height}",\n'
            f'  "publishFormat": "{publish_format}",\n'
            '  "elements": [\n'
            '    {\n'
            '      "type": "image",\n'
            '      "position": "background"\n'
            "    },\n"
            '    {\n'
            '      "type": "overlay",\n'
            '      "style": "dark gradient bottom"\n'
            "    },\n"
            '    {\n'
            '      "type": "text",\n'
            f'      "content": "{headline.replace(chr(34), "")}",\n'
            '      "position": "bottom",\n'
            '      "fontSize": "large",\n'
            '      "weight": "bold"\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )

    @staticmethod
    def _source_badge_label(source_url: str) -> str:
        value = (source_url or "").strip()
        if not value:
            return "local.source"
        try:
            host = urlparse(value).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            return host if host else "local.source"
        except Exception:  # noqa: BLE001
            compact = value[:30]
            return compact if compact else "local.source"

    @classmethod
    def _avatar_data_url(cls, size: int) -> str | None:
        avatar = cls._load_avatar_image(size=size)
        if avatar is None:
            return None
        buffer = io.BytesIO()
        avatar.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    @classmethod
    def _load_avatar_image(cls, size: int) -> Image.Image | None:
        avatar_path = Path(cls.CREATOR_AVATAR_PATH)
        if not avatar_path.exists():
            return None
        avatar = Image.open(avatar_path).convert("RGB")
        avatar = ImageOps.fit(avatar, (size, size), method=Image.Resampling.LANCZOS)
        alpha = Image.new("L", (size, size), 0)
        ImageDraw.Draw(alpha).ellipse((0, 0, size - 1, size - 1), fill=255)
        avatar_rgba = avatar.convert("RGBA")
        avatar_rgba.putalpha(alpha)
        return avatar_rgba

    @staticmethod
    def _headline_font_size(headline: str, *, publish_format: str) -> int:
        length = len(headline)
        if publish_format == "feed":
            if length <= 34:
                return 72
            if length <= 52:
                return 64
            if length <= 72:
                return 58
            return 52
        if length <= 34:
            return 84
        if length <= 52:
            return 76
        if length <= 72:
            return 68
        return 62

    @staticmethod
    def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
        words = text.split()
        lines: list[str] = []
        current: list[str] = []
        for word in words:
            trial = " ".join(current + [word])
            left, _, right, _ = draw.textbbox((0, 0), trial, font=font)
            if right - left <= max_width:
                current.append(word)
                continue
            if current:
                lines.append(" ".join(current))
            current = [word]
        if current:
            lines.append(" ".join(current))
        return "\n".join(textwrap.wrap(" ".join(lines), width=26)[:4])

    @staticmethod
    def _load_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [font_path, "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
        return ImageFont.load_default()
