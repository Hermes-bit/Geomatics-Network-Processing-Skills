-- =============================================================================
-- Proximité DT-DICT : réseaux proches d'une emprise de travaux et exploitants concernés.
-- PostGIS >= 3.1. Testé avec PostgreSQL 16 et PostGIS 3.4.
--
-- Pré-analyse seulement : la liste officielle des exploitants à consulter est celle
-- que renvoie le guichet unique (téléservice reseaux-et-canalisations.ineris.fr).
-- Ce script aide à préparer et à contrôler la déclaration, il ne la remplace pas.
--
-- Le script construit, dans le schéma de travail dtdict (recréé à chaque exécution) :
--   dtdict.controle_emprise       contrôles de l'emprise (art. 4 de l'arrêté du 15/02/2012)
--   dtdict.ouvrages_concernes     un ouvrage par ligne, avec sa situation et ses alertes
--   dtdict.exploitants_concernes  un exploitant par ligne : ce qu'il faut lui envoyer
--   dtdict.resume                 nombre d'ouvrages par situation
-- Les tables source ne sont jamais modifiées. Adapter la section 0, puis :
--   psql -d ma_base -f proximite_dt_dict.sql
-- =============================================================================

SET client_min_messages = warning;
DROP SCHEMA IF EXISTS dtdict CASCADE;
CREATE SCHEMA dtdict;

-- -----------------------------------------------------------------------------
-- 0. PARAMÈTRES ET SOURCES (à adapter)
-- -----------------------------------------------------------------------------
CREATE TABLE dtdict.parametres AS SELECT
  5.0::float  AS marge_proximite,        -- m : ouvrages listés « à proximité » jusqu'à cette distance
  3.0::float  AS fuseau_aerien,          -- m : projection horizontale autour d'un réseau aérien (BT, traction ferroviaire)
  0.40::float AS incertitude_a_rigide,   -- m : classe A, ouvrage rigide
  0.50::float AS incertitude_a_flexible, -- m : classe A, ouvrage flexible
  1.50::float AS incertitude_b,          -- m : classe B, ouvrage principal
  1.00::float AS incertitude_b_branch,   -- m : classe B, branchement
  1.50::float AS incertitude_c_min,      -- m : classe C : au moins 1,5 m, en réalité inconnue
  20.0::float AS surface_max_ha,         -- ha : emprise d'une déclaration (2 ha si travaux urgents)
  2.0::float  AS surface_max_urgent_ha,
  50.0::float AS ecart_max_polygones,    -- m : distance maximale entre polygones d'une même emprise
  20000.0::float AS etendue_max;         -- m : distance maximale entre les deux points les plus éloignés

-- Emprise des travaux : un ou plusieurs polygones d'une même déclaration.
CREATE VIEW dtdict.src_emprise AS
SELECT id, nom, travaux_urgents, geom FROM dtdict_exemple.emprise;

-- Ouvrages (réseaux) : lignes ou points. Mettre NULL si l'attribut n'existe pas.
--   categorie       : electricite, gaz, hydrocarbures, chimie, chaleur, telecom, eau,
--                     assainissement, eclairage, ferroviaire, autre
--   pose            : souterrain, aerien, subaquatique
--   classe_precision: A, B, C (NULL = inconnue, traitée comme C)
--   flexible        : true pour un ouvrage flexible (PE, câble), false pour un rigide
--   branchement     : true pour un branchement
CREATE VIEW dtdict.src_ouvrages AS
SELECT id::text, exploitant, categorie, pose, classe_precision, flexible, branchement,
       tension_kv, geom
FROM dtdict_exemple.ouvrages;

-- Exploitants : coordonnées à reprendre dans les déclarations (facultatif).
CREATE VIEW dtdict.src_exploitants AS
SELECT exploitant, contact, telephone_urgence FROM dtdict_exemple.exploitants;

