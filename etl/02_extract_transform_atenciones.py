"""
etl/02_extract_transform_atenciones.py

Paso 2 del ETL — SSD EsSalud.
Lee atenciones de consulta externa EsSalud (382 MB) por chunks, filtra
DES_ACT == 'Consultas', limpia padding, y construye el staging compatible
con el DDL real:

  - fact_atenciones_consultas.csv  -> grano DDL: periodo x establecimiento x
    especialidad x geografia (UBIGEO). SIN red (la red es atributo de la
    dimension, no del hecho). Una fila por combinacion, SUM(CANTIDAD).
  - dim_tiempo.csv         -> periodo, anio, mes, nombre_mes, trimestre,
    semestre, fecha_inicio  (las dos ultimas son NOT NULL en el DDL).
  - dim_especialidad.csv   -> especialidad, area.
  - establecimientos_atenciones.csv -> una fila por SES_DESCAS (UNIQUE
    nombre_centro en el DDL): ubigeo y red dominantes por establecimiento.
  - geografia_union.csv    -> union atenciones+RENIPRESS deduplicada por
    UBIGEO (UNIQUE ubigeo en el DDL).

NO calcula ratio_saturacion (paso 02b: pendiente estimador de linea base,
exclusion COVID en el denominador, y grano del ratio en el hecho).
NO escribe al DW. Conserva todos los anios (incl. 2020-2021).

Requiere haber corrido antes el paso 01 (geografia_renipress.csv).
Ejecutar desde la raiz:  python etl/02_extract_transform_atenciones.py
"""
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import config

ATENCIONES_CSV = os.path.join(config.BASE_DIR, "data", "raw",
                              "atenciones_essalud", "DATASET_CEXTERNA_2015_2022_0.csv")
STG_GEO_RENIPRESS = os.path.join(config.PROCESSED_DIR, "geografia_renipress.csv")

OUT_FACT = os.path.join(config.PROCESSED_DIR, "fact_atenciones_consultas.csv")
OUT_TIEMPO = os.path.join(config.PROCESSED_DIR, "dim_tiempo.csv")
OUT_ESPEC = os.path.join(config.PROCESSED_DIR, "dim_especialidad.csv")
OUT_ESTAB = os.path.join(config.PROCESSED_DIR, "establecimientos_atenciones.csv")
OUT_GEO = os.path.join(config.PROCESSED_DIR, "geografia_union.csv")

CHUNKSIZE = 200_000
MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
         "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

FACT_KEYS = ["PERIODO", "SES_DESCAS", "DES_SER", "UBIGEO"]
GEO_KEYS = ["UBIGEO", "DEPARTAMENTO", "PROVINCIA", "DISTRITO"]
ESTAB_KEYS = ["SES_DESCAS", "SES_DESRED", "UBIGEO"]


def normalize_name(s: pd.Series) -> pd.Series:
    out = s.fillna("").astype(str).str.upper().str.strip()
    out = out.map(lambda x: "".join(
        c for c in unicodedata.normalize("NFKD", x)
        if not unicodedata.combining(c)))
    return out.str.replace(r"\s+", " ", regex=True)


def normalize_ubigeo(s: pd.Series) -> pd.Series:
    u = s.fillna("").astype(str).str.strip().str.replace(r"\D", "", regex=True)
    return u.where(u == "", u.str.zfill(6))


def process_chunks():
    """Un solo pase. Acumula tres agregaciones parciales para no tener
    en memoria los 382 MB: hecho, observaciones de geografia, observaciones
    de establecimiento (con conteos para resolver valores dominantes)."""
    fact_parts, geo_parts, estab_parts = [], [], []
    leidas = consultas = cant_no_num = des_ser_vacio = 0

    reader = pd.read_csv(ATENCIONES_CSV, sep=";", encoding="utf-8-sig",
                         dtype=str, keep_default_na=False, chunksize=CHUNKSIZE)
    for chunk in reader:
        chunk.columns = chunk.columns.str.strip()
        leidas += len(chunk)
        for c in chunk.columns:
            chunk[c] = chunk[c].str.strip()

        chunk = chunk[chunk["DES_ACT"] == "Consultas"]
        consultas += len(chunk)
        if chunk.empty:
            continue

        des_ser_vacio += (chunk["DES_SER"] == "").sum()
        chunk["UBIGEO"] = normalize_ubigeo(chunk["UBIGEO"])

        cant = pd.to_numeric(chunk["CANTIDAD"], errors="coerce")
        cant_no_num += int(cant.isna().sum())
        chunk = chunk.assign(CANTIDAD=cant).dropna(subset=["CANTIDAD"])
        chunk["CANTIDAD"] = chunk["CANTIDAD"].astype("int64")

        fact_parts.append(chunk.groupby(FACT_KEYS, as_index=False)["CANTIDAD"].sum())
        g = chunk.groupby(GEO_KEYS, as_index=False).size().rename(columns={"size": "n"})
        geo_parts.append(g)
        e = chunk.groupby(ESTAB_KEYS, as_index=False).size().rename(columns={"size": "n"})
        estab_parts.append(e)

    fact = (pd.concat(fact_parts, ignore_index=True)
            .groupby(FACT_KEYS, as_index=False)["CANTIDAD"].sum())
    geo_obs = (pd.concat(geo_parts, ignore_index=True)
               .groupby(GEO_KEYS, as_index=False)["n"].sum())
    estab_obs = (pd.concat(estab_parts, ignore_index=True)
                 .groupby(ESTAB_KEYS, as_index=False)["n"].sum())

    contadores = {
        "filas_leidas": leidas,
        "filas_consultas": consultas,
        "cantidad_no_numerica": cant_no_num,
        "des_ser_vacio_en_consultas": int(des_ser_vacio),
    }
    return fact, geo_obs, estab_obs, contadores


