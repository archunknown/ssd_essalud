/* ============================================================================
   SSD EsSalud - Esquema Estrella - Data Warehouse
   Archivo: 01_create_schema.sql
   Proposito: Crear el esquema y las DIMENSIONES del modelo dimensional.

   Modelo anclado a columnas reales verificadas de:
     - Atenciones Consulta Externa EsSalud (datosabiertos.gob.pe)
       Columnas: PERIODO, SES_DESRED, SES_DESCAS, DES_GRU, DES_ACT,
                 DES_SER, CANTIDAD, DEPARTAMENTO, PROVINCIA, DISTRITO,
                 UBIGEO, FECHA_CORTE
     - RENIPRESS (SUSALUD) - enriquecimiento opcional de categoria.

   Reglas de negocio aplicadas (PRD v1.3):
     - Metrica de atencion: filas con DES_ACT = 'Consultas'.
     - Saturacion = atenciones / linea base operativa historica.
     - Solo establecimientos EsSalud (el dataset ya es 100% EsSalud en origen).

   Ejecutar conectado a la base de datos SSD_EsSalud.
   ============================================================================ */

USE SSD_EsSalud;
GO

/* ---------------------------------------------------------------------------
   Esquema logico para agrupar los objetos del DW.
   --------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dw')
BEGIN
    EXEC('CREATE SCHEMA dw');
END
GO

/* ---------------------------------------------------------------------------
   dim_tiempo
   Granularidad: mensual (el dataset usa PERIODO en formato aaaamm).
   Se usa una clave subrogada entera independiente del PERIODO de origen.
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dw.dim_tiempo', 'U') IS NOT NULL
    DROP TABLE dw.dim_tiempo;
GO

CREATE TABLE dw.dim_tiempo (
    id_tiempo       INT IDENTITY(1,1) NOT NULL,
    periodo         INT           NOT NULL,   -- formato aaaamm de origen (p.ej. 201501)
    anio            SMALLINT      NOT NULL,
    mes             TINYINT       NOT NULL,
    nombre_mes      VARCHAR(12)   NOT NULL,
    trimestre       TINYINT       NOT NULL,
    semestre        TINYINT       NOT NULL,
    fecha_inicio    DATE          NOT NULL,   -- primer dia del mes, util para Prophet
    CONSTRAINT pk_dim_tiempo PRIMARY KEY (id_tiempo),
    CONSTRAINT uq_dim_tiempo_periodo UNIQUE (periodo)
);
GO

/* ---------------------------------------------------------------------------
   dim_geografia
   Granularidad: distrito (nivel mas fino del dataset).
   UBIGEO es la clave natural de negocio (catalogo INEI, 6 digitos).
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dw.dim_geografia', 'U') IS NOT NULL
    DROP TABLE dw.dim_geografia;
GO

CREATE TABLE dw.dim_geografia (
    id_geografia    INT IDENTITY(1,1) NOT NULL,
    ubigeo          VARCHAR(6)    NOT NULL,
    departamento    VARCHAR(50)   NOT NULL,
    provincia       VARCHAR(100)  NOT NULL,
    distrito        VARCHAR(100)  NOT NULL,
    CONSTRAINT pk_dim_geografia PRIMARY KEY (id_geografia),
    CONSTRAINT uq_dim_geografia_ubigeo UNIQUE (ubigeo)
);
GO

/* ---------------------------------------------------------------------------
   dim_establecimiento
   Granularidad: centro asistencial (SES_DESCAS).
   El dataset de atenciones identifica el establecimiento por NOMBRE, no por
   codigo IPRESS. La categoria proveniente de RENIPRESS se incorpora como
   enriquecimiento opcional (puede quedar NULL si el match por nombre falla).
   SCD Tipo 1 (PRD): se sobrescribe, no se versiona historial.
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dw.dim_establecimiento', 'U') IS NOT NULL
    DROP TABLE dw.dim_establecimiento;
GO

CREATE TABLE dw.dim_establecimiento (
    id_establecimiento  INT IDENTITY(1,1) NOT NULL,
    nombre_centro       VARCHAR(150)  NOT NULL,   -- SES_DESCAS (limpiado de padding)
    red_essalud         VARCHAR(100)  NULL,       -- SES_DESRED
    cod_ipress          VARCHAR(8)    NULL,       -- enriquecimiento RENIPRESS (match por nombre)
    categoria           VARCHAR(10)   NULL,       -- enriquecimiento RENIPRESS (I-1..III-E)
    id_geografia        INT           NULL,       -- ubicacion del establecimiento
    linea_base_operativa DECIMAL(12,2) NULL,      -- capacidad operativa de referencia (PRD v1.3)
    CONSTRAINT pk_dim_establecimiento PRIMARY KEY (id_establecimiento),
    CONSTRAINT uq_dim_establecimiento_nombre UNIQUE (nombre_centro),
    CONSTRAINT fk_dim_establecimiento_geografia
        FOREIGN KEY (id_geografia) REFERENCES dw.dim_geografia (id_geografia)
);
GO

/* ---------------------------------------------------------------------------
   dim_especialidad
   Granularidad: servicio / especialidad medica (DES_SER).
   Valores reales observados: Medicina, Ginecologia, Pediatria, Cirugia,
   Obstetricia. Se incluye agrupacion por area para analisis del PRD.
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dw.dim_especialidad', 'U') IS NOT NULL
    DROP TABLE dw.dim_especialidad;
GO

CREATE TABLE dw.dim_especialidad (
    id_especialidad INT IDENTITY(1,1) NOT NULL,
    especialidad    VARCHAR(60)   NOT NULL,   -- DES_SER (limpiado de padding)
    area            VARCHAR(30)   NULL,       -- agrupacion: Clinica, Quirurgica, etc.
    CONSTRAINT pk_dim_especialidad PRIMARY KEY (id_especialidad),
    CONSTRAINT uq_dim_especialidad UNIQUE (especialidad)
);
GO

PRINT 'Dimensiones creadas: dim_tiempo, dim_geografia, dim_establecimiento, dim_especialidad.';
GO