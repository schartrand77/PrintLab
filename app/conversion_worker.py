from __future__ import annotations

import json
import sys
from pathlib import Path

from app.conversion import convert_model_bytes


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4:
        print("Usage: python -m app.conversion_worker <input_path> <output_path> <filename> <target_format> [source_format]", file=sys.stderr)
        return 2

    input_path = Path(args[0])
    output_path = Path(args[1])
    filename = args[2]
    target_format = args[3]
    source_format = args[4] if len(args) > 4 and args[4] else None

    try:
        result = convert_model_bytes(
            filename=filename,
            content=input_path.read_bytes(),
            target_format=target_format,
            source_format=source_format,
        )
        output_path.write_text(json.dumps(result), encoding="utf-8")
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
