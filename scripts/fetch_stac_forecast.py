#!/usr/bin/env python3
from __future__ import annotations

import json, math, os, random, socket, sys, tempfile, time
import urllib.error, urllib.parse, urllib.request
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
MIN_COMPLETE_STEPS = int(os.getenv("MIN_COMPLETE_STEPS", "50"))
WANTED = {"2t", "10si", "10wdir", "gust", "cc", "tp", "2r", "pres"}


def backoff(attempt, retry_after=None):
    try: header = float(retry_after) if retry_after else 0.0
    except (TypeError, ValueError): header = 0.0
    return max(header, min(60.0, 4.0 * (2 ** attempt))) + random.uniform(1.0, 4.0)


def open_with_retry(url, accept="*/*"):
    headers = {"User-Agent": "strandvejr.dk DMI STAC forecast/1.1", "Accept": accept}
    for attempt in range(MAX_RETRIES + 1):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= MAX_RETRIES: raise
            delay = backoff(attempt, exc.headers.get("Retry-After")); print(f"HTTP 429. Retry in {delay:.1f}s", file=sys.stderr); time.sleep(delay)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            if attempt >= MAX_RETRIES: raise
            delay = backoff(attempt); print(f"Temporary error: {exc}. Retry in {delay:.1f}s", file=sys.stderr); time.sleep(delay)
    raise RuntimeError("Request failed after retries")


def get_json(url):
    with open_with_retry(url, "application/geo+json, application/json") as response: return json.load(response)


def download_file(url, path):
    total = 0
    with open_with_retry(url, "application/x-grib, application/octet-stream, */*") as response, open(path, "wb") as fh:
        while True:
            chunk = response.read(8 * 1024 * 1024)
            if not chunk: break
            fh.write(chunk); total += len(chunk)
    return total


def parse_dt(value): return datetime.fromisoformat(value.replace("Z", "+00:00"))


def find_latest_complete_run():
    endpoint = f"{BASE}/collections/{COLLECTION}/items"
    data = get_json(endpoint + "?" + urllib.parse.urlencode({"limit": 1000}))
    groups = defaultdict(list)
    for f in data.get("features", []):
        run = f.get("properties", {}).get("modelRun")
        if run: groups[run].append(f)
    if not groups: raise RuntimeError("No HARMONIE model runs found")
    candidates = sorted(groups.items(), key=lambda x: x[0], reverse=True)
    for run, features in candidates:
        valid_times = {f.get("properties", {}).get("datetime") for f in features if f.get("properties", {}).get("datetime")}
        if len(valid_times) >= MIN_COMPLETE_STEPS:
            return run, features
    raise RuntimeError("No sufficiently complete HARMONIE run found")


def fetch_run_items(model_run, fallback):
    endpoint = f"{BASE}/collections/{COLLECTION}/items"
    data = get_json(endpoint + "?" + urllib.parse.urlencode({"modelRun": model_run, "limit": 1000}))
    return data.get("features", []) or fallback


def selected_items(model_run, features):
    run_dt = parse_dt(model_run); selected = []
    for f in features:
        valid = f.get("properties", {}).get("datetime"); href = f.get("asset", {}).get("data", {}).get("href")
        if not valid or not href: continue
        lead = round((parse_dt(valid) - run_dt).total_seconds() / 3600)
        if 0 <= lead <= MAX_FORECAST_HOURS and lead % STEP_HOURS == 0: selected.append((lead, f))
    selected.sort(key=lambda x: x[0])
    if len(selected) < 15: raise RuntimeError(f"Only {len(selected)} selected forecast steps found")
    return selected


def safe_get(gid, key, default=None):
    try: return codes_get(gid, key)
    except Exception: return default


def read_point(path):
    found = {}; model_point = None
    with open(path, "rb") as fh:
        while True:
            gid = codes_grib_new_from_file(fh)
            if gid is None: break
            try:
                name = str(safe_get(gid, "shortName", ""))
                if name not in WANTED or name in found: continue
                if name == "2t" and str(safe_get(gid, "stepType", "")) not in {"instant", ""}: continue
                nearest = codes_grib_find_nearest(gid, LAT, LON)[0]
                found[name] = float(nearest.value)
                if model_point is None:
                    model_point = {"latitude": float(nearest.lat), "longitude": float(nearest.lon), "distanceKm": round(float(nearest.distance), 3)}
                if WANTED.issubset(found): break
            finally: codes_release(gid)
    return found, model_point


