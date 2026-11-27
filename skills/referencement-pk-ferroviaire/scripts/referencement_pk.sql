-- =============================================================================
-- Référencement linéaire ferroviaire : PK (km+m) <-> coordonnées, avec PostGIS.
-- PostGIS >= 3.1. Testé avec PostGIS 3.4.
--
-- Le script construit, dans le schéma de travail pk_ref (recréé à chaque exécution) :
--   pk_ref.axe        l'axe fusionné et orienté dans le sens des PK croissants
--   pk_ref.calage     les points de calage (bornes + sauts de PK) et leur contrôle
--   pk_ref.troncons_m l'axe découpé entre points de calage, mesuré en PK (LineStringM)
-- et les fonctions de conversion :
--   pk_ref.pk_vers_m('15+342')           -> 15342
--   pk_ref.m_vers_pk(15342.4)            -> '15+342.4'
--   pk_ref.pk_vers_point(pk_m, decalage) -> point, méthode, avertissement
--   pk_ref.point_vers_pk(geom)           -> pk, distance, décalage signé, avertissement
--   pk_ref.evenement_lineaire(pk_debut_m, pk_fin_m) -> ligne, avertissement
-- Convention de décalage : positif à GAUCHE dans le sens des PK croissants.
--
-- Les tables source ne sont jamais modifiées. Adapter la section 0, puis :
--   psql -d ma_base -f referencement_pk.sql
-- =============================================================================

DROP SCHEMA IF EXISTS pk_ref CASCADE;
CREATE SCHEMA pk_ref;

