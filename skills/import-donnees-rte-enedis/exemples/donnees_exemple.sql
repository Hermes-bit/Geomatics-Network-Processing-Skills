-- Jeu de données d'exemple : extraits FICTIFS au format des exports ouverts de RTE (ODRÉ)
-- et des gestionnaires de distribution (Enedis, Agence ORE), tels que les charge ogr2ogr
-- depuis les GeoJSON (WGS84, EPSG:4326) dans le schéma elec_brut.
-- Géométries écrites en Lambert 93 (origine fictive X0 = 850000, Y0 = 6550000) puis converties en WGS84.
-- Pièges volontaires, détaillés dans resultats_attendus.md :
--   * tensions en texte : « 63kV », « 225 kV », « HORS TENSION », « HTA », « BT » ;
--   * pose écrite « Aérien », « Souterrain », « aérien » ;
--   * une ligne HTA coupée en deux à la limite de commune (deux codes INSEE) ;
--   * une ligne RTE hors tension ;
--   * un câble HTA souterrain qui s'arrête à 0,6 m du câble voisin (quasi-connexion) ;
--   * un poste HTA/BT publié deux fois ;
--   * une ligne sans tension.
--
-- Chargement : psql -d ma_base -f donnees_exemple.sql   (prérequis : CREATE EXTENSION postgis;)

SET client_min_messages = warning;
DROP SCHEMA IF EXISTS elec_brut CASCADE;
CREATE SCHEMA elec_brut;

CREATE FUNCTION elec_brut._w(wkt text) RETURNS geometry LANGUAGE sql AS $$
  SELECT ST_Transform(ST_Translate(ST_GeomFromText(wkt, 2154), 850000, 6550000), 4326)
$$;

-- RTE (ODRÉ) : lignes aériennes et liaisons souterraines
CREATE TABLE elec_brut.lignes_rte_aeriennes (
  ogc_fid serial PRIMARY KEY, code_ligne varchar, nom_ligne varchar, etat varchar, tension varchar,
  geom geometry(MultiLineString, 4326)
);
INSERT INTO elec_brut.lignes_rte_aeriennes (code_ligne, nom_ligne, etat, tension, geom) VALUES
  ('VALMOL61RIVIE', 'Ligne 63 kV Valmont - Rivière', 'EN EXPLOITATION', '63kV',
     elec_brut._w('MULTILINESTRING((-3000 0, -1500 200, 0 0))')),
  ('VALMOL71NORD',  'Ligne 225 kV Valmont - Nord',   'EN EXPLOITATION', '225 kV',
     elec_brut._w('MULTILINESTRING((-3000 0, -3000 4000))')),
  ('VALMOL62ANC',   'Ancienne ligne 63 kV',          'HORS TENSION',    'HORS TENSION',
     elec_brut._w('MULTILINESTRING((-3000 0, -5000 -1000))'));

CREATE TABLE elec_brut.lignes_rte_souterraines (
  ogc_fid serial PRIMARY KEY, code_ligne varchar, nom_ligne varchar, etat varchar, tension varchar,
  geom geometry(MultiLineString, 4326)
);
INSERT INTO elec_brut.lignes_rte_souterraines (code_ligne, nom_ligne, etat, tension, geom) VALUES
  ('RIVIEL61SUD', 'Liaison 63 kV Rivière - Sud', 'EN EXPLOITATION', '63kV',
     elec_brut._w('MULTILINESTRING((0 0, 0 -1500))'));

CREATE TABLE elec_brut.postes_rte (
  ogc_fid serial PRIMARY KEY, code_poste varchar, nom_poste varchar, fonction varchar, etat varchar, tension varchar,
  geom geometry(Point, 4326)
);
INSERT INTO elec_brut.postes_rte (code_poste, nom_poste, fonction, etat, tension, geom) VALUES
  ('VALMO', 'Valmont', 'POSTE DE TRANSFORMATION', 'EN EXPLOITATION', '225kV', elec_brut._w('POINT(-3000 0)')),
  ('NORD',  'Nord',    'POSTE DE TRANSFORMATION', 'EN EXPLOITATION', '225kV', elec_brut._w('POINT(-3000 4000)')),
  ('SUD',   'Sud',     'POSTE DE TRANSFORMATION', 'EN EXPLOITATION', '63kV',  elec_brut._w('POINT(0 -1500)')),
  ('ANCIE', 'Ancien',  'POSTE DE TRANSFORMATION', 'HORS TENSION',    '63kV',  elec_brut._w('POINT(-5000 -1000)'));

