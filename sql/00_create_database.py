"""
Crea la base de datos SSD_EsSalud si no existe.
Se conecta a 'master' porque no se puede crear una base de datos
estando conectado a ella misma.

Ejecutar una sola vez (o cada vez que se reconstruya el entorno desde cero).
"""
import sys
import os

# Permite importar config.py desde la raiz del proyecto,
# sin importar desde donde se invoque este script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyodbc
from config import DB_SERVER, DB_NAME, DB_DRIVER

conn_str = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE=master;"
    f"Trusted_Connection=yes;"
    f"Encrypt=no;"
)

conn = pyodbc.connect(conn_str, autocommit=True)
cursor = conn.cursor()

cursor.execute(f"""
IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = '{DB_NAME}')
BEGIN
    CREATE DATABASE {DB_NAME};
END
""")

cursor.execute(f"SELECT name FROM sys.databases WHERE name = '{DB_NAME}'")
row = cursor.fetchone()

if row:
    print(f"OK - Base de datos '{DB_NAME}' existe y esta lista.")
else:
    print(f"ERROR - No se pudo confirmar la creacion de '{DB_NAME}'.")

cursor.close()
conn.close()