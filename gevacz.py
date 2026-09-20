#!/usr/bin/env python3
"""Normaliza as planilhas de EDLs e ovitrampas da GEVACZ."""
import argparse
import re
import unicodedata
from pathlib import Path

import pandas as pd
import geopandas as gpd
import numpy as np
from pyproj import Transformer
from shapely.geometry import Point
from shapely.ops import transform, unary_union


def text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def key(value):
    value = unicodedata.normalize("NFKD", text(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def number(value):
    value = text(value).replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def coordinate(value, longitude=False):
    value = re.sub(r"(?<=\d)\.\s+(?=\d)", ".", text(value).replace(",", "."))
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    result = float(match.group())
    if abs(result) > (180 if longitude else 90):
        digits = re.sub(r"\D", "", match.group())
        places = 2 if longitude else 1
        result = float(f"{digits[:places]}.{digits[places:]}")
    if result > 0:
        result = -result
    return result


def coordinates(first, second=None):
    first, second = text(first), text(second)
    parts = re.split(r"\s*[,;]\s*", first)
    if len(parts) >= 2:
        return coordinate(parts[0]), coordinate(parts[1], longitude=True)
    if second:
        return coordinate(first), coordinate(second, longitude=True)
    return None, None


def valid_coordinates(row):
    latitude, longitude = row.latitude, row.longitude
    return pd.notna(latitude) and pd.notna(longitude) and -9 < latitude < -7 and -36 < longitude < -34


def classify_geography(frame, data):
    """Distingue pontos fora do município e pontos sem área operacional."""
    if frame.empty:
        return frame
    frame["qualidade_geografica"] = "sem_coordenada"
    valid = frame["qualidade_coordenada"].eq("valida")
    if not valid.any():
        return frame
    boundary_path = data / "curated" / "limites" / "recife.geojson"
    areas_path = data / "curated" / "areas_recife.geojson"
    if not boundary_path.exists():
        frame.loc[valid, "qualidade_geografica"] = "nao_auditada"
        return frame
    subset = frame.loc[valid].copy()
    points = gpd.GeoDataFrame(subset, geometry=gpd.points_from_xy(subset.longitude, subset.latitude), crs=4326)
    boundary = unary_union(gpd.read_file(boundary_path).to_crs(4326).geometry)
    inside_boundary = points.geometry.within(boundary)
    frame.loc[subset.index[~inside_boundary.to_numpy()], "qualidade_geografica"] = "fora_recife"
    frame.loc[subset.index[inside_boundary.to_numpy()], "qualidade_geografica"] = "valida"
    if areas_path.exists():
        operational = unary_union(gpd.read_file(areas_path).to_crs(4326).geometry)
        inside_area = points.loc[inside_boundary].geometry.within(operational)
        frame.loc[inside_area.index[~inside_area.to_numpy()], "qualidade_geografica"] = "sem_area_compesa"
    return frame


def header_row(raw, required):
    for index, row in raw.iterrows():
        values = {key(value) for value in row.tolist()}
        if all(any(item in value for value in values) for item in required):
            return index
    return None


def unique_columns(values):
    result, counts = [], {}
    for value in values:
        name = key(value) or "coluna"
        counts[name] = counts.get(name, 0) + 1
        result.append(name if counts[name] == 1 else f"{name}_{counts[name]}")
    return result


def ovt_key(value):
    return re.sub(r"[^A-Z0-9]", "", text(value).upper())


def read_sheets(path):
    for sheet in pd.ExcelFile(path).sheet_names:
        yield sheet, pd.read_excel(path, sheet_name=sheet, header=None)


def read_edls(root):
    rows = []
    path = root / "TOTAL DE EDL POR DS.xlsx"
    for sheet, raw in read_sheets(path):
        row_index = header_row(raw, ["nome_fantasia", "logradouro"])
        if row_index is None:
            continue
        district = re.search(r"DS\s*(\d+)", sheet, re.I)
        district = district.group(1) if district else ""
        for values in raw.iloc[row_index + 1 :].itertuples(index=False, name=None):
            values = list(values) + [None] * 15
            if number(values[0]) is None:
                continue
            latitude, longitude = coordinates(values[7], values[8])
            real = number(values[11]) if number(values[11]) is not None else number(values[10])
            rows.append({
                "edl_id": f"DS{district}_{int(number(values[0]))}",
                "distrito_sanitario": district,
                "bairro": text(values[6]),
                "nome_local": text(values[4]),
                "tipo_local": text(values[3]),
                "logradouro": text(values[5]),
                "latitude": latitude,
                "longitude": longitude,
                "edl_ideal": number(values[10]),
                "edl_real": real,
                "tamanho_area": text(values[9]),
                "arquivo_origem": str(path.relative_to(root)),
            })
    return pd.DataFrame(rows)


def read_georeferenced_ovts(root):
    rows = {}
    path = next(root.glob("Georreferenciamento OVT *.xlsx"), None)
    if path is None:
        return rows
    for sheet, raw in read_sheets(path):
        row_index = header_row(raw, ["id_ovt", "latitude", "longitude"])
        if row_index is None:
            continue
        columns = unique_columns(raw.iloc[row_index].tolist())
        for values in raw.iloc[row_index + 1 :].itertuples(index=False, name=None):
            record = dict(zip(columns, list(values) + [None] * len(columns)))
            ovt_id = text(record.get("id_ovt"))
            if not ovt_id:
                continue
            latitude, longitude = coordinates(record.get("latitude"), record.get("longitude"))
            rows[ovt_key(ovt_id)] = {
                "id_ovt": ovt_id,
                "bairro": text(record.get("bairro")),
                "latitude": latitude,
                "longitude": longitude,
                "endereco": text(record.get("endereco")),
                "arquivo_origem": str(path.relative_to(root)),
            }
    return rows


def read_ovitrampas(root, locations):
    rows = []
    source_files = [
        p for p in root.glob("**/*")
        if p.suffix.lower() in {".xlsx", ".xls", ".ods"} and not p.name.startswith("~$")
    ]
    for path in source_files:
        if (
            "TOTAL DE EDL" in path.name
            or path.name.startswith("Georreferenciamento OVT")
            or path.name.startswith("CONSOLIDADOS")
            or path.suffix.lower() != ".xlsx"
        ):
            continue
        for sheet, raw in read_sheets(path):
            row_index = header_row(raw, ["id_ovt", "n_ovos"])
            if row_index is None:
                continue
            frame = raw.iloc[row_index + 1 :].copy()
            frame.columns = unique_columns(raw.iloc[row_index].tolist())
            if "id_ovt" not in frame or "n_ovos" not in frame:
                continue
            for record in frame.to_dict("records"):
                ovt_id = text(record.get("id_ovt"))
                if not ovt_id:
                    continue
                location = locations.get(ovt_key(ovt_id), {})
                status = text(record.get("obs_f_fechado_e_extraviado_r_recusado_d_desocupado_rec_recuperada"))
                rows.append({
                    "id_ovt": ovt_id,
                    "ano_arquivo": number(record.get("ano")),
                    "ciclo": number(record.get("ciclos", record.get("ciclo"))),
                    "distrito_sanitario": text(record.get("ds")),
                    "bairro": text(record.get("bairro")) or location.get("bairro", ""),
                    "bairro_area": text(record.get("bairro_area")),
                    "latitude": location.get("latitude"),
                    "longitude": location.get("longitude"),
                    "endereco": location.get("endereco", ""),
                    "data_coleta": pd.to_datetime(record.get("dt_coleta"), errors="coerce"),
                    "data_entrega_apoio": pd.to_datetime(record.get("dt_entrega_apoio"), errors="coerce"),
                    "data_entrega_laboratorio": pd.to_datetime(record.get("dt_entrega_lab"), errors="coerce"),
                    "data_leitura": pd.to_datetime(record.get("dt_leitura"), errors="coerce"),
                    "data_digitacao": pd.to_datetime(record.get("dt_dig"), errors="coerce"),
                    "data_envio_ds": pd.to_datetime(record.get("dt_envio_ds"), errors="coerce"),
                    "quantidade_palhetas": number(record.get("qt")),
                    "n_ovos": number(record.get("n_ovos")),
                    "status": status,
                    "arquivo_origem": str(path.relative_to(root)),
                    "aba_origem": sheet,
                    "formato_origem": "longo",
                })
    return pd.DataFrame(rows)


def read_wide_ovitrampas(root, locations, year):
    """Converte as planilhas 2024/2025, que têm três colunas por ciclo."""
    rows = []
    folder = root / f"OVITRAMPAS {year}"
    district_names = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7", "VIII": "8"}
    for path in sorted(folder.glob("Planilha OVT DS-*.xls")):
        district = district_names.get(path.stem.rsplit("-", 1)[-1], "")
        for sheet, raw in read_sheets(path):
            row_index = header_row(raw, ["id_ovt", "numero_ovos"])
            if row_index is None:
                continue
            for values in raw.iloc[row_index + 1 :].itertuples(index=False, name=None):
                values = list(values) + [None] * 84
                ovt_id = text(values[4])
                if not ovt_id or ovt_key(ovt_id) in {"IDO", "TOTAL"}:
                    continue
                location = locations.get(ovt_key(ovt_id), {})
                for ciclo in range(1, 27):
                    offset = 6 + (ciclo - 1) * 3
                    rows.append({
                        "id_ovt": ovt_id,
                        "ano_arquivo": year,
                        "ciclo": ciclo,
                        "distrito_sanitario": district,
                        "bairro": text(values[0]) or sheet,
                        "agente": text(values[1]),
                        "quantidade_palhetas": number(values[3]),
                        "latitude": location.get("latitude"),
                        "longitude": location.get("longitude"),
                        "endereco": location.get("endereco", ""),
                        "data_coleta_original": values[offset],
                        "data_coleta": pd.to_datetime(values[offset], errors="coerce"),
                        "n_ovos": number(values[offset + 1]),
                        "status": text(values[offset + 2]),
                        "arquivo_origem": str(path.relative_to(root)),
                        "aba_origem": sheet,
                        "formato_origem": "largo",
                    })
    return pd.DataFrame(rows)


def normalize_dates(observations):
    if observations.empty:
        return observations
    observations["ano_arquivo"] = pd.to_numeric(observations["ano_arquivo"], errors="coerce").astype("Int64")
    observations["data_coleta"] = pd.to_datetime(observations["data_coleta"], errors="coerce")
    observations["ano_coleta"] = observations["data_coleta"].dt.year.astype("Int64")
    observations["qualidade_data"] = "confirmada"
    observations.loc[observations["data_coleta"].isna(), "qualidade_data"] = "ausente"
    outside = observations["ano_coleta"].notna() & (observations["ano_coleta"] != observations["ano_arquivo"])
    observations.loc[outside, "qualidade_data"] = "transicao_de_ano"

    keys = ["id_ovt", "ciclo", "data_coleta", "n_ovos", "status"]
    duplicate = observations.duplicated(keys, keep=False) & outside
    observations.loc[duplicate, "qualidade_data"] = "duplicada"
    observations["data_suspeita"] = observations["qualidade_data"].isin(["ausente", "transicao_de_ano", "duplicada"])
    return observations


def build_cycle_summary(observations):
    if observations.empty:
        return pd.DataFrame()
    valid_dates = observations.dropna(subset=["data_coleta"])
    summary = valid_dates.groupby(["ano_arquivo", "ciclo"], as_index=False).agg(
        data_inicio_coleta=("data_coleta", "min"),
        data_fim_coleta=("data_coleta", "max"),
        data_referencia=("data_coleta", "median"),
        quantidade_observacoes=("id_ovt", "size"),
        quantidade_ovitrampas=("id_ovt", "nunique"),
    )
    summary["ciclo_id"] = summary["ano_arquivo"].astype(str) + " C" + summary["ciclo"].astype(str)
    return summary


def rolling_daily(frame, group_columns, date_column, measures):
    """Calcula janelas anteriores sem incluir o dia da coleta."""
    if frame.empty:
        return frame
    result = []
    for _, group in frame.sort_values(date_column).groupby(group_columns, dropna=False):
        group = group.sort_values(date_column).copy()
        for days in (7, 14, 21, 28):
            for column, operation in measures.items():
                shifted = group[column].shift(1)
                values = shifted.rolling(days, min_periods=days).agg(operation)
                group[f"{column}_{days}d"] = values.to_numpy()
        result.append(group)
    return pd.concat(result, ignore_index=True)


def build_analytical_table(observations, root, data):
    """Associa cada observação ao clima e abastecimento anteriores à coleta."""
    result = observations.copy()
    result["data"] = pd.to_datetime(result["data_coleta"], errors="coerce").dt.normalize()
    edl_path = data / "curated" / "gevacz" / "edls.parquet"
    if edl_path.exists():
        edls = pd.read_parquet(edl_path)
        edls = edls[edls["qualidade_coordenada"] == "valida"].dropna(subset=["latitude", "longitude"])
        if not edls.empty:
            project = Transformer.from_crs(4326, 31985, always_xy=True).transform
            edl_x, edl_y = project(edls.longitude.to_numpy(), edls.latitude.to_numpy())
            valid = result["latitude"].notna() & result["longitude"].notna()
            valid_index = result.index[valid]
            x, y = project(result.loc[valid, "longitude"].to_numpy(), result.loc[valid, "latitude"].to_numpy())
            distances = []
            for start in range(0, len(x), 20_000):
                distances.append(np.sqrt((x[start:start + 20_000, None] - edl_x[None, :]) ** 2 + (y[start:start + 20_000, None] - edl_y[None, :]) ** 2).min(axis=1))
            result.loc[valid_index, "distancia_edl_m"] = np.concatenate(distances)
            for radius in (50, 100, 150, 200):
                result[f"edl_a_{radius}m"] = result["distancia_edl_m"].le(radius)
    locations = result[["id_ovt", "latitude", "longitude"]].drop_duplicates("id_ovt")
    area_path = data / "curated" / "areas_recife.geojson"
    if area_path.exists() and not locations.empty:
        points = gpd.GeoDataFrame(
            locations.dropna(subset=["latitude", "longitude"]),
            geometry=gpd.points_from_xy(locations.dropna(subset=["latitude", "longitude"]).longitude, locations.dropna(subset=["latitude", "longitude"]).latitude),
            crs=4326,
        )
        areas = gpd.read_file(area_path)[["ID", "geometry"]]
        joined = gpd.sjoin(points, areas, how="left", predicate="within")
        area_by_ovt = joined.drop_duplicates("id_ovt").set_index("id_ovt")["ID"].rename("area_id")
        result = result.merge(area_by_ovt, on="id_ovt", how="left")
    else:
        result["area_id"] = pd.NA

    climate_frames = []
    for year in sorted(result["data"].dropna().dt.year.unique()):
        path = data / "analytics" / "clima" / "diario" / f"clima_{int(year)}.parquet"
        if path.exists():
            climate_frames.append(pd.read_parquet(path))
    climate = pd.concat(climate_frames, ignore_index=True) if climate_frames else pd.DataFrame()
    if not climate.empty and not result.empty:
        climate["data"] = pd.to_datetime(climate["data"]).dt.normalize()
        cells = climate[["weather_lat", "weather_lon"]].drop_duplicates().dropna().to_numpy()
        valid = result["latitude"].notna() & result["longitude"].notna()
        result.loc[valid, "weather_lat"] = result.loc[valid].apply(lambda row: min(cells, key=lambda cell: (cell[0] - row.latitude) ** 2 + (cell[1] - row.longitude) ** 2)[0], axis=1)
        result.loc[valid, "weather_lon"] = result.loc[valid].apply(lambda row: min(cells, key=lambda cell: (cell[0] - row.latitude) ** 2 + (cell[1] - row.longitude) ** 2)[1], axis=1)
        climate = climate.drop_duplicates(["data", "weather_lat", "weather_lon"])
        climate = rolling_daily(climate, ["weather_lat", "weather_lon"], "data", {
            "chuva_mm": "sum",
            "temperatura_media": "mean",
        })
        climate_columns = ["data", "weather_lat", "weather_lon"] + [
            f"{column}_{days}d" for column in ("chuva_mm", "temperatura_media") for days in (7, 14, 21, 28)
        ]
        result = result.merge(climate[climate_columns], on=["data", "weather_lat", "weather_lon"], how="left")

    supply_frames = []
    for year in sorted(result["data"].dropna().dt.year.unique()):
        path = data / "analytics" / "diario" / f"abastecimento_{int(year)}.parquet"
        if path.exists():
            supply_frames.append(pd.read_parquet(path))
    supply = pd.concat(supply_frames, ignore_index=True) if supply_frames else pd.DataFrame()
    if not supply.empty:
        supply["data"] = pd.to_datetime(supply["data"]).dt.normalize()
        supply = rolling_daily(supply, ["area_id"], "data", {
            "horas_abastecimento": "sum",
            "sem_abastecimento": "sum",
        })
        supply_columns = ["area_id", "data"] + [
            f"{column}_{days}d" for column in ("horas_abastecimento", "sem_abastecimento") for days in (7, 14, 21, 28)
        ]
        result = result.merge(supply[supply_columns], on=["area_id", "data"], how="left")

    return result.drop(columns=["data"], errors="ignore")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/informacoes-gevacz"))
    parser.add_argument("--output", type=Path, default=Path("data/curated/gevacz"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    edls = read_edls(args.data)
    locations = read_georeferenced_ovts(args.data)
    observations = pd.concat([
        read_wide_ovitrampas(args.data, locations, 2024),
        read_wide_ovitrampas(args.data, locations, 2025),
        read_ovitrampas(args.data, locations),
    ], ignore_index=True)
    ovitrampas = pd.DataFrame(locations.values())
    observations["id_ovt_chave"] = observations["id_ovt"].map(ovt_key)
    if not ovitrampas.empty:
        ovitrampas["id_ovt_chave"] = ovitrampas["id_ovt"].map(ovt_key)

    observations = normalize_dates(observations)
    if "data_coleta_original" in observations:
        observations["data_coleta_original"] = observations["data_coleta_original"].map(text).astype("string")

    if not edls.empty:
        edls["qualidade_coordenada"] = edls.apply(
            lambda row: "valida" if valid_coordinates(row) else "suspeita",
            axis=1,
        )
    if not ovitrampas.empty:
        ovitrampas["qualidade_coordenada"] = ovitrampas.apply(
            lambda row: "valida" if valid_coordinates(row) else "suspeita",
            axis=1,
        )
        ovitrampas = classify_geography(ovitrampas, args.data.parent)
    if not observations.empty:
        observations["qualidade_coordenada"] = observations.apply(
            lambda row: "valida" if valid_coordinates(row) else "ausente",
            axis=1,
        )
        geography_by_id = ovitrampas.set_index("id_ovt_chave")["qualidade_geografica"] if not ovitrampas.empty else pd.Series(dtype=str)
        observations["qualidade_geografica"] = observations["id_ovt_chave"].map(geography_by_id).fillna("sem_localizacao")
    edls.to_parquet(args.output / "edls.parquet", index=False)
    cycles = build_cycle_summary(observations)
    analytical = build_analytical_table(observations, args.data, args.data.parent)
    id_audit = observations.groupby("id_ovt_chave", as_index=False).agg(
        id_ovt=("id_ovt", "first"),
        anos=("ano_arquivo", lambda values: ",".join(map(str, sorted(set(values.dropna()))))),
        bairros=("bairro", lambda values: "; ".join(sorted(set(text(value) for value in values if text(value))))),
        observacoes=("id_ovt_chave", "size"),
    )
    location_columns = ["id_ovt_chave", "latitude", "longitude", "qualidade_coordenada", "qualidade_geografica"]
    id_audit = id_audit.merge(ovitrampas[location_columns], on="id_ovt_chave", how="left")
    id_audit["situacao"] = id_audit["qualidade_geografica"].fillna("sem_localizacao")

    edls.to_parquet(args.output / "edls.parquet", index=False)
    ovitrampas.to_parquet(args.output / "ovitrampas.parquet", index=False)
    observations.to_parquet(args.output / "observacoes_ovitrampas.parquet", index=False)
    cycles.to_parquet(args.output / "ciclos.parquet", index=False)
    analytical.to_parquet(args.output / "observacoes_analiticas.parquet", index=False)
    id_audit.to_parquet(args.output / "auditoria_ids_ovitrampas.parquet", index=False)
    ovitrampas[ovitrampas["qualidade_geografica"] != "valida"].to_parquet(
        args.output / "auditoria_coordenadas_ovitrampas.parquet", index=False
    )
    pd.DataFrame([{
        "edls": len(edls),
        "edls_coordenadas_validas": int((edls.get("qualidade_coordenada", pd.Series(dtype=str)) == "valida").sum()),
        "ovitrampas": len(ovitrampas),
        "observacoes": len(observations),
        "observacoes_por_ano": observations.groupby("ano_arquivo").size().to_dict() if not observations.empty else {},
        "ciclos": len(cycles),
        "observacoes_analiticas": len(analytical),
        "datas_suspeitas": int(observations.get("data_suspeita", pd.Series(dtype=bool)).sum()),
        "observacoes_com_coordenada": int((observations.get("qualidade_coordenada", pd.Series(dtype=str)) == "valida").sum()),
        "observacoes_com_ovos": int(observations.get("n_ovos", pd.Series(dtype=float)).notna().sum()),
        "ovitrampas_por_qualidade_geografica": ovitrampas.groupby("qualidade_geografica").size().to_dict(),
        "ids_por_situacao": id_audit.groupby("situacao").size().to_dict(),
    }]).to_json(args.output / "qualidade.json", orient="records", indent=2)
    print(f"EDLs: {len(edls)} | ovitrampas: {len(ovitrampas)} | observações: {len(observations)}")


if __name__ == "__main__":
    main()