-- Distribution (format Agence ORE / Enedis) : position, tension, nom_grd, code_insee
CREATE TABLE elec_brut.lignes_hta_aeriennes (
  ogc_fid serial PRIMARY KEY, position varchar, tension varchar, nom_grd varchar, code_insee varchar,
  commune varchar, geom geometry(MultiLineString, 4326)
);
INSERT INTO elec_brut.lignes_hta_aeriennes (position, tension, nom_grd, code_insee, commune, geom) VALUES
  ('Aérien', 'HTA', 'Enedis', '99001', 'Rivière',   elec_brut._w('MULTILINESTRING((0 0, 500 0))')),
  ('Aérien', 'HTA', 'Enedis', '99002', 'Bellevue',  elec_brut._w('MULTILINESTRING((500 0, 1000 0))')),   -- coupée à la limite de commune
  ('Aérien', 'HTA', 'Enedis', '99002', 'Bellevue',  elec_brut._w('MULTILINESTRING((1000 0, 1000 800))')),
  ('Aérien', NULL,  'Enedis', '99002', 'Bellevue',  elec_brut._w('MULTILINESTRING((1000 800, 1000 1300))'));  -- tension vide

CREATE TABLE elec_brut.lignes_hta_souterraines (
  ogc_fid serial PRIMARY KEY, position varchar, tension varchar, nom_grd varchar, code_insee varchar,
  commune varchar, geom geometry(MultiLineString, 4326)
);
INSERT INTO elec_brut.lignes_hta_souterraines (position, tension, nom_grd, code_insee, commune, geom) VALUES
  ('Souterrain', 'HTA', 'Enedis', '99002', 'Bellevue', elec_brut._w('MULTILINESTRING((1000 0, 2000 0))')),
  ('Souterrain', 'HTA', 'Enedis', '99002', 'Bellevue', elec_brut._w('MULTILINESTRING((2000.6 0, 2000.6 600))'));  -- 0,6 m du câble voisin

CREATE TABLE elec_brut.lignes_bt_aeriennes (
  ogc_fid serial PRIMARY KEY, position varchar, tension varchar, nom_grd varchar, code_insee varchar,
  geom geometry(MultiLineString, 4326)
);
INSERT INTO elec_brut.lignes_bt_aeriennes (position, tension, nom_grd, code_insee, geom) VALUES
  ('aérien', 'BT', 'Enedis', '99002', elec_brut._w('MULTILINESTRING((1000 800, 1200 800))'));

CREATE TABLE elec_brut.postes_source (
  ogc_fid serial PRIMARY KEY, nom_grd varchar, code_insee varchar, geom geometry(Point, 4326)
);
INSERT INTO elec_brut.postes_source (nom_grd, code_insee, geom) VALUES
  ('Enedis', '99001', elec_brut._w('POINT(0 0)'));

CREATE TABLE elec_brut.postes_hta_bt (
  ogc_fid serial PRIMARY KEY, nom_grd varchar, code_insee varchar, geom geometry(Point, 4326)
);
INSERT INTO elec_brut.postes_hta_bt (nom_grd, code_insee, geom) VALUES
  ('Enedis', '99002', elec_brut._w('POINT(1000 800)')),
  ('Enedis', '99002', elec_brut._w('POINT(2000 0)')),
  ('Enedis', '99002', elec_brut._w('POINT(2000.6 600)')),
  ('Enedis', '99002', elec_brut._w('POINT(2000.3 0.2)'));   -- même poste publié deux fois
