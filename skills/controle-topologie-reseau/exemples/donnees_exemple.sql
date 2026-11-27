-- Jeu de données d'exemple : petit réseau HTA 20 kV fictif, en Lambert 93 (EPSG:2154).
-- Les coordonnées sont relatives à une origine fictive près de Lyon (X0 = 842000, Y0 = 6519000).
-- Il contient des anomalies VOLONTAIRES, listées dans resultats_attendus.md.
--
-- Chargement : psql -d ma_base -f donnees_exemple.sql
-- Prérequis : CREATE EXTENSION postgis; CREATE EXTENSION pgrouting;

DROP SCHEMA IF EXISTS reseau_exemple CASCADE;
CREATE SCHEMA reseau_exemple;

-- Tronçons : MultiLineString comme après un import de shapefile.
-- pose : 'aerien' ou 'souterrain' (un aérien qui croise un souterrain est un franchissement normal).
-- etat_exploitation : 'NF' (normalement fermé) ou 'NO' (point d'ouverture du réseau radial).
CREATE TABLE reseau_exemple.troncons (
  id                 integer PRIMARY KEY,
  code_depart        text,
  tension_kv         numeric,
  pose               text,
  etat_exploitation  text,
  geom               geometry(MultiLineString, 2154)
);

CREATE TABLE reseau_exemple.postes (
  id     integer PRIMARY KEY,
  nom    text,
  type   text,
  geom   geometry(Point, 2154)
);

-- Fonction utilitaire locale pour écrire les coordonnées relatives
CREATE FUNCTION reseau_exemple._l(wkt text) RETURNS geometry LANGUAGE sql AS $$
  SELECT ST_Translate(ST_Multi(ST_GeomFromText(wkt, 2154)), 842000, 6519000)
$$;
CREATE FUNCTION reseau_exemple._p(x float, y float) RETURNS geometry LANGUAGE sql AS $$
  SELECT ST_SetSRID(ST_MakePoint(842000 + x, 6519000 + y), 2154)
$$;

INSERT INTO reseau_exemple.postes VALUES
  (1, 'Poste source Les Brotteaux', 'poste_source', reseau_exemple._p(0, 0)),
  (3, 'Poste HTA/BT Moulin',        'poste_hta_bt', reseau_exemple._p(0, 500)),
  (4, 'Poste HTA/BT Gare',          'poste_hta_bt', reseau_exemple._p(2000, 0)),
  (5, 'Poste HTA/BT Pré Sud',       'poste_hta_bt', reseau_exemple._p(1200, -300)),
  (6, 'Poste HTA/BT Pré Nord',      'poste_hta_bt', reseau_exemple._p(1200, 300)),
  (7, 'Poste HTA/BT Écoles',        'poste_hta_bt', reseau_exemple._p(700, 300)),
  (8, 'Poste HTA/BT Les Saules',    'poste_hta_bt', reseau_exemple._p(2500, 1500));   -- ANOMALIE : poste isolé

INSERT INTO reseau_exemple.troncons VALUES
  -- Boucle A-B-C-D ouverte par T4 (NO) : normal en exploitation radiale
  (1,  'DEP-01', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(0 0, 500 0)')),
  (2,  'DEP-01', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(500 0, 1000 0)')),
  (3,  'DEP-01', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(1000 0, 1000 500)')),
  (4,  'DEP-01', 20, 'aerien',     'NO', reseau_exemple._l('LINESTRING(1000 500, 500 500)')),
  (5,  'DEP-01', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(500 500, 500 0)')),
  -- Boucle B-E-F-C entièrement fermée : ANOMALIE boucle en exploitation radiale
  (6,  'DEP-01', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(1000 0, 1500 0)')),
  -- T7 en deux morceaux contigus : à fusionner avec ST_LineMerge
  (7,  'DEP-01', 20, 'aerien',     'NF', reseau_exemple._l('MULTILINESTRING((1500 0, 1500 250),(1500 250, 1500 500))')),
  (8,  'DEP-01', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(1500 500, 1000.3 500)')),
  (15, 'DEP-01', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(1000.3 500, 1000 500)')),   -- ANOMALIE : tronçon de 0,3 m
  -- ANOMALIE : extrémité pendante + tension non normalisée (21 kV)
  (9,  'DEP-01', 21, 'aerien',     'NF', reseau_exemple._l('LINESTRING(500 500, 500 900)')),
  -- ANOMALIE attribut : tension manquante (l'extrémité est bien sur le poste 3)
  (10, 'DEP-01', NULL, 'souterrain','NF', reseau_exemple._l('LINESTRING(500 500, 0 500)')),
  -- ANOMALIE : quasi-connexion, démarre à 0,6 m du nœud E (1500 0)
  (11, 'DEP-02', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(1500.6 0, 2000 0)')),
  -- ANOMALIE : croise T6 en (1200 0) sans nœud, même pose (aérien / aérien)
  (12, 'DEP-02', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(1200 -300, 1200 300)')),
  -- PIÈGE (pas une anomalie) : souterrain qui passe sous T2 en (700 0), franchissement normal
  (13, 'DEP-01', 20, 'souterrain', 'NF', reseau_exemple._l('LINESTRING(0 0, 0 -300, 700 -300, 700 300)')),
  -- ANOMALIE : composante isolée, loin de tout
  (14, 'DEP-03', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(3000 3000, 3200 3000)')),
  -- ANOMALIE : doublon géométrique exact de T3
  (16, 'DEP-01', 20, 'aerien',     'NF', reseau_exemple._l('LINESTRING(1000 0, 1000 500)'));

DROP FUNCTION reseau_exemple._l(text);
DROP FUNCTION reseau_exemple._p(float, float);

CREATE INDEX ON reseau_exemple.troncons USING gist (geom);
CREATE INDEX ON reseau_exemple.postes USING gist (geom);
