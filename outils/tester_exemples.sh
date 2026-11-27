#!/usr/bin/env bash
# Charge le jeu d'exemple de chaque skill, exécute son script et lance l'exemple.
# Usage : PGDATABASE=ma_base ./outils/tester_exemples.sh
# Prérequis : PostgreSQL avec les extensions postgis et pgrouting disponibles.
# Les schémas créés (reseau_exemple, topo_controle, ferro_exemple, pk_ref) sont recréés à chaque fois.
set -euo pipefail
cd "$(dirname "$0")/.."
PSQL="psql -X -q -v ON_ERROR_STOP=1"
$PSQL -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pgrouting;"
for dossier in skills/*/; do
  [ -f "$dossier/exemples/donnees_exemple.sql" ] || continue
  echo "=== $(basename "$dossier")"
  (
    cd "$dossier"
    $PSQL -f exemples/donnees_exemple.sql 2>/dev/null
    for s in scripts/*.sql; do $PSQL -f "$s" 2>/dev/null; done
    [ -f exemples/lancer_exemple.sql ] && $PSQL -f exemples/lancer_exemple.sql
  )
  echo "    Comparer avec $dossier""exemples/resultats_attendus.md"
done
