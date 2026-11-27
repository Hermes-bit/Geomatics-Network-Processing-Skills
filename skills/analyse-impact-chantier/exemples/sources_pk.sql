-- Section 0 du script ../referencement-pk-ferroviaire/scripts/referencement_pk.sql pour le chantier d'exemple.
-- Utilisée par scripts/chainer_postgis.py --pk. La voie est celle du jeu d'exemple du skill PK (schéma ferro_exemple).
CREATE TABLE pk_ref.parametres AS SELECT
  '830000'::text AS code_ligne,
  20.0::float    AS distance_max_axe,     -- m : au-delà, le point est signalé
  0.05::float    AS ecart_echelle_max;    -- 5 % : écart toléré entre PK et longueur réelle

CREATE VIEW pk_ref.src_axes AS
SELECT a.geom FROM ferro_exemple.axes a, pk_ref.parametres p
WHERE a.code_ligne = p.code_ligne AND a.voie = 'V1';

CREATE VIEW pk_ref.src_bornes AS
SELECT b.pk, b.geom FROM ferro_exemple.bornes_pk b, pk_ref.parametres p
WHERE b.code_ligne = p.code_ligne;

CREATE VIEW pk_ref.src_sauts AS          -- table vide si la ligne n'a pas de saut
SELECT s.pk_amont, s.pk_aval, s.geom FROM ferro_exemple.sauts_pk s, pk_ref.parametres p
WHERE s.code_ligne = p.code_ligne;
