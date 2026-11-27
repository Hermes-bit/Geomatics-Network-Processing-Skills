# Geomatics-Network-Processing-Skills

Des **skills Claude** pour la géomatique des réseaux électriques et ferroviaires : contrôle de topologie, référencement par PK, DT-DICT, données ouvertes, végétation LiDAR, bilans électriques, et une analyse d'impact de chantier qui les enchaîne. Chaque skill apprend à Claude une méthode de travail précise (étapes, pièges, format de sortie) et s'accompagne de scripts testés (PostGIS, et un algorithme QGIS pour la topologie et les PK), d'un jeu de données d'exemple et de demandes types pour l'essayer.

Le dépôt est rempli au fur et à mesure. Les retours sont les bienvenus : [ouvrez une *issue*](https://github.com/Hermes-bit/Geomatics-Network-Processing-Skills/issues/new/choose) pour signaler un problème ou proposer un skill (des formulaires vous guident).

## Les skills

| Skill | Ce qu'il fait | Outils |
|---|---|---|
| [analyse-impact-chantier](skills/analyse-impact-chantier/) | À partir d'une emprise de travaux, enchaîne les autres skills (DT-DICT, PK de la voie, végétation LiDAR HD) et le cadastre pour rendre un dossier d'impact complet : registre des risques classés de critique à information (réseaux, voisinage électrique, voie ferrée, végétation, foncier), exploitants à consulter, parcelles occupées et riveraines, dossier PDF et carte HTML. | PostGIS ou QGIS seul |
| [analyse-bilan-electrique](skills/analyse-bilan-electrique/) | Contrôle et analyse un bilan électrique ou une courbe de charge au pas de 15 ou 30 min (bilan demi-heure Enedis, ODRÉ) : pas manquants, doublons, changements d'heure, équilibre injection / soutirage / pertes / consommation, puis énergies journalières, pointes, part de production locale, pertes, avec un rapport HTML. Testé sur de vraies données Enedis. | Python (sans installation) |
| [controle-topologie-reseau](skills/controle-topologie-reseau/) | Contrôle la topologie d'un réseau linéaire électrique ou ferroviaire : extrémités pendantes, quasi-connexions, croisements sans nœud (en tenant compte des franchissements), composantes et postes isolés, tronçons trop courts, boucles fermées en exploitation radiale, attributs incohérents. Produit une table d'anomalies localisées et un résumé, sans jamais toucher aux données source. Rapport PDF et carte HTML à partager. | PostGIS + pgRouting, ou QGIS seul |
| [import-donnees-rte-enedis](skills/import-donnees-rte-enedis/) | Importe les données ouvertes RTE (ODRÉ) et Enedis / Agence ORE (lignes HTB, HTA, BT aériennes et souterraines, postes) en Lambert 93, avec tensions en kV et pose normalisées, au format du skill de topologie et du skill DT-DICT. | PostGIS, GDAL, QGIS |
| [import-donnees-sncf-reseau](skills/import-donnees-sncf-reseau/) | Importe les données ouvertes SNCF Réseau (lignes du RFN, gares, passages à niveau, passerelles, ponts-route, passages souterrains) en Lambert 93 pour QGIS, contrôle les PK, détecte les sauts de PK et le sens des tronçons, et prépare les axes, bornes et sauts du skill de référencement PK. | PostGIS, GDAL, QGIS |
| [proximite-dt-dict](skills/proximite-dt-dict/) | Pré-analyse DT-DICT : repère les réseaux proches d'une emprise de travaux et liste les exploitants à consulter, avec classes de précision A, B, C, zones d'incertitude, fuseau de 3 m des réseaux aériens et investigations complémentaires à prévoir. Contrôle aussi l'emprise (surface, écart entre polygones). Ne remplace pas le guichet unique. | PostGIS, ou QGIS seul |
| [referencement-pk-ferroviaire](skills/referencement-pk-ferroviaire/) | Convertit des PK (`15+342`) en coordonnées Lambert 93 et inversement, avec calage sur les bornes, gestion des sauts de PK, décalage latéral, événements linéaires de PK à PK, et alerte quand un point est à plus de 20 m de l'axe. Sortie en CSV avec la méthode utilisée et les avertissements. | PostGIS, ou QGIS seul |
| [vegetation-lidar-hd](skills/vegetation-lidar-hd/) | Repère la végétation trop haute ou trop proche des lignes électriques aériennes et des voies ferrées à partir des nuages de points classés LiDAR HD de l'IGN : hauteur au-dessus du sol, risque de chute d'arbre, hauteur excessive dans l'emprise, priorité par tronçon de 25 m et par côté, sortie CSV et GeoJSON. | Python (numpy, laspy), QGIS |

## Installer un skill dans Claude

### Dans Claude (claude.ai, application de bureau)
1. Téléchargez le dossier du skill en ZIP : soit avec `./outils/empaqueter.sh` (crée `dist/<skill>.zip`), soit en zippant vous-même le dossier `skills/<skill>/` (le ZIP doit contenir le dossier, avec `SKILL.md` dedans).
2. Dans Claude : **Paramètres > Capacités**, activez l'exécution de code si ce n'est pas déjà fait, puis dans la section **Skills**, importez le ZIP.
3. Activez le skill. Claude l'utilisera de lui-même quand une demande correspond à sa description.

### Dans Claude Code
Ajoutez ce dépôt comme marketplace de plugins, puis installez le plugin :
```
/plugin marketplace add Hermes-bit/Geomatics-Network-Processing-Skills
/plugin install geomatique-reseaux@geomatics-network-processing-skills
```
Ou copiez simplement un dossier de skill dans `~/.claude/skills/` (pour vous) ou `.claude/skills/` (pour un projet).

## Tester avec les données d'exemple

Il faut une base PostgreSQL avec les extensions **PostGIS** (3.1 ou plus) et **pgRouting** (3.4 ou plus, pour la topologie). Les scripts ont été testés avec PostgreSQL 16, PostGIS 3.4 et pgRouting 3.6.

```bash
createdb essai_skills
psql -d essai_skills -c "CREATE EXTENSION postgis; CREATE EXTENSION pgrouting;"
PGDATABASE=essai_skills ./outils/tester_exemples.sh
```

Chaque skill a son dossier `exemples/` :
- `donnees_exemple.sql` : un petit jeu de données fictif en Lambert 93, avec des pièges volontaires ;
- `resultats_attendus.md` : ce que le skill doit trouver ;
- `demandes_exemple.md` : des phrases à donner à Claude pour l'essayer ;
- `verifier_resultats.sql` (pour les nouveaux skills) : un test automatique, lancé par `tester_exemples.sh`, qui s'arrête en erreur si les résultats s'écartent des résultats attendus.

Le skill `analyse-impact-chantier` enchaîne les autres : son test `exemples/chainer_exemple.sh` charge le chantier d'exemple et la voie du skill PK, fait tourner le vrai script de végétation sur un nuage LiDAR fictif (si `numpy` et `laspy` sont installés), lance les scripts DT-DICT et PK puis la synthèse, et vérifie le registre des risques.

Le skill `vegetation-lidar-hd` n'utilise pas de base : il lui faut Python 3 avec `numpy` et `laspy` (`pip install numpy "laspy[lazrs]"`). Son test `exemples/test_vegetation.py` génère un petit nuage fictif au format LiDAR HD, lance l'analyse et compare au résultat attendu ; `tester_exemples.sh` le lance aussi.

### Dans QGIS, en un clic : l'extension « Géomatique des réseaux »

L'extension regroupe tous les algorithmes QGIS du dépôt (analyse d'impact, DT-DICT, PK, topologie) et ajoute un bouton **Analyse d'impact d'un chantier** dans la barre d'outils, plus un menu *Extensions > Géomatique des réseaux*.
1. Créez le ZIP : `./outils/empaqueter_extension.sh` (il écrit `dist/geomatique_reseaux.zip`).
2. Dans QGIS : *Extensions > Installer/Gérer les extensions > Installer depuis un ZIP*, choisissez le fichier, puis *Installer l'extension*. Elle est marquée expérimentale : cochez « Afficher les extensions expérimentales » dans les paramètres si besoin.
3. Cliquez sur le bouton de la barre d'outils, remplissez la fenêtre (emprise, réseaux, voie, végétation, parcelles, fichiers PDF et HTML) et lancez.

