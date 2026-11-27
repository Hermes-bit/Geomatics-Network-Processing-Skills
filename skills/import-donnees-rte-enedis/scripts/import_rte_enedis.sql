-- =============================================================================
-- Import des données ouvertes des réseaux électriques (RTE, Enedis, Agence ORE) dans PostGIS.
-- PostGIS >= 3.1. Testé avec PostgreSQL 16 et PostGIS 3.4.
--
-- Entrée : les fichiers téléchargés (ODRÉ pour RTE, opendata.enedis.fr ou opendata.agenceore.fr
-- pour la distribution), chargés tels quels par ogr2ogr dans le schéma elec_brut :
--   elec_brut.lignes_<nom>   une table par fichier de lignes (aériennes, souterraines, HTB, HTA, BT)
--   elec_brut.postes_<nom>   une table par fichier de postes (RTE, postes sources, postes HTA/BT)
-- Le nom de la table sert de valeur par défaut : « rte » -> gestionnaire RTE,
-- « aerien » / « souterrain » -> pose, « source » / « hta_bt » -> type de poste.
--
-- Sortie : schéma reseau_elec (recréé à chaque exécution), au format du skill controle-topologie-reseau :
--   reseau_elec.troncons(id, gestionnaire, domaine, tension_kv, pose, etat_exploitation, ..., geom)
--   reseau_elec.postes(id, nom, type, gestionnaire, ..., geom)
--   reseau_elec.ouvrages_dtdict   vue au format du skill proximite-dt-dict
--   reseau_elec.champs_utilises, reseau_elec.controles, reseau_elec.resume
-- Les tables de elec_brut ne sont jamais modifiées.
--   psql -d ma_base -f import_rte_enedis.sql
-- =============================================================================

SET client_min_messages = warning;
DROP SCHEMA IF EXISTS reseau_elec CASCADE;
CREATE SCHEMA reseau_elec;

-- -----------------------------------------------------------------------------
-- 0. PARAMÈTRES ET NOMS DE CHAMPS (à adapter)
-- -----------------------------------------------------------------------------
CREATE TABLE reseau_elec.parametres AS SELECT
  'elec_brut'::text AS schema_brut,
  20::numeric  AS tension_hta_kv,  -- valeur retenue quand le fichier dit seulement « HTA »
  0.4::numeric AS tension_bt_kv,   -- valeur retenue quand le fichier dit seulement « BT »
  NULL::text   AS zone_wkt_l93;    -- polygone en Lambert 93 pour ne garder qu'une zone (NULL = tout)

CREATE TABLE reseau_elec.correspondance (couche text, role text, noms text[]);
INSERT INTO reseau_elec.correspondance VALUES
  ('lignes', 'id_source',    ARRAY['code_ligne', 'identifiant', 'id', 'objectid', 'ogc_fid']),
  ('lignes', 'nom',          ARRAY['nom_ligne', 'nom', 'libelle']),
  ('lignes', 'tension',      ARRAY['tension', 'tension_kv', 'niveau_tension', 'domaine_tension']),
  ('lignes', 'pose',         ARRAY['position', 'pose', 'type_ligne', 'nature']),
  ('lignes', 'etat',         ARRAY['etat', 'statut', 'etat_exploitation']),
  ('lignes', 'gestionnaire', ARRAY['nom_grd', 'gestionnaire', 'proprietaire', 'exploitant']),
  ('lignes', 'code_insee',   ARRAY['code_insee', 'code_commune', 'insee']),
  ('postes', 'id_source',    ARRAY['code_poste', 'identifiant', 'id', 'objectid', 'ogc_fid']),
  ('postes', 'nom',          ARRAY['nom_poste', 'nom', 'libelle']),
  ('postes', 'type',         ARRAY['fonction', 'type_poste', 'type', 'nature']),
  ('postes', 'tension',      ARRAY['tension', 'tension_kv', 'tension_max']),
  ('postes', 'etat',         ARRAY['etat', 'statut']),
  ('postes', 'gestionnaire', ARRAY['nom_grd', 'gestionnaire', 'proprietaire', 'exploitant']),
  ('postes', 'code_insee',   ARRAY['code_insee', 'code_commune', 'insee']);

-- -----------------------------------------------------------------------------
-- 1. OUTILS
-- -----------------------------------------------------------------------------
CREATE TABLE reseau_elec.champs_utilises (table_source text, role text, champ text);
CREATE TABLE reseau_elec.controles (
  id serial PRIMARY KEY, table_source text, id_objet text, type text, detail text, geom geometry(Geometry, 2154)
);

