#!/usr/bin/env python3
"""Normaliza as planilhas de EDLs e ovitrampas da GEVACZ."""
import argparse
import re
import unicodedata
from pathlib import Path

import pandas as pd
import geopandas as gpd
import numpy as np
import h3
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


INSTALLATION_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def installation_date(value):
    """Extrai a data da coluna L sem transformar observações em datas exatas."""
    raw = text(value)
    normalized = key(raw)
    if not raw:
        return pd.NaT, raw, "sem_data"
    if "retir" in normalized:
        return pd.NaT, raw, "retirada_ou_observacao"

    full_date = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", raw)
    if full_date:
        day, month, year = map(int, full_date.groups())
        return pd.Timestamp(year=year, month=month, day=day), raw, "data_exata"

    iso_date = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if iso_date:
        year, month, day = map(int, iso_date.groups())
        return pd.Timestamp(year=year, month=month, day=day), raw, "data_exata"

    for month_name, month in INSTALLATION_MONTHS.items():
        if re.search(rf"(?:^|_){month_name}(?:_|$)", normalized):
            year = re.search(r"(?:^|_)(20\d{2})(?:_|$)", normalized)
            if year:
                return pd.Timestamp(year=int(year.group(1)), month=month, day=1), raw, "mes_ano"
    return pd.NaT, raw, "sem_data"


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
    """Distingue município, faixa de fronteira e cobertura operacional."""
    if frame.empty:
        return frame
    frame["qualidade_geografica"] = "sem_coordenada"
    frame["qualidade_municipal"] = "sem_coordenada"
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
    boundary = unary_union(gpd.read_file(boundary_path).to_crs(31985).geometry)
    points_metric = points.to_crs(31985)
    inside_boundary = points_metric.geometry.within(boundary)
    near_boundary = ~inside_boundary & points_metric.geometry.within(boundary.buffer(500))
    frame.loc[subset.index[inside_boundary.to_numpy()], "qualidade_municipal"] = "dentro_recife"
    frame.loc[subset.index[near_boundary.to_numpy()], "qualidade_municipal"] = "fora_recife_proxima"
    frame.loc[subset.index[(~inside_boundary & ~near_boundary).to_numpy()], "qualidade_municipal"] = "fora_recife"
    frame.loc[subset.index[inside_boundary.to_numpy()], "qualidade_geografica"] = "valida"
    frame.loc[subset.index[near_boundary.to_numpy()], "qualidade_geografica"] = "fora_recife_proxima"
    frame.loc[subset.index[(~inside_boundary & ~near_boundary).to_numpy()], "qualidade_geografica"] = "fora_recife"
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
        for row_number, values in enumerate(raw.iloc[row_index + 1 :].itertuples(index=False, name=None), start=row_index + 2):
            values = list(values) + [None] * 15
            if number(values[0]) is None and not any(text(values[index]) for index in (4, 5, 7, 11)):
                continue
            latitude, longitude = coordinates(values[7], values[8])
            real = number(values[11]) if number(values[11]) is not None else number(values[10])
            data_instalacao, data_instalacao_original, qualidade_data_instalacao = installation_date(values[11])
            edl_number = number(values[0])
            rows.append({
                "edl_id": f"DS{district}_{int(edl_number) if edl_number is not None else f'R{row_number}'}",
                "distrito_sanitario": district,
                "bairro": text(values[6]),
                "nome_local": text(values[4]),
                "tipo_local": text(values[3]),
                "logradouro": text(values[5]),
                "latitude": latitude,
                "longitude": longitude,
                "edl_ideal": number(values[10]),
                "edl_real": real,
                "data_instalacao": data_instalacao,
                "data_instalacao_original": data_instalacao_original,
                "qualidade_data_instalacao": qualidade_data_instalacao,
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
                "latitude_original": latitude,
                "longitude_original": longitude,
                "fonte_coordenada": "excel",
                "qualidade_correcao": "nao_confirmada",
                "presente_no_excel": True,
                "endereco": text(record.get("endereco")),
                "arquivo_origem": str(path.relative_to(root)),
            }
    shapefile_rows = read_ovt_shapefiles(root)
    for key_value, shape_location in shapefile_rows.items():
        location = rows.setdefault(key_value, {"id_ovt": shape_location["id_ovt"]})
        location.setdefault("presente_no_excel", False)
        if "latitude_original" not in location:
            location.update({"latitude_original": location.get("latitude"), "longitude_original": location.get("longitude")})
        location.update({
            "latitude": shape_location["latitude"],
            "longitude": shape_location["longitude"],
            "fonte_coordenada": "shapefile_ovt_2026",
            "qualidade_correcao": shape_location["qualidade_correcao"],
        })
        location.setdefault("bairro", shape_location.get("bairro", ""))
        location.setdefault("endereco", "")
    return rows


def read_ovt_shapefiles(root):
    """Lê os pontos OVT 2026 e os usa como referência espacial por ID."""
    records = read_ovt_shapefile_records(root)
    if records.empty:
        return {}
    result = {}
    for ovt_id, group in records.groupby(records["id_ovt"].map(ovt_key)):
        unique = group[["latitude", "longitude"]].round(7).drop_duplicates()
        if len(unique) != 1:
            continue
        row = group.iloc[0]
        result[ovt_id] = {
            "id_ovt": row["id_ovt"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "qualidade_correcao": "confirmada_shapefile",
        }
    return result


def read_ovt_shapefile_records(root):
    records = []
    shapefile_root = root / "ATUALIZAÇÃO TOTAL DAS OVITRAMPAS 2026 shapefile"
    for path in shapefile_root.glob("**/*.shp"):
        frame = gpd.read_file(path)
        if frame.empty or frame.crs is None:
            continue
        id_column = "FolderPath" if "FolderPath" in frame else "OVITRAMPA" if "OVITRAMPA" in frame else None
        if id_column is None:
            continue
        frame = frame.to_crs(4326)
        for _, row in frame.iterrows():
            if row.geometry is None or row.geometry.is_empty or row.geometry.geom_type != "Point":
                continue
            records.append({
                "id_ovt": text(row[id_column]),
                "latitude": row.geometry.y,
                "longitude": row.geometry.x,
                "arquivo_shapefile": str(path.relative_to(root)),
            })
    return pd.DataFrame(records)


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
                    "latitude_original": location.get("latitude_original"),
                    "longitude_original": location.get("longitude_original"),
                    "fonte_coordenada": location.get("fonte_coordenada"),
                    "qualidade_correcao": location.get("qualidade_correcao"),
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
                        "latitude_original": location.get("latitude_original"),
                        "longitude_original": location.get("longitude_original"),
                        "fonte_coordenada": location.get("fonte_coordenada"),
                        "qualidade_correcao": location.get("qualidade_correcao"),
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


def correct_cycle_dates(observations):
    """Corrige apenas o ano 2026 digitado nos ciclos 2025 e audita o restante."""
    if observations.empty:
        return observations
    result = observations.copy()
    result["data_coleta_original_parseada"] = result["data_coleta"]
    result["data_coleta_corrigida"] = result["data_coleta"]
    result["regra_data"] = "original"
    result["confianca_data"] = "alta"
    file_2025 = result["ano_arquivo"].eq(2025)
    cycles_before_24 = pd.to_numeric(result["ciclo"], errors="coerce").le(23)
    wrong_2026 = file_2025 & cycles_before_24 & result["data_coleta"].dt.year.eq(2026)
    if wrong_2026.any():
        corrected = result.loc[wrong_2026, "data_coleta"].map(
            lambda value: value.replace(year=2025) if pd.notna(value) else pd.NaT
        )
        result.loc[wrong_2026, "data_coleta_corrigida"] = corrected
        result.loc[wrong_2026, "regra_data"] = "ano_2026_corrigido_para_2025"
        result.loc[wrong_2026, "confianca_data"] = "alta"
    impossible = result["data_coleta"].notna() & ~result["data_coleta"].dt.year.between(2000, 2026)
    result.loc[impossible, "data_coleta_corrigida"] = pd.NaT
    result.loc[impossible, "regra_data"] = "data_fora_da_faixa"
    result.loc[impossible, "confianca_data"] = "revisar"
    result["data_coleta"] = result["data_coleta_corrigida"]
    result["qualidade_data"] = "confirmada"
    result.loc[result["data_coleta"].isna(), "qualidade_data"] = "ausente_ou_suspeita"
    result.loc[result["regra_data"].ne("original"), "qualidade_data"] = "corrigida_ou_suspeita"
    result["data_suspeita"] = result["qualidade_data"].ne("confirmada")
    return result


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
            edl_dates = pd.to_datetime(edls.get("data_instalacao"), errors="coerce").to_numpy()
            valid = result["latitude"].notna() & result["longitude"].notna()
            valid_index = result.index[valid]
            x, y = project(result.loc[valid, "longitude"].to_numpy(), result.loc[valid, "latitude"].to_numpy())
            distances = []
            nearest_indices = []
            active_distances = []
            for start in range(0, len(x), 20_000):
                distance_matrix = np.sqrt((x[start:start + 20_000, None] - edl_x[None, :]) ** 2 + (y[start:start + 20_000, None] - edl_y[None, :]) ** 2)
                distances.append(distance_matrix.min(axis=1))
                nearest_indices.append(distance_matrix.argmin(axis=1))
                collection_dates = pd.to_datetime(result.loc[valid_index[start:start + 20_000], "data"], errors="coerce").to_numpy()
                active = (~pd.isna(edl_dates))[None, :] & (edl_dates[None, :] <= collection_dates[:, None])
                active_matrix = np.where(active, distance_matrix, np.inf)
                active_distances.append(active_matrix.min(axis=1))
            result.loc[valid_index, "distancia_edl_m"] = np.concatenate(distances)
            active_distance = np.concatenate(active_distances)
            active_distance[np.isinf(active_distance)] = np.nan
            result.loc[valid_index, "distancia_edl_ativa_m"] = active_distance
            nearest = np.concatenate(nearest_indices)
            result.loc[valid_index, "edl_mais_proxima_id"] = edls.iloc[nearest].edl_id.to_numpy()
            result.loc[valid_index, "data_instalacao_edl"] = edl_dates[nearest]
            result.loc[valid_index, "qualidade_data_instalacao_edl"] = edls.iloc[nearest].qualidade_data_instalacao.to_numpy()
            result["instalada_ate_coleta"] = pd.Series(pd.NA, index=result.index, dtype="boolean")
            comparable = result["data_instalacao_edl"].notna() & result["data"].notna()
            result.loc[comparable, "instalada_ate_coleta"] = result.loc[comparable, "data_instalacao_edl"].le(result.loc[comparable, "data"])
            for radius in (50, 100, 150, 200, 300, 400, 500):
                result[f"edl_a_{radius}m"] = result["distancia_edl_m"].le(radius)
                result[f"edl_ativa_a_{radius}m"] = result["distancia_edl_ativa_m"].le(radius)
            result["faixa_distancia_edl_ativa"] = pd.cut(
                result["distancia_edl_ativa_m"],
                bins=[-np.inf, 100, 200, 300, 400, 500, np.inf],
                labels=["0-100m", "100-200m", "200-300m", "300-400m", "400-500m", ">500m"],
            )
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


def build_h3_tables(analytical, output):
    """Gera agregações H3 e diagnóstico de resolução para observações válidas."""
    columns = [
        "ano_arquivo", "ciclo", "id_ovt", "latitude", "longitude", "n_ovos",
        "data_coleta", "bairro", "qualidade_geografica", "distancia_edl_m", "distancia_edl_ativa_m", "edl_mais_proxima_id",
        "instalada_ate_coleta", "data_instalacao_edl", "edl_a_50m", "edl_a_100m",
        "edl_a_150m", "edl_a_200m", "edl_a_300m", "edl_a_400m", "edl_a_500m",
        "edl_ativa_a_50m", "edl_ativa_a_100m", "edl_ativa_a_150m", "edl_ativa_a_200m",
        "edl_ativa_a_300m", "edl_ativa_a_400m", "edl_ativa_a_500m",
        "chuva_mm_7d", "chuva_mm_14d", "chuva_mm_21d", "chuva_mm_28d",
        "temperatura_media_7d", "temperatura_media_14d", "temperatura_media_21d",
        "temperatura_media_28d", "sem_abastecimento_7d", "sem_abastecimento_14d",
        "sem_abastecimento_21d", "sem_abastecimento_28d",
    ]
    available = [column for column in columns if column in analytical]
    frame = analytical[available].copy()
    if "qualidade_geografica" in frame:
        frame = frame[frame["qualidade_geografica"].isin(["valida", "fora_recife_proxima", "sem_area_compesa"])]
    frame = frame.dropna(subset=["latitude", "longitude", "ano_arquivo", "ciclo"])
    if frame.empty:
        empty = pd.DataFrame()
        empty.to_parquet(output / "observacoes_h3.parquet", index=False)
        empty.to_parquet(output / "h3_diagnostico.parquet", index=False)
        return empty, empty

    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    frame = frame.dropna(subset=["latitude", "longitude"])
    optional_columns = [
        "distancia_edl_m", "distancia_edl_ativa_m", "edl_mais_proxima_id", "instalada_ate_coleta",
        "data_instalacao_edl", "bairro", "data_coleta",
    ] + [column for column in columns if column.startswith(("edl_a_", "chuva_mm_", "temperatura_media_", "sem_abastecimento_"))]
    for column in optional_columns:
        if column not in frame:
            frame[column] = pd.NA
    rows = []
    diagnostics = []
    for resolution in (8, 9):
        current = frame.copy()
        current["h3_index"] = [
            h3.latlng_to_cell(float(latitude), float(longitude), resolution)
            for latitude, longitude in current[["latitude", "longitude"]].itertuples(index=False, name=None)
        ]
        current["resolucao_h3"] = resolution
        current["ovos_validos"] = pd.to_numeric(current["n_ovos"], errors="coerce")
        current["positiva"] = current["ovos_validos"].gt(0)
        group_columns = ["resolucao_h3", "h3_index", "ano_arquivo", "ciclo"]
        aggregations = {
            "observacoes": ("id_ovt", "size"),
            "ovitrampas": ("id_ovt", "nunique"),
            "ovos_total": ("ovos_validos", "sum"),
            "observacoes_com_ovos": ("ovos_validos", "count"),
            "ovitrampas_positivas": ("positiva", "sum"),
            "data_inicio": ("data_coleta", "min"),
            "data_fim": ("data_coleta", "max"),
            "bairro": ("bairro", "first"),
            "distancia_edl_media_m": ("distancia_edl_m", "mean"),
            "distancia_edl_ativa_media_m": ("distancia_edl_ativa_m", "mean"),
            "ovos_media": ("ovos_validos", "mean"),
            "ovos_mediana": ("ovos_validos", "median"),
            "edls_mais_proximas": ("edl_mais_proxima_id", "nunique"),
            "instaladas_ate_coleta": ("instalada_ate_coleta", "sum"),
        }
        for column in current.columns:
            if column.startswith(("chuva_mm_", "temperatura_media_", "sem_abastecimento_", "edl_a_", "edl_ativa_a_")):
                current[column] = pd.to_numeric(current[column], errors="coerce")
                aggregations[column + "_media"] = (column, "mean")
        aggregated = current.groupby(group_columns, dropna=False).agg(**aggregations).reset_index()
        aggregated["positividade"] = aggregated["ovitrampas_positivas"].div(aggregated["observacoes_com_ovos"].replace(0, np.nan))
        rows.append(aggregated)
        counts = aggregated["observacoes"]
        diagnostics.append({
            "resolucao_h3": resolution,
            "celulas": len(aggregated),
            "observacoes": int(counts.sum()),
            "media_observacoes_por_celula": float(counts.mean()),
            "mediana_observacoes_por_celula": float(counts.median()),
            "celulas_com_menos_de_5_observacoes": int((counts < 5).sum()),
            "percentual_celulas_com_menos_de_5": float((counts < 5).mean()),
        })

    result = pd.concat(rows, ignore_index=True)
    diagnostic = pd.DataFrame(diagnostics)
    result.to_parquet(output / "observacoes_h3.parquet", index=False)
    diagnostic.to_parquet(output / "h3_diagnostico.parquet", index=False)
    return result, diagnostic


def write_coordinate_audit(ovitrampas, id_audit, shapefile_records, observations, output):
    """Exporta a rastreabilidade das coordenadas e dos IDs sem confirmação."""
    columns = [
        "id_ovt_chave", "id_ovt", "bairros", "anos", "observacoes", "latitude_original",
        "longitude_original", "latitude", "longitude", "fonte_coordenada", "qualidade_correcao",
        "qualidade_coordenada", "qualidade_geografica", "situacao",
    ]
    location_columns = [
        "id_ovt_chave", "latitude_original", "longitude_original", "latitude", "longitude",
        "fonte_coordenada", "qualidade_correcao", "qualidade_coordenada", "qualidade_geografica",
    ]
    audit = id_audit.drop(columns=[column for column in location_columns if column != "id_ovt_chave" and column in id_audit], errors="ignore").merge(
        ovitrampas[location_columns], on="id_ovt_chave", how="left"
    )
    audit["situacao"] = audit["qualidade_geografica"].fillna("sem_localizacao")
    audit["coordenada_alterada"] = (
        audit["latitude_original"].notna()
        & audit["latitude"].notna()
        & (
            ((audit["latitude_original"] - audit["latitude"]).abs() > 1e-7)
            | ((audit["longitude_original"] - audit["longitude"]).abs() > 1e-7)
        )
    )
    corrections = audit[audit["fonte_coordenada"].eq("shapefile_ovt_2026")].copy()
    accepted = ["valida", "fora_recife_proxima", "sem_area_compesa"]
    pending = audit[~audit["qualidade_geografica"].isin(accepted)].copy()
    unconfirmed = audit[~audit["fonte_coordenada"].eq("shapefile_ovt_2026")].copy()
    summary = audit.groupby(["fonte_coordenada", "qualidade_geografica"], dropna=False).agg(
        ids=("id_ovt_chave", "nunique"), observacoes=("observacoes", "sum")
    ).reset_index()
    excel_locations = ovitrampas[ovitrampas["presente_no_excel"].eq(True)][
        ["id_ovt_chave", "id_ovt", "latitude_original", "longitude_original"]
    ].copy()
    excel_locations = excel_locations.rename(columns={
        "latitude_original": "latitude_excel",
        "longitude_original": "longitude_excel",
    })
    shape_locations = shapefile_records.copy()
    if not shape_locations.empty:
        shape_locations["id_ovt_chave"] = shape_locations["id_ovt"].map(ovt_key)
        shape_summary = shape_locations.groupby("id_ovt_chave", as_index=False).agg(
            id_ovt_shapefile=("id_ovt", "first"),
            latitude_shapefile=("latitude", "first"),
            longitude_shapefile=("longitude", "first"),
            arquivos_shapefile=("arquivo_shapefile", lambda values: "; ".join(sorted(set(values)))),
            registros_shapefile=("id_ovt", "size"),
        )
        unique_coordinates = shape_locations.groupby("id_ovt_chave").apply(
            lambda group: len(group[["latitude", "longitude"]].round(7).drop_duplicates()),
            include_groups=False,
        ).rename("coordenadas_distintas_shapefile").reset_index()
        shape_summary = shape_summary.merge(unique_coordinates, on="id_ovt_chave")
    else:
        shape_summary = pd.DataFrame(columns=["id_ovt_chave"])
    comparison = excel_locations.merge(shape_summary, on="id_ovt_chave", how="outer", indicator=True)
    comparison["distancia_excel_shapefile_m"] = np.nan
    comparable = comparison["latitude_excel"].notna() & comparison["latitude_shapefile"].notna()
    if comparable.any():
        project = Transformer.from_crs(4326, 31985, always_xy=True).transform
        excel_x, excel_y = project(comparison.loc[comparable, "longitude_excel"], comparison.loc[comparable, "latitude_excel"])
        shape_x, shape_y = project(comparison.loc[comparable, "longitude_shapefile"], comparison.loc[comparable, "latitude_shapefile"])
        comparison.loc[comparable, "distancia_excel_shapefile_m"] = np.sqrt((excel_x - shape_x) ** 2 + (excel_y - shape_y) ** 2)
    comparison["situacao_comparacao"] = np.select(
        [
            comparison["_merge"].eq("left_only"),
            comparison["_merge"].eq("right_only"),
            comparison["coordenadas_distintas_shapefile"].gt(1),
            comparison["distancia_excel_shapefile_m"].le(10),
        ],
        ["somente_excel", "somente_shapefile", "conflito_no_shapefile", "coordenadas_concordantes_ate_10m"],
        default="coordenadas_divergentes",
    )
    comparison = comparison.drop(columns="_merge")
    temporal_detail = observations[observations["regra_data"].ne("original")][[
        "id_ovt", "ano_arquivo", "ciclo", "data_coleta_original", "data_coleta_original_parseada",
        "data_coleta_corrigida", "regra_data", "confianca_data", "qualidade_data", "arquivo_origem",
    ]].copy()
    temporal_summary = observations.groupby(["ano_arquivo", "ciclo"], dropna=False).agg(
        data_original_min=("data_coleta_original_parseada", "min"),
        data_original_max=("data_coleta_original_parseada", "max"),
        data_corrigida_min=("data_coleta", "min"),
        data_corrigida_max=("data_coleta", "max"),
        data_referencia=("data_coleta", "median"),
        observacoes=("id_ovt", "size"),
        datas_suspeitas=("data_suspeita", "sum"),
    ).reset_index()
    temporal_summary["datas_corrigidas"] = observations.groupby(["ano_arquivo", "ciclo"], dropna=False)["regra_data"].apply(lambda values: values.ne("original").sum()).to_numpy()
    path = output / "auditoria_georreferenciamento.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="resumo", index=False)
        comparison.to_excel(writer, sheet_name="excel_vs_shapefile", index=False)
        corrections[columns + ["coordenada_alterada"]].to_excel(writer, sheet_name="shapefile_confirmadas", index=False)
        pending[columns + ["coordenada_alterada"]].to_excel(writer, sheet_name="pendencias_geograficas", index=False)
        unconfirmed[columns + ["coordenada_alterada"]].to_excel(writer, sheet_name="sem_confirmacao_shp", index=False)
        temporal_summary.to_excel(writer, sheet_name="datas_ciclos", index=False)
        temporal_detail.to_excel(writer, sheet_name="correcoes_datas", index=False)
    return path


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
    observations = correct_cycle_dates(observations)
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
    h3_tables, h3_diagnostic = build_h3_tables(analytical, args.output)
    id_audit = observations.groupby("id_ovt_chave", as_index=False).agg(
        id_ovt=("id_ovt", "first"),
        anos=("ano_arquivo", lambda values: ",".join(map(str, sorted(set(values.dropna()))))),
        bairros=("bairro", lambda values: "; ".join(sorted(set(text(value) for value in values if text(value))))),
        observacoes=("id_ovt_chave", "size"),
    )
    location_columns = ["id_ovt_chave", "latitude", "longitude", "qualidade_coordenada", "qualidade_geografica"]
    id_audit = id_audit.merge(ovitrampas[location_columns], on="id_ovt_chave", how="left")
    id_audit["situacao"] = id_audit["qualidade_geografica"].fillna("sem_localizacao")
    coordinate_audit = write_coordinate_audit(
        ovitrampas,
        id_audit,
        read_ovt_shapefile_records(args.data),
        observations,
        args.output,
    )

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
        "edls_com_data_instalacao": int(edls.get("data_instalacao", pd.Series(dtype="datetime64[ns]")).notna().sum()),
        "edls_instalacao_2026": int(pd.to_datetime(edls.get("data_instalacao"), errors="coerce").dt.year.eq(2026).sum()) if not edls.empty else 0,
        "ovitrampas": len(ovitrampas),
        "observacoes": len(observations),
        "observacoes_por_ano": observations.groupby("ano_arquivo").size().to_dict() if not observations.empty else {},
        "ciclos": len(cycles),
        "observacoes_analiticas": len(analytical),
        "observacoes_h3": len(h3_tables),
        "h3_diagnostico": h3_diagnostic.to_dict("records"),
        "datas_suspeitas": int(observations.get("data_suspeita", pd.Series(dtype=bool)).sum()),
        "observacoes_com_coordenada": int((observations.get("qualidade_coordenada", pd.Series(dtype=str)) == "valida").sum()),
        "observacoes_com_ovos": int(observations.get("n_ovos", pd.Series(dtype=float)).notna().sum()),
        "ovitrampas_por_qualidade_geografica": ovitrampas.groupby("qualidade_geografica").size().to_dict(),
        "ids_por_situacao": id_audit.groupby("situacao").size().to_dict(),
    }]).to_json(args.output / "qualidade.json", orient="records", indent=2)
    print(f"EDLs: {len(edls)} | ovitrampas: {len(ovitrampas)} | observações: {len(observations)} | auditoria: {coordinate_audit}")


if __name__ == "__main__":
    main()
