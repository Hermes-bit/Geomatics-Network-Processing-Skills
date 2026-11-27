# Résultats attendus sur le jeu d'exemple

Réseau HTA 20 kV fictif (schéma `reseau_exemple`), 16 tronçons et 7 postes en Lambert 93.

```
psql -d ma_base -f exemples/donnees_exemple.sql
psql -d ma_base -f scripts/controles_topologie.sql
```

## Résumé attendu

| Gravité | Type | Nombre |
|---|---|---|
| majeure | boucle_fermee_radial | 1 |
| majeure | composante_isolee | 3 |
| majeure | croisement_sans_noeud | 1 |
| majeure | doublon_geometrique | 1 |
| majeure | poste_isole | 1 |
| majeure | quasi_connexion | 1 |
| mineure | attribut_incoherent | 1 |
| mineure | attribut_manquant | 1 |
| mineure | extremite_pendante | 4 |
| mineure | tension_incoherente_noeud | 1 |
| mineure | troncon_trop_court | 1 |
| info | franchissement | 1 |
| info | troncon_multi_fusionne | 1 |

## Anomalies volontaires et ce qu'on doit trouver

| Tronçon / poste | Anomalie placée | Détection attendue |
|---|---|---|
| T16 | doublon exact de T3 | `doublon_geometrique` sur 16, exclu du graphe |
| T7 | MultiLineString en deux morceaux contigus | `troncon_multi_fusionne` (info), fusionné sans erreur |
| T11 | démarre à 0,6 m du nœud (1500, 0) | `quasi_connexion` (0,60 m du tronçon 6), plus `extremite_pendante` et `composante_isolee` qui en découlent |
| T12 | croise T6 sans nœud, aérien / aérien | `croisement_sans_noeud` 6/12, plus `composante_isolee` qui en découle |
| T13 | souterrain qui passe sous T2 | **pas** d'anomalie : seulement `franchissement` (info) |
| T14 | tronçon isolé loin de tout | `composante_isolee` et 2 `extremite_pendante` |
| T9 | bout libre, tension 21 kV | `extremite_pendante`, `attribut_incoherent`, et `tension_incoherente_noeud` au nœud (500, 500) où T9 rejoint des tronçons 20 kV sans poste |
| T10 | tension vide | `attribut_manquant` |
| T15 | 0,3 m de long | `troncon_trop_court` |
| T3, T6, T7, T8, T15 | boucle sans tronçon NO | `boucle_fermee_radial` sur ces 5 tronçons |
| T1, T2, T3, T4, T5 | boucle ouverte par T4 (NO) | **pas** d'anomalie |
| Poste 8 « Les Saules » | aucun tronçon à proximité | `poste_isole` |

Les numéros de nœuds (`noeud 14`…) dépendent de l'ordre de construction et peuvent varier ; les identifiants de tronçons, eux, sont stables.

Les doublons sont retirés **avant** le graphe : sinon T3 et T16 formeraient une fausse boucle.

## Version QGIS

L'algorithme `qgis/controle_topologie_reseau.py`, lancé sur `reseau_exemple.gpkg` (couches `troncons` et `postes`), doit donner exactement le même résumé, réparti entre la couche *Anomalies ponctuelles* (8) et la couche *Anomalies linéaires* (10). `python3 outils/tester_qgis.py` le vérifie automatiquement, avec le rapport PDF et la carte HTML (`rapport_exemple.pdf`, `carte_exemple.html`).
