#!/usr/bin/env python3
"""Baixa a série anual da COMPESA e prepara o mapa temporal do Recife."""
import argparse
import csv
import gzip
import json
import time
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from shapely import make_valid
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

ROOT = "https://geo.compesa.com.br:6443/arcgis/rest/services/Calendario/Calendario/MapServer"
RECIFE_IBGE = "2611606"
FRAC_MIN_RECIFE = 0.05
DEFAULT_OUT = Path("data")
SESSION = requests.Session()


def api_post(url, **params):
    params.setdefault("f", "json")
    for attempt in range(3):
        try:
            response = SESSION.post(url, data=params, timeout=180)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return payload
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2**attempt)


def query_ids(layer, where):
    return api_post(f"{ROOT}/{layer}/query", where=where, returnIdsOnly="true").get("objectIds") or []


def query_features(layer, where, geometry=False, batch=200):
    ids = query_ids(layer, where)
    features = []
    for start in range(0, len(ids), batch):
        features.extend(api_post(
            f"{ROOT}/{layer}/query",
            objectIds=",".join(map(str, ids[start:start + batch])),
            outFields="*",
            returnGeometry=str(geometry).lower(),
            outSR=4326,
        ).get("features", []))
        time.sleep(0.2)
    return features


def query_features_for_ids(layer, field, ids, date_where, batch=100):
    """Consulta apenas as áreas de interesse, evitando varrer Pernambuco inteiro."""
    features = []
    for start in range(0, len(ids), batch):
        values = ",".join("'" + str(value).replace("'", "''") + "'" for value in ids[start:start + batch])
        features.extend(query_features(layer, f"{field} IN ({values}) AND ({date_where})"))
    return features


def raw_path(out, name, year=None, snapshot=False):
    folder = out / "raw" / "compesa" / name
    folder.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%Y-%m-%d") if snapshot else str(year)
    return folder / f"{name}_{suffix}.jsonl.gz"


def load_or_fetch(path, fetch):
    if path.exists() and path.stat().st_size:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream if line.strip()]
    records = fetch()
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return records


def utc_dates(frame, columns):
    for column in columns:
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], unit="ms", utc=True)
    return frame


def union_hours(intervals, start, end):
    clipped = sorted((max(a, start), min(b, end)) for a, b in intervals if a < end and b > start)
    total = 0
    current = None
    for left, right in clipped:
        if right <= left:
            continue
        if current is None:
            current = [left, right]
        elif left <= current[1]:
            current[1] = max(current[1], right)
        else:
            total += current[1] - current[0]
            current = [left, right]
    if current:
        total += current[1] - current[0]
    return total / 3_600_000


def daily_status(intervals, events, year, month):
    """Classifica cada dia do mês pelo total de horas abastecidas."""
    integral = partial = without_supply = maintenance = 0
    for day in range(1, monthrange(year, month)[1] + 1):
        start = int(pd.Timestamp(year=year, month=month, day=day, tz="UTC").timestamp() * 1000)
        end = start + 24 * 3_600_000
        hours = union_hours(intervals, start, end)
        if hours >= 24 - 1e-6:
            integral += 1
        elif hours > 0:
            partial += 1
        else:
            without_supply += 1
        if any(
            event.get("INICIO_PREVISTO") is not None
            and event.get("TERMINO_PREVISTO") is not None
            and event["INICIO_PREVISTO"] < end
            and event["TERMINO_PREVISTO"] > start
            for event in events
        ):
            maintenance += 1
    total_days = monthrange(year, month)[1]
    return {
        "dias_abastecimento_integral": integral,
        "dias_abastecimento_parcial": partial,
        "dias_sem_abastecimento": without_supply,
        "dias_manutencao_programada": maintenance,
        "percentual_dias_integral": round(100 * integral / total_days, 4),
        "percentual_dias_parcial": round(100 * partial / total_days, 4),
        "percentual_dias_sem_abastecimento": round(100 * without_supply / total_days, 4),
        "percentual_dias_manutencao": round(100 * maintenance / total_days, 4),
    }


def write_table(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    try:
        frame.to_parquet(path.with_suffix(".parquet"), index=False)
    except ImportError:
        print("aviso: instale pyarrow para gerar também os arquivos Parquet")


def esri_to_shapely(rings):
    """Converte anéis Esri em uma geometria Shapely válida."""
    exteriores, furos = [], []
    for ring in rings or []:
        if len(ring) < 4:
            continue
        signed_area = sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])
        ) / 2
        (exteriores if signed_area < 0 else furos).append(make_valid(Polygon(ring)))
    if not exteriores:
        exteriores, furos = furos, []
    geometry = unary_union(exteriores) if exteriores else Polygon()
    if furos:
        geometry = geometry.difference(unary_union(furos))
    return make_valid(geometry)


