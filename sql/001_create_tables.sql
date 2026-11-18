-- =========================================================
-- PROJET : Rôles d'évaluation foncière du Québec
-- Fichier : 001_create_tables.sql
-- SGBD    : PostgreSQL 16 (UNIQUE ... NULLS NOT DISTINCT requiert PG 15+)
--
-- Principe : une municipalité a des rôles (un par millésime),
-- un rôle contient des unités d'évaluation (propriétés), et
-- chaque groupe répétable du XML (RL0101x, RL0103x, RL0201x,
-- RL0504x, RL0507x) devient une table enfant de l'unité.
-- Valeur NULL = champ absent du XML. Valeur 0 = zéro explicite.
-- =========================================================

BEGIN;

-- =========================================================
-- 1. municipality
-- Alimentée par l'index CSV (le XML ne contient que le code).
-- Code sur 5 caractères : l'index écrit 1023, le fichier 01023.
-- =========================================================

CREATE TABLE IF NOT EXISTS municipality (
    municipality_code CHAR(5) PRIMARY KEY
        CONSTRAINT ck_municipality_code CHECK (municipality_code ~ '^[0-9]{5}$'),
    name              TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =========================================================
-- 2. assessment_role
-- Un rôle = une municipalité + un millésime (RLM02A).
-- Rejouer un fichier = remplacer ce rôle (voir étape 3).
-- =========================================================

CREATE TABLE IF NOT EXISTS assessment_role (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    municipality_code CHAR(5)     NOT NULL
        CONSTRAINT fk_assessment_role_municipality
        REFERENCES municipality (municipality_code),
    assessment_year   SMALLINT    NOT NULL,
    format_version    VARCHAR(10) NOT NULL,   -- VERSION : 2.6 à 2.9
    source_file       TEXT        NOT NULL,
    imported_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_assessment_role UNIQUE (municipality_code, assessment_year)
);

-- =========================================================
-- 3. assessment_unit
-- Une unité d'évaluation = un terrain et ses bâtiments.
-- Le matricule est composé de 3 parties obligatoires (A, B, C)
-- et de 5 facultatives (D à H) : on garde chaque partie, et la
-- contrainte d'unicité considère deux NULL comme égaux.
-- =========================================================

CREATE TABLE IF NOT EXISTS assessment_unit (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role_id                     BIGINT NOT NULL
        CONSTRAINT fk_assessment_unit_role
        REFERENCES assessment_role (id) ON DELETE CASCADE,

    -- Matricule (RL0104A à RL0104H) : du TEXTE, pour garder les zéros
    matricule_division          TEXT NOT NULL,   -- RL0104A
    matricule_section           TEXT NOT NULL,   -- RL0104B
    matricule_location          TEXT NOT NULL,   -- RL0104C (emplacement)
    matricule_check_digit       TEXT,            -- RL0104D
    building_number             TEXT,            -- RL0104E
    local_number                TEXT,            -- RL0104F
    utm_zone                    TEXT,            -- RL0104G (fuseau)
    discriminant                TEXT,            -- RL0104H

    -- Identification
    borough_number              TEXT,            -- RL0102A
    primary_use_code            TEXT,            -- RL0105A (CUBF)
    file_number                 TEXT,            -- RL0106A
    neighbourhood_unit          TEXT,            -- RL0107A
    owner_condition_code        SMALLINT         -- RL0201U (1 à 9)
        CONSTRAINT ck_unit_owner_condition CHECK (owner_condition_code BETWEEN 1 AND 9),

    -- Terrain
    frontage_m                  NUMERIC(8, 2),   -- RL0301A
    land_area_m2                NUMERIC(15, 2),  -- RL0302A
    agricultural_zoning_code    SMALLINT         -- RL0303A (0, 1, 2)
        CONSTRAINT ck_unit_agri_zoning CHECK (agricultural_zoning_code IN (0, 1, 2)),
    eae_total_area_m2           NUMERIC(15, 2),  -- RL0304A
    eae_agri_zone_area_m2       NUMERIC(15, 2),  -- RL0305A
    eae_max_taxation_area_m2    NUMERIC(15, 2),  -- RL0314A
    forest_total_area_m2        NUMERIC(15, 2),  -- RL0315A
    forest_agri_zone_area_m2    NUMERIC(15, 2),  -- RL0316A

    -- Bâtiment principal
    number_of_floors            SMALLINT,        -- RL0306A
    construction_year           SMALLINT,        -- RL0307A
    construction_year_kind      CHAR(1)          -- RL0307B (R réelle, E estimée)
        CONSTRAINT ck_unit_year_kind CHECK (construction_year_kind IN ('R', 'E')),
    floor_area_m2               NUMERIC(12, 2),  -- RL0308A
    physical_link_code          SMALLINT         -- RL0309A (1 à 5)
        CONSTRAINT ck_unit_physical_link CHECK (physical_link_code BETWEEN 1 AND 5),
    construction_type_code      SMALLINT         -- RL0310A (1 à 5)
        CONSTRAINT ck_unit_construction_type CHECK (construction_type_code BETWEEN 1 AND 5),
    dwelling_count              INTEGER,         -- RL0311A
    rental_room_count           INTEGER,         -- RL0312A
    non_residential_count       INTEGER,         -- RL0313A

    -- Valeurs au rôle (NULL = absent, 0 = zéro explicite)
    market_reference_date       DATE,            -- RL0401A
    land_value                  NUMERIC(15, 2),  -- RL0402A
    building_value              NUMERIC(15, 2),  -- RL0403A
    total_value                 NUMERIC(15, 2),  -- RL0404A
    previous_role_value         NUMERIC(15, 2),  -- RL0405A

    -- Catégories fiscales
    vacant_serviced_land        BOOLEAN,         -- RL0501A (0 / 1)
    non_residential_class       TEXT,            -- RL0502A ('1A', '03', ...)
    industrial_class            SMALLINT,        -- RL0503A

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_assessment_unit UNIQUE NULLS NOT DISTINCT (
        role_id, matricule_division, matricule_section, matricule_location,
        matricule_check_digit, building_number, local_number, utm_zone, discriminant
    )
);

-- =========================================================
-- 4. Tables enfants (groupes répétables du XML)
-- =========================================================

-- RL0101x : une unité peut avoir plusieurs adresses
CREATE TABLE IF NOT EXISTS unit_address (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    unit_id             BIGINT NOT NULL
        REFERENCES assessment_unit (id) ON DELETE CASCADE,
    lower_number        TEXT,    -- RL0101Ax
    lower_number_suffix TEXT,    -- RL0101Bx
    upper_number        TEXT,    -- RL0101Cx
    upper_number_suffix TEXT,    -- RL0101Dx
    street_type_code    TEXT,    -- RL0101Ex (code de générique)
    link_code           TEXT,    -- RL0101Fx
    street_name         TEXT,    -- RL0101Gx (texte libre, non normalisé)
    cardinal_point_code TEXT,    -- RL0101Hx
    apartment_number    TEXT,    -- RL0101Ix
    apartment_suffix    TEXT     -- RL0101Jx
);

-- RL0201x : inscriptions de propriétaires (sans nom ni adresse)
CREATE TABLE IF NOT EXISTS unit_owner_registration (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    unit_id           BIGINT NOT NULL
        REFERENCES assessment_unit (id) ON DELETE CASCADE,
    registration_date DATE,       -- RL0201Gx
    owner_status_code SMALLINT    -- RL0201Hx (1 personne physique, 2 morale)
        CONSTRAINT ck_owner_status CHECK (owner_status_code IN (1, 2))
);

-- RL0103x : champ NON documenté dans le guide, conservé tel quel.
-- Hypothèse (non confirmée) : désignation cadastrale.
CREATE TABLE IF NOT EXISTS unit_cadastral_ref (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    unit_id   BIGINT NOT NULL
        REFERENCES assessment_unit (id) ON DELETE CASCADE,
    value_a   TEXT,   -- RL0103Ax
    value_b   TEXT,   -- RL0103Bx
    value_c   TEXT,   -- RL0103Cx
    value_d   TEXT,   -- RL0103Dx
    value_e   TEXT,   -- RL0103Ex
    value_f   TEXT    -- RL0103Fx
);

-- RL0504x (général) et RL0507x (scolaire, exploitations agricoles)
CREATE TABLE IF NOT EXISTS unit_tax_split (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    unit_id          BIGINT NOT NULL
        REFERENCES assessment_unit (id) ON DELETE CASCADE,
    split_kind       TEXT NOT NULL
        CONSTRAINT ck_tax_split_kind CHECK (split_kind IN ('general', 'school')),
    law_number       TEXT,            -- RL0504Ax / RL0507Ax
    article_number   TEXT,            -- RL0504Bx / RL0507Bx
    paragraph_number TEXT,            -- RL0504Cx / RL0507Cx
    amount           NUMERIC(15, 2),  -- RL0504Dx / RL0507Dx
    part_code        CHAR(1)          -- RL0504Ex / RL0507Ex
        CONSTRAINT ck_tax_split_part CHECK (part_code IN ('T', 'B', 'I')),
    taxability_code  SMALLINT         -- RL0504Fx / RL0507Fx
        CONSTRAINT ck_tax_split_taxability CHECK (taxability_code IN (1, 2, 3))
);

-- =========================================================
-- 5. Suivi des imports (utilisé à l'étape 3 : erreurs, relances)
-- =========================================================

CREATE TABLE IF NOT EXISTS import_run (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'running'
        CONSTRAINT ck_import_run_status CHECK (status IN ('running', 'success', 'failed'))
);

CREATE TABLE IF NOT EXISTS import_issue (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      BIGINT NOT NULL
        REFERENCES import_run (id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    severity    TEXT NOT NULL
        CONSTRAINT ck_import_issue_severity CHECK (severity IN ('warning', 'error')),
    code        TEXT NOT NULL,   -- ex. 'UNKNOWN_TAG', 'VALUE_MISMATCH'
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =========================================================
-- 6. Index (les contraintes UNIQUE créent déjà les leurs :
--    inutile d'indexer role_id seul ni municipality_code seul)
-- =========================================================

CREATE INDEX IF NOT EXISTS idx_assessment_role_year
    ON assessment_role (assessment_year);

CREATE INDEX IF NOT EXISTS idx_assessment_unit_matricule
    ON assessment_unit (matricule_division, matricule_section, matricule_location);

CREATE INDEX IF NOT EXISTS idx_unit_address_unit      ON unit_address (unit_id);
CREATE INDEX IF NOT EXISTS idx_unit_owner_unit        ON unit_owner_registration (unit_id);
CREATE INDEX IF NOT EXISTS idx_unit_cadastral_unit    ON unit_cadastral_ref (unit_id);
CREATE INDEX IF NOT EXISTS idx_unit_tax_split_unit    ON unit_tax_split (unit_id);
CREATE INDEX IF NOT EXISTS idx_import_issue_run       ON import_issue (run_id);

-- =========================================================
-- 7. Vue latest_assessment : dernière évaluation de chaque propriété
-- =========================================================

CREATE OR REPLACE VIEW latest_assessment AS
SELECT DISTINCT ON (
    ar.municipality_code,
    au.matricule_division, au.matricule_section, au.matricule_location,
    au.matricule_check_digit, au.building_number, au.local_number,
    au.utm_zone, au.discriminant
)
    m.municipality_code,
    m.name AS municipality_name,
    au.matricule_division,
    au.matricule_section,
    au.matricule_location,
    au.matricule_check_digit,
    au.building_number,
    au.local_number,
    ar.assessment_year,
    au.land_value,
    au.building_value,
    au.total_value,
    ar.imported_at
FROM assessment_unit au
JOIN assessment_role ar ON au.role_id = ar.id
JOIN municipality m     ON ar.municipality_code = m.municipality_code
ORDER BY
    ar.municipality_code,
    au.matricule_division, au.matricule_section, au.matricule_location,
    au.matricule_check_digit, au.building_number, au.local_number,
    au.utm_zone, au.discriminant,
    ar.assessment_year DESC,
    ar.imported_at DESC;

COMMIT;