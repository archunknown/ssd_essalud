/* ============================================================================
   SSD EsSalud - Esquema Estrella - Data Warehouse
   Archivo: 05_create_dim_departamento.sql
   Proposito: Resolver el defecto de grano de los resultados de modelos.

   Los modelos (Prophet, Random Forest) producen a nivel DEPARTAMENTO, pero
   dim_geografia esta a grano DISTRITO (UNIQUE ubigeo). No existia clave
   subrogada de departamento a la cual referenciar los resultados.

   Solucion (opcion separar granos):
     - Nueva dim_departamento (grano departamento).
     - dim_geografia gana id_departamento (FK) -> jerarquia distrito->departamento.
     - resultado_proyeccion y resultado_clasificacion se re-crean apuntando su
       FK a dim_departamento (estaban vacias; cambio sin costo).

   El codigo de departamento son los 2 primeros digitos del UBIGEO (INEI).
   dim_departamento se puebla (en etl/06) solo con los departamentos presentes
   en los hechos, no con el catalogo completo de 25.

   Idempotente: se puede re-ejecutar. Ejecutar conectado a SSD_EsSalud.
   ============================================================================ */

USE SSD_EsSalud;
GO

/* 1) Soltar primero las tablas de resultados (pueden tener FK a departamento
      si este script ya corrio antes), para poder recrear dim_departamento. */
IF OBJECT_ID('dw.resultado_clasificacion', 'U') IS NOT NULL
    DROP TABLE dw.resultado_clasificacion;
GO
IF OBJECT_ID('dw.resultado_proyeccion', 'U') IS NOT NULL
    DROP TABLE dw.resultado_proyeccion;
GO

/* 2) Soltar la FK de dim_geografia hacia departamento si existe, y la tabla. */
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'fk_dim_geografia_departamento')
    ALTER TABLE dw.dim_geografia DROP CONSTRAINT fk_dim_geografia_departamento;
GO
IF OBJECT_ID('dw.dim_departamento', 'U') IS NOT NULL
    DROP TABLE dw.dim_departamento;
GO

/* 3) dim_departamento. Grano: departamento. Clave natural: codigo INEI (2 dig). */
CREATE TABLE dw.dim_departamento (
    id_departamento     INT IDENTITY(1,1) NOT NULL,
    codigo_departamento CHAR(2)       NOT NULL,   -- 2 primeros digitos del ubigeo
    nombre              VARCHAR(50)   NOT NULL,
    CONSTRAINT pk_dim_departamento PRIMARY KEY (id_departamento),
    CONSTRAINT uq_dim_departamento_codigo UNIQUE (codigo_departamento)
);
GO

/* 4) dim_geografia: jerarquia distrito -> departamento (NULLable: algunos
      distritos de RENIPRESS pueden estar en departamentos sin atenciones). */
IF COL_LENGTH('dw.dim_geografia', 'id_departamento') IS NULL
    ALTER TABLE dw.dim_geografia ADD id_departamento INT NULL;
GO
ALTER TABLE dw.dim_geografia ADD CONSTRAINT fk_dim_geografia_departamento
    FOREIGN KEY (id_departamento) REFERENCES dw.dim_departamento (id_departamento);
GO

/* 5) resultado_proyeccion (Modelo 1 - Prophet). FK -> dim_departamento. */
CREATE TABLE dw.resultado_proyeccion (
    id_proyeccion          INT IDENTITY(1,1) NOT NULL,
    id_departamento        INT           NOT NULL,
    mes_proyectado         DATE          NOT NULL,
    atenciones_proyectadas INT           NOT NULL,
    limite_inferior_ic95   INT           NULL,
    limite_superior_ic95   INT           NULL,
    mape_validacion        DECIMAL(6,2)  NULL,
    fecha_ejecucion        DATETIME      NOT NULL CONSTRAINT df_proy_fecha DEFAULT (GETDATE()),
    CONSTRAINT pk_resultado_proyeccion PRIMARY KEY (id_proyeccion),
    CONSTRAINT fk_resultado_proyeccion_departamento
        FOREIGN KEY (id_departamento) REFERENCES dw.dim_departamento (id_departamento)
);
GO

/* 6) resultado_clasificacion (Modelo 2 - Random Forest). FK -> dim_departamento. */
CREATE TABLE dw.resultado_clasificacion (
    id_clasificacion    INT IDENTITY(1,1) NOT NULL,
    id_departamento     INT           NOT NULL,
    mes_clasificado     DATE          NOT NULL,
    ratio_saturacion    DECIMAL(8,2)  NOT NULL,
    nivel_saturacion    VARCHAR(10)   NOT NULL,
    f1_score_validacion DECIMAL(5,2)  NULL,
    fecha_ejecucion     DATETIME      NOT NULL CONSTRAINT df_clas_fecha DEFAULT (GETDATE()),
    CONSTRAINT pk_resultado_clasificacion PRIMARY KEY (id_clasificacion),
    CONSTRAINT fk_resultado_clasificacion_departamento
        FOREIGN KEY (id_departamento) REFERENCES dw.dim_departamento (id_departamento),
    CONSTRAINT ck_nivel_saturacion
        CHECK (nivel_saturacion IN ('Bajo', 'Normal', 'Alto', 'Critico'))
);
GO

PRINT 'OK: dim_departamento creada; dim_geografia.id_departamento agregado; resultados re-creados con FK a departamento.';
GO