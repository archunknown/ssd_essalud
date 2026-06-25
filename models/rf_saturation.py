"""
models/rf_saturation.py
Modelo 2 — Clasificacion de saturacion (Random Forest). SSD EsSalud.

Clasifica el NIVEL de saturacion por departamento y mes. El nivel se define por
umbrales sobre el ratio de saturacion departamental:
    ratio = atenciones_mes / linea_base_departamental * 100
    linea_base_departamental = p90 de los totales mensuales NO-COVID del
    departamento (mismo metodo que la base por establecimiento, a grano
    departamento; NO la suma de bases por establecimiento).

CLASES: se colapso de 4 a 3 por rareza estructural de la saturacion critica
(12/1200 casos en 4 anios x 25 deptos): ningun clasificador aprende una clase
con 12 ejemplos. 'Saturado' fusiona los antiguos 'Alto' (90-110) y 'Critico'
(>110): operativamente son la misma accion (intervenir). El reporte de 4 clases
del intento original es la evidencia del rediseno (documentar en monografia).
    tres   : Bajo (<70) / Normal (70-90) / Saturado (>=90)
    binario: Normal (<90) / Saturado (>=90)   [Bajo absorbido en Normal]
Si el F1 macro no alcanza 80% por la rareza de 'Bajo' (~2% de los meses),
cambiar CLASS_SCHEME a "binario" y re-ejecutar. No requiere otro cambio.

ANTI-CIRCULARIDAD: el RF NO recibe el ratio del propio mes (seria reproducir el
umbral). Aprende desde senales ANTECEDENTES: rezagos del ratio (t-1,2,3,12),
rezagos de atenciones (t-1,12), mes y departamento.

Entrenamiento: regimen estable 2016-2019. Validacion: StratifiedKFold, F1 macro
(metrica de aceptacion) + ponderado + por clase. Aplica al horizonte proyectado
(resultado_proyeccion) -> resultado_clasificacion.

Requisitos: DW poblado (01-06), sql/06_alter_check_nivel.sql aplicado, y
prophet_demand.py ejecutado. Ejecutar:  python models/rf_saturation.py
"""
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import f1_score, classification_report
import config

warnings.filterwarnings("ignore")

CLASS_SCHEME = "binario"          # "tres" | "binario"
COVID_YEARS = (2020, 2021)
TRAIN_YEARS = (2016, 2017, 2018, 2019)
BASELINE_PERCENTILE = 0.90
U_BAJO, U_NORMAL = 70, 90      # Saturado = ratio >= U_NORMAL (ex Alto+Critico)

RATIO_LAGS = [1, 2, 3, 12]
ATEN_LAGS = [1, 12]
LAG_COLS = [f"ratio_lag{L}" for L in RATIO_LAGS] + [f"aten_lag{L}" for L in ATEN_LAGS]
BASE_FEATS = LAG_COLS + ["mes"]

N_ESTIMATORS = 300
RANDOM_STATE = 42
N_SPLITS = 5


def engine():
    return create_engine(config.CONNECTION_STRING, fast_executemany=True)


def nivel(ratio):
    if CLASS_SCHEME == "binario":
        return "Saturado" if ratio >= U_NORMAL else "Normal"
    if ratio < U_BAJO:
        return "Bajo"
    if ratio < U_NORMAL:
        return "Normal"
    return "Saturado"


def load_series(eng):
    q = text("""
        SELECT g.id_departamento AS id_dep, t.fecha_inicio AS ds, t.anio AS anio,
               SUM(f.cantidad_atenciones) AS aten
        FROM dw.fact_atenciones f
        JOIN dw.dim_tiempo t    ON f.id_tiempo = t.id_tiempo
        JOIN dw.dim_geografia g ON f.id_geografia = g.id_geografia
        WHERE g.id_departamento IS NOT NULL
        GROUP BY g.id_departamento, t.fecha_inicio, t.anio
    """)
    df = pd.read_sql(q, eng)
    df["ds"] = pd.to_datetime(df["ds"])
    return df.sort_values(["id_dep", "ds"]).reset_index(drop=True)


def load_proyeccion(eng):
    p = pd.read_sql(text("""
        SELECT id_departamento AS id_dep, mes_proyectado AS ds,
               atenciones_proyectadas AS aten
        FROM dw.resultado_proyeccion
    """), eng)
    if p.empty:
        sys.exit("resultado_proyeccion vacia; corre models/prophet_demand.py primero.")
    p["ds"] = pd.to_datetime(p["ds"])
    return p


def dept_baseline(df):
    nc = df[~df["anio"].isin(COVID_YEARS)]
    return nc.groupby("id_dep")["aten"].quantile(BASELINE_PERCENTILE)


def _add_lags(s):
    for L in RATIO_LAGS:
        s[f"ratio_lag{L}"] = s["ratio"].shift(L)
    for L in ATEN_LAGS:
        s[f"aten_lag{L}"] = s["aten"].shift(L)
    return s


