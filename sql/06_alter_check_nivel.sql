/* ============================================================================
   SSD EsSalud - Ajuste de clases de saturacion
   Archivo: 06_alter_check_nivel.sql

   El RF colapso de 4 a 3 clases por rareza estructural de la saturacion
   critica (12/1200 casos). Niveles validos ahora: Bajo, Normal, Saturado
   (Saturado fusiona los antiguos Alto y Critico). El esquema binario opcional
   usa el subconjunto {Normal, Saturado}, asi que este mismo CHECK lo admite.

   resultado_clasificacion esta vacia (se repuebla al correr el RF), cambio sin
   costo. Idempotente. Ejecutar:  python sql\run_sql.py sql\06_alter_check_nivel.sql
   ============================================================================ */

USE SSD_EsSalud;
GO

IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_nivel_saturacion')
    ALTER TABLE dw.resultado_clasificacion DROP CONSTRAINT ck_nivel_saturacion;
GO

ALTER TABLE dw.resultado_clasificacion ADD CONSTRAINT ck_nivel_saturacion
    CHECK (nivel_saturacion IN ('Bajo', 'Normal', 'Saturado'));
GO

PRINT 'OK: ck_nivel_saturacion actualizado a (Bajo, Normal, Saturado).';
GO