-- Réseaux sensibles pour la sécurité (art. R. 554-2 du code de l'environnement) :
-- correspondance par défaut, à vérifier pour chaque exploitant.
CREATE TABLE dtdict.categories (categorie text PRIMARY KEY, sensible boolean, libelle text);
INSERT INTO dtdict.categories VALUES
  ('electricite',    true,  'Électricité'),
  ('gaz',            true,  'Gaz combustible'),
  ('hydrocarbures',  true,  'Hydrocarbures'),
  ('chimie',         true,  'Produits chimiques'),
  ('chaleur',        true,  'Chaleur ou froid (vapeur, eau chaude)'),
  ('ferroviaire',    true,  'Installations ferroviaires ou guidées'),
  ('telecom',        false, 'Communications électroniques'),
  ('eau',            false, 'Eau potable'),
  ('assainissement', false, 'Assainissement'),
  ('eclairage',      false, 'Éclairage public et signalisation'),
  ('autre',          NULL,  'Autre : sensibilité à vérifier');

-- -----------------------------------------------------------------------------
-- 1. CONTRÔLES DE L'EMPRISE
-- -----------------------------------------------------------------------------
CREATE TABLE dtdict.controle_emprise (
  controle text, resultat text, conforme boolean
);

DO $$
DECLARE n int; srids text;
BEGIN
  SELECT count(*), string_agg(DISTINCT ST_SRID(geom)::text, ',') INTO n, srids FROM dtdict.src_emprise;
  IF n = 0 THEN RAISE EXCEPTION 'Aucun polygone d''emprise trouvé'; END IF;
  IF srids <> '2154' THEN
    RAISE EXCEPTION 'Emprise en SRID % : reprojeter en Lambert 93 (2154) avant l''analyse', srids;
  END IF;
  SELECT string_agg(DISTINCT ST_SRID(geom)::text, ',') INTO srids FROM dtdict.src_ouvrages;
  IF srids <> '2154' THEN
    RAISE EXCEPTION 'Ouvrages en SRID % : reprojeter en Lambert 93 (2154) avant l''analyse', srids;
  END IF;
END $$;

CREATE TABLE dtdict.emprise AS
SELECT ST_Union(ST_MakeValid(geom)) AS geom, bool_or(coalesce(travaux_urgents, false)) AS urgent,
       count(*) AS nb_polygones, bool_and(ST_IsValid(geom)) AS valide
FROM dtdict.src_emprise;

INSERT INTO dtdict.controle_emprise
SELECT 'géométrie valide', CASE WHEN valide THEN 'oui' ELSE 'non : réparée avec ST_MakeValid' END, valide
FROM dtdict.emprise;

INSERT INTO dtdict.controle_emprise
SELECT 'surface totale',
       round((ST_Area(e.geom) / 10000)::numeric, 2) || ' ha (maximum ' ||
         CASE WHEN e.urgent THEN p.surface_max_urgent_ha ELSE p.surface_max_ha END || ' ha)',
       ST_Area(e.geom) / 10000 <= CASE WHEN e.urgent THEN p.surface_max_urgent_ha ELSE p.surface_max_ha END
FROM dtdict.emprise e, dtdict.parametres p;

INSERT INTO dtdict.controle_emprise
SELECT 'étendue (points les plus éloignés)',
       round(ST_MaxDistance(e.geom, e.geom)::numeric) || ' m (maximum ' || p.etendue_max || ' m)',
       ST_MaxDistance(e.geom, e.geom) <= p.etendue_max
FROM dtdict.emprise e, dtdict.parametres p;

-- Chaque polygone doit être à moins de 50 m d'un autre (sinon : faire deux déclarations).
INSERT INTO dtdict.controle_emprise
SELECT 'écart entre polygones',
       CASE WHEN max(d) IS NULL THEN 'un seul polygone'
            ELSE 'plus grand écart au voisin le plus proche : ' || round(max(d)::numeric, 1) || ' m (maximum ' || max(p.ecart_max_polygones) || ' m)' END,
       coalesce(max(d) <= max(p.ecart_max_polygones), true)
FROM (
  SELECT a.id, min(ST_Distance(a.geom, b.geom)) AS d
  FROM dtdict.src_emprise a JOIN dtdict.src_emprise b ON a.id <> b.id
  GROUP BY a.id
) x, dtdict.parametres p;

-- -----------------------------------------------------------------------------
-- 2. OUVRAGES PROCHES DE L'EMPRISE
-- -----------------------------------------------------------------------------
CREATE TABLE dtdict.ouvrages_concernes AS
WITH o AS (
  SELECT s.*, coalesce(c.sensible, NULL) AS sensible,
         upper(coalesce(s.classe_precision, 'C')) AS classe,
         ST_Distance(s.geom, e.geom) AS distance_m,
         CASE upper(coalesce(s.classe_precision, 'C'))
           WHEN 'A' THEN CASE WHEN s.flexible THEN p.incertitude_a_flexible ELSE p.incertitude_a_rigide END
           WHEN 'B' THEN CASE WHEN s.branchement THEN p.incertitude_b_branch ELSE p.incertitude_b END
           ELSE p.incertitude_c_min
         END AS incertitude_m,
         p.marge_proximite, p.fuseau_aerien
  FROM dtdict.src_ouvrages s
  CROSS JOIN dtdict.emprise e
  CROSS JOIN dtdict.parametres p
  LEFT JOIN dtdict.categories c ON c.categorie = s.categorie
  WHERE ST_DWithin(s.geom, e.geom, greatest(p.marge_proximite, p.fuseau_aerien, p.incertitude_c_min))
)
SELECT id, exploitant, categorie, sensible, pose, classe, incertitude_m, tension_kv,
       round(distance_m::numeric, 2) AS distance_m,
       CASE
         WHEN distance_m = 0 THEN 'dans_emprise'
         WHEN pose = 'aerien' AND distance_m <= fuseau_aerien THEN 'fuseau_aerien'
         WHEN distance_m <= incertitude_m THEN 'zone_incertitude'
         ELSE 'proximite'
       END AS situation,
       concat_ws(' ; ',
         CASE WHEN sensible IS NULL THEN 'catégorie « ' || coalesce(categorie, 'vide') || ' » : sensibilité à vérifier' END,
         CASE WHEN classe_precision IS NULL THEN 'classe de précision inconnue : traitée comme C' END,
         CASE WHEN classe = 'C' THEN 'classe C : position réelle inconnue, ne pas se fier à la distance' END,
         CASE WHEN sensible AND pose = 'souterrain' AND classe IN ('B', 'C') AND distance_m <= incertitude_m
              THEN 'ouvrage sensible enterré non classé A dans l''emprise ou sa zone d''incertitude : investigations complémentaires ou mesures de localisation à prévoir' END,
         CASE WHEN pose = 'aerien' AND categorie = 'electricite' AND coalesce(tension_kv, 0) > 1
              THEN 'ligne aérienne HTA ou HTB : distances de sécurité du code du travail à respecter, consulter l''exploitant' END,
         CASE WHEN pose = 'aerien' AND distance_m > fuseau_aerien
                   AND (categorie = 'ferroviaire' OR (categorie = 'electricite' AND coalesce(tension_kv, 0) <= 1))
              THEN 'aérien au-delà de ' || fuseau_aerien || ' m en projection horizontale : exemption possible pour des travaux aériens sans permis, à vérifier' END
       ) AS alertes,
       geom
FROM o;

-- Gravité d'affichage : ce qu'il faut regarder en premier.
ALTER TABLE dtdict.ouvrages_concernes ADD COLUMN ordre int;
UPDATE dtdict.ouvrages_concernes SET ordre = CASE situation
  WHEN 'dans_emprise' THEN 1 WHEN 'fuseau_aerien' THEN 2 WHEN 'zone_incertitude' THEN 3 ELSE 4 END;

-- -----------------------------------------------------------------------------
-- 3. EXPLOITANTS À CONSULTER
-- -----------------------------------------------------------------------------
CREATE TABLE dtdict.exploitants_concernes AS
SELECT o.exploitant,
       string_agg(DISTINCT o.categorie, ', ') AS categories,
       bool_or(o.sensible) AS reseau_sensible,
       count(*) AS nb_ouvrages,
       min(o.distance_m) AS distance_min_m,
       (array_agg(o.situation ORDER BY o.ordre))[1] AS situation_la_plus_proche,
       bool_or(o.alertes LIKE '%investigations complémentaires%') AS ic_a_prevoir,
       x.contact, x.telephone_urgence
FROM dtdict.ouvrages_concernes o
LEFT JOIN dtdict.src_exploitants x ON x.exploitant = o.exploitant
GROUP BY o.exploitant, x.contact, x.telephone_urgence
ORDER BY bool_or(o.sensible) DESC NULLS LAST, min(o.distance_m), o.exploitant;

CREATE VIEW dtdict.resume AS
SELECT situation, count(*) AS nb_ouvrages, count(DISTINCT exploitant) AS nb_exploitants
FROM dtdict.ouvrages_concernes GROUP BY situation ORDER BY min(ordre);

\echo '--- Contrôle de l''emprise'
SELECT * FROM dtdict.controle_emprise;
\echo '--- Exploitants concernés'
SELECT exploitant, categories, reseau_sensible, nb_ouvrages, distance_min_m, situation_la_plus_proche, ic_a_prevoir
FROM dtdict.exploitants_concernes;
