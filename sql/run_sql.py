import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyodbc
from config import DB_SERVER, DB_NAME, DB_DRIVER

if len(sys.argv) < 2:
    sys.exit("uso: python sql/run_sql.py <archivo.sql>")
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    sql = f.read()

# separa por GO en su propia linea
batches = [b.strip() for b in re.split(r"(?im)^\s*GO\s*$", sql) if b.strip()]

conn = pyodbc.connect(
    f"DRIVER={{{DB_DRIVER}}};SERVER={DB_SERVER};DATABASE={DB_NAME};"
    "Trusted_Connection=yes;Encrypt=no;", autocommit=True)
cur = conn.cursor()
for i, b in enumerate(batches, 1):
    try:
        cur.execute(b)
        while cur.nextset():
            pass
        print(f"[{i}/{len(batches)}] OK")
    except Exception as e:
        print(f"[{i}/{len(batches)}] FALLO:\n{b[:200]}\n--> {e}")
        raise
print("Script aplicado completo.")
cur.close(); conn.close()