from __future__ import annotations

from news_image_generator.models import (
    CopyItem,
    VisualPromptInput,
    VisualPromptItem,
    VisualPromptOutput,
)


class VisualPromptAgent:
    def run(self, payload: VisualPromptInput) -> VisualPromptOutput:
        copy_by_id: dict[str, CopyItem] = {item.id: item for item in payload.copies}
        results: list[VisualPromptItem] = []
        for article in payload.articles:
            copy = copy_by_id.get(article.id)
            if not copy:
                continue
            tags = self._style_tags(article.title, article.summary)
            prompt = (
                "viral editorial thumbnail, cinematic photojournalism, "
                "expressive human face or company symbol in foreground, "
                "corporate/tech context in background, clear depth separation, "
                f"{', '.join(tags)}, dramatic key light, high contrast, rich texture, "
                "ultra realistic, dynamic composition, no text, no watermark, no logo"
            )
            negative = (
                "text, letters, logo, watermark, signature, blurry, deformed face, "
                "extra limbs, low quality, oversaturated"
            )
            results.append(
                VisualPromptItem(
                    id=article.id,
                    prompt=prompt,
                    negativePrompt=negative,
                    styleTags=tags,
                )
            )
        return VisualPromptOutput(prompts=results)

    @staticmethod
    def _style_tags(title: str, summary: str) -> list[str]:
        seed = f"{title} {summary}".lower()
        tags = ["editorial realism"]
        if any(word in seed for word in ["ai", "tech", "software", "startup", "chip"]):
            tags.extend(["futuristic newsroom", "neon reflections"])
        elif any(word in seed for word in ["war", "conflict", "election", "government"]):
            tags.extend(["tense atmosphere", "documentary framing"])
        elif any(word in seed for word in ["market", "stock", "finance", "economy"]):
            tags.extend(["financial district", "glass and steel skyline"])
        elif any(word in seed for word in ["health", "virus", "hospital", "medicine"]):
            tags.extend(["clinical environment", "soft blue palette"])
        else:
            tags.extend(["urban backdrop", "depth of field"])
        return tags
