#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import random
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from eccodes import codes_get, codes_grib_find_nearest, codes_grib_new_from_file, codes_release

BASE = "https://opendataapi.dmi.dk/v1/forecastdata"
COLLECTION = "harmonie_dini_sf"
LAT = float(os.getenv("SORTSOE_LAT", "54.9347"))
LON = float(os.getenv("SORTSOE_LON", "11.9889"))
OUT = Path(os.getenv("STAC_PROBE_OUT", "data/stac_probe.json"))
MAX_RETRIES = int(os.getenv("DMI_MAX_RETRIES", "7"))
TIMEOUT = int(os.getenv("DMI_TIMEOUT", "60"))

WANTED = {"2t", "10si", "10wdir", "gust", "cc", "rprate", "2r", "pres"}


def wait_seconds(attempt: int, retry_after: str | None = None) -> float:
    try:
        header = float(retry_after) if retry_after else 0.0
    except (TypeError, ValueError):
        header = 0.0
    return max(header, min(60.0, 4.0 * (2 ** attempt))) + random.uniform(1.0, 4.0)


def request(url: str) -> bytes:
    headers = {
        "User-Agent": "strandvejr.dk DMI STAC fetcher/1.0",
        "Accept": "application/geo+json, application/json, application/x-grib, */*",
    }
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= MAX_RETRIES:
                raise
            delay = wait_seconds(attempt, exc.headers.get("Retry-After"))
            print(f"DMI HTTP 429. Retry {attempt + 1}/{MAX_RETRIES} in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            if attempt >= MAX_RETRIES:
                raise
            delay = wait_seconds(attempt)
            print(f"Temporary DMI error ({exc}). Retry {attempt + 1}/{MAX_RETRIES} in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
    raise RuntimeError("DMI request failed after retries")


def get_json(url: str) -> dict:
    return json.loads(request(url).decode("utf-8"))


def latest_model_run() -> str:
    # Fast path: ask STAC to sort by modelRun. If that is unavailable, fall back
    # to a larger unsorted page and select the newest modelRun locally.
    endpoint = f"{BASE}/collections/{COLLECTION}/items"
    fast_url = endpoint + "?" + urllib.parse.urlencode({"limit": 1, "sortorder": "modelRun,DESC"})
    try:
        data = get_json(fast_url)
        features = data.get("features", [])
        if features and features[0].get("properties", {}).get("modelRun"):
            return features[0]["properties"]["modelRun"]
    except Exception as exc:
        print(f"Sorted STAC lookup failed, using fallback: {exc}", file=sys.stderr)

    fallback_url = endpoint + "?" + urllib.parse.urlencode({"limit": 500})
    data = get_json(fallback_url)
    runs = [f.get("properties", {}).get("modelRun") for f in data.get("features", [])]
    runs = [r for r in runs if r]
    if not runs:
        raise RuntimeError("No HARMONIE modelRun found in STAC response")
    return max(runs)


def select_step(model_run: str) -> dict:
    endpoint = f"{BASE}/collections/{COLLECTION}/items"
    url = endpoint + "?" + urllib.parse.urlencode({"modelRun": model_run, "limit": 100})
    data = get_json(url)
    features = data.get("features", [])
    if not features:
        raise RuntimeError(f"No STAC files found for modelRun {model_run}")
    features.sort(key=lambda f: f.get("properties", {}).get("datetime", ""))
    return features[0]


def safe_get(gid, key: str, default=None):
    try:
        return codes_get(gid, key)
    except Exception:
        return default


def read_point(grib_path: str) -> dict:
    found: dict[str, dict] = {}
    available = set()

    with open(grib_path, "rb") as fh:
        while True:
            gid = codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                short_name = str(safe_get(gid, "shortName", ""))
                if short_name:
                    available.add(short_name)
                if short_name not in WANTED:
                    continue

                step_type = str(safe_get(gid, "stepType", ""))
                # 2t occurs as instant, maximum and minimum fields. For this first
                # probe we want the instantaneous temperature.
                if short_name == "2t" and step_type not in {"instant", ""}:
                    continue
                if short_name in found:
                    continue

                nearest = codes_grib_find_nearest(gid, LAT, LON)[0]
                found[short_name] = {
                    "value": float(nearest.value),
                    "latitude": float(nearest.lat),
                    "longitude": float(nearest.lon),
                    "distanceKm": float(nearest.distance),
                    "units": str(safe_get(gid, "units", "")),
                    "name": str(safe_get(gid, "name", short_name)),
                    "stepType": step_type,
                }
            finally:
                codes_release(gid)

    if not found:
        raise RuntimeError("No requested weather parameters were found in the GRIB file")

    return {"parameters": found, "availableShortNames": sorted(available)}


def convert_values(parameters: dict) -> dict:
    result = {}
    for key, entry in parameters.items():
        value = entry["value"]
        converted = dict(entry)
        if key == "2t":
            converted["valueC"] = round(value - 273.15, 1)
        elif key == "cc":
            converted["valuePct"] = round(value * 100.0 if value <= 1.2 else value)
        elif key == "rprate":
            converted["valueMmH"] = round(max(0.0, value * 3600.0), 3)
        elif key == "pres":
            converted["valueHpa"] = round(value / 100.0, 1)
        result[key] = converted
    return result


def main() -> None:
    print("Finding latest DMI HARMONIE DINI surface model run via STAC")
    model_run = latest_model_run()
    print(f"Latest modelRun: {model_run}")

    item = select_step(model_run)
    props = item.get("properties", {})
    asset = item.get("asset", {}).get("data", {})
    href = asset.get("href")
    if not href:
        raise RuntimeError("STAC item has no asset.data.href")

    print(f"Downloading one GRIB step: {props.get('datetime')}")
    grib_bytes = request(href)
    print(f"Downloaded {len(grib_bytes):,} bytes")

    with tempfile.NamedTemporaryFile(suffix=".grib", delete=False) as tmp:
        tmp.write(grib_bytes)
        temp_path = tmp.name

    try:
        point = read_point(temp_path)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    payload = {
        "ok": True,
        "location": {"name": "Sortsø Strand", "latitude": LAT, "longitude": LON},
        "source": {
            "provider": "DMI",
            "api": "Forecast Data STAC API",
            "collection": COLLECTION,
            "modelRun": model_run,
            "forecastTime": props.get("datetime"),
            "created": props.get("created"),
            "stacItem": item.get("id"),
            "downloadUrl": href,
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
        "parameters": convert_values(point["parameters"]),
        "availableShortNames": point["availableShortNames"],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    for short_name, entry in payload["parameters"].items():
        print(short_name, entry)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
