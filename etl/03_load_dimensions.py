"""
etl/03_load_dimensions.py

Paso 3 del ETL — SSD EsSalud.
Carga las cuatro dimensiones al Data Warehouse (esquema dw) desde el staging
del paso 02 (y el enriquecimiento RENIPRESS del paso 01).

Escrito contra el DDL real (sql/01_create_schema.sql). Las subrogadas son
IDENTITY(1,1): NO se insertan; SQL Server las genera. Tras insertar cada
dimension se relee para construir el lookup clave_natural -> subrogada.

Orden por dependencia de FK:
  dim_geografia -> dim_tiempo -> dim_especialidad -> dim_establecimiento
  (dim_establecimiento.id_geografia es FK a dim_geografia).

linea_base_operativa se carga NULL: se calcula en el paso 02b una vez fijado
el estimador de linea base y la exclusion COVID del denominador.

RESET: borra los datos en orden seguro de FK para permitir recarga limpia.
La reconstruccion total del esquema (reseed de IDENTITY) se hace re-ejecutando
los scripts sql/. Este reset es solo de datos.

Ejecutar desde la raiz:  python etl/03_load_dimensions.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import create_engine, text
import config

P = config.PROCESSED_DIR
F_GEO = os.path.join(P, "geografia_union.csv")
F_TIEMPO = os.path.join(P, "dim_tiempo.csv")
F_ESPEC = os.path.join(P, "dim_especialidad.csv")
F_ESTAB = os.path.join(P, "establecimientos_atenciones.csv")
F_RENIPRESS = os.path.join(P, "renipress_essalud_activo.csv")

RESET_ORDER = [
    "dw.resultado_clasificacion", "dw.resultado_proyeccion",
    "dw.fact_atenciones", "dw.dim_establecimiento",
    "dw.dim_especialidad", "dw.dim_tiempo", "dw.dim_geografia",
]


def engine():
    return create_engine(config.CONNECTION_STRING, fast_executemany=True)


def require(*paths):
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        sys.exit("Falta staging; corre los pasos 01 y 02 primero:\n  " +
                 "\n  ".join(missing))


def reset(eng):
    with eng.begin() as cx:
        for t in RESET_ORDER:
            cx.execute(text(f"DELETE FROM {t};"))
    print("Reset: tablas dw vaciadas (orden seguro de FK).")


def load_geografia(eng):
    df = pd.read_csv(F_GEO, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df = df[["ubigeo", "departamento", "provincia", "distrito"]]
    df.to_sql("dim_geografia", eng, schema="dw", if_exists="append",
              index=False, chunksize=1000)
    look = pd.read_sql(text("SELECT id_geografia, ubigeo FROM dw.dim_geografia"), eng)
    print(f"dim_geografia        : {len(df):>6} filas")
    return dict(zip(look["ubigeo"], look["id_geografia"]))


def load_tiempo(eng):
    df = pd.read_csv(F_TIEMPO, sep=";", encoding="utf-8-sig", parse_dates=["fecha_inicio"])
    df = df[["periodo", "anio", "mes", "nombre_mes", "trimestre", "semestre", "fecha_inicio"]]
    df.to_sql("dim_tiempo", eng, schema="dw", if_exists="append",
              index=False, chunksize=1000)
    print(f"dim_tiempo           : {len(df):>6} filas")


def load_especialidad(eng):
    df = pd.read_csv(F_ESPEC, sep=";", encoding="utf-8-sig", keep_default_na=False)
    df["area"] = df["area"].replace("", None)
    df = df[["especialidad", "area"]]
    df.to_sql("dim_especialidad", eng, schema="dw", if_exists="append",
              index=False, chunksize=1000)
    print(f"dim_especialidad     : {len(df):>6} filas")


def load_establecimiento(eng, geo_lookup):
    est = pd.read_csv(F_ESTAB, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)

    # Enriquecimiento opcional RENIPRESS por nombre normalizado.
    rp = pd.read_csv(F_RENIPRESS, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    rp = rp[["NOMBRE_NORM", "COD_IPRESS", "CATEGORIA"]].drop_duplicates(subset="NOMBRE_NORM")
    rp = rp.rename(columns={"NOMBRE_NORM": "nombre_norm",
                            "COD_IPRESS": "cod_ipress", "CATEGORIA": "categoria"})

    m = est.merge(rp, on="nombre_norm", how="left")
    tasa_match = m["cod_ipress"].notna().mean() if len(m) else 0.0

    m["id_geografia"] = m["ubigeo"].map(geo_lookup).astype("Int64")
    out = pd.DataFrame({
        "nombre_centro": m["nombre_centro"],
        "red_essalud": m["red_essalud"].replace("", None),
        "cod_ipress": m["cod_ipress"],
        "categoria": m["categoria"],
        "id_geografia": m["id_geografia"],
        "linea_base_operativa": pd.NA,  # paso 02b
    })
    out.to_sql("dim_establecimiento", eng, schema="dw", if_exists="append",
               index=False, chunksize=1000)
    print(f"dim_establecimiento  : {len(out):>6} filas")
    print(f"  enriquecidos RENIPRESS (categoria/cod_ipress): "
          f"{int(m['cod_ipress'].notna().sum())}/{len(m)}  "
          f"(tasa match {tasa_match:.1%})")
    print(f"  sin id_geografia (ubigeo no resuelto)        : "
          f"{int(out['id_geografia'].isna().sum())}")


if __name__ == "__main__":
    require(F_GEO, F_TIEMPO, F_ESPEC, F_ESTAB, F_RENIPRESS)
    eng = engine()
    reset(eng)
    geo_lookup = load_geografia(eng)
    load_tiempo(eng)
    load_especialidad(eng)
    load_establecimiento(eng, geo_lookup)
    print("\nDimensiones cargadas. Procede el paso 04 (hechos).")