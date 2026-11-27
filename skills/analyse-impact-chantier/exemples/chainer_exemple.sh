#!/usr/bin/env bash
# Test de bout en bout du chantier d'exemple : tous les skills s'enchaînent sur la même base.
#   1. données : chantier (donnees_exemple.sql) et voie 830000 du skill referencement-pk-ferroviaire ;
#   2. végétation : nuage LiDAR HD fictif, analysé par le VRAI script du skill vegetation-lidar-hd,
#      puis chargé dans impact_exemple.vegetation (ignoré si numpy, laspy ou ogr2ogr manquent) ;
#   3. DT-DICT, PK et synthèse avec scripts/chainer_postgis.py ;
#   4. test automatique exemples/verifier_resultats.sql.
# À lancer depuis le dossier du skill :  PGDATABASE=ma_base ./exemples/chainer_exemple.sh [dossier_de_sortie]
set -euo pipefail
PSQL="psql -X -q -v ON_ERROR_STOP=1"
SORTIE="${1:-$(mktemp -d)}"
mkdir -p "$SORTIE"
export PGOPTIONS="-c client_min_messages=warning"
$PSQL -f ../referencement-pk-ferroviaire/exemples/donnees_exemple.sql
$PSQL -f exemples/donnees_exemple.sql
if python3 -c "import numpy, laspy" 2>/dev/null && command -v ogr2ogr >/dev/null; then
  python3 exemples/generer_nuage_exemple.py "$SORTIE" > /dev/null
  python3 ../vegetation-lidar-hd/scripts/vegetation_lidar.py --lignes "$SORTIE/lignes_chantier.geojson" \
      --sortie "$SORTIE/vegetation" "$SORTIE/nuage_chantier.las" > /dev/null
  ogr2ogr -f PostgreSQL "PG:dbname=${PGDATABASE:-}" "$SORTIE/vegetation/troncons_vegetation.geojson" \
      -nln impact_exemple.vegetation -append -a_srs EPSG:2154 -nlt LINESTRING \
      -sql "SELECT id_ligne, type, nom, troncon, cote, hauteur_max_m, distance_min_m, marge_chute_min_m, priorite FROM troncons_vegetation"
  export VEGETATION=oui
else
  echo "    numpy, laspy ou ogr2ogr absent : végétation non testée (pip install numpy \"laspy[lazrs]\")"
fi
GPKG=""; command -v ogr2ogr >/dev/null && GPKG="--gpkg $SORTIE/impact.gpkg"
python3 scripts/chainer_postgis.py --dtdict exemples/sources_dtdict.sql --pk exemples/sources_pk.sql $GPKG > "$SORTIE/chainage.log"
$PSQL -v vegetation="${VEGETATION:-non}" -f exemples/verifier_resultats.sql
echo "    Résultats dans $SORTIE"
