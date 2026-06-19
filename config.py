# config.py
import os

# SQL Server
DB_SERVER = r"localhost\SQLEXPRESS"
DB_NAME   = "SSD_EsSalud"
DB_DRIVER = "ODBC Driver 18 for SQL Server"

CONNECTION_STRING = (
    f"mssql+pyodbc://{DB_SERVER}/{DB_NAME}"
    f"?driver={DB_DRIVER.replace(' ', '+')}"
    "&trusted_connection=yes"
    "&Encrypt=no"
)

# Cadena de conexion a master, usada unicamente para crear la base de datos
# (no se puede crear una DB estando conectado a ella misma)
MASTER_CONNECTION_STRING = (
    f"mssql+pyodbc://{DB_SERVER}/master"
    f"?driver={DB_DRIVER.replace(' ', '+')}"
    "&trusted_connection=yes"
    "&Encrypt=no"
)

# Rutas
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
RAW_RENAES      = os.path.join(BASE_DIR, "data", "raw", "renaes")
RAW_REUNIS      = os.path.join(BASE_DIR, "data", "raw", "reunis")
RAW_DATOS_AB    = os.path.join(BASE_DIR, "data", "raw", "datos_abiertos")
PROCESSED_DIR   = os.path.join(BASE_DIR, "data", "processed")
OUTPUTS_DIR     = os.path.join(BASE_DIR, "data", "outputs")

# Reglas de negocio (PRD RN-02)
UMBRAL_BAJO     = 70.0
UMBRAL_NORMAL   = 90.0
UMBRAL_ALTO     = 110.0

# Filtro institucional (PRD RN-09)
INSTITUCION_ESSALUD = "ESSALUD"

# Horizonte de prediccion (PRD RN-04)
HORIZONTE_MESES = 6