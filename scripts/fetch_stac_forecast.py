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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from eccodes import codes_get, codes_grib_find_nearest, codes_grib_new_from_file, codes_release

BASE = "https://opendataapi.dmi.dk/v1/forecastdata"
COLLECTION = "harmonie_dini_sf"
LAT = float(os.getenv("SORTSOE_LAT", "54.9347"))
LON = float(os.getenv("SORTSOE_LON", "11.9889"))
TZ = ZoneInfo("Europe/Copenhagen")
OUT = Path(os.getenv("FORECAST_OUT", "data/sortsoe.json"))
MAX_RETRIES = int(os.getenv("DMI_MAX_RETRIES", "7"))
TIMEOUT = int(os.getenv("DMI_TIMEOUT", "90"))
STEP_HOURS = int(os.getenv("FORECAST_STEP_HOURS", "3"))
MAX_FORECAST_HOURS = int(os.getenv("MAX_FORECAST_HOURS", "60"))

WANTED = {"2t", "10si", "10wdir", "cc", "rprate", "2r", "pres"}


def backoff(attempt: int, retry_after: str | None = None) -> float:
    try:
        header = float(retry_after) if retry_after else 0.0
    except (TypeError, ValueError):
        header = 0.0
    return max(header, min(60.0, 4.0 * (2 ** attempt))) + random.uniform(1.0, 4.0)


