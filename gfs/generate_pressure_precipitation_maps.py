#!/usr/bin/env python3
"""Render European GFS maps with 6 hour precipitation and sea level pressure."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cfgrib
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
BASE_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
EXTENT = (-12.0, 38.0, 35.0, 72.0)
DEFAULT_STEPS = tuple(range(6, 121, 6))


def latest_candidate_runs(now: datetime) -> list[datetime]:
    available = now - timedelta(hours=5)
    cycle_hour = (available.hour // 6) * 6
    first = available.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)
    return [first - timedelta(hours=6 * offset) for offset in range(5)]


def subset_url(run: datetime, step: int) -> str:
    query = {
        "file": f"gfs.t{run:%H}z.pgrb2.0p25.f{step:03d}",
        "lev_mean_sea_level": "on",
        "lev_surface": "on",
        "var_PRMSL": "on",
        "var_APCP": "on",
        "subregion": "",
        "leftlon": str(EXTENT[0]),
        "rightlon": str(EXTENT[1]),
        "toplat": str(EXTENT[3]),
        "bottomlat": str(EXTENT[2]),
        "dir": f"/gfs.{run:%Y%m%d}/{run:%H}/atmos",
    }
    return f"{BASE_URL}?{urlencode(query)}"


def download(url: str, destination: Path, attempts: int = 4) -> None:
    request = Request(url, headers={"User-Agent": "strandvejr.dk GFS map generator"})
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=120) as response, destination.open("wb") as target:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                shutil.copyfileobj(response, target)
            if destination.stat().st_size < 10_000:
                raise RuntimeError("NOAA response was unexpectedly small")
            return
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            destination.unlink(missing_ok=True)
            if attempt == attempts:
                raise RuntimeError(f"Could not download {url}: {exc}") from exc
            time.sleep(attempt * 5)


def select_run(now: datetime, work_dir: Path) -> tuple[datetime, Path]:
    probe = work_dir / "probe.grib2"
    errors = []
    for run in latest_candidate_runs(now):
        try:
            download(subset_url(run, 6), probe, attempts=2)
            return run, probe
        except RuntimeError as exc:
            errors.append(str(exc))
    raise RuntimeError("No recent GFS cycle was available. " + " | ".join(errors))


def read_fields(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    datasets = cfgrib.open_datasets(path, backend_kwargs={"indexpath": ""})
    pressure = None
    precipitation = None
    latitudes = None
    longitudes = None

    for dataset in datasets:
        if "prmsl" in dataset.data_vars:
            pressure = np.asarray(dataset["prmsl"].values, dtype=float) / 100.0
            latitudes = np.asarray(dataset.latitude.values)
            longitudes = np.asarray(dataset.longitude.values)
        for name in ("tp", "apcp"):
            if name in dataset.data_vars:
                precipitation = np.asarray(dataset[name].values, dtype=float)
                latitudes = np.asarray(dataset.latitude.values)
                longitudes = np.asarray(dataset.longitude.values)

    if pressure is None or precipitation is None or latitudes is None or longitudes is None:
        available = sorted({name for dataset in datasets for name in dataset.data_vars})
        raise RuntimeError(f"Missing pressure or precipitation in GRIB. Available fields: {available}")

    longitudes = np.where(longitudes > 180, longitudes - 360, longitudes)
    precipitation = np.maximum(precipitation, 0.0)
    return longitudes, latitudes, pressure, precipitation


def precipitation_scale() -> tuple[ListedColormap, np.ndarray]:
    levels = np.array([0.1, 0.5, 1, 2, 4, 7, 10, 15, 20, 30, 50, 75])
    colors = [
        "#d8f2ff", "#9bdcff", "#4eb7f2", "#1687d1", "#52c878",
        "#a9db4d", "#f3df38", "#f7a72b", "#ef642f", "#d52d3f", "#9d1a67",
    ]
    return ListedColormap(colors, name="strandvejr_precipitation"), levels


def render_map(grib: Path, run: datetime, step: int, destination: Path) -> None:
    longitudes, latitudes, pressure, precipitation = read_fields(grib)
    cmap, rain_levels = precipitation_scale()
    norm = BoundaryNorm(rain_levels, cmap.N)

    figure = plt.figure(figsize=(8, 7.15), dpi=140, facecolor="white")
    axis = figure.add_axes((0.055, 0.105, 0.80, 0.85), projection=ccrs.PlateCarree())
    axis.set_extent(EXTENT, crs=ccrs.PlateCarree())
    rain = axis.contourf(
        longitudes, latitudes, precipitation,
        levels=rain_levels, cmap=cmap, norm=norm, extend="max",
        transform=ccrs.PlateCarree(),
    )
    pressure_levels = np.arange(940, 1065, 4)
    isobars = axis.contour(
        longitudes, latitudes, pressure,
        levels=pressure_levels, colors="#161616", linewidths=0.75,
        transform=ccrs.PlateCarree(),
    )
    axis.clabel(isobars, inline=True, fontsize=7, fmt="%d")
    axis.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.65, edgecolor="#202020")
    axis.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.45, edgecolor="#454545")
    grid = axis.gridlines(draw_labels=True, linewidth=0.45, color="#82939d", alpha=0.65, linestyle=(0, (2, 4)))
    grid.top_labels = False
    grid.right_labels = False
    grid.xlabel_style = {"size": 7}
    grid.ylabel_style = {"size": 7}

    color_axis = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    colorbar = figure.colorbar(rain, cax=color_axis, ticks=rain_levels)
    colorbar.set_label("Nedbør 6 timer, mm", fontsize=8)
    colorbar.ax.tick_params(labelsize=7)

    valid = run + timedelta(hours=step)
    figure.text(0.055, 0.105, "Lufttryk og nedbør", fontsize=12, weight="bold")
    figure.text(0.055, 0.072, f"Data: NOAA GFS 0,25°, kørsel {run:%d.%m.%Y kl. %H} UTC", fontsize=8)
    figure.text(0.855, 0.105, "Kort © Vejrstation Sortsø Strand", fontsize=7, color="#222222", ha="right")
    figure.text(0.855, 0.072, f"Gyldig: {valid:%d.%m.%Y kl. %H} UTC", fontsize=8, ha="right")
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def parse_steps(value: str) -> tuple[int, ...]:
    steps = tuple(sorted({int(item) for item in value.split(",") if item.strip()}))
    if not steps or min(steps) < 1 or max(steps) > 384:
        raise argparse.ArgumentTypeError("Steps must be comma separated values from 1 to 384")
    return steps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=parse_steps, default=DEFAULT_STEPS)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)

    with tempfile.TemporaryDirectory(prefix="gfs_pressure_rain_") as temp_name:
        temp_dir = Path(temp_name)
        run, probe = select_run(now, temp_dir)
        products = []
        args.output.mkdir(parents=True, exist_ok=True)

        for old_map in args.output.glob("pressure_precipitation_f*.png"):
            old_map.unlink()

        for step in args.steps:
            grib = probe if step == 6 else temp_dir / f"gfs_pressure_rain_f{step:03d}.grib2"
            if step != 6:
                download(subset_url(run, step), grib)
            filename = f"pressure_precipitation_f{step:03d}.png"
            render_map(grib, run, step, args.output / filename)
            products.append({
                "step_hours": step,
                "valid_utc": (run + timedelta(hours=step)).isoformat(),
                "file": filename,
            })

        manifest = {
            "source": "NOAA GFS 0.25 degree",
            "parameters": ["mean sea level pressure", "6 hour accumulated precipitation"],
            "run_utc": run.isoformat(),
            "generated_utc": now.isoformat(),
            "extent": {"west": EXTENT[0], "east": EXTENT[1], "south": EXTENT[2], "north": EXTENT[3]},
            "products": products,
        }
        manifest_path = args.output / "pressure_precipitation_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Generated {len(products)} pressure and precipitation maps from GFS run {run:%Y%m%d %H} UTC")


if __name__ == "__main__":
    main()
