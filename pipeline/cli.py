"""Command-line entry point.

Examples:
    python -m pipeline                                  # last complete month, SST + LST
    python -m pipeline --month 2026-09
    python -m pipeline --months 2026-01:2026-09 --products SST
    python -m pipeline --start 2026-10-01 --end 2026-10-07
    python -m pipeline --month 2026-09 --export drive
"""

import argparse
import json
import pathlib

from . import config, export, gee, periods, plot


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="GCOM-C SST/LST products for the Philippine Area of Responsibility")
    when = p.add_mutually_exclusive_group()
    when.add_argument("--month", action="append", help="Target month YYYY-MM (repeatable)")
    when.add_argument("--months", help="Inclusive month range YYYY-MM:YYYY-MM")
    when.add_argument("--start", help="Custom period start YYYY-MM-DD (use with --end)")
    p.add_argument("--end", help="Custom period end YYYY-MM-DD, inclusive")
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


def target_periods(args, latest):
    if args.month:
        return [periods.parse_month(m) for m in args.month]
    if args.months:
        return periods.month_range(*args.months.split(":"))
    if args.start:
        return [periods.custom_period(args.start, args.end)]
    return [periods.last_complete_month(latest)]


def run_product(product, args):
    sat_pass = args.sat_pass or product.default_pass
    coll = gee.collection(product, sat_pass)
    first, latest = gee.date_range(coll)
    if args.baseline:
        first_year, last_year = (int(y) for y in args.baseline.split(":"))
    else:
        first_year, last_year = first.year, latest.year
    print(f"[{product.name}] {product.collection} pass={sat_pass} record {first} -> {latest}, "
          f"baseline {first_year}-{last_year}")

    kinds = list(product.outputs)
    if product.name == "LST" and args.lst_anomaly:
        kinds.append("anomaly")

    for period in target_periods(args, latest):
        if period.start > latest:
            print(f"[{product.name}] {period.label}: no data yet (latest {latest}), skipping")
            continue
        temp, n_images = gee.composite(coll, period)
        clim, n_years = gee.climatology(coll, period, first_year, last_year)
        images = {"temperature": temp, "anomaly": gee.anomaly(temp, clim)}

        meta = {
            "product": product.long_name,
            "collection": product.collection,
            "satellite_pass": sat_pass,
            "period_start": period.start.isoformat(),
            "period_end_exclusive": period.end.isoformat(),
            "record_first": first.isoformat(),
            "record_latest": latest.isoformat(),
            "climatology_years": f"{first_year}-{last_year}",
            "units": "degC",
            "extent": "Philippine Area of Responsibility",
        }
        counts = {"n_images": n_images}
        if "anomaly" in kinds:
            counts["n_climatology_years"] = n_years
        meta.update(gee.ee.Dictionary(counts).getInfo())
        if meta["n_images"] == 0:
            print(f"[{product.name}] {period.label}: no images, skipping")
            continue
        if period.end > latest:
            meta["note"] = f"partial period: data available up to {latest}"

        for kind in kinds:
            name = f"{product.name}_{kind}_{period.label}"
            band = f"{product.name}_{kind}"
            if args.export == "drive":
                task = export.export_to_drive(images[kind], band, f"PAR_{product.name}_{kind}", name)
                print(f"[{product.name}] started Drive export {name} (task {task.id})")
                continue
            out_dir = args.out / product.name / kind
            tif = export.download_geotiff(images[kind], band, out_dir / f"{name}.tif", {**meta, "output": kind})
            (out_dir / f"{name}.json").write_text(json.dumps({**meta, "output": kind}, indent=2))
            msg = f"[{product.name}] wrote {tif}"
            if not args.no_png:
                title = f"{product.long_name} {'anomaly ' if kind == 'anomaly' else ''}— {period.label}\n" \
                        f"GCOM-C/SGLI, pass={sat_pass}"
                if kind == "anomaly":
                    title += f", vs {first_year}-{last_year} climatology"
                png = plot.quicklook(tif, tif.with_suffix(".png"), kind, product, title)
                msg += f" (+ {png.name})"
            print(msg)


def main(argv=None):
    args = parse_args(argv)
    gee.initialize(args.project)
    for name in args.products:
        run_product(config.PRODUCTS[name], args)


if __name__ == "__main__":
    main()
