-- Jeu de données d'exemple : chantier fictif de raccordement HTA avec traversée de la ligne
-- ferroviaire fictive 830000 par fonçage, en Lambert 93 (EPSG:2154). Données inventées.
--
-- La voie est celle du jeu d'exemple du skill referencement-pk-ferroviaire (schéma ferro_exemple,
-- chargé par ../referencement-pk-ferroviaire/exemples/donnees_exemple.sql). Les géométries sont
-- saisies dans un repère local (s, d) : s le long de la voie dans le sens des PK croissants,
-- d à gauche de la voie, avec l'origine sur le saut de PK 15+400 = 15+650 (805242.19, 6500234.77).
--
-- Pièges volontaires, détaillés dans resultats_attendus.md :
--   * la zone de stockage est à 60 m de la tranchée : l'emprise ne fait pas une seule déclaration ;
--   * le fonçage passe sous la voie, et la section concernée contient le saut de PK ;
--   * la ligne RTE 63 kV et la caténaire 25 kV surplombent l'emprise (voisinage électrique) ;
--   * le câble de signalisation SNCF est en classe C : investigations complémentaires ;
--   * une parcelle ne touche l'emprise que sur 1,2 m² : imprécision probable du cadastre ;
--   * la conduite d'eau à 54 m et la parcelle à 44 m ne doivent PAS être retenues.
--
-- Chargement : psql -d ma_base -f donnees_exemple.sql   (prérequis : CREATE EXTENSION postgis;)

SET client_min_messages = warning;
DROP SCHEMA IF EXISTS impact_exemple CASCADE;
CREATE SCHEMA impact_exemple;

-- Repère local (s, d) -> Lambert 93 : rotation sur la direction de la voie (2000, 700).
CREATE FUNCTION impact_exemple._g(wkt text) RETURNS geometry LANGUAGE sql IMMUTABLE AS $$
  SELECT ST_Affine(ST_GeomFromText(wkt, 2154),
                   2000 / sqrt(4490000.0), -700 / sqrt(4490000.0),
                   700 / sqrt(4490000.0), 2000 / sqrt(4490000.0),
                   805242.19, 6500234.77)
$$;

-- Emprise des travaux : six polygones d'une même déclaration envisagée.
CREATE TABLE impact_exemple.emprise (
  id integer PRIMARY KEY, nom text, travaux_urgents boolean, geom geometry(Polygon, 2154)
);
INSERT INTO impact_exemple.emprise VALUES
  (1, 'Tranchée HTA côté sud',       false, impact_exemple._g('POLYGON((-120 -16, 20 -16, 20 -12, -120 -12, -120 -16))')),
  (2, 'Puits de fonçage sud',        false, impact_exemple._g('POLYGON((20 -16, 30 -16, 30 -6, 20 -6, 20 -16))')),
  (3, 'Fonçage sous la voie',        false, impact_exemple._g('POLYGON((24 -6, 26 -6, 26 6, 24 6, 24 -6))')),
  (4, 'Puits de fonçage nord',       false, impact_exemple._g('POLYGON((20 6, 30 6, 30 14, 20 14, 20 6))')),
  (5, 'Tranchée HTA côté nord',      false, impact_exemple._g('POLYGON((25 14, 29 14, 29 58.3, 25 58.3, 25 14))')),
  (6, 'Zone de stockage des engins', false, impact_exemple._g('POLYGON((-200 -45, -180 -45, -180 -25, -200 -25, -200 -45))'));

-- Ouvrages : mêmes colonnes que le skill proximite-dt-dict.
CREATE TABLE impact_exemple.ouvrages (
  id integer PRIMARY KEY, exploitant text, categorie text, pose text,
  classe_precision text, flexible boolean, branchement boolean, tension_kv numeric,
  geom geometry(LineString, 2154)
);
INSERT INTO impact_exemple.ouvrages VALUES
  (1, 'Enedis',      'electricite', 'souterrain', 'B',  true,  false, 20,   impact_exemple._g('LINESTRING(-118 -14, -118 -60)')),
  (2, 'GRDF',        'gaz',         'souterrain', 'A',  true,  false, NULL, impact_exemple._g('LINESTRING(-150 -16.3, 40 -16.3)')),
  (3, 'Orange',      'telecom',     'souterrain', NULL, true,  false, NULL, impact_exemple._g('LINESTRING(-60 -30, -60 0)')),
  (4, 'RTE',         'electricite', 'aerien',     'B',  true,  false, 63,   impact_exemple._g('LINESTRING(-80 -100, -40 100)')),
  (5, 'SNCF Réseau', 'ferroviaire', 'aerien',     'A',  true,  false, 25,   impact_exemple._g('LINESTRING(-300 0, 300 0)')),
  (6, 'SNCF Réseau', 'ferroviaire', 'souterrain', 'C',  true,  false, NULL, impact_exemple._g('LINESTRING(-300 -4, 300 -4)')),
  (7, 'Régie des eaux', 'eau',      'souterrain', 'A',  false, false, NULL, impact_exemple._g('LINESTRING(-150 -70, 40 -70)'));

