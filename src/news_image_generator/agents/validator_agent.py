from __future__ import annotations

from pathlib import Path

from news_image_generator.models import ValidationItem, ValidatorInput, ValidatorOutput


class ValidatorAgent:
    def run(self, payload: ValidatorInput) -> ValidatorOutput:
        copy_by_id = {item.id: item for item in payload.copies}
        image_by_id = {item.id: item for item in payload.images}
        composed_by_id = {item.id: item for item in payload.composed}

        validations: list[ValidationItem] = []
        for article in payload.articles:
            errors: list[str] = []
            warnings: list[str] = []
            copy = copy_by_id.get(article.id)
            image = image_by_id.get(article.id)
            composed = composed_by_id.get(article.id)

            if not copy:
                errors.append("Missing copywriter output")
            else:
                if len(copy.viralHeadline) < 30:
                    warnings.append("Headline is short and may underperform")
                if len(copy.viralHeadline) > 95:
                    errors.append("Headline exceeds 95 characters")

            if not image:
                errors.append("Missing generated image")
            else:
                if not Path(image.imagePath).exists():
                    errors.append(f"Generated image path does not exist: {image.imagePath}")
                if image.usedFallback:
                    warnings.append("Fallback image used because AI generation failed")

            if not composed:
                errors.append("Missing composed thumbnail")
            else:
                if not Path(composed.composedImagePath).exists():
                    errors.append(
                        f"Composed image path does not exist: {composed.composedImagePath}"
                    )

            validations.append(
                ValidationItem(
                    id=article.id,
                    valid=len(errors) == 0,
                    errors=errors,
                    warnings=warnings,
                )
            )

        return ValidatorOutput(validations=validations)
