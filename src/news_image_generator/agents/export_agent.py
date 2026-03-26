from __future__ import annotations

import json
import shutil
from pathlib import Path

from news_image_generator.models import (
    ExportInput,
    ExportItem,
    ExportOutput,
    ensure_dir,
)


class ExportAgent:
    def run(self, payload: ExportInput) -> ExportOutput:
        export_dir = ensure_dir(Path(payload.output_dir) / "final")
        article_by_id = {item.id: item for item in payload.articles}
        copy_by_id = {item.id: item for item in payload.copies}
        validation_by_id = {item.id: item for item in payload.validations}

        exports: list[ExportItem] = []
        for index, composed in enumerate(payload.composed, start=1):
            article = article_by_id.get(composed.id)
            copy = copy_by_id.get(composed.id)
            if not article or not copy:
                continue
            file_name = f"{index:02d}_{composed.id[:8]}.png"
            destination = export_dir / file_name
            shutil.copy2(composed.composedImagePath, destination)
            validation = validation_by_id.get(composed.id)
            exports.append(
                ExportItem(
                    id=composed.id,
                    outputPath=str(destination),
                    title=article.title,
                    headline=composed.headline,
                    sourceUrl=article.sourceUrl,
                    valid=validation.valid if validation else True,
                )
            )

        manifest_path = export_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({"exports": [item.to_json() for item in exports]}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return ExportOutput(exports=exports, manifestPath=str(manifest_path))
