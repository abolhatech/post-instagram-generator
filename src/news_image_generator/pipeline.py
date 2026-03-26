from __future__ import annotations

import shutil
from pathlib import Path

from news_image_generator.agents.copywriter_agent import CopywriterAgent
from news_image_generator.agents.export_agent import ExportAgent
from news_image_generator.agents.image_generator_agent import ImageGeneratorAgent
from news_image_generator.agents.layout_composer_agent import LayoutComposerAgent
from news_image_generator.agents.nanobana_agent import NanobanaAgent
from news_image_generator.agents.parser_agent import ParserAgent
from news_image_generator.agents.validator_agent import ValidatorAgent
from news_image_generator.agents.visual_prompt_agent import VisualPromptAgent
from news_image_generator.models import (
    CopywriterInput,
    ExportInput,
    ImageGeneratorInput,
    LayoutComposerInput,
    NanobanaInput,
    ParseInput,
    PipelineOutput,
    PipelineRequest,
    ValidationItem,
    ValidatorInput,
    VisualPromptInput,
    ensure_dir,
)


class NewsImagePipeline:
    def __init__(
        self,
        parser: ParserAgent | None = None,
        copywriter: CopywriterAgent | None = None,
        visual_prompt: VisualPromptAgent | None = None,
        image_generator: ImageGeneratorAgent | None = None,
        nanobana: NanobanaAgent | None = None,
        layout_composer: LayoutComposerAgent | None = None,
        validator: ValidatorAgent | None = None,
        exporter: ExportAgent | None = None,
    ) -> None:
        self.parser = parser or ParserAgent()
        self.copywriter = copywriter or CopywriterAgent()
        self.visual_prompt = visual_prompt or VisualPromptAgent()
        self.image_generator = image_generator or ImageGeneratorAgent()
        self.nanobana = nanobana or NanobanaAgent()
        self.layout_composer = layout_composer or LayoutComposerAgent()
        self.validator = validator or ValidatorAgent()
        self.exporter = exporter or ExportAgent()

    def run(self, payload: PipelineRequest) -> PipelineOutput:
        ensure_dir(payload.output_dir)

        parsed = self.parser.run(
            ParseInput(input_path=payload.input_path, max_articles=payload.max_articles)
        )
        if not parsed.articles:
            raise RuntimeError("Parser returned no articles. Check input format.")

        copied = self.copywriter.run(CopywriterInput(articles=parsed.articles))
        prompted = self.visual_prompt.run(
            VisualPromptInput(articles=parsed.articles, copies=copied.copies)
        )
        if payload.enable_nanobana_step:
            has_per_article_sources = all(
                bool((article.sourceUrl or "").strip()) and bool((article.sourceUrl2 or "").strip())
                for article in parsed.articles
            )
            if not payload.reference_image_path and not has_per_article_sources:
                raise RuntimeError(
                    "Nanobana step needs sourceUrl/sourceUrl2 in every article or a fallback "
                    "reference image via --reference-image."
                )
            generated = self.nanobana.run(
                NanobanaInput(
                    articles=parsed.articles,
                    prompts=prompted.prompts,
                    output_dir=payload.output_dir,
                    reference_image_path=payload.reference_image_path,
                    provider="google" if payload.enable_google_image_step else "nanobana",
                    endpoint=payload.nanobana_endpoint,
                    google_api_key=payload.google_api_key,
                    google_model=payload.google_model,
                    width=payload.width,
                    height=payload.height,
                    seed=payload.seed,
                    style_strength=payload.nanobana_style_strength,
                    identity_lock=payload.nanobana_identity_lock,
                )
            )
        else:
            generated = self.image_generator.run(
                ImageGeneratorInput(
                    prompts=prompted.prompts,
                    output_dir=payload.output_dir,
                    endpoint=payload.endpoint,
                    width=payload.width,
                    height=payload.height,
                    steps=payload.steps,
                    cfg_scale=payload.cfg_scale,
                    seed=payload.seed,
                    sampler_name=payload.sampler_name,
                    enable_second_pass=payload.enable_second_pass,
                    second_pass_steps=payload.second_pass_steps,
                    second_pass_denoise=payload.second_pass_denoise,
                    base_pass_scale=payload.base_pass_scale,
                    face_restore=payload.face_restore,
                    style_preset=payload.style_preset,
                )
            )
        composed = self.layout_composer.run(
            LayoutComposerInput(
                articles=parsed.articles,
                copies=copied.copies,
                images=generated.images,
                output_dir=payload.output_dir,
                font_path=payload.font_path,
            )
        )

        if payload.run_validator:
            validated = self.validator.run(
                ValidatorInput(
                    articles=parsed.articles,
                    copies=copied.copies,
                    images=generated.images,
                    composed=composed.composed,
                )
            ).validations
        else:
            validated = [ValidationItem(id=item.id, valid=True) for item in composed.composed]

        exported = self.exporter.run(
            ExportInput(
                articles=parsed.articles,
                copies=copied.copies,
                composed=composed.composed,
                validations=validated,
                output_dir=payload.output_dir,
            )
        )
        fallback_count = sum(1 for item in generated.images if item.usedFallback)
        if payload.fail_on_fallback and fallback_count > 0:
            errors = [item.error for item in generated.images if item.usedFallback and item.error]
            detail = errors[0] if errors else "Unknown image generation error."
            raise RuntimeError(
                f"Image generation used fallback for {fallback_count} item(s). First error: {detail}"
            )

        if payload.cleanup_intermediate:
            self._cleanup_intermediate_outputs(payload.output_dir)

        return PipelineOutput(
            parsed_count=len(parsed.articles),
            exported_count=len(exported.exports),
            manifest_path=exported.manifestPath,
            parse_warnings=parsed.warnings,
            used_fallback_images=fallback_count,
        )

    @staticmethod
    def _cleanup_intermediate_outputs(output_dir: str) -> None:
        root = Path(output_dir)
        for name in ["generated", "composed", "logs"]:
            target = root / name
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)

        # Remove stale root-level manifest from older runs; final manifest is under final/.
        old_manifest = root / "manifest.json"
        if old_manifest.exists():
            old_manifest.unlink(missing_ok=True)
