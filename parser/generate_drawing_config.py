from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .drawing_config_generator import DEFAULT_UNITS, generate_drawing_config_file
except ImportError:  # pragma: no cover - used when running as a script from parser/
    from drawing_config_generator import DEFAULT_UNITS, generate_drawing_config_file


def parse_args() -> argparse.Namespace:
    parser_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Generate drawing_config.json from parser/drafting_data.json."
    )
    parser.add_argument(
        "-i",
        "--input",
        default=parser_dir / "drafting_data.json",
        type=Path,
        help="Path to drafting_data.json.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=parser_dir / "drawing_config.json",
        type=Path,
        help="Path for generated drawing_config.json.",
    )
    parser.add_argument(
        "--units",
        default=DEFAULT_UNITS,
        help="Units label to store in drawing_config.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generate_drawing_config_file(
        input_path=args.input,
        output_path=args.output,
        units=args.units,
    )
    print(f"DONE -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
