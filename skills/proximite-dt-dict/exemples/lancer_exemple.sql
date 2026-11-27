-- À lancer depuis le dossier du skill après donnees_exemple.sql et scripts/proximite_dt_dict.sql.
-- Écrit deux CSV dans le dossier courant : resultat_exploitants.csv et resultat_ouvrages.csv.
\copy (SELECT exploitant, categories, reseau_sensible, nb_ouvrages, distance_min_m, situation_la_plus_proche, ic_a_prevoir, contact, telephone_urgence FROM dtdict.exploitants_concernes) TO 'resultat_exploitants.csv' CSV HEADER
\copy (SELECT id, exploitant, categorie, sensible, pose, classe, incertitude_m, tension_kv, distance_m, situation, alertes, ST_AsText(geom, 2) AS wkt_l93 FROM dtdict.ouvrages_concernes ORDER BY ordre, distance_m, id) TO 'resultat_ouvrages.csv' CSV HEADER
\echo 'Fichiers écrits : resultat_exploitants.csv, resultat_ouvrages.csv'
