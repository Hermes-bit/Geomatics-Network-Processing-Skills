# Résultats attendus sur le jeu d'exemple

Extraits fictifs au format des exports RTE (ODRÉ) et Agence ORE / Enedis, schéma `elec_brut`, en WGS84.

```
psql -d ma_base -f exemples/donnees_exemple.sql
psql -d ma_base -f scripts/import_rte_enedis.sql
psql -d ma_base -f exemples/verifier_resultats.sql               # test automatique
PGDATABASE=ma_base ./exemples/verifier_compatibilite_topologie.sh  # enchaînement avec le skill de topologie
```

## Tronçons importés (`reseau_elec.troncons`)

| Domaine | Pose | Nombre | Remarque |
|---|---|---|---|
| HTB | aérien | 3 | 63 kV, 225 kV et une ligne hors tension |
| HTB | souterrain | 1 | 63 kV |
| HTA | aérien | 4 | dont une ligne coupée à la limite de commune et une sans tension (domaine déduit du nom de la table) |
| HTA | souterrain | 2 | dont un câble à 0,6 m du câble voisin |
| BT | aérien | 1 | |

Lecture des tensions : `225 kV` → 225, `63kV` → 63, `HTA` → 20, `BT` → 0,4, `HORS TENSION` → vide.

## Postes (`reseau_elec.postes`)

| Type | Nombre |
|---|---|
| poste_htb (RTE) | 4 |
| poste_source | 1 |
| poste_hta_bt | 4, dont un en double |

## Contrôles de l'import

| Type | Nombre | Objet |
|---|---|---|
| hors_exploitation | 1 | ligne RTE hors tension |
| tension_illisible | 1 | ligne HTA sans tension |
| tension_supposee | 3 | une ligne par table : HTA aérien, HTA souterrain, BT |
| poste_en_double | 1 | poste HTA/BT à 0,36 m d'un autre |

## Enchaînement avec le skill de topologie

| Anomalie | Nombre | Pourquoi |
|---|---|---|
| quasi_connexion | 2 | le câble HTA souterrain s'arrête à 0,6 m de son voisin (vu des deux côtés) |
| composante_isolee | 1 | ce câble n'est donc relié à aucun poste source |
| attribut_manquant | 2 | la ligne HTA sans tension et la ligne hors tension |
| extremite_pendante | 2 | bout de la BT et de la ligne HTA sans tension (antennes, normales) |
