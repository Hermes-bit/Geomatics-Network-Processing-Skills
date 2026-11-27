---
name: analyse-impact-chantier
description: Analyse d'impact complète d'un chantier à partir de son emprise de travaux - réseaux et exploitants concernés (DT-DICT), voie ferrée et PK, végétation LiDAR HD, parcelles cadastrales occupées ou riveraines - avec un registre des risques classés (critique, majeur, à traiter, information), un dossier PDF et une carte HTML. Enchaîne les skills proximite-dt-dict, referencement-pk-ferroviaire et vegetation-lidar-hd. À utiliser pour toute demande d'étude d'impact, d'analyse préalable, de dossier de chantier, de préparation de travaux près des réseaux ou des voies, ou de « qu'est-ce que ce chantier touche ? ».
---

# Analyse d'impact d'un chantier

À partir d'une zone de travaux, ce skill répond en un seul dossier à la question « qu'est-ce que ce chantier touche, et que faut-il faire avant de commencer ? ». Il ne refait pas le travail des autres skills du dépôt : il les **enchaîne** sur la même emprise, puis assemble leurs résultats et y ajoute les parcelles cadastrales et un registre des risques.

| Étape | Skill réutilisé | Ce qu'il apporte |
|---|---|---|
| Réseaux et exploitants | `proximite-dt-dict` | ouvrages dans l'emprise, zones d'incertitude, fuseau aérien, investigations complémentaires, contrôles de l'emprise |
| Voie ferrée | `referencement-pk-ferroviaire` | PK de début et de fin de la section concernée, sauts de PK |
| Végétation | `vegetation-lidar-hd` | tronçons à élaguer ou à surveiller, zones sans LiDAR |
| Parcelles | ce skill | parcelles occupées, riveraines, contacts douteux, propriétaires personnes morales |
| Synthèse | ce skill | registre des risques, exploitants avec leur niveau de risque, dossier PDF et carte HTML |

Deux versions testées sont fournies : PostGIS (`scripts/chainer_postgis.py`, qui lance les scripts SQL des autres skills puis `scripts/impact_chantier.sql`) et QGIS (`qgis/analyse_impact_chantier.py`, qui lance les algorithmes QGIS des autres skills). Le dossier est produit par `rapport/dossier_impact.py` (PostGIS) ou directement par l'algorithme QGIS.

## Règle d'or
- **C'est une pré-analyse.** La liste officielle des exploitants vient du guichet unique ([reseaux-et-canalisations.ineris.fr](https://www.reseaux-et-canalisations.ineris.fr)), et seules les couches fournies sont analysées : ne jamais écrire qu'un chantier « ne touche rien ». Le dire dans chaque réponse et dans le dossier.
- Les seuils (distance aux voies, débattement des engins, marges) sont des **valeurs de départ** à confirmer avec les exploitants et SNCF Réseau. Les annoncer.
- Ne jamais modifier les données source : tout se fait dans les schémas de travail `dtdict`, `pk_ref` et `impact`, ou dans des couches temporaires.
- Ne pas dupliquer les autres skills : s'ils manquent, demander de les installer (ils doivent être dans le même dossier parent que celui-ci) plutôt que de réécrire leurs calculs.
- Les propriétaires personnes physiques ne sont pas publiés : ne pas chercher à les retrouver. Seul le fichier DGFiP des parcelles des personnes morales donne un propriétaire.

