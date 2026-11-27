---
name: referencement-pk-ferroviaire
description: Convertit des points kilométriques ferroviaires (PK au format km+m, ex. 15+342) en coordonnées Lambert 93 et inversement avec PostGIS, en calant l'axe de la ligne sur les bornes et en gérant les sauts de PK. Traite aussi les décalages latéraux et les événements linéaires (de PK à PK). À utiliser pour toute demande de positionnement par PK, de référencement linéaire, de localisation d'objets le long d'une voie ou de conversion PK / XY.
---

# Référencement linéaire ferroviaire (PK <-> coordonnées)

Ce skill positionne des objets le long d'une ligne ferroviaire à partir de leur PK, ou retrouve le PK d'un objet à partir de ses coordonnées. Deux versions testées sont fournies : `scripts/referencement_pk.sql` (PostGIS) et `qgis/referencement_pk_ferroviaire.py` (algorithme de traitement QGIS, sans PostGIS).

## Ce qu'il faut savoir sur les PK
- Un PK s'écrit `km+m` : `15+342` = 15 342 m depuis l'origine de la ligne. Accepter aussi `15+342.5`, `015+342`, des espaces. Toujours renvoyer le même format.
- Un PK n'est **pas** une distance mesurée sur l'axe : les bornes ont été posées à une époque, les tracés ont été rectifiés depuis. Un kilomètre de PK peut mesurer 980 ou 1 020 m sur le terrain.
- **Sauts de PK** : à certains endroits le PK « saute » (ex. `15+400 = 15+650`). Une lacune fait que des PK n'existent pas ; un chevauchement fait qu'un PK existe deux fois. Il faut les connaître pour convertir juste.
- Les PK sont propres à une ligne (code ligne, ex. 830000) et souvent à une voie. Ne jamais mélanger deux lignes.

## Avant de commencer : informations à obtenir
1. La couche d'axe (table, colonne code ligne, voie) et le code ligne à traiter.
2. Les bornes kilométriques (points avec leur PK) ou, à défaut, le PK de l'origine de l'axe.
3. Les sauts de PK connus (table ou liste).
4. Les objets à convertir (CSV de PK ou de coordonnées), leur SCR, et la convention de décalage s'il y en a un.

S'il manque les bornes, on peut seulement calibrer à l'échelle 1 depuis l'origine : le dire, et marquer chaque résultat « sans calage sur bornes ».

## Étapes

### 1. Préparer l'axe
- Filtrer **une** ligne (et une voie). Travailler en **Lambert 93 (2154)** ; reprojeter avec `ST_Transform` sinon.
- Fusionner les morceaux : `ST_LineMerge(ST_Collect(geom))`. Le résultat doit être un seul `LINESTRING`. S'il reste un `MULTILINESTRING`, l'axe a des trous ou des embranchements : s'arrêter et les montrer à l'utilisateur plutôt que de deviner.
- Orienter l'axe dans le sens des PK croissants : si `ST_LineLocatePoint` de la borne de plus petit PK est plus grand que celui de la borne de plus grand PK, appliquer `ST_Reverse`.

### 2. Caler sur les bornes
- Pour chaque borne : position relative `ST_LineLocatePoint(axe, borne)` et distance à l'axe. Une borne à plus de 20 m de l'axe est suspecte.
- Ajouter les sauts : deux points de calage à la même position, avec PK amont et PK aval.
- Vérifier que le PK croît le long de l'axe ; sinon une borne est mal placée ou mal saisie, la signaler.
- Découper l'axe entre points de calage successifs avec `ST_LineSubstring`, puis mesurer chaque morceau avec `ST_AddMeasure(morceau, pk_debut, pk_fin)`. On obtient un axe mesuré par morceaux, exact au droit de chaque borne.
- Comparer PK et longueur réelle de chaque morceau : un écart de plus de 5 % trahit souvent un saut de PK non déclaré.
- Avant la première et après la dernière borne : extrapoler à l'échelle 1 et marquer « extrapolé ».

