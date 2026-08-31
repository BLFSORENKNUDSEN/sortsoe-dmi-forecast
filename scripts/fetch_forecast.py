#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "https://opendataapi.dmi.dk/v1/forecastedr"
COLLECTION = "harmonie_dini_sf"
LAT = float(os.getenv("SORTSOE_LAT", "54.9347"))
LON = float(os.getenv("SORTSOE_LON", "11.9889"))
TZ = ZoneInfo("Europe/Copenhagen")
OUT = Path(os.getenv("FORECAST_OUT", "data/sortsoe.json"))
MAX_RETRIES = int(os.getenv("DMI_MAX_RETRIES", "7"))
REQUEST_TIMEOUT = int(os.getenv("DMI_TIMEOUT", "45"))

PARAMETERS = [
    "temperature-2m",
    "wind-speed-10m",
    "wind-dir-10m",
    "gust-wind-speed-10m",
    "fraction-of-cloud-cover",
    "rain-precipitation-rate",
    "precipitation-type",
    "probability-of-lightning",
]


def retry_wait(attempt: int, retry_after: str | None = None) -> float:
    try:
        header_wait = float(retry_after) if retry_after else 0.0
    except (TypeError, ValueError):
        header_wait = 0.0
    backoff = min(60.0, 4.0 * (2 ** attempt))
    return max(header_wait, backoff) + random.uniform(1.0, 4.0)