## Avant de commencer : informations à obtenir
1. **L'emprise** (polygones d'une même déclaration, SCR, travaux urgents ou non) et le nom du chantier.
2. **Les réseaux** au format du skill `proximite-dt-dict` (exploitant, categorie, pose, classe_precision, flexible, branchement, tension_kv) et les contacts des exploitants. Les skills `import-donnees-rte-enedis` et `import-donnees-sncf-reseau` préparent les données ouvertes dans ce format.
3. **La voie ferrée**, s'il y en a une à moins de 20 m : axes, bornes kilométriques et sauts de PK au format du skill `referencement-pk-ferroviaire`, code ligne et voie.
4. **La végétation** : le résultat `troncons_vegetation.geojson` du skill `vegetation-lidar-hd`, lancé sur les lignes aériennes et les voies du secteur avec les dalles LiDAR HD. Sinon, le dire : la végétation n'est pas contrôlée.
5. **Le cadastre** : parcelles Etalab ([cadastre.data.gouv.fr](https://cadastre.data.gouv.fr), colonnes id, commune, prefixe, section, numero, contenance) ou PCI, et si possible le fichier des parcelles des personnes morales (data.gouv.fr).

Il manque une couche facultative : faire l'analyse quand même, et lister dans la réponse ce qui n'a pas été contrôlé.

## Ce que dit le registre des risques
Chaque risque a un niveau, un thème, un objet, un constat, une mesure et le skill d'origine. Il est situé par un point sur la partie de l'objet la plus proche de l'emprise.

| Niveau | Cas |
|---|---|
| 1 critique | réseau enterré sensible (ou de sensibilité inconnue) dans l'emprise ; ligne aérienne ou caténaire à moins de la distance minimale de sécurité (3 m sous 50 kV, 5 m au-delà, art. R. 4534-108 du code du travail ; 5 m si la tension est inconnue) ; emprise qui coupe la voie ferrée |
| 2 majeur | réseau sensible enterré dans sa zone d'incertitude ; ligne aérienne à moins de la distance de sécurité plus le débattement des engins (5 m par défaut) ; travaux à moins de 20 m de la voie ; emprise non conforme pour une seule déclaration (surface, écart de plus de 50 m entre polygones, étendue) ; végétation à traiter près du chantier |
| 3 à traiter | réseau non sensible dans l'emprise ou sa zone d'incertitude ; végétation à surveiller ; parcelle occupée (accord du propriétaire, permission de voirie, autorisation d'occupation du domaine ferroviaire) |
| 4 information | réseau à proximité ; tronçon sans données LiDAR ; parcelle riveraine ; contact de moins de 2 m² avec une parcelle (imprécision du cadastre) |

Pour la voie ferrée, le registre donne les PK de la section à moins de 20 m de l'emprise et ceux de la partie dans l'emprise. Si la section contient un saut de PK, il le dit : la longueur sur le terrain n'est pas l'écart de PK.

## Étapes (PostGIS)
1. Préparer les sources : un fichier de section 0 par script, qui contient ses `CREATE TABLE ... parametres` et ses `CREATE VIEW ... src_*` adaptés aux tables de l'utilisateur. Partir de `exemples/sources_dtdict.sql` et `exemples/sources_pk.sql`, et de la section 0 de `scripts/impact_chantier.sql` (nom du chantier, seuils, vues `src_parcelles`, `src_proprietaires`, `src_vegetation`). Pour une couche absente, une vue vide : `SELECT ... WHERE false`.
2. Charger la végétation : `ogr2ogr -f PostgreSQL PG:"dbname=ma_base" troncons_vegetation.geojson -nln travail.vegetation -a_srs EPSG:2154`.
3. Tout lancer :
   ```bash
   python3 scripts/chainer_postgis.py --base "dbname=ma_base" --dtdict sources_dtdict.sql \
       --pk sources_pk.sql --impact sources_impact.sql --gpkg impact.gpkg
   ```
   Sans voie ferrée, omettre `--pk`. Le script remplace seulement la section 0 des scripts des autres skills, à la volée, sans les copier ni les modifier.
4. Lire `impact.synthese`, `impact.risques` et `impact.exploitants`. Vérifier les contrôles non conformes de `dtdict.controle_emprise`.
5. Produire le dossier avec le Python de QGIS :
   ```bash
   python3 rapport/dossier_impact.py impact.gpkg --pdf dossier_impact.pdf --html carte_impact.html
   ```

## Dans QGIS sans PostGIS
1. Ajouter à la boîte à outils (Traitements > icône Python > *Ajouter un script à la boîte à outils…*) trois scripts : `qgis/analyse_impact_chantier.py`, `../proximite-dt-dict/qgis/proximite_dt_dict.py` et `../referencement-pk-ferroviaire/qgis/referencement_pk_ferroviaire.py`.
2. Lancer *Scripts > Géomatique des réseaux > Analyse d'impact d'un chantier* : emprise, ouvrages, exploitants, et selon le cas axes, bornes et sauts de PK (code ligne, voie), tronçons de végétation, parcelles et propriétaires. Les champs attendus sont ceux des skills d'import ; sinon, les renommer avec *Refactoriser les champs*.
3. Donner un fichier pour *Dossier PDF* et *Carte HTML*. Les couches de sortie (registre des risques, exploitants, ouvrages, voie, végétation, parcelles, zone) s'ouvrent dans le projet.

## Sortie
- `impact.risques(id, niveau, gravite, theme, objet, exploitant, description, mesure, source, geom)` : points, numérotés du plus grave au moins grave.
- `impact.exploitants` : la liste du skill DT-DICT, plus `niveau_max` (le risque le plus grave qui le concerne), et SNCF Réseau si la voie est concernée sans ouvrage ferroviaire dans les couches.
- `impact.voies`, `impact.vegetation`, `impact.parcelles`, `impact.zone`, et la vue `impact.synthese` (une ligne).
- Le dossier PDF : page 1 avec la carte (emprise, réseaux, voie, végétation, parcelles, risques numérotés) et la synthèse ; pages suivantes avec les exploitants, le registre des risques et les parcelles. La carte HTML : mêmes contenus, risques cliquables, fond OpenStreetMap.

Dans la réponse :
1. Le niveau global et le nombre de risques par niveau, en rappelant que c'est une pré-analyse.
2. Les risques critiques, un par ligne, avec la mesure à prendre.
3. Le tableau des exploitants à consulter, réseaux sensibles en premier, avec les investigations complémentaires.
4. La voie (ligne, PK de début et de fin, saut de PK éventuel), les parcelles occupées et leur propriétaire s'il est connu.
5. Ce qui n'a pas été contrôlé (couches absentes, tronçons sans LiDAR) et les seuils utilisés.
6. Le lien vers le PDF et la carte HTML.

## Exemple
`exemples/` contient un chantier fictif de raccordement HTA qui traverse la ligne 830000 par fonçage, au droit du saut de PK 15+400 = 15+650 du jeu d'exemple du skill PK : six polygones d'emprise (dont une zone de stockage trop éloignée), sept réseaux (dont une ligne RTE 63 kV et la caténaire au-dessus de l'emprise), dix parcelles et un nuage LiDAR HD fictif (`generer_nuage_exemple.py`) analysé par le vrai script du skill végétation. `chainer_exemple.sh` enchaîne tout et lance le test `verifier_resultats.sql` ; `outils/tester_qgis.py` teste la version QGIS et le dossier. Résultats attendus dans `resultats_attendus.md`, demandes types dans `demandes_exemple.md`, dossier produit dans `dossier_exemple.pdf` et `carte_exemple.html`.
