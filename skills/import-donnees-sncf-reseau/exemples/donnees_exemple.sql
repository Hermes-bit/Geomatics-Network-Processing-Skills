-- Jeu de données d'exemple : extraits FICTIFS au format des exports de ressources.data.sncf.com,
-- tels que les charge ogr2ogr depuis les GeoJSON (WGS84, EPSG:4326) dans le schéma sncf_brut.
-- Les géométries sont écrites en Lambert 93 puis converties en WGS84, comme dans les vrais fichiers.
--
-- Ligne fictive 999000, de 0+000 à 7+600, en trois tronçons. Pièges volontaires :
--   * le tronçon 2 est numérisé à l'envers (du PK le plus fort vers le plus faible) ;
--   * saut de PK à la jonction des tronçons 1 et 2 : 4+000 = 4+250 (lacune de 250 m) ;
--   * le tronçon 3 est une MultiLineString en deux parties contiguës ;
--   * une seconde ligne 999100 (un seul tronçon) part de la gare de Valbonne ;
--   * un passage à niveau a un PK illisible, un autre est à 45 m de sa ligne ;
--   * une passerelle porte un PK hors de la ligne ;
--   * une gare porte le code d'une ligne absente de la couche.
--
-- Chargement : psql -d ma_base -f donnees_exemple.sql   (prérequis : CREATE EXTENSION postgis;)

SET client_min_messages = warning;
DROP SCHEMA IF EXISTS sncf_brut CASCADE;
CREATE SCHEMA sncf_brut;

CREATE FUNCTION sncf_brut._w(wkt text) RETURNS geometry LANGUAGE sql AS $$
  SELECT ST_Transform(ST_GeomFromText(wkt, 2154), 4326)
$$;

-- formes-des-lignes-du-rfn
CREATE TABLE sncf_brut.lignes (
  ogc_fid serial PRIMARY KEY, code_ligne varchar, lib_ligne varchar, statut varchar,
  rg_troncon integer, pkd varchar, pkf varchar, geom geometry(Geometry, 4326)
);
INSERT INTO sncf_brut.lignes (code_ligne, lib_ligne, statut, rg_troncon, pkd, pkf, geom) VALUES
  ('999000', 'Ligne de Valbonne à Montreuil-sur-Rail', 'Exploitée', 1, '000+000', '004+000',
     sncf_brut._w('LINESTRING(800000 6600000, 802000 6600100, 804000 6600000)')),
  ('999000', 'Ligne de Valbonne à Montreuil-sur-Rail', 'Exploitée', 2, '004+250', '006+290',
     sncf_brut._w('LINESTRING(806000 6600400, 804000 6600000)')),                         -- à l'envers
  ('999000', 'Ligne de Valbonne à Montreuil-sur-Rail', 'Exploitée', 3, '006+290', '007+600',
     sncf_brut._w('MULTILINESTRING((806000 6600400, 806700 6600400), (806700 6600400, 807310 6600400))')),
  ('999100', 'Raccordement de Valbonne', 'Exploitée', 1, '000+000', '001+500',
     sncf_brut._w('LINESTRING(802000 6600100, 802300 6601570)'));

-- liste-des-gares
CREATE TABLE sncf_brut.gares (
  ogc_fid serial PRIMARY KEY, code_uic varchar, libelle varchar, fret varchar, voyageurs varchar,
  code_ligne varchar, rg_troncon integer, pk varchar, geom geometry(Point, 4326)
);
INSERT INTO sncf_brut.gares (code_uic, libelle, fret, voyageurs, code_ligne, rg_troncon, pk, geom) VALUES
  ('87999001', 'Valbonne',              'O', 'O', '999000', 1, '002+002', sncf_brut._w('POINT(802000 6600100)')),
  ('87999002', 'Montreuil-sur-Rail',    'N', 'O', '999000', 3, '007+600', sncf_brut._w('POINT(807310 6600400)')),
  ('87999003', 'Halte des Peupliers',   'N', 'O', '998000', 1, '012+300', sncf_brut._w('POINT(805000 6598000)'));  -- ligne absente

-- liste-des-passages-a-niveau
CREATE TABLE sncf_brut.passages_niveau (
  ogc_fid serial PRIMARY KEY, code_ligne varchar, rg_troncon integer, pk varchar, libelle varchar,
  classe varchar, geom geometry(Point, 4326)
);
INSERT INTO sncf_brut.passages_niveau (code_ligne, rg_troncon, pk, libelle, classe, geom) VALUES
  ('999000', 1, '001+001', 'PN 1',  '11', sncf_brut._w('POINT(801000 6600050)')),
  ('999000', 2, 'PK 5,4',  'PN 2',  '11', sncf_brut._w('POINT(805150 6600230)')),   -- PK illisible
  ('999000', 3, '006+990', 'PN 3',  '21', sncf_brut._w('POINT(806700 6600445)')),   -- à 45 m de la ligne
  ('999100', 1, '000+800', 'PN 11', '0',  sncf_brut._w('POINT(802160 6600884)'));

-- liste-des-passerelles et liste-des-ponts-route : une table par fichier, préfixe ouvrages_
CREATE TABLE sncf_brut.ouvrages_passerelles (
  ogc_fid serial PRIMARY KEY, code_ligne varchar, pk varchar, libelle varchar, geom geometry(Point, 4326)
);
INSERT INTO sncf_brut.ouvrages_passerelles (code_ligne, pk, libelle, geom) VALUES
  ('999000', '003+200', 'Passerelle du Moulin', sncf_brut._w('POINT(803200 6600040)')),
  ('999000', '009+100', 'Passerelle des Écoles', sncf_brut._w('POINT(807300 6600400)'));  -- PK hors ligne

CREATE TABLE sncf_brut.ouvrages_ponts_route (
  ogc_fid serial PRIMARY KEY, code_ligne varchar, pk varchar, libelle varchar, geom geometry(Point, 4326)
);
INSERT INTO sncf_brut.ouvrages_ponts_route (code_ligne, pk, libelle, geom) VALUES
  ('999000', '005+300', 'Pont de la D 12', sncf_brut._w('POINT(805020 6600204)'));
