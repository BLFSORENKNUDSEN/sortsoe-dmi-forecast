#!/usr/bin/env python3
"""Generate Strandvejr.dk winter outlook maps from NOAA GFS 0.25 degree data."""

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

OUTPUT_DIR = Path(__file__).resolve().parent / "winter_output"
BASE_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
EXTENT = (-12.0, 38.0, 35.0, 72.0)

# High detail through day 5, lighter sampling through day 16.
DEFAULT_STEPS = tuple(list(range(0, 121, 6)) + list(range(132, 385, 12)))


def latest_candidate_runs(now: datetime) -> list[datetime]:
    available = now - timedelta(hours=5)
    cycle_hour = (available.hour // 6) * 6
    first = available.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)
    return [first - timedelta(hours=6 * offset) for offset in range(5)]


def subset_url(run: datetime, step: int) -> str:
    query = {
        "file": f"gfs.t{run:%H}z.pgrb2.0p25.f{step:03d}",
        "lev_2_m_above_ground": "on",
        "lev_850_mb": "on",
        "lev_surface": "on",
        "var_TMP": "on",
        "var_SNOD": "on",
        "var_CSNOW": "on",
        "var_CRAIN": "on",
        "var_CFRZR": "on",
        "var_CICEP": "on",
        "subregion": "",
        "leftlon": str(EXTENT[0]),
        "rightlon": str(EXTENT[1]),
        "toplat": str(EXTENT[3]),
        "bottomlat": str(EXTENT[2]),
        "dir": f"/gfs.{run:%Y%m%d}/{run:%H}/atmos",
    }
    return f"{BASE_URL}?{urlencode(query)}"


def download(url: str, destination: Path, attempts: int = 4) -> None:
    request = Request(url, headers={"User-Agent": "strandvejr.dk GFS winter outlook/1.0"})
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


def field_by_alias(datasets, aliases: tuple[str, ...], level_coord: str | None = None, level_value: float | None = None):
    aliases_lower = {a.lower() for a in aliases}

    for ds in datasets:
        if level_coord and level_coord not in ds.coords:
            continue
        if level_coord and level_value is not None:
            try:
                coord = np.asarray(ds.coords[level_coord].values).astype(float)
                if not np.any(np.isclose(coord, level_value)):
                    continue
            except Exception:
                continue

        for name, da in ds.data_vars.items():
            short_name = str(da.attrs.get("GRIB_shortName", "")).lower()
            if name.lower() in aliases_lower or short_name in aliases_lower:
                values = np.asarray(da.values, dtype=float)
                if values.ndim > 2:
                    values = np.squeeze(values)
                return values, ds
    return None, None


def read_fields(path: Path) -> dict[str, np.ndarray]:
    datasets = cfgrib.open_datasets(path, backend_kwargs={"indexpath": ""})

    t2m, ds_t2m = field_by_alias(datasets, ("t2m", "2t"))
    t850, ds_t850 = field_by_alias(datasets, ("t", "tmp"), "isobaricInhPa", 850)
    snow_depth, ds_snow = field_by_alias(datasets, ("sde", "snod", "sd"))

    csnow, ds_csnow = field_by_alias(datasets, ("csnow",))
    crain, _ = field_by_alias(datasets, ("crain",))
    cfrzr, _ = field_by_alias(datasets, ("cfrzr",))
    cicep, _ = field_by_alias(datasets, ("cicep",))

    reference = ds_t2m or ds_t850 or ds_snow or ds_csnow
    required = {
        "2 m temperature": t2m,
        "850 hPa temperature": t850,
        "snow depth": snow_depth,
        "categorical snow": csnow,
        "categorical rain": crain,
        "categorical freezing rain": cfrzr,
        "categorical ice pellets": cicep,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing or reference is None:
        available = sorted({
            f"{name}:{da.attrs.get('GRIB_shortName', '')}"
            for ds in datasets for name, da in ds.data_vars.items()
        })
        raise RuntimeError(f"Missing GFS winter fields {missing}. Available: {available}")

    latitudes = np.asarray(reference.latitude.values)
    longitudes = np.asarray(reference.longitude.values)
    longitudes = np.where(longitudes > 180, longitudes - 360, longitudes)

    return {
        "longitude": longitudes,
        "latitude": latitudes,
        "temperature_2m": t2m - 273.15,
        "temperature_850": t850 - 273.15,
        "snow_depth_cm": np.maximum(snow_depth * 100.0, 0.0),
        "csnow": csnow,
        "crain": crain,
        "cfrzr": cfrzr,
        "cicep": cicep,
    }


def add_geography(axis) -> None:
    axis.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.65, edgecolor="#202020")
    axis.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.45, edgecolor="#454545")
    grid = axis.gridlines(
        draw_labels=True, linewidth=0.45, color="#82939d",
        alpha=0.65, linestyle=(0, (2, 4)),
    )
    grid.top_labels = False
    grid.right_labels = False
    grid.xlabel_style = {"size": 7}
    grid.ylabel_style = {"size": 7}


