---
name: controle-topologie-reseau
description: Contrôle la topologie d'un réseau linéaire électrique (HTA, HTB, BT) ou ferroviaire dans PostGIS ou QGIS. Détecte extrémités pendantes, quasi-connexions, croisements sans nœud, composantes et postes isolés, tronçons trop courts, boucles fermées en exploitation radiale et attributs incohérents, puis produit une table d'anomalies et un résumé. À utiliser dès qu'on demande de vérifier, valider, auditer ou nettoyer la topologie ou la connectivité d'un réseau.
---

# Contrôle de topologie d'un réseau linéaire

Ce skill vérifie qu'un réseau de lignes (câbles, lignes aériennes, voies ferrées) forme un graphe cohérent, et livre la liste des anomalies localisées. Il s'appuie sur PostGIS et pgRouting, ou sur QGIS seul. Deux versions testées sont fournies : `scripts/controles_topologie.sql` (PostGIS) et `qgis/controle_topologie_reseau.py` (algorithme de traitement QGIS).

## Règle d'or

**Ne jamais modifier les données source sans l'accord explicite de l'utilisateur.** Toutes les réparations se font dans une copie de travail (schéma `topo_controle`). Si l'utilisateur veut corriger la source, proposer les requêtes de correction, les lui montrer, et attendre son accord.

## Avant de commencer : questions à poser (ou hypothèses à annoncer)

1. Nom des tables tronçons et postes, et colonnes utiles (identifiant, tension, mode de pose ou niveau, état d'exploitation, sens).
2. Type de réseau : électrique radial (HTA, BT), maillé (HTB), ou ferroviaire. Le contrôle des boucles ne s'applique qu'au radial.
3. Tolérances. Valeurs par défaut si l'utilisateur ne sait pas :
   - accrochage (extrémités considérées identiques) : 0,01 m ;
   - quasi-connexion (extrémités presque raccordées à signaler) : 1 m ;
   - longueur minimale d'un tronçon : 1 m.
4. Quels postes alimentent le réseau (postes sources, sous-stations) pour repérer les parties non alimentées.

Si l'utilisateur ne répond pas, partir des valeurs par défaut et le dire clairement dans le résumé.

## Étapes

### 1. Vérifier le système de coordonnées
- Contrôler `ST_SRID(geom)` : on attend **2154 (Lambert 93)** en métropole. Les distances et tolérances sont en mètres ; un réseau en 4326 (degrés) rend les tolérances absurdes.
- Si le SRID est autre (CC46, 3857, 4326, ou 0), le signaler. Reprojeter dans la copie de travail avec `ST_Transform(geom, 2154)` ; si le SRID vaut 0, demander le système d'origine plutôt que de deviner.
- Outre-mer : RGAF09 / UTM 20N (5490) pour les Antilles, RGR92 / UTM 40S (2975) pour La Réunion, etc.

### 2. Réparer dans la copie de travail
- `ST_MakeValid` puis `ST_CollectionExtract(..., 2)` pour ne garder que les lignes.
- `ST_LineMerge` pour fusionner les MultiLineString contiguës (cas fréquent après un import de shapefile). Un tronçon qui reste multi-parties est une vraie discontinuité : anomalie.
- Doublons : `ST_Equals` (indépendant du sens). Garder le plus petit identifiant, exclure les autres du graphe et les signaler.
- Ne pas utiliser `ST_Snap` ou `ST_SnapToGrid` sur la géométrie complète sans le dire : cela déplace les sommets.

### 3. Construire le graphe
- Nœuds = extrémités des tronçons accrochées sur une grille de la tolérance (`ST_SnapToGrid(ST_StartPoint(geom), tol)`). C'est l'équivalent de `pgr_extractVertices` sur des géométries accrochées.
- `pgr_createTopology` fonctionne aussi mais est **obsolète depuis pgRouting 3.8** ; le mentionner si l'utilisateur l'emploie. Avec une tolérance de 1 m, il raccorde silencieusement les quasi-connexions : c'est pourquoi on accroche à 0,01 m et on signale à part ce qui est entre 0,01 et 1 m.
- Calculer le degré de chaque nœud et rattacher les nœuds aux postes à moins du seuil.

### 4. Contrôles
| Contrôle | Méthode | Gravité par défaut |
|---|---|---|
| Extrémité pendante | nœud de degré 1 qui n'est pas sur un poste | mineure (normale en bout d'antenne, à confirmer) |
| Quasi-connexion | nœud de degré 1 à moins du seuil d'un autre tronçon (`ST_DWithin`) sans y être raccordé | majeure |
| Croisement sans nœud | `ST_Crosses` entre deux tronçons **de même pose ou niveau** | majeure |
| Franchissement | `ST_Crosses` entre poses différentes (aérien / souterrain, pont / voie) : normal | info |
| Composante isolée | `pgr_connectedComponents` ; composante sans poste source | majeure |
| Poste isolé | aucun tronçon à moins du seuil | majeure |
| Tronçon trop court | `ST_Length < longueur_min` | mineure |
| Boucle fermée (radial) | retirer les tronçons « NO » puis `pgr_biconnectedComponents` : toute composante biconnexe de plus d'un tronçon est une boucle sans point d'ouverture | majeure |
| Tronçon bouclé sur lui-même | source = target | majeure |
| Attributs | valeur manquante, tension hors liste normalisée, incohérence de tension de part et d'autre d'un nœud sans poste | mineure |
| Sens (ferroviaire, réseaux orientés) | tronçons consécutifs de sens opposé, à contrôler si un attribut de sens existe | mineure |