-- Texte sans accents et en minuscules, pour comparer « Aérien », « AERIENNE », « aérien ».
CREATE FUNCTION reseau_elec._norm(t text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT lower(translate(coalesce(t, ''), 'ÀÂÄÉÈÊËÎÏÔÖÙÛÜÇàâäéèêëîïôöùûüç', 'AAAEEEEIIOOUUUCaaaeeeeiioouuuc'))
$$;

-- Tension en kV à partir d'un texte ou d'un nombre : '225kV' -> 225, '63 kV' -> 63, 'HTA' -> 20,
-- 'BT' -> 0.4, 20000 (volts) -> 20, 'HORS TENSION' ou 'HTB' -> NULL.
CREATE FUNCTION reseau_elec.tension_vers_kv(t text) RETURNS numeric LANGUAGE plpgsql STABLE AS $$
DECLARE n text := reseau_elec._norm(t); v numeric; m text[];
BEGIN
  IF n = '' OR n LIKE '%hors tension%' THEN RETURN NULL; END IF;
  m := regexp_match(replace(n, ',', '.'), '(\d+(?:\.\d+)?)\s*(kv|v)?');
  IF m IS NOT NULL THEN
    v := m[1]::numeric;
    IF m[2] = 'v' OR (m[2] IS NULL AND v >= 1000) THEN v := v / 1000; END IF;
    RETURN v;
  END IF;
  IF n ~ '\mhta\M' THEN RETURN (SELECT tension_hta_kv FROM reseau_elec.parametres); END IF;
  IF n ~ '\mbt\M'  THEN RETURN (SELECT tension_bt_kv FROM reseau_elec.parametres); END IF;
  RETURN NULL;
END $$;

-- Vue normalisée d'une table brute : champs renommés selon les rôles, géométrie en 2154.
CREATE FUNCTION reseau_elec._preparer(p_couche text, p_table text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE r record; champ text; cols text := ''; geomcol text; srid int; sch text;
BEGIN
  SELECT schema_brut INTO sch FROM reseau_elec.parametres;
  SELECT f_geometry_column, gc.srid INTO geomcol, srid FROM geometry_columns gc
  WHERE f_table_schema = sch AND f_table_name = p_table LIMIT 1;
  IF geomcol IS NULL THEN
    RAISE EXCEPTION 'Table %.% sans géométrie : la charger avec ogr2ogr depuis le GeoJSON ou le shapefile', sch, p_table;
  END IF;
  FOR r IN SELECT * FROM reseau_elec.correspondance WHERE couche = p_couche LOOP
    SELECT c.column_name INTO champ
    FROM unnest(r.noms) WITH ORDINALITY n(nom, i)
    JOIN information_schema.columns c
      ON c.table_schema = sch AND c.table_name = p_table AND lower(c.column_name) = lower(n.nom)
    ORDER BY n.i LIMIT 1;
    INSERT INTO reseau_elec.champs_utilises VALUES (p_table, r.role, champ);
    cols := cols || format('%s::text AS %I, ', coalesce(quote_ident(champ), 'NULL'), r.role);
  END LOOP;
  EXECUTE format(
    'CREATE VIEW reseau_elec.%I AS SELECT %L::text AS table_source, %s %s AS geom, to_jsonb(t) - %L AS attributs FROM %I.%I t',
    'v_' || p_table, p_table, cols,
    CASE WHEN srid = 2154 THEN quote_ident(geomcol)
         WHEN srid IS NULL OR srid IN (0, -1) THEN 'ST_Transform(ST_SetSRID(' || quote_ident(geomcol) || ', 4326), 2154)'
         ELSE 'ST_Transform(' || quote_ident(geomcol) || ', 2154)' END,
    geomcol, sch, p_table);
  IF srid IS NULL OR srid IN (0, -1) THEN
    INSERT INTO reseau_elec.controles (table_source, type, detail)
    VALUES (p_table, 'scr_suppose', 'SRID absent : WGS84 (4326) supposé');
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 2. RÉUNION DES TABLES BRUTES
-- -----------------------------------------------------------------------------
DO $$
DECLARE sch text; t text; lignes text := ''; postes text := '';
BEGIN
  SELECT schema_brut INTO sch FROM reseau_elec.parametres;
  FOR t IN SELECT table_name FROM information_schema.tables
           WHERE table_schema = sch AND table_type = 'BASE TABLE'
             AND (table_name LIKE 'lignes\_%' OR table_name LIKE 'postes\_%') ORDER BY table_name LOOP
    PERFORM reseau_elec._preparer(split_part(t, '_', 1), t);
    IF t LIKE 'lignes\_%' THEN
      lignes := lignes || CASE WHEN lignes <> '' THEN ' UNION ALL ' ELSE '' END || format('SELECT * FROM reseau_elec.%I', 'v_' || t);
    ELSE
      postes := postes || CASE WHEN postes <> '' THEN ' UNION ALL ' ELSE '' END || format('SELECT * FROM reseau_elec.%I', 'v_' || t);
    END IF;
  END LOOP;
  IF lignes = '' THEN
    RAISE EXCEPTION 'Aucune table %.lignes_* : charger au moins un fichier de lignes (voir SKILL.md)', sch;
  END IF;
  EXECUTE 'CREATE VIEW reseau_elec.v_lignes AS ' || lignes;
  IF postes = '' THEN
    EXECUTE 'CREATE VIEW reseau_elec.v_postes AS SELECT NULL::text AS table_source, NULL::text AS id_source, NULL::text AS nom,
             NULL::text AS type, NULL::text AS tension, NULL::text AS etat, NULL::text AS gestionnaire, NULL::text AS code_insee,
             NULL::geometry AS geom, NULL::jsonb AS attributs WHERE false';
  ELSE
    EXECUTE 'CREATE VIEW reseau_elec.v_postes AS ' || postes;
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 3. TRONÇONS (format du skill controle-topologie-reseau)
-- -----------------------------------------------------------------------------
CREATE TABLE reseau_elec.troncons AS
WITH l AS (
  SELECT v.*, reseau_elec._norm(v.table_source) AS nt, reseau_elec._norm(v.pose) AS np,
         reseau_elec._norm(v.tension) AS ntens, reseau_elec._norm(v.etat) AS netat
  FROM reseau_elec.v_lignes v, reseau_elec.parametres p
  WHERE v.geom IS NOT NULL
    AND (p.zone_wkt_l93 IS NULL OR ST_Intersects(v.geom, ST_GeomFromText(p.zone_wkt_l93, 2154)))
)
SELECT row_number() OVER (ORDER BY table_source, id_source, ST_XMin(geom))::int AS id,
       id_source, nom,
       coalesce(gestionnaire, CASE WHEN nt LIKE '%rte%' THEN 'RTE' END) AS gestionnaire,
       reseau_elec.tension_vers_kv(tension) AS tension_kv,
       tension AS tension_origine,
       CASE WHEN reseau_elec.tension_vers_kv(tension) IS NULL THEN
              CASE WHEN ntens ~ '\mbt\M' THEN 'BT' WHEN ntens ~ '\mhta\M' THEN 'HTA' WHEN ntens ~ '\mhtb\M' THEN 'HTB'
                   WHEN nt LIKE '%rte%' OR nt LIKE '%htb%' THEN 'HTB' WHEN nt LIKE '%hta%' THEN 'HTA' WHEN nt LIKE '%\_bt%' THEN 'BT' END
            WHEN reseau_elec.tension_vers_kv(tension) <= 1 THEN 'BT'
            WHEN reseau_elec.tension_vers_kv(tension) <= 50 THEN 'HTA'
            ELSE 'HTB' END AS domaine,
       CASE WHEN np LIKE '%aer%' OR np LIKE '%aerien%' THEN 'aerien'
            WHEN np LIKE '%souterr%' OR np LIKE '%enterr%' THEN 'souterrain'
            WHEN np LIKE '%sous-marin%' OR np LIKE '%subaqu%' THEN 'subaquatique'
            WHEN nt LIKE '%aer%' THEN 'aerien'
            WHEN nt LIKE '%souterr%' THEN 'souterrain' END AS pose,
       -- Les points d'ouverture (NO) ne sont pas publiés en données ouvertes.
       CASE WHEN netat LIKE '%hors tension%' OR ntens LIKE '%hors tension%' THEN 'hors_tension'
            WHEN netat LIKE '%projet%' THEN 'en_projet' END AS etat_exploitation,
       code_insee, table_source,
       ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 2))::geometry(MultiLineString, 2154) AS geom,
       attributs
