-- =============================================================================
-- Import des données ouvertes de SNCF Réseau dans PostGIS, en Lambert 93.
-- PostGIS >= 3.1. Testé avec PostgreSQL 16 et PostGIS 3.4.
--
-- Entrée : les fichiers téléchargés sur ressources.data.sncf.com, chargés tels quels
-- par ogr2ogr dans le schéma sncf_brut (voir SKILL.md) :
--   sncf_brut.lignes            formes-des-lignes-du-rfn          (obligatoire)
--   sncf_brut.gares             liste-des-gares                    (facultatif)
--   sncf_brut.passages_niveau   liste-des-passages-a-niveau        (facultatif)
--   sncf_brut.ouvrages_*        liste-des-passerelles, liste-des-ponts-route,
--                               liste-des-passages-souterrains…   (facultatif, un par fichier)
--
-- Sortie : schéma sncf (recréé à chaque exécution) :
--   sncf.lignes, sncf.gares, sncf.passages_niveau, sncf.ouvrages   couches propres pour QGIS
--   sncf.axes, sncf.bornes_pk, sncf.sauts_pk                       entrées du skill referencement-pk-ferroviaire
--   sncf.champs_utilises       quel champ source a servi à quoi
--   sncf.controles             anomalies relevées pendant l'import
-- Les tables de sncf_brut ne sont jamais modifiées.
--   psql -d ma_base -f import_sncf_reseau.sql
-- =============================================================================

SET client_min_messages = warning;
DROP SCHEMA IF EXISTS sncf CASCADE;
CREATE SCHEMA sncf;

