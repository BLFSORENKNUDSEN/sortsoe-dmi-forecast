#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import random
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from eccodes import (
    codes_get,
    codes_get_array,
    codes_grib_new_from_file,
    codes_release,
)

BASE = "https://opendataapi.dmi.dk/v1/forecastdata"
COLLECTION = "harmonie_dini_sf"

LAT = float(os.getenv("SORTSOE_LAT", "54.9347"))
LON = float(os.getenv("SORTSOE_LON", "11.9889"))
TZ = ZoneInfo("Europe/Copenhagen")

SORTSOE_OUT = Path("data/sortsoe.json")
GRID_DIR = Path("data/grid")
MANIFEST_OUT = GRID_DIR / "manifest.json"

MAX_RETRIES = int(os.getenv("DMI_MAX_RETRIES", "7"))
TIMEOUT = int(os.getenv("DMI_TIMEOUT", "90"))
STEP_HOURS = int(os.getenv("FORECAST_STEP_HOURS", "3"))
MAX_FORECAST_HOURS = int(os.getenv("MAX_FORECAST_HOURS", "60"))
MIN_COMPLETE_STEPS = int(os.getenv("MIN_COMPLETE_STEPS", "50"))

# Approximate geographic extent used by the browser solution.
DK_BOUNDS = {
    "south": 54.40,
    "north": 57.90,
    "west": 7.80,
    "east": 15.30,
}
GRID_RESOLUTION = 0.10
TILE_SIZE = 1.0

WANTED = {"2t", "10si", "10wdir", "cc", "tp", "2r", "pres"}


def backoff(attempt, retry_after=None):
    try:
        header = float(retry_after) if retry_after else 0.0
    except (TypeError, ValueError):
        header = 0.0
    return max(header, min(60.0, 4.0 * (2 ** attempt))) + random.uniform(1.0, 4.0)


