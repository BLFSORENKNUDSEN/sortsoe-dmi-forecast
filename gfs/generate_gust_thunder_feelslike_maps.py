#!/usr/bin/env python3
"""Render European GFS maps for gusts, thunder potential and feels like temperature."""

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
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap

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
        "lev_surface": "on",
        "lev_2_m_above_ground": "on",
        "lev_10_m_above_ground": "on",
        "var_GUST": "on",
        "var_CAPE": "on",
        "var_CIN": "on",
        "var_TMP": "on",
        "var_RH": "on",
        "var_UGRD": "on",
        "var_VGRD": "on",
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


def read_fields(path: Path) -> dict[str, np.ndarray]:
    datasets = cfgrib.open_datasets(path, backend_kwargs={"indexpath": ""})
    fields: dict[str, np.ndarray] = {}
    latitudes = None
    longitudes = None

    aliases = {
        "gust": "gust",
        "cape": "cape",
        "cin": "cin",
        "t2m": "temperature",
        "r2": "humidity",
        "u10": "u_wind",
        "v10": "v_wind",
    }
    for dataset in datasets:
        for source_name, target_name in aliases.items():
            if source_name in dataset.data_vars:
                fields[target_name] = np.asarray(dataset[source_name].values, dtype=float)
                if hasattr(dataset, "latitude") and hasattr(dataset, "longitude"):
                    latitudes = np.asarray(dataset.latitude.values)
                    longitudes = np.asarray(dataset.longitude.values)

    required = {"gust", "cape", "temperature", "humidity", "u_wind", "v_wind"}
    missing = sorted(required.difference(fields))
    if missing or latitudes is None or longitudes is None:
        available = sorted({name for dataset in datasets for name in dataset.data_vars})
        raise RuntimeError(f"Missing GFS fields {missing}. Available fields: {available}")

    fields["latitude"] = latitudes
    fields["longitude"] = np.where(longitudes > 180, longitudes - 360, longitudes)
    fields["temperature"] = fields["temperature"] - 273.15
    fields["cape"] = np.maximum(fields["cape"], 0.0)
    return fields


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


def base_figure():
    figure = plt.figure(figsize=(8, 7.15), dpi=140, facecolor="white")
    axis = figure.add_axes((0.055, 0.105, 0.80, 0.85), projection=ccrs.PlateCarree())
    axis.set_extent(EXTENT, crs=ccrs.PlateCarree())
    return figure, axis


def render_gust(fields: dict[str, np.ndarray], run: datetime, step: int, destination: Path) -> None:
    levels = np.array([0, 5, 8, 10, 12, 15, 18, 22, 26, 30, 35, 40, 50])
    colors = ["#eef8ff", "#bfe5fa", "#7cc9ea", "#3aa8d1", "#54bd82", "#a3d653", "#e4df43", "#f4b13a", "#ed7832", "#da413b", "#a52c63", "#76268e"]
    cmap = ListedColormap(colors, name="strandvejr_gust")
    figure, axis = base_figure()
    field = axis.contourf(fields["longitude"], fields["latitude"], fields["gust"], levels=levels, cmap=cmap, norm=BoundaryNorm(levels, cmap.N), extend="max", transform=ccrs.PlateCarree())
    add_geography(axis)
    color_axis = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    colorbar = figure.colorbar(field, cax=color_axis, ticks=levels)
    colorbar.set_label("Vindstød, m/s", fontsize=8)
    colorbar.ax.tick_params(labelsize=7)
    add_footer(figure, "Vindstød", run, step)
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def render_thunder(fields: dict[str, np.ndarray], run: datetime, step: int, destination: Path) -> None:
    cape = fields["cape"]
    if "cin" in fields:
        cape = cape * np.exp(-np.abs(np.minimum(fields["cin"], 0.0)) / 200.0)
    levels = np.array([25, 100, 300, 600, 1000, 1500, 2500, 3500, 5000])
    colors = ["#d9f0ff", "#8cd1f2", "#47b879", "#b5d94e", "#f2dc3e", "#f4a032", "#e45138", "#a32369"]
    cmap = ListedColormap(colors, name="strandvejr_thunder")
    figure, axis = base_figure()
    field = axis.contourf(fields["longitude"], fields["latitude"], cape, levels=levels, cmap=cmap, norm=BoundaryNorm(levels, cmap.N), extend="max", transform=ccrs.PlateCarree())
    add_geography(axis)
    color_axis = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    colorbar = figure.colorbar(field, cax=color_axis, ticks=levels)
    colorbar.set_label("Tordenpotentiale, J/kg", fontsize=8)
    colorbar.ax.tick_params(labelsize=7)
    add_footer(figure, "Tordenrisiko", run, step)
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def feels_like_temperature(temperature: np.ndarray, humidity: np.ndarray, wind_ms: np.ndarray) -> np.ndarray:
    result = temperature.copy()
    wind_kmh = wind_ms * 3.6
    wind_chill = 13.12 + 0.6215 * temperature - 11.37 * np.power(np.maximum(wind_kmh, 0.1), 0.16) + 0.3965 * temperature * np.power(np.maximum(wind_kmh, 0.1), 0.16)
    cold_mask = (temperature <= 10.0) & (wind_kmh >= 4.8)
    result = np.where(cold_mask, wind_chill, result)

    temp_f = temperature * 9.0 / 5.0 + 32.0
    heat_f = (
        -42.379 + 2.04901523 * temp_f + 10.14333127 * humidity
        - 0.22475541 * temp_f * humidity - 0.00683783 * temp_f * temp_f
        - 0.05481717 * humidity * humidity + 0.00122874 * temp_f * temp_f * humidity
        + 0.00085282 * temp_f * humidity * humidity - 0.00000199 * temp_f * temp_f * humidity * humidity
    )
    heat_c = (heat_f - 32.0) * 5.0 / 9.0
    heat_mask = (temperature >= 27.0) & (humidity >= 40.0)
    return np.where(heat_mask, heat_c, result)


