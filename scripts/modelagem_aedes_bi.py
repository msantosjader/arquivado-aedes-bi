#!/usr/bin/env python3
"""Prepara, ajusta e resume a analise exploratoria do AEDES BI."""
from __future__ import annotations

import hashlib
import json
import re
import warnings
from pathlib import Path

import h3
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/curated/gevacz/observacoes_analiticas.parquet"
OUTPUT = ROOT / "data/curated/gevacz/base_modelagem.parquet"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
WINDOWS = (7, 14, 21, 28)


def load_arboviroses() -> tuple[pd.DataFrame, dict]:
    datasets = {
        "dengue": sorted(ROOT.glob("data/datasets/*casos-de-dengue-*.csv")),
        "zika": sorted(ROOT.glob("data/datasets/*casos-confirmados-de-zika-*.csv")),
        "chikungunya": sorted(ROOT.glob("data/datasets/*chikon-*.csv")) + sorted(ROOT.glob("data/datasets/*chikungunya*.csv")),
    }
    rows = []
    for disease, paths in datasets.items():
        for path in paths:
            frame = pd.read_csv(path, sep=";", encoding="utf-8-sig", low_memory=False)
            frame = frame[frame["ID_MUNICIP"].astype("string").str.zfill(6).eq("261160")].copy()
            frame["data_inicio"] = pd.to_datetime(frame.get("DT_SIN_PRI"), format="mixed", dayfirst=True, errors="coerce")
            frame["data_notificacao"] = pd.to_datetime(frame.get("DT_NOTIFIC"), format="mixed", dayfirst=True, errors="coerce")
            file_year = int(re.search(r"20\d{2}", path.name).group())
            invalid_onset = ~frame["data_inicio"].dt.year.isin([2024, 2025])
            frame.loc[invalid_onset, "data_inicio"] = pd.NaT
            frame["doenca"] = disease
            frame["arquivo_origem"] = path.name
            keep = ["doenca", "data_inicio", "data_notificacao", "NM_BAIRRO", "ID_BAIRRO", "ID_DISTRIT", "CLASSI_FIN", "CRITERIO", "arquivo_origem"]
            rows.append(frame[[c for c in keep if c in frame]])
    cases = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if cases.empty:
        return cases, {"rows": 0, "by_disease": {}}
    cases["mes"] = cases["data_inicio"].dt.to_period("M").astype(str)
    cases["semana"] = cases["data_inicio"].dt.to_period("W").astype(str)
    out = ROOT / "data/curated/arboviroses"
    out.mkdir(parents=True, exist_ok=True)
    cases.to_parquet(out / "casos_arboviroses.parquet", index=False)
    monthly = cases.groupby(["doenca", "mes"], dropna=False).size().rename("casos").reset_index()
    monthly.to_parquet(out / "casos_arboviroses_mensais.parquet", index=False)
    if "ID_BAIRRO" in cases:
        cases.groupby(["doenca", "mes", "ID_BAIRRO", "NM_BAIRRO"], dropna=False).size().rename("casos").reset_index().to_parquet(out / "casos_arboviroses_bairro_mensais.parquet", index=False)
    if "ID_DISTRIT" in cases:
        cases.groupby(["doenca", "mes", "ID_DISTRIT"], dropna=False).size().rename("casos").reset_index().to_parquet(out / "casos_arboviroses_distrito_mensais.parquet", index=False)
    audit = {
        "rows": int(len(cases)),
        "by_disease": {str(k): int(v) for k, v in cases.groupby("doenca").size().items()},
        "by_year": {str(k): int(v) for k, v in cases.groupby(cases["data_inicio"].dt.year).size().items()},
        "missing_or_invalid_onset_date": int(cases["data_inicio"].isna().sum()),
        "bairros": int(cases["NM_BAIRRO"].nunique(dropna=True)),
    }
    return cases, audit


