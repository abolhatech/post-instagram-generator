from __future__ import annotations

import base64
import io
import json
from hashlib import sha256
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from news_image_generator.models import (
    GeneratedImageItem,
    ImageGeneratorInput,
    ImageGeneratorOutput,
    ensure_dir,
)


class ImageGeneratorAgent:
    _STYLE_SUFFIXES: dict[str, str] = {
        "cinematic": (
            "cinematic portrait, expressive human face, dramatic rim lighting, "
            "tech atmosphere, editorial photo, high detail skin texture, "
            "shallow depth of field, realistic color grading"
        ),
        "editorial": (
            "editorial photography, natural facial features, balanced contrast, "
            "modern newsroom ambiance"
        ),
    }
    _NEGATIVE_SUFFIX = (
        "text, watermark, logo, signature, low quality, blurry, out of focus, "
        "distorted face, deformed hands, extra fingers, jpeg artifacts"
    )

    def run(self, payload: ImageGeneratorInput) -> ImageGeneratorOutput:
        out_dir = ensure_dir(Path(payload.output_dir) / "generated")
        logs_dir = ensure_dir(Path(payload.output_dir) / "logs" / "image_generator")
        results: list[GeneratedImageItem] = []

        for item in payload.prompts:
            destination = out_dir / f"{item.id}.png"
            error = ""
            used_fallback = False
            seed = payload.seed if payload.seed >= 0 else self._deterministic_seed(item.id)
            final_prompt = self._merge_prompt(item.prompt, payload.style_preset)
            final_negative = self._merge_negative_prompt(item.negativePrompt)

            try:
                image = self._generate_with_a1111(
                    endpoint=payload.endpoint,
                    prompt=final_prompt,
                    negative_prompt=final_negative,
                    width=payload.width,
                    height=payload.height,
                    steps=payload.steps,
                    cfg_scale=payload.cfg_scale,
                    seed=seed,
                    sampler_name=payload.sampler_name,
                    enable_second_pass=payload.enable_second_pass,
                    second_pass_steps=payload.second_pass_steps,
                    second_pass_denoise=payload.second_pass_denoise,
                    base_pass_scale=payload.base_pass_scale,
                    face_restore=payload.face_restore,
                )
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                used_fallback = True
                image = self._generate_fallback(
                    prompt=final_prompt,
                    width=payload.width,
                    height=payload.height,
                )

            image.save(destination, format="PNG")
            self._write_generation_log(
                destination=logs_dir / f"{item.id}.json",
                item_id=item.id,
                prompt=final_prompt,
                negative_prompt=final_negative,
                image_path=str(destination),
                seed=seed,
                used_fallback=used_fallback,
                error=error,
                payload=payload,
            )
            results.append(
                GeneratedImageItem(
                    id=item.id,
                    prompt=final_prompt,
                    imagePath=str(destination),
                    provider="automatic1111-two-pass",
                    usedFallback=used_fallback,
                    error=error,
                )
            )
        return ImageGeneratorOutput(images=results)

    @staticmethod
    def _generate_with_a1111(
        *,
        endpoint: str,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        seed: int,
        sampler_name: str,
        enable_second_pass: bool,
        second_pass_steps: int,
        second_pass_denoise: float,
        base_pass_scale: float,
        face_restore: bool,
    ) -> Image.Image:
        base_width, base_height = ImageGeneratorAgent._base_dimensions(
            width=width, height=height, scale=base_pass_scale
        )
        first_image = ImageGeneratorAgent._txt2img(
            endpoint=endpoint,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=base_width,
            height=base_height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            sampler_name=sampler_name,
            face_restore=face_restore,
        )

        if not enable_second_pass:
            return ImageGeneratorAgent._resize_to_target(first_image, width, height)

        second_image = ImageGeneratorAgent._img2img(
            endpoint=endpoint,
            prompt=prompt,
            negative_prompt=negative_prompt,
            init_image=first_image,
            width=width,
            height=height,
            steps=second_pass_steps,
            cfg_scale=cfg_scale,
            seed=seed,
            sampler_name=sampler_name,
            denoising_strength=second_pass_denoise,
            face_restore=face_restore,
        )
        return second_image

    @staticmethod
    def _txt2img(
        *,
        endpoint: str,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        seed: int,
        sampler_name: str,
        face_restore: bool,
    ) -> Image.Image:
        body = ImageGeneratorAgent._post_json(
            endpoint=endpoint,
            path="/sdapi/v1/txt2img",
            payload={
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "steps": steps,
                "cfg_scale": cfg_scale,
                "seed": seed,
                "width": width,
                "height": height,
                "sampler_name": sampler_name,
                "restore_faces": face_restore,
            },
            timeout=180,
        )
        return ImageGeneratorAgent._decode_response_image(body)

    @staticmethod
    def _img2img(
        *,
        endpoint: str,
        prompt: str,
        negative_prompt: str,
        init_image: Image.Image,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        seed: int,
        sampler_name: str,
        denoising_strength: float,
        face_restore: bool,
    ) -> Image.Image:
        body = ImageGeneratorAgent._post_json(
            endpoint=endpoint,
            path="/sdapi/v1/img2img",
            payload={
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "init_images": [ImageGeneratorAgent._encode_image(init_image)],
                "steps": steps,
                "cfg_scale": cfg_scale,
                "seed": seed,
                "width": width,
                "height": height,
                "sampler_name": sampler_name,
                "denoising_strength": denoising_strength,
                "restore_faces": face_restore,
                "resize_mode": 1,
            },
            timeout=220,
        )
        return ImageGeneratorAgent._decode_response_image(body)

    @staticmethod
    def _post_json(
        *,
        endpoint: str,
        path: str,
        payload: dict,
        timeout: int,
    ) -> dict:
        response = requests.post(
            endpoint.rstrip("/") + path,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _decode_response_image(body: dict) -> Image.Image:
        images = body.get("images") or []
        if not images:
            raise RuntimeError("No image returned by Automatic1111 endpoint")
        raw = base64.b64decode(images[0].split(",", 1)[-1])
        return Image.open(io.BytesIO(raw)).convert("RGB")

    @staticmethod
    def _encode_image(image: Image.Image) -> str:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @staticmethod
    def _resize_to_target(image: Image.Image, width: int, height: int) -> Image.Image:
        if image.size == (width, height):
            return image
        return image.resize((width, height), Image.Resampling.LANCZOS)

    @staticmethod
    def _base_dimensions(*, width: int, height: int, scale: float) -> tuple[int, int]:
        scaled_w = max(512, int(width * scale))
        scaled_h = max(768, int(height * scale))
        return ImageGeneratorAgent._closest64(scaled_w), ImageGeneratorAgent._closest64(scaled_h)

    @staticmethod
    def _closest64(value: int) -> int:
        return max(64, int(round(value / 64.0)) * 64)

    @staticmethod
    def _deterministic_seed(text: str) -> int:
        digest = sha256(text.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def _merge_prompt(self, prompt: str, style_preset: str) -> str:
        suffix = self._STYLE_SUFFIXES.get(style_preset.lower(), self._STYLE_SUFFIXES["cinematic"])
        return ", ".join(part for part in [prompt.strip(), suffix] if part)

    def _merge_negative_prompt(self, negative_prompt: str) -> str:
        merged = ", ".join(part for part in [negative_prompt.strip(), self._NEGATIVE_SUFFIX] if part)
        seen: set[str] = set()
        unique_parts: list[str] = []
        for part in (piece.strip() for piece in merged.split(",")):
            if not part:
                continue
            key = part.lower()
            if key in seen:
                continue
            seen.add(key)
            unique_parts.append(part)
        return ", ".join(unique_parts)

    @staticmethod
    def _write_generation_log(
        *,
        destination: Path,
        item_id: str,
        prompt: str,
        negative_prompt: str,
        image_path: str,
        seed: int,
        used_fallback: bool,
        error: str,
        payload: ImageGeneratorInput,
    ) -> None:
        destination.write_text(
            json.dumps(
                {
                    "id": item_id,
                    "prompt": prompt,
                    "negativePrompt": negative_prompt,
                    "imagePath": image_path,
                    "seed": seed,
                    "usedFallback": used_fallback,
                    "error": error,
                    "settings": {
                        "endpoint": payload.endpoint,
                        "width": payload.width,
                        "height": payload.height,
                        "steps": payload.steps,
                        "cfgScale": payload.cfg_scale,
                        "samplerName": payload.sampler_name,
                        "enableSecondPass": payload.enable_second_pass,
                        "secondPassSteps": payload.second_pass_steps,
                        "secondPassDenoise": payload.second_pass_denoise,
                        "basePassScale": payload.base_pass_scale,
                        "faceRestore": payload.face_restore,
                        "stylePreset": payload.style_preset,
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_fallback(*, prompt: str, width: int, height: int) -> Image.Image:
        base = Image.new("RGB", (width, height), color=(20, 24, 35))
        draw = ImageDraw.Draw(base)
        for y in range(height):
            ratio = y / max(height - 1, 1)
            color = (
                int(30 + 100 * ratio),
                int(40 + 80 * ratio),
                int(90 + 100 * ratio),
            )
            draw.line((0, y, width, y), fill=color)
        draw.rectangle((32, 32, width - 32, height - 32), outline=(255, 255, 255), width=3)
        draw.text((52, 52), "FALLBACK IMAGE", fill=(255, 255, 255))
        return base
