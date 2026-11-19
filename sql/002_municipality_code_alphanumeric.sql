-- =========================================================
-- Fichier : 002_municipality_code_alphanumeric.sql
-- Raison  : l'index contient 34 codes avec des lettres (NR020, NR030...),
--           qui désignent des territoires non organisés. Le code reste sur
--           5 caractères, mais peut contenir des lettres majuscules.
-- Rejouable : la contrainte est supprimée puis recréée.
-- =========================================================

BEGIN;

ALTER TABLE municipality DROP CONSTRAINT IF EXISTS ck_municipality_code;

ALTER TABLE municipality
    ADD CONSTRAINT ck_municipality_code
    CHECK (municipality_code ~ '^[0-9A-Z]{5}$');

COMMIT;