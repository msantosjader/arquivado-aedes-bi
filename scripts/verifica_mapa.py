#!/usr/bin/env python3
"""Checagem das mudanças do mapa: janela 0, payload H3, hexágono e projeção de EDLs.

Uso: uv run python scripts/verifica_mapa.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gevacz import rolling_daily  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def verifica_janela_zero():
    frame = pd.DataFrame({"grupo": "g", "data": pd.date_range("2026-01-01", periods=10), "chuva_mm": range(10)})
    out = rolling_daily(frame, ["grupo"], "data", {"chuva_mm": "sum"}).sort_values("data")
    # janela 0 = o próprio dia da coleta
    check(bool((out["chuva_mm_0d"] == out["chuva_mm"]).all()), "chuva_mm_0d deve ser o valor do próprio dia")
    # janela 7 exclui o dia da coleta e exige 7 dias cheios
    check(bool(pd.isna(out.loc[6, "chuva_mm_7d"])), "chuva_mm_7d deve ser NaN antes de 7 dias cheios")
    check(out.loc[7, "chuva_mm_7d"] == 21, f"chuva_mm_7d no dia 7 deve ser 21, veio {out.loc[7, 'chuva_mm_7d']}")


def verifica_parquet():
    path = ROOT / "data" / "curated" / "gevacz" / "observacoes_analiticas.parquet"
    if not path.exists():
        print(f"  pulado (ainda nao regenerado): {path.name}")
        return
    frame = pd.read_parquet(path)
    for column in ("chuva_mm_0d", "temperatura_media_0d", "sem_abastecimento_0d"):
        check(column in frame.columns, f"{column} ausente em observacoes_analiticas.parquet")
        if column in frame.columns:
            base = column.replace("_0d", "_7d")
            check(int(frame[column].notna().sum()) > 0.8 * int(frame[base].notna().sum()),
                  f"{column} tem cobertura muito menor que {base}")


def verifica_html():
    path = ROOT / "data" / "mapa_recife.html"
    if not path.exists():
        print(f"  pulado (ainda nao regenerado): {path.name}")
        return
    html = path.read_text(encoding="utf-8")
    for needle in ("lagDays=[0,7,14,21,28]", 'id="janela" type="range" min="0" max="4" value="1"',
                   'id="raio-bloco"', "hexEmCima", "DATA.h3_geometries[cell.h3_index]",
                   "amostraSuficiente", "dia da coleta",
                   'id="edl-proj-visivel"', "const PROJ=", "edlProjLayers",
                   "projK+' pontos para cobrir '",
                   "hexEmCima(o.latitude,o.longitude,radius)"):
        check(needle in html, f"HTML sem: {needle}")
    for banned in ("edl_buffers", "L.circle([edl.latitude", "H3 (resolução 8)"):
        check(banned not in html, f"HTML ainda contem: {banned}")
    check('"resolucao_h3":8' not in html, "HTML contem celulas H3 de resolucao 8")
    check(html.count('"resolucao_h3":9') > 0, "HTML sem celulas H3 de resolucao 9")


if __name__ == "__main__":
    verifica_janela_zero()
    verifica_parquet()
    verifica_html()
    for message in failures:
        print(f"FALHOU: {message}")
    print(f"{len(failures)} falha(s)")
    sys.exit(1 if failures else 0)
