-- =============================================================================
-- Contrôle de topologie d'un réseau linéaire (électrique ou ferroviaire)
-- PostGIS >= 3.1, pgRouting >= 3.4. Testé avec PostGIS 3.4 et pgRouting 3.6.
--
-- Principe : on ne modifie JAMAIS les tables source. Tout est fait dans le schéma
-- de travail topo_controle, qui est recréé à chaque exécution.
--
-- Utilisation : adapter la section 0, puis  psql -d ma_base -f controles_topologie.sql
-- =============================================================================

DROP SCHEMA IF EXISTS topo_controle CASCADE;
CREATE SCHEMA topo_controle;

-- -----------------------------------------------------------------------------
-- 0. PARAMÈTRES ET CORRESPONDANCE DES COLONNES (à adapter aux données réelles)
-- -----------------------------------------------------------------------------
CREATE TABLE topo_controle.parametres AS SELECT
  0.01::float   AS tolerance_accrochage,   -- m : extrémités considérées identiques
  1.0::float    AS seuil_quasi_connexion,  -- m : extrémités "presque" connectées à signaler
  1.0::float    AS longueur_min,           -- m : tronçon suspect en dessous
  ARRAY[0.4, 15, 20, 63, 90, 150, 225, 400]::numeric[] AS tensions_valides; -- kV

-- Tronçons : id, geom, et les attributs utiles. Mettre NULL si l'attribut n'existe pas.
CREATE VIEW topo_controle.src_troncons AS
SELECT id,
       tension_kv,
       pose,                         -- niveau / mode de pose pour les franchissements
       etat_exploitation,            -- 'NO' = point d'ouverture (réseau radial)
       geom
FROM reseau_exemple.troncons;

-- Postes / nœuds métier : id, nom, type, geom (Point).
CREATE VIEW topo_controle.src_postes AS
SELECT id, nom, type, geom FROM reseau_exemple.postes;

-- Types de postes qui alimentent le réseau (pour les composantes isolées).
CREATE TABLE topo_controle.types_source AS SELECT unnest(ARRAY['poste_source']) AS type;

-- -----------------------------------------------------------------------------
-- 1. TABLE DES ANOMALIES
-- -----------------------------------------------------------------------------
CREATE TABLE topo_controle.anomalies (
  id        serial PRIMARY KEY,
  type      text NOT NULL,
  gravite   text NOT NULL CHECK (gravite IN ('bloquante', 'majeure', 'mineure', 'info')),
  id_objet  text,
  detail    text,
  geom      geometry(Geometry, 2154)
);

-- -----------------------------------------------------------------------------
-- 2. CONTRÔLE DU SCR
-- -----------------------------------------------------------------------------
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'scr_inattendu', 'bloquante', id::text,
       'SRID ' || ST_SRID(geom) || ' au lieu de 2154 (Lambert 93)', NULL
FROM topo_controle.src_troncons WHERE ST_SRID(geom) <> 2154;

-- -----------------------------------------------------------------------------
-- 3. COPIE DE TRAVAIL RÉPARÉE (validité, fusion des morceaux, doublons)
-- -----------------------------------------------------------------------------
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'geometrie_invalide', 'majeure', id::text, ST_IsValidReason(geom), geom
FROM topo_controle.src_troncons WHERE NOT ST_IsValid(geom);

CREATE TABLE topo_controle.troncons AS
WITH repare AS (
  SELECT t.*,
         ST_LineMerge(ST_CollectionExtract(ST_MakeValid(t.geom), 2)) AS g
  FROM topo_controle.src_troncons t
)
SELECT id, tension_kv, pose, etat_exploitation,
       ST_NumGeometries(geom) AS nb_parties_origine,
       g AS geom
FROM repare;

-- Tronçons multi-parties qui restent multi après fusion : vraie discontinuité interne
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'troncon_discontinu', 'majeure', id::text,
       'Reste en ' || ST_NumGeometries(geom) || ' parties après ST_LineMerge', geom