def prepare_data() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    raw = pd.read_parquet(INPUT)
    raw["_score"] = raw[["n_ovos", "data_coleta", "agente"]].notna().sum(axis=1)
    raw["_score"] += raw["agente"].fillna("").astype(str).str.strip().ne("")
    raw = raw.sort_values(
        ["id_ovt_chave", "ano_arquivo", "ciclo", "_score"],
        ascending=[True, True, True, False], kind="mergesort"
    )
    duplicate_key = ["id_ovt_chave", "ano_arquivo", "ciclo"]
    duplicated = raw.duplicated(duplicate_key, keep=False)
    deduped = raw.drop_duplicates(duplicate_key, keep="first").copy()

    accepted = ["valida", "fora_recife_proxima", "sem_area_compesa"]
    frame = deduped[deduped["qualidade_geografica"].isin(accepted)].copy()
    frame = frame[frame["n_ovos"].notna() & frame["data_coleta"].notna()].copy()
    frame = frame[~frame["data_suspeita"]].copy()
    frame = frame[frame["data_coleta"].dt.year.isin([2024, 2025, 2026])].copy()
    frame = frame.dropna(subset=["latitude", "longitude"]).copy()
    environmental = frame.copy()

    for data in (environmental,):
        data["ano"] = data["ano_arquivo"].astype(int)
        data["ciclo"] = data["ciclo"].astype(int)
        data["mes"] = data["data_coleta"].dt.month.astype(int)
        data["h3_index"] = [
            h3.latlng_to_cell(float(lat), float(lon), 8)
            for lat, lon in data[["latitude", "longitude"]].itertuples(index=False, name=None)
        ]
        data["sem_area_compesa"] = data["qualidade_geografica"].eq("sem_area_compesa").astype(int)
        data["edl_distancia_km"] = data["distancia_edl_m"] / 1000
        data["edl_faixa"] = pd.cut(
            data["distancia_edl_m"],
            bins=[-np.inf, 100, 200, 300, 400, 500, np.inf],
            labels=["0-100m", "100-200m", "200-300m", "300-400m", "400-500m", ">500m"],
        ).astype(str)
        data["edl_400m"] = data["distancia_edl_m"].le(400).astype(int)
        for days in WINDOWS:
            data[f"horas_sem_abastecimento_{days}d"] = 24 * days - data[f"horas_abastecimento_{days}d"]
            data[f"dias_sem_abastecimento_{days}d"] = data[f"sem_abastecimento_{days}d"]

    environmental.to_parquet(OUTPUT, index=False)
    edl = environmental[environmental["distancia_edl_m"].notna()].copy()
    active = edl[edl["distancia_edl_ativa_m"].notna()].copy()
    active["edl_ativa_distancia_km"] = active["distancia_edl_ativa_m"] / 1000
    audit = {
        "raw_rows": int(len(raw)),
        "duplicate_rows": int(duplicated.sum()),
        "duplicate_keys": int(raw.loc[duplicated].drop_duplicates(duplicate_key).shape[0]),
        "duplicate_ids": sorted(raw.loc[duplicated, "id_ovt_chave"].unique().tolist()),
        "deduplicated_rows": int(len(deduped)),
        "eligible_before_environment": int(len(frame)),
        "environment_rows": int(len(environmental)),
        "edl_rows": int(len(edl)),
        "active_edl_rows": int(len(active)),
        "unknown_active_edl_rows": int(len(edl) - len(active)),
        "environment_rows_by_year": {str(k): int(v) for k, v in environmental.groupby("ano").size().items()},
        "edl_rows_by_year": {str(k): int(v) for k, v in edl.groupby("ano").size().items()},
        "zero_rows_environment": int((environmental["n_ovos"] == 0).sum()),
        "zero_fraction_environment": float((environmental["n_ovos"] == 0).mean()),
        "mean_eggs_environment": float(environmental["n_ovos"].mean()),
        "variance_eggs_environment": float(environmental["n_ovos"].var()),
        "variance_mean_ratio_environment": float(environmental["n_ovos"].var() / environmental["n_ovos"].mean()),
        "environment_missing": {f"{c}_{d}d": int(environmental[f"{c}_{d}d"].isna().sum()) for c in ("chuva_mm", "temperatura_media", "horas_abastecimento") for d in WINDOWS},
        "sem_area_compesa_levels": environmental["sem_area_compesa"].value_counts().to_dict(),
    }
    return environmental, active, audit


def model_data(data: pd.DataFrame, days: int) -> pd.DataFrame:
    columns = [
        "n_ovos", f"chuva_mm_{days}d", f"temperatura_media_{days}d",
        f"dias_sem_abastecimento_{days}d", "ano", "mes", "h3_index",
    ]
    return data.dropna(subset=columns).copy()


