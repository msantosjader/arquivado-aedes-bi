#!/usr/bin/env python3
"""Baixa e agrega clima diário do Open-Meteo para os centroides das áreas."""
import argparse
import gzip
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from shapely.geometry import shape

API = "https://archive-api.open-meteo.com/v1/archive"
TIMEZONE = "America/Recife"
MODEL = "ecmwf_ifs025"
BATCH_SIZE = 50
DAILY_VARIABLES = ",".join([
    "temperature_2m_mean",
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
    "precipitation_hours",
])


def area_points(path):
    source = json.loads(path.read_text(encoding="utf-8"))
    points = []
    for feature in source["features"]:
        point = shape(feature["geometry"]).representative_point()
        points.append({
            "area_id": feature["properties"]["ID"],
            "latitude": round(point.y, 6),
            "longitude": round(point.x, 6),
        })
    return points


def weather_points(path):
    groups = {}
    for point in area_points(path):
        key = (round(point["latitude"] * 4) / 4, round(point["longitude"] * 4) / 4)
        groups.setdefault(key, []).append(point["area_id"])
    return [
        {"area_ids": area_ids, "latitude": latitude, "longitude": longitude}
        for (latitude, longitude), area_ids in groups.items()
    ]


def fetch_batch(path, points, start, end, refresh=False):
    if path.exists() and not refresh:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    params = {
        "latitude": ",".join(str(point["latitude"]) for point in points),
        "longitude": ",".join(str(point["longitude"]) for point in points),
        "start_date": start,
        "end_date": end,
        "daily": DAILY_VARIABLES,
        "timezone": TIMEZONE,
        "models": MODEL,
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
    }
    for attempt in range(3):
        response = requests.get(API, params=params, timeout=180)
        if response.status_code != 429 or attempt == 2:
            response.raise_for_status()
            break
        delay = int(response.headers.get("Retry-After", 60))
        print(f"Open-Meteo limitou a consulta; aguardando {delay}s")
        time.sleep(delay)
    payload = response.json()
    if isinstance(payload, dict):
        payload = [payload]
    record = {"request": response.url, "areas": points, "responses": payload}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False)
    return record


def daily_rows(record):
    rows = []
    for point, response in zip(record["areas"], record["responses"]):
        daily = response.get("daily", {})
        area_ids = point.get("area_ids", [point.get("area_id")])
        for area_id in area_ids:
            for index, day in enumerate(daily.get("time", [])):
                rows.append({
                    "area_id": area_id,
                    "data": day,
                    "weather_lat": response.get("latitude"),
                    "weather_lon": response.get("longitude"),
                    "elevacao_m": response.get("elevation"),
                    "temperatura_media": (daily.get("temperature_2m_mean") or [None])[index],
                    "temperatura_minima": (daily.get("temperature_2m_min") or [None])[index],
                    "temperatura_maxima": (daily.get("temperature_2m_max") or [None])[index],
                    "chuva_mm": (daily.get("precipitation_sum") or [None])[index],
                    "horas_precipitacao": (daily.get("precipitation_hours") or [None])[index],
                })
    return rows


def write_table(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    frame.to_parquet(path.with_suffix(".parquet"), index=False)


def run(year, data, refresh=False):
    start = f"{year}-01-01"
    end = f"{year}-12-31" if year < date.today().year else date.today().isoformat()
    points = weather_points(data / "curated" / "areas_recife.geojson")
    records = []
    for offset in range(0, len(points), BATCH_SIZE):
        batch = points[offset:offset + BATCH_SIZE]
        path = data / "raw" / "open_meteo" / f"clima_grid_{year}_{offset // BATCH_SIZE:02d}.json.gz"
        records.append(fetch_batch(path, batch, start, end, refresh))

    daily = pd.DataFrame([row for record in records for row in daily_rows(record)])
    daily["data"] = pd.to_datetime(daily["data"])
    daily["ano"] = daily["data"].dt.year
    daily["mes"] = daily["data"].dt.month
    daily["dia_chuvoso"] = daily["chuva_mm"].fillna(0) > 0
    write_table(daily, data / "analytics" / "clima" / "diario" / f"clima_{year}.parquet")

    monthly = daily.groupby(["area_id", "ano", "mes", "weather_lat", "weather_lon"], as_index=False).agg(
        temperatura_media=("temperatura_media", "mean"),
        temperatura_minima=("temperatura_minima", "min"),
        temperatura_maxima=("temperatura_maxima", "max"),
        chuva_acumulada_mm=("chuva_mm", "sum"),
        horas_precipitacao=("horas_precipitacao", "sum"),
        dias_chuvosos=("dia_chuvoso", "sum"),
    )
    observed = daily.groupby(["area_id", "ano", "mes"], as_index=False).size()
    monthly = monthly.merge(observed, on=["area_id", "ano", "mes"], how="left").rename(columns={"size": "dias_observados"})
    write_table(monthly, data / "analytics" / "clima" / "mensal" / f"clima_{year}.parquet")
    print(f"clima {year}: {len(daily)} registros diários | {len(monthly)} registros mensais")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", type=int, action="append", required=True)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    for year in args.ano:
        run(year, args.data, args.refresh)


if __name__ == "__main__":
    main()