FROM l;
CREATE INDEX ON reseau_elec.troncons USING gist (geom);

-- Le skill de topologie tient « hors_tension » et « en_projet » pour des tronçons fermés :
-- ils sont signalés pour que l'utilisateur décide de les retirer.
INSERT INTO reseau_elec.controles (table_source, id_objet, type, detail, geom)
SELECT table_source, id::text, 'hors_exploitation', 'état : ' || etat_exploitation, geom
FROM reseau_elec.troncons WHERE etat_exploitation IS NOT NULL;

INSERT INTO reseau_elec.controles (table_source, id_objet, type, detail, geom)
SELECT table_source, id::text, 'tension_illisible', 'tension « ' || coalesce(tension_origine, 'vide') || ' »', geom
FROM reseau_elec.troncons WHERE tension_kv IS NULL AND etat_exploitation IS DISTINCT FROM 'hors_tension';

-- Une seule ligne par table : la tension n'est donnée que par domaine (HTA, BT).
INSERT INTO reseau_elec.controles (table_source, id_objet, type, detail)
SELECT table_source, count(*) || ' tronçons', 'tension_supposee',
       'tension « ' || min(tension_origine) || ' » : ' || min(tension_kv) || ' kV retenus (valeur nominale par défaut, à confirmer)'
FROM reseau_elec.troncons WHERE reseau_elec._norm(tension_origine) IN ('hta', 'bt')
GROUP BY table_source, reseau_elec._norm(tension_origine);