FROM topo_controle.troncons WHERE GeometryType(geom) = 'MULTILINESTRING';

-- Multi-parties fusionnées sans problème : information seulement
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'troncon_multi_fusionne', 'info', id::text,
       nb_parties_origine || ' parties contiguës fusionnées dans la copie de travail', geom
FROM topo_controle.troncons
WHERE nb_parties_origine > 1 AND GeometryType(geom) = 'LINESTRING';

-- Doublons géométriques (même géométrie, quel que soit le sens) : on garde le plus petit id
CREATE TABLE topo_controle.doublons AS
SELECT b.id AS id_doublon, a.id AS id_garde, b.geom
FROM topo_controle.troncons a
JOIN topo_controle.troncons b
  ON a.id < b.id AND a.geom && b.geom AND ST_Equals(a.geom, b.geom);

INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT DISTINCT ON (id_doublon) 'doublon_geometrique', 'majeure', id_doublon::text,
       'Identique au tronçon ' || id_garde || ' (exclu du graphe)', geom
FROM topo_controle.doublons ORDER BY id_doublon, id_garde;

DELETE FROM topo_controle.troncons WHERE id IN (SELECT id_doublon FROM topo_controle.doublons);
-- On ne garde que les LineString simples pour le graphe
DELETE FROM topo_controle.troncons WHERE GeometryType(geom) <> 'LINESTRING';
CREATE INDEX ON topo_controle.troncons USING gist (geom);

-- -----------------------------------------------------------------------------
-- 4. GRAPHE (nœuds = extrémités accrochées à la tolérance)
-- -----------------------------------------------------------------------------
-- Les extrémités sont accrochées sur une grille de la tolérance, puis numérotées.
-- (équivalent à pgr_extractVertices sur des géométries accrochées ; on évite
--  pgr_createTopology, obsolète depuis pgRouting 3.8)
ALTER TABLE topo_controle.troncons ADD COLUMN source bigint, ADD COLUMN target bigint;

CREATE TABLE topo_controle.noeuds AS
SELECT row_number() OVER (ORDER BY ST_X(g), ST_Y(g)) AS id, g AS geom
FROM (
  SELECT DISTINCT ST_SnapToGrid(ST_StartPoint(geom), p.tolerance_accrochage) AS g
  FROM topo_controle.troncons, topo_controle.parametres p
  UNION
  SELECT ST_SnapToGrid(ST_EndPoint(geom), p.tolerance_accrochage)
  FROM topo_controle.troncons, topo_controle.parametres p
) e;
CREATE INDEX ON topo_controle.noeuds USING gist (geom);

UPDATE topo_controle.troncons t SET
  source = (SELECT n.id FROM topo_controle.noeuds n, topo_controle.parametres p
            WHERE n.geom = ST_SnapToGrid(ST_StartPoint(t.geom), p.tolerance_accrochage)),
  target = (SELECT n.id FROM topo_controle.noeuds n, topo_controle.parametres p
            WHERE n.geom = ST_SnapToGrid(ST_EndPoint(t.geom), p.tolerance_accrochage));

-- Degré de chaque nœud
ALTER TABLE topo_controle.noeuds ADD COLUMN degre int;
UPDATE topo_controle.noeuds n SET degre = (
  SELECT count(*) FROM topo_controle.troncons t WHERE t.source = n.id
) + (
  SELECT count(*) FROM topo_controle.troncons t WHERE t.target = n.id
);

-- Nœud porté par un poste ?
ALTER TABLE topo_controle.noeuds ADD COLUMN id_poste integer;
UPDATE topo_controle.noeuds n SET id_poste = (
  SELECT s.id FROM topo_controle.src_postes s, topo_controle.parametres p
  WHERE ST_DWithin(s.geom, n.geom, p.seuil_quasi_connexion)
  ORDER BY ST_Distance(s.geom, n.geom) LIMIT 1
);

