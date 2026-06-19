/* ============================================================================
   SSD EsSalud - Esquema Estrella - Data Warehouse
   Archivo: 04_create_results_tables.sql
   Proposito: Crear las tablas de RESULTADOS de los modelos predictivos.
              Estructura segun PRD v1.3, seccion 12.

   Ejecutar DESPUES de 01_create_schema.sql (FK a dim_geografia).
   ============================================================================ */

USE SSD_EsSalud;
GO

/* ---------------------------------------------------------------------------
   resultado_proyeccion  (Modelo 1 - Prophet)
   Proyeccion de atenciones mensuales por departamento.
   PRD v1.3, seccion 12.1.
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dw.resultado_proyeccion', 'U') IS NOT NULL
    DROP TABLE dw.resultado_proyeccion;
GO

CREATE TABLE dw.resultado_proyeccion (
    id_proyeccion          INT IDENTITY(1,1) NOT NULL,
    id_geografia           INT           NOT NULL,   -- referencia a nivel departamento
    mes_proyectado         DATE          NOT NULL,
    atenciones_proyectadas INT           NOT NULL,
    limite_inferior_ic95   INT           NULL,
    limite_superior_ic95   INT           NULL,
    mape_validacion        DECIMAL(6,2)  NULL,
    fecha_ejecucion        DATETIME      NOT NULL CONSTRAINT df_proy_fecha DEFAULT (GETDATE()),
    CONSTRAINT pk_resultado_proyeccion PRIMARY KEY (id_proyeccion),
    CONSTRAINT fk_resultado_proyeccion_geografia
        FOREIGN KEY (id_geografia) REFERENCES dw.dim_geografia (id_geografia)
);
GO

/* ---------------------------------------------------------------------------
   resultado_clasificacion  (Modelo 2 - Random Forest)
   Clasificacion de saturacion departamental en 4 clases.
   PRD v1.3, seccion 12.2 y RN-02.
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dw.resultado_clasificacion', 'U') IS NOT NULL
    DROP TABLE dw.resultado_clasificacion;
GO

CREATE TABLE dw.resultado_clasificacion (
    id_clasificacion    INT IDENTITY(1,1) NOT NULL,
    id_geografia        INT           NOT NULL,   -- referencia a nivel departamento
    mes_clasificado     DATE          NOT NULL,
    ratio_saturacion    DECIMAL(8,2)  NOT NULL,
    nivel_saturacion    VARCHAR(10)   NOT NULL,   -- Bajo | Normal | Alto | Critico
    f1_score_validacion DECIMAL(5,2)  NULL,
    fecha_ejecucion     DATETIME      NOT NULL CONSTRAINT df_clas_fecha DEFAULT (GETDATE()),
    CONSTRAINT pk_resultado_clasificacion PRIMARY KEY (id_clasificacion),
    CONSTRAINT fk_resultado_clasificacion_geografia
        FOREIGN KEY (id_geografia) REFERENCES dw.dim_geografia (id_geografia),
    CONSTRAINT ck_nivel_saturacion
        CHECK (nivel_saturacion IN ('Bajo', 'Normal', 'Alto', 'Critico'))
);
GO

PRINT 'Tablas de resultados creadas: resultado_proyeccion, resultado_clasificacion.';
GO