#!/usr/bin/env bash
# Crée un ZIP par skill dans dist/, prêt à importer dans claude.ai
# (Paramètres > Capacités > Skills). Usage : ./outils/empaqueter.sh [nom-du-skill]
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
for dossier in skills/${1:-*}/; do
  nom=$(basename "$dossier")
  [ -f "$dossier/SKILL.md" ] || { echo "Ignoré : $nom (pas de SKILL.md)"; continue; }
  rm -f "dist/$nom.zip"
  (cd skills && zip -qr "../dist/$nom.zip" "$nom" -x '*.DS_Store' '*/resultat_*.csv' '*/anomalies.csv')
  echo "dist/$nom.zip"
done
