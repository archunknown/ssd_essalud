"""
etl/01_extract_transform_renipress.py

Paso 1 del ETL — SSD EsSalud.
Extrae, limpia y perfila RENIPRESS (29-05-2026). Filtra EsSalud + ACTIVO.
Emite staging para el enriquecimiento opcional de dim_establecimiento
(cod_ipress, categoria por match de nombre) y la contribucion de RENIPRESS
a dim_geografia.

NO escribe al Data Warehouse. Solo staging en data/processed.

Anclado al DDL real (sql/01_create_schema.sql):
  dim_geografia.ubigeo es VARCHAR(6) UNIQUE -> se normaliza a 6 digitos.
  El match de enriquecimiento usa nombre normalizado (uppercase+strip+sin
  tildes+espacios colapsados), aplicado aqui sobre NOMBRE y en el paso 02
  sobre SES_DESCAS.

Ejecutar desde la raiz:  python etl/01_extract_transform_renipress.py
"""
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import config

RENIPRESS_CSV = os.path.join(config.RAW_RENIPRESS, "RENIPRESS_29-05-2026.csv")
STG_RENIPRESS = os.path.join(config.PROCESSED_DIR, "renipress_essalud_activo.csv")
STG_GEO = os.path.join(config.PROCESSED_DIR, "geografia_renipress.csv")

EXPECTED_TOTAL = 35581
EXPECTED_ESSALUD = 491
GEO_COLS = ["DEPARTAMENTO", "PROVINCIA", "DISTRITO", "UBIGEO"]


def normalize_name(s: pd.Series) -> pd.Series:
    out = s.fillna("").astype(str).str.upper().str.strip()
    out = out.map(lambda x: "".join(
        c for c in unicodedata.normalize("NFKD", x)
        if not unicodedata.combining(c)))
    return out.str.replace(r"\s+", " ", regex=True)


def normalize_ubigeo(s: pd.Series) -> pd.Series:
    u = s.fillna("").astype(str).str.strip().str.replace(r"\D", "", regex=True)
    return u.where(u == "", u.str.zfill(6))


def extract():
    df = pd.read_csv(RENIPRESS_CSV, sep=";", encoding="utf-8-sig",
                     dtype=str, keep_default_na=False)
    df.columns = df.columns.str.strip()
    return df


def transform(df):
    for c in df.columns:
        df[c] = df[c].str.strip()

    essalud = df[df["INSTITUCION"] == config.INSTITUCION_ESSALUD].copy()
    activo = essalud[essalud["ESTADO"] == "ACTIVO"].copy()

    activo["UBIGEO"] = normalize_ubigeo(activo["UBIGEO"])
    activo["UBIGEO_VALIDO"] = activo["UBIGEO"].str.fullmatch(r"\d{6}")
    activo["CATEGORIA_VALIDA"] = activo["CATEGORIA"] != "0"
    activo["NOMBRE_NORM"] = normalize_name(activo["NOMBRE"])
    return essalud, activo


def build_geografia(activo):
    geo = activo.loc[activo["UBIGEO_VALIDO"], GEO_COLS].copy()
    geo = geo.drop_duplicates().sort_values("UBIGEO").reset_index(drop=True)
    geo.columns = ["departamento", "provincia", "distrito", "ubigeo"]
    return geo[["ubigeo", "departamento", "provincia", "distrito"]]


def profile(df, essalud, activo):
    print("=== PERFILADO RENIPRESS ===")
    print(f"{'Filas totales':<26}: {len(df):>6}  (esperado {EXPECTED_TOTAL})")
    print(f"{'INSTITUCION == ESSALUD':<26}: {len(essalud):>6}  (esperado {EXPECTED_ESSALUD})")
    print(f"{'  + ESTADO == ACTIVO':<26}: {len(activo):>6}")
    print(f"{'  CATEGORIA == 0':<26}: {(activo['CATEGORIA'] == '0').sum():>6}")
    print(f"{'  UBIGEO no 6-digitos':<26}: {(~activo['UBIGEO_VALIDO']).sum():>6}")
    print(f"{'  COD_IPRESS duplicados':<26}: {activo['COD_IPRESS'].duplicated().sum():>6}")
    print(f"{'  NOMBRE_NORM duplicados':<26}: {activo['NOMBRE_NORM'].duplicated().sum():>6}")
    if len(essalud) != EXPECTED_ESSALUD:
        print(f"\n[AVISO] EsSalud != {EXPECTED_ESSALUD}: la fuente cambio. Revisar antes de continuar.")
    print("\nCATEGORIA:")
    print(activo["CATEGORIA"].value_counts(dropna=False).to_string())


def stage(activo, geo):
    os.makedirs(config.PROCESSED_DIR, exist_ok=True)
    activo.to_csv(STG_RENIPRESS, sep=";", encoding="utf-8-sig", index=False)
    geo.to_csv(STG_GEO, sep=";", encoding="utf-8-sig", index=False)
    print(f"\nStaging RENIPRESS  : {STG_RENIPRESS}  ({len(activo)} filas)")
    print(f"Geografia RENIPRESS: {STG_GEO}  ({len(geo)} ubigeos validos)")


if __name__ == "__main__":
    df = extract()
    essalud, activo = transform(df)
    profile(df, essalud, activo)
    geo = build_geografia(activo)
    stage(activo, geo)