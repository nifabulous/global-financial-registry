#!/usr/bin/env python3
"""Build or verify the lightweight data projection used by the logo gallery."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from financial_registry.gallery_data import (
    GalleryDataError,
    build_gallery_data,
    serialize_gallery_data,
    verify_gallery_data,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("gallery", type=Path)
    parser.add_argument("--write", action="store_true", help="write instead of verifying")
    args = parser.parse_args()
    try:
        if args.write:
            data = build_gallery_data(args.registry)
            args.gallery.write_text(serialize_gallery_data(data), encoding="utf-8")
        else:
            data = verify_gallery_data(args.registry, args.gallery)
    except GalleryDataError as exc:
        print(f"gallery data invalid: {exc}", file=sys.stderr)
        return 1
    print(f"gallery data valid: {len(data['assets'])} assets, {len(data['institutions']) + len(data['brands'])} linked owners")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
