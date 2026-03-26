from __future__ import annotations

import base64
import io
import json
import os
import random
from hashlib import sha256
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from news_image_generator.models import (
    GeneratedImageItem,
    ImageGeneratorOutput,
    NanobanaInput,
    NewsArticle,
    ensure_dir,
)


class NanobanaAgent:
    def run(self, payload: NanobanaInput) -> ImageGeneratorOutput:
        out_dir = ensure_dir(Path(payload.output_dir) / "generated")
        logs_dir = ensure_dir(Path(payload.output_dir) / "logs" / "nanobana")
        article_by_id = {article.id: article for article in payload.articles}

        fallback_reference: Image.Image | None = None
        if payload.reference_image_path:
            reference_path = Path(payload.reference_image_path)
            if not reference_path.exists():
                raise FileNotFoundError(f"Reference image not found: {reference_path}")
            fallback_reference = Image.open(reference_path).convert("RGB")

        results: list[GeneratedImageItem] = []
        for item in payload.prompts:
            article = article_by_id.get(item.id)
            destination = out_dir / f"{item.id}.png"
            seed = payload.seed if payload.seed >= 0 else self._deterministic_seed(item.id)
            error = ""
            used_fallback = False
            provider_name = "google-nano-banana" if payload.provider == "google" else "nanobana"

            composed_reference: Image.Image | None = None
            front_ref_b64: str | None = None
            back_ref_b64: str | None = None
            source_compose_error = ""

            if article and article.sourceUrl and article.sourceUrl2:
                try:
                    front_image = self._download_image(article.sourceUrl)
                    back_image = self._download_image(article.sourceUrl2)
                    composed_reference = self._compose_source_pair(
                        front_image=front_image,
                        back_image=back_image,
                        width=payload.width,
                        height=payload.height,
                    )
                    front_ref_b64 = self._encode_image(front_image, payload.width, payload.height)
                    back_ref_b64 = self._encode_image(back_image, payload.width, payload.height)
                except Exception:  # noqa: BLE001
                    composed_reference = None
                    front_ref_b64 = None
                    back_ref_b64 = None
                    source_compose_error = "Failed to download/compose sourceUrl and sourceUrl2."

            if composed_reference is None:
                composed_reference = (
                    fallback_reference
                    if fallback_reference is not None
                    else self._neutral_reference(width=payload.width, height=payload.height)
                )

            prepared_reference = self._prepare_reference(
                image=composed_reference,
                width=payload.width,
                height=payload.height,
            )
            prepared_reference.save(logs_dir / f"{item.id}_reference_prepared.png", format="PNG")
            ref_base64 = self._encode_image(prepared_reference, payload.width, payload.height)

            try:
                if payload.provider == "google":
                    api_key = (
                        payload.google_api_key
                        or os.getenv("GOOGLE_API_KEY")
                        or os.getenv("GEMINI_API_KEY")
                    )
                    if not api_key:
                        raise RuntimeError(
                            "Google image step enabled, but GOOGLE_API_KEY was not provided."
                        )
                    image = self._generate_with_google(
                        api_key=api_key,
                        model=payload.google_model,
                        prompt=item.prompt,
                        reference_b64=ref_base64,
                        foreground_b64=front_ref_b64,
                        background_b64=back_ref_b64,
                        article=article,
                    )
                else:
                    image = self._generate_with_nanobana(
                        endpoint=payload.endpoint,
                        prompt=item.prompt,
                        negative_prompt=item.negativePrompt,
                        reference_b64=ref_base64,
                        width=payload.width,
                        height=payload.height,
                        style_strength=payload.style_strength,
                        identity_lock=payload.identity_lock,
                        seed=seed,
                    )
            except Exception as exc:  # noqa: BLE001
                error = (
                    f"{source_compose_error} {exc}".strip()
                    if source_compose_error
                    else str(exc)
                )
                used_fallback = True
                image = self._fallback_from_reference(
                    reference_image=prepared_reference,
                    width=payload.width,
                    height=payload.height,
                    seed=seed,
                )

            image.save(destination, format="PNG")
            self._write_log(
                destination=logs_dir / f"{item.id}.json",
                item_id=item.id,
                image_path=str(destination),
                prompt=item.prompt,
                negative_prompt=item.negativePrompt,
                seed=seed,
                used_fallback=used_fallback,
                error=error,
                payload=payload,
                article=article,
            )
            results.append(
                GeneratedImageItem(
                    id=item.id,
                    prompt=item.prompt,
                    imagePath=str(destination),
                    provider=provider_name,
                    usedFallback=used_fallback,
                    error=error,
                )
            )
        return ImageGeneratorOutput(images=results)

    @staticmethod
    def _neutral_reference(*, width: int, height: int) -> Image.Image:
        canvas = Image.new("RGB", (width, height), color=(18, 23, 36))
        draw = ImageDraw.Draw(canvas)
        for y in range(height):
            ratio = y / max(1, height - 1)
            color = (
                int(18 + ratio * 40),
                int(23 + ratio * 32),
                int(36 + ratio * 70),
            )
            draw.line((0, y, width, y), fill=color)
        return canvas

    @staticmethod
    def _download_image(url: str, timeout: int = 45) -> Image.Image:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGB")

    @staticmethod
    def _compose_source_pair(
        *,
        front_image: Image.Image,
        back_image: Image.Image,
        width: int,
        height: int,
    ) -> Image.Image:
        background = ImageOps.fit(back_image, (width, height), method=Image.Resampling.LANCZOS)
        background = background.filter(ImageFilter.GaussianBlur(radius=2))
        background = ImageEnhance.Color(background).enhance(1.08)
        background = ImageEnhance.Contrast(background).enhance(1.10)

        shade = Image.new("RGBA", (width, height), (6, 10, 18, 70))
        canvas = Image.alpha_composite(background.convert("RGBA"), shade)

        front = front_image.copy().convert("RGBA")
        front.thumbnail((int(width * 0.9), int(height * 0.76)), Image.Resampling.LANCZOS)
        x = (width - front.width) // 2
        y = int(height * 0.46 - front.height * 0.5)

        mask = Image.new("L", front.size, color=245).filter(ImageFilter.GaussianBlur(radius=8))

        shadow = Image.new("RGBA", (front.width + 28, front.height + 28), (0, 0, 0, 0))
        shadow_alpha = Image.new("L", (front.width, front.height), 160).filter(ImageFilter.GaussianBlur(radius=14))
        shadow.paste((0, 0, 0, 155), (14, 14), shadow_alpha)
        canvas.alpha_composite(shadow, (x - 14, y - 14))
        canvas.paste(front, (x, y), mask)

        return canvas.convert("RGB")

    @staticmethod
    def _generate_with_nanobana(
        *,
        endpoint: str,
        prompt: str,
        negative_prompt: str,
        reference_b64: str,
        width: int,
        height: int,
        style_strength: float,
        identity_lock: float,
        seed: int,
    ) -> Image.Image:
        response = requests.post(
            endpoint.rstrip("/") + "/v1/generate",
            json={
                "prompt": prompt,
                "negativePrompt": negative_prompt,
                "referenceImage": reference_b64,
                "width": width,
                "height": height,
                "seed": seed,
                "styleStrength": style_strength,
                "identityLock": identity_lock,
                "format": "png",
            },
            timeout=240,
        )
        response.raise_for_status()
        body = response.json()

        encoded = body.get("image") or body.get("imageBase64")
        if not encoded:
            images = body.get("images")
            if isinstance(images, list) and images:
                encoded = images[0]
        if not encoded:
            raise RuntimeError("Nanobana response did not include image payload")

        raw = base64.b64decode(encoded.split(",", 1)[-1])
        return Image.open(io.BytesIO(raw)).convert("RGB")

    @staticmethod
    def _fallback_from_reference(
        *,
        reference_image: Image.Image,
        width: int,
        height: int,
        seed: int,
    ) -> Image.Image:
        rnd = random.Random(seed)
        canvas = reference_image.resize((width, height), Image.Resampling.LANCZOS).convert("RGB")
        canvas = ImageEnhance.Color(canvas).enhance(1.12 + rnd.uniform(-0.03, 0.05))
        canvas = ImageEnhance.Contrast(canvas).enhance(1.12 + rnd.uniform(-0.02, 0.04))
        canvas = ImageEnhance.Sharpness(canvas).enhance(1.18 + rnd.uniform(-0.03, 0.05))
        glow = canvas.filter(ImageFilter.GaussianBlur(radius=1.2))
        return Image.blend(canvas, glow, alpha=0.18)

    @staticmethod
    def _encode_image(image: Image.Image, width: int, height: int) -> str:
        resized = ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @staticmethod
    def _deterministic_seed(text: str) -> int:
        digest = sha256(text.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    @staticmethod
    def _write_log(
        *,
        destination: Path,
        item_id: str,
        image_path: str,
        prompt: str,
        negative_prompt: str,
        seed: int,
        used_fallback: bool,
        error: str,
        payload: NanobanaInput,
        article: NewsArticle | None,
    ) -> None:
        destination.write_text(
            json.dumps(
                {
                    "id": item_id,
                    "imagePath": image_path,
                    "prompt": prompt,
                    "negativePrompt": negative_prompt,
                    "seed": seed,
                    "usedFallback": used_fallback,
                    "error": error,
                    "article": article.to_json() if article else {},
                    "settings": {
                        "provider": payload.provider,
                        "endpoint": payload.endpoint,
                        "googleModel": payload.google_model,
                        "referenceImagePath": payload.reference_image_path,
                        "width": payload.width,
                        "height": payload.height,
                        "styleStrength": payload.style_strength,
                        "identityLock": payload.identity_lock,
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_with_google(
        *,
        api_key: str,
        model: str,
        prompt: str,
        reference_b64: str,
        foreground_b64: str | None,
        background_b64: str | None,
        article: NewsArticle | None,
    ) -> Image.Image:
        models_to_try = [
            model,
            "gemini-2.5-flash-image",
            "gemini-3.1-flash-image-preview",
        ]
        seen: set[str] = set()
        last_error = "Google image API request failed."

        for candidate_model in models_to_try:
            if candidate_model in seen:
                continue
            seen.add(candidate_model)
            try:
                parts: list[dict] = [
                    {"text": NanobanaAgent._google_instruction(prompt=prompt, article=article, use_pair=bool(foreground_b64 and background_b64))}
                ]
                if background_b64:
                    parts.append(
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": background_b64,
                            }
                        }
                    )
                if foreground_b64:
                    parts.append(
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": foreground_b64,
                            }
                        }
                    )
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": reference_b64,
                        }
                    }
                )

                response = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent",
                    headers={
                        "x-goog-api-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "contents": [{"parts": parts}],
                        "generationConfig": {
                            "responseModalities": ["TEXT", "IMAGE"],
                        },
                    },
                    timeout=240,
                )
                response.raise_for_status()
                body = response.json()
                image = NanobanaAgent._extract_inline_image_from_google(body)
                if image is not None:
                    return image
                last_error = f"Model {candidate_model} did not return inline image data."
            except Exception as exc:  # noqa: BLE001
                last_error = f"Model {candidate_model} failed: {exc}"

        raise RuntimeError(last_error)

    @staticmethod
    def _google_instruction(*, prompt: str, article: NewsArticle | None, use_pair: bool) -> str:
        base = (
            "Create a viral, ultra-realistic vertical editorial image (9:16). "
            "No text, no letters, no logos, no watermark, no UI, no captions. "
        )
        if use_pair:
            pair = (
                "Use image #1 as the BACKGROUND context (defocused, cinematic atmosphere). "
                "Use image #2 as the FOREGROUND subject (dominant, sharp, emotional expression). "
                "Foreground must be clearly in front of the background with strong depth. "
            )
        else:
            pair = "Use the provided reference style with cinematic composition and high realism. "
        detail = f"Topic: {(article.title if article else prompt)}. "
        return base + pair + detail + f"Style hints: {prompt}."

    @staticmethod
    def _prepare_reference(*, image: Image.Image, width: int, height: int) -> Image.Image:
        prepared = ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS).convert("RGB")
        blur = prepared.filter(ImageFilter.GaussianBlur(radius=12))
        top_h = int(height * 0.12)
        bottom_h = int(height * 0.30)

        prepared.paste(blur.crop((0, 0, width, top_h)), (0, 0))
        prepared.paste(blur.crop((0, height - bottom_h, width, height)), (0, height - bottom_h))
        return prepared

    @staticmethod
    def _extract_inline_image_from_google(body: dict) -> Image.Image | None:
        candidates = body.get("candidates") or []
        for candidate in candidates:
            parts = ((candidate.get("content") or {}).get("parts")) or []
            for part in parts:
                inline_data = part.get("inlineData") or part.get("inline_data")
                if not inline_data:
                    continue
                raw_b64 = inline_data.get("data")
                if not raw_b64:
                    continue
                raw = base64.b64decode(raw_b64.split(",", 1)[-1])
                return Image.open(io.BytesIO(raw)).convert("RGB")
        return None