-- -----------------------------------------------------------------------------
-- 5. CONTRÔLES
-- -----------------------------------------------------------------------------

-- 5.1 Quasi-connexions : extrémité de degré 1 à moins du seuil d'un autre tronçon,
--     sans y être accrochée. Une seule ligne par extrémité (le tronçon le plus proche).
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT DISTINCT ON (n.id) 'quasi_connexion', 'majeure', 'noeud ' || n.id,
       'Extrémité à ' || round(ST_Distance(n.geom, t.geom)::numeric, 2) ||
       ' m du tronçon ' || t.id || ' sans y être raccordée',
       ST_MakeLine(n.geom, ST_ClosestPoint(t.geom, n.geom))
FROM topo_controle.noeuds n
JOIN topo_controle.parametres p ON true
JOIN topo_controle.troncons t
  ON ST_DWithin(n.geom, t.geom, p.seuil_quasi_connexion)
 AND t.source <> n.id AND t.target <> n.id
WHERE n.degre = 1
ORDER BY n.id, ST_Distance(n.geom, t.geom), t.id;

-- 5.2 Extrémités pendantes : degré 1, pas sur un poste
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'extremite_pendante', 'mineure', 'noeud ' || n.id,
       'Extrémité libre du tronçon ' ||
       (SELECT string_agg(id::text, ',') FROM topo_controle.troncons t
         WHERE t.source = n.id OR t.target = n.id),
       n.geom
FROM topo_controle.noeuds n
WHERE n.degre = 1 AND n.id_poste IS NULL;

-- 5.3 Croisements sans nœud. Un croisement entre deux poses différentes
--     (aérien / souterrain, pont / voie) est un franchissement normal : ignoré.
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'croisement_sans_noeud', 'majeure', a.id || '/' || b.id,
       'Croisement ' || coalesce(a.pose, '?') || ' / ' || coalesce(b.pose, '?') || ' sans nœud commun',
       ST_Intersection(a.geom, b.geom)
FROM topo_controle.troncons a
JOIN topo_controle.troncons b ON a.id < b.id AND a.geom && b.geom
WHERE ST_Crosses(a.geom, b.geom)
  AND a.pose IS NOT DISTINCT FROM b.pose;

INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'franchissement', 'info', a.id || '/' || b.id,
       'Croisement ' || a.pose || ' / ' || b.pose || ' : franchissement considéré comme normal',
       ST_Intersection(a.geom, b.geom)
FROM topo_controle.troncons a
JOIN topo_controle.troncons b ON a.id < b.id AND a.geom && b.geom
WHERE ST_Crosses(a.geom, b.geom)
  AND a.pose IS DISTINCT FROM b.pose;

-- 5.4 Composantes connexes (pgRouting) et composantes non alimentées
CREATE TABLE topo_controle.composantes AS
SELECT node, component
FROM pgr_connectedComponents(
  'SELECT id, source, target, 1 AS cost, 1 AS reverse_cost FROM topo_controle.troncons');

ALTER TABLE topo_controle.noeuds ADD COLUMN composante bigint;
UPDATE topo_controle.noeuds n SET composante = c.component
FROM topo_controle.composantes c WHERE c.node = n.id;

INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'composante_isolee', 'majeure', 'composante ' || n.composante,
       count(DISTINCT t.id) || ' tronçon(s) non relié(s) à un poste source : ' ||
       string_agg(DISTINCT t.id::text, ','),
       ST_Union(DISTINCT t.geom)
FROM topo_controle.noeuds n
JOIN topo_controle.troncons t ON t.source = n.id OR t.target = n.id
WHERE n.composante NOT IN (
  SELECT n2.composante FROM topo_controle.noeuds n2
  JOIN topo_controle.src_postes s ON s.id = n2.id_poste
  WHERE s.type IN (SELECT type FROM topo_controle.types_source)
)
GROUP BY n.composante;

