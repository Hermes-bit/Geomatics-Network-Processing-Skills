-- Section 0 du script ../proximite-dt-dict/scripts/proximite_dt_dict.sql pour le chantier d'exemple.
-- Utilisée par scripts/chainer_postgis.py --dtdict. Seules les sources changent (schéma impact_exemple).
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
SELECT id, nom, travaux_urgents, geom FROM impact_exemple.emprise;

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
FROM impact_exemple.ouvrages;

-- Exploitants : coordonnées à reprendre dans les déclarations (facultatif).
CREATE VIEW dtdict.src_exploitants AS
SELECT exploitant, contact, telephone_urgence FROM impact_exemple.exploitants;

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
