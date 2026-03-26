from __future__ import annotations

import argparse
import json
import sys

from news_image_generator.models import PipelineRequest
from news_image_generator.pipeline import NewsImagePipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local multi-agent news image generator")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run end-to-end pipeline")
    run_parser.add_argument("--input", required=True, help="Path to .json or .md input file")
    run_parser.add_argument("--output", required=True, help="Output folder")
    run_parser.add_argument("--endpoint", default="http://127.0.0.1:7860", help="Local Automatic1111 endpoint")
    run_parser.add_argument("--max-articles", type=int, default=7, help="Maximum number of articles")
    run_parser.add_argument("--width", type=int, default=1080)
    run_parser.add_argument("--height", type=int, default=1920)
    run_parser.add_argument("--steps", type=int, default=24)
    run_parser.add_argument("--cfg-scale", type=float, default=6.5)
    run_parser.add_argument("--seed", type=int, default=-1)
    run_parser.add_argument("--sampler-name", default="DPM++ 2M Karras")
    run_parser.add_argument("--disable-second-pass", action="store_true")
    run_parser.add_argument("--second-pass-steps", type=int, default=30)
    run_parser.add_argument("--second-pass-denoise", type=float, default=0.32)
    run_parser.add_argument("--base-pass-scale", type=float, default=0.62)
    run_parser.add_argument("--disable-face-restore", action="store_true")
    run_parser.add_argument(
        "--style-preset",
        choices=["cinematic", "editorial"],
        default="cinematic",
        help="Prompt suffix preset used by image generator",
    )
    run_parser.add_argument("--enable-nanobana", action="store_true")
    run_parser.add_argument("--reference-image", default=None, help="Reference image path for Nanobana step")
    run_parser.add_argument("--nanobana-endpoint", default="http://127.0.0.1:9000")
    run_parser.add_argument("--nanobana-style-strength", type=float, default=0.72)
    run_parser.add_argument("--nanobana-identity-lock", type=float, default=0.66)
    run_parser.add_argument("--enable-google-image-step", action="store_true")
    run_parser.add_argument("--google-api-key", default=None, help="Google AI API key (optional if GOOGLE_API_KEY env is set)")
    run_parser.add_argument("--google-model", default="gemini-2.5-flash-image")
    run_parser.add_argument("--font-path", default=None, help="Optional TTF font path")
    run_parser.add_argument("--skip-validator", action="store_true")
    run_parser.add_argument("--keep-intermediate", action="store_true")
    run_parser.add_argument("--fail-on-fallback", action="store_true")
    run_parser.add_argument("--json", action="store_true", help="Print machine-readable summary")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 1

    pipeline = NewsImagePipeline()
    result = pipeline.run(
        PipelineRequest(
            input_path=args.input,
            output_dir=args.output,
            endpoint=args.endpoint,
            max_articles=args.max_articles,
            width=args.width,
            height=args.height,
            steps=args.steps,
            cfg_scale=args.cfg_scale,
            seed=args.seed,
            sampler_name=args.sampler_name,
            enable_second_pass=not args.disable_second_pass,
            second_pass_steps=args.second_pass_steps,
            second_pass_denoise=args.second_pass_denoise,
            base_pass_scale=args.base_pass_scale,
            face_restore=not args.disable_face_restore,
            style_preset=args.style_preset,
            enable_nanobana_step=args.enable_nanobana,
            reference_image_path=args.reference_image,
            nanobana_endpoint=args.nanobana_endpoint,
            nanobana_style_strength=args.nanobana_style_strength,
            nanobana_identity_lock=args.nanobana_identity_lock,
            enable_google_image_step=args.enable_google_image_step,
            google_api_key=args.google_api_key,
            google_model=args.google_model,
            fail_on_fallback=args.fail_on_fallback,
            cleanup_intermediate=not args.keep_intermediate,
            run_validator=not args.skip_validator,
            font_path=args.font_path,
        )
    )

    if args.json:
        print(json.dumps(result.to_json(), indent=2, ensure_ascii=False))
    else:
        print(f"Parsed articles: {result.parsed_count}")
        print(f"Exported images: {result.exported_count}")
        print(f"Manifest: {result.manifest_path}")
        print(f"Fallback images used: {result.used_fallback_images}")
        if result.parse_warnings:
            print("Warnings:")
            for warning in result.parse_warnings:
                print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
