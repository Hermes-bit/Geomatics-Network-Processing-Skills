---
name: vegetation-lidar-hd
description: Repère la végétation trop haute ou trop proche des lignes électriques aériennes (HTB, HTA, BT) et des voies ferrées à partir des nuages de points classés LiDAR HD de l'IGN (dalles LAZ / COPC), avec risque de chute d'arbre, hauteur excessive dans l'emprise et tronçons à surveiller, en sortie CSV et GeoJSON pour QGIS. À utiliser pour toute demande d'élagage, de débroussaillage, de maîtrise de la végétation, de programme d'entretien ou de risque de chute d'arbres le long d'un réseau, à partir du LiDAR.
---

# Végétation près des lignes et des voies (LiDAR HD de l'IGN)

Ce skill mesure, tronçon par tronçon, la hauteur de la végétation autour d'une ligne électrique aérienne ou d'une voie ferrée et classe chaque tronçon par priorité d'intervention. Un script Python testé est fourni : `scripts/vegetation_lidar.py` (dépendances : `numpy` et `laspy[lazrs]`).

## Règle d'or
- Les seuils par défaut sont des **valeurs de départ**, pas une règle d'entretien. Les distances d'élagage dépendent du gestionnaire (RTE, Enedis, SNCF Réseau), de la tension, du type de conducteur et des conventions locales. Demander les règles de l'utilisateur ; sinon annoncer les valeurs utilisées dans chaque réponse.
- Les câbles ne sont pas une classe du LiDAR HD : le script raisonne sur l'axe de la ligne au sol, pas sur la hauteur réelle des conducteurs ni sur leur balancement.
- Le LiDAR date du vol : la végétation a poussé depuis. Toujours donner la date des dalles.
- Le résultat sert à préparer une visite ou un programme d'élagage. Il ne remplace pas une inspection sur le terrain.

