#!/usr/bin/env bash
# Test de bout en bout : l'import RTE / Enedis alimente directement le skill controle-topologie-reseau.
# À lancer depuis le dossier du skill, après donnees_exemple.sql et scripts/import_rte_enedis.sql :
#   PGDATABASE=ma_base ./exemples/verifier_compatibilite_topologie.sh
# Le script de topologie est lancé avec sa section 0 pointée sur reseau_elec.troncons et reseau_elec.postes.
set -euo pipefail
TOPO_SQL="../controle-topologie-reseau/scripts/controles_topologie.sql"
[ -f "$TOPO_SQL" ] || { echo "Skill controle-topologie-reseau absent : test ignoré"; exit 0; }
sed -e "s/FROM reseau_exemple.troncons;/FROM reseau_elec.troncons;/" \
    -e "s/FROM reseau_exemple.postes;/FROM reseau_elec.postes;/" "$TOPO_SQL" \
  | PGOPTIONS="-c client_min_messages=warning" psql -X -q -v ON_ERROR_STOP=1 -o /dev/null
psql -X -q -v ON_ERROR_STOP=1 <<'SQL'
DO $$
DECLARE v text;
BEGIN
  SELECT string_agg(type || '=' || nb, ',' ORDER BY type) INTO v
  FROM (SELECT type, count(*) AS nb FROM topo_controle.anomalies GROUP BY type) a;
  IF v IS DISTINCT FROM 'attribut_manquant=2,composante_isolee=1,extremite_pendante=2,quasi_connexion=2' THEN
    RAISE EXCEPTION 'Anomalies de topologie : obtenu %', v;
  END IF;
  RAISE NOTICE 'import-donnees-rte-enedis : compatible avec controle-topologie-reseau';
END $$;
SQL
