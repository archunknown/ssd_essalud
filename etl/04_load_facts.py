"""
etl/04_load_facts.py

Paso 4 del ETL — SSD EsSalud.
Carga fact_atenciones al DW resolviendo las cuatro claves subrogadas contra
las dimensiones ya pobladas (paso 03).

Escrito contra el DDL real (sql/03_create_facts.sql). Grano:
  periodo x establecimiento x especialidad x geografia.
Las cuatro FK son NOT NULL: toda fila cuya clave no resuelva va a cuarentena
(no se carga) y se cuenta para la tasa de validos.

ratio_saturacion se deja sin cargar (columna NULL en el DDL): se computa en
el paso 02b una vez fijado el modelo de saturacion.

Mide la tasa de validos = filas cargadas / filas del hecho agregado, contra
el criterio de aceptacion 2 del PRD (>= 95%).

Ejecutar despues del paso 03:  python etl/04_load_facts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import create_engine, text
import config

F_FACT = os.path.join(config.PROCESSED_DIR, "fact_atenciones_consultas.csv")
F_REJECTS = os.path.join(config.PROCESSED_DIR, "fact_rechazadas.csv")
UMBRAL_VALIDOS = 0.95  # criterio de aceptacion 2 (PRD)


def engine():
    return create_engine(config.CONNECTION_STRING, fast_executemany=True)


def lookups(eng):
    t = pd.read_sql(text("SELECT id_tiempo, periodo FROM dw.dim_tiempo"), eng)
    e = pd.read_sql(text("SELECT id_establecimiento, nombre_centro FROM dw.dim_establecimiento"), eng)
    s = pd.read_sql(text("SELECT id_especialidad, especialidad FROM dw.dim_especialidad"), eng)
    g = pd.read_sql(text("SELECT id_geografia, ubigeo FROM dw.dim_geografia"), eng)
    return (
        dict(zip(t["periodo"].astype(int), t["id_tiempo"])),
        dict(zip(e["nombre_centro"], e["id_establecimiento"])),
        dict(zip(s["especialidad"], s["id_especialidad"])),
        dict(zip(g["ubigeo"].astype(str), g["id_geografia"])),
    )


def main():
    if not os.path.exists(F_FACT):
        sys.exit("Falta fact_atenciones_consultas.csv; corre el paso 02.")

    df = pd.read_csv(F_FACT, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    total = len(df)
    df["cantidad_atenciones"] = pd.to_numeric(df["cantidad_atenciones"], errors="coerce").astype("Int64")

    eng = engine()
    lk_t, lk_e, lk_s, lk_g = lookups(eng)

    df["id_tiempo"] = df["periodo"].astype(int).map(lk_t).astype("Int64")
    df["id_establecimiento"] = df["nombre_centro"].map(lk_e).astype("Int64")
    df["id_especialidad"] = df["especialidad"].map(lk_s).astype("Int64")
    df["id_geografia"] = df["ubigeo"].astype(str).map(lk_g).astype("Int64")

    fk = ["id_tiempo", "id_establecimiento", "id_especialidad", "id_geografia"]
    ok = df[fk + ["cantidad_atenciones"]].notna().all(axis=1)
    validas = df[ok]
    rechazadas = df[~ok]

    if len(rechazadas):
        # motivo: que clave fallo
        motivos = {c: int(df.loc[~ok, c].isna().sum()) for c in fk + ["cantidad_atenciones"]}
        rechazadas.to_csv(F_REJECTS, sep=";", encoding="utf-8-sig", index=False)

    carga = validas[fk + ["cantidad_atenciones"]].copy()
    carga["cantidad_atenciones"] = carga["cantidad_atenciones"].astype(int)
    carga.to_sql("fact_atenciones", eng, schema="dw", if_exists="append",
                 index=False, chunksize=2000)

    tasa = len(validas) / total if total else 0.0
    print("=== CARGA fact_atenciones ===")
    print(f"{'filas hecho agregado':<26}: {total:>8}")
    print(f"{'cargadas':<26}: {len(validas):>8}")
    print(f"{'rechazadas (FK no resuelta)':<26}: {len(rechazadas):>8}")
    if len(rechazadas):
        for k, v in motivos.items():
            if v:
                print(f"    {k:<22}: {v:>8}")
        print(f"  detalle en: {F_REJECTS}")
    print(f"{'tasa de validos':<26}: {tasa:>8.2%}  (criterio PRD >= {UMBRAL_VALIDOS:.0%})")
    print("OK" if tasa >= UMBRAL_VALIDOS else "[FALLA] Tasa bajo el umbral: revisar rechazadas antes de continuar.")


if __name__ == "__main__":
    main()