INSERT INTO reseau_elec.controles (table_source, id_objet, type, detail, geom)
SELECT table_source, id::text, 'pose_inconnue', 'ni le champ ni le nom de la table ne disent aérien ou souterrain', geom
FROM reseau_elec.troncons WHERE pose IS NULL;

INSERT INTO reseau_elec.controles (table_source, id_objet, type, detail, geom)
SELECT table_source, id::text, 'geometrie_vide', 'aucune ligne exploitable après ST_MakeValid', NULL
FROM reseau_elec.troncons WHERE ST_IsEmpty(geom);
DELETE FROM reseau_elec.troncons WHERE ST_IsEmpty(geom);

-- -----------------------------------------------------------------------------
-- 4. POSTES
-- -----------------------------------------------------------------------------
CREATE TABLE reseau_elec.postes AS
WITH p AS (
  SELECT v.*, reseau_elec._norm(v.table_source) AS nt, reseau_elec._norm(v.type) AS ntype
  FROM reseau_elec.v_postes v, reseau_elec.parametres pr
  WHERE v.geom IS NOT NULL
    AND (pr.zone_wkt_l93 IS NULL OR ST_Intersects(v.geom, ST_GeomFromText(pr.zone_wkt_l93, 2154)))
)
SELECT row_number() OVER (ORDER BY table_source, id_source, nom)::int AS id,
       id_source, nom,
       CASE WHEN nt LIKE '%source%' OR ntype LIKE '%source%' OR ntype LIKE '%repartition%' THEN 'poste_source'
            WHEN nt LIKE '%hta_bt%' OR ntype LIKE '%hta/bt%' OR ntype LIKE '%distribution%' THEN 'poste_hta_bt'
            WHEN nt LIKE '%rte%' OR ntype LIKE '%transformation%' OR ntype LIKE '%piquage%' THEN 'poste_htb'
            ELSE 'poste' END AS type,
       type AS type_origine,
       coalesce(gestionnaire, CASE WHEN nt LIKE '%rte%' THEN 'RTE' END) AS gestionnaire,
       tension AS tension_origine, etat, code_insee, table_source,
       ST_PointOnSurface(geom)::geometry(Point, 2154) AS geom,  -- une enceinte de poste devient un point
       attributs
FROM p;
CREATE INDEX ON reseau_elec.postes USING gist (geom);

-- Postes publiés en double (même type à moins de 1 m, souvent l'enceinte et le point)
INSERT INTO reseau_elec.controles (table_source, id_objet, type, detail, geom)
SELECT b.table_source, b.id::text, 'poste_en_double', 'à ' || round(ST_Distance(a.geom, b.geom)::numeric, 2) || ' m du poste ' || a.id, b.geom
FROM reseau_elec.postes a JOIN reseau_elec.postes b
  ON a.id < b.id AND a.type = b.type AND ST_DWithin(a.geom, b.geom, 1);

-- -----------------------------------------------------------------------------
-- 5. VUES POUR LES AUTRES SKILLS
-- -----------------------------------------------------------------------------
-- Skill proximite-dt-dict : la précision des données ouvertes est inconnue, donc classe C.
CREATE VIEW reseau_elec.ouvrages_dtdict AS
SELECT id::text AS id, coalesce(gestionnaire, 'gestionnaire inconnu') AS exploitant, 'electricite'::text AS categorie,
       pose, NULL::text AS classe_precision, true AS flexible, false AS branchement, tension_kv, geom
FROM reseau_elec.troncons;

CREATE VIEW reseau_elec.resume AS
SELECT 'troncons' AS couche, coalesce(domaine, '?') || ' ' || coalesce(pose, '?') AS detail, count(*) AS nb,
       round(sum(ST_Length(geom))::numeric) AS longueur_m
FROM reseau_elec.troncons GROUP BY domaine, pose
UNION ALL
SELECT 'postes', type, count(*), NULL FROM reseau_elec.postes GROUP BY type
UNION ALL
SELECT 'controles', type, count(*), NULL FROM reseau_elec.controles GROUP BY type
ORDER BY 1, 2;

\echo '--- Résumé de l''import'
SELECT * FROM reseau_elec.resume;
