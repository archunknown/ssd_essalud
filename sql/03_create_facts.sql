/* ============================================================================
   SSD EsSalud - Esquema Estrella - Data Warehouse
   Archivo: 03_create_facts.sql
   Proposito: Crear la TABLA DE HECHOS central del modelo dimensional.

   Ejecutar DESPUES de 01_create_schema.sql (requiere las dimensiones).
   ============================================================================ */

USE SSD_EsSalud;
GO

/* ---------------------------------------------------------------------------
   fact_atenciones
   Grano: una fila por (periodo x establecimiento x especialidad x geografia).
   Origen: dataset Atenciones Consulta Externa EsSalud, filtrado a
           DES_ACT = 'Consultas' y agregado con SUM(CANTIDAD).
   Metrica aditiva: cantidad_atenciones.
   ratio_saturacion se calcula en la capa de transformacion (PRD RN-01):
       ratio = (atenciones del periodo / linea base operativa historica) * 100
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dw.fact_atenciones', 'U') IS NOT NULL
    DROP TABLE dw.fact_atenciones;
GO

CREATE TABLE dw.fact_atenciones (
    id_atencion         BIGINT IDENTITY(1,1) NOT NULL,
    id_tiempo           INT           NOT NULL,
    id_establecimiento  INT           NOT NULL,
    id_especialidad     INT           NOT NULL,
    id_geografia        INT           NOT NULL,
    cantidad_atenciones INT           NOT NULL,   -- SUM(CANTIDAD) donde DES_ACT='Consultas'
    ratio_saturacion    DECIMAL(8,2)  NULL,       -- variable derivada (capa transformacion)
    CONSTRAINT pk_fact_atenciones PRIMARY KEY (id_atencion),
    CONSTRAINT fk_fact_tiempo
        FOREIGN KEY (id_tiempo)          REFERENCES dw.dim_tiempo (id_tiempo),
    CONSTRAINT fk_fact_establecimiento
        FOREIGN KEY (id_establecimiento) REFERENCES dw.dim_establecimiento (id_establecimiento),
    CONSTRAINT fk_fact_especialidad
        FOREIGN KEY (id_especialidad)    REFERENCES dw.dim_especialidad (id_especialidad),
    CONSTRAINT fk_fact_geografia
        FOREIGN KEY (id_geografia)       REFERENCES dw.dim_geografia (id_geografia)
);
GO

/* Indices no agrupados sobre las claves foraneas mas usadas en las consultas
   del dashboard (filtros por tiempo y geografia). Mejora el tiempo de respuesta
   en Power BI (criterio RNF-01: < 5 s). */
CREATE INDEX ix_fact_atenciones_tiempo
    ON dw.fact_atenciones (id_tiempo);
GO
CREATE INDEX ix_fact_atenciones_geografia
    ON dw.fact_atenciones (id_geografia);
GO

PRINT 'Tabla de hechos creada: fact_atenciones (con indices sobre tiempo y geografia).';
GO