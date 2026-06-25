"""
models/prophet_demand.py
Modelo 1 — Proyeccion de demanda (Prophet). SSD EsSalud.

Una serie por departamento (25). Entrena sobre atenciones mensuales agregadas
por departamento. Excluye 2020-2021 (COVID) del entrenamiento.

Dos evaluaciones (decision del proyecto):
  - MAPE PRINCIPAL: cross_validation de Prophet sobre la era estable 2015-2019.
    Es el MAPE de aceptacion (criterio PRD: < 10%).
  - MAPE RECUPERACION: modelo entrenado en 2015-2019 prediciendo 2022. Se
    reporta aparte como desempeno post-COVID; NO es el MAPE de aceptacion.

Modelo de PRODUCCION: entrena sobre 2015-2019 + 2022 y proyecta HORIZONTE_MESES
(RN-04 = 6) -> dw.resultado_proyeccion.

Limitacion estructural (reportar, no esconder): la proyeccion 2023 se hace
sobre datos que terminan en 2022-12 y cruzan el hueco 2020-2021; la tendencia
interpola ese hueco. La confiabilidad de la proyeccion esta acotada por eso.

Requisitos: DW poblado (pasos 01-06).
Ejecutar:  python models/prophet_demand.py
"""
import os
import sys
import logging
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from prophet import Prophet
from prophet.diagnostics import cross_validation, performance_metrics
import config

warnings.filterwarnings("ignore")
logging.getLogger("prophet").setLevel(logging.CRITICAL)
logging.getLogger("cmdstanpy").setLevel(logging.CRITICAL)
logging.getLogger("cmdstanpy").disabled = True   # el setLevel solo no basta

COVID_YEARS = (2020, 2021)
STABLE_YEARS = (2015, 2016, 2017, 2018, 2019)
RECOVERY_YEAR = 2022
HORIZON_MESES = config.HORIZONTE_MESES   # 6
MIN_STABLE = 48                          # meses minimos en era estable para CV

CV_INITIAL = "1095 days"   # ~36 meses de entrenamiento inicial
CV_PERIOD = "183 days"     # ~6 meses entre cortes
CV_HORIZON = "183 days"    # ~6 meses de horizonte (coincide con RN-04)


def engine():
    return create_engine(config.CONNECTION_STRING, fast_executemany=True)


def load_series(eng):
    q = text("""
        SELECT g.id_departamento AS id_dep,
               t.fecha_inicio     AS ds,
               t.anio             AS anio,
               SUM(f.cantidad_atenciones) AS y
        FROM dw.fact_atenciones f
        JOIN dw.dim_tiempo t    ON f.id_tiempo = t.id_tiempo
        JOIN dw.dim_geografia g ON f.id_geografia = g.id_geografia
        WHERE g.id_departamento IS NOT NULL
        GROUP BY g.id_departamento, t.fecha_inicio, t.anio
    """)
    df = pd.read_sql(q, eng)
    df["ds"] = pd.to_datetime(df["ds"])
    return df.sort_values(["id_dep", "ds"]).reset_index(drop=True)


def new_model():
    return Prophet(yearly_seasonality=True, weekly_seasonality=False,
                   daily_seasonality=False, interval_width=0.95)


def mape(actual, pred):
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    m = actual != 0
    if not m.any():
        return np.nan
    return float(np.mean(np.abs((actual[m] - pred[m]) / actual[m])) * 100)


def primary_mape(stable):
    model = new_model().fit(stable[["ds", "y"]])
    cv = cross_validation(model, initial=CV_INITIAL, period=CV_PERIOD,
                          horizon=CV_HORIZON, disable_tqdm=True)
    pm = performance_metrics(cv, metrics=["mape"])
    return float(pm["mape"].mean() * 100), model


def recovery_mape(model_stable, df_dep):
    obs = df_dep[df_dep["anio"] == RECOVERY_YEAR]
    if obs.empty:
        return np.nan
    fcst = model_stable.predict(obs[["ds"]])
    return mape(obs["y"].values, fcst["yhat"].values)


def production_forecast(usable):
    model = new_model().fit(usable[["ds", "y"]])
    future = model.make_future_dataframe(periods=HORIZON_MESES, freq="MS")
    fcst = model.predict(future).tail(HORIZON_MESES)
    out = fcst[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
    for c in ["yhat", "yhat_lower", "yhat_upper"]:
        out[c] = out[c].round().clip(lower=0).astype(int)
    return out


def main():
    eng = engine()
    df = load_series(eng)
    deps = pd.read_sql(text("SELECT id_departamento AS id_dep, nombre FROM dw.dim_departamento"), eng)
    nombre = dict(zip(deps["id_dep"], deps["nombre"]))

    proyecciones, resumen = [], []
    for id_dep, g in df.groupby("id_dep"):
        nom = nombre.get(id_dep, str(id_dep))
        stable = g[g["anio"].isin(STABLE_YEARS)]
        usable = g[~g["anio"].isin(COVID_YEARS)]
        if len(stable) < MIN_STABLE:
            resumen.append((id_dep, nom, len(stable), np.nan, np.nan, "SIN_CV"))
            continue
        try:
            mp, model_stable = primary_mape(stable)
            mr = recovery_mape(model_stable, g)
            fc = production_forecast(usable)
            fc["id_departamento"] = id_dep
            fc["mape_validacion"] = round(mp, 2)
            proyecciones.append(fc)
            resumen.append((id_dep, nom, len(stable), round(mp, 2),
                            None if np.isnan(mr) else round(mr, 2), "OK"))
        except Exception as e:
            resumen.append((id_dep, nom, len(stable), np.nan, np.nan, f"ERROR:{type(e).__name__}"))

    n_filas = 0
    if proyecciones:
        allf = pd.concat(proyecciones, ignore_index=True)
        ins = pd.DataFrame({
            "id_departamento": allf["id_departamento"],
            "mes_proyectado": allf["ds"].dt.date,
            "atenciones_proyectadas": allf["yhat"],
            "limite_inferior_ic95": allf["yhat_lower"],
            "limite_superior_ic95": allf["yhat_upper"],
            "mape_validacion": allf["mape_validacion"],
        })
        with eng.begin() as cx:
            cx.execute(text("DELETE FROM dw.resultado_proyeccion;"))
        ins.to_sql("resultado_proyeccion", eng, schema="dw",
                   if_exists="append", index=False, chunksize=1000)
        n_filas = len(ins)

    res = pd.DataFrame(resumen, columns=["id_dep", "departamento", "meses_estables",
                                         "mape_principal", "mape_2022", "estado"])
    ok = res[res["estado"] == "OK"]
    print("=== Prophet — proyeccion de demanda por departamento ===")
    print(res.to_string(index=False))
    print(f"\ndepartamentos modelados : {len(ok)}/{len(res)}")
    if len(ok):
        cumplen = int((ok["mape_principal"] < 10).sum())
        print(f"MAPE principal < 10%    : {cumplen}/{len(ok)}  (criterio de aceptacion)")
        print(f"MAPE principal mediana  : {ok['mape_principal'].median():.2f}%")
        mr_series = ok["mape_2022"].dropna()
        if len(mr_series):
            print(f"MAPE 2022 mediana       : {mr_series.median():.2f}%  (recuperacion post-COVID, informativo)")
    print(f"proyecciones escritas en resultado_proyeccion: {n_filas} filas")


if __name__ == "__main__":
    main()