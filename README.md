# Geomatics-Network-Processing-Skills

Des **skills Claude** pour la géomatique des réseaux électriques et ferroviaires : contrôle de topologie, référencement par PK, et bientôt d'autres. Chaque skill apprend à Claude une méthode de travail précise (étapes, pièges, format de sortie) et s'accompagne d'un script PostGIS et d'un algorithme QGIS testés, d'un jeu de données d'exemple et de demandes types pour l'essayer.

Le dépôt est rempli au fur et à mesure. Les retours sont les bienvenus : [ouvrez une *issue*](https://github.com/Hermes-bit/Geomatics-Network-Processing-Skills/issues/new/choose) pour signaler un problème ou proposer un skill (des formulaires vous guident).

## Les skills

| Skill | Ce qu'il fait | Outils |
|---|---|---|
| [controle-topologie-reseau](skills/controle-topologie-reseau/) | Contrôle la topologie d'un réseau linéaire électrique ou ferroviaire : extrémités pendantes, quasi-connexions, croisements sans nœud (en tenant compte des franchissements), composantes et postes isolés, tronçons trop courts, boucles fermées en exploitation radiale, attributs incohérents. Produit une table d'anomalies localisées et un résumé, sans jamais toucher aux données source. Rapport PDF et carte HTML à partager. | PostGIS + pgRouting, ou QGIS seul |
| [referencement-pk-ferroviaire](skills/referencement-pk-ferroviaire/) | Convertit des PK (`15+342`) en coordonnées Lambert 93 et inversement, avec calage sur les bornes, gestion des sauts de PK, décalage latéral, événements linéaires de PK à PK, et alerte quand un point est à plus de 20 m de l'axe. Sortie en CSV avec la méthode utilisée et les avertissements. | PostGIS, ou QGIS seul |

### Prévus

- Analyse de proximité DT-DICT (réseaux à proximité d'une emprise de travaux)
- Intégration des données ouvertes RTE et Enedis
- Import des données ouvertes SNCF Réseau

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
- `demandes_exemple.md` : des phrases à donner à Claude pour l'essayer.

### Sans PostGIS, avec QGIS

Chaque skill a un dossier `qgis/` qui contient un algorithme de traitement QGIS équivalent au script SQL (testé avec QGIS 3.34, aucune extension à installer) :
1. Dans QGIS, ouvrez la boîte à outils Traitements, cliquez sur l'icône Python puis *Ajouter un script à la boîte à outils…* et choisissez le fichier `.py`.
2. L'algorithme apparaît dans *Scripts > Géomatique des réseaux*. Les jeux d'exemple existent aussi en GeoPackage (`exemples/*.gpkg`) pour l'essayer tout de suite.

Pour vérifier les deux algorithmes sans ouvrir QGIS, lancez avec le Python de QGIS (sous Windows, `python-qgis` dans l'« OSGeo4W Shell ») :
```bash
python3 outils/tester_qgis.py
```

La façon la plus parlante de tester : chargez les données d'exemple, donnez à Claude une des demandes types, et comparez sa réponse aux résultats attendus.

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
    rapport/              (topologie) rapport PDF et carte HTML à partager
    exemples/             données d'exemple, résultats attendus, demandes types
modele-skill/             gabarit à copier pour créer un nouveau skill
outils/                   empaquetage en ZIP, tests des exemples (SQL et QGIS)
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
