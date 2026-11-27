---
name: import-donnees-sncf-reseau
description: Importe les données ouvertes de SNCF Réseau (lignes du réseau ferré national, gares, passages à niveau, ouvrages d'art comme passerelles, ponts-route et passages souterrains) dans PostGIS en Lambert 93, prêtes pour QGIS, avec contrôle des PK et détection des sauts de PK. Produit aussi les axes, bornes et sauts attendus par le skill referencement-pk-ferroviaire. À utiliser pour télécharger, charger, nettoyer ou cartographier les données SNCF Réseau ou data.sncf.com, ou pour préparer un référencement PK sur une vraie ligne.
---

# Import des données ouvertes SNCF Réseau

Ce skill charge les fichiers publiés par SNCF Réseau, les met en Lambert 93, contrôle leurs PK et les range en couches propres. Il prépare directement les entrées du skill `referencement-pk-ferroviaire`. Un script PostGIS testé est fourni : `scripts/import_sncf_reseau.sql`.

## Règle d'or
- Ne jamais modifier les tables brutes `sncf_brut` : tout est recréé dans le schéma `sncf`.
- Ne pas deviner un champ : le script cherche les noms connus et s'arrête en listant les champs présents s'il ne trouve pas un champ obligatoire.
- Les données sont sous **licence ODbL** : le rappeler (citer « SNCF Réseau » et partager à l'identique les bases dérivées diffusées).

## Les sources (portail ressources.data.sncf.com, republiées sur data.gouv.fr)
| Couche | Identifiant du jeu | Contenu |
|---|---|---|
| Lignes | `formes-des-lignes-du-rfn` | Lignes du réseau ferré national par tronçon, avec code ligne, rang du tronçon, PK de début et de fin, statut (exploitée, neutralisée, fermée…) |
| Voies | `fichier-de-formes-des-voies-du-reseau-ferre-national` | Voies principales et voies de service, plus lourd (40 Mo) |
| Gares | `liste-des-gares` | Gares voyageurs et fret, **projetées sur la ligne** (la position peut différer du bâtiment) |
| Passages à niveau | `liste-des-passages-a-niveau` | Centre du croisement route / voie, classe du PN |
| Ouvrages d'art | `liste-des-passerelles`, `liste-des-ponts-route`, `liste-des-passages-souterrains` | Ouvrages de plus de 2 m, projetés sur la ligne |

Chaque jeu se télécharge en CSV, GeoJSON ou shapefile depuis sa page `https://ressources.data.sncf.com/explore/dataset/<identifiant>/` (onglet Export), ou par l'API Opendatasoft :
`https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/<identifiant>/exports/geojson`.
Préférer le **GeoJSON** : il est en WGS84 (EPSG:4326) sans ambiguïté. Les pages annoncent aussi des coordonnées « Lambert 93 et WGS84 (EPSG:3857) » : 3857 est en fait le Web Mercator, d'où l'intérêt de contrôler le SCR du fichier réellement téléchargé.

Les noms de champs ci-dessous sont ceux des exports au moment de l'écriture du skill (`code_ligne`, `lib_ligne`, `rg_troncon`, `pkd`, `pkf`, `pk`, `libelle`…). Ils peuvent changer : le script essaie plusieurs noms (table `sncf.correspondance`) et `sncf.champs_utilises` dit lequel a servi.

## Avant de commencer : informations à obtenir
1. Les jeux voulus et la zone (France entière, une région, quelques codes ligne).
2. La base PostGIS cible, et si l'utilisateur a GDAL (`ogr2ogr`, livré avec QGIS).
3. Si le but est un référencement PK : le code ligne à traiter.

## Étapes

### 1. Charger les fichiers bruts
```bash
psql -d ma_base -c "CREATE SCHEMA IF NOT EXISTS sncf_brut"
ogr2ogr -f PostgreSQL PG:"dbname=ma_base" formes-des-lignes-du-rfn.geojson -nln sncf_brut.lignes -lco GEOMETRY_NAME=geom -overwrite
ogr2ogr -f PostgreSQL PG:"dbname=ma_base" liste-des-gares.geojson -nln sncf_brut.gares -lco GEOMETRY_NAME=geom -overwrite
ogr2ogr -f PostgreSQL PG:"dbname=ma_base" liste-des-passages-a-niveau.geojson -nln sncf_brut.passages_niveau -lco GEOMETRY_NAME=geom -overwrite
ogr2ogr -f PostgreSQL PG:"dbname=ma_base" liste-des-passerelles.geojson -nln sncf_brut.ouvrages_passerelles -lco GEOMETRY_NAME=geom -overwrite
```
Une table `sncf_brut.ouvrages_<type>` par fichier d'ouvrages : elles sont toutes réunies dans `sncf.ouvrages` avec `type_ouvrage = <type>`. Seule `sncf_brut.lignes` est obligatoire.

### 2. Importer
`psql -d ma_base -f scripts/import_sncf_reseau.sql`. Le script :
- reprojette en Lambert 93 (2154) ; un SRID absent est supposé WGS84 et signalé ;
- répare et éclate les géométries (`ST_MakeValid`, `ST_LineMerge`, `ST_Dump`) ;
- lit les PK au format `km+m` (`012+345`) et signale ceux qui sont illisibles ;
- compare l'écart de PK de chaque tronçon à sa longueur mesurée (plus de 5 % = saut de PK probable dans le tronçon).

### 3. Préparer le référencement PK
- Les tronçons ne sont pas toujours numérisés dans le sens des PK. Le script les place sur l'axe fusionné de leur ligne et donne le plus petit PK à l'extrémité amont.
- À chaque jonction entre tronçons successifs, un PK différent de part et d'autre est un **saut de PK** (lacune si le PK aval est plus grand, chevauchement sinon). Il va dans `sncf.sauts_pk`.
- Les autres extrémités de tronçons deviennent des bornes (`sncf.bornes_pk`).
- Une ligne qui reste en plusieurs morceaux après fusion (trou, embranchement) est signalée `axe_discontinu` : le skill PK ne pourra pas la traiter telle quelle.
- Une ligne en un seul tronçon : le sens des PK est supposé être celui de la numérisation (`sens_suppose`), à vérifier avec une gare ou un PN.

Pour enchaîner avec le skill PK, remplacer dans sa section 0 :
```sql
'830000'::text AS code_ligne            ->  '<code ligne>'::text AS code_ligne
FROM ferro_exemple.axes a ... a.voie = 'V1'  ->  FROM sncf.axes a ... a.voie = 'axe'
FROM ferro_exemple.bornes_pk b          ->  FROM sncf.bornes_pk b
FROM ferro_exemple.sauts_pk s           ->  FROM sncf.sauts_pk s
```
`exemples/verifier_compatibilite_pk.sh` fait exactement cela et vérifie le résultat.

Les PK des gares et des ouvrages ne servent pas de bornes : ces objets sont projetés sur la ligne par SNCF Réseau, ce qui en fait de bons contrôles mais des bornes approximatives. On peut les ajouter à `sncf.bornes_pk` si l'utilisateur le demande, en le signalant.

### 4. Contrôler les objets ponctuels
Pour les gares, PN et ouvrages : PK illisible, objet à plus de 20 m de sa ligne, code ligne absent de la couche des lignes, PK hors de l'intervalle de la ligne.

## Sortie
- `sncf.lignes(id, code_ligne, lib_ligne, statut, rg_troncon, pkd, pkf, pkd_m, pkf_m, geom, attributs)` ;
- `sncf.gares`, `sncf.passages_niveau`, `sncf.ouvrages` (points, avec `code_ligne`, `pk`, `pk_m`, `attributs` qui garde tous les champs d'origine en JSON) ;
- `sncf.axes`, `sncf.bornes_pk`, `sncf.sauts_pk` : entrées du skill PK ;
- `sncf.controles(couche, id_objet, type, detail, geom)` et `sncf.champs_utilises`.

Dans la réponse : nombre d'objets importés par couche, sauts de PK trouvés, contrôles par type, champs utilisés, et le rappel de la licence ODbL. Pour QGIS : Couche > Ajouter une couche PostGIS, schéma `sncf`.

## Dans QGIS sans PostGIS
Ouvrir le GeoJSON, *Reprojeter la couche* en EPSG:2154, *Réparer les géométries*, puis filtrer par `code_ligne`. La détection des sauts de PK et le sens des tronçons demandent le script.

## Exemple
`exemples/` contient des extraits fictifs au format des exports (`donnees_exemple.sql`) : une ligne en trois tronçons dont un à l'envers et un saut de PK, un raccordement, des gares, PN et ouvrages avec des erreurs. Avec les résultats attendus (`resultats_attendus.md`), le test automatique (`verifier_resultats.sql`), le test d'enchaînement avec le skill PK (`verifier_compatibilite_pk.sh`) et des demandes types (`demandes_exemple.md`).