def recife_boundary(out):
    path = out / "curated" / "limites" / "recife.geojson"
    if path.exists() and path.stat().st_size:
        return json.loads(path.read_text(encoding="utf-8"))
    response = SESSION.get(
        f"https://servicodados.ibge.gov.br/api/v3/malhas/municipios/{RECIFE_IBGE}",
        params={"formato": "application/vnd.geo+json", "qualidade": "maxima"},
        timeout=180,
    )
    response.raise_for_status()
    boundary = response.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(boundary, ensure_ascii=False), encoding="utf-8")
    return boundary


def boundary_geometry(geojson):
    features = geojson.get("features", [geojson])
    return make_valid(unary_union([shape(feature["geometry"]) for feature in features]))


def prepare_recife_areas(areas_all, boundary, out):
    """Seleciona e recorta áreas que têm pelo menos 5% dentro do Recife."""
    grouped = {}
    for feature in areas_all:
        attrs = feature.get("attributes", {})
        area_id = attrs.get("ID")
        geometry = feature.get("geometry")
        if not area_id or not geometry:
            continue
        grouped.setdefault(area_id, {"attrs": attrs, "geometries": []})["geometries"].append(
            esri_to_shapely(geometry.get("rings", []))
        )

    municipal = boundary_geometry(boundary)
    selected = []
    for area_id, item in grouped.items():
        original = make_valid(unary_union(item["geometries"]))
        if original.is_empty or not original.area:
            continue
        clipped = make_valid(original.intersection(municipal))
        if clipped.is_empty or clipped.area / original.area < FRAC_MIN_RECIFE:
            continue
        attrs = dict(item["attrs"])
        attrs["FRAC_AREA_RECIFE"] = clipped.area / original.area
        selected.append({"attributes": attrs, "geometry": mapping(clipped)})

    output = out / "curated" / "areas_recife.geojson"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": f["geometry"], "properties": f["attributes"]} for f in selected],
    }, ensure_ascii=False), encoding="utf-8")
    return selected


def build_monthly(year, areas, periods, services, out):
    area_attrs = {a["attributes"]["ID"]: a["attributes"] for a in areas}
    area_ids = set(area_attrs)
    period_map = {area_id: [] for area_id in area_ids}
    for feature in periods:
        attr = feature["attributes"]
        if attr.get("ID") in area_ids and attr.get("colapso", 0) == 0:
            period_map[attr["ID"]].append((attr.get("Inicio"), attr.get("Termino")))

    service_map = {area_id: [] for area_id in area_ids}
    for feature in services:
        attr = feature["attributes"]
        if attr.get("ID_AREA_ABASTECIMENTO") in area_ids:
            service_map[attr["ID_AREA_ABASTECIMENTO"]].append(attr)

    rows = []
    for month in range(1, 13):
        start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
        end = start + pd.offsets.MonthBegin(1)
        start_ms, end_ms = start.value // 10**6, end.value // 10**6
        month_hours = (end - start).total_seconds() / 3600
        for area_id, attrs in area_attrs.items():
            intervals = [(int(a), int(b)) for a, b in period_map[area_id] if a is not None and b is not None]
            supply_hours = union_hours(intervals, start_ms, end_ms)
            events = [event for event in service_map[area_id]
                      if event.get("INICIO_PREVISTO", 0) < end_ms and event.get("TERMINO_PREVISTO", 0) > start_ms]
            types = sorted({str(event.get("NATUREZA_SERVICOS")) for event in events if event.get("NATUREZA_SERVICOS")})
            daily = daily_status(intervals, events, year, month)
            rows.append({
                "area_id": area_id,
                "municipio": attrs.get("MUNICIPIOS"),
                "area_nome": attrs.get("NOMABAST"),
                "calendario_nome": attrs.get("NOMECALEND"),
                "bairros": attrs.get("BAIRROS"),
                "sistema": attrs.get("NOMSIS"),
                "setor_operacional": attrs.get("NOMSETOPER"),
                "distrito": attrs.get("NOMDIST"),
                "localidade": attrs.get("localidade"),
                "economias_cadastradas": attrs.get("Quantidade_de_Economias"),
                "matriculas": attrs.get("Quantidade_de_Matriculas"),
                "ligacoes_residenciais": attrs.get("Ligações_Residenciais"),
                "ligacoes_ligadas": attrs.get("Ligações_Ligadas"),
                "frac_area_recife": attrs.get("FRAC_AREA_RECIFE", 1),
                "ano": year,
                "mes": month,
                "horas_mes": round(month_hours, 2),
                "horas_abastecimento_calendario": round(supply_hours, 2),
                "horas_sem_abastecimento_previsto": round(max(month_hours - supply_hours, 0), 2),
                "percentual_abastecimento_calendario": round(100 * supply_hours / month_hours, 4),
                "calendario_status": "completo" if supply_hours >= month_hours * 0.999 else ("parcial" if supply_hours else "sem_abastecimento"),
                "quantidade_intervencoes": len(events),
                "intervencao_prevista": bool(events),
                "tipos_intervencao": "; ".join(types),
                "qualidade_dado": "completo" if intervals else "sem_periodos",
                **daily,
            })
    result = pd.DataFrame(rows)
    write_table(result, out / "analytics" / "mensal" / f"indicadores_{year}.parquet")
    return result


