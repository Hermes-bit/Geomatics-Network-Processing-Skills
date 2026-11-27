# Résultats attendus sur le jeu d'exemple

Extraits fictifs au format des exports SNCF Réseau (schéma `sncf_brut`, en WGS84).

```
psql -d ma_base -f exemples/donnees_exemple.sql
psql -d ma_base -f scripts/import_sncf_reseau.sql
psql -d ma_base -f exemples/verifier_resultats.sql        # test automatique
PGDATABASE=ma_base ./exemples/verifier_compatibilite_pk.sh  # enchaînement avec le skill PK
```

## Couches importées

| Couche | Nombre |
|---|---|
| `sncf.lignes` | 4 tronçons (le tronçon 3, en deux parties contiguës, est fusionné) |
| `sncf.gares` | 3 |
| `sncf.passages_niveau` | 4 |
| `sncf.ouvrages` | 3 (2 passerelles, 1 pont-route) |
| `sncf.bornes_pk` | 5 |
| `sncf.sauts_pk` | 1 |

## Bornes et sauts de PK

| Ligne | PK | Position (L93) | Remarque |
|---|---|---|---|
| 999000 | 0+000 | 800000 6600000 | début |
| 999000 | 4+000 = 4+250 | 804000 6600000 | **saut de PK** (lacune de 250 m), pas de borne simple ici |
| 999000 | 6+290 | 806000 6600400 | bout aval du tronçon 2, numérisé à l'envers : le script doit le retrouver |
| 999000 | 7+600 | 807310 6600400 | fin |
| 999100 | 0+000 et 1+500 | | ligne en un seul tronçon |

## Contrôles attendus

| Couche | Objet | Type |
|---|---|---|
| lignes | 999100 | sens_suppose |
| lignes | 999000 | saut_pk_lacune (4+000 = 4+250) |
| gares | Halte des Peupliers | ligne_inconnue (998000) |
| passages_niveau | PN 2 | pk_illisible (« PK 5,4 ») |
| passages_niveau | PN 3 | loin_de_sa_ligne (45 m) |
| ouvrages | Passerelle des Écoles | pk_hors_ligne (9+100 au-delà de 7+600) |

## Enchaînement avec le skill PK (ligne 999000)

| PK | Résultat attendu |
|---|---|
| 5+300 | 805029.6 6600205.9, à une dizaine de mètres du pont de la D 12 |
| 4+100 | pas de position : PK dans la lacune 4+000 = 4+250 |
