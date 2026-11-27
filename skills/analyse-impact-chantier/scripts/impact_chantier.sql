-- =============================================================================
-- Analyse d'impact d'un chantier : synthèse des réseaux, voies ferrées, végétation et parcelles
-- concernés par une emprise de travaux, avec un registre des risques.
-- PostGIS >= 3.1. Testé avec PostgreSQL 16 et PostGIS 3.4.
--
-- Ce script NE refait PAS les analyses des autres skills : il les assemble.
--   * DT-DICT : le schéma dtdict, construit par ../proximite-dt-dict/scripts/proximite_dt_dict.sql
--     (obligatoire : il donne l'emprise, les ouvrages et les exploitants) ;
--   * PK : le schéma pk_ref, construit par ../referencement-pk-ferroviaire/scripts/referencement_pk.sql
--     (facultatif : seulement s'il y a une voie ferrée près du chantier) ;
--   * végétation : le résultat troncons_vegetation.geojson du skill vegetation-lidar-hd, chargé
--     dans une table (facultatif) ;
--   * parcelles : le cadastre (Etalab ou PCI), et si possible le fichier des parcelles des
--     personnes morales (facultatif).
-- scripts/chainer_postgis.py lance les trois scripts dans l'ordre.
--
-- Le script construit, dans le schéma de travail impact (recréé à chaque exécution) :
--   impact.zone          l'emprise (reprise de dtdict.emprise) et sa surface
--   impact.voies         la section de voie proche du chantier, avec ses PK
--   impact.vegetation    les tronçons de végétation à traiter près du chantier
--   impact.parcelles     les parcelles occupées ou riveraines, avec le propriétaire s'il est publié
--   impact.risques       le registre des risques : un risque par ligne, niveau 1 (critique) à 4 (info)
--   impact.exploitants   un exploitant par ligne, avec son niveau de risque le plus élevé
--   impact.synthese      une ligne de synthèse pour le dossier
-- Les tables source et les schémas des autres skills ne sont jamais modifiés.
-- =============================================================================

SET client_min_messages = warning;
DROP SCHEMA IF EXISTS impact CASCADE;
CREATE SCHEMA impact;

-- -----------------------------------------------------------------------------
-- 0. PARAMÈTRES ET SOURCES (à adapter)
-- -----------------------------------------------------------------------------
CREATE TABLE impact.parametres AS SELECT
  'Raccordement HTA et traversée de la ligne 830000 par fonçage (exemple)'::text AS nom_chantier,
  20.0::float AS distance_voie_m,        -- m : travaux « à proximité des voies » en deçà (à confirmer avec SNCF Réseau)
  3.0::float  AS distance_min_moins_50kv,-- m : distance minimale de sécurité, U < 50 kV (code du travail, R. 4534-108)
  5.0::float  AS distance_min_50kv_plus, -- m : distance minimale de sécurité, U >= 50 kV
  5.0::float  AS marge_engins_m,         -- m : débattement des engins à ajouter en projection horizontale
  20.0::float AS marge_vegetation_m,     -- m : tronçons de végétation retenus autour de l'emprise
  20.0::float AS marge_riverains_m,      -- m : parcelles riveraines retenues autour de l'emprise
  2.0::float  AS surface_min_m2;         -- m² : en dessous, contact dû à l'imprécision du cadastre

-- Parcelles cadastrales (Etalab : id, commune, prefixe, section, numero, contenance).
-- Pas de cadastre : CREATE VIEW ... AS SELECT NULL::text AS id, ... WHERE false;
CREATE VIEW impact.src_parcelles AS
SELECT id, commune, section, numero, contenance, geom FROM impact_exemple.parcelles;

-- Propriétaires personnes morales (fichier DGFiP), par identifiant de parcelle (facultatif).
CREATE VIEW impact.src_proprietaires AS
SELECT id_parcelle, proprietaire FROM impact_exemple.proprietaires_pm;

-- Résultat du skill vegetation-lidar-hd (troncons_vegetation.geojson chargé avec ogr2ogr).
CREATE VIEW impact.src_vegetation AS
SELECT id_ligne, type, nom, troncon, cote, hauteur_max_m, distance_min_m, marge_chute_min_m, priorite, geom
FROM impact_exemple.vegetation;

-- -----------------------------------------------------------------------------
-- 1. ZONE DE TRAVAUX (reprise du skill proximite-dt-dict)
-- -----------------------------------------------------------------------------
DO $$
BEGIN
  IF to_regclass('dtdict.ouvrages_concernes') IS NULL THEN
    RAISE EXCEPTION 'Schéma dtdict absent : lancer d''abord ../proximite-dt-dict/scripts/proximite_dt_dict.sql sur la même emprise (ou scripts/chainer_postgis.py)';
  END IF;
END $$;

CREATE TABLE impact.zone AS
SELECT e.geom, e.urgent, e.nb_polygones, round((ST_Area(e.geom))::numeric, 1) AS surface_m2
FROM dtdict.emprise e;

-- Registre provisoire : la géométrie est celle de l'objet ; le registre final (section 7) garde
-- un point par risque, sur la partie de l'objet la plus proche de l'emprise.
CREATE TABLE impact._risques (
  n serial,
  niveau int,           -- 1 critique, 2 majeur, 3 à traiter, 4 information
  theme text,           -- déclaration, ferroviaire, voisinage électrique, réseaux, végétation, foncier
  objet text,
  exploitant text,
  description text,
  mesure text,
  source text,          -- skill d'origine
  geom geometry
);

-- Point qui situe un risque : dans l'emprise si l'objet la touche, sinon au plus près de l'emprise.
CREATE FUNCTION impact.point_risque(g geometry, z geometry) RETURNS geometry LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN ST_Intersects(g, z) THEN ST_PointOnSurface(ST_Intersection(g, z))
              ELSE ST_ClosestPoint(g, z) END
$$;

-- -----------------------------------------------------------------------------
-- 2. DÉCLARATION : contrôles de l'emprise non conformes
-- -----------------------------------------------------------------------------
INSERT INTO impact._risques (niveau, theme, objet, description, mesure, source, geom)
SELECT 2, 'déclaration', 'Emprise : ' || c.controle, c.resultat,
       'Découper en plusieurs déclarations DT-DICT (arrêté du 15/02/2012, art. 4) ou revoir l''emprise',
       'proximite-dt-dict', z.geom
FROM dtdict.controle_emprise c, impact.zone z
WHERE NOT c.conforme AND c.controle <> 'géométrie valide';

-- -----------------------------------------------------------------------------
-- 3. RÉSEAUX : un risque par ouvrage retenu par le skill DT-DICT
-- -----------------------------------------------------------------------------
-- 3a. Ouvrages enterrés ou subaquatiques : risque d'endommagement
INSERT INTO impact._risques (niveau, theme, objet, exploitant, description, mesure, source, geom)
SELECT CASE
         WHEN o.situation = 'dans_emprise' AND o.sensible IS DISTINCT FROM false THEN 1
         WHEN o.situation = 'zone_incertitude' AND o.sensible IS DISTINCT FROM false THEN 2
         WHEN o.situation IN ('dans_emprise', 'zone_incertitude') THEN 3
         ELSE 4 END,
       'réseaux',
       'Ouvrage ' || o.id || ' : ' || coalesce(o.categorie, '?') || ' ' || coalesce(o.pose, '') ||
         ', classe ' || o.classe || CASE WHEN o.tension_kv IS NOT NULL THEN ', ' || o.tension_kv || ' kV' ELSE '' END,
       o.exploitant,
       CASE o.situation
         WHEN 'dans_emprise' THEN 'Traverse l''emprise'
         WHEN 'zone_incertitude' THEN 'À ' || o.distance_m || ' m de l''emprise, dans sa zone d''incertitude (' || o.incertitude_m || ' m)'
         ELSE 'À ' || o.distance_m || ' m de l''emprise' END ||
         CASE WHEN o.sensible THEN ' ; réseau sensible' WHEN o.sensible IS NULL THEN ' ; sensibilité à vérifier' ELSE '' END ||
         CASE WHEN o.alertes <> '' THEN ' ; ' || o.alertes ELSE '' END,
       concat_ws(' ; ',
         CASE WHEN o.alertes LIKE '%investigations complémentaires%'
              THEN 'Investigations complémentaires ou mesures de localisation avant les travaux' END,
         CASE WHEN o.situation IN ('dans_emprise', 'zone_incertitude')
              THEN 'Marquage-piquetage ; techniques douces au droit de l''ouvrage et dans sa zone d''incertitude' END,
         CASE WHEN o.situation = 'proximite' THEN 'Reporter l''ouvrage sur les plans d''exécution' END),
       'proximite-dt-dict', o.geom
FROM dtdict.ouvrages_concernes o
WHERE o.pose IS DISTINCT FROM 'aerien';

-- 3b. Ouvrages aériens électriques (lignes, caténaires) : travaux au voisinage
INSERT INTO impact._risques (niveau, theme, objet, exploitant, description, mesure, source, geom)
SELECT CASE WHEN o.distance_m <= d.dmin THEN 1
            WHEN o.distance_m <= d.dmin + p.marge_engins_m THEN 2
            ELSE 4 END,
       'voisinage électrique',
       'Ouvrage ' || o.id || ' : ' || o.categorie || ' aérien' ||
         coalesce(', ' || o.tension_kv || ' kV', ', tension inconnue'),
       o.exploitant,
       CASE WHEN o.distance_m = 0 THEN 'Surplombe l''emprise' ELSE 'À ' || o.distance_m || ' m de l''emprise en projection horizontale' END ||
         ' ; distance minimale de sécurité ' ||
         d.dmin || ' m' || CASE WHEN o.tension_kv IS NULL THEN ' (tension inconnue : 5 m retenus)' ELSE '' END,
       CASE WHEN o.distance_m <= d.dmin + p.marge_engins_m
            THEN 'Travaux au voisinage : demander à l''exploitant la consignation ou des mesures de protection (balisage, gabarit, limitation de hauteur des engins) ; AIPR et habilitation des intervenants'
            ELSE 'Vérifier la hauteur des engins et leur débattement' END,
       'proximite-dt-dict', o.geom
FROM dtdict.ouvrages_concernes o
CROSS JOIN impact.parametres p
CROSS JOIN LATERAL (SELECT CASE WHEN o.tension_kv IS NOT NULL AND o.tension_kv < 50
                                THEN p.distance_min_moins_50kv ELSE p.distance_min_50kv_plus END AS dmin) d
WHERE o.pose = 'aerien' AND (o.categorie = 'electricite' OR (o.categorie = 'ferroviaire' AND o.tension_kv IS NOT NULL));

-- 3c. Autres ouvrages aériens (télécom, ferroviaire sans tension) : information
INSERT INTO impact._risques (niveau, theme, objet, exploitant, description, mesure, source, geom)
SELECT CASE WHEN o.situation IN ('dans_emprise', 'fuseau_aerien') THEN 3 ELSE 4 END, 'réseaux',
       'Ouvrage ' || o.id || ' : ' || coalesce(o.categorie, '?') || ' aérien', o.exploitant,
       'À ' || o.distance_m || ' m de l''emprise en projection horizontale' ||
         CASE WHEN o.alertes <> '' THEN ' ; ' || o.alertes ELSE '' END,
       'Vérifier la hauteur des engins', 'proximite-dt-dict', o.geom
FROM dtdict.ouvrages_concernes o
WHERE o.pose = 'aerien' AND NOT (o.categorie = 'electricite' OR (o.categorie = 'ferroviaire' AND o.tension_kv IS NOT NULL));

-- -----------------------------------------------------------------------------
-- 4. VOIES FERRÉES (skill referencement-pk-ferroviaire, facultatif)
-- -----------------------------------------------------------------------------
CREATE TABLE impact.voies (
  code_ligne text, pk_debut text, pk_fin text, longueur_m float, ecart_pk_m float,
  distance_min_m float, pk_emprise_debut text, pk_emprise_fin text, avertissement text,
  geom geometry(LineString, 2154)
);

DO $$
BEGIN
  IF to_regclass('pk_ref.axe') IS NULL THEN
    RAISE NOTICE 'Schéma pk_ref absent : pas de voie ferrée analysée';
    RETURN;
  END IF;
  INSERT INTO impact.voies
  WITH morceaux AS (
    SELECT row_number() OVER () AS n, d.geom AS g, z.geom AS zone
    FROM pk_ref.axe a, impact.zone z, impact.parametres p,
         ST_Dump(ST_Intersection(a.geom, ST_Buffer(z.geom, p.distance_voie_m))) d
    WHERE GeometryType(d.geom) = 'LINESTRING'
  ), dans_emprise AS (   -- partie de la voie dans l'emprise elle-même
    SELECT m.n, min(s.pk_m) AS m0, max(e.pk_m) AS m1
    FROM morceaux m
    CROSS JOIN LATERAL ST_Dump(ST_Intersection(m.g, m.zone)) c
    CROSS JOIN LATERAL pk_ref.point_vers_pk(ST_StartPoint(c.geom)) s
    CROSS JOIN LATERAL pk_ref.point_vers_pk(ST_EndPoint(c.geom)) e
    WHERE GeometryType(c.geom) = 'LINESTRING'
    GROUP BY m.n
  ), pk AS (
    SELECT m.*, d.pk AS pk_debut, d.pk_m AS m_debut, f.pk AS pk_fin, f.pk_m AS m_fin, x.m0, x.m1
    FROM morceaux m
    CROSS JOIN LATERAL pk_ref.point_vers_pk(ST_StartPoint(m.g)) d
    CROSS JOIN LATERAL pk_ref.point_vers_pk(ST_EndPoint(m.g)) f
    LEFT JOIN dans_emprise x ON x.n = m.n
  )
  SELECT (SELECT code_ligne FROM pk_ref.parametres), pk_debut, pk_fin,
         round(ST_Length(g)::numeric, 1), round((m_fin - m_debut)::numeric, 1),
         round(ST_Distance(g, zone)::numeric, 2), pk_ref.m_vers_pk(m0), pk_ref.m_vers_pk(m1),
         concat_ws(' ; ',
           (SELECT 'Contient la lacune de PK ' || string_agg(l.libelle, ', ') || ' : ' || round(ST_Length(g)::numeric) ||
                   ' m sur le terrain pour ' || round((m_fin - m_debut)::numeric) || ' m d''écart de PK'
              FROM pk_ref.lacunes l WHERE l.pk_debut_m >= m_debut AND l.pk_fin_m <= m_fin)),
         g
  FROM pk ORDER BY m_debut;
END $$;

INSERT INTO impact._risques (niveau, theme, objet, exploitant, description, mesure, source, geom)
SELECT CASE WHEN v.pk_emprise_debut IS NOT NULL THEN 1 ELSE 2 END, 'ferroviaire',
       'Ligne ' || v.code_ligne || ', PK ' || v.pk_debut || ' à ' || v.pk_fin,
       'SNCF Réseau',
       CASE WHEN v.pk_emprise_debut IS NOT NULL
            THEN 'L''emprise coupe la voie entre les PK ' || v.pk_emprise_debut || ' et ' || v.pk_emprise_fin
            ELSE 'Travaux à ' || v.distance_min_m || ' m de la voie' END ||
         ' ; ' || v.longueur_m || ' m de voie à moins de ' || p.distance_voie_m || ' m de l''emprise' ||
         CASE WHEN v.avertissement <> '' THEN ' ; ' || v.avertissement ELSE '' END,
       CASE WHEN v.pk_emprise_debut IS NOT NULL
            THEN 'Convention de travaux avec SNCF Réseau ; protection du chantier contre le risque ferroviaire (interruption temporaire de circulation ou limitation de vitesse) ; suivi topographique de la voie pendant un fonçage ou un forage'
            ELSE 'Consulter SNCF Réseau ; protection du personnel contre le risque ferroviaire ; engins hors du gabarit de la voie' END,
       'referencement-pk-ferroviaire', v.geom
FROM impact.voies v, impact.parametres p;

-- -----------------------------------------------------------------------------
-- 5. VÉGÉTATION (skill vegetation-lidar-hd, facultatif)
-- -----------------------------------------------------------------------------
CREATE TABLE impact.vegetation AS
SELECT v.id_ligne, v.type, v.nom, v.troncon, v.cote, v.hauteur_max_m, v.distance_min_m, v.marge_chute_min_m,
       v.priorite, round(ST_Distance(v.geom, z.geom)::numeric, 1) AS distance_emprise_m,
       ST_Force2D(ST_SetSRID(v.geom, 2154))::geometry(LineString, 2154) AS geom
FROM impact.src_vegetation v, impact.zone z, impact.parametres p
WHERE v.priorite IN ('1_intervenir', '2_surveiller', 'sans_donnees')
  AND ST_DWithin(ST_SetSRID(v.geom, 2154), z.geom, p.marge_vegetation_m);

INSERT INTO impact._risques (niveau, theme, objet, description, mesure, source, geom)
SELECT CASE v.priorite WHEN '1_intervenir' THEN 2 WHEN '2_surveiller' THEN 3 ELSE 4 END, 'végétation',
       coalesce(v.nom, v.id_ligne) || ', tronçon ' || v.troncon || ' ' || v.cote,
       CASE v.priorite
         WHEN 'sans_donnees' THEN 'Pas de données LiDAR HD sur ce tronçon : végétation non contrôlée'
         ELSE 'Végétation de ' || v.hauteur_max_m || ' m à ' || v.distance_min_m || ' m de l''axe (' ||
              CASE WHEN v.priorite = '1_intervenir' THEN 'à traiter' ELSE 'à surveiller' END || ')' END ||
         ', à ' || v.distance_emprise_m || ' m de l''emprise',
       CASE v.priorite
         WHEN '1_intervenir' THEN 'Élagage ou abattage avant le chantier, avec l''exploitant (risque de chute sur la ligne ou la voie) ; ces travaux sont eux-mêmes soumis à DT-DICT'
         WHEN '2_surveiller' THEN 'Contrôler sur place avant les travaux'
         ELSE 'Visite de terrain pour la végétation' END,
       'vegetation-lidar-hd', v.geom
FROM impact.vegetation v;

-- -----------------------------------------------------------------------------
-- 6. PARCELLES OCCUPÉES OU RIVERAINES
-- -----------------------------------------------------------------------------
CREATE TABLE impact.parcelles AS
WITH p AS (
  SELECT c.*, ST_Area(ST_Intersection(c.geom, z.geom)) AS s_emprise, ST_Distance(c.geom, z.geom) AS dist,
         prm.surface_min_m2
  FROM impact.src_parcelles c, impact.zone z, impact.parametres prm
  WHERE ST_DWithin(c.geom, z.geom, prm.marge_riverains_m)
)
SELECT p.id, p.commune, p.section, p.numero, p.contenance,
       round(p.s_emprise::numeric, 1) AS surface_emprise_m2,
       round((100 * p.s_emprise / nullif(ST_Area(p.geom), 0))::numeric, 2) AS part_emprise_pct,
       round(p.dist::numeric, 1) AS distance_m,
       CASE WHEN p.s_emprise >= p.surface_min_m2 THEN 'occupee'
            WHEN p.s_emprise > 0 THEN 'contact_negligeable'
            ELSE 'riveraine' END AS situation,
       coalesce((SELECT string_agg(DISTINCT o.proprietaire, ', ') FROM impact.src_proprietaires o WHERE o.id_parcelle = p.id),
                'non publié (personne physique ou non renseigné)') AS proprietaire,
       p.geom
FROM p ORDER BY p.id;

INSERT INTO impact._risques (niveau, theme, objet, description, mesure, source, geom)
SELECT CASE situation WHEN 'occupee' THEN 3 ELSE 4 END, 'foncier',
       'Parcelle ' || section || ' ' || numero || ' (' || commune || ')',
       CASE situation
         WHEN 'occupee' THEN surface_emprise_m2 || ' m² dans l''emprise'
         WHEN 'contact_negligeable' THEN 'Contact de ' || surface_emprise_m2 || ' m² seulement : probablement l''imprécision du cadastre'
         ELSE 'Riveraine, à ' || distance_m || ' m de l''emprise' END || ' ; propriétaire : ' || proprietaire,
       CASE situation
         WHEN 'occupee' THEN CASE WHEN proprietaire ILIKE '%SNCF%' THEN 'Autorisation d''occupation du domaine ferroviaire (SNCF Réseau)'
                                  WHEN proprietaire ILIKE 'COMMUNE%' OR proprietaire ILIKE '%DEPARTEMENT%' THEN 'Permission de voirie ou convention d''occupation avec la collectivité'
                                  ELSE 'Accord du propriétaire (convention d''occupation temporaire ou de servitude)' END
         WHEN 'contact_negligeable' THEN 'Vérifier la limite sur place ou sur le plan de bornage'
         ELSE 'Information des riverains (accès, nuisances)' END,
       'cadastre', geom
FROM impact.parcelles;

-- -----------------------------------------------------------------------------
-- 7. EXPLOITANTS ET SYNTHÈSE
-- -----------------------------------------------------------------------------
CREATE TABLE impact.risques AS
SELECT row_number() OVER (ORDER BY r.niveau, array_position(ARRAY['déclaration', 'ferroviaire', 'voisinage électrique',
         'réseaux', 'végétation', 'foncier'], r.theme), r.n)::int AS id,
       r.niveau,
       CASE r.niveau WHEN 1 THEN 'critique' WHEN 2 THEN 'majeur' WHEN 3 THEN 'à traiter' ELSE 'information' END AS gravite,
       r.theme, r.objet, r.exploitant, r.description, r.mesure, r.source,
       ST_Force2D(impact.point_risque(r.geom, z.geom))::geometry(Point, 2154) AS geom
FROM impact._risques r, impact.zone z
ORDER BY 1;
DROP TABLE impact._risques;

CREATE TABLE impact.exploitants AS
SELECT e.exploitant, e.categories, e.reseau_sensible, e.nb_ouvrages, e.distance_min_m, e.situation_la_plus_proche,
       e.ic_a_prevoir, (SELECT min(r.niveau) FROM impact.risques r WHERE r.exploitant = e.exploitant) AS niveau_max,
       e.contact, e.telephone_urgence
FROM dtdict.exploitants_concernes e
UNION ALL
-- La voie concernée sans ouvrage SNCF dans les couches DT-DICT : ajouter le gestionnaire.
SELECT 'SNCF Réseau', 'ferroviaire', true, 0, min(v.distance_min_m), 'voie à proximité', false,
       min(r.niveau), NULL, NULL
FROM impact.voies v JOIN impact.risques r ON r.theme = 'ferroviaire'
WHERE NOT EXISTS (SELECT 1 FROM dtdict.exploitants_concernes WHERE exploitant = 'SNCF Réseau')
HAVING count(*) > 0;

CREATE VIEW impact.synthese AS
SELECT p.nom_chantier, z.surface_m2, z.nb_polygones, z.urgent,
       (SELECT min(niveau) FROM impact.risques) AS niveau_global,
       (SELECT count(*) FROM impact.risques WHERE niveau = 1) AS nb_critiques,
       (SELECT count(*) FROM impact.risques WHERE niveau = 2) AS nb_majeurs,
       (SELECT count(*) FROM impact.risques WHERE niveau = 3) AS nb_a_traiter,
       (SELECT count(*) FROM impact.risques WHERE niveau = 4) AS nb_info,
       (SELECT count(*) FROM impact.exploitants) AS nb_exploitants,
       (SELECT count(*) FROM impact.exploitants WHERE reseau_sensible) AS nb_exploitants_sensibles,
       (SELECT bool_and(conforme) FROM dtdict.controle_emprise) AS emprise_conforme,
       (SELECT string_agg(code_ligne || ' PK ' || pk_debut || ' à ' || pk_fin, ', ') FROM impact.voies) AS voies,
       (SELECT count(*) FROM impact.parcelles WHERE situation = 'occupee') AS nb_parcelles_occupees,
       (SELECT count(*) FROM impact.parcelles WHERE situation <> 'occupee') AS nb_parcelles_riveraines,
       (SELECT count(*) FROM impact.vegetation WHERE priorite = '1_intervenir') AS nb_troncons_vegetation
FROM impact.parametres p, impact.zone z;

\echo '--- Synthèse'
SELECT * FROM impact.synthese;
\echo '--- Risques'
SELECT id, gravite, theme, objet, exploitant FROM impact.risques ORDER BY id;