def add_footer(figure, title: str, run: datetime, step: int) -> None:
    valid = run + timedelta(hours=step)
    figure.text(0.055, 0.105, title, fontsize=12, weight="bold")
    figure.text(0.055, 0.072, f"NOAA GFS 0,25° · kørsel {run:%d.%m.%Y kl. %H} UTC", fontsize=8)
    figure.text(0.855, 0.105, "Kort © Vejrstation Sortsø Strand", fontsize=7, color="#222222", ha="right")
    figure.text(0.855, 0.072, f"Gyldig: {valid:%d.%m.%Y kl. %H} UTC · +{step} t", fontsize=8, ha="right")


def base_figure():
    figure = plt.figure(figsize=(8, 7.15), dpi=140, facecolor="white")
    axis = figure.add_axes((0.055, 0.105, 0.80, 0.85), projection=ccrs.PlateCarree())
    axis.set_extent(EXTENT, crs=ccrs.PlateCarree())
    return figure, axis


def temperature_cmap():
    colors = [
        "#6f00a8", "#2840a6", "#0877c9", "#58b7e8", "#d8f3ff",
        "#e9f6d0", "#d9ef65", "#f5d640", "#f6a02e", "#e4542d", "#9e174b",
    ]
    levels = np.arange(-36, 22, 2)
    return LinearSegmentedColormap.from_list("winter_temp", colors, N=len(levels) - 1), levels


