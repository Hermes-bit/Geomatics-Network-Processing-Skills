---
name: import-donnees-rte-enedis
description: Importe les données ouvertes des réseaux électriques de RTE (ODRÉ : lignes aériennes, liaisons souterraines, postes) et des gestionnaires de distribution (Enedis, Agence ORE : lignes HTA et BT aériennes ou souterraines, postes sources, postes HTA/BT) dans PostGIS en Lambert 93, avec tensions en kV et mode de pose normalisés, au format du skill controle-topologie-reseau et du skill proximite-dt-dict. À utiliser pour télécharger, charger, cartographier ou contrôler les réseaux RTE ou Enedis en open data, ou pour préparer un contrôle de topologie sur un réseau électrique réel.
---

# Import des données ouvertes RTE et Enedis

Ce skill réunit les fichiers ouverts des réseaux électriques en deux couches propres, `reseau_elec.troncons` et `reseau_elec.postes`, prêtes pour QGIS et pour le skill `controle-topologie-reseau`. Un script PostGIS testé est fourni : `scripts/import_rte_enedis.sql`.

## Règle d'or
- Ne jamais modifier les tables brutes `elec_brut` : tout est recréé dans le schéma `reseau_elec`.
- Ces données sont une **cartographie de connaissance**, pas des plans d'exploitant. Leur précision n'est pas garantie : pour une DT-DICT elles valent au mieux une classe C, et ne remplacent pas les réponses des exploitants.
- Les points d'ouverture du réseau HTA (NO) ne sont **pas publiés** : un contrôle de topologie trouvera des boucles qui sont normales en exploitation. Le dire.

