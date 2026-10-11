"""Command line entry point: python -m invkit.cli FILE.csv [--sort KEY] [--low N]"""
import argparse
import sys
from pathlib import Path

from .parsing import parse_csv
from .report import SORT_KEYS, format_report
from .store import Inventory


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="invkit")
    p.add_argument("csv_file")
    p.add_argument("--sort", default="sku", choices=sorted(SORT_KEYS))
    p.add_argument("--low", type=int, default=None, help="only items with stock below N")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    inv = Inventory(parse_csv(Path(args.csv_file).read_text()))
    items = inv.low_stock(args.low) if args.low is not None else list(inv)
    print(format_report(items, sort_by=args.sort))
    return 0


if __name__ == "__main__":
    sys.exit(main())