-- -----------------------------------------------------------------------------
-- 0. PARAMÈTRES ET NOMS DE CHAMPS (à adapter si l'export a changé)
-- -----------------------------------------------------------------------------
CREATE TABLE sncf.parametres AS SELECT
  'sncf_brut'::text AS schema_brut,
  20.0::float AS distance_max_ligne,   -- m : objet plus loin de sa ligne = signalé
  0.05::float AS ecart_longueur_max,   -- 5 % : écart toléré entre PK et longueur du tronçon
  1.0::float  AS tolerance_jonction,   -- m : deux tronçons qui se touchent
  0.5::float  AS ecart_pk_saut;        -- m : écart de PK à une jonction au-delà duquel on déclare un saut

-- Pour chaque rôle, les noms de champs possibles, dans l'ordre de préférence.
-- Le script prend le premier qui existe (sans tenir compte des majuscules).
CREATE TABLE sncf.correspondance (couche text, role text, noms text[], obligatoire boolean);
INSERT INTO sncf.correspondance VALUES
  ('lignes', 'code_ligne', ARRAY['code_ligne', 'code_lign', 'ligne', 'cd_ligne'], true),
  ('lignes', 'lib_ligne',  ARRAY['lib_ligne', 'libelle', 'nom_ligne', 'nom'], false),
  ('lignes', 'statut',     ARRAY['statut', 'mnemo', 'etat'], false),
  ('lignes', 'rg_troncon', ARRAY['rg_troncon', 'rang', 'rang_troncon'], false),
  ('lignes', 'pkd',        ARRAY['pkd', 'pk_debut', 'pk_deb', 'pkdebut'], true),
  ('lignes', 'pkf',        ARRAY['pkf', 'pk_fin', 'pkfin'], true),
  ('gares', 'code_ligne',  ARRAY['code_ligne', 'code_lign', 'ligne'], false),
  ('gares', 'pk',          ARRAY['pk', 'pk_gare', 'pkd'], false),
  ('gares', 'libelle',     ARRAY['libelle', 'nom', 'nom_gare', 'libelle_gare'], true),
  ('gares', 'code_uic',    ARRAY['code_uic', 'uic', 'code_gare'], false),
  ('gares', 'voyageurs',   ARRAY['voyageurs', 'voyageur'], false),
  ('gares', 'fret',        ARRAY['fret'], false),
  ('passages_niveau', 'code_ligne', ARRAY['code_ligne', 'code_lign', 'ligne'], false),
  ('passages_niveau', 'pk',         ARRAY['pk', 'pk_pn'], false),
  ('passages_niveau', 'libelle',    ARRAY['libelle', 'nom', 'libelle_pn', 'num_pn'], false),
  ('passages_niveau', 'classe',     ARRAY['classe', 'type', 'classe_pn'], false),
  ('ouvrages', 'code_ligne', ARRAY['code_ligne', 'code_lign', 'ligne'], false),
  ('ouvrages', 'pk',         ARRAY['pk', 'pkd', 'pk_ouvrage'], false),
  ('ouvrages', 'libelle',    ARRAY['libelle', 'nom', 'designation', 'num_ouvrage'], false);

-- -----------------------------------------------------------------------------
-- 1. OUTILS : format des PK et détection des champs
-- -----------------------------------------------------------------------------
-- PK texte km+m ('012+345', '12+345.6', ' 12 + 345 ') -> mètres ; NULL si illisible.
CREATE FUNCTION sncf.pk_vers_m(pk text) RETURNS numeric LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE m text[];
BEGIN
  IF pk IS NULL THEN RETURN NULL; END IF;
  m := regexp_match(replace(pk, ' ', ''), '^(-?\d+)\+(\d{1,3}(?:[.,]\d+)?)$');
  IF m IS NULL THEN RETURN NULL; END IF;
  RETURN m[1]::numeric * 1000 + replace(m[2], ',', '.')::numeric;
END $$;

-- Mètres -> texte au format du skill PK : 4250 -> '4+250'
CREATE FUNCTION sncf.m_vers_pk(m numeric) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT floor(m / 1000)::int || '+' || lpad(floor(m - floor(m / 1000) * 1000)::int::text, 3, '0') ||
         coalesce('.' || nullif(rtrim(substring((m - floor(m))::text FROM '\.(\d+)'), '0'), ''), '')
$$;

CREATE TABLE sncf.champs_utilises (couche text, table_source text, role text, champ text);
CREATE TABLE sncf.controles (
  id serial PRIMARY KEY, couche text, id_objet text, type text, detail text, geom geometry(Geometry, 2154)
);

-- Vue normalisée d'une table brute : champs renommés selon les rôles, géométrie en 2154.
CREATE FUNCTION sncf._preparer(p_couche text, p_table text, p_vue text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  r record; champ text; cols text := ''; geomcol text; srid int; sch text;
  dispo text;
BEGIN
  SELECT schema_brut INTO sch FROM sncf.parametres;
  SELECT f_geometry_column, gc.srid INTO geomcol, srid FROM geometry_columns gc
  WHERE f_table_schema = sch AND f_table_name = p_table LIMIT 1;
  IF geomcol IS NULL THEN
    RAISE EXCEPTION 'Table %.% sans géométrie : charger le GeoJSON ou le shapefile avec ogr2ogr', sch, p_table;
  END IF;
  SELECT string_agg(column_name, ', ' ORDER BY ordinal_position) INTO dispo
  FROM information_schema.columns WHERE table_schema = sch AND table_name = p_table;

  FOR r IN SELECT * FROM sncf.correspondance WHERE couche = p_couche LOOP
    SELECT c.column_name INTO champ
    FROM unnest(r.noms) WITH ORDINALITY n(nom, i)
    JOIN information_schema.columns c
      ON c.table_schema = sch AND c.table_name = p_table AND lower(c.column_name) = lower(n.nom)
    ORDER BY n.i LIMIT 1;
    IF champ IS NULL AND r.obligatoire THEN
      RAISE EXCEPTION 'Champ « % » introuvable dans %.% (noms essayés : %). Champs présents : %. Compléter sncf.correspondance.',
        r.role, sch, p_table, array_to_string(r.noms, ', '), dispo;
    END IF;
    INSERT INTO sncf.champs_utilises VALUES (p_couche, p_table, r.role, champ);
    cols := cols || format('%s::text AS %I, ', coalesce(quote_ident(champ), 'NULL'), r.role);
  END LOOP;

  EXECUTE format(
    'CREATE VIEW sncf.%I AS SELECT row_number() OVER () AS id_import, %s %s AS geom, to_jsonb(t) - %L AS attributs FROM %I.%I t',
    p_vue, cols,
    CASE WHEN srid = 2154 THEN quote_ident(geomcol)
         WHEN srid IN (0, -1) OR srid IS NULL THEN 'ST_Transform(ST_SetSRID(' || quote_ident(geomcol) || ', 4326), 2154)'
         ELSE 'ST_Transform(' || quote_ident(geomcol) || ', 2154)' END,
    geomcol, sch, p_table);
  IF srid IS NULL OR srid IN (0, -1) THEN
    INSERT INTO sncf.controles (couche, type, detail)
    VALUES (p_couche, 'scr_suppose', p_table || ' : SRID absent, WGS84 (4326) supposé');
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 2. LIGNES
-- -----------------------------------------------------------------------------
DO $$ BEGIN PERFORM sncf._preparer('lignes', 'lignes', 'v_lignes'); END $$;

-- Une ligne par tronçon simple (les MultiLineString sont fusionnées si possible, sinon éclatées).
CREATE TABLE sncf.lignes AS
SELECT row_number() OVER (ORDER BY code_ligne, sncf.pk_vers_m(pkd), rg_troncon) AS id,
       code_ligne, lib_ligne, statut, rg_troncon, pkd, pkf,
       sncf.pk_vers_m(pkd) AS pkd_m, sncf.pk_vers_m(pkf) AS pkf_m,
       g.geom::geometry(LineString, 2154) AS geom, attributs
FROM sncf.v_lignes v,
     LATERAL ST_Dump(ST_LineMerge(ST_CollectionExtract(ST_MakeValid(v.geom), 2))) g
WHERE v.geom IS NOT NULL;
CREATE INDEX ON sncf.lignes USING gist (geom);

INSERT INTO sncf.controles (couche, id_objet, type, detail, geom)
SELECT 'lignes', id::text, 'pk_illisible', 'pkd = ' || coalesce(pkd, 'vide') || ', pkf = ' || coalesce(pkf, 'vide'), geom
FROM sncf.lignes WHERE pkd_m IS NULL OR pkf_m IS NULL;

INSERT INTO sncf.controles (couche, id_objet, type, detail, geom)
SELECT 'lignes', id::text, 'code_ligne_manquant', NULL, geom FROM sncf.lignes WHERE code_ligne IS NULL;

INSERT INTO sncf.controles (couche, id_objet, type, detail, geom)
SELECT 'lignes', id::text, 'ecart_pk_longueur',
       'ligne ' || code_ligne || ' de ' || pkd || ' à ' || pkf || ' : ' || round(abs(pkf_m - pkd_m)) ||
       ' m de PK pour ' || round(ST_Length(geom)::numeric) || ' m mesurés (saut de PK probable dans le tronçon)', geom
FROM sncf.lignes, sncf.parametres p
WHERE pkd_m IS NOT NULL AND pkf_m IS NOT NULL AND ST_Length(geom) > 0
  AND abs(abs(pkf_m - pkd_m) - ST_Length(geom)) / ST_Length(geom) > p.ecart_longueur_max;

-- -----------------------------------------------------------------------------
-- 3. ENTRÉES DU SKILL PK : axes, bornes aux extrémités des tronçons, sauts de PK
-- -----------------------------------------------------------------------------
-- Les géométries ne sont pas forcément numérisées dans le sens des PK. On place chaque
-- tronçon sur l'axe fusionné de sa ligne, et on donne le plus petit PK à l'extrémité
-- la plus en amont ; si l'axe fusionné est à l'envers, on inverse.
CREATE TABLE sncf.axe_fusionne AS
SELECT code_ligne, ST_LineMerge(ST_Collect(geom)) AS geom
FROM sncf.lignes WHERE code_ligne IS NOT NULL AND pkd_m IS NOT NULL AND pkf_m IS NOT NULL
GROUP BY code_ligne;

INSERT INTO sncf.controles (couche, id_objet, type, detail, geom)
SELECT 'lignes', code_ligne, 'axe_discontinu',
       'la ligne ' || code_ligne || ' reste en ' || ST_NumGeometries(geom) ||
       ' morceaux après fusion (trou ou embranchement) : à traiter avant le skill PK', geom
FROM sncf.axe_fusionne WHERE GeometryType(geom) <> 'LINESTRING';

CREATE TABLE sncf.troncons_orientes AS
WITH pos AS (
  SELECT l.id, l.code_ligne, l.geom,
         least(l.pkd_m, l.pkf_m) AS pk_min, greatest(l.pkd_m, l.pkf_m) AS pk_max,
         ST_LineLocatePoint(a.geom, ST_StartPoint(l.geom)) AS f1,
         ST_LineLocatePoint(a.geom, ST_EndPoint(l.geom)) AS f2
  FROM sncf.lignes l JOIN sncf.axe_fusionne a USING (code_ligne)
  WHERE GeometryType(a.geom) = 'LINESTRING'
),
sens AS (   -- +1 si le PK croît dans le sens de l'axe fusionné
  SELECT code_ligne,
         CASE WHEN (array_agg(pk_min ORDER BY least(f1, f2)))[1]
                   <= (array_agg(pk_min ORDER BY least(f1, f2) DESC))[1] THEN 1 ELSE -1 END AS s
  FROM pos GROUP BY code_ligne
)
SELECT p.id, p.code_ligne, p.pk_min, p.pk_max,
       CASE WHEN (p.f1 <= p.f2) = (s.s = 1) THEN ST_StartPoint(p.geom) ELSE ST_EndPoint(p.geom) END AS pt_min,
       CASE WHEN (p.f1 <= p.f2) = (s.s = 1) THEN ST_EndPoint(p.geom) ELSE ST_StartPoint(p.geom) END AS pt_max,
       CASE WHEN s.s = 1 THEN least(p.f1, p.f2) ELSE 1 - greatest(p.f1, p.f2) END AS rang_axe
FROM pos p JOIN sens s USING (code_ligne);

INSERT INTO sncf.controles (couche, id_objet, type, detail)
SELECT 'lignes', code_ligne, 'sens_suppose',
       'ligne ' || code_ligne || ' en un seul tronçon : PK supposés croissants dans le sens de numérisation, à vérifier avec une gare ou un PN'
FROM sncf.troncons_orientes GROUP BY code_ligne HAVING count(*) = 1;

-- Jonctions entre tronçons successifs : PK différent de part et d'autre = saut de PK.
CREATE TABLE sncf.jonctions AS
SELECT a.code_ligne, a.id AS id_amont, b.id AS id_aval, a.pk_max AS pk_amont_m, b.pk_min AS pk_aval_m,
       ST_Distance(a.pt_max, b.pt_min) AS ecart_m, a.pt_max AS geom
FROM sncf.troncons_orientes a
JOIN LATERAL (
  SELECT * FROM sncf.troncons_orientes b
  WHERE b.code_ligne = a.code_ligne AND b.rang_axe > a.rang_axe
  ORDER BY b.rang_axe LIMIT 1
) b ON true;

CREATE TABLE sncf.sauts_pk AS
SELECT j.code_ligne, sncf.m_vers_pk(j.pk_amont_m) AS pk_amont, sncf.m_vers_pk(j.pk_aval_m) AS pk_aval,
       j.geom::geometry(Point, 2154) AS geom
FROM sncf.jonctions j, sncf.parametres p
WHERE j.ecart_m <= p.tolerance_jonction AND abs(j.pk_aval_m - j.pk_amont_m) > p.ecart_pk_saut;

INSERT INTO sncf.controles (couche, id_objet, type, detail, geom)
SELECT 'lignes', j.code_ligne, CASE WHEN j.pk_aval_m > j.pk_amont_m THEN 'saut_pk_lacune' ELSE 'saut_pk_chevauchement' END,
       'ligne ' || j.code_ligne || ' : ' || sncf.m_vers_pk(j.pk_amont_m) || ' = ' || sncf.m_vers_pk(j.pk_aval_m), j.geom
FROM sncf.jonctions j, sncf.parametres p
WHERE j.ecart_m <= p.tolerance_jonction AND abs(j.pk_aval_m - j.pk_amont_m) > p.ecart_pk_saut;

-- Axes : un enregistrement par tronçon, comme attendu par le skill PK (colonne voie fixée à 'axe').
CREATE TABLE sncf.axes AS
SELECT id, code_ligne, 'axe'::text AS voie, geom FROM sncf.lignes
WHERE code_ligne IN (SELECT code_ligne FROM sncf.troncons_orientes);

-- Bornes : extrémités des tronçons, sauf au droit d'un saut (déjà porté par sncf.sauts_pk).
CREATE TABLE sncf.bornes_pk AS
SELECT DISTINCT ON (code_ligne, pk_m) code_ligne, sncf.m_vers_pk(pk_m) AS pk,
       geom::geometry(Point, 2154) AS geom, 'extremite_troncon'::text AS origine
FROM (
  SELECT code_ligne, pk_min AS pk_m, pt_min AS geom FROM sncf.troncons_orientes
  UNION ALL
  SELECT code_ligne, pk_max, pt_max FROM sncf.troncons_orientes
) e
WHERE NOT EXISTS (
  SELECT 1 FROM sncf.sauts_pk s, sncf.parametres p
  WHERE s.code_ligne = e.code_ligne AND ST_DWithin(s.geom, e.geom, p.tolerance_jonction)
)
ORDER BY code_ligne, pk_m;

-- -----------------------------------------------------------------------------
-- 4. OBJETS PONCTUELS : gares, passages à niveau, ouvrages d'art
-- -----------------------------------------------------------------------------
DO $$
DECLARE sch text; t text; n int := 0; req text := '';
BEGIN
  SELECT schema_brut INTO sch FROM sncf.parametres;

  IF to_regclass(sch || '.gares') IS NOT NULL THEN
    PERFORM sncf._preparer('gares', 'gares', 'v_gares');
    EXECUTE 'CREATE TABLE sncf.gares AS SELECT id_import AS id, code_uic, libelle, code_ligne, pk,
             sncf.pk_vers_m(pk) AS pk_m, voyageurs, fret, ST_PointOnSurface(geom)::geometry(Point, 2154) AS geom, attributs
             FROM sncf.v_gares';
  END IF;

  IF to_regclass(sch || '.passages_niveau') IS NOT NULL THEN
    PERFORM sncf._preparer('passages_niveau', 'passages_niveau', 'v_passages_niveau');
    EXECUTE 'CREATE TABLE sncf.passages_niveau AS SELECT id_import AS id, libelle, classe, code_ligne, pk,
             sncf.pk_vers_m(pk) AS pk_m, ST_PointOnSurface(geom)::geometry(Point, 2154) AS geom, attributs
             FROM sncf.v_passages_niveau';
  END IF;

  -- Toutes les tables sncf_brut.ouvrages_<type> sont réunies dans sncf.ouvrages.
  FOR t IN SELECT table_name FROM information_schema.tables
           WHERE table_schema = sch AND table_name LIKE 'ouvrages\_%' ORDER BY table_name LOOP
    n := n + 1;
    PERFORM sncf._preparer('ouvrages', t, 'v_' || t);
    req := req || CASE WHEN n > 1 THEN ' UNION ALL ' ELSE '' END ||
           format('SELECT %L::text AS type_ouvrage, libelle, code_ligne, pk, geom, attributs FROM sncf.%I',
                  substr(t, 10), 'v_' || t);
  END LOOP;
  IF n > 0 THEN
    EXECUTE 'CREATE TABLE sncf.ouvrages AS SELECT row_number() OVER (ORDER BY type_ouvrage, code_ligne, pk) AS id,
             type_ouvrage, libelle, code_ligne, pk, sncf.pk_vers_m(pk) AS pk_m,
             ST_PointOnSurface(geom)::geometry(Point, 2154) AS geom, attributs FROM (' || req || ') u';
  END IF;
END $$;

-- Contrôles communs aux objets ponctuels : PK lisible, distance à la ligne, PK dans l'intervalle de la ligne.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['gares', 'passages_niveau', 'ouvrages'] LOOP
    IF to_regclass('sncf.' || t) IS NULL THEN CONTINUE; END IF;
    EXECUTE format($q$
      INSERT INTO sncf.controles (couche, id_objet, type, detail, geom)
      SELECT %1$L, o.id::text, 'pk_illisible', 'PK « ' || o.pk || ' » : format km+m attendu', o.geom
      FROM sncf.%1$I o WHERE o.pk IS NOT NULL AND o.pk_m IS NULL;

      INSERT INTO sncf.controles (couche, id_objet, type, detail, geom)
      SELECT %1$L, o.id::text, 'loin_de_sa_ligne',
             coalesce(o.libelle, '') || ' à ' || round(d.dist::numeric, 1) || ' m de la ligne ' || o.code_ligne,
             o.geom
      FROM sncf.%1$I o
      CROSS JOIN sncf.parametres p
      JOIN LATERAL (SELECT min(ST_Distance(l.geom, o.geom)) AS dist FROM sncf.lignes l WHERE l.code_ligne = o.code_ligne) d ON true
      WHERE d.dist > p.distance_max_ligne;

      INSERT INTO sncf.controles (couche, id_objet, type, detail, geom)
      SELECT %1$L, o.id::text, 'ligne_inconnue', 'code ligne ' || o.code_ligne || ' absent de la couche des lignes', o.geom
      FROM sncf.%1$I o
      WHERE o.code_ligne IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sncf.lignes l WHERE l.code_ligne = o.code_ligne);

      INSERT INTO sncf.controles (couche, id_objet, type, detail, geom)
      SELECT %1$L, o.id::text, 'pk_hors_ligne',
             'PK ' || o.pk || ' hors de la ligne ' || o.code_ligne || ' (' || sncf.m_vers_pk(m.pk_min) || ' à ' || sncf.m_vers_pk(m.pk_max) || ')',
             o.geom
      FROM sncf.%1$I o
      JOIN (SELECT code_ligne, min(least(pkd_m, pkf_m)) AS pk_min, max(greatest(pkd_m, pkf_m)) AS pk_max
            FROM sncf.lignes GROUP BY code_ligne) m USING (code_ligne)
      WHERE o.pk_m NOT BETWEEN m.pk_min AND m.pk_max;
    $q$, t);
  END LOOP;
END $$;

CREATE VIEW sncf.resume AS
SELECT 'lignes' AS couche, count(*) AS nb FROM sncf.lignes
UNION ALL SELECT 'bornes_pk', count(*) FROM sncf.bornes_pk
UNION ALL SELECT 'sauts_pk', count(*) FROM sncf.sauts_pk
UNION ALL SELECT 'controles', count(*) FROM sncf.controles;

\echo '--- Champs utilisés'
SELECT couche, table_source, role, coalesce(champ, '(absent)') AS champ FROM sncf.champs_utilises ORDER BY 1, 2, 3;
\echo '--- Contrôles'
SELECT couche, id_objet, type, detail FROM sncf.controles ORDER BY id;
