#!/usr/bin/env bash
# Charge le jeu d'exemple de chaque skill, exécute son script et lance l'exemple.
# Si le skill fournit exemples/verifier_resultats.sql, ce test automatique est lancé
# et le script s'arrête en erreur au premier écart avec les résultats attendus.
# Les tests exemples/verifier_*.sh (tests entre skills) sont lancés aussi. Un skill qui enchaîne
# d'autres skills fournit à la place exemples/chainer_exemple.sh, lancé seul.
# Usage : PGDATABASE=ma_base ./outils/tester_exemples.sh
# Prérequis : PostgreSQL avec les extensions postgis et pgrouting disponibles.
# Les schémas créés (reseau_exemple, topo_controle, ferro_exemple, pk_ref, dtdict_exemple, dtdict, impact…) sont recréés à chaque fois.
set -euo pipefail
cd "$(dirname "$0")/.."
PSQL="psql -X -q -v ON_ERROR_STOP=1"
$PSQL -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pgrouting;"
for dossier in skills/*/; do
  [ -f "$dossier/exemples/donnees_exemple.sql" ] || continue
  echo "=== $(basename "$dossier")"
  # Skill qui enchaîne d'autres skills : il fournit son propre test de bout en bout.
  if [ -x "$dossier/exemples/chainer_exemple.sh" ]; then
    (cd "$dossier" && ./exemples/chainer_exemple.sh)
    continue
  fi
  (
    cd "$dossier"
    $PSQL -f exemples/donnees_exemple.sql 2>/dev/null
    for s in scripts/*.sql; do $PSQL -f "$s" 2>/dev/null; done
    if [ -f exemples/lancer_exemple.sql ]; then $PSQL -f exemples/lancer_exemple.sql; fi
    if [ -f exemples/verifier_resultats.sql ]; then $PSQL -f exemples/verifier_resultats.sql; fi
    for t in exemples/verifier_*.sh; do if [ -x "$t" ]; then "$t"; fi; done
  )
  echo "    Comparer avec $dossier""exemples/resultats_attendus.md"
done
# Skills en Python (sans base de données) : exemples/test_*.py
for test in skills/*/exemples/test_*.py; do
  [ -f "$test" ] || continue
  echo "=== $(basename "$(dirname "$(dirname "$test")")") (Python)"
  python3 "$test" > /dev/null || { python3 "$test"; exit 1; }
  echo "    $test : conforme"
done