def render_feels_like(fields: dict[str, np.ndarray], run: datetime, step: int, destination: Path) -> None:
    wind_speed = np.hypot(fields["u_wind"], fields["v_wind"])
    feels_like = feels_like_temperature(fields["temperature"], fields["humidity"], wind_speed)
    levels = np.arange(-35, 41, 2.5)
    colors = ["#6a1b9a", "#2447a5", "#168bcc", "#8ad5f5", "#e6f5f2", "#b9e77d", "#f2e63c", "#f8a532", "#ec4b36", "#a80f4f"]
    cmap = LinearSegmentedColormap.from_list("strandvejr_feels_like", colors, N=len(levels) - 1)
    figure, axis = base_figure()
    field = axis.contourf(fields["longitude"], fields["latitude"], feels_like, levels=levels, cmap=cmap, norm=BoundaryNorm(levels, cmap.N), extend="both", transform=ccrs.PlateCarree())
    contours = axis.contour(fields["longitude"], fields["latitude"], feels_like, levels=np.arange(-30, 41, 5), colors="#303030", linewidths=0.4, alpha=0.65, transform=ccrs.PlateCarree())
    axis.clabel(contours, inline=True, fontsize=6, fmt="%d")
    add_geography(axis)
    color_axis = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    colorbar = figure.colorbar(field, cax=color_axis, ticks=np.arange(-30, 41, 5))
    colorbar.set_label("Oplevet temperatur, Celsius", fontsize=8)
    colorbar.ax.tick_params(labelsize=7)
    add_footer(figure, "Oplevet temperatur", run, step)
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def parse_steps(value: str) -> tuple[int, ...]:
    steps = tuple(sorted({int(item) for item in value.split(",") if item.strip()}))
    if not steps or min(steps) < 0 or max(steps) > 384:
        raise argparse.ArgumentTypeError("Steps must be comma separated values from 0 to 384")
    return steps


def write_manifest(output: Path, filename: str, parameter: str, run: datetime, now: datetime, products: list[dict]) -> None:
    manifest = {
        "source": "NOAA GFS 0.25 degree",
        "parameter": parameter,
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

    with tempfile.TemporaryDirectory(prefix="gfs_extra_maps_") as temp_name:
        temp_dir = Path(temp_name)
        run, probe = select_run(now, temp_dir)
        args.output.mkdir(parents=True, exist_ok=True)
        for pattern in ("gust_f*.png", "thunder_f*.png", "feels_like_f*.png"):
            for old_map in args.output.glob(pattern):
                old_map.unlink()
        products = {"gust": [], "thunder": [], "feels_like": []}

        for step in args.steps:
            grib = probe if step == 0 else temp_dir / f"gfs_extra_f{step:03d}.grib2"
            if step != 0:
                download(subset_url(run, step), grib)
            fields = read_fields(grib)
            valid_utc = (run + timedelta(hours=step)).isoformat()
            filenames = {
                "gust": f"gust_f{step:03d}.png",
                "thunder": f"thunder_f{step:03d}.png",
                "feels_like": f"feels_like_f{step:03d}.png",
            }
            render_gust(fields, run, step, args.output / filenames["gust"])
            render_thunder(fields, run, step, args.output / filenames["thunder"])
            render_feels_like(fields, run, step, args.output / filenames["feels_like"])
            for map_type, filename in filenames.items():
                products[map_type].append({"step_hours": step, "valid_utc": valid_utc, "file": filename})

        write_manifest(args.output, "gust_manifest.json", "surface wind gust", run, now, products["gust"])
        write_manifest(args.output, "thunder_manifest.json", "CAPE adjusted for CIN", run, now, products["thunder"])
        write_manifest(args.output, "feels_like_manifest.json", "calculated feels like temperature", run, now, products["feels_like"])
        print(f"Generated {len(args.steps)} maps for gusts, thunder potential and feels like temperature from GFS run {run:%Y%m%d %H} UTC")


if __name__ == "__main__":
    main()
