#!/usr/bin/env python3
"""Download a compact NOAA GFS subset and render European 2 m temperature maps."""

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
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
BASE_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
EXTENT = (-12.0, 38.0, 35.0, 72.0)
DEFAULT_STEPS = tuple(range(0, 121, 6))


def latest_candidate_runs(now: datetime) -> list[datetime]:
    """Return recent GFS cycles, allowing time for NOAA to publish each run."""
    available = now - timedelta(hours=5)
    cycle_hour = (available.hour // 6) * 6
    first = available.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)
    return [first - timedelta(hours=6 * offset) for offset in range(5)]


def subset_url(run: datetime, step: int) -> str:
    query = {
        "file": f"gfs.t{run:%H}z.pgrb2.0p25.f{step:03d}",
        "lev_2_m_above_ground": "on",
        "var_TMP": "on",
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
    """Find the newest cycle whose analysis field is actually available."""
    probe = work_dir / "probe.grib2"
    errors = []
    for run in latest_candidate_runs(now):
        try:
            download(subset_url(run, 0), probe, attempts=2)
            return run, probe
        except RuntimeError as exc:
            errors.append(str(exc))
    raise RuntimeError("No recent GFS cycle was available. " + " | ".join(errors))


def temperature_colormap() -> tuple[LinearSegmentedColormap, np.ndarray]:
    colors = [
        "#b000b0", "#54169c", "#073eaa", "#0079c8", "#54b8ef",
        "#c8e9ff", "#b8f58a", "#eff22b", "#ffb51b", "#ee4b16", "#ad0047",
    ]
    levels = np.arange(-32, 36, 2)
    return LinearSegmentedColormap.from_list("strandvejr_temperature", colors, N=len(levels) - 1), levels


def read_temperature(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    datasets = cfgrib.open_datasets(
        path,
        backend_kwargs={"indexpath": "", "filter_by_keys": {"typeOfLevel": "heightAboveGround"}},
    )
    try:
        dataset = next(ds for ds in datasets if "t2m" in ds.data_vars)
    except StopIteration as exc:
        raise RuntimeError("The downloaded GRIB file did not contain 2 m temperature") from exc
    temperature = np.asarray(dataset["t2m"].values, dtype=float) - 273.15
    latitudes = np.asarray(dataset.latitude.values)
    longitudes = np.asarray(dataset.longitude.values)
    longitudes = np.where(longitudes > 180, longitudes - 360, longitudes)
    return longitudes, latitudes, temperature


def render_map(grib: Path, run: datetime, step: int, destination: Path) -> None:
    longitudes, latitudes, temperature = read_temperature(grib)
    cmap, levels = temperature_colormap()
    norm = BoundaryNorm(levels, cmap.N, clip=True)

    figure = plt.figure(figsize=(8, 7.15), dpi=140, facecolor="white")
    axis = figure.add_axes((0.055, 0.105, 0.80, 0.85), projection=ccrs.PlateCarree())
    axis.set_extent(EXTENT, crs=ccrs.PlateCarree())
    filled = axis.contourf(
        longitudes, latitudes, temperature, levels=levels, cmap=cmap, norm=norm,
        extend="both", transform=ccrs.PlateCarree(),
    )
    contours = axis.contour(
        longitudes, latitudes, temperature, levels=np.arange(-30, 36, 5),
        colors="#303030", linewidths=0.45, alpha=0.72, transform=ccrs.PlateCarree(),
    )
    axis.clabel(contours, inline=True, fontsize=6, fmt="%d")
    axis.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.65, edgecolor="#111111")
    axis.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.45, edgecolor="#333333")
    grid = axis.gridlines(draw_labels=True, linewidth=0.45, color="#7f9db1", alpha=0.7, linestyle=(0, (2, 4)))
    grid.top_labels = False
    grid.right_labels = False
    grid.xlabel_style = {"size": 7}
    grid.ylabel_style = {"size": 7}

    color_axis = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    colorbar = figure.colorbar(filled, cax=color_axis, ticks=np.arange(-30, 36, 5))
    colorbar.set_label("Celsius", fontsize=8)
    colorbar.ax.tick_params(labelsize=7)

    valid = run + timedelta(hours=step)
    figure.text(0.055, 0.105, "Temperatur 2 m", fontsize=12, weight="bold")
    figure.text(0.055, 0.072, f"Data: NOAA GFS 0,25°, kørsel {run:%d.%m.%Y kl. %H} UTC", fontsize=8)
    figure.text(0.855, 0.072, f"Gyldig: {valid:%d.%m.%Y kl. %H} UTC", fontsize=8, ha="right")
    figure.text(0.855, 0.105, "Kort © Vejrstation Sortsø Strand", fontsize=7, color="#222222", ha="right")
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def parse_steps(value: str) -> tuple[int, ...]:
    steps = tuple(sorted({int(item) for item in value.split(",") if item.strip()}))
    if not steps or min(steps) < 0 or max(steps) > 384:
        raise argparse.ArgumentTypeError("Steps must be comma separated values from 0 to 384")
    return steps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=parse_steps, default=DEFAULT_STEPS)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)

    with tempfile.TemporaryDirectory(prefix="gfs_maps_") as temp_name:
        temp_dir = Path(temp_name)
        run, probe = select_run(now, temp_dir)
        staging = temp_dir / "output"
        staging.mkdir()
        products = []

        for step in args.steps:
            grib = probe if step == 0 else temp_dir / f"gfs_f{step:03d}.grib2"
            if step != 0:
                download(subset_url(run, step), grib)
            filename = f"temperature_f{step:03d}.png"
            render_map(grib, run, step, staging / filename)
            products.append({
                "step_hours": step,
                "valid_utc": (run + timedelta(hours=step)).isoformat(),
                "file": filename,
            })

        manifest = {
            "source": "NOAA GFS 0.25 degree",
            "parameter": "2 m temperature",
            "run_utc": run.isoformat(),
            "generated_utc": now.isoformat(),
            "extent": {"west": EXTENT[0], "east": EXTENT[1], "south": EXTENT[2], "north": EXTENT[3]},
            "products": products,
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            shutil.rmtree(args.output)
        shutil.copytree(staging, args.output)
        print(f"Generated {len(products)} maps from GFS run {run:%Y%m%d %H} UTC")


if __name__ == "__main__":
    main()