Les algorithmes de l'extension sont copiés des dossiers `skills/*/qgis/` au moment de l'empaquetage : il n'y a qu'une version de chaque algorithme. Pas besoin d'ajouter les scripts un par un.

### Sans PostGIS, avec QGIS

Les skills `controle-topologie-reseau`, `referencement-pk-ferroviaire`, `proximite-dt-dict` et `analyse-impact-chantier` ont un dossier `qgis/` qui contient un algorithme de traitement QGIS équivalent au script SQL (testé avec QGIS 3.34, aucune extension à installer) :
1. Dans QGIS, ouvrez la boîte à outils Traitements, cliquez sur l'icône Python puis *Ajouter un script à la boîte à outils…* et choisissez le fichier `.py`.
2. L'algorithme apparaît dans *Scripts > Géomatique des réseaux*. Les jeux d'exemple existent aussi en GeoPackage (`exemples/*.gpkg`) pour l'essayer tout de suite.
3. L'analyse d'impact lance les algorithmes DT-DICT et PK : ajoutez aussi ces deux scripts à la boîte à outils.

Pour vérifier les algorithmes sans ouvrir QGIS, lancez avec le Python de QGIS (sous Windows, `python-qgis` dans l'« OSGeo4W Shell ») :
```bash
python3 outils/tester_qgis.py
```

La façon la plus parlante de tester : chargez les données d'exemple, donnez à Claude une des demandes types, et comparez sa réponse aux résultats attendus.

## Dossier d'impact d'un chantier

`skills/analyse-impact-chantier/` rassemble tout ce qu'un chantier touche en un dossier à partager : un PDF (carte avec les risques numérotés, synthèse, exploitants, registre des risques, parcelles) et une carte HTML interactive.

```bash
cd skills/analyse-impact-chantier
python3 scripts/chainer_postgis.py --base "dbname=ma_base" --dtdict mes_sources_dtdict.sql \
    --pk mes_sources_pk.sql --impact mes_sources_impact.sql --gpkg impact.gpkg
python3 rapport/dossier_impact.py impact.gpkg --pdf dossier_impact.pdf --html carte_impact.html   # Python de QGIS
```
Dans QGIS, l'algorithme *Analyse d'impact d'un chantier* écrit directement le PDF et la carte. Exemples : `exemples/dossier_exemple.pdf` et `exemples/carte_exemple.html`.

## Rapport d'anomalies à partager

`skills/controle-topologie-reseau/rapport/rapport_anomalies.py` transforme le résultat du contrôle de topologie en documents à envoyer :
- un **PDF** avec la carte des anomalies colorées par gravité, le résumé et la liste détaillée ;
- une **carte HTML** interactive en un seul fichier, ouvrable dans n'importe quel navigateur, avec des filtres par gravité et la fiche de chaque anomalie au clic.

```bash
# Depuis PostGIS : exporter d'abord la table des anomalies
cd skills/controle-topologie-reseau
./rapport/exporter_anomalies_postgis.sh "dbname=ma_base" anomalies.gpkg
python3 rapport/rapport_anomalies.py --reseau "reseau.gpkg|layername=troncons" \
    --anomalies "anomalies.gpkg|layername=anomalies_points" --anomalies "anomalies.gpkg|layername=anomalies_lignes" \
    --titre "Contrôle de topologie - départ DEP-01" --note "Tolérances : accrochage 0,01 m, quasi-connexion 1 m" \
    --pdf rapport.pdf --html carte.html
```
Depuis QGIS, passez directement les couches *Anomalies ponctuelles* et *Anomalies linéaires* enregistrées par l'algorithme. Un exemple de chaque est dans `skills/controle-topologie-reseau/exemples/` (`rapport_exemple.pdf`, `carte_exemple.html`).

## Organisation du dépôt

```
skills/
  <nom-du-skill>/
    SKILL.md              instructions lues par Claude (frontmatter name + description)
    scripts/              scripts SQL testés que le skill utilise (PostGIS)
    qgis/                 algorithme de traitement QGIS équivalent (PyQGIS)
    rapport/              (topologie, impact) rapport PDF et carte HTML à partager
    exemples/             données d'exemple, résultats attendus, demandes types
modele-skill/             gabarit à copier pour créer un nouveau skill
extension-qgis/           extension QGIS (bouton, menu et fournisseur Traitements)
outils/                   empaquetage en ZIP (skills et extension QGIS), tests des exemples (SQL et QGIS)
.claude-plugin/           déclaration du marketplace pour Claude Code
.github/ISSUE_TEMPLATE/   formulaires pour signaler un problème ou proposer un skill
```

Pour ajouter un skill, voir [CONTRIBUER.md](CONTRIBUER.md).

## Conventions communes
- Système de coordonnées de travail : **Lambert 93 (EPSG:2154)** en métropole ; les distances et tolérances sont en mètres.
- Les données source ne sont **jamais modifiées** sans accord explicite : tout se fait dans un schéma de travail.
- Chaque résultat dit comment il a été obtenu et porte ses avertissements.
- Documentation et instructions en français.

## Avertissement
Les jeux de données d'exemple sont fictifs. Les skills aident à contrôler et convertir des données, mais ne remplacent pas la vérification par une personne compétente, en particulier pour les DT-DICT et tout usage réglementaire.

## Licence
Ce dépôt est publié sous **licence MIT** (voir [LICENSE](LICENSE)) : chacun peut utiliser, copier, modifier et redistribuer les skills, y compris dans un cadre professionnel, à condition de conserver la mention de copyright et le texte de la licence. Les skills sont fournis sans garantie.
