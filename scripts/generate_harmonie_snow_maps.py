#!/usr/bin/env python3
"""Generate Denmark/Scandinavia snow water equivalent maps from DMI HARMONIE DINI surface GRIB data."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib
import numpy as np
from eccodes import (
    codes_get,
    codes_get_array,
    codes_grib_new_from_file,
    codes_release,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from matplotlib.colors import BoundaryNorm, ListedColormap

BASE = "https://opendataapi.dmi.dk/v1/forecastdata"
COLLECTION = "harmonie_dini_sf"
OUTPUT_DIR = Path("data/dmi_snow")

# Denmark plus southern Scandinavia, matching the intended winter view.
EXTENT = (5.0, 18.5, 53.5, 61.5)
DK_BOX = (7.7, 15.4, 54.4, 57.9)

STEP_HOURS = 3
MAX_FORECAST_HOURS = 54
MIN_COMPLETE_STEPS = 45

SNOW_SHORTNAMES = {"sdwe"}


def get_json(url: str):
    req = Request(url, headers={"User-Agent": "strandvejr.dk DMI snow maps/1.0"})
    with urlopen(req, timeout=90) as response:
        return json.load(response)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def find_latest_complete_run():
    endpoint = f"{BASE}/collections/{COLLECTION}/items"
    data = get_json(endpoint + "?" + urlencode({"limit": 1000}))
    groups = defaultdict(list)

    for feature in data.get("features", []):
        run = feature.get("properties", {}).get("modelRun")
        if run:
            groups[run].append(feature)

    for run, features in sorted(groups.items(), key=lambda item: item[0], reverse=True):
        valid = {
            f.get("properties", {}).get("datetime")
            for f in features
            if f.get("properties", {}).get("datetime")
        }
        if len(valid) >= MIN_COMPLETE_STEPS:
            return run, features

    raise RuntimeError("No sufficiently complete HARMONIE run found")


def selected_items(model_run, features):
    run_dt = parse_dt(model_run)
    selected = []

    for feature in features:
        valid = feature.get("properties", {}).get("datetime")
        href = feature.get("asset", {}).get("data", {}).get("href")
        if not valid or not href:
            continue

        lead = round((parse_dt(valid) - run_dt).total_seconds() / 3600)
        if 0 <= lead <= MAX_FORECAST_HOURS and lead % STEP_HOURS == 0:
            selected.append((lead, feature))

    selected.sort(key=lambda item: item[0])
    return selected


def download(url: str, destination: Path, attempts: int = 4):
    req = Request(url, headers={"User-Agent": "strandvejr.dk DMI snow maps/1.0"})

    for attempt in range(1, attempts + 1):
        try:
            with urlopen(req, timeout=120) as response, destination.open("wb") as target:
                shutil.copyfileobj(response, target)
            if destination.stat().st_size < 10000:
                raise RuntimeError("Downloaded GRIB is unexpectedly small")
            return
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            destination.unlink(missing_ok=True)
            if attempt == attempts:
                raise
            time.sleep(attempt * 5)


def safe_get(gid, key, default=None):
    try:
        return codes_get(gid, key)
    except Exception:
        return default


def is_snow_water_equivalent_message(gid) -> bool:
    short_name = str(safe_get(gid, "shortName", "")).lower()
    name = str(safe_get(gid, "name", "")).lower()
    cf_name = str(safe_get(gid, "cfName", "")).lower()

    if short_name in SNOW_SHORTNAMES:
        return True

    combined = f"{name} {cf_name}"
    return "snow depth water equivalent" in combined


def read_snow_water_equivalent(path: Path):
    with path.open("rb") as fh:
        while True:
            gid = codes_grib_new_from_file(fh)
            if gid is None:
                break

            try:
                if not is_snow_water_equivalent_message(gid):
                    continue

                values = np.asarray(codes_get_array(gid, "values"), dtype=float)
                lats = np.asarray(codes_get_array(gid, "latitudes"), dtype=float)
                lons = np.asarray(codes_get_array(gid, "longitudes"), dtype=float)
                units = str(safe_get(gid, "units", ""))

                # DMI HARMONIE sdwe is kg m**-2. Numerically this equals
                # millimetres of liquid water equivalent.
                swe_mm = np.maximum(values, 0.0)

                return lons, lats, swe_mm, {
                    "shortName": str(safe_get(gid, "shortName", "")),
                    "name": str(safe_get(gid, "name", "")),
                    "units": units,
                }
            finally:
                codes_release(gid)

    raise RuntimeError("No snow depth water equivalent field (sdwe) found in HARMONIE GRIB")


def snow_scale():
    levels = np.array([0.5, 1, 2, 3, 5, 7, 10, 20, 30, 50, 70, 100, 200, 400], dtype=float)
    colors = [
        "#fbf7ff", "#f1e5ff", "#e5d1fa", "#d6baf4", "#c49de9",
        "#ae7cda", "#965aca", "#7e3bb6", "#67249d", "#531783",
        "#401069", "#2f0c51", "#21083d",
    ]
    return levels, ListedColormap(colors, name="dmi_snow_water_equivalent")



def add_value_labels(ax, lons, lats, values):
    """Add readable, spatially thinned snow values to the map."""
    mask = (
        np.isfinite(values)
        & (values >= 1.0)
        & (lons >= EXTENT[0]) & (lons <= EXTENT[1])
        & (lats >= EXTENT[2]) & (lats <= EXTENT[3])
    )

    if not np.any(mask):
        return

    label_lons = lons[mask]
    label_lats = lats[mask]
    label_values = values[mask]

    # One representative value per geographic cell keeps the native
    # HARMONIE grid readable instead of printing thousands of numbers.
    lon_step = 0.60
    lat_step = 0.45
    cells = {}

    for lon, lat, value in zip(label_lons, label_lats, label_values):
        key = (
            int(math.floor((lon - EXTENT[0]) / lon_step)),
            int(math.floor((lat - EXTENT[2]) / lat_step)),
        )

        current = cells.get(key)
        # Keep the highest value in each cell. This highlights the
        # meaningful snow maxima without creating excessive label density.
        if current is None or value > current[2]:
            cells[key] = (float(lon), float(lat), float(value))

    for lon, lat, value in cells.values():
        text = ax.text(
            lon,
            lat,
            f"{value:.0f}",
            transform=ccrs.PlateCarree(),
            ha="center",
            va="center",
            fontsize=6.6,
            color="#2b173a",
            fontweight="bold",
            zorder=8,
        )
        text.set_path_effects([
            path_effects.Stroke(linewidth=2.0, foreground="white", alpha=0.9),
            path_effects.Normal(),
        ])



def render_map(lons, lats, swe_mm, run_dt, valid_dt, lead, destination):
    levels, cmap = snow_scale()
    norm = BoundaryNorm(levels, cmap.N)

    mask = (
        (lons >= EXTENT[0]) & (lons <= EXTENT[1]) &
        (lats >= EXTENT[2]) & (lats <= EXTENT[3])
    )
    if not np.any(mask):
        raise RuntimeError("No HARMONIE snow grid points inside map extent")

    x = lons[mask]
    y = lats[mask]
    z = swe_mm[mask]

    dk = (
        (lons >= DK_BOX[0]) & (lons <= DK_BOX[1]) &
        (lats >= DK_BOX[2]) & (lats <= DK_BOX[3])
    )
    max_dk = float(np.nanmax(swe_mm[dk])) if np.any(dk) else float("nan")

    fig = plt.figure(figsize=(9.5, 7.2), dpi=140, facecolor="white")
    ax = fig.add_axes((0.06, 0.12, 0.82, 0.80), projection=ccrs.PlateCarree())
    ax.set_extent(EXTENT, crs=ccrs.PlateCarree())

    # HARMONIE uses a curvilinear high resolution grid. Triangulated contouring
    # preserves the native point density without reducing it to the 0.1 degree web grid.
    field = ax.tricontourf(
        x, y, z,
        levels=levels,
        cmap=cmap,
        norm=norm,
        extend="max",
        transform=ccrs.PlateCarree(),
    )

    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor="#efefdc", zorder=0)
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="#ffffff", zorder=0)
    ax.add_feature(cfeature.COASTLINE.with_scale("10m"), linewidth=0.7, edgecolor="#9ca3af", zorder=5)
    ax.add_feature(cfeature.BORDERS.with_scale("10m"), linewidth=0.55, edgecolor="#555555", linestyle=":", zorder=5)

    # Add numeric values directly on the map, similar to DMI's own snow maps.
    add_value_labels(ax, lons, lats, swe_mm)

    cax = fig.add_axes((0.89, 0.16, 0.024, 0.70))
    cb = fig.colorbar(field, cax=cax, ticks=levels)
    cb.set_label("Snevandækvivalent (mm)", fontsize=8)
    cb.ax.tick_params(labelsize=7)

    fig.text(0.06, 0.955, "Snevandækvivalent (mm)", fontsize=12, weight="bold")
    fig.text(0.06, 0.925, "DMI HARMONIE DINI · ca. 2 km", fontsize=8.5, color="#444444")
    fig.text(0.48, 0.935, f"+{lead:03d}H", fontsize=11, weight="bold", ha="center")

    fig.text(
        0.06, 0.885,
        f"Max DK: {max_dk:.1f} mm" if np.isfinite(max_dk) else "Max DK: –",
        fontsize=8.5, weight="bold",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#bbbbbb"},
    )

    fig.text(0.88, 0.955, f"Gyldig: {valid_dt:%d.%m.%Y %H} UTC", fontsize=8, ha="right")
    fig.text(0.88, 0.925, f"Kørsel: {run_dt:%d.%m.%Y %H} UTC", fontsize=8, ha="right")
    fig.text(0.88, 0.085, "Kort © Vejrstation Sortsø Strand", fontsize=7, color="#333333", ha="right")

    fig.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)

    return round(max_dk, 1) if np.isfinite(max_dk) else None


def main():
    model_run, features = find_latest_complete_run()
    run_dt = parse_dt(model_run)
    items = selected_items(model_run, features)

    if not items:
        raise RuntimeError("No forecast steps selected")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for old in OUTPUT_DIR.glob("snow_water_f*.png"):
        old.unlink()

    products = []
    field_meta = None

    with tempfile.TemporaryDirectory(prefix="dmi_snow_") as tmp_name:
        tmp_dir = Path(tmp_name)

        for index, (lead, item) in enumerate(items, 1):
            props = item.get("properties", {})
            valid = props.get("datetime")
            href = item.get("asset", {}).get("data", {}).get("href")
            if not valid or not href:
                continue

            grib = tmp_dir / f"f{lead:03d}.grib2"
            print(f"[{index}/{len(items)}] Downloading +{lead:03d}h")
            download(href, grib)

            lons, lats, swe_mm, meta = read_snow_water_equivalent(grib)
            if field_meta is None:
                field_meta = meta
                print(f"Snow field: {meta}")

            filename = f"snow_water_f{lead:03d}.png"
            valid_dt = parse_dt(valid)
            max_dk = render_map(
                lons, lats, swe_mm,
                run_dt, valid_dt, lead,
                OUTPUT_DIR / filename,
            )

            products.append({
                "step_hours": lead,
                "valid_utc": valid_dt.isoformat(),
                "file": filename,
                "max_denmark_mm": max_dk,
            })

    manifest = {
        "source": "DMI Forecast Data STAC API",
        "model": "HARMONIE DINI surface",
        "collection": COLLECTION,
        "run_utc": run_dt.isoformat(),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "interval_hours": STEP_HOURS,
        "horizon_hours": MAX_FORECAST_HOURS,
        "parameter": {
            "title": "Snevandækvivalent",
            "unit": "mm",
            "grib": field_meta,
        },
        "products": products,
    }

    (OUTPUT_DIR / "snow_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Generated {len(products)} DMI HARMONIE snow depth maps")


if __name__ == "__main__":
    main()