def fetch_json(url: str) -> dict:
    headers = {
        "User-Agent": "strandvejr.dk DMI forecast fetcher/1.2",
        "Accept": "application/geo+json, application/json",
    }

    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= MAX_RETRIES:
                raise
            wait_seconds = retry_wait(attempt, exc.headers.get("Retry-After"))
            print(
                f"DMI returned HTTP 429. Retry {attempt + 1}/{MAX_RETRIES} "
                f"in {wait_seconds:.1f} seconds.",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            if attempt >= MAX_RETRIES:
                raise
            wait_seconds = retry_wait(attempt)
            print(
                f"DMI request timed out or failed temporarily ({exc}). "
                f"Retry {attempt + 1}/{MAX_RETRIES} in {wait_seconds:.1f} seconds.",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)

    raise RuntimeError("DMI request failed after retries")


def build_url() -> str:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = now + timedelta(hours=120)
    q = {
        "coords": f"POINT({LON} {LAT})",
        "crs": "crs84",
        "parameter-name": ",".join(PARAMETERS),
        "datetime": f"{now.isoformat().replace('+00:00', 'Z')}/{end.isoformat().replace('+00:00', 'Z')}",
        "f": "GeoJSON",
    }
    return f"{BASE}/collections/{COLLECTION}/position?{urllib.parse.urlencode(q)}"


def k_to_c(v):
    return None if v is None else round(float(v) - 273.15, 1)


def rate_to_mmh(v):
    return None if v is None else round(max(0.0, float(v) * 3600.0), 2)


def cloud_to_pct(v):
    if v is None:
        return None
    x = float(v)
    return round(x * 100.0 if x <= 1.2 else x)


def probability_to_pct(v):
    if v is None:
        return None
    x = float(v)
    return round(x * 100.0 if x <= 1.2 else x)


def wind_dir_text(deg):
    if deg is None:
        return None
    dirs = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]
    return dirs[int((float(deg) + 22.5) // 45) % 8]


def ptype_name(v):
    if v is None:
        return None
    mapping = {0: "drizzle", 1: "rain", 2: "sleet", 3: "snow", 4: "freezing_drizzle", 5: "freezing_rain", 6: "graupel", 7: "hail"}
    try:
        return mapping.get(int(round(float(v))), "unknown")
    except Exception:
        return None


def classify_weather(cloud_pct, rain_mmh, ptype, lightning_pct):
    rain = rain_mmh or 0.0
    cloud = cloud_pct if cloud_pct is not None else 0
    lightning = lightning_pct or 0
    if lightning >= 25 and rain >= 0.2:
        return "thunder"
    if ptype in {"snow", "graupel"} and rain >= 0.05:
        return "snow"
    if ptype == "sleet" and rain >= 0.05:
        return "sleet"
    if ptype in {"freezing_drizzle", "freezing_rain"} and rain >= 0.05:
        return "freezing_rain"
    if rain >= 4.0:
        return "heavy_rain"
    if rain >= 0.5:
        return "rain"
    if rain >= 0.05:
        return "light_rain"
    if cloud >= 88:
        return "overcast"
    if cloud >= 60:
        return "cloudy"
    if cloud >= 25:
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
        "thunder": "Regn og risiko for torden",
        "snow": "Sne",
        "sleet": "Slud",
        "freezing_rain": "Isslag",
    }.get(code, "Vejr")


def parse_step(feature):
    p = feature.get("properties", {})
    step = p.get("step") or p.get("time") or p.get("datetime")
    if not step:
        return None
    dt = datetime.fromisoformat(step.replace("Z", "+00:00")).astimezone(TZ)
    cloud = cloud_to_pct(p.get("fraction-of-cloud-cover"))
    rain = rate_to_mmh(p.get("rain-precipitation-rate"))
    ptype = ptype_name(p.get("precipitation-type"))
    lightning = probability_to_pct(p.get("probability-of-lightning"))
    code = classify_weather(cloud, rain, ptype, lightning)
    return {
        "time": dt.isoformat(timespec="minutes"),
        "temperature": k_to_c(p.get("temperature-2m")),
        "wind": round(float(p["wind-speed-10m"]), 1) if p.get("wind-speed-10m") is not None else None,
        "windDirection": round(float(p["wind-dir-10m"])) if p.get("wind-dir-10m") is not None else None,
        "windDirectionText": wind_dir_text(p.get("wind-dir-10m")),
        "gust": round(float(p["gust-wind-speed-10m"]), 1) if p.get("gust-wind-speed-10m") is not None else None,
        "rainMmH": rain,
        "precipitationType": ptype,
        "cloudCover": cloud,
        "lightningProbability": lightning,
        "weather": code,
        "weatherLabel": weather_label(code),
    }


def summarize_day(day, rows):
    temps = [r["temperature"] for r in rows if r["temperature"] is not None]
    winds = [r["wind"] for r in rows if r["wind"] is not None]
    gusts = [r["gust"] for r in rows if r["gust"] is not None]
    rain = [r["rainMmH"] or 0 for r in rows]
    daylight_rows = [r for r in rows if 8 <= datetime.fromisoformat(r["time"]).hour <= 20] or rows
    codes = [r["weather"] for r in daylight_rows]
    severity = ["thunder", "heavy_rain", "snow", "sleet", "freezing_rain", "rain", "light_rain", "overcast", "cloudy", "partly_cloudy", "clear"]
    dominant = next((c for c in severity if c in codes), "clear")
    dirs = [r["windDirection"] for r in rows if r["windDirection"] is not None]
    mean_dir = None
    if dirs:
        x = sum(math.sin(math.radians(d)) for d in dirs)
        y = sum(math.cos(math.radians(d)) for d in dirs)
        mean_dir = (math.degrees(math.atan2(x, y)) + 360) % 360
    total_rain = round(sum(rain), 1)
    text_bits = [weather_label(dominant)]
    if temps:
        text_bits.append(f"{round(max(temps))} grader")
    if total_rain >= 0.1:
        text_bits.append(f"omkring {total_rain:g} mm nedbør")
    if winds:
        wd = wind_dir_text(mean_dir) if mean_dir is not None else ""
        text_bits.append(f"vind {wd} {round(sum(winds)/len(winds))} m/s".strip())
    return {
        "date": day,
        "temperatureMin": round(min(temps), 1) if temps else None,
        "temperatureMax": round(max(temps), 1) if temps else None,
        "rainMm": total_rain,
        "windAvg": round(sum(winds) / len(winds), 1) if winds else None,
        "gustMax": round(max(gusts), 1) if gusts else None,
        "windDirection": round(mean_dir) if mean_dir is not None else None,
        "windDirectionText": wind_dir_text(mean_dir),
        "weather": dominant,
        "weatherLabel": weather_label(dominant),
        "summary": ", ".join(text_bits) + ".",
    }


def main():
    url = build_url()
    print("Fetching a five day DMI forecast for Sortsoe Strand")
    data = fetch_json(url)
    features = data.get("features", [])
    rows = [r for r in (parse_step(f) for f in features) if r]
    rows.sort(key=lambda r: r["time"])
    now = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
    rows = [r for r in rows if datetime.fromisoformat(r["time"]) >= now]
    if not rows:
        raise RuntimeError("DMI returned no future forecast rows")
    by_day = {}
    for r in rows:
        d = datetime.fromisoformat(r["time"]).date().isoformat()
        by_day.setdefault(d, []).append(r)
    days = [summarize_day(day, vals) for day, vals in sorted(by_day.items())]
    geometry = features[0].get("geometry", {}) if features else {}
    model_coords = geometry.get("coordinates") if geometry.get("type") == "Point" else None
    payload = {
        "location": {
            "name": "Sortsø Strand",
            "latitude": LAT,
            "longitude": LON,
            "timezone": "Europe/Copenhagen",
            "modelPoint": {
                "longitude": model_coords[0] if model_coords else None,
                "latitude": model_coords[1] if model_coords else None,
            },
        },
        "source": {
            "provider": "DMI",
            "model": "HARMONIE DINI surface",
            "collection": COLLECTION,
            "api": "Forecast Data EDR API",
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
        "currentForecast": rows[0],
        "hours": rows[:120],
        "days": days[:5],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} with {len(payload['hours'])} hourly rows and {len(payload['days'])} days")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