Prendre en compte les franchissements : sans attribut de pose ou de niveau, **ne pas** conclure qu'un croisement est une erreur ; le classer « à vérifier » et le dire.

### 5. Sortie
- Table `topo_controle.anomalies(id, type, gravite, id_objet, detail, geom)` en Lambert 93, ouvrable directement dans QGIS (Couche > Ajouter une couche PostGIS), à styler par `gravite`.
- Vue `topo_controle.resume` : nombre d'anomalies par gravité et type.
- Dans la réponse : un résumé court (combien d'anomalies bloquantes, majeures, mineures), les 3 à 5 problèmes les plus importants avec leur identifiant, les hypothèses retenues (tolérances, champs utilisés) et les anomalies qui découlent d'une autre (une quasi-connexion crée aussi une extrémité pendante et souvent une composante isolée).
- Proposer ensuite, sans les exécuter, les corrections possibles (raccorder une quasi-connexion, supprimer un doublon, découper au croisement avec `ST_Split`).

## Utiliser le script fourni
1. Lire `scripts/controles_topologie.sql`.
2. Adapter la section 0 : paramètres, vues `src_troncons` et `src_postes` (correspondance des colonnes ; mettre `NULL::text AS pose` si la colonne n'existe pas), types de postes sources.
3. Exécuter, puis lire `topo_controle.resume` et `topo_controle.anomalies`.

Si l'utilisateur n'a pas pgRouting, les composantes peuvent se calculer avec `ST_ClusterIntersecting` ou `ST_ClusterDBSCAN(geom, eps := tol, minpoints := 1)`, mais la détection des boucles demande pgRouting ou un parcours en Python (NetworkX).

## Dans QGIS sans PostGIS
Utiliser l'algorithme fourni `qgis/controle_topologie_reseau.py` : mêmes contrôles, mêmes types d'anomalies et mêmes gravités que le script SQL, y compris les boucles en radial et les composantes non alimentées (graphe calculé en Python, aucune extension à installer). Testé avec QGIS 3.34.
1. Boîte à outils Traitements > icône Python > *Ajouter un script à la boîte à outils…* > choisir le fichier.
2. Lancer *Scripts > Géomatique des réseaux > Contrôle de topologie d'un réseau*, choisir la couche des tronçons et, si elles existent, celle des postes, puis faire correspondre les champs (identifiant, tension, pose, état d'exploitation, type de poste). Les champs facultatifs peuvent rester vides : le dire dans le résumé (sans pose, tout croisement est signalé ; sans état, aucune boucle n'est considérée comme ouverte).
3. Sorties : *Anomalies ponctuelles*, *Anomalies linéaires* (mêmes champs que `topo_controle.anomalies`) et *Résumé des anomalies*.
La couche doit être dans un SCR projeté en mètres : l'algorithme refuse une couche en degrés et prévient si le SCR n'est pas Lambert 93.

Outils natifs complémentaires : *Vérifier la validité*, *Vérificateur de topologie*, *Accrocher les géométries à la couche*.

## Rapport à partager
Pour livrer le résultat à quelqu'un qui n'a ni PostGIS ni QGIS ouvert, produire un rapport avec `rapport/rapport_anomalies.py` (en ligne de commande avec le Python de QGIS ; sous Windows, `python-qgis` dans l’« OSGeo4W Shell ») :
- un **PDF** : carte des anomalies colorées par gravité sur le fond du réseau, résumé par type, puis liste détaillée ;
- une **carte HTML** interactive en un seul fichier (fond OpenStreetMap, filtres par gravité, fiche de chaque anomalie au clic), à envoyer par courriel ou à déposer sur un intranet.
Depuis PostGIS, exporter d'abord les anomalies avec `rapport/exporter_anomalies_postgis.sh` (deux couches, points et lignes). Passer les hypothèses (tolérances, champs utilisés) avec `--note` pour qu'elles figurent sur le rapport.

## Exemple
Le dossier `exemples/` contient un petit réseau HTA avec des anomalies volontaires (`donnees_exemple.sql` pour PostGIS, `reseau_exemple.gpkg` pour QGIS), les résultats attendus (`resultats_attendus.md`), des demandes types (`demandes_exemple.md`), et le rapport produit sur ces données (`rapport_exemple.pdf`, `carte_exemple.html`).