def open_with_retry(url: str, accept: str = "*/*"):
    headers = {"User-Agent": "strandvejr.dk DMI STAC forecast/1.0", "Accept": accept}
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= MAX_RETRIES:
                raise
            delay = backoff(attempt, exc.headers.get("Retry-After"))
            print(f"HTTP 429 for {url}. Retry in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            if attempt >= MAX_RETRIES:
                raise
            delay = backoff(attempt)
            print(f"Temporary error for {url}: {exc}. Retry in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
    raise RuntimeError("Request failed after retries")


def get_json(url: str) -> dict:
    with open_with_retry(url, "application/geo+json, application/json") as response:
        return json.load(response)


def download_file(url: str, path: str) -> int:
    total = 0
    with open_with_retry(url, "application/x-grib, application/octet-stream, */*") as response:
        with open(path, "wb") as fh:
            while True:
                chunk = response.read(8 * 1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                total += len(chunk)
    return total


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def find_latest_complete_run() -> tuple[str, list[dict]]:
    endpoint = f"{BASE}/collections/{COLLECTION}/items"
    data = get_json(endpoint + "?" + urllib.parse.urlencode({"limit": 500}))
    groups: dict[str, list[dict]] = defaultdict(list)
    for feature in data.get("features", []):
        run = feature.get("properties", {}).get("modelRun")
        if run:
            groups[run].append(feature)
    if not groups:
        raise RuntimeError("No HARMONIE model runs found")

    # Prefer the newest run with a substantial number of forecast files.
    candidates = sorted(groups.items(), key=lambda item: item[0], reverse=True)
    for run, features in candidates:
        if len(features) >= 15:
            return run, features
    return candidates[0]


def fetch_run_items(model_run: str, fallback: list[dict]) -> list[dict]:
    endpoint = f"{BASE}/collections/{COLLECTION}/items"
    url = endpoint + "?" + urllib.parse.urlencode({"modelRun": model_run, "limit": 100})
    data = get_json(url)
    features = data.get("features", [])
    return features or fallback


def selected_items(model_run: str, features: list[dict]) -> list[tuple[int, dict]]:
    run_dt = parse_dt(model_run)
    selected: list[tuple[int, dict]] = []
    for feature in features:
        p = feature.get("properties", {})
        valid = p.get("datetime")
        href = feature.get("asset", {}).get("data", {}).get("href")
        if not valid or not href:
            continue
        lead = round((parse_dt(valid) - run_dt).total_seconds() / 3600)
        if 0 <= lead <= MAX_FORECAST_HOURS and lead % STEP_HOURS == 0:
            selected.append((lead, feature))
    selected.sort(key=lambda item: item[0])
    if not selected:
        raise RuntimeError("No suitable STAC forecast steps found")
    return selected


def safe_get(gid, key: str, default=None):
    try:
        return codes_get(gid, key)
    except Exception:
        return default


def read_point(path: str) -> tuple[dict, dict | None]:
    found: dict[str, float] = {}
    model_point = None
    with open(path, "rb") as fh:
        while True:
            gid = codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                short_name = str(safe_get(gid, "shortName", ""))
                if short_name not in WANTED or short_name in found:
                    continue
                if short_name == "2t" and str(safe_get(gid, "stepType", "")) not in {"instant", ""}:
                    continue
                nearest = codes_grib_find_nearest(gid, LAT, LON)[0]
                found[short_name] = float(nearest.value)
                if model_point is None:
                    model_point = {
                        "latitude": float(nearest.lat),
                        "longitude": float(nearest.lon),
                        "distanceKm": round(float(nearest.distance), 3),
                    }
                if WANTED.issubset(found.keys()):
                    break
            finally:
                codes_release(gid)
    return found, model_point


def wind_dir_text(deg):
    if deg is None:
        return None
    dirs = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]
    return dirs[int((deg + 22.5) // 45) % 8]


def weather_code(cloud: float | None, rain_rate: float | None) -> str:
    cloud_pct = cloud if cloud is not None else 0
    rain = rain_rate if rain_rate is not None else 0
    if rain >= 4:
        return "heavy_rain"
    if rain >= 0.5:
        return "rain"
    if rain >= 0.05:
        return "light_rain"
    if cloud_pct >= 88:
        return "overcast"
    if cloud_pct >= 60:
        return "cloudy"
    if cloud_pct >= 25:
        return "partly_cloudy"
    return "clear"


def weather_label(code: str) -> str:
    return {
        "clear": "Klart",
        "partly_cloudy": "Let skyet",
        "cloudy": "Skyet",
        "overcast": "Overskyet",
        "light_rain": "Let regn",
        "rain": "Regn",
        "heavy_rain": "Kraftig regn",
    }.get(code, "Vejr")


def make_row(valid_time: str, lead: int, raw: dict) -> dict:
    local = parse_dt(valid_time).astimezone(TZ)
    temp = round(raw["2t"] - 273.15, 1) if "2t" in raw else None
    cloud = None
    if "cc" in raw:
        cloud = round(raw["cc"] * 100 if raw["cc"] <= 1.2 else raw["cc"])
    rain = round(max(0.0, raw.get("rprate", 0.0) * 3600.0), 2) if "rprate" in raw else None
    wind = round(raw["10si"], 1) if "10si" in raw else None
    wind_dir = round(raw["10wdir"]) if "10wdir" in raw else None
    humidity = round(raw["2r"]) if "2r" in raw else None
    pressure = round(raw["pres"] / 100.0, 1) if "pres" in raw else None
    code = weather_code(cloud, rain)
    return {
        "time": local.isoformat(timespec="minutes"),
        "leadHours": lead,
        "temperature": temp,
        "wind": wind,
        "windDirection": wind_dir,
        "windDirectionText": wind_dir_text(wind_dir),
        "cloudCover": cloud,
        "rainRateMmH": rain,
        "humidity": humidity,
        "pressure": pressure,
        "weather": code,
        "weatherLabel": weather_label(code),
    }


def summarize_days(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["time"][:10]].append(row)
    days = []
    for day, vals in sorted(groups.items()):
        temps = [v["temperature"] for v in vals if v["temperature"] is not None]
        winds = [v["wind"] for v in vals if v["wind"] is not None]
        rains = [v["rainRateMmH"] for v in vals if v["rainRateMmH"] is not None]
        codes = [v["weather"] for v in vals]
        severity = ["heavy_rain", "rain", "light_rain", "overcast", "cloudy", "partly_cloudy", "clear"]
        dominant = next((c for c in severity if c in codes), Counter(codes).most_common(1)[0][0])
        dirs = [v["windDirection"] for v in vals if v["windDirection"] is not None]
        mean_dir = None
        if dirs:
            x = sum(math.sin(math.radians(d)) for d in dirs)
            y = sum(math.cos(math.radians(d)) for d in dirs)
            mean_dir = (math.degrees(math.atan2(x, y)) + 360) % 360
        max_temp = max(temps) if temps else None
        min_temp = min(temps) if temps else None
        avg_wind = round(sum(winds) / len(winds), 1) if winds else None
        peak_rain = max(rains) if rains else None
        text = weather_label(dominant)
        if max_temp is not None:
            text += f", op til {round(max_temp)} grader"
        if avg_wind is not None:
            text += f", vind {wind_dir_text(mean_dir)} omkring {round(avg_wind)} m/s"
        if peak_rain is not None and peak_rain >= 0.05:
            text += f". Højeste beregnede nedbørsintensitet omkring {peak_rain:g} mm/time"
        days.append({
            "date": day,
            "temperatureMin": min_temp,
            "temperatureMax": max_temp,
            "windAvg": avg_wind,
            "windDirectionText": wind_dir_text(mean_dir),
            "rainRateMaxMmH": peak_rain,
            "weather": dominant,
            "weatherLabel": weather_label(dominant),
            "summary": text + ".",
        })
    return days


def existing_model_run() -> str | None:
    if not OUT.exists():
        return None
    try:
        return json.loads(OUT.read_text(encoding="utf-8")).get("source", {}).get("modelRun")
    except Exception:
        return None


def main() -> None:
    print("Finding newest usable HARMONIE DINI surface run")
    model_run, fallback = find_latest_complete_run()
    print(f"Selected modelRun: {model_run}")

    if existing_model_run() == model_run and os.getenv("FORCE_FORECAST", "0") != "1":
        print("Forecast already uses this modelRun; nothing to do")
        return

    features = fetch_run_items(model_run, fallback)
    items = selected_items(model_run, features)
    print(f"Downloading {len(items)} GRIB steps at {STEP_HOURS} hour intervals")

    rows = []
    model_point = None
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
            raw, point = read_point(temp_path)
            if model_point is None and point:
                model_point = point
            row = make_row(valid, lead, raw)
            rows.append(row)
            print(f"  {size / 1_000_000:.1f} MB | {row['temperature']} C | {row['wind']} m/s | {row['weatherLabel']}")
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    if not rows:
        raise RuntimeError("No forecast rows were produced")

    payload = {
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
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "downloadedBytes": total_bytes,
        },
        "currentForecast": rows[0],
        "hours": rows,
        "days": summarize_days(rows),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}: {len(rows)} forecast points, {total_bytes / 1_000_000_000:.2f} GB downloaded")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