def build_dim_tiempo(fact):
    t = pd.DataFrame({"periodo": sorted(fact["PERIODO"].unique())})
    t = t[t["periodo"].str.fullmatch(r"\d{6}")].reset_index(drop=True)
    t["anio"] = t["periodo"].str[:4].astype(int)
    t["mes"] = t["periodo"].str[4:6].astype(int)
    t["nombre_mes"] = t["mes"].map(lambda m: MESES[m])
    t["trimestre"] = ((t["mes"] - 1) // 3) + 1
    t["semestre"] = (t["mes"] > 6).astype(int) + 1
    t["fecha_inicio"] = pd.to_datetime(t["periodo"] + "01", format="%Y%m%d").dt.date
    t["periodo"] = t["periodo"].astype(int)
    return t[["periodo", "anio", "mes", "nombre_mes", "trimestre", "semestre", "fecha_inicio"]]


def build_dim_especialidad(fact):
    e = pd.DataFrame({"especialidad": sorted(x for x in fact["DES_SER"].unique() if x)})
    e["area"] = pd.NA  # taxonomia por area: pendiente de catalogo; NULL explicito
    return e


def _dominant(obs, key, attrs):
    """Para cada 'key' devuelve la combinacion de 'attrs' con mayor n."""
    d = obs.sort_values("n", ascending=False).drop_duplicates(subset=key)
    return d[[key] + attrs].reset_index(drop=True)


def build_geografia_union(geo_obs):
    at = _dominant(geo_obs, "UBIGEO", ["DEPARTAMENTO", "PROVINCIA", "DISTRITO"])
    at.columns = ["ubigeo", "departamento", "provincia", "distrito"]
    at = at[at["ubigeo"].str.fullmatch(r"\d{6}")]

    if os.path.exists(STG_GEO_RENIPRESS):
        rp = pd.read_csv(STG_GEO_RENIPRESS, sep=";", encoding="utf-8-sig",
                         dtype=str, keep_default_na=False)
        rp = rp[rp["ubigeo"].str.fullmatch(r"\d{6}")]
    else:
        print(f"[AVISO] Falta {STG_GEO_RENIPRESS}. Corre el paso 01. Geografia solo de atenciones.")
        rp = at.iloc[0:0]

    # Union deduplicada por UBIGEO (UNIQUE en el DDL). Prioridad: atenciones
    # (fuente del grano del hecho); RENIPRESS solo aporta ubigeos no presentes.
    union = pd.concat([at, rp], ignore_index=True)
    union = union.drop_duplicates(subset="ubigeo", keep="first")
    return union.sort_values("ubigeo").reset_index(drop=True)


def build_establecimientos(estab_obs):
    est = _dominant(estab_obs, "SES_DESCAS", ["SES_DESRED", "UBIGEO"])
    est.columns = ["nombre_centro", "red_essalud", "ubigeo"]
    est["nombre_norm"] = normalize_name(est["nombre_centro"])
    est["nombre_excede_150"] = est["nombre_centro"].str.len() > 150
    return est.sort_values("nombre_centro").reset_index(drop=True)


def profile(fact, contadores, tiempo, espec, estab, geo):
    print("=== PERFILADO ATENCIONES (Consultas) ===")
    for k, v in contadores.items():
        print(f"{k:<28}: {v:>10}")
    print(f"{'filas hecho agregado':<28}: {len(fact):>10}")
    print(f"{'establecimientos (centros)':<28}: {len(estab):>10}")
    print(f"{'  nombre_centro > 150 char':<28}: {int(estab['nombre_excede_150'].sum()):>10}")
    print(f"{'especialidades':<28}: {len(espec):>10}")
    print(f"{'periodos (meses)':<28}: {len(tiempo):>10}")
    print(f"{'rango periodo':<28}: {tiempo['periodo'].min()} - {tiempo['periodo'].max()}")
    print(f"{'ubigeos (geografia union)':<28}: {len(geo):>10}")
    print(f"{'CANTIDAD total':<28}: {fact['CANTIDAD'].sum():>10}")
    print("\nEspecialidades:")
    print(espec["especialidad"].to_string(index=False))


def stage(fact, tiempo, espec, estab, geo):
    os.makedirs(config.PROCESSED_DIR, exist_ok=True)
    out = fact.rename(columns={
        "PERIODO": "periodo", "SES_DESCAS": "nombre_centro",
        "DES_SER": "especialidad", "UBIGEO": "ubigeo",
        "CANTIDAD": "cantidad_atenciones"})
    out.to_csv(OUT_FACT, sep=";", encoding="utf-8-sig", index=False)
    tiempo.to_csv(OUT_TIEMPO, sep=";", encoding="utf-8-sig", index=False)
    espec.to_csv(OUT_ESPEC, sep=";", encoding="utf-8-sig", index=False)
    estab.to_csv(OUT_ESTAB, sep=";", encoding="utf-8-sig", index=False)
    geo.to_csv(OUT_GEO, sep=";", encoding="utf-8-sig", index=False)
    print("\nStaging escrito en", config.PROCESSED_DIR + ":")
    for p in (OUT_FACT, OUT_TIEMPO, OUT_ESPEC, OUT_ESTAB, OUT_GEO):
        print(f"  {os.path.basename(p)}")


if __name__ == "__main__":
    fact, geo_obs, estab_obs, contadores = process_chunks()
    tiempo = build_dim_tiempo(fact)
    espec = build_dim_especialidad(fact)
    estab = build_establecimientos(estab_obs)
    geo = build_geografia_union(geo_obs)
    profile(fact, contadores, tiempo, espec, estab, geo)
    stage(fact, tiempo, espec, estab, geo)