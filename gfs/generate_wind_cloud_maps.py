#!/usr/bin/env python3
"""Render European GFS maps for 10 m wind and total cloud cover."""

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
DEFAULT_STEPS = tuple(range(0, 121, 6))


def latest_candidate_runs(now: datetime) -> list[datetime]:
    available = now - timedelta(hours=5)
    cycle_hour = (available.hour // 6) * 6
    first = available.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)
    return [first - timedelta(hours=6 * offset) for offset in range(5)]


def subset_url(run: datetime, step: int) -> str:
    query = {
        "file": f"gfs.t{run:%H}z.pgrb2.0p25.f{step:03d}",
        "lev_10_m_above_ground": "on",
        "lev_entire_atmosphere": "on",
        "var_UGRD": "on",
        "var_VGRD": "on",
        "var_TCDC": "on",
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
            download(subset_url(run, 0), probe, attempts=2)
            return run, probe
        except RuntimeError as exc:
            errors.append(str(exc))
    raise RuntimeError("No recent GFS cycle was available. " + " | ".join(errors))


def read_fields(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    datasets = cfgrib.open_datasets(path, backend_kwargs={"indexpath": ""})
    u_wind = None
    v_wind = None
    cloud = None
    latitudes = None
    longitudes = None

    for dataset in datasets:
        if "u10" in dataset.data_vars:
            u_wind = np.asarray(dataset["u10"].values, dtype=float)
            latitudes = np.asarray(dataset.latitude.values)
            longitudes = np.asarray(dataset.longitude.values)
        if "v10" in dataset.data_vars:
            v_wind = np.asarray(dataset["v10"].values, dtype=float)
            latitudes = np.asarray(dataset.latitude.values)
            longitudes = np.asarray(dataset.longitude.values)
        for name in ("tcc", "tcdc"):
            if name in dataset.data_vars:
                cloud = np.asarray(dataset[name].values, dtype=float)

    if u_wind is None or v_wind is None or cloud is None or latitudes is None or longitudes is None:
        available = sorted({name for dataset in datasets for name in dataset.data_vars})
        raise RuntimeError(f"Missing wind or cloud data in GRIB. Available fields: {available}")

    longitudes = np.where(longitudes > 180, longitudes - 360, longitudes)
    cloud = np.clip(cloud, 0.0, 100.0)
    return longitudes, latitudes, u_wind, v_wind, cloud


def add_geography(axis) -> None:
    axis.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.65, edgecolor="#202020")
    axis.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.45, edgecolor="#454545")
    grid = axis.gridlines(draw_labels=True, linewidth=0.45, color="#82939d", alpha=0.65, linestyle=(0, (2, 4)))
    grid.top_labels = False
    grid.right_labels = False
    grid.xlabel_style = {"size": 7}
    grid.ylabel_style = {"size": 7}


def add_footer(figure, title: str, run: datetime, step: int) -> None:
    valid = run + timedelta(hours=step)
    figure.text(0.055, 0.105, title, fontsize=12, weight="bold")
    figure.text(0.055, 0.072, f"Data: NOAA GFS 0,25°, kørsel {run:%d.%m.%Y kl. %H} UTC", fontsize=8)
    figure.text(0.855, 0.105, "Kort © Vejrstation Sortsø Strand", fontsize=7, color="#222222", ha="right")
    figure.text(0.855, 0.072, f"Gyldig: {valid:%d.%m.%Y kl. %H} UTC", fontsize=8, ha="right")


def render_wind(longitudes, latitudes, u_wind, v_wind, run: datetime, step: int, destination: Path) -> None:
    speed = np.hypot(u_wind, v_wind)
    levels = np.array([0, 2, 4, 6, 8, 10, 12, 15, 18, 22, 26, 30, 36])
    colors = [
        "#e8f5ff", "#b9e2fa", "#79c6e8", "#3ba7cf", "#55bd83", "#a5d65c",
        "#e5df45", "#f5b43b", "#ed7b32", "#dc4338", "#a72d62", "#76278e",
    ]
    cmap = ListedColormap(colors, name="strandvejr_wind")
    norm = BoundaryNorm(levels, cmap.N)
    figure = plt.figure(figsize=(8, 7.15), dpi=140, facecolor="white")
    axis = figure.add_axes((0.055, 0.105, 0.80, 0.85), projection=ccrs.PlateCarree())
    axis.set_extent(EXTENT, crs=ccrs.PlateCarree())
    field = axis.contourf(longitudes, latitudes, speed, levels=levels, cmap=cmap, norm=norm, extend="max", transform=ccrs.PlateCarree())
    stride = 8
    axis.quiver(
        longitudes[::stride], latitudes[::stride], u_wind[::stride, ::stride], v_wind[::stride, ::stride],
        transform=ccrs.PlateCarree(), color="#202020", scale=420, width=0.0015,
        headwidth=3.5, headlength=4.5, headaxislength=4.0, alpha=0.8,
    )
    add_geography(axis)
    color_axis = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    colorbar = figure.colorbar(field, cax=color_axis, ticks=levels)
    colorbar.set_label("Vind 10 m, m/s", fontsize=8)
    colorbar.ax.tick_params(labelsize=7)
    add_footer(figure, "Vind 10 m", run, step)
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def render_cloud(longitudes, latitudes, cloud, run: datetime, step: int, destination: Path) -> None:
    levels = np.arange(0, 110, 10)
    colors = ["#fff8d9", "#f2f1dc", "#e3e9e8", "#d2dfe3", "#bed3da", "#a9c4cf", "#8faeba", "#748f9e", "#586e7c", "#3b4a59"]
    cmap = ListedColormap(colors, name="strandvejr_cloud")
    norm = BoundaryNorm(levels, cmap.N)
    figure = plt.figure(figsize=(8, 7.15), dpi=140, facecolor="white")
    axis = figure.add_axes((0.055, 0.105, 0.80, 0.85), projection=ccrs.PlateCarree())
    axis.set_extent(EXTENT, crs=ccrs.PlateCarree())
    field = axis.contourf(longitudes, latitudes, cloud, levels=levels, cmap=cmap, norm=norm, extend="neither", transform=ccrs.PlateCarree())
    add_geography(axis)
    color_axis = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    colorbar = figure.colorbar(field, cax=color_axis, ticks=levels)
    colorbar.set_label("Samlet skydække, procent", fontsize=8)
    colorbar.ax.tick_params(labelsize=7)
    add_footer(figure, "Samlet skydække", run, step)
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def parse_steps(value: str) -> tuple[int, ...]:
    steps = tuple(sorted({int(item) for item in value.split(",") if item.strip()}))
    if not steps or min(steps) < 0 or max(steps) > 384:
        raise argparse.ArgumentTypeError("Steps must be comma separated values from 0 to 384")
    return steps


def write_manifest(output: Path, filename: str, source_parameter: str, run: datetime, now: datetime, products: list[dict]) -> None:
    manifest = {
        "source": "NOAA GFS 0.25 degree",
        "parameter": source_parameter,
        "run_utc": run.isoformat(),
        "generated_utc": now.isoformat(),
        "extent": {"west": EXTENT[0], "east": EXTENT[1], "south": EXTENT[2], "north": EXTENT[3]},
        "products": products,
    }
    (output / filename).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=parse_steps, default=DEFAULT_STEPS)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)

    with tempfile.TemporaryDirectory(prefix="gfs_wind_cloud_") as temp_name:
        temp_dir = Path(temp_name)
        run, probe = select_run(now, temp_dir)
        args.output.mkdir(parents=True, exist_ok=True)
        for pattern in ("wind_f*.png", "cloud_f*.png"):
            for old_map in args.output.glob(pattern):
                old_map.unlink()
        wind_products = []
        cloud_products = []

        for step in args.steps:
            grib = probe if step == 0 else temp_dir / f"gfs_wind_cloud_f{step:03d}.grib2"
            if step != 0:
                download(subset_url(run, step), grib)
            longitudes, latitudes, u_wind, v_wind, cloud = read_fields(grib)
            wind_filename = f"wind_f{step:03d}.png"
            cloud_filename = f"cloud_f{step:03d}.png"
            render_wind(longitudes, latitudes, u_wind, v_wind, run, step, args.output / wind_filename)
            render_cloud(longitudes, latitudes, cloud, run, step, args.output / cloud_filename)
            common = {"step_hours": step, "valid_utc": (run + timedelta(hours=step)).isoformat()}
            wind_products.append({**common, "file": wind_filename})
            cloud_products.append({**common, "file": cloud_filename})

        write_manifest(args.output, "wind_manifest.json", "10 m wind", run, now, wind_products)
        write_manifest(args.output, "cloud_manifest.json", "total cloud cover", run, now, cloud_products)
        print(f"Generated {len(wind_products)} wind maps and {len(cloud_products)} cloud maps from GFS run {run:%Y%m%d %H} UTC")


if __name__ == "__main__":
    main()