def build_daily(year, areas, periods, services, out):
    """Expande os intervalos de abastecimento para uma linha por área e dia."""
    area_attrs = {a["attributes"]["ID"]: a["attributes"] for a in areas}
    area_ids = set(area_attrs)
    period_map = {area_id: [] for area_id in area_ids}
    for feature in periods:
        attr = feature["attributes"]
        if attr.get("ID") in area_ids and attr.get("colapso", 0) == 0:
            period_map[attr["ID"]].append((attr.get("Inicio"), attr.get("Termino")))
    service_map = {area_id: [] for area_id in area_ids}
    for feature in services:
        attr = feature["attributes"]
        if attr.get("ID_AREA_ABASTECIMENTO") in area_ids:
            service_map[attr["ID_AREA_ABASTECIMENTO"]].append(attr)

    rows = []
    for day in pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D"):
        start = pd.Timestamp(day, tz="UTC")
        end = start + pd.Timedelta(days=1)
        start_ms, end_ms = start.value // 10**6, end.value // 10**6
        for area_id, attrs in area_attrs.items():
            intervals = [(int(a), int(b)) for a, b in period_map[area_id] if a is not None and b is not None]
            events = [event for event in service_map[area_id]
                      if event.get("INICIO_PREVISTO", 0) < end_ms and event.get("TERMINO_PREVISTO", 0) > start_ms]
            hours = union_hours(intervals, start_ms, end_ms)
            rows.append({
                "area_id": area_id,
                "data": day.date().isoformat(),
                "ano": year,
                "mes": day.month,
                "horas_abastecimento": round(hours, 4),
                "horas_sem_abastecimento": round(max(24 - hours, 0), 4),
                "percentual_abastecimento": round(100 * hours / 24, 4),
                "sem_abastecimento": hours == 0,
                "abastecimento_integral": hours >= 24 - 1e-6,
                "manutencao_programada": bool(events),
                "qualidade_dado": "completo" if intervals else "sem_periodos",
                "municipio": attrs.get("MUNICIPIOS"),
            })
    result = pd.DataFrame(rows)
    write_table(result, out / "analytics" / "diario" / f"abastecimento_{year}.parquet")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    ini, fim = f"{args.ano}-01-01", f"{args.ano + 1}-01-01"
    period_where = f"Inicio < '{fim}' AND Termino >= '{ini}'"
    service_where = f"INICIO_PREVISTO < '{fim}' AND TERMINO_PREVISTO >= '{ini}'"

    area_file = raw_path(args.out, "areas", snapshot=True)
    period_file = raw_path(args.out, "periodos", args.ano)
    service_file = raw_path(args.out, "servicos", args.ano)
    if args.refresh:
        for path in (area_file, period_file, service_file):
            if path.exists():
                path.unlink()

    areas_all = load_or_fetch(area_file, lambda: query_features(0, "1=1", geometry=True, batch=50))
    boundary = recife_boundary(args.out)
    areas = prepare_recife_areas(areas_all, boundary, args.out)
    area_ids = {feature["attributes"]["ID"] for feature in areas}
    periods_all = load_or_fetch(
        period_file,
        lambda: query_features_for_ids(5, "ID", sorted(area_ids), period_where),
    )
    services_all = load_or_fetch(
        service_file,
        lambda: query_features_for_ids(2, "ID_AREA_ABASTECIMENTO", sorted(area_ids), service_where),
    )
    periods = [f for f in periods_all if f["attributes"].get("ID") in area_ids]
    services = [f for f in services_all if f["attributes"].get("ID_AREA_ABASTECIMENTO") in area_ids]

    curated = pd.DataFrame([f["attributes"] for f in periods])
    utc_dates(curated, ["Inicio", "Termino"])
    write_table(curated, args.out / "curated" / "periodos_recife" / f"periodos_{args.ano}.parquet")
    curated_services = pd.DataFrame([f["attributes"] for f in services])
    utc_dates(curated_services, ["INICIO_PREVISTO", "TERMINO_PREVISTO"])
    write_table(curated_services, args.out / "curated" / "servicos_recife" / f"servicos_{args.ano}.parquet")
    monthly = build_monthly(args.ano, areas, periods, services, args.out)
    daily = build_daily(args.ano, areas, periods, services, args.out)
    print(f"áreas Recife: {len(area_ids)} | períodos: {len(periods)} | serviços: {len(services)}")
    print(f"indicadores mensais: {len(monthly)} | diários: {len(daily)}")


if __name__ == "__main__":
    main()
