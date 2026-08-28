#!/usr/bin/env python3
"""Generate or verify the checked-in logo linkage manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from financial_registry.logo_manifest import (
    LogoManifestError,
    build_logo_manifest,
    serialize_logo_manifest,
    verify_logo_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write a deterministic manifest instead of comparing an existing one",
    )
    args = parser.parse_args()

    try:
        if args.write:
            manifest = build_logo_manifest(args.registry, registry_label=args.registry.as_posix())
            args.manifest.write_text(serialize_logo_manifest(manifest), encoding="utf-8")
        else:
            manifest = verify_logo_manifest(args.registry, args.manifest)
    except LogoManifestError as exc:
        print(f"logo manifest invalid: {exc}", file=sys.stderr)
        return 1

    print(
        f"logo manifest valid: {manifest['asset_count']} assets, "
        f"{manifest['owner_count']} owners, {manifest['source_count']} sources"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
