"""
etl/05_compute_baseline.py

Paso 5 del ETL — SSD EsSalud.
Calcula linea_base_operativa por establecimiento (denominador de saturacion,
PRD RN-01) y la escribe en dw.dim_establecimiento.

Corre DESPUES del paso 04: necesita dw.fact_atenciones poblada.

Decisiones de diseno (reversibles via las constantes de abajo):
  - Estimador: percentil alto (p90) del total mensual de atenciones del
    establecimiento. NO el promedio: el promedio centra el ratio en ~100 y
    dispara 'Critico' (>110) ante variacion estacional normal; el p90 es
    proxy del techo operativo que el establecimiento demostro sostener.
  - Exclusion COVID: 2020-2021 fuera del denominador. El ratio de esos meses
    se calcula aparte contra la base no-COVID y saldra bajo (hecho real).
  - Minimo de meses: >= 24 meses no-COVID para base estable (consistente con
    el requisito de 24 meses de Prophet). Por debajo, linea_base = NULL y el
    establecimiento no se clasifica.

ratio_saturacion NO se materializa en fact_atenciones (es no-aditivo): se
deriva como medida en el dashboard y en Python para el modelo departamental.

Ejecutar:  python etl/05_compute_baseline.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import create_engine, text
import config

# --- decisiones como constantes ---------------------------------------------
BASELINE_PERCENTILE = 0.90      # p90. Para p95: 0.95. Para promedio: pon USE_MEAN=True
USE_MEAN = False                # True => usa el promedio en vez del percentil
COVID_YEARS = (2020, 2021)
MIN_MESES = 24
# ----------------------------------------------------------------------------


def engine():
    return create_engine(config.CONNECTION_STRING, fast_executemany=True)


def monthly_totals(eng):
    """Total mensual de atenciones por establecimiento (suma sobre especialidad
    y geografia). Resultado pequeno: ~establecimientos x meses."""
    q = text("""
        SELECT f.id_establecimiento AS id_est,
               t.periodo            AS periodo,
               t.anio               AS anio,
               SUM(f.cantidad_atenciones) AS total
        FROM dw.fact_atenciones f
        JOIN dw.dim_tiempo t ON f.id_tiempo = t.id_tiempo
        GROUP BY f.id_establecimiento, t.periodo, t.anio
    """)
    return pd.read_sql(q, eng)


def compute(df):
    base = df[~df["anio"].isin(COVID_YEARS)]
    g = base.groupby("id_est")["total"]
    estimador = g.mean() if USE_MEAN else g.quantile(BASELINE_PERCENTILE)
    res = pd.DataFrame({"meses": g.size(), "linea_base": estimador}).reset_index()
    res.loc[res["meses"] < MIN_MESES, "linea_base"] = pd.NA
    res["linea_base"] = res["linea_base"].round(2)
    return res


def update_dim(eng, res):
    rows = [
        (None if pd.isna(r.linea_base) else float(r.linea_base), int(r.id_est))
        for r in res.itertuples()
    ]
    with eng.begin() as cx:
        cx.exec_driver_sql(
            "UPDATE dw.dim_establecimiento SET linea_base_operativa = ? "
            "WHERE id_establecimiento = ?", rows)


def main():
    eng = engine()
    df = monthly_totals(eng)
    if df.empty:
        sys.exit("dw.fact_atenciones vacia; corre el paso 04 primero.")

    res = compute(df)
    update_dim(eng, res)

    con_base = int(res["linea_base"].notna().sum())
    metodo = "promedio" if USE_MEAN else f"p{int(BASELINE_PERCENTILE * 100)}"
    print("=== linea_base_operativa ===")
    print(f"{'establecimientos con datos':<28}: {len(res):>8}")
    print(f"{'  con base (>= ' + str(MIN_MESES) + ' meses)':<28}: {con_base:>8}")
    print(f"{'  sin base (NULL)':<28}: {len(res) - con_base:>8}")
    print(f"{'estimador':<28}: {metodo:>8}")
    print(f"{'anios excluidos':<28}: {','.join(map(str, COVID_YEARS)):>8}")
    serie = res.loc[res["linea_base"].notna(), "linea_base"]
    if len(serie):
        print("\nDistribucion linea_base:")
        print(serie.describe().round(1).to_string())


if __name__ == "__main__":
    main()