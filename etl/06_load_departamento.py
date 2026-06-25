"""
etl/06_load_departamento.py

Paso 6 del ETL — SSD EsSalud.
Pobla dw.dim_departamento con los departamentos PRESENTES EN LOS HECHOS y
rellena dw.dim_geografia.id_departamento (jerarquia distrito -> departamento).

Departamento = 2 primeros digitos del UBIGEO (codigo INEI). Solo entran los
departamentos con atenciones reales (mismo principio dimensional que
SES_DESCAS: la dimension contiene lo que el hecho referencia).

Requisitos:
  - sql/05_create_dim_departamento.sql ya aplicado.
  - Paso 04 ya corrido (dw.fact_atenciones poblada).
  - Tablas de resultados vacias (este paso corre antes del modelado).

NO recarga hechos ni otras dimensiones: es un cambio aditivo en sitio.

Ejecutar:  python etl/06_load_departamento.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import create_engine, text
import config


def engine():
    return create_engine(config.CONNECTION_STRING, fast_executemany=True)


def main():
    eng = engine()

    # Departamentos presentes en los hechos: codigo (2 dig de ubigeo) + nombre.
    q = text("""
        SELECT LEFT(g.ubigeo, 2) AS codigo,
               g.departamento     AS nombre,
               COUNT(*)           AS n
        FROM dw.fact_atenciones f
        JOIN dw.dim_geografia g ON f.id_geografia = g.id_geografia
        GROUP BY LEFT(g.ubigeo, 2), g.departamento
    """)
    df = pd.read_sql(q, eng)
    if df.empty:
        sys.exit("dw.fact_atenciones vacia; corre el paso 04 primero.")

    # Nombre dominante por codigo (por si un codigo trae grafias distintas).
    dept = (df.sort_values("n", ascending=False)
              .drop_duplicates(subset="codigo")[["codigo", "nombre"]]
              .sort_values("codigo").reset_index(drop=True))
    dept.columns = ["codigo_departamento", "nombre"]

    # Reset en sitio: limpiar refs de geografia y recargar dim_departamento.
    with eng.begin() as cx:
        cx.execute(text("UPDATE dw.dim_geografia SET id_departamento = NULL;"))
        cx.execute(text("DELETE FROM dw.dim_departamento;"))

    dept.to_sql("dim_departamento", eng, schema="dw", if_exists="append",
                index=False, chunksize=1000)

    # Backfill: cada distrito hereda el id_departamento por su codigo.
    with eng.begin() as cx:
        cx.execute(text("""
            UPDATE g
            SET g.id_departamento = d.id_departamento
            FROM dw.dim_geografia g
            JOIN dw.dim_departamento d
              ON LEFT(g.ubigeo, 2) = d.codigo_departamento;
        """))

    look = pd.read_sql(text(
        "SELECT id_departamento, codigo_departamento, nombre "
        "FROM dw.dim_departamento ORDER BY codigo_departamento"), eng)
    sin_dep = pd.read_sql(text(
        "SELECT COUNT(*) AS n FROM dw.dim_geografia WHERE id_departamento IS NULL"),
        eng)["n"].iat[0]

    print("=== dim_departamento (presentes en hechos) ===")
    print(f"departamentos: {len(look)}")
    print(look.to_string(index=False))
    print(f"\ndim_geografia sin departamento (distritos sin atenciones): {sin_dep}")


if __name__ == "__main__":
    main()