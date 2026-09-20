#!/usr/bin/env python3
"""
Extrai o calendário de abastecimento da COMPESA (PE inteiro) para AGOSTO/2026
e classifica quais áreas pertencem ao Recife.

Uso:
    pip install requests pandas geopandas shapely
    python compesa_agosto2026.py

Saída (pasta saida_agosto2026/):
    raw_areas.jsonl, raw_periodos.jsonl, raw_servicos.jsonl   -> bruto da API
    periodos.csv, servicos.csv                                -> tabelas com datas convertidas
    areas_municipios.csv                                      -> área x município x fração
    recife_periodos.csv, recife_servicos.csv                  -> só o Recife
"""
import json
import pathlib
import time

import pandas as pd
import requests

ROOT = "https://geo.compesa.com.br:6443/arcgis/rest/services/Calendario/Calendario/MapServer"
INI, FIM = "2026-08-01", "2026-09-01"   # período: agosto/2026 (FIM é exclusivo)
RECIFE = "2611606"                       # código IBGE
FRAC_MIN = 0.05                          # fração mínima da área dentro do Recife
VERIFY_SSL = True                        # se der erro de certificado, veja README/mensagem
REBAIXAR = False                         # True = ignora os arquivos brutos já salvos e baixa de novo
OUT = pathlib.Path("saida_agosto2026")
OUT.mkdir(exist_ok=True)

S = requests.Session()


def post(url, **params):
    params.setdefault("f", "json")
    for t in range(3):
        try:
            r = S.post(url, data=params, timeout=180, verify=VERIFY_SSL)
            r.raise_for_status()
            j = r.json()
            if "error" in j:
                raise RuntimeError(j["error"])
            return j
        except Exception:
            if t == 2:
                raise
            time.sleep(2 ** t)


def buscar_ids(layer, wheres):
    """Tenta cada sintaxe de filtro até uma devolver registros."""
    for w in wheres:
        try:
            j = post(f"{ROOT}/{layer}/query", where=w, returnIdsOnly="true")
        except Exception as e:
            print(f"  [layer {layer}] filtro falhou ({str(e)[:80]}): {w[:70]}...")
            continue
        ids = j.get("objectIds") or []
        if ids:
            print(f"  [layer {layer}] filtro OK: {w[:90]}")
            return ids
    return []


def baixar(layer, wheres, geometry=False, batch=200):
    ids = buscar_ids(layer, wheres)
    print(f"  [layer {layer}] {len(ids)} registros")
    feats = []
    for i in range(0, len(ids), batch):
        j = post(f"{ROOT}/{layer}/query",
                 objectIds=",".join(map(str, ids[i:i + batch])),
                 outFields="*", returnGeometry=str(geometry).lower(), outSR=4326)
        feats += j.get("features", [])
        time.sleep(0.3)
    return feats


def salvar_jsonl(nome, feats):
    with (OUT / nome).open("w", encoding="utf-8") as f:
        for ft in feats:
            f.write(json.dumps(ft, ensure_ascii=False) + "\n")


def obter(arquivo, layer, wheres, geometry=False, batch=200):
    """Usa o bruto salvo se existir; senão baixa e salva."""
    p = OUT / arquivo
    if p.exists() and p.stat().st_size > 0 and not REBAIXAR:
        print(f"  usando arquivo já salvo: {arquivo} (apague-o ou use REBAIXAR=True para baixar de novo)")
        with p.open(encoding="utf-8") as f:
            return [json.loads(l) for l in f]
    feats = baixar(layer, wheres, geometry, batch)
    salvar_jsonl(arquivo, feats)
    return feats


def ms_to_dt(serie):
    # horário local ingênuo: NÃO converter fuso
    return pd.to_datetime(serie, unit="ms")


# ---------------------------------------------------------------- 1) download
print("1) Baixando áreas (PE inteiro, com geometria)...")
areas_raw = obter("raw_areas.jsonl", 0, ["1=1"], geometry=True, batch=50)

print("2) Baixando períodos (layer 5) de agosto/2026...")
where_p = [
    f"Inicio < '{FIM}' AND Termino >= '{INI}'",   # funciona (SQL Server)
    f"Inicio < timestamp '{FIM} 00:00:00' AND Termino >= timestamp '{INI} 00:00:00'",
    "(DATEPART(MONTH,Inicio)='08' OR DATEPART(MONTH,Termino)='08') AND DATEPART(YEAR,Inicio)='2026'",
]
per_raw = obter("raw_periodos.jsonl", 5, where_p)

print("3) Baixando serviços (layer 2) de agosto/2026...")
where_s = [
    f"INICIO_PREVISTO < '{FIM}' AND TERMINO_PREVISTO >= '{INI}'",   # funciona (SQL Server)
    f"INICIO_PREVISTO < timestamp '{FIM} 00:00:00' AND TERMINO_PREVISTO >= timestamp '{INI} 00:00:00'",
    "(DATEPART(MONTH,INICIO_PREVISTO)='08' OR DATEPART(MONTH,TERMINO_PREVISTO)='08') "
    "AND DATEPART(YEAR,INICIO_PREVISTO)='2026'",
]
srv_raw = obter("raw_servicos.jsonl", 2, where_s)

# ------------------------------------------------------------ 2) tabelas
df_p = pd.DataFrame([f["attributes"] for f in per_raw])
df_s = pd.DataFrame([f["attributes"] for f in srv_raw])
for df, cols in [(df_p, ["Inicio", "Termino"]), (df_s, ["INICIO_PREVISTO", "TERMINO_PREVISTO"])]:
    for c in cols:
        if c in df:
            df[c] = ms_to_dt(df[c])
df_p.to_csv(OUT / "periodos.csv", index=False, encoding="utf-8-sig")
df_s.to_csv(OUT / "servicos.csv", index=False, encoding="utf-8-sig")
print(f"   períodos: {len(df_p)} | serviços: {len(df_s)}")

# ---------------------------------------------- 3) áreas x municípios (IBGE)
try:
    import geopandas as gpd
    from shapely import make_valid
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    def esri_to_shapely(rings):
        """Anel horário = exterior; anti-horário = furo (convenção Esri)."""
        ext, furos = [], []
        for r in rings:
            if len(r) < 4:
                continue
            area = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1])) / 2
            (ext if area < 0 else furos).append(make_valid(Polygon(r)))
        if not ext:                       # orientação inesperada: trata tudo como exterior
            ext, furos = furos, []
        g = unary_union(ext)
        if furos:
            g = g.difference(unary_union(furos))
        return make_valid(g)

    def so_poligonos(g):
        """Depois de make_valid pode sobrar linha/ponto; mantém só polígonos."""
        if g.geom_type in ("Polygon", "MultiPolygon"):
            return g
        partes = [p for p in getattr(g, "geoms", []) if p.geom_type in ("Polygon", "MultiPolygon")]
        return unary_union(partes) if partes else g

    print("4) Classificando áreas por município (IBGE)...")
    por_id = {}
    for ft in areas_raw:
        if ft.get("geometry"):
            por_id.setdefault(ft["attributes"]["ID"], []).append(esri_to_shapely(ft["geometry"]["rings"]))
    areas = gpd.GeoDataFrame(
        {"ID": list(por_id), "geometry": [so_poligonos(make_valid(unary_union(g))) for g in por_id.values()]},
        crs=4326,
    ).to_crs(31985)
    areas["geometry"] = areas.geometry.apply(lambda g: so_poligonos(make_valid(g)))
    areas["area_total"] = areas.geometry.area
    print(f"   {len(areas)} áreas únicas (IDs)")

    mun = gpd.read_file(
        "https://servicodados.ibge.gov.br/api/v3/malhas/estados/26"
        "?formato=application/vnd.geo+json&intrarregiao=municipio&qualidade=maxima"
    ).to_crs(31985)
    mun["geometry"] = mun.geometry.apply(lambda g: so_poligonos(make_valid(g)))
    nomes = requests.get(
        "https://servicodados.ibge.gov.br/api/v1/localidades/estados/26/municipios", timeout=60
    ).json()
    mun["municipio"] = mun["codarea"].astype(str).map({str(m["id"]): m["nome"] for m in nomes})

    # interseção área a área (um polígono problemático não derruba o resto)
    sidx = mun.sindex
    linhas, falhas = [], []
    for row in areas.itertuples():
        for j in sidx.query(row.geometry, predicate="intersects"):
            m = mun.iloc[j]
            try:
                inter = row.geometry.intersection(m.geometry)
            except Exception:
                try:
                    inter = row.geometry.buffer(0).intersection(m.geometry.buffer(0))
                except Exception:
                    falhas.append(row.ID)
                    continue
            frac = inter.area / row.area_total if row.area_total else 0
            if frac > 0:
                linhas.append({"ID": row.ID, "codarea": str(m.codarea),
                               "municipio": m.municipio, "frac_area": frac})
    if falhas:
        print(f"   atenção: {len(set(falhas))} áreas falharam na interseção: {sorted(set(falhas))[:10]}")

    tab = pd.DataFrame(linhas).sort_values(["ID", "frac_area"], ascending=[True, False])
    tab.to_csv(OUT / "areas_municipios.csv", index=False, encoding="utf-8-sig")
    print(f"   áreas sem município encontrado: {len(areas) - tab.ID.nunique()}")

    ids_recife = set(tab.loc[(tab.codarea == RECIFE) & (tab.frac_area >= FRAC_MIN), "ID"])
    print(f"   áreas com >= {FRAC_MIN:.0%} dentro do Recife: {len(ids_recife)}")
    if "ID" in df_p:
        df_p[df_p["ID"].isin(ids_recife)].to_csv(OUT / "recife_periodos.csv", index=False, encoding="utf-8-sig")
    if "ID_AREA_ABASTECIMENTO" in df_s:
        df_s[df_s["ID_AREA_ABASTECIMENTO"].isin(ids_recife)].to_csv(OUT / "recife_servicos.csv", index=False, encoding="utf-8-sig")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"\n!! Classificação por município falhou: {e}")
    print("   O bruto e as tabelas de PE já foram salvos. Me mande o erro acima.")

print(f"\nPronto. Arquivos em: {OUT.resolve()}")