def open_with_retry(url, accept="*/*"):
    headers = {
        "User-Agent": "strandvejr.dk DMI STAC Denmark grid/1.0",
        "Accept": accept,
    }
    for attempt in range(MAX_RETRIES + 1):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=headers),
                timeout=TIMEOUT,
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= MAX_RETRIES:
                raise
            delay = backoff(attempt, exc.headers.get("Retry-After"))
            print(f"HTTP 429. Retry in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            if attempt >= MAX_RETRIES:
                raise
            delay = backoff(attempt)
            print(f"Temporary error: {exc}. Retry in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
    raise RuntimeError("Request failed after retries")


def get_json(url):
    with open_with_retry(url, "application/geo+json, application/json") as response:
        return json.load(response)


def download_file(url, path):
    total = 0
    with open_with_retry(url, "application/x-grib, application/octet-stream, */*") as response, open(path, "wb") as fh:
        while True:
            chunk = response.read(8 * 1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            total += len(chunk)
    return total


def parse_dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def find_latest_complete_run():
    endpoint = f"{BASE}/collections/{COLLECTION}/items"
    data = get_json(endpoint + "?" + urllib.parse.urlencode({"limit": 1000}))
    groups = defaultdict(list)
    for feature in data.get("features", []):
        run = feature.get("properties", {}).get("modelRun")
        if run:
            groups[run].append(feature)

    if not groups:
        raise RuntimeError("No HARMONIE model runs found")

    for run, features in sorted(groups.items(), key=lambda x: x[0], reverse=True):
        valid_times = {
            f.get("properties", {}).get("datetime")
            for f in features
            if f.get("properties", {}).get("datetime")
        }
        if len(valid_times) >= MIN_COMPLETE_STEPS:
            return run, features

    raise RuntimeError("No sufficiently complete HARMONIE run found")


def fetch_run_items(model_run, fallback):
    endpoint = f"{BASE}/collections/{COLLECTION}/items"
    data = get_json(
        endpoint
        + "?"
        + urllib.parse.urlencode({"modelRun": model_run, "limit": 1000})
    )
    return data.get("features", []) or fallback


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
    selected.sort(key=lambda x: x[0])
    if len(selected) < 15:
        raise RuntimeError(f"Only {len(selected)} selected forecast steps found")
    return selected


def safe_get(gid, key, default=None):
    try:
        return codes_get(gid, key)
    except Exception:
        return default


def rounded_grid(v, step=GRID_RESOLUTION):
    return math.floor((v / step) + 0.5) * step


def build_spatial_selection(gid):
    lats = np.asarray(codes_get_array(gid, "latitudes"), dtype=np.float64)
    lons = np.asarray(codes_get_array(gid, "longitudes"), dtype=np.float64)

    mask = (
        (lats >= DK_BOUNDS["south"] - 0.15)
        & (lats <= DK_BOUNDS["north"] + 0.15)
        & (lons >= DK_BOUNDS["west"] - 0.15)
        & (lons <= DK_BOUNDS["east"] + 0.15)
    )
    candidate_indices = np.flatnonzero(mask)

    cells = {}
    for idx in candidate_indices.tolist():
        lat = float(lats[idx])
        lon = float(lons[idx])
        glat = rounded_grid(lat)
        glon = rounded_grid(lon)
        if not (
            DK_BOUNDS["south"] <= glat <= DK_BOUNDS["north"]
            and DK_BOUNDS["west"] <= glon <= DK_BOUNDS["east"]
        ):
            continue

        # Longitude degrees are shorter at Danish latitudes.
        dx = (lon - glon) * math.cos(math.radians(glat))
        dy = lat - glat
        d2 = dx * dx + dy * dy
        key = (round(glat, 2), round(glon, 2))
        current = cells.get(key)
        if current is None or d2 < current[0]:
            cells[key] = (d2, idx, lat, lon)

    selected = sorted(cells.items())
    indices = np.asarray([entry[1][1] for entry in selected], dtype=np.int64)
    coords = [
        {
            "gridLat": key[0],
            "gridLon": key[1],
            "lat": round(entry[1][2], 5),
            "lon": round(entry[1][3], 5),
        }
        for entry, key in [(v, k) for k, v in selected]
    ]

    # Exact nearest native point for Sortsø Strand.
    distances = (
        (lats[candidate_indices] - LAT) ** 2
        + ((lons[candidate_indices] - LON) * math.cos(math.radians(LAT))) ** 2
    )
    sortsoe_native_index = int(candidate_indices[int(np.argmin(distances))])

    return indices, coords, sortsoe_native_index, lats, lons


def read_step(path, selected_indices=None, sortsoe_native_index=None):
    fields = {}
    sortsoe = {}
    selection_info = None

    with open(path, "rb") as fh:
        while True:
            gid = codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                short_name = str(safe_get(gid, "shortName", ""))
                if short_name not in WANTED:
                    continue
                if short_name == "2t" and str(safe_get(gid, "stepType", "")) not in {"instant", ""}:
                    continue
                if short_name in fields:
                    continue

                if selected_indices is None:
                    selection_info = build_spatial_selection(gid)
                    selected_indices, _, sortsoe_native_index, _, _ = selection_info

                values = np.asarray(codes_get_array(gid, "values"), dtype=np.float64)
                fields[short_name] = values[selected_indices]
                if sortsoe_native_index is not None:
                    sortsoe[short_name] = float(values[sortsoe_native_index])

                if WANTED.issubset(fields.keys()):
                    break
            finally:
                codes_release(gid)

    return fields, sortsoe, selection_info


def wind_dir_text(deg):
    if deg is None:
        return None
    dirs = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]
    return dirs[int((deg + 22.5) // 45) % 8]


def weather_code(cloud, rain_mm):
    c = cloud or 0
    r = rain_mm or 0
    if r >= 8:
        return "heavy_rain"
    if r >= 1:
        return "rain"
    if r >= 0.1:
        return "light_rain"
    if c >= 88:
        return "overcast"
    if c >= 60:
        return "cloudy"
    if c >= 25:
        return "partly_cloudy"
    return "clear"


def weather_label(code):
    return {
        "clear": "Klart",
        "partly_cloudy": "Let skyet",
        "cloudy": "Skyet",
        "overcast": "Overskyet",
        "light_rain": "Let regn",
        "rain": "Regn",
        "heavy_rain": "Kraftig regn",
    }.get(code, "Vejr")


def make_sortsoe_row(valid_time, lead, raw, rain_mm):
    local = parse_dt(valid_time).astimezone(TZ)
    temp = round(raw["2t"] - 273.15, 1) if "2t" in raw else None
    cloud = (
        round(raw["cc"] * 100 if raw.get("cc", 0) <= 1.2 else raw["cc"])
        if "cc" in raw
        else None
    )
    wind = round(raw["10si"], 1) if "10si" in raw else None
    wind_dir = round(raw["10wdir"]) if "10wdir" in raw else None
    humidity = round(raw["2r"]) if "2r" in raw else None
    pressure = round(raw["pres"] / 100.0, 1) if "pres" in raw else None
    code = weather_code(cloud, rain_mm)

    return {
        "time": local.isoformat(timespec="minutes"),
        "leadHours": lead,
        "temperature": temp,
        "wind": wind,
        "windDirection": wind_dir,
        "windDirectionText": wind_dir_text(wind_dir),
        "cloudCover": cloud,
        "rainMm": round(rain_mm, 2) if rain_mm is not None else None,
        "humidity": humidity,
        "pressure": pressure,
        "weather": code,
        "weatherLabel": weather_label(code),
    }


def summarize_days(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["time"][:10]].append(row)

    days = []
    severity = ["heavy_rain", "rain", "light_rain", "overcast", "cloudy", "partly_cloudy", "clear"]

    for day, vals in sorted(groups.items()):
        temps = [v["temperature"] for v in vals if v["temperature"] is not None]
        winds = [v["wind"] for v in vals if v["wind"] is not None]
        rains = [v["rainMm"] or 0 for v in vals]
        codes = [v["weather"] for v in vals]
        dominant = next((c for c in severity if c in codes), "clear")

        dirs = [v["windDirection"] for v in vals if v["windDirection"] is not None]
        mean_dir = None
        if dirs:
            x = sum(math.sin(math.radians(d)) for d in dirs)
            y = sum(math.cos(math.radians(d)) for d in dirs)
            mean_dir = (math.degrees(math.atan2(x, y)) + 360) % 360

        total_rain = round(sum(rains), 1)
        avg_wind = round(sum(winds) / len(winds), 1) if winds else None
        text = weather_label(dominant)
        if temps:
            text += f", {round(min(temps))} til {round(max(temps))} grader"
        if total_rain >= 0.1:
            text += f", omkring {total_rain:g} mm nedbør"
        if avg_wind is not None:
            text += f", vind {wind_dir_text(mean_dir)} omkring {round(avg_wind)} m/s"

        days.append({
            "date": day,
            "temperatureMin": round(min(temps), 1) if temps else None,
            "temperatureMax": round(max(temps), 1) if temps else None,
            "rainMm": total_rain,
            "windAvg": avg_wind,
            "windDirectionText": wind_dir_text(mean_dir),
            "weather": dominant,
            "weatherLabel": weather_label(dominant),
            "summary": text + ".",
        })

    return days


def num(v, decimals=1):
    if v is None or not np.isfinite(v):
        return None
    return round(float(v), decimals)


def tile_key(lat, lon):
    return f"{math.floor(lat):02d}_{math.floor(lon):02d}"


def main():
    print("Finding newest complete HARMONIE DINI surface run")
    model_run, fallback = find_latest_complete_run()
    print(f"Selected modelRun: {model_run}")

    features = fetch_run_items(model_run, fallback)
    items = selected_items(model_run, features)
    print(f"Downloading {len(items)} GRIB steps at {STEP_HOURS} hour intervals")

    selected_indices = None
    coords = None
    sortsoe_native_index = None
    native_lats = native_lons = None

    times = []
    leads = []
    series = defaultdict(list)
    sortsoe_rows = []
    previous_tp = None
    previous_sortsoe_tp = None
    total_bytes = 0

    for index, (lead, item) in enumerate(items, 1):
        props = item.get("properties", {})
        valid = props.get("datetime")
        href = item.get("asset", {}).get("data", {}).get("href")
        print(f"[{index}/{len(items)}] +{lead:02d}h {valid}")

        with tempfile.NamedTemporaryFile(suffix=".grib", delete=False) as tmp:
            temp_path = tmp.name

        try:
            size = download_file(href, temp_path)
            total_bytes += size
            fields, sortsoe_raw, selection_info = read_step(
                temp_path,
                selected_indices=selected_indices,
                sortsoe_native_index=sortsoe_native_index,
            )

            if selection_info is not None:
                selected_indices, coords, sortsoe_native_index, native_lats, native_lons = selection_info
                print(f"Selected {len(selected_indices)} Denmark grid points")

            local_time = parse_dt(valid).astimezone(TZ).isoformat(timespec="minutes")
            times.append(local_time)
            leads.append(lead)

            tp = fields.get("tp")
            if tp is not None:
                if previous_tp is None:
                    rain = np.zeros_like(tp)
                else:
                    rain = np.maximum(0.0, tp - previous_tp)
                previous_tp = tp.copy()
            else:
                rain = np.full(len(selected_indices), np.nan)

            conversions = {
                "temperature": fields.get("2t") - 273.15 if "2t" in fields else None,
                "wind": fields.get("10si"),
                "windDirection": fields.get("10wdir"),
                "cloudCover": fields.get("cc") * 100.0 if "cc" in fields else None,
                "rainMm": rain,
                "humidity": fields.get("2r"),
                "pressure": fields.get("pres") / 100.0 if "pres" in fields else None,
            }
            for name, arr in conversions.items():
                series[name].append(arr)

            sortsoe_tp = sortsoe_raw.get("tp")
            if sortsoe_tp is None:
                sortsoe_rain = None
            elif previous_sortsoe_tp is None:
                sortsoe_rain = 0.0
            else:
                sortsoe_rain = max(0.0, sortsoe_tp - previous_sortsoe_tp)
            if sortsoe_tp is not None:
                previous_sortsoe_tp = sortsoe_tp

            sortsoe_rows.append(make_sortsoe_row(valid, lead, sortsoe_raw, sortsoe_rain))
            print(f"  {size / 1_000_000:.1f} MB | Sortsoe {sortsoe_rows[-1]['temperature']} C")

        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    if not coords or not sortsoe_rows:
        raise RuntimeError("No forecast data produced")

    # Stack as point x time matrices.
    matrices = {}
    for name, arrays in series.items():
        valid_arrays = [
            a if a is not None else np.full(len(coords), np.nan)
            for a in arrays
        ]
        matrices[name] = np.stack(valid_arrays, axis=1)

    GRID_DIR.mkdir(parents=True, exist_ok=True)

    # Clear obsolete grid JSON files from earlier model runs.
    for old in GRID_DIR.glob("tile_*.json"):
        old.unlink()

    tile_points = defaultdict(list)
    for i, coord in enumerate(coords):
        key = tile_key(coord["gridLat"], coord["gridLon"])
        tile_points[key].append(i)

    for key, point_indices in tile_points.items():
        points = []
        for i in point_indices:
            points.append([
                coord_value := coords[i]["gridLat"],
                coords[i]["gridLon"],
                [num(x) for x in matrices["temperature"][i]],
                [num(x) for x in matrices["wind"][i]],
                [num(x, 0) for x in matrices["windDirection"][i]],
                [num(x, 0) for x in matrices["cloudCover"][i]],
                [num(x, 2) for x in matrices["rainMm"][i]],
                [num(x, 0) for x in matrices["humidity"][i]],
                [num(x) for x in matrices["pressure"][i]],
            ])

        tile_payload = {
            "v": 1,
            "modelRun": model_run,
            "intervalHours": STEP_HOURS,
            "times": times,
            "fields": [
                "gridLat",
                "gridLon",
                "temperature",
                "wind",
                "windDirection",
                "cloudCover",
                "rainMm",
                "humidity",
                "pressure",
            ],
            "points": points,
        }
        (GRID_DIR / f"tile_{key}.json").write_text(
            json.dumps(tile_payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    manifest = {
        "v": 1,
        "provider": "DMI",
        "model": "HARMONIE DINI surface",
        "modelRun": model_run,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "intervalHours": STEP_HOURS,
        "resolutionDegrees": GRID_RESOLUTION,
        "tileSizeDegrees": TILE_SIZE,
        "bounds": DK_BOUNDS,
        "times": times,
        "tiles": sorted(tile_points.keys()),
        "fields": [
            "gridLat",
            "gridLon",
            "temperature",
            "wind",
            "windDirection",
            "cloudCover",
            "rainMm",
            "humidity",
            "pressure",
        ],
    }
    MANIFEST_OUT.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    model_point = {
        "latitude": round(float(native_lats[sortsoe_native_index]), 6),
        "longitude": round(float(native_lons[sortsoe_native_index]), 6),
    }
    sortsoe_payload = {
        "location": {
            "name": "Sortsø Strand",
            "latitude": LAT,
            "longitude": LON,
            "timezone": "Europe/Copenhagen",
            "modelPoint": model_point,
        },
        "source": {
            "provider": "DMI",
            "api": "Forecast Data STAC API",
            "model": "HARMONIE DINI surface",
            "collection": COLLECTION,
            "modelRun": model_run,
            "intervalHours": STEP_HOURS,
            "generated": manifest["generated"],
            "downloadedBytes": total_bytes,
        },
        "currentForecast": sortsoe_rows[0],
        "hours": sortsoe_rows,
        "days": summarize_days(sortsoe_rows),
    }
    SORTSOE_OUT.write_text(
        json.dumps(sortsoe_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Wrote Sortsoe forecast plus {len(tile_points)} regional grid tiles "
        f"from {len(coords)} grid points."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
