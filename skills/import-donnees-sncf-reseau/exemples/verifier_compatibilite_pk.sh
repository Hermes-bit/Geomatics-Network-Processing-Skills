#!/usr/bin/env bash
# Test de bout en bout : l'import SNCF alimente directement le skill referencement-pk-ferroviaire.
# À lancer depuis le dossier du skill, après donnees_exemple.sql et scripts/import_sncf_reseau.sql :
#   PGDATABASE=ma_base ./exemples/verifier_compatibilite_pk.sh
# Le script du skill PK est lancé avec sa section 0 pointée sur sncf.axes, sncf.bornes_pk et
# sncf.sauts_pk (ligne 999000), puis on vérifie deux conversions.
set -euo pipefail
PK_SQL="../referencement-pk-ferroviaire/scripts/referencement_pk.sql"
[ -f "$PK_SQL" ] || { echo "Skill referencement-pk-ferroviaire absent : test ignoré"; exit 0; }
sed -e "s/'830000'::text AS code_ligne/'999000'::text AS code_ligne/" \
    -e "s/FROM ferro_exemple.axes a/FROM sncf.axes a/" \
    -e "s/AND a.voie = 'V1'/AND a.voie = 'axe'/" \
    -e "s/FROM ferro_exemple.bornes_pk b/FROM sncf.bornes_pk b/" \
    -e "s/FROM ferro_exemple.sauts_pk s/FROM sncf.sauts_pk s/" "$PK_SQL" \
  | PGOPTIONS="-c client_min_messages=warning" psql -X -q -v ON_ERROR_STOP=1 -o /dev/null
psql -X -q -v ON_ERROR_STOP=1 <<'SQL'
DO $$
DECLARE r record;
BEGIN
  -- 5+300 : sur le tronçon numérisé à l'envers, près du pont de la D 12
  SELECT * INTO r FROM pk_ref.pk_vers_point(pk_ref.pk_vers_m('5+300'), 0);
  IF r.geom IS NULL OR ST_Distance(r.geom, ST_SetSRID(ST_MakePoint(805029.6, 6600205.9), 2154)) > 1 THEN
    RAISE EXCEPTION 'PK 5+300 mal placé : %', ST_AsText(r.geom, 1);
  END IF;
  -- 4+100 : dans la lacune 4+000 = 4+250, ne doit pas avoir de position
  SELECT * INTO r FROM pk_ref.pk_vers_point(pk_ref.pk_vers_m('4+100'), 0);
  IF r.geom IS NOT NULL OR r.avertissement NOT LIKE '%lacune%' THEN
    RAISE EXCEPTION 'PK 4+100 aurait dû tomber dans la lacune : % / %', ST_AsText(r.geom), r.avertissement;
  END IF;
  RAISE NOTICE 'import-donnees-sncf-reseau : compatible avec referencement-pk-ferroviaire';
END $$;
SQL
