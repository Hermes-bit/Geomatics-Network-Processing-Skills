#!/usr/bin/env bash
# Crée dist/geomatique_reseaux.zip, l'extension QGIS à installer par
# Extensions > Installer/Gérer les extensions > Installer depuis un ZIP.
# Les algorithmes ne sont pas recopiés dans le dépôt : ils sont pris dans les dossiers
# skills/*/qgis/ au moment de l'empaquetage, pour rester identiques à ceux des skills.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp -r extension-qgis/geomatique_reseaux "$tmp/"
mkdir -p "$tmp/geomatique_reseaux/algorithmes"
cp skills/*/qgis/*.py "$tmp/geomatique_reseaux/algorithmes/"
cp LICENSE "$tmp/geomatique_reseaux/"
mkdir -p dist
rm -f dist/geomatique_reseaux.zip
(cd "$tmp" && zip -qr - geomatique_reseaux -x '*/__pycache__/*') > dist/geomatique_reseaux.zip
echo "dist/geomatique_reseaux.zip ($(ls "$tmp/geomatique_reseaux/algorithmes" | tr '\n' ' '))"