-- -----------------------------------------------------------------------------
-- 0. PARAMÈTRES ET SOURCES (à adapter)
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- 1. CONVERSION DU FORMAT km+m
-- -----------------------------------------------------------------------------
-- Accepte '15+342', '15+342.5', '015+342', '15+042', ' 15 + 342 '.
CREATE FUNCTION pk_ref.pk_vers_m(pk text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE m text[];
BEGIN
  m := regexp_match(replace(pk, ' ', ''), '^(-?\d+)\+(\d{1,3}(?:[.,]\d+)?)$');
  IF m IS NULL THEN
    RAISE EXCEPTION 'PK "%" illisible : format attendu km+m, par exemple 15+342', pk;
  END IF;
  RETURN m[1]::numeric * 1000 + replace(m[2], ',', '.')::numeric;
END $$;

CREATE FUNCTION pk_ref.m_vers_pk(m numeric) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  -- 15342.4 -> '15+342.4' ; 15042 -> '15+042'
  SELECT floor(m / 1000)::int || '+' ||
         lpad(floor(m - floor(m / 1000) * 1000)::int::text, 3, '0') ||
         coalesce('.' || nullif(rtrim(substring((m - floor(m))::text FROM '\.(\d+)'), '0'), ''), '')
$$;

-- -----------------------------------------------------------------------------
-- 2. AXE : fusion des morceaux et orientation
-- -----------------------------------------------------------------------------
CREATE TABLE pk_ref.axe AS
SELECT ST_LineMerge(ST_Collect(geom)) AS geom FROM pk_ref.src_axes;

DO $$
DECLARE t text; n int;
BEGIN
  SELECT GeometryType(geom), ST_NumGeometries(geom) INTO t, n FROM pk_ref.axe;
  IF t IS NULL THEN RAISE EXCEPTION 'Aucun axe trouvé pour cette ligne'; END IF;
  IF t <> 'LINESTRING' THEN
    RAISE EXCEPTION 'L''axe reste en % morceaux après ST_LineMerge : trous ou embranchements à traiter avant le calage', n;
  END IF;
  IF (SELECT ST_SRID(geom) FROM pk_ref.axe) <> 2154 THEN
    RAISE EXCEPTION 'Axe en SRID %, reprojeter en Lambert 93 (2154)', (SELECT ST_SRID(geom) FROM pk_ref.axe);
  END IF;
END $$;

-- Orientation : la borne de plus petit PK doit être vers le début de l'axe.
UPDATE pk_ref.axe a SET geom = ST_Reverse(a.geom)
WHERE (SELECT ST_LineLocatePoint(a.geom, geom) FROM pk_ref.src_bornes
        ORDER BY pk_ref.pk_vers_m(pk) LIMIT 1)
    > (SELECT ST_LineLocatePoint(a.geom, geom) FROM pk_ref.src_bornes
        ORDER BY pk_ref.pk_vers_m(pk) DESC LIMIT 1);

-- -----------------------------------------------------------------------------
-- 3. POINTS DE CALAGE (bornes + sauts) et contrôle
-- -----------------------------------------------------------------------------
CREATE TABLE pk_ref.calage (
  ordre        int,
  origine      text,       -- borne / saut_amont / saut_aval / debut_axe / fin_axe
  pk_texte     text,
  pk_m         numeric,
  frac         float,      -- position relative sur l'axe (0 à 1)
  abscisse_m   float,      -- distance depuis le début de l'axe
  dist_axe_m   float,
  avertissement text
);

INSERT INTO pk_ref.calage (origine, pk_texte, pk_m, frac, dist_axe_m)
SELECT 'borne', b.pk, pk_ref.pk_vers_m(b.pk), ST_LineLocatePoint(a.geom, b.geom), ST_Distance(a.geom, b.geom)
FROM pk_ref.src_bornes b, pk_ref.axe a
UNION ALL
SELECT 'saut_amont', s.pk_amont, pk_ref.pk_vers_m(s.pk_amont), ST_LineLocatePoint(a.geom, s.geom), ST_Distance(a.geom, s.geom)
FROM pk_ref.src_sauts s, pk_ref.axe a
UNION ALL
SELECT 'saut_aval', s.pk_aval, pk_ref.pk_vers_m(s.pk_aval), ST_LineLocatePoint(a.geom, s.geom), ST_Distance(a.geom, s.geom)
FROM pk_ref.src_sauts s, pk_ref.axe a;

UPDATE pk_ref.calage c SET abscisse_m = c.frac * ST_Length(a.geom) FROM pk_ref.axe a;

-- Extrémités de l'axe, extrapolées à l'échelle 1 (signalé dans les résultats)
INSERT INTO pk_ref.calage (origine, pk_texte, pk_m, frac, abscisse_m, dist_axe_m)
SELECT 'debut_axe', NULL, c.pk_m - c.abscisse_m, 0, 0, 0
FROM pk_ref.calage c ORDER BY c.frac, c.pk_m LIMIT 1;
INSERT INTO pk_ref.calage (origine, pk_texte, pk_m, frac, abscisse_m, dist_axe_m)
SELECT 'fin_axe', NULL, c.pk_m + (ST_Length(a.geom) - c.abscisse_m), 1, ST_Length(a.geom), 0
FROM pk_ref.calage c, pk_ref.axe a WHERE c.origine <> 'debut_axe'
ORDER BY c.frac DESC, c.pk_m DESC LIMIT 1;
UPDATE pk_ref.calage SET pk_texte = pk_ref.m_vers_pk(round(pk_m, 1)) WHERE pk_texte IS NULL;

UPDATE pk_ref.calage c SET ordre = o.rn
FROM (SELECT ctid, row_number() OVER (ORDER BY frac, pk_m) rn FROM pk_ref.calage) o
WHERE c.ctid = o.ctid;

UPDATE pk_ref.calage c SET avertissement = 'Borne à ' || round(dist_axe_m::numeric, 1) || ' m de l''axe'
FROM pk_ref.parametres p WHERE c.dist_axe_m > p.distance_max_axe;

-- PK qui décroît le long de l'axe (borne mal placée ou mal saisie)
UPDATE pk_ref.calage c SET avertissement = concat_ws(' ; ', c.avertissement,
       'PK non croissant par rapport au point de calage précédent (' || prev.pk_texte || ')')
FROM pk_ref.calage prev
WHERE prev.ordre = c.ordre - 1 AND c.pk_m < prev.pk_m;

-- -----------------------------------------------------------------------------
-- 4. AXE MESURÉ : un tronçon par intervalle entre deux points de calage
-- -----------------------------------------------------------------------------
CREATE TABLE pk_ref.troncons_m AS
SELECT c1.ordre,
       c1.pk_texte AS pk_debut, c2.pk_texte AS pk_fin,
       c1.pk_m AS pk_debut_m, c2.pk_m AS pk_fin_m,
       ST_Length(ST_LineSubstring(a.geom, c1.frac, c2.frac)) AS longueur_m,
       (c2.pk_m - c1.pk_m) / NULLIF(ST_Length(ST_LineSubstring(a.geom, c1.frac, c2.frac)), 0) AS echelle,
       CASE WHEN c1.origine = 'debut_axe' OR c2.origine = 'fin_axe'
            THEN 'extrapolation hors bornes' ELSE 'interpolation entre bornes' END AS methode,
       ST_AddMeasure(ST_LineSubstring(a.geom, c1.frac, c2.frac), c1.pk_m, c2.pk_m) AS geom
FROM pk_ref.calage c1
JOIN pk_ref.calage c2 ON c2.ordre = c1.ordre + 1
CROSS JOIN pk_ref.axe a
WHERE c2.frac > c1.frac AND c2.pk_m > c1.pk_m;   -- les sauts (même position) ne créent pas de tronçon
CREATE INDEX ON pk_ref.troncons_m USING gist (geom);

-- Lacunes de PK (zones de PK qui n'existent pas sur le terrain)
CREATE VIEW pk_ref.lacunes AS
SELECT a.pk_m AS pk_debut_m, b.pk_m AS pk_fin_m, a.pk_texte || ' = ' || b.pk_texte AS libelle
FROM pk_ref.calage a JOIN pk_ref.calage b ON b.ordre = a.ordre + 1
WHERE a.origine = 'saut_amont' AND b.origine = 'saut_aval' AND b.pk_m > a.pk_m;

-- -----------------------------------------------------------------------------
-- 5. FONCTIONS DE CONVERSION
-- -----------------------------------------------------------------------------

-- PK -> point (décalage positif à gauche dans le sens des PK croissants)
CREATE FUNCTION pk_ref.pk_vers_point(p_pk numeric, p_decalage float DEFAULT 0)
RETURNS TABLE (geom geometry, methode text, avertissement text)
LANGUAGE plpgsql STABLE AS $$
DECLARE t record; lac text;
BEGIN
  SELECT * INTO t FROM pk_ref.troncons_m
  WHERE p_pk BETWEEN pk_debut_m AND pk_fin_m ORDER BY ordre LIMIT 1;
  IF NOT FOUND THEN
    SELECT libelle INTO lac FROM pk_ref.lacunes WHERE p_pk > pk_debut_m AND p_pk < pk_fin_m;
    IF lac IS NOT NULL THEN
      RETURN QUERY SELECT NULL::geometry, 'aucune'::text, ('PK inexistant : dans la lacune ' || lac)::text;
    ELSE
      RETURN QUERY SELECT NULL::geometry, 'aucune'::text,
        ('PK hors de la ligne (' || (SELECT min(pk_texte) FILTER (WHERE origine = 'debut_axe') FROM pk_ref.calage)
         || ' à ' || (SELECT min(pk_texte) FILTER (WHERE origine = 'fin_axe') FROM pk_ref.calage) || ')')::text;
    END IF;
    RETURN;
  END IF;
  RETURN QUERY SELECT
    ST_Force2D(ST_GeometryN(ST_LocateAlong(t.geom, p_pk, p_decalage), 1)),
    t.methode || CASE WHEN p_decalage <> 0 THEN ', décalage ' || p_decalage || ' m' ELSE '' END,
    CASE WHEN t.methode LIKE 'extrapolation%' THEN 'PK hors des bornes : position extrapolée, à vérifier'
         WHEN abs(t.echelle - 1) > (SELECT ecart_echelle_max FROM pk_ref.parametres)
         THEN 'Kilomètre ' || t.pk_debut || ' - ' || t.pk_fin || ' : écart de ' ||
              round(((t.echelle - 1) * 100)::numeric, 1) || ' % entre PK et longueur mesurée (saut de PK non déclaré ?)'
    END;
END $$;

-- Point -> PK, avec distance à l'axe et décalage signé
CREATE FUNCTION pk_ref.point_vers_pk(p_geom geometry)
RETURNS TABLE (pk_m numeric, pk text, distance_axe_m float, decalage_m float, methode text, avertissement text)
LANGUAGE plpgsql STABLE AS $$
DECLARE t record; m float; d float; f float; a geometry; p0 geometry; p1 geometry; cote float;
BEGIN
  IF ST_SRID(p_geom) <> 2154 THEN p_geom := ST_Transform(p_geom, 2154); END IF;
  SELECT * INTO t FROM pk_ref.troncons_m ORDER BY geom <-> p_geom, ST_Distance(geom, p_geom) LIMIT 1;
  m := ST_InterpolatePoint(t.geom, p_geom);
  d := ST_Distance(t.geom, p_geom);
  -- côté : produit vectoriel entre la direction locale de l'axe et le point
  SELECT geom INTO a FROM pk_ref.axe;
  f := ST_LineLocatePoint(a, p_geom);
  p0 := ST_LineInterpolatePoint(a, greatest(f - 0.00001, 0));
  p1 := ST_LineInterpolatePoint(a, least(f + 0.00001, 1));
  cote := sign((ST_X(p1) - ST_X(p0)) * (ST_Y(p_geom) - ST_Y(p0)) - (ST_Y(p1) - ST_Y(p0)) * (ST_X(p_geom) - ST_X(p0)));
  RETURN QUERY SELECT round(m::numeric, 1), pk_ref.m_vers_pk(round(m::numeric, 1)), round(d::numeric, 2)::float,
    round((d * cote)::numeric, 2)::float, t.methode,
    concat_ws(' ; ',
      CASE WHEN d > (SELECT distance_max_axe FROM pk_ref.parametres)
           THEN 'Point à ' || round(d::numeric, 1) || ' m de l''axe : rattachement douteux' END,
      CASE WHEN t.methode LIKE 'extrapolation%' THEN 'Hors des bornes : PK extrapolé' END,
      (SELECT 'Au droit du saut de PK ' || l.libelle || ' : les deux PK désignent ce point'
         FROM pk_ref.lacunes l WHERE abs(m - l.pk_debut_m) < 1 OR abs(m - l.pk_fin_m) < 1 LIMIT 1),
      CASE WHEN abs(t.echelle - 1) > (SELECT ecart_echelle_max FROM pk_ref.parametres)
           THEN 'Kilomètre ' || t.pk_debut || ' - ' || t.pk_fin || ' hors échelle' END);
END $$;

-- Événement linéaire entre deux PK
CREATE FUNCTION pk_ref.evenement_lineaire(p_debut numeric, p_fin numeric)
RETURNS TABLE (geom geometry, longueur_m float, avertissement text)
LANGUAGE sql STABLE AS $$
  WITH morceaux AS (
    SELECT ST_Force2D(ST_LocateBetween(t.geom, least(p_debut, p_fin), greatest(p_debut, p_fin))) AS g
    FROM pk_ref.troncons_m t
    WHERE t.pk_fin_m >= least(p_debut, p_fin) AND t.pk_debut_m <= greatest(p_debut, p_fin)
  ), ligne AS (
    SELECT ST_LineMerge(ST_Union(g)) AS g FROM morceaux WHERE NOT ST_IsEmpty(g)
  )
  SELECT g, ST_Length(g),
    concat_ws(' ; ',
      (SELECT 'Contient la lacune ' || string_agg(libelle, ', ') || ' : longueur terrain < écart de PK'
         FROM pk_ref.lacunes WHERE pk_debut_m < greatest(p_debut, p_fin) AND pk_fin_m > least(p_debut, p_fin)),
      CASE WHEN g IS NULL THEN 'Intervalle hors de la ligne' END)
  FROM ligne
$$;

-- -----------------------------------------------------------------------------
-- 6. CONTRÔLE RAPIDE
-- -----------------------------------------------------------------------------
SELECT ordre, origine, pk_texte, round(abscisse_m::numeric, 1) AS abscisse_m,
       round(dist_axe_m::numeric, 1) AS dist_axe_m, avertissement
FROM pk_ref.calage ORDER BY ordre;
