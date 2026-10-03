#!/usr/bin/env python3
"""Export SMEDC ledger tables, preferring XLSX with explicit text cells."""

import sys

from export_ledger_csv import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], default_format="xlsx"))