## Les sources
**RTE, sur ODRÉ** ([opendata.reseaux-energies.fr](https://opendata.reseaux-energies.fr), plateforme Opendatasoft) : lignes aériennes, liaisons souterraines, pylônes, postes électriques (localisation et enceintes). Licence Ouverte 2.0. Rechercher « RTE » dans le catalogue, puis télécharger le GeoJSON (onglet Export) ou le shapefile complet (pièces jointes de l'onglet Informations). Une couche « végétation dans l'emprise des lignes RTE » existe aussi.

**Enedis** ([opendata.enedis.fr](https://opendata.enedis.fr)) : lignes HTA aériennes (`reseau-hta`), lignes HTA souterraines (`reseau-souterrain-hta`), postes HTA/BT (`poste-electrique`), poteaux HTA et BT (`position-geographique-des-poteaux-hta-et-bt`, avec une API data-fair). Licence Ouverte 2.0, mise à jour deux fois par an, en RGF93. Les lignes sont découpées en segments.

**Agence ORE** ([opendata.agenceore.fr](https://opendata.agenceore.fr)) : les mêmes couches pour tous les gestionnaires de distribution (Enedis, entreprises locales de distribution…), France entière : postes sources et de répartition, postes HTA/BT, lignes BT, HTA et HTB aériennes et souterraines (par exemple `reseau-aerien-haute-tension-htb`). D'après sa note méthodologique (version 7.2 du 22/12/2023), les champs sont `geo_shape`, `geo_point_2d`, `position` (aérien ou souterrain), `tension` (BT, HTA ou HTB), `nom_grd`, `date_maj`, `code_insee`, `commune`, `code_epci`, `code_departement`, `code_region`. WGS84, Licence Ouverte, mise à jour au moins annuelle.

Les noms de champs évoluent : le script essaie plusieurs noms (table `reseau_elec.correspondance`) et `reseau_elec.champs_utilises` dit lequel a servi. Vérifier l'en-tête des fichiers réels avant de conclure.

## Avant de commencer : informations à obtenir
1. La zone (communes, département, emprise) et les niveaux de tension voulus (HTB, HTA, BT).
2. Le but : carte, contrôle de topologie, pré-analyse DT-DICT.
3. La tension nominale HTA du secteur si elle est connue (20 kV le plus souvent, 15 kV par endroits) : les fichiers de distribution disent seulement « HTA ».

## Étapes

### 1. Charger les fichiers bruts
Une table par fichier, nommée `lignes_<nom>` ou `postes_<nom>`. Le nom sert de valeur par défaut quand un champ manque : `rte` donne le gestionnaire RTE et le domaine HTB, `aerien` ou `souterrain` la pose, `source` ou `hta_bt` le type de poste.
```bash
psql -d ma_base -c "CREATE SCHEMA IF NOT EXISTS elec_brut"
ogr2ogr -f PostgreSQL PG:"dbname=ma_base" lignes-aeriennes-rte.geojson -nln elec_brut.lignes_rte_aeriennes -lco GEOMETRY_NAME=geom -overwrite
ogr2ogr -f PostgreSQL PG:"dbname=ma_base" postes-rte.geojson           -nln elec_brut.postes_rte -lco GEOMETRY_NAME=geom -overwrite
ogr2ogr -f PostgreSQL PG:"dbname=ma_base" reseau-hta.geojson           -nln elec_brut.lignes_hta_aeriennes -lco GEOMETRY_NAME=geom -overwrite
ogr2ogr -f PostgreSQL PG:"dbname=ma_base" reseau-souterrain-hta.geojson -nln elec_brut.lignes_hta_souterraines -lco GEOMETRY_NAME=geom -overwrite
ogr2ogr -f PostgreSQL PG:"dbname=ma_base" poste-electrique.geojson     -nln elec_brut.postes_hta_bt -lco GEOMETRY_NAME=geom -overwrite
```
Pour une zone, filtrer dès le téléchargement (API Opendatasoft `?refine=code_departement:69` ou équivalent) ou avec le paramètre `zone_wkt_l93` du script.

### 2. Importer
`psql -d ma_base -f scripts/import_rte_enedis.sql`. Le script :
- reprojette en Lambert 93 (2154) ; un SRID absent est supposé WGS84 et signalé ;
- lit les tensions : `225kV` ou `225 kV` donnent 225, `HTA` donne 20 kV et `BT` 0,4 kV (valeurs par défaut signalées une fois par table), `HORS TENSION` donne une tension vide et l'état `hors_tension` ;
- range chaque tronçon en domaine BT (≤ 1 kV), HTA (≤ 50 kV) ou HTB ;
- normalise la pose (`Aérien`, `AERIENNE`, `aérien` donnent `aerien`) ;
- réduit les enceintes de postes à un point (`ST_PointOnSurface`) et signale les postes publiés deux fois.

### 3. Enchaîner avec les autres skills
**Contrôle de topologie** : dans la section 0 de `controles_topologie.sql`, remplacer `FROM reseau_exemple.troncons` par `FROM reseau_elec.troncons` et `FROM reseau_exemple.postes` par `FROM reseau_elec.postes`. Les colonnes `id, tension_kv, pose, etat_exploitation, geom` et `id, nom, type, geom` sont celles attendues, et les postes sources ont le type `poste_source`. `exemples/verifier_compatibilite_topologie.sh` le fait et vérifie le résultat. À annoncer dans la réponse :
- retirer d'abord les tronçons `hors_tension` et `en_projet` si on veut le réseau en service ;
- les boucles HTA trouvées sont normales tant que les points d'ouverture ne sont pas connus ;
- les découpages aux limites de commune créent des nœuds de degré 2 sans conséquence ;
- pour un contrôle HTB seul, considérer les postes RTE comme sources (ajouter `poste_htb` à `types_source`).

**Proximité DT-DICT** : la vue `reseau_elec.ouvrages_dtdict` a les colonnes de `src_ouvrages` du skill `proximite-dt-dict`, avec une classe de précision vide (donc traitée comme C).

## Sortie
- `reseau_elec.troncons(id, id_source, nom, gestionnaire, tension_kv, tension_origine, domaine, pose, etat_exploitation, code_insee, table_source, geom, attributs)` en MultiLineString 2154 ;
- `reseau_elec.postes(id, id_source, nom, type, type_origine, gestionnaire, tension_origine, etat, code_insee, table_source, geom, attributs)` ;
- `reseau_elec.ouvrages_dtdict`, `reseau_elec.controles`, `reseau_elec.champs_utilises`, `reseau_elec.resume`.

`attributs` garde tous les champs d'origine en JSON. Dans la réponse : longueur par domaine et par pose, nombre de postes par type, contrôles par type, hypothèses (tension HTA retenue, champs utilisés), rappel de la licence et de la précision.

## Dans QGIS sans PostGIS
Ouvrir les GeoJSON, *Reprojeter la couche* en EPSG:2154, *Fusionner des couches vecteur*, puis une colonne `tension_kv` avec la calculatrice de champs (`CASE WHEN "tension" = 'HTA' THEN 20 ...`). Le skill de topologie a besoin de PostGIS et pgRouting.

## Exemple
`exemples/` contient des extraits fictifs au format des exports RTE et Agence ORE (`donnees_exemple.sql`) : lignes 63 et 225 kV, une ligne hors tension, un départ HTA aérien et souterrain avec une quasi-connexion, de la BT, un poste source et des postes HTA/BT dont un en double. Avec les résultats attendus (`resultats_attendus.md`), le test automatique (`verifier_resultats.sql`), le test d'enchaînement avec le skill de topologie (`verifier_compatibilite_topologie.sh`) et des demandes types (`demandes_exemple.md`).