def render_temperature(fields, key: str, title: str, run, step, destination):
    cmap, levels = temperature_cmap()
    values = fields[key]
    figure, axis = base_figure()
    field = axis.contourf(
        fields["longitude"], fields["latitude"], values,
        levels=levels, cmap=cmap, norm=BoundaryNorm(levels, cmap.N),
        extend="both", transform=ccrs.PlateCarree(),
    )
    contours = axis.contour(
        fields["longitude"], fields["latitude"], values,
        levels=np.arange(-30, 21, 5), colors="#252525",
        linewidths=0.5, alpha=0.7, transform=ccrs.PlateCarree(),
    )
    axis.clabel(contours, inline=True, fontsize=6, fmt="%d")
    add_geography(axis)
    cax = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    cb = figure.colorbar(field, cax=cax, ticks=np.arange(-30, 21, 5))
    cb.set_label("°C", fontsize=8)
    cb.ax.tick_params(labelsize=7)
    add_footer(figure, title, run, step)
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def render_snow_depth(fields, run, step, destination):
    values = fields["snow_depth_cm"]
    levels = np.array([0.5, 1, 2, 5, 10, 20, 30, 50, 75, 100])
    colors = ["#e8f7ff", "#c9edff", "#9ddcff", "#68c3f0", "#3a9ad9", "#5777cf", "#7453bc", "#943da0", "#b82d74"]
    cmap = ListedColormap(colors, name="snow_depth")
    figure, axis = base_figure()
    field = axis.contourf(
        fields["longitude"], fields["latitude"], values,
        levels=levels, cmap=cmap, norm=BoundaryNorm(levels, cmap.N),
        extend="max", transform=ccrs.PlateCarree(),
    )
    add_geography(axis)
    cax = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    cb = figure.colorbar(field, cax=cax, ticks=levels)
    cb.set_label("Snedybde, cm", fontsize=8)
    cb.ax.tick_params(labelsize=7)
    add_footer(figure, "Snedybde", run, step)
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def render_precip_type(fields, run, step, destination):
    # Priority when GFS categorical flags overlap:
    # freezing rain > ice pellets > snow > rain.
    ptype = np.zeros_like(fields["csnow"], dtype=np.int8)
    ptype = np.where(fields["crain"] >= 0.5, 1, ptype)
    ptype = np.where(fields["csnow"] >= 0.5, 2, ptype)
    ptype = np.where(fields["cicep"] >= 0.5, 3, ptype)
    ptype = np.where(fields["cfrzr"] >= 0.5, 4, ptype)

    cmap = ListedColormap(["#5cb85c", "#4aa3df", "#a16ad5", "#e34b87"], name="precip_type")
    levels = np.array([0.5, 1.5, 2.5, 3.5, 4.5])
    figure, axis = base_figure()
    field = axis.contourf(
        fields["longitude"], fields["latitude"], ptype,
        levels=levels, cmap=cmap, norm=BoundaryNorm(levels, cmap.N),
        transform=ccrs.PlateCarree(),
    )
    add_geography(axis)
    cax = figure.add_axes((0.88, 0.15, 0.022, 0.76))
    cb = figure.colorbar(field, cax=cax, ticks=[1, 2, 3, 4])
    cb.ax.set_yticklabels(["Regn", "Sne", "Iskorn", "Frysende regn"])
    cb.ax.tick_params(labelsize=7)
    add_footer(figure, "Nedbørstype", run, step)
    figure.savefig(destination, format="png", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def parse_steps(value: str) -> tuple[int, ...]:
    steps = tuple(sorted({int(item) for item in value.split(",") if item.strip()}))
    if not steps or min(steps) < 0 or max(steps) > 384:
        raise argparse.ArgumentTypeError("Steps must be comma separated values from 0 to 384")
    return steps


def write_manifest(output: Path, run: datetime, now: datetime, products: dict[str, list[dict]]) -> None:
    manifest = {
        "source": "NOAA GFS 0.25 degree",
        "run_utc": run.isoformat(),
        "generated_utc": now.isoformat(),
        "extent": {"west": EXTENT[0], "east": EXTENT[1], "south": EXTENT[2], "north": EXTENT[3]},
        "sampling": {
            "through_120_hours": "6 hourly",
            "after_120_hours": "12 hourly",
            "horizon_hours": 384,
        },
        "layers": {
            "temperature_2m": {"title": "Temperatur 2 m", "products": products["temperature_2m"]},
            "temperature_850": {"title": "Temperatur 850 hPa", "products": products["temperature_850"]},
            "precip_type": {"title": "Nedbørstype", "products": products["precip_type"]},
            "snow_depth": {"title": "Snedybde", "products": products["snow_depth"]},
        },
    }
    (output / "winter_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=parse_steps, default=DEFAULT_STEPS)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)

    with tempfile.TemporaryDirectory(prefix="gfs_winter_") as temp_name:
        temp_dir = Path(temp_name)
        run, probe = select_run(now, temp_dir)

        staging = temp_dir / "winter_output"
        staging.mkdir()
        products = {key: [] for key in ("temperature_2m", "temperature_850", "precip_type", "snow_depth")}

        for step in args.steps:
            grib = probe if step == 0 else temp_dir / f"winter_f{step:03d}.grib2"
            if step != 0:
                download(subset_url(run, step), grib)

            fields = read_fields(grib)
            valid = (run + timedelta(hours=step)).isoformat()
            common = {"step_hours": step, "valid_utc": valid}

            names = {
                "temperature_2m": f"winter_temperature_2m_f{step:03d}.png",
                "temperature_850": f"winter_temperature_850_f{step:03d}.png",
                "precip_type": f"winter_precip_type_f{step:03d}.png",
                "snow_depth": f"winter_snow_depth_f{step:03d}.png",
            }

            render_temperature(fields, "temperature_2m", "Temperatur 2 m", run, step, staging / names["temperature_2m"])
            render_temperature(fields, "temperature_850", "Temperatur 850 hPa", run, step, staging / names["temperature_850"])
            render_precip_type(fields, run, step, staging / names["precip_type"])
            render_snow_depth(fields, run, step, staging / names["snow_depth"])

            for key, filename in names.items():
                products[key].append({**common, "file": filename})

            print(f"Rendered winter maps +{step:03d} h")

        write_manifest(staging, run, now, products)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            shutil.rmtree(args.output)
        shutil.copytree(staging, args.output)
        print(f"Generated {len(args.steps)} winter timesteps from GFS run {run:%Y%m%d %H} UTC")


if __name__ == "__main__":
    main()