## Le LiDAR HD de l'IGN
- Nuages de points classés, diffusés en **dalles de 1 km × 1 km** au format LAZ 1.4, aussi en **COPC** (lecture partielle par requêtes HTTP). Au moins 10 impulsions/m². Précision annoncée : 10 cm en altitude, 50 cm en planimétrie. Licence Ouverte 2.0. Couverture de la métropole et des DROM (hors Guyane) prévue pour 2026 : vérifier que la zone est acquise.
- Téléchargement : [geoservices.ign.fr/lidarhd](https://geoservices.ign.fr/lidarhd) et le catalogue [cartes.gouv.fr](https://cartes.gouv.fr/catalogue/dataset/IGNF_NUAGES-DE-POINTS-LIDAR-HD), où l'on choisit les dalles sur une carte ; fiche data.gouv.fr « Nuages de points LiDAR HD ». En métropole, les dalles sont en Lambert 93, altitudes IGN69.
- Classes utilisées : 1 non classé, **2 sol**, 3 végétation basse (0-50 cm), **4 végétation moyenne (50 cm-1,50 m)**, **5 végétation haute (plus de 1,50 m)**, 6 bâtiment, 9 eau, 17 tablier de pont, 64 sursol pérenne (pylônes, antennes, éoliennes…), 66 points virtuels, 67 divers bâtis.
- Produits dérivés : MNT, MNS et MNH (hauteur du sursol) en GeoTIFF, au pas de 50 cm. Ils permettent une première carte rapide dans QGIS (voir plus bas), mais le MNH ne distingue pas un arbre d'un bâtiment : le nuage classé est plus fiable.

## Avant de commencer : informations à obtenir
1. Les lignes ou voies à traiter, en Lambert 93 (GeoJSON, ou exportées depuis PostGIS ou QGIS). Le skill `import-donnees-rte-enedis` donne les lignes électriques aériennes, `import-donnees-sncf-reseau` les voies.
2. Pour chaque type : largeur du couloir analysé, largeur de l'emprise à dégager, hauteur maximale tolérée dans l'emprise, marges.
3. Les dalles LiDAR HD qui couvrent la zone (le script signale les tronçons sans données).

## Étapes

### 1. Préparer les lignes
GeoJSON en EPSG:2154 avec les propriétés `id` et `type` (`ligne_aerienne` ou `voie_ferree`). Les propriétés `couloir_m`, `emprise_m`, `h_max_emprise_m`, `marge_chute_m`, `marge_surveillance_m` remplacent les valeurs par défaut pour une ligne. Exemple depuis PostGIS :
```bash
ogr2ogr -f GeoJSON lignes.geojson PG:"dbname=ma_base" -sql "SELECT id, 'ligne_aerienne' AS type, geom FROM reseau_elec.troncons WHERE pose = 'aerien' AND domaine = 'HTA'"
```

### 2. Lancer l'analyse
```bash
pip install numpy "laspy[lazrs]"
python3 scripts/vegetation_lidar.py --lignes lignes.geojson --sortie resultats/ dalles/*.copc.laz
```
Le script :
- ne lit que les points proches des lignes (rectangle englobant plus le couloir) ;
- calcule un modèle de sol de 1 m à partir des classes 2 (sol) et 9 (eau), en bouchant les trous sous les arbres denses ;
- calcule la hauteur de chaque point de végétation (classes 4 et 5 par défaut) au-dessus du sol ;
- découpe chaque ligne en tronçons de 25 m, de chaque côté (gauche et droite dans le sens de numérisation) ;
- applique les règles et donne une priorité à chaque tronçon.

### 3. Les règles
| Règle | Condition | Priorité |
|---|---|---|
| hauteur_excessive | végétation plus haute que `h_max_emprise_m` à moins de `emprise_m` de l'axe | 1_intervenir |
| risque_chute | hors emprise, hauteur > distance à l'axe − `marge_chute_m` : l'arbre peut atteindre l'axe en tombant | 1_intervenir |
| à surveiller | arbre à moins de `marge_surveillance_m` de pouvoir atteindre l'axe, ou végétation à moins de 1 m de la hauteur maximale dans l'emprise | 2_surveiller |
| sans données | pas de points sol à proximité : dalle manquante ou zone non acquise | sans_donnees |

Valeurs par défaut :
| Type | Couloir | Emprise | Hauteur max dans l'emprise | Marge de chute | Marge de surveillance |
|---|---|---|---|---|---|
| ligne_aerienne | 30 m | 5 m | 4 m | 1 m | 3 m |
| voie_ferree | 25 m | 4 m | 1,5 m | 1 m | 3 m |

Pour changer toutes les valeurs : `--parametres mes_regles.json`, par exemple `{"pas_m": 50, "types": {"ligne_aerienne": {"emprise_m": 10}}}`.

## Sortie
- `troncons_vegetation.csv` et `.geojson` : `id_ligne, type, nom, troncon, abscisse_debut_m, abscisse_fin_m, cote, nb_points_vegetation, hauteur_max_m, distance_min_m, marge_chute_min_m, nb_points_hauteur_excessive, nb_points_risque_chute, priorite` (+ `wkt_l93` dans le CSV). `marge_chute_min_m` négative : un arbre atteint l'axe en tombant.
- `points_signales.geojson` : cellules de 2 m où un point est signalé, avec le motif et la hauteur, pour localiser l'arbre dans QGIS.
- `bilan.json` : paramètres utilisés, dalles (date, SCR), statistiques, nombre de tronçons par priorité, avertissements.

Dans la réponse : longueur analysée, nombre de tronçons par priorité, les 5 tronçons les plus urgents (ligne, abscisse, côté, hauteur, distance), les tronçons sans données, la date du LiDAR, et les règles appliquées.

## Dans QGIS sans Python
Avec le MNH LiDAR HD (50 cm) : *Tampon* sur les lignes (emprise, couloir), *Statistiques de zone* du MNH par tampon, ou *Découper un raster selon une couche de masque* puis *Calculatrice raster* (`"mnh@1" > 4`). Cela donne une carte des hauteurs, mais pas la règle de chute (qui dépend de la distance à l'axe), et le MNH compte les bâtiments et les pylônes comme de la hauteur. Avec PDAL (livré avec QGIS), `filters.hag_delaunay` calcule aussi la hauteur au-dessus du sol sur le nuage.

## Exemple
`exemples/generer_nuage_exemple.py` crée un petit nuage fictif au format LiDAR HD (LAS 1.4, classes IGN) avec une ligne HTA et une voie ferrée, et des arbres placés pour tester chaque règle. `exemples/test_vegetation.py` lance l'analyse et la compare aux résultats attendus (`resultats_attendus.md`). Demandes types dans `demandes_exemple.md`.
