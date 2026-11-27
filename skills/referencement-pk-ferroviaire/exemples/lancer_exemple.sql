-- Démonstration complète sur le jeu d'exemple, à lancer DEPUIS LE DOSSIER du skill :
--   psql -d ma_base -f exemples/donnees_exemple.sql
--   psql -d ma_base -f scripts/referencement_pk.sql
--   psql -d ma_base -f exemples/lancer_exemple.sql
-- Produit trois CSV dans le dossier courant : resultat_pk_vers_xy.csv,
-- resultat_xy_vers_pk.csv et resultat_evenements.csv.

CREATE TEMP TABLE entree_pk (id text, code_ligne text, pk text, decalage_m float, description text);
\copy entree_pk FROM 'exemples/pk_a_convertir.csv' CSV HEADER

CREATE TEMP TABLE entree_points (id text, x float, y float, description text);
\copy entree_points FROM 'exemples/points_a_localiser.csv' CSV HEADER

CREATE TEMP TABLE entree_evenements (id text, code_ligne text, pk_debut text, pk_fin text, description text);
\copy entree_evenements FROM 'exemples/evenements_lineaires.csv' CSV HEADER

\copy (SELECT e.id, e.code_ligne, e.pk, e.decalage_m, round(ST_X(r.geom)::numeric, 2) AS x_l93, round(ST_Y(r.geom)::numeric, 2) AS y_l93, r.methode, r.avertissement, e.description FROM entree_pk e, pk_ref.pk_vers_point(pk_ref.pk_vers_m(e.pk), e.decalage_m) r ORDER BY e.id) TO 'resultat_pk_vers_xy.csv' CSV HEADER

\copy (SELECT p.id, p.x AS x_l93, p.y AS y_l93, r.pk, r.distance_axe_m, r.decalage_m, r.methode, r.avertissement, p.description FROM entree_points p, pk_ref.point_vers_pk(ST_SetSRID(ST_MakePoint(p.x, p.y), 2154)) r ORDER BY p.id) TO 'resultat_xy_vers_pk.csv' CSV HEADER

\copy (SELECT v.id, v.pk_debut, v.pk_fin, round(r.longueur_m::numeric, 1) AS longueur_terrain_m, r.avertissement, ST_AsText(r.geom, 2) AS wkt_l93, v.description FROM entree_evenements v, pk_ref.evenement_lineaire(pk_ref.pk_vers_m(v.pk_debut), pk_ref.pk_vers_m(v.pk_fin)) r ORDER BY v.id) TO 'resultat_evenements.csv' CSV HEADER

\echo 'Fichiers écrits : resultat_pk_vers_xy.csv, resultat_xy_vers_pk.csv, resultat_evenements.csv'
