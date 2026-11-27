-- À lancer depuis le dossier du skill après donnees_exemple.sql et scripts/controles_topologie.sql.
-- Exporte les anomalies en CSV (géométrie en WKT, Lambert 93) pour les ouvrir dans un tableur ou QGIS.
\copy (SELECT id, type, gravite, id_objet, detail, ST_AsText(geom, 2) AS wkt_l93 FROM topo_controle.anomalies ORDER BY id) TO 'anomalies.csv' CSV HEADER
\echo 'Fichier écrit : anomalies.csv (dans QGIS : Couche > Ajouter une couche de texte délimité, géométrie WKT, EPSG:2154)'
-- Pour un GeoPackage (si GDAL est installé) :
--   ogr2ogr -f GPKG anomalies.gpkg PG:"dbname=ma_base" -sql "SELECT * FROM topo_controle.anomalies"