-- 5.5 Postes isolés : aucun tronçon à moins du seuil
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'poste_isole', 'majeure', 'poste ' || s.id, s.nom || ' : aucun tronçon à proximité', s.geom
FROM topo_controle.src_postes s, topo_controle.parametres p
WHERE NOT EXISTS (
  SELECT 1 FROM topo_controle.troncons t WHERE ST_DWithin(t.geom, s.geom, p.seuil_quasi_connexion));

-- 5.6 Tronçons trop courts
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'troncon_trop_court', 'mineure', t.id::text,
       round(ST_Length(t.geom)::numeric, 2) || ' m (< ' || p.longueur_min || ' m)', t.geom
FROM topo_controle.troncons t, topo_controle.parametres p
WHERE ST_Length(t.geom) < p.longueur_min;

-- 5.7 Boucles fermées en exploitation radiale : on retire les tronçons NO (points
--     d'ouverture), puis pgr_biconnectedComponents. Un tronçon qui appartient à une
--     composante biconnexe de plus d'un tronçon fait partie d'une boucle fermée.
WITH bcc AS (
  SELECT edge, component FROM pgr_biconnectedComponents(
    'SELECT id, source, target, 1 AS cost, 1 AS reverse_cost FROM topo_controle.troncons
     WHERE coalesce(etat_exploitation, ''NF'') <> ''NO''')
), boucles AS (
  SELECT component, array_agg(edge ORDER BY edge) AS ids
  FROM bcc GROUP BY component HAVING count(*) > 1
)
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'boucle_fermee_radial', 'majeure', array_to_string(b.ids, ','),
       'Boucle sans point d''ouverture (NO) formée par les tronçons ' || array_to_string(b.ids, ', '),
       (SELECT ST_Union(t.geom) FROM topo_controle.troncons t WHERE t.id = ANY (b.ids))
FROM boucles b;

-- 5.8 Boucles sur elles-mêmes (source = target)
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'troncon_boucle_sur_lui_meme', 'majeure', id::text, 'Début et fin au même nœud', geom
FROM topo_controle.troncons WHERE source = target;

-- 5.9 Cohérence des attributs
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'attribut_manquant', 'mineure', t.id::text, 'tension_kv vide', t.geom
FROM topo_controle.troncons t WHERE t.tension_kv IS NULL;

INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'attribut_incoherent', 'mineure', t.id::text,
       'tension_kv = ' || t.tension_kv || ' hors des valeurs normalisées', t.geom
FROM topo_controle.troncons t, topo_controle.parametres p
WHERE t.tension_kv IS NOT NULL AND NOT t.tension_kv = ANY (p.tensions_valides);

-- Changement de tension sur un nœud qui n'est pas un poste (transformation impossible)
INSERT INTO topo_controle.anomalies (type, gravite, id_objet, detail, geom)
SELECT 'tension_incoherente_noeud', 'mineure', 'noeud ' || n.id,
       'Tensions ' || string_agg(DISTINCT t.tension_kv::text, ' / ') ||
       ' kV sur un nœud sans poste (tronçons ' || string_agg(DISTINCT t.id::text, ',') || ')',
       n.geom
FROM topo_controle.noeuds n
JOIN topo_controle.troncons t ON (t.source = n.id OR t.target = n.id) AND t.tension_kv IS NOT NULL
WHERE n.id_poste IS NULL
GROUP BY n.id, n.geom
HAVING count(DISTINCT t.tension_kv) > 1;

-- -----------------------------------------------------------------------------
-- 6. RÉSUMÉ
-- -----------------------------------------------------------------------------
CREATE VIEW topo_controle.resume AS
SELECT gravite, type, count(*) AS nombre
FROM topo_controle.anomalies
GROUP BY gravite, type
ORDER BY CASE gravite WHEN 'bloquante' THEN 1 WHEN 'majeure' THEN 2
                      WHEN 'mineure' THEN 3 ELSE 4 END, type;

SELECT * FROM topo_controle.resume;
