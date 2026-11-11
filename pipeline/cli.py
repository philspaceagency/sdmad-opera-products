"""Command-line entry point.

Examples:
    python -m pipeline --start 2026-10-01 --end 2026-10-15
    python -m pipeline --start 2026-09-01 --end 2026-10-31          # only what is missing is processed
    python -m pipeline --start 2026-09-01 --end 2026-09-30 --products SST --sst-pass N
    python -m pipeline --start 2026-01-01 --end 2026-09-30 --products LST --lst-platform terra
"""

import argparse
import pathlib

from . import config, gee, mpc, runner


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="GCOM-C SST / MODIS LST for the Philippine Area of Responsibility")
    p.add_argument("--start", required=True, help="First day, YYYY-MM-DD")
    p.add_argument("--end", required=True, help="Last day (inclusive), YYYY-MM-DD")
    p.add_argument("--products", nargs="+", default=list(config.PRODUCTS), choices=list(config.PRODUCTS))
    p.add_argument("--sst-pass", choices=list(config.SST.passes), default=config.SST.default_pass,
                   help="GCOM-C pass for SST (default: both)")
    p.add_argument("--lst-pass", choices=list(config.LST.passes), default=config.LST.default_pass,
                   help="MODIS LST day (D) or night (N) (default: D)")
    p.add_argument("--lst-platform", choices=["both", *config.MODIS_PLATFORMS], default=config.MODIS_DEFAULT_PLATFORM,
                   help="MODIS platform(s) for LST (default: both, each against its own climatology)")
    p.add_argument("--baseline", default=f"{config.BASELINE[0]}:{config.BASELINE[1]}",
                   help="Climatology years FIRST:LAST, inclusive (default: %(default)s)")
    p.add_argument("--out", default="outputs", type=pathlib.Path, help="Output root")
    p.add_argument("--cache", default="cache", type=pathlib.Path,
                   help="Planetary Computer search + MODIS composite cache (makes LST reruns cheap)")
    p.add_argument("--no-png", action="store_true", help="Skip PNG quicklooks")
    p.add_argument("--no-gif", action="store_true", help="Skip the GIF of the range")
    p.add_argument("--gif-fps", type=float, default=4)
    p.add_argument("--project", default=config.GEE_PROJECT)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if "SST" in args.products:
        gee.initialize(args.project)
    mpc.set_cache_dir(args.cache)
    baseline = tuple(int(y) for y in args.baseline.split(":"))
    passes = {"SST": args.sst_pass, "LST": args.lst_pass}
    for name in args.products:
        runner.run_range(
            config.PRODUCTS[name], args.start, args.end, sat_pass=passes[name], baseline=baseline,
            platform=args.lst_platform, out=args.out, png=not args.no_png, gif=not args.no_gif,
            gif_fps=args.gif_fps,
        )


if __name__ == "__main__":
    main()