def wind_dir_text(deg):
    if deg is None: return None
    dirs = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]
    return dirs[int((deg + 22.5) // 45) % 8]


def weather_code(cloud, rain_mm):
    c = cloud or 0; r = rain_mm or 0
    if r >= 8: return "heavy_rain"
    if r >= 1: return "rain"
    if r >= 0.1: return "light_rain"
    if c >= 88: return "overcast"
    if c >= 60: return "cloudy"
    if c >= 25: return "partly_cloudy"
    return "clear"


def weather_label(code):
    return {"clear":"Klart","partly_cloudy":"Let skyet","cloudy":"Skyet","overcast":"Overskyet","light_rain":"Let regn","rain":"Regn","heavy_rain":"Kraftig regn"}.get(code,"Vejr")


def make_row(valid_time, lead, raw, rain_mm):
    local = parse_dt(valid_time).astimezone(TZ)
    temp = round(raw["2t"] - 273.15, 1) if "2t" in raw else None
    cloud = round(raw["cc"] * 100 if raw.get("cc", 0) <= 1.2 else raw["cc"]) if "cc" in raw else None
    wind = round(raw["10si"], 1) if "10si" in raw else None
    wind_dir = round(raw["10wdir"]) if "10wdir" in raw else None
    gust = round(raw["gust"], 1) if "gust" in raw else None
    humidity = round(raw["2r"]) if "2r" in raw else None
    pressure = round(raw["pres"] / 100.0, 1) if "pres" in raw else None
    code = weather_code(cloud, rain_mm)
    return {"time": local.isoformat(timespec="minutes"), "leadHours": lead, "temperature": temp, "wind": wind, "gust": gust, "windDirection": wind_dir, "windDirectionText": wind_dir_text(wind_dir), "cloudCover": cloud, "rainMm": round(rain_mm,2) if rain_mm is not None else None, "humidity": humidity, "pressure": pressure, "weather": code, "weatherLabel": weather_label(code)}


def summarize_days(rows):
    groups = defaultdict(list)
    for row in rows: groups[row["time"][:10]].append(row)
    days = []
    severity = ["heavy_rain","rain","light_rain","overcast","cloudy","partly_cloudy","clear"]
    for day, vals in sorted(groups.items()):
        temps=[v["temperature"] for v in vals if v["temperature"] is not None]; winds=[v["wind"] for v in vals if v["wind"] is not None]; gusts=[v["gust"] for v in vals if v.get("gust") is not None]; rains=[v["rainMm"] or 0 for v in vals]
        codes=[v["weather"] for v in vals]; dominant=next((c for c in severity if c in codes), Counter(codes).most_common(1)[0][0])
        dirs=[v["windDirection"] for v in vals if v["windDirection"] is not None]; mean_dir=None
        if dirs:
            x=sum(math.sin(math.radians(d)) for d in dirs); y=sum(math.cos(math.radians(d)) for d in dirs); mean_dir=(math.degrees(math.atan2(x,y))+360)%360
        total_rain=round(sum(rains),1); avg_wind=round(sum(winds)/len(winds),1) if winds else None
        text=weather_label(dominant)
        if temps: text += f", {round(min(temps))} til {round(max(temps))} grader"
        if total_rain >= 0.1: text += f", omkring {total_rain:g} mm nedbør"
        if avg_wind is not None: text += f", vind {wind_dir_text(mean_dir)} omkring {round(avg_wind)} m/s"
        days.append({"date":day,"temperatureMin":round(min(temps),1) if temps else None,"temperatureMax":round(max(temps),1) if temps else None,"rainMm":total_rain,"windAvg":avg_wind,"gustMax":round(max(gusts),1) if gusts else None,"windDirectionText":wind_dir_text(mean_dir),"weather":dominant,"weatherLabel":weather_label(dominant),"summary":text+"."})
    return days


def main():
    print("Finding newest complete HARMONIE DINI surface run")
    model_run, fallback = find_latest_complete_run(); print(f"Selected modelRun: {model_run}")
    features = fetch_run_items(model_run, fallback); items = selected_items(model_run, features); print(f"Downloading {len(items)} GRIB steps at {STEP_HOURS} hour intervals")
    rows=[]; model_point=None; total_bytes=0; previous_tp=None
    for index,(lead,item) in enumerate(items,1):
        valid=item.get("properties",{}).get("datetime"); href=item.get("asset",{}).get("data",{}).get("href"); print(f"[{index}/{len(items)}] +{lead:02d}h {valid}")
        with tempfile.NamedTemporaryFile(suffix=".grib", delete=False) as tmp: temp_path=tmp.name
        try:
            size=download_file(href,temp_path); total_bytes += size; raw,point=read_point(temp_path)
            if model_point is None and point: model_point=point
            tp=raw.get("tp"); rain_mm=0.0 if previous_tp is None else max(0.0, tp-previous_tp) if tp is not None and previous_tp is not None else None
            if tp is not None: previous_tp=tp
            row=make_row(valid,lead,raw,rain_mm); rows.append(row); print(f"  {size/1_000_000:.1f} MB | {row['temperature']} C | {row['wind']} m/s | rain {row['rainMm']} mm | {row['weatherLabel']}")
        finally:
            try: os.unlink(temp_path)
            except OSError: pass
    if not rows: raise RuntimeError("No forecast rows were produced")
    payload={"location":{"name":"Sortsø Strand","latitude":LAT,"longitude":LON,"timezone":"Europe/Copenhagen","modelPoint":model_point},"source":{"provider":"DMI","api":"Forecast Data STAC API","model":"HARMONIE DINI surface","collection":COLLECTION,"modelRun":model_run,"intervalHours":STEP_HOURS,"generated":datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"),"downloadedBytes":total_bytes},"currentForecast":rows[0],"hours":rows,"days":summarize_days(rows)}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(f"Wrote {OUT}: {len(rows)} points, {total_bytes/1_000_000_000:.2f} GB")

if __name__ == "__main__":
    try: main()
    except Exception as exc: print(f"ERROR: {exc}",file=sys.stderr); raise