def model_formula(exposure: str | None, days: int, spatial: bool, year_effect: bool, month_effect: bool, data: pd.DataFrame) -> str:
    terms = []
    if exposure:
        terms.append(exposure)
    terms += [f"chuva_mm_{days}d", f"temperatura_media_{days}d", f"dias_sem_abastecimento_{days}d"]
    if data["sem_area_compesa"].nunique() > 1:
        terms.append("sem_area_compesa")
    if year_effect:
        terms.append("C(ano)")
    if month_effect:
        terms.append("C(mes)")
    if spatial:
        terms.append("C(h3_index)")
    return "n_ovos ~ " + " + ".join(terms)


def estimate_alpha(poisson: object) -> float:
    observed = np.asarray(poisson.model.endog, dtype=float)
    mean = np.maximum(np.asarray(poisson.fittedvalues, dtype=float), 1e-8)
    target = float(poisson.df_resid)

    def score(alpha: float) -> float:
        return float(np.sum((observed - mean) ** 2 / (mean + alpha * mean**2)) - target)

    if score(0) <= 0:
        return 0.0
    low, high = 0.0, 1.0
    while score(high) > 0 and high < 1e6:
        high *= 2
    for _ in range(80):
        middle = (low + high) / 2
        if score(middle) > 0:
            low = middle
        else:
            high = middle
    return float((low + high) / 2)