### 3. Convertir
- **PK -> point** : trouver le morceau qui contient le PK, puis `ST_LocateAlong(morceau_mesure, pk, decalage)`. Le décalage est **positif à gauche** dans le sens des PK croissants (convention PostGIS) ; l'annoncer et inverser si l'utilisateur a l'autre convention. Équivalent sans mesure : `ST_LineInterpolatePoint(ST_LineSubstring(...), fraction)`.
- **Point -> PK** : morceau le plus proche, `ST_InterpolatePoint(morceau_mesure, point)` pour la mesure (ou `ST_LineLocatePoint` puis interpolation entre les PK des bornes), distance `ST_Distance`, et côté (gauche / droite) par produit vectoriel. **Alerte si la distance à l'axe dépasse 20 m** : l'objet n'est probablement pas sur cette ligne ou cette voie.
- **Événement linéaire** (de PK à PK) : `ST_LocateBetween(morceau_mesure, pk_debut, pk_fin)` sur chaque morceau concerné, puis `ST_LineMerge(ST_Union(...))`. Si l'intervalle contient une lacune, la longueur terrain est plus courte que l'écart de PK : le dire.
- PK dans une lacune ou hors de la ligne : ne pas inventer de position, renvoyer un avertissement.

### 4. Sortie
Un CSV par conversion, avec au minimum :
- PK -> XY : `id, code_ligne, pk, decalage_m, x_l93, y_l93, methode, avertissement`
- XY -> PK : `id, x_l93, y_l93, pk, distance_axe_m, decalage_m, methode, avertissement`
- Événements : `id, pk_debut, pk_fin, longueur_terrain_m, avertissement, wkt_l93`

`methode` dit comment le résultat a été obtenu (interpolation entre bornes, extrapolation hors bornes, décalage). `avertissement` est vide quand tout va bien. Dans la réponse, résumer le nombre de conversions réussies, les avertissements, et les hypothèses (code ligne, voie, convention de décalage, sauts utilisés).

## Utiliser le script fourni
1. Lire `scripts/referencement_pk.sql`.
2. Adapter la section 0 : code ligne, tolérances, vues `src_axes`, `src_bornes`, `src_sauts`.
3. Exécuter. Le script s'arrête avec un message clair si l'axe ne se fusionne pas en une seule ligne.
4. Utiliser les fonctions `pk_ref.pk_vers_point`, `pk_ref.point_vers_pk`, `pk_ref.evenement_lineaire`, `pk_ref.pk_vers_m` et `pk_ref.m_vers_pk`. `exemples/lancer_exemple.sql` montre comment charger des CSV et écrire les résultats avec `\copy`.

## Dans QGIS sans PostGIS
Utiliser l'algorithme fourni `qgis/referencement_pk_ferroviaire.py` : même calage sur les bornes, mêmes sauts de PK, même convention de décalage et mêmes avertissements que le script SQL. Testé avec QGIS 3.34.
1. Boîte à outils Traitements > icône Python > *Ajouter un script à la boîte à outils…* > choisir le fichier.
2. Lancer *Scripts > Géomatique des réseaux > Référencement PK ferroviaire* : couche d'axes (avec code ligne et voie à traiter), bornes kilométriques, sauts de PK s'il y en a.
3. Donner une ou plusieurs entrées selon le besoin : table de PK à convertir (CSV chargé sans géométrie, avec un champ décalage facultatif), couche de points à localiser, table d'événements de PK à PK.
4. Sorties : *PK convertis en points*, *Points localisés en PK*, *Événements linéaires* (avec les attributs d'origine, la méthode et l'avertissement) et *Points de calage* pour contrôler les bornes (distance à l'axe, PK non croissant).
L'algorithme s'arrête avec un message clair si l'axe ne se fusionne pas en une seule ligne ou s'il est en degrés.

## Sources de données
Les données ouvertes de SNCF Réseau (data.sncf.com) publient notamment les lignes du réseau ferré national avec leur code ligne et des points kilométriques : à vérifier au moment de l'usage, les jeux et leurs champs évoluent.

## Exemple
`exemples/` contient une ligne fictive avec un axe en deux morceaux dont un à l'envers, des bornes imprécises et un saut de PK (`donnees_exemple.sql` pour PostGIS, `ligne_exemple.gpkg` pour QGIS), des CSV d'entrée, les résultats attendus (`resultats_attendus.md`) et des demandes types (`demandes_exemple.md`).
