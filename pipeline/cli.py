"""Command-line entry point.

Examples:
    python -m pipeline                                  # last complete month, SST + LST
    python -m pipeline --month 2026-09
    python -m pipeline --months 2026-01:2026-09 --products SST
    python -m pipeline --start 2026-10-01 --end 2026-10-07
    python -m pipeline --as-of 2026-10-15 --window-days 7   # 7 days ending 2026-10-15
    python -m pipeline --as-of latest                       # 30 days ending at the latest image
    python -m pipeline --month 2026-09 --export drive
"""

import argparse
import datetime as dt
import functools
import pathlib

from . import config, gee, periods, runner


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="GCOM-C SST/LST products for the Philippine Area of Responsibility")
    when = p.add_mutually_exclusive_group()
    when.add_argument("--month", action="append", help="Target month YYYY-MM (repeatable)")
    when.add_argument("--months", help="Inclusive month range YYYY-MM:YYYY-MM")
    when.add_argument("--start", help="Custom period start YYYY-MM-DD (use with --end)")
    when.add_argument("--as-of", help="Window ending on this date (YYYY-MM-DD or 'latest')")
    p.add_argument("--end", help="Custom period end YYYY-MM-DD, inclusive")
    p.add_argument("--window-days", type=int, default=30, help="Window length for --as-of (default 30)")
    p.add_argument("--products", nargs="+", default=list(config.PRODUCTS), choices=list(config.PRODUCTS))
    p.add_argument("--pass", dest="sat_pass", choices=["D", "N", "both"],
                   help="Satellite pass (default: SST=both, LST=D)")
    p.add_argument("--lst-anomaly", action="store_true", help="Also produce an LST anomaly")
    p.add_argument("--baseline", help="Climatology years FIRST:LAST (default: entire record)")
    p.add_argument("--export", choices=["local", "drive"], default="local")
    p.add_argument("--out", default="outputs", type=pathlib.Path, help="Local output root")
    p.add_argument("--no-png", action="store_true", help="Skip PNG quicklooks")
    p.add_argument("--project", default=config.GEE_PROJECT)
    args = p.parse_args(argv)
    if bool(args.start) != bool(args.end):
        p.error("--start and --end must be used together")
    return args


def targets_from_args(args):
    """Callable latest-date -> periods, so defaults can depend on each product's record."""
    as_of = None
    if args.as_of and args.as_of != "latest":
        as_of = dt.date.fromisoformat(args.as_of)
    return functools.partial(
        runner.resolve_targets,
        months=args.month or (periods.month_labels(*args.months.split(":")) if args.months else None),
        start=args.start, end=args.end,
        as_of=as_of, window_days=args.window_days if args.as_of else None,
    )


def main(argv=None):
    args = parse_args(argv)
    gee.initialize(args.project)
    baseline = tuple(int(y) for y in args.baseline.split(":")) if args.baseline else None
    for name in args.products:
        runner.run_product(
            config.PRODUCTS[name], targets_from_args(args), sat_pass=args.sat_pass, baseline=baseline,
            lst_anomaly=args.lst_anomaly, export_mode=args.export, out=args.out, png=not args.no_png,
        )


if __name__ == "__main__":
    main()