CREATE TABLE impact_exemple.exploitants (exploitant text PRIMARY KEY, contact text, telephone_urgence text);
INSERT INTO impact_exemple.exploitants VALUES
  ('Enedis',      'Agence travaux fictive',          '00 00 00 00 01'),
  ('GRDF',        'Service DT-DICT fictif',          '00 00 00 00 02'),
  ('RTE',         'Groupe maintenance fictif',       '00 00 00 00 03'),
  ('SNCF Réseau', 'Infrapôle fictif, pôle travaux',  '00 00 00 00 04');

-- Parcelles cadastrales, au format du cadastre Etalab (cadastre.data.gouv.fr).
CREATE TABLE impact_exemple.parcelles (
  id text PRIMARY KEY, commune text, prefixe text, section text, numero text, contenance integer,
  geom geometry(Polygon, 2154)
);
INSERT INTO impact_exemple.parcelles VALUES
  ('99001000AB0101', '99001', '000', 'AB', '0101', NULL, impact_exemple._g('POLYGON((-400 -10, 400 -10, 400 10, -400 10, -400 -10))')),
  ('99001000AB0102', '99001', '000', 'AB', '0102', NULL, impact_exemple._g('POLYGON((-400 -60, -150 -60, -150 -10, -400 -10, -400 -60))')),
  ('99001000AB0103', '99001', '000', 'AB', '0103', NULL, impact_exemple._g('POLYGON((-150 -60, -50 -60, -50 -10, -150 -10, -150 -60))')),
  ('99001000AB0104', '99001', '000', 'AB', '0104', NULL, impact_exemple._g('POLYGON((-50 -60, 45 -60, 45 -10, -50 -10, -50 -60))')),
  ('99001000AB0105', '99001', '000', 'AB', '0105', NULL, impact_exemple._g('POLYGON((45 -60, 400 -60, 400 -10, 45 -10, 45 -60))')),
  ('99001000AC0201', '99001', '000', 'AC', '0201', NULL, impact_exemple._g('POLYGON((-400 10, -10 10, -10 80, -400 80, -400 10))')),
  ('99001000AC0202', '99001', '000', 'AC', '0202', NULL, impact_exemple._g('POLYGON((-10 10, 100 10, 100 58, -10 58, -10 10))')),
  ('99001000AC0203', '99001', '000', 'AC', '0203', NULL, impact_exemple._g('POLYGON((-10 58, 100 58, 100 120, -10 120, -10 58))')),
  ('99001000AC0204', '99001', '000', 'AC', '0204', NULL, impact_exemple._g('POLYGON((100 10, 400 10, 400 80, 100 80, 100 10))')),
  ('99001000AB0106', '99001', '000', 'AB', '0106', NULL, impact_exemple._g('POLYGON((-150 -120, 45 -120, 45 -60, -150 -60, -150 -120))'));
UPDATE impact_exemple.parcelles SET contenance = round(ST_Area(geom));

-- Propriétaires personnes morales (fichier DGFiP des parcelles des personnes morales).
-- Les propriétaires personnes physiques ne sont pas publiés.
CREATE TABLE impact_exemple.proprietaires_pm (id_parcelle text, proprietaire text);
INSERT INTO impact_exemple.proprietaires_pm VALUES
  ('99001000AB0101', 'SNCF RESEAU'),
  ('99001000AB0104', 'COMMUNE DE VILLE-EXEMPLE'),
  ('99001000AC0202', 'SCI DES SAULES');

-- Tronçons de végétation : chargés par exemples/chainer_exemple.sh à partir du résultat du skill
-- vegetation-lidar-hd (troncons_vegetation.geojson) lancé sur le nuage fictif de generer_nuage_exemple.py.
CREATE TABLE impact_exemple.vegetation (
  id_ligne text, type text, nom text, troncon integer, cote text, hauteur_max_m float,
  distance_min_m float, marge_chute_min_m float, priorite text, geom geometry(LineString, 2154)
);