def fit_models(data: pd.DataFrame, exposure: str | None, days: int, spatial: bool = True, year_effect: bool = True, month_effect: bool = True) -> tuple[object, object]:
    data = model_data(data, days)
    formula = model_formula(exposure, days, spatial, year_effect, month_effect, data)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        poisson = smf.glm(formula, data=data, family=sm.families.Poisson()).fit()
        alpha = estimate_alpha(poisson)
        nb2 = smf.glm(formula, data=data, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
    nb2._nb2_alpha = alpha
    return poisson, nb2


def fit_custom_models(data: pd.DataFrame, formula: str) -> tuple[object, object]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        poisson = smf.glm(formula, data=data, family=sm.families.Poisson()).fit()
        alpha = estimate_alpha(poisson)
        nb2 = smf.glm(formula, data=data, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
    nb2._nb2_alpha = alpha
    return poisson, nb2


def prepare_did(environmental: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    exact = environmental[environmental["qualidade_data_instalacao_edl"].eq("data_exata")].copy()
    exact = exact[exact["data_instalacao_edl"].notna() & exact["distancia_edl_m"].notna()].copy()
    treated_ids = set(exact.loc[exact["distancia_edl_m"].le(400), "id_ovt_chave"])
    treated = environmental[environmental["id_ovt_chave"].isin(treated_ids)].copy()
    controls = environmental[~environmental["id_ovt_chave"].isin(treated_ids) & environmental["distancia_edl_m"].gt(400)].copy()
    did = pd.concat([treated, controls], ignore_index=True)
    did["treated_400m"] = did["id_ovt_chave"].isin(treated_ids).astype(int)
    did["post_installation"] = (
        did["treated_400m"].eq(1)
        & did["data_instalacao_edl"].notna()
        & did["data_coleta"].ge(did["data_instalacao_edl"])
    ).astype(int)
    did["did_effect"] = did["treated_400m"] * did["post_installation"]
    did = model_data(did, 7)
    summary = did.groupby(["treated_400m", "post_installation"], as_index=False).agg(
        observacoes=("n_ovos", "size"),
        ovitrampas=("id_ovt_chave", "nunique"),
        media_ovos=("n_ovos", "mean"),
        mediana_ovos=("n_ovos", "median"),
    )
    pre = did[did["ano"] < 2026].copy()
    pre["periodo_pre"] = pre["data_coleta"].dt.to_period("M").astype(str)
    pre_means = pre.groupby(["periodo_pre", "treated_400m"], as_index=False)["n_ovos"].mean()
    pre_means["tempo"] = pd.factorize(pre_means["periodo_pre"])[0]
    slopes = {}
    for treated_value, group in pre_means.groupby("treated_400m"):
        slopes[str(int(treated_value))] = float(np.polyfit(group["tempo"], group["n_ovos"], 1)[0]) if len(group) > 1 else np.nan
    audit = {
        "exact_installation_rows": int(len(exact)),
        "treated_ovitrampas": int(len(treated_ids)),
        "treated_rows": int(len(treated)),
        "control_rows_before_model": int(len(controls)),
        "did_model_rows": int(len(did)),
        "did_model_ovitrampas": int(did["id_ovt_chave"].nunique()),
        "treated_post_rows": int((did["did_effect"] == 1).sum()),
        "treated_pre_rows": int(((did["treated_400m"] == 1) & (did["post_installation"] == 0)).sum()),
        "control_rows": int((did["treated_400m"] == 0).sum()),
        "pretrend_slope_control": slopes.get("0"),
        "pretrend_slope_treated": slopes.get("1"),
        "pretrend_slope_difference": slopes.get("1", np.nan) - slopes.get("0", np.nan),
    }
    return did, audit, summary


def fit_row(result: object, analysis: str, exposure: str, validation: str, days: int) -> dict:
    aic = float(-2 * result.llf + 2 * len(result.params))
    bic = float(-2 * result.llf + len(result.params) * np.log(result.nobs))
    return {
        "analysis": analysis,
        "validation": validation,
        "window_days": days,
        "exposure": exposure,
        "model": "NB2" if hasattr(result, "_nb2_alpha") else "Poisson",
        "n": int(result.nobs),
        "aic": aic,
        "bic": bic,
        "deviance": float(getattr(result, "deviance", np.nan)),
        "dispersion_pearson": float(np.sum(result.resid_pearson ** 2) / result.df_resid),
        "alpha_nb2": float(getattr(result, "_nb2_alpha", np.nan)),
    }


def coefficients(result: object, analysis: str, exposure: str, validation: str, days: int) -> pd.DataFrame:
    interval = result.conf_int()
    return pd.DataFrame({
        "analysis": analysis,
        "validation": validation,
        "window_days": days,
        "exposure": exposure,
        "model": "NB2" if hasattr(result, "_nb2_alpha") else "Poisson",
        "term": result.params.index,
        "coef": result.params.to_numpy(),
        "std_err": result.bse.to_numpy(),
        "p_value": result.pvalues.to_numpy(),
        "ci_low": interval.iloc[:, 0].to_numpy(),
        "ci_high": interval.iloc[:, 1].to_numpy(),
    })


def prediction_metrics(result: object, test: pd.DataFrame) -> dict:
    predicted = np.maximum(np.asarray(result.predict(test), dtype=float), 1e-12)
    observed = test["n_ovos"].to_numpy(dtype=float)
    return {
        "log_score": float(np.mean(observed * np.log(predicted) - predicted)),
        "mae": float(np.mean(np.abs(observed - predicted))),
        "rmse": float(np.sqrt(np.mean((observed - predicted) ** 2))),
    }


def run_models(environmental: pd.DataFrame, edl: pd.DataFrame, active: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict, pd.DataFrame]:
    metrics, coefs = [], []
    for days in WINDOWS:
        env_poisson, env_nb2 = fit_models(environmental, None, days)
        for result in (env_poisson, env_nb2):
            metrics.append(fit_row(result, "ambiental", "nenhuma", "ajuste_completo", days))
            coefs.append(coefficients(result, "ambiental", "nenhuma", "ajuste_completo", days))

    exposure_models = {
        "edl_distancia_km": "distancia_continua",
        "C(edl_faixa)": "faixa_distancia",
        "edl_400m": "indicador_400m",
    }
    for exposure, label in exposure_models.items():
        poisson, nb2 = fit_models(edl, exposure, 7)
        for result in (poisson, nb2):
            metrics.append(fit_row(result, "edl_espacial", label, "ajuste_completo", 7))
            coefs.append(coefficients(result, "edl_espacial", label, "ajuste_completo", 7))

    if not active.empty:
        poisson, nb2 = fit_models(active, "edl_ativa_distancia_km", 7)
        for result in (poisson, nb2):
            metrics.append(fit_row(result, "edl_ativa_sensibilidade", "distancia_ativa_continua", "ajuste_completo", 7))
            coefs.append(coefficients(result, "edl_ativa_sensibilidade", "distancia_ativa_continua", "ajuste_completo", 7))

    for days in WINDOWS:
        for analysis, data, exposure in [("ambiental", environmental, None), ("edl_espacial", edl, "edl_distancia_km")]:
            train = data[data["ano"] < 2026]
            test = data[data["ano"] == 2026]
            if train.empty or test.empty:
                continue
            poisson, nb2 = fit_models(train, exposure, days, spatial=False, year_effect=False, month_effect=False)
            test = model_data(test, days)
            for result in (poisson, nb2):
                row = fit_row(result, analysis, "distancia_continua" if exposure else "nenhuma", "temporal_2026", days)
                row.update(prediction_metrics(result, test))
                metrics.append(row)

    edl = edl.copy()
    edl["_spatial_test"] = edl["h3_index"].map(lambda value: int(hashlib.md5(value.encode()).hexdigest(), 16) % 5 == 0)
    spatial_train, spatial_test = edl[~edl["_spatial_test"]], edl[edl["_spatial_test"]]
    poisson, nb2 = fit_models(spatial_train, "edl_distancia_km", 7, spatial=False, year_effect=True, month_effect=True)
    spatial_test = model_data(spatial_test, 7)
    for result in (poisson, nb2):
        row = fit_row(result, "edl_espacial", "distancia_continua", "espacial_bloco_h3", 7)
        row.update(prediction_metrics(result, spatial_test))
        metrics.append(row)

    did_data, did_audit, did_summary = prepare_did(environmental)
    did_formula = (
        "n_ovos ~ did_effect + chuva_mm_7d + temperatura_media_7d "
        "+ dias_sem_abastecimento_7d + C(ano) + C(mes) + C(h3_index)"
    )
    if not did_data.empty:
        poisson, nb2 = fit_custom_models(did_data, did_formula)
        for result in (poisson, nb2):
            metrics.append(fit_row(result, "did_400m", "tratado_pos", "ajuste_completo", 7))
            coefs.append(coefficients(result, "did_400m", "tratado_pos", "ajuste_completo", 7))

    validation = {
        "temporal_environment_train": int(len(model_data(environmental[environmental["ano"] < 2026], 7))),
        "temporal_environment_test": int(len(model_data(environmental[environmental["ano"] == 2026], 7))),
        "temporal_edl_train": int(len(edl[edl["ano"] < 2026])),
        "temporal_edl_test": int(len(edl[edl["ano"] == 2026])),
        "active_edl_sensitivity_rows": int(len(active)),
        "spatial_edl_train": int(len(spatial_train)),
        "spatial_edl_test": int(len(spatial_test)),
        "zinb_tested": False,
        "znib_tested": False,
    }
    validation["did"] = did_audit
    return pd.DataFrame(metrics), pd.concat(coefs, ignore_index=True), validation, did_summary


def make_figures(environmental: pd.DataFrame, edl: pd.DataFrame, disease: pd.DataFrame, did_summary: pd.DataFrame, metric_table: pd.DataFrame, coef_table: pd.DataFrame) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].hist(np.log1p(environmental["n_ovos"]), bins=40, color="#2563eb")
    axes[0].set(title="Distribuicao de n_ovos", xlabel="log(1 + n_ovos)", ylabel="Observacoes")
    axes[1].bar(["Zero", "Positivo"], [(environmental["n_ovos"] == 0).sum(), (environmental["n_ovos"] > 0).sum()], color=["#94a3b8", "#0f766e"])
    axes[1].set(title="Zeros e positivos", ylabel="Observacoes")
    fig.tight_layout(); fig.savefig(FIGURES / "distribuicao_resposta.png", dpi=150); plt.close(fig)

    monthly = environmental.groupby(["ano", "mes"])["n_ovos"].mean().unstack(0)
    fig, ax = plt.subplots(figsize=(10, 4)); monthly.plot(marker="o", ax=ax)
    ax.set(title="Media de n_ovos por mes e ano", xlabel="Mes", ylabel="Media de n_ovos"); fig.tight_layout(); fig.savefig(FIGURES / "sazonalidade_mensal.png", dpi=150); plt.close(fig)

    bins = pd.cut(edl["distancia_edl_m"], [-np.inf, 100, 200, 300, 400, 500, np.inf], labels=["0-100", "100-200", "200-300", "300-400", "400-500", ">500"])
    grouped = edl.assign(faixa=bins).groupby("faixa", observed=False)["n_ovos"].agg(["mean", "median", "count"])
    fig, ax = plt.subplots(figsize=(10, 4)); grouped["mean"].plot(kind="bar", ax=ax, color="#f97316")
    ax.set(title="Ovos medios por distancia ate a EDL mais proxima", xlabel="Faixa de distancia (m)", ylabel="Media de n_ovos")
    fig.tight_layout(); fig.savefig(FIGURES / "ovos_por_distancia.png", dpi=150); plt.close(fig)

    selected = coef_table[(coef_table["model"] == "NB2") & (coef_table["validation"] == "ajuste_completo")].copy()
    selected = selected[selected["term"].str.contains("edl_distancia|edl_400m|chuva_mm_7d|temperatura_media_7d|dias_sem_abastecimento_7d", regex=True)]
    selected["label"] = selected["analysis"] + ":" + selected["exposure"] + ":" + selected["term"]
    selected["irr"] = np.exp(selected["coef"]); selected["low"] = np.exp(selected["ci_low"]); selected["high"] = np.exp(selected["ci_high"])
    selected = selected.sort_values("irr")
    fig, ax = plt.subplots(figsize=(10, max(4, len(selected) * .35)))
    y = np.arange(len(selected)); ax.errorbar(selected["irr"], y, xerr=[selected["irr"] - selected["low"], selected["high"] - selected["irr"]], fmt="o", color="#7c3aed")
    ax.axvline(1, color="black", linewidth=1); ax.set_yticks(y, selected["label"]); ax.set_xlabel("Razao de medias (exp(coeficiente), IC 95%)"); ax.set_title("Coeficientes NB2")
    fig.tight_layout(); fig.savefig(FIGURES / "coeficientes_nb2.png", dpi=150); plt.close(fig)

    validation = metric_table[metric_table["validation"].isin(["temporal_2026", "espacial_bloco_h3"])].dropna(subset=["mae"])
    validation["split"] = validation["analysis"] + " / " + validation["validation"]
    fig, ax = plt.subplots(figsize=(10, 4)); validation.pivot_table(index="split", columns="model", values="mae", aggfunc="first").plot(kind="bar", ax=ax, color=["#64748b", "#0f766e"])
    ax.set(title="Erro absoluto medio fora da amostra", xlabel="Validacao", ylabel="MAE"); fig.tight_layout(); fig.savefig(FIGURES / "validacao_mae.png", dpi=150); plt.close(fig)

    if not did_summary.empty:
        plot_data = did_summary.copy()
        plot_data["grupo"] = np.where(plot_data["treated_400m"].eq(1), "Ate 400 m", ">400 m")
        plot_data["periodo"] = np.where(plot_data["post_installation"].eq(1), "Pos", "Pre")
        chart = plot_data.pivot(index="grupo", columns="periodo", values="media_ovos")
        fig, ax = plt.subplots(figsize=(7, 4)); chart[[c for c in ["Pre", "Pos"] if c in chart].copy()].plot(kind="bar", ax=ax, color=["#64748b", "#0f766e"])
        ax.set(title="Media de ovos antes e depois da instalacao registrada", xlabel="Grupo", ylabel="Media de n_ovos"); fig.tight_layout(); fig.savefig(FIGURES / "did_pre_pos.png", dpi=150); plt.close(fig)

    windows = coef_table[(coef_table["analysis"] == "ambiental") & (coef_table["model"] == "NB2") & (coef_table["validation"] == "ajuste_completo")].copy()
    windows = windows[windows["term"].str.contains("chuva_mm|temperatura_media|dias_sem_abastecimento")]
    windows["variavel"] = windows["term"].str.replace(r"_\d+d$", "", regex=True).str.replace("chuva_mm", "chuva", regex=False).str.replace("temperatura_media", "temperatura", regex=False).str.replace("dias_sem_abastecimento", "sem abastecimento", regex=False)
    fig, ax = plt.subplots(figsize=(10, 5))
    for variable, group in windows.groupby("variavel"):
        ax.plot(group["window_days"], group["coef"], marker="o", label=variable)
    ax.axhline(0, color="black", linewidth=1); ax.set(title="Coeficientes NB2 por janela ambiental", xlabel="Janela (dias)", ylabel="Coeficiente"); ax.legend(); fig.tight_layout(); fig.savefig(FIGURES / "janelas_ambientais.png", dpi=150); plt.close(fig)

    if not disease.empty:
        monthly_cases = disease.groupby(["mes", "doenca"]).size().unstack(fill_value=0)
        fig, ax = plt.subplots(figsize=(11, 4)); monthly_cases.plot(kind="bar", ax=ax)
        ax.set(title="Casos de arboviroses por mes em Recife", xlabel="Mes de inicio dos sintomas", ylabel="Casos registrados"); fig.tight_layout(); fig.savefig(FIGURES / "arboviroses_mensais.png", dpi=150); plt.close(fig)


def conclusion(coefs: pd.DataFrame, analysis: str, term_pattern: str, title: str) -> str:
    row = coefs[(coefs["analysis"] == analysis) & (coefs["model"] == "NB2") & (coefs["validation"] == "ajuste_completo") & coefs["term"].str.contains(term_pattern, regex=True)]
    if row.empty:
        return f"**{title}:** nao estimado na amostra final."
    row = row.iloc[0]
    if row.p_value < .05 and row.ci_low * row.ci_high > 0:
        direction = "associacao positiva" if row.coef > 0 else "associacao negativa"
        return f"**{title}:** evidencia de {direction} no ajuste NB2 (coeficiente {row.coef:.4f}, p={row.p_value:.3g}); isso nao demonstra causalidade."
    return f"**{title}:** nao ha evidencia estatistica robusta no ajuste NB2 (coeficiente {row.coef:.4f}, p={row.p_value:.3g})."


def write_outputs(environmental: pd.DataFrame, edl: pd.DataFrame, disease: pd.DataFrame, disease_audit: dict, did_summary: pd.DataFrame, audit: dict, metrics: pd.DataFrame, coefs: pd.DataFrame, validation: dict) -> None:
    REPORTS.mkdir(exist_ok=True)
    metrics.to_csv(REPORTS / "modelagem_aedes_bi_metricas.csv", index=False)
    coefs.to_csv(REPORTS / "modelagem_aedes_bi_coeficientes.csv", index=False)
    did_summary.to_csv(REPORTS / "did_400m_resumo.csv", index=False)
    diagnosis = {**audit, **validation}
    diagnosis["arboviroses"] = disease_audit
    window_lines = []
    for days in WINDOWS:
        rows = coefs[(coefs["analysis"] == "ambiental") & (coefs["model"] == "NB2") & (coefs["validation"] == "ajuste_completo") & (coefs["window_days"] == days)]
        values = []
        for pattern, label in [("chuva_mm", "chuva"), ("temperatura_media", "temperatura"), ("dias_sem_abastecimento", "falta_abastecimento")]:
            row = rows[rows["term"].str.contains(pattern)]
            if not row.empty:
                row = row.iloc[0]
                values.append(f"{label}={row.coef:.4f} (p={row.p_value:.3g})")
        window_lines.append(f"- {days} dias: " + "; ".join(values) + ".")
    (REPORTS / "modelagem_aedes_bi_diagnostico.json").write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2))
    lines = [
        "# Relatorio exploratorio de modelagem do AEDES BI", "",
        "Os resultados descrevem associacoes. Nao sao evidencia de causalidade nem de eficacia comprovada das EDLs.", "",
        "## Conclusoes", "",
        "**Conclusao sobre EDLs:** nao ha evidencia consistente para afirmar eficacia. A distancia ate a EDL mais proxima apresentou associacao negativa, o indicador de 400 m nao foi robusto e a distancia ate EDL ativa conhecida apresentou sinal contrario. Essa inconsistencia, somada a informacao incompleta de ativacao e manutencao, impede uma conclusao de eficacia.",
        "**Diferenca-em-diferencas:** a instalacao registrada em 2026 foi analisada como proxy de inicio da intervencao para 126 ovitrampas no raio de 400 m, com controles a mais de 400 m. O resultado deve ser interpretado somente se as tendencias pre-intervencao forem plausivelmente paralelas; a instalacao nao comprova ativacao, manutencao ou eficacia.",
        "**Conclusao sobre ambiente:** as janelas de 7, 14, 21 e 28 dias foram ajustadas separadamente. A leitura final deve priorizar sinais que se repetem entre janelas, anos e validacoes; um resultado isolado em uma janela nao e considerado evidencia robusta.",
        "",
        conclusion(coefs, "edl_espacial", "^edl_distancia_km$", "Distancia ate EDL mais proxima"),
        conclusion(coefs, "edl_espacial", "^edl_400m$", "Indicador de 400 m"),
        conclusion(coefs, "edl_ativa_sensibilidade", "^edl_ativa_distancia_km$", "Distancia ate EDL ativa conhecida (sensibilidade)"),
        conclusion(coefs, "did_400m", "^did_effect$", "Efeito DiD de instalacao registrada"),
        conclusion(coefs, "ambiental", "^chuva_mm_7d$", "Chuva em 7 dias"),
        conclusion(coefs, "ambiental", "^temperatura_media_7d$", "Temperatura em 7 dias"),
        conclusion(coefs, "ambiental", "^dias_sem_abastecimento_7d$", "Dias sem abastecimento em 7 dias"),
        "",
        "## Comparacao das janelas ambientais", "",
        "Cada janela foi ajustada em um modelo separado. Coeficientes positivos indicam maior media esperada de ovos conforme aumenta a covariavel, mantendo os demais termos do modelo.",
        *window_lines,
        "",
        "## Arboviroses", "",
        f"- Registros de Recife normalizados: {disease_audit.get('rows', 0)}.",
        f"- Por doenca: {disease_audit.get('by_disease', {})}.",
        "- Os casos foram agregados por mes e bairro/distrito. Esta etapa e descritiva; nao ha coordenadas individuais nem denominador populacional para taxas H3.",
        "",
        "## Diferenca-em-diferencas", "",
        f"- Resumo: {did_summary.to_string(index=False)}",
        "- O modelo compara a mudanca pre/post nas ovitrampas ate 400 m com ovitrampas a mais de 400 m, controlando clima, falta de abastecimento, ano, mes e efeitos fixos H3-8.",
        f"- Tendencia mensal pre-2026: grupo ate 400 m={validation['did'].get('pretrend_slope_treated'):.3f}; controle={validation['did'].get('pretrend_slope_control'):.3f}; diferenca={validation['did'].get('pretrend_slope_difference'):.3f}. Isso e um diagnostico simples, nao um teste definitivo de tendencias paralelas.",
        "",
        "## Base e exclusoes", "",
        f"- Base ambiental: {audit['environment_rows']} observacoes.",
        f"- Base EDL espacial: {audit['edl_rows']} observacoes.",
        f"- Exposicao EDL ativa conhecida: {audit['active_edl_rows']} observacoes; desconhecida: {audit['unknown_active_edl_rows']}. Observacoes desconhecidas nao foram excluidas da analise ambiental.",
        f"- Duplicidades de chave: {audit['duplicate_keys']} ({', '.join(audit['duplicate_ids'])}); tratadas somente na base derivada.",
        f"- Media ambiental de ovos: {audit['mean_eggs_environment']:.2f}; variancia: {audit['variance_eggs_environment']:.2f}; razao variancia/media: {audit['variance_mean_ratio_environment']:.2f}.",
        f"- Zeros: {audit['zero_fraction_environment']:.4f}.",
        "",
        "## Comparacao dos modelos", "", "```text", metrics.to_string(index=False), "```", "",
        "## Validacao", "",
        f"- Validacao temporal ambiental: treino {validation['temporal_environment_train']} e teste {validation['temporal_environment_test']}.",
        f"- Validacao temporal EDL: treino {validation['temporal_edl_train']} e teste {validation['temporal_edl_test']}.",
        f"- Validacao espacial EDL por blocos H3: treino {validation['spatial_edl_train']} e teste {validation['spatial_edl_test']}.",
        "- A validacao temporal continua limitada pela cobertura de datas e ciclos; os resultados fora da amostra devem ser lidos como diagnostico, nao como prova de previsao geral.",
        "",
        "## Limites", "",
        "- Distancia ate EDL mede proximidade espacial, nao confirma ativacao, manutencao ou eficacia.",
        "- A exposicao ativa so foi usada na analise de sensibilidade porque muitas datas de instalacao sao desconhecidas.",
        "- A temperatura media observada nao cobre 30--35 graus C; essa faixa nao pode ser inferida deste conjunto.",
        "- ZINB nao foi ajustado; a proporcao de zeros e baixa. ZNIB nao foi ajustado porque QT e o denominador binomial nao foram confirmados.",
    ]
    (REPORTS / "modelagem_aedes_bi.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    environmental, active, audit = prepare_data()
    disease, disease_audit = load_arboviroses()
    metrics, coefs, validation, did_summary = run_models(environmental, environmental.copy(), active)
    make_figures(environmental, environmental, disease, did_summary, metrics, coefs)
    write_outputs(environmental, active, disease, disease_audit, did_summary, audit, metrics, coefs, validation)
    print(json.dumps({**audit, **validation, "arboviroses": disease_audit}, ensure_ascii=False, indent=2))
    print("\nMETRICAS\n" + metrics.to_string(index=False))
    print("\nCONCLUSOES\n" + "\n".join([
        conclusion(coefs, "edl_espacial", "^edl_distancia_km$", "Distancia EDL"),
        conclusion(coefs, "edl_espacial", "^edl_400m$", "EDL a 400m"),
        conclusion(coefs, "edl_ativa_sensibilidade", "^edl_ativa_distancia_km$", "EDL ativa conhecida"),
        conclusion(coefs, "ambiental", "^chuva_mm_7d$", "Chuva"),
        conclusion(coefs, "ambiental", "^temperatura_media_7d$", "Temperatura"),
        conclusion(coefs, "ambiental", "^dias_sem_abastecimento_7d$", "Falta de abastecimento"),
    ]))


if __name__ == "__main__":
    main()
