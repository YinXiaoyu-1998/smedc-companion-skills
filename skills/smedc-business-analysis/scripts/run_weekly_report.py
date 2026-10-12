#!/usr/bin/env python3
"""Profile and render a SMEDC weekly meeting report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from generate_weekly_report_html import render
from identity import organization_name_from_current_user_file
from profile_weekly_data import profile
from report_common import cleanup_partition_extracts, load_store_groups


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument(
        "--current-user",
        type=Path,
        help="Saved smedc_get_current_user response used as the only report organization source.",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--company")
    parser.add_argument("--store-groups", type=Path, help="Explicit full-name 大店/小店 JSON configuration.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        organization_name = organization_name_from_current_user_file(args.current_user) if args.current_user else None
        summary = profile(args.bundle, args.output_dir, organization_name, load_store_groups(args.store_groups))
        result = render(args.output_dir, args.report, args.company)
        result["notices"] = summary.get("data_gaps", [])
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        cleanup_partition_extracts(args.bundle)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
