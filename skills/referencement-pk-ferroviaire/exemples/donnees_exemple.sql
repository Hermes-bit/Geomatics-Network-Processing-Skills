-- Jeu de données d'exemple : ligne ferroviaire fictive 830000, voie V1, en Lambert 93 (EPSG:2154).
-- PK de 10+000 à environ 20+214. Particularités volontaires :
--   * l'axe est numérisé en deux morceaux, le second dans le mauvais sens ;
--   * une autre ligne (831000) est dans la même table et ne doit pas être mélangée ;
--   * les bornes kilométriques sont relevées à 2-4 m de l'axe, avec ±1,5 m d'imprécision ;
--   * un saut de PK (lacune) : le PK 15+400 est suivi immédiatement du PK 15+650,
--     donc le kilomètre 15 ne mesure que 750 m sur le terrain.
--
-- Chargement : psql -d ma_base -f donnees_exemple.sql   (prérequis : CREATE EXTENSION postgis;)

DROP SCHEMA IF EXISTS ferro_exemple CASCADE;
CREATE SCHEMA ferro_exemple;

CREATE TABLE ferro_exemple.axes (
  id          integer PRIMARY KEY,
  code_ligne  text,
  voie        text,
  geom        geometry(LineString, 2154)
);

CREATE TABLE ferro_exemple.bornes_pk (
  code_ligne  text,
  pk          text,          -- format km+m
  geom        geometry(Point, 2154)
);

-- Sauts de PK : au point geom, le PK passe de pk_amont à pk_aval.
CREATE TABLE ferro_exemple.sauts_pk (
  code_ligne  text,
  pk_amont    text,
  pk_aval     text,
  geom        geometry(Point, 2154)
);

INSERT INTO ferro_exemple.axes VALUES
  (1, '830000', 'V1', ST_GeomFromText('LINESTRING(800000.00 6500000.00, 802000.00 6500300.00, 804000.00 6499800.00)', 2154)),
  (2, '830000', 'V1', ST_GeomFromText('LINESTRING(809500.00 6500800.00, 808000.00 6500000.00, 806000.00 6500500.00, 804000.00 6499800.00)', 2154)),  -- numérisé à l'envers
  (3, '831000', 'V1', ST_GeomFromText('LINESTRING(804000 6499800, 804500 6497500)', 2154));  -- autre ligne (embranchement)

INSERT INTO ferro_exemple.bornes_pk VALUES
  ('830000', '10+000', ST_SetSRID(ST_MakePoint(799999.63, 6499997.17), 2154)),
  ('830000', '11+000', ST_SetSRID(ST_MakePoint(800989.72, 6500145.21), 2154)),
  ('830000', '12+000', ST_SetSRID(ST_MakePoint(801978.71, 6500299.35), 2154)),
  ('830000', '13+000', ST_SetSRID(ST_MakePoint(802948.41, 6500066.07), 2154)),
  ('830000', '14+000', ST_SetSRID(ST_MakePoint(803919.52, 6499823.50), 2154)),
  ('830000', '15+000', ST_SetSRID(ST_MakePoint(804864.89, 6500098.75), 2154)),
  ('830000', '16+000', ST_SetSRID(ST_MakePoint(805573.71, 6500347.26), 2154)),
  ('830000', '17+000', ST_SetSRID(ST_MakePoint(806528.87, 6500365.10), 2154)),
  ('830000', '18+000', ST_SetSRID(ST_MakePoint(807500.27, 6500127.97), 2154)),
  ('830000', '19+000', ST_SetSRID(ST_MakePoint(808427.40, 6500231.83), 2154)),
  ('830000', '20+000', ST_SetSRID(ST_MakePoint(809310.27, 6500702.73), 2154));

INSERT INTO ferro_exemple.sauts_pk VALUES
  ('830000', '15+400', '15+650', ST_SetSRID(ST_MakePoint(805242.19, 6500234.77), 2154));
