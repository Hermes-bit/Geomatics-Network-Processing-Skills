-- Jeu de données d'exemple : chantier fictif de voirie et réseaux voisins, en Lambert 93 (EPSG:2154).
-- Coordonnées relatives à une origine fictive (X0 = 845000, Y0 = 6520000). Données inventées.
-- Pièges volontaires, détaillés dans resultats_attendus.md :
--   * un troisième polygone d'emprise est à 240 m des autres : il faudrait une autre déclaration ;
--   * une conduite de gaz de classe A passe à 0,4 m de l'emprise : dans sa zone d'incertitude ;
--   * un câble télécom n'a pas de classe de précision : traité comme classe C ;
--   * une ligne BT aérienne est à 2,5 m : dans le fuseau de 3 m ;
--   * un réseau de chaleur de classe B est à 1 m : investigations complémentaires à prévoir ;
--   * une conduite d'eau à 20 m ne doit PAS être retenue ;
--   * un ouvrage a une catégorie « autre » : sensibilité à vérifier.
--
-- Chargement : psql -d ma_base -f donnees_exemple.sql   (prérequis : CREATE EXTENSION postgis;)

SET client_min_messages = warning;
DROP SCHEMA IF EXISTS dtdict_exemple CASCADE;
CREATE SCHEMA dtdict_exemple;

CREATE FUNCTION dtdict_exemple._g(wkt text) RETURNS geometry LANGUAGE sql AS $$
  SELECT ST_Translate(ST_GeomFromText(wkt, 2154), 845000, 6520000)
$$;

CREATE TABLE dtdict_exemple.emprise (
  id integer PRIMARY KEY, nom text, travaux_urgents boolean, geom geometry(Polygon, 2154)
);
INSERT INTO dtdict_exemple.emprise VALUES
  (1, 'Tranchée rue des Lilas',   false, dtdict_exemple._g('POLYGON((0 0, 100 0, 100 40, 0 40, 0 0))')),
  (2, 'Fosse de raccordement',    false, dtdict_exemple._g('POLYGON((130 0, 160 0, 160 20, 130 20, 130 0))')),
  (3, 'Massif de candélabre',     false, dtdict_exemple._g('POLYGON((400 0, 420 0, 420 20, 400 20, 400 0))'));

CREATE TABLE dtdict_exemple.ouvrages (
  id integer PRIMARY KEY, exploitant text, categorie text, pose text,
  classe_precision text, flexible boolean, branchement boolean, tension_kv numeric,
  geom geometry(LineString, 2154)
);
INSERT INTO dtdict_exemple.ouvrages VALUES
  (1, 'Enedis',               'electricite',    'souterrain', 'B',  true,  false, 20,   dtdict_exemple._g('LINESTRING(50 -20, 50 60)')),
  (2, 'GRDF',                 'gaz',            'souterrain', 'A',  true,  false, NULL, dtdict_exemple._g('LINESTRING(0 -0.4, 100 -0.4)')),
  (3, 'Orange',               'telecom',        'souterrain', NULL, true,  false, NULL, dtdict_exemple._g('LINESTRING(0 43, 100 43)')),
  (4, 'Enedis',               'electricite',    'aerien',     'B',  true,  false, 0.4,  dtdict_exemple._g('LINESTRING(-20 -2.5, 120 -2.5)')),
  (5, 'RTE',                  'electricite',    'aerien',     'A',  true,  false, 63,   dtdict_exemple._g('LINESTRING(-50 44.5, 200 44.5)')),
  (6, 'Régie des eaux',       'eau',            'souterrain', 'A',  false, false, NULL, dtdict_exemple._g('LINESTRING(0 60, 100 60)')),
  (7, 'Métropole',            'assainissement', 'souterrain', 'B',  false, false, NULL, dtdict_exemple._g('LINESTRING(165 -10, 165 30)')),
  (8, 'Chaleur Urbaine',      'chaleur',        'souterrain', 'B',  false, false, NULL, dtdict_exemple._g('LINESTRING(161 -10, 161 30)')),
  (9, 'Syndicat intercommunal','autre',         'souterrain', 'C',  true,  false, NULL, dtdict_exemple._g('LINESTRING(135 5, 155 5)'));

CREATE TABLE dtdict_exemple.exploitants (exploitant text PRIMARY KEY, contact text, telephone_urgence text);
INSERT INTO dtdict_exemple.exploitants VALUES
  ('Enedis', 'Agence travaux fictive', '00 00 00 00 01'),
  ('GRDF',   'Service DT-DICT fictif', '00 00 00 00 02'),
  ('RTE',    'Groupe maintenance fictif', '00 00 00 00 03');
