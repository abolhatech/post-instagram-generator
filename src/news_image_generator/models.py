from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class NewsArticle:
    id: str
    title: str
    summary: str
    imageUrl: str = ""
    sourceUrl: str = ""
    sourceUrl2: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "imageUrl": self.imageUrl,
            "sourceUrl": self.sourceUrl,
            "sourceUrl2": self.sourceUrl2,
        }


@dataclass
class ParseInput:
    input_path: str
    max_articles: int = 7


@dataclass
class ParseOutput:
    articles: list[NewsArticle]
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "articles": [article.to_json() for article in self.articles],
            "warnings": self.warnings,
        }


@dataclass
class CopyItem:
    id: str
    title: str
    viralHeadline: str
    angle: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "viralHeadline": self.viralHeadline,
            "angle": self.angle,
        }


@dataclass
class CopywriterInput:
    articles: list[NewsArticle]


@dataclass
class CopywriterOutput:
    copies: list[CopyItem]

    def to_json(self) -> dict[str, Any]:
        return {"copies": [copy.to_json() for copy in self.copies]}


@dataclass
class VisualPromptItem:
    id: str
    prompt: str
    negativePrompt: str
    styleTags: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "negativePrompt": self.negativePrompt,
            "styleTags": self.styleTags,
        }


@dataclass
class VisualPromptInput:
    articles: list[NewsArticle]
    copies: list[CopyItem]


@dataclass
class VisualPromptOutput:
    prompts: list[VisualPromptItem]

    def to_json(self) -> dict[str, Any]:
        return {"prompts": [prompt.to_json() for prompt in self.prompts]}


@dataclass
class GeneratedImageItem:
    id: str
    prompt: str
    imagePath: str
    provider: str
    usedFallback: bool
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "imagePath": self.imagePath,
            "provider": self.provider,
            "usedFallback": self.usedFallback,
            "error": self.error,
        }


@dataclass
class ImageGeneratorInput:
    prompts: list[VisualPromptItem]
    output_dir: str
    endpoint: str = "http://127.0.0.1:7860"
    width: int = 1080
    height: int = 1920
    steps: int = 24
    cfg_scale: float = 6.5
    seed: int = -1
    sampler_name: str = "DPM++ 2M Karras"
    enable_second_pass: bool = True
    second_pass_steps: int = 30
    second_pass_denoise: float = 0.32
    base_pass_scale: float = 0.62
    face_restore: bool = True
    style_preset: str = "cinematic"


@dataclass
class ImageGeneratorOutput:
    images: list[GeneratedImageItem]

    def to_json(self) -> dict[str, Any]:
        return {"images": [image.to_json() for image in self.images]}


@dataclass
class NanobanaInput:
    articles: list[NewsArticle]
    prompts: list[VisualPromptItem]
    output_dir: str
    reference_image_path: str | None = None
    provider: str = "nanobana"
    endpoint: str = "http://127.0.0.1:9000"
    google_api_key: str | None = None
    google_model: str = "gemini-2.5-flash-image"
    width: int = 1080
    height: int = 1920
    seed: int = -1
    style_strength: float = 0.72
    identity_lock: float = 0.66


@dataclass
class ComposedImageItem:
    id: str
    headline: str
    sourceUrl: str
    baseImagePath: str
    composedImagePath: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "headline": self.headline,
            "sourceUrl": self.sourceUrl,
            "baseImagePath": self.baseImagePath,
            "composedImagePath": self.composedImagePath,
        }


@dataclass
class LayoutComposerInput:
    articles: list[NewsArticle]
    copies: list[CopyItem]
    images: list[GeneratedImageItem]
    output_dir: str
    font_path: str | None = None
    publish_format: str = "story"


@dataclass
class LayoutComposerOutput:
    composed: list[ComposedImageItem]

    def to_json(self) -> dict[str, Any]:
        return {"composed": [item.to_json() for item in self.composed]}


@dataclass
class ValidationItem:
    id: str
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class ValidatorInput:
    articles: list[NewsArticle]
    copies: list[CopyItem]
    images: list[GeneratedImageItem]
    composed: list[ComposedImageItem]


@dataclass
class ValidatorOutput:
    validations: list[ValidationItem]

    def to_json(self) -> dict[str, Any]:
        return {"validations": [item.to_json() for item in self.validations]}


@dataclass
class ExportItem:
    id: str
    outputPath: str
    title: str
    headline: str
    sourceUrl: str
    valid: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "outputPath": self.outputPath,
            "title": self.title,
            "headline": self.headline,
            "sourceUrl": self.sourceUrl,
            "valid": self.valid,
        }


@dataclass
class ExportInput:
    articles: list[NewsArticle]
    copies: list[CopyItem]
    composed: list[ComposedImageItem]
    validations: list[ValidationItem]
    output_dir: str


@dataclass
class ExportOutput:
    exports: list[ExportItem]
    manifestPath: str

    def to_json(self) -> dict[str, Any]:
        return {
            "exports": [item.to_json() for item in self.exports],
            "manifestPath": self.manifestPath,
        }


@dataclass
class PipelineRequest:
    input_path: str
    output_dir: str
    endpoint: str = "http://127.0.0.1:7860"
    max_articles: int = 7
    publish_format: str = "story"
    width: int = 1080
    height: int = 1920
    steps: int = 24
    cfg_scale: float = 6.5
    seed: int = -1
    sampler_name: str = "DPM++ 2M Karras"
    enable_second_pass: bool = True
    second_pass_steps: int = 30
    second_pass_denoise: float = 0.32
    base_pass_scale: float = 0.62
    face_restore: bool = True
    style_preset: str = "cinematic"
    enable_nanobana_step: bool = False
    reference_image_path: str | None = None
    nanobana_endpoint: str = "http://127.0.0.1:9000"
    nanobana_style_strength: float = 0.72
    nanobana_identity_lock: float = 0.66
    enable_google_image_step: bool = False
    google_api_key: str | None = None
    google_model: str = "gemini-2.5-flash-image"
    fail_on_fallback: bool = False
    cleanup_intermediate: bool = True
    run_validator: bool = True
    font_path: str | None = None


@dataclass
class PipelineOutput:
    parsed_count: int
    exported_count: int
    manifest_path: str
    parse_warnings: list[str]
    used_fallback_images: int

    def to_json(self) -> dict[str, Any]:
        return {
            "parsedCount": self.parsed_count,
            "exportedCount": self.exported_count,
            "manifestPath": self.manifest_path,
            "parseWarnings": self.parse_warnings,
            "usedFallbackImages": self.used_fallback_images,
        }


def ensure_dir(path: str | Path) -> Path:
    value = Path(path)
    value.mkdir(parents=True, exist_ok=True)
    return value