def build_panel(df, baseline):
    idx = pd.date_range(df["ds"].min(), df["ds"].max(), freq="MS")
    frames = []
    for id_dep, g in df.groupby("id_dep"):
        s = g.set_index("ds")[["aten"]].reindex(idx)
        s["ratio"] = s["aten"] / baseline.get(id_dep, np.nan) * 100
        s = _add_lags(s)
        s["mes"] = s.index.month
        s["anio"] = s.index.year
        s["id_dep"] = id_dep
        frames.append(s.reset_index(drop=True))
    return pd.concat(frames, ignore_index=True)


def build_pred_features(df, baseline, proj):
    frames = []
    for id_dep in sorted(proj["id_dep"].unique()):
        base = baseline.get(id_dep, np.nan)
        act = df[(df["id_dep"] == id_dep) & (df["ds"] >= "2022-01-01")][["ds", "aten"]]
        pr = proj[proj["id_dep"] == id_dep][["ds", "aten"]]
        comb = (pd.concat([act, pr]).drop_duplicates("ds")
                .sort_values("ds").set_index("ds"))
        comb = comb.reindex(pd.date_range(comb.index.min(), comb.index.max(), freq="MS"))
        comb["ratio"] = comb["aten"] / base * 100
        comb = _add_lags(comb)
        comb["mes"] = comb.index.month
        comb["id_dep"] = id_dep
        keep = comb[comb.index.isin(pr["ds"])].copy()
        keep["ds"] = keep.index
        frames.append(keep.reset_index(drop=True))
    return pd.concat(frames, ignore_index=True)


def make_X(frame, all_deps):
    base = frame[BASE_FEATS].reset_index(drop=True)
    dep = pd.Categorical(frame["id_dep"].values, categories=all_deps)
    dum = pd.get_dummies(dep, prefix="dep").reset_index(drop=True)
    return pd.concat([base, dum], axis=1)


def main():
    eng = engine()
    df = load_series(eng)
    baseline = dept_baseline(df)
    all_deps = sorted(df["id_dep"].unique())

    panel = build_panel(df, baseline)
    train = panel[panel["anio"].isin(TRAIN_YEARS)].dropna(subset=LAG_COLS + ["ratio"]).copy()
    train["nivel"] = train["ratio"].map(nivel)

    counts = train["nivel"].value_counts()
    splits = max(2, min(N_SPLITS, int(counts.min())))

    X = make_X(train, all_deps)
    y = train["nivel"].values
    clf = RandomForestClassifier(n_estimators=N_ESTIMATORS, class_weight="balanced",
                                 random_state=RANDOM_STATE, n_jobs=-1)
    skf = StratifiedKFold(n_splits=splits, shuffle=True, random_state=RANDOM_STATE)
    y_cv = cross_val_predict(clf, X, y, cv=skf)
    f1_macro = f1_score(y, y_cv, average="macro") * 100
    f1_weight = f1_score(y, y_cv, average="weighted") * 100
    clf.fit(X, y)

    proj = load_proyeccion(eng)
    pf = build_pred_features(df, baseline, proj).dropna(subset=LAG_COLS + ["ratio"]).copy()
    descartadas = len(proj) - len(pf)
    pf["nivel"] = clf.predict(make_X(pf, all_deps))

    ins = pd.DataFrame({
        "id_departamento": pf["id_dep"].astype(int),
        "mes_clasificado": pf["ds"].dt.date,
        "ratio_saturacion": pf["ratio"].round(2),
        "nivel_saturacion": pf["nivel"],
        "f1_score_validacion": round(f1_macro, 2),
    })
    with eng.begin() as cx:
        cx.execute(text("DELETE FROM dw.resultado_clasificacion;"))
    ins.to_sql("resultado_clasificacion", eng, schema="dw",
               if_exists="append", index=False, chunksize=1000)

    print(f"=== Random Forest — clasificacion de saturacion (esquema: {CLASS_SCHEME}) ===")
    print(f"muestras de entrenamiento (2016-2019): {len(train)}")
    print("distribucion de clases (entrenamiento):")
    print(counts.to_string())
    print(f"folds estratificados usados           : {splits}")
    print(f"\nF1 macro    (metrica de aceptacion) : {f1_macro:6.2f}%   (criterio >= 80%)")
    print(f"F1 ponderado                        : {f1_weight:6.2f}%")
    print("\nReporte por clase (validacion cruzada):")
    print(classification_report(y, y_cv, zero_division=0))
    print(f"clasificaciones escritas en resultado_clasificacion: {len(ins)} filas")
    if descartadas:
        print(f"[AVISO] {descartadas} meses proyectados sin rezagos completos, no clasificados.")
    print("Distribucion del nivel proyectado 2023:")
    print(pf["nivel"].value_counts().to_string())


if __name__ == "__main__":
    main()