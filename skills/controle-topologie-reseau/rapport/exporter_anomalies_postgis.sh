#!/usr/bin/env bash
# Exporte la table topo_controle.anomalies (script SQL du skill controle-topologie-reseau)
# vers un GeoPackage à deux couches, anomalies_points et anomalies_lignes, lisibles par
# QGIS et par rapport/rapport_anomalies.py.
# Usage : ./rapport/exporter_anomalies_postgis.sh "dbname=ma_base" anomalies.gpkg
# Prérequis : GDAL (ogr2ogr), fourni avec QGIS.
set -euo pipefail
CONNEXION="${1:?connexion PostgreSQL, par ex. \"dbname=ma_base host=localhost user=moi\"}"
SORTIE="${2:-anomalies.gpkg}"
rm -f "$SORTIE"
ogr2ogr -f GPKG "$SORTIE" PG:"$CONNEXION" -nln anomalies_points -nlt MULTIPOINT -a_srs EPSG:2154 -sql \
  "SELECT id, type, gravite, id_objet, detail, ST_Multi(ST_CollectionExtract(geom, 1)) AS geom
     FROM topo_controle.anomalies
    WHERE geom IS NOT NULL AND NOT ST_IsEmpty(ST_CollectionExtract(geom, 1)) ORDER BY id"
ogr2ogr -update -f GPKG "$SORTIE" PG:"$CONNEXION" -nln anomalies_lignes -nlt MULTILINESTRING -a_srs EPSG:2154 -sql \
  "SELECT id, type, gravite, id_objet, detail, ST_Multi(ST_CollectionExtract(geom, 2)) AS geom
     FROM topo_controle.anomalies
    WHERE geom IS NULL OR NOT ST_IsEmpty(ST_CollectionExtract(geom, 2)) ORDER BY id"
echo "Écrit : $SORTIE (couches anomalies_points et anomalies_lignes)"
