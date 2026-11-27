# -*- coding: utf-8 -*-
"""
Contrôle de topologie d'un réseau linéaire (électrique ou ferroviaire) dans QGIS,
sans PostGIS. Version PyQGIS du script scripts/controles_topologie.sql : mêmes
contrôles, mêmes types d'anomalies, mêmes gravités.

Installation : dans QGIS, boîte à outils Traitements > icône Python >
« Ajouter un script à la boîte à outils… » et choisir ce fichier. L'algorithme
apparaît dans Scripts > Géomatique des réseaux > Contrôle de topologie d'un réseau.

Testé avec QGIS 3.34. Aucune extension à installer : le graphe (composantes
connexes, boucles) est calculé en Python pur.

Les couches source ne sont jamais modifiées : les résultats sont écrits dans de
nouvelles couches (anomalies ponctuelles, anomalies linéaires, résumé).
"""

import math
from collections import defaultdict

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProject,
    QgsSpatialIndex,
    QgsWkbTypes,
)

ORDRE_GRAVITE = {"bloquante": 1, "majeure": 2, "mineure": 3, "info": 4}


def _texte(v):
    """Valeur d'attribut QGIS -> str ou None (gère NULL)."""
    if v is None:
        return None
    try:
        if v.isNull():
            return None
    except AttributeError:
        pass
    s = str(v)
    return s if s != "" and s != "NULL" else None


def _nombre(v):
    s = _texte(v)
    if s is None:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _fmt(x):
    """20.0 -> '20', 0.4 -> '0.4' (comme l'affichage numeric de PostgreSQL)."""
    return ("%f" % x).rstrip("0").rstrip(".")


def _parties_lignes(geom):
    """Liste des polylignes (listes de QgsPointXY) d'une géométrie quelconque."""
    out = []
    if geom is None or geom.isEmpty():
        return out
    t = QgsWkbTypes.geometryType(geom.wkbType())
    if t == QgsWkbTypes.LineGeometry:
        if geom.isMultipart():
            out.extend([list(p) for p in geom.asMultiPolyline()])
        else:
            out.append(list(geom.asPolyline()))
    elif QgsWkbTypes.flatType(geom.wkbType()) == QgsWkbTypes.GeometryCollection:
        for g in geom.asGeometryCollection():
            out.extend(_parties_lignes(g))
    return [p for p in out if len(p) >= 2]


class Troncon:
    __slots__ = ("id", "tension", "pose", "etat", "geom", "nb_parties", "source", "target")


class ControleTopologieReseau(QgsProcessingAlgorithm):
    TRONCONS = "TRONCONS"
    CHAMP_ID = "CHAMP_ID"
    CHAMP_TENSION = "CHAMP_TENSION"
    CHAMP_POSE = "CHAMP_POSE"
    CHAMP_ETAT = "CHAMP_ETAT"
    VALEUR_OUVERT = "VALEUR_OUVERT"
    POSTES = "POSTES"
    CHAMP_POSTE_ID = "CHAMP_POSTE_ID"
    CHAMP_POSTE_NOM = "CHAMP_POSTE_NOM"
    CHAMP_POSTE_TYPE = "CHAMP_POSTE_TYPE"
    TYPES_SOURCE = "TYPES_SOURCE"
    TOL_ACCROCHAGE = "TOL_ACCROCHAGE"
    SEUIL_QUASI = "SEUIL_QUASI"
    LONGUEUR_MIN = "LONGUEUR_MIN"
    TENSIONS_VALIDES = "TENSIONS_VALIDES"
    SORTIE_POINTS = "SORTIE_POINTS"
    SORTIE_LIGNES = "SORTIE_LIGNES"
    SORTIE_RESUME = "SORTIE_RESUME"

    def tr(self, s):
        return QCoreApplication.translate("ControleTopologieReseau", s)

    def createInstance(self):
        return ControleTopologieReseau()

    def name(self):
        return "controle_topologie_reseau"

    def displayName(self):
        return self.tr("Contrôle de topologie d'un réseau")

    def group(self):
        return self.tr("Géomatique des réseaux")

    def groupId(self):
        return "geomatique_reseaux"

    def shortHelpString(self):
        return self.tr(
            "Contrôle la topologie d'un réseau linéaire électrique (HTA, HTB, BT) ou ferroviaire : "
            "extrémités pendantes, quasi-connexions, croisements sans nœud (les croisements entre poses "
            "différentes sont des franchissements normaux), composantes non reliées à un poste source, "
            "postes isolés, tronçons trop courts, boucles fermées en exploitation radiale, tronçons "
            "bouclés sur eux-mêmes, doublons, géométries invalides et attributs incohérents.\n\n"
            "Les tolérances sont en unités de la couche : travaillez dans un SCR projeté en mètres "
            "(Lambert 93, EPSG:2154, en métropole). Les couches source ne sont jamais modifiées.\n\n"
            "Les champs facultatifs peuvent rester vides : sans champ de pose, tout croisement est "
            "signalé ; sans champ d'état, aucune boucle n'est considérée comme ouverte."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.TRONCONS, self.tr("Tronçons du réseau"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.CHAMP_ID, self.tr("Identifiant des tronçons"), parentLayerParameterName=self.TRONCONS,
            optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CHAMP_TENSION, self.tr("Tension en kV (facultatif)"), parentLayerParameterName=self.TRONCONS,
            optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CHAMP_POSE, self.tr("Mode de pose ou niveau, pour les franchissements (facultatif)"),
            parentLayerParameterName=self.TRONCONS, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CHAMP_ETAT, self.tr("État d'exploitation (facultatif)"), parentLayerParameterName=self.TRONCONS,
            optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.VALEUR_OUVERT, self.tr("Valeur de l'état qui désigne un point d'ouverture"), defaultValue="NO"))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.POSTES, self.tr("Postes (facultatif)"), [QgsProcessing.TypeVectorPoint], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CHAMP_POSTE_ID, self.tr("Identifiant des postes"), parentLayerParameterName=self.POSTES,
            optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CHAMP_POSTE_NOM, self.tr("Nom des postes"), parentLayerParameterName=self.POSTES, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CHAMP_POSTE_TYPE, self.tr("Type de poste"), parentLayerParameterName=self.POSTES, optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.TYPES_SOURCE, self.tr("Types de postes qui alimentent le réseau (séparés par des virgules)"),
            defaultValue="poste_source"))
        self.addParameter(QgsProcessingParameterNumber(
            self.TOL_ACCROCHAGE, self.tr("Tolérance d'accrochage (m)"), QgsProcessingParameterNumber.Double,
            0.01, minValue=0.000001))
        self.addParameter(QgsProcessingParameterNumber(
            self.SEUIL_QUASI, self.tr("Seuil de quasi-connexion (m)"), QgsProcessingParameterNumber.Double,
            1.0, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.LONGUEUR_MIN, self.tr("Longueur minimale d'un tronçon (m)"), QgsProcessingParameterNumber.Double,
            1.0, minValue=0))
        self.addParameter(QgsProcessingParameterString(
            self.TENSIONS_VALIDES, self.tr("Tensions normalisées en kV (vide = pas de contrôle)"),
            defaultValue="0.4,15,20,63,90,150,225,400", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SORTIE_POINTS, self.tr("Anomalies ponctuelles"), QgsProcessing.TypeVectorPoint))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SORTIE_LIGNES, self.tr("Anomalies linéaires"), QgsProcessing.TypeVectorLine))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SORTIE_RESUME, self.tr("Résumé des anomalies"), QgsProcessing.TypeVector))

    # ------------------------------------------------------------------ outils
    def _ajouter(self, type_, gravite, id_objet, detail, geom):
        self.anomalies.append((type_, gravite, id_objet, detail, geom))

    # ------------------------------------------------------------- algorithme
    def processAlgorithm(self, parameters, context, feedback):
        self.anomalies = []
        src = self.parameterAsSource(parameters, self.TRONCONS, context)
        if src is None:
            raise QgsProcessingException(self.tr("Couche de tronçons introuvable"))
        postes_src = self.parameterAsSource(parameters, self.POSTES, context)

        f_id = self.parameterAsString(parameters, self.CHAMP_ID, context)
        f_tension = self.parameterAsString(parameters, self.CHAMP_TENSION, context)
        f_pose = self.parameterAsString(parameters, self.CHAMP_POSE, context)
        f_etat = self.parameterAsString(parameters, self.CHAMP_ETAT, context)
        val_ouvert = self.parameterAsString(parameters, self.VALEUR_OUVERT, context)
        fp_id = self.parameterAsString(parameters, self.CHAMP_POSTE_ID, context)
        fp_nom = self.parameterAsString(parameters, self.CHAMP_POSTE_NOM, context)
        fp_type = self.parameterAsString(parameters, self.CHAMP_POSTE_TYPE, context)
        types_source = {t.strip() for t in self.parameterAsString(parameters, self.TYPES_SOURCE, context).split(",")
                        if t.strip()}
        tol = self.parameterAsDouble(parameters, self.TOL_ACCROCHAGE, context)
        seuil = self.parameterAsDouble(parameters, self.SEUIL_QUASI, context)
        long_min = self.parameterAsDouble(parameters, self.LONGUEUR_MIN, context)
        tv = self.parameterAsString(parameters, self.TENSIONS_VALIDES, context) or ""
        tensions_valides = [float(x.replace(",", ".")) for x in tv.replace(";", " ").replace(" ", ",").split(",")
                            if x.strip()] if tv.strip() else []
        # Les tensions sont écrites avec une virgule comme séparateur de liste : « 0.4,15,20 ».

        crs = src.sourceCrs()
        if crs.isGeographic():
            raise QgsProcessingException(self.tr(
                "La couche est en coordonnées géographiques (%s) : les tolérances en mètres n'ont pas de sens. "
                "Reprojetez-la d'abord, en Lambert 93 (EPSG:2154) en métropole.") % crs.authid())
        if crs.authid() != "EPSG:2154":
            feedback.pushWarning(self.tr(
                "SCR %s au lieu de Lambert 93 (EPSG:2154) : contrôles faits dans ce SCR, vérifiez qu'il est "
                "en mètres.") % crs.authid())

        # ---- 1. Lecture, réparation, fusion des morceaux
        troncons = []
        n_total = src.featureCount() or 1
        for i, f in enumerate(src.getFeatures()):
            if feedback.isCanceled():
                return {}
            fid = _texte(f[f_id]) if f_id else str(f.id())
            g = QgsGeometry(f.geometry())
            if g.isNull() or g.isEmpty():
                self._ajouter("geometrie_vide", "majeure", fid, "Tronçon sans géométrie", None)
                continue
            if not g.isGeosValid():
                raison = g.validateGeometry()
                self._ajouter("geometrie_invalide", "majeure", fid,
                              "; ".join(e.what() for e in raison) or "Géométrie invalide", QgsGeometry(g))
                g = g.makeValid()
            parties = _parties_lignes(g)
            nb_origine = len(parties)
            if nb_origine == 0:
                continue
            fusion = QgsGeometry.fromMultiPolylineXY(parties).mergeLines() if nb_origine > 1 \
                else QgsGeometry.fromPolylineXY(parties[0])
            t = Troncon()
            t.id = fid
            t.tension = _nombre(f[f_tension]) if f_tension else None
            t.pose = _texte(f[f_pose]) if f_pose else None
            t.etat = _texte(f[f_etat]) if f_etat else None
            t.nb_parties = nb_origine
            t.geom = fusion
            if fusion.isMultipart() and len(fusion.asMultiPolyline()) > 1:
                self._ajouter("troncon_discontinu", "majeure", fid,
                              "Reste en %d parties après fusion" % len(fusion.asMultiPolyline()), fusion)
                continue
            if fusion.isMultipart():
                t.geom = QgsGeometry.fromPolylineXY(fusion.asMultiPolyline()[0])
            if nb_origine > 1:
                self._ajouter("troncon_multi_fusionne", "info", fid,
                              "%d parties contiguës fusionnées dans la copie de travail" % nb_origine, t.geom)
            troncons.append(t)
            feedback.setProgress(20 * i / n_total)

        # ---- 2. Doublons géométriques (quel que soit le sens) : on garde le plus petit identifiant
        def cle_val(v):
            try:
                return (0, float(v), str(v))
            except (TypeError, ValueError):
                return (1, 0, str(v))

        def cle_id(t):
            return cle_val(t.id)

        troncons.sort(key=cle_id)
        index = QgsSpatialIndex()
        for k, t in enumerate(troncons):
            f = QgsFeature(k)
            f.setGeometry(t.geom)
            index.addFeature(f)
        exclus = set()
        for k, t in enumerate(troncons):
            for j in index.intersects(t.geom.boundingBox()):
                if j > k and j not in exclus and troncons[j].geom.isGeosEqual(t.geom):
                    exclus.add(j)
                    self._ajouter("doublon_geometrique", "majeure", troncons[j].id,
                                  "Identique au tronçon %s (exclu du graphe)" % t.id, troncons[j].geom)
        troncons = [t for k, t in enumerate(troncons) if k not in exclus]
        feedback.setProgress(30)

        # Index des tronçons retenus
        index = QgsSpatialIndex()
        for k, t in enumerate(troncons):
            f = QgsFeature(k)
            f.setGeometry(t.geom)
            index.addFeature(f)

        # ---- 3. Graphe : nœuds = extrémités accrochées sur une grille de la tolérance
        def accroche(p):
            return (math.floor(p.x() / tol + 0.5), math.floor(p.y() / tol + 0.5))

        noeuds = {}          # clé de grille -> id du nœud
        coords = {}          # id -> QgsPointXY
        cles = set()
        for t in troncons:
            pl = t.geom.asPolyline()
            cles.add(accroche(pl[0]))
            cles.add(accroche(pl[-1]))
        for n, c in enumerate(sorted(cles, key=lambda c: (c[0], c[1])), start=1):
            noeuds[c] = n
            coords[n] = QgsPointXY(c[0] * tol, c[1] * tol)
        degre = defaultdict(int)
        incidents = defaultdict(list)
        for k, t in enumerate(troncons):
            pl = t.geom.asPolyline()
            t.source = noeuds[accroche(pl[0])]
            t.target = noeuds[accroche(pl[-1])]
            degre[t.source] += 1
            degre[t.target] += 1
            incidents[t.source].append(k)
            if t.target != t.source:
                incidents[t.target].append(k)
            else:
                incidents[t.source].append(k)

        # Postes
        postes = []   # (id, nom, type, QgsGeometry)
        if postes_src is not None:
            xform = None
            if postes_src.sourceCrs() != crs:
                xform = QgsCoordinateTransform(postes_src.sourceCrs(), crs, context.transformContext())
            for f in postes_src.getFeatures():
                g = QgsGeometry(f.geometry())
                if g.isNull() or g.isEmpty():
                    continue
                if xform:
                    g.transform(xform)
                postes.append((_texte(f[fp_id]) if fp_id else str(f.id()),
                               _texte(f[fp_nom]) if fp_nom else None,
                               _texte(f[fp_type]) if fp_type else None, g))
        index_postes = QgsSpatialIndex()
        for k, p in enumerate(postes):
            f = QgsFeature(k)
            f.setGeometry(p[3])
            index_postes.addFeature(f)
        poste_du_noeud = {}
        for n, pt in coords.items():
            gpt = QgsGeometry.fromPointXY(pt)
            proches = [(postes[k][3].distance(gpt), k) for k in
                       index_postes.intersects(gpt.buffer(seuil, 4).boundingBox())]
            proches = [(d, k) for d, k in proches if d <= seuil]
            if proches:
                poste_du_noeud[n] = min(proches)[1]
        feedback.setProgress(45)

        # ---- 4. Contrôles
        # 4.1 Quasi-connexions
        for n in sorted(coords):
            if degre[n] != 1:
                continue
            gpt = QgsGeometry.fromPointXY(coords[n])
            candidats = []
            for k in index.intersects(gpt.buffer(seuil, 4).boundingBox()):
                t = troncons[k]
                if t.source == n or t.target == n:
                    continue
                d = t.geom.distance(gpt)
                if d <= seuil:
                    candidats.append((d, cle_id(t), k))
            if candidats:
                d, _, k = min(candidats)
                t = troncons[k]
                proche = t.geom.nearestPoint(gpt).asPoint()
                self._ajouter("quasi_connexion", "majeure", "noeud %d" % n,
                              "Extrémité à %.2f m du tronçon %s sans y être raccordée" % (d, t.id),
                              QgsGeometry.fromPolylineXY([coords[n], proche]))

        # 4.2 Extrémités pendantes
        for n in sorted(coords):
            if degre[n] == 1 and n not in poste_du_noeud:
                ids = ",".join(troncons[k].id for k in incidents[n])
                self._ajouter("extremite_pendante", "mineure", "noeud %d" % n,
                              "Extrémité libre du tronçon " + ids, QgsGeometry.fromPointXY(coords[n]))

        # 4.3 Croisements sans nœud / franchissements
        for k, a in enumerate(troncons):
            for j in index.intersects(a.geom.boundingBox()):
                if j <= k:
                    continue
                b = troncons[j]
                ordre = sorted([a, b], key=cle_id)
                if not a.geom.crosses(b.geom):
                    continue
                inter = a.geom.intersection(b.geom)
                if a.pose == b.pose:
                    self._ajouter("croisement_sans_noeud", "majeure", "%s/%s" % (ordre[0].id, ordre[1].id),
                                  "Croisement %s / %s sans nœud commun" % (a.pose or "?", b.pose or "?"), inter)
                else:
                    self._ajouter("franchissement", "info", "%s/%s" % (ordre[0].id, ordre[1].id),
                                  "Croisement %s / %s : franchissement considéré comme normal"
                                  % (ordre[0].pose or "?", ordre[1].pose or "?"), inter)
        feedback.setProgress(60)

        # 4.4 Composantes connexes (union-find) et composantes non alimentées
        parent = {n: n for n in coords}

        def racine(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for t in troncons:
            ra, rb = racine(t.source), racine(t.target)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        alimentees = {racine(n) for n, k in poste_du_noeud.items() if postes[k][2] in types_source}
        composantes = defaultdict(list)
        for k, t in enumerate(troncons):
            composantes[racine(t.source)].append(k)
        for c in sorted(composantes):
            if c in alimentees:
                continue
            ks = sorted(composantes[c], key=lambda k: cle_id(troncons[k]))
            ids = [troncons[k].id for k in ks]
            geom = QgsGeometry.unaryUnion([troncons[k].geom for k in ks])
            self._ajouter("composante_isolee", "majeure", "composante %d" % c,
                          "%d tronçon(s) non relié(s) à un poste source : %s" % (len(ids), ",".join(ids)), geom)

        # 4.5 Postes isolés
        for k, (pid, nom, typ, g) in enumerate(postes):
            proches = [j for j in index.intersects(g.buffer(seuil, 4).boundingBox())
                       if troncons[j].geom.distance(g) <= seuil]
            if not proches:
                self._ajouter("poste_isole", "majeure", "poste %s" % pid,
                              "%s : aucun tronçon à proximité" % (nom or pid), QgsGeometry(g))

        # 4.6 Tronçons trop courts
        for t in troncons:
            if t.geom.length() < long_min:
                self._ajouter("troncon_trop_court", "mineure", t.id,
                              "%.2f m (< %s m)" % (t.geom.length(), _fmt(long_min)), t.geom)

        # 4.7 Boucles fermées en exploitation radiale : composantes biconnexes (Tarjan)
        #     du graphe privé des tronçons ouverts.
        aretes = [k for k, t in enumerate(troncons)
                  if not (val_ouvert and t.etat == val_ouvert) and t.source != t.target]
        adj = defaultdict(list)
        for k in aretes:
            adj[troncons[k].source].append((troncons[k].target, k))
            adj[troncons[k].target].append((troncons[k].source, k))
        for blocs in self._blocs_biconnexes(adj):
            if len(blocs) > 1:
                ks = sorted(blocs, key=lambda k: cle_id(troncons[k]))
                ids = [troncons[k].id for k in ks]
                self._ajouter("boucle_fermee_radial", "majeure", ",".join(ids),
                              "Boucle sans point d'ouverture (%s) formée par les tronçons %s"
                              % (val_ouvert or "aucun", ", ".join(ids)),
                              QgsGeometry.unaryUnion([troncons[k].geom for k in ks]))
        feedback.setProgress(75)

        # 4.8 Tronçons bouclés sur eux-mêmes
        for t in troncons:
            if t.source == t.target:
                self._ajouter("troncon_boucle_sur_lui_meme", "majeure", t.id, "Début et fin au même nœud", t.geom)

        # 4.9 Attributs
        if f_tension:
            for t in troncons:
                if t.tension is None:
                    self._ajouter("attribut_manquant", "mineure", t.id, "tension vide", t.geom)
                elif tensions_valides and not any(abs(t.tension - v) < 1e-9 for v in tensions_valides):
                    self._ajouter("attribut_incoherent", "mineure", t.id,
                                  "tension = %s kV hors des valeurs normalisées" % _fmt(t.tension), t.geom)
            for n in sorted(coords):
                if n in poste_du_noeud:
                    continue
                ks = incidents[n]
                tensions = sorted({troncons[k].tension for k in ks if troncons[k].tension is not None})
                if len(tensions) > 1:
                    ids = sorted({troncons[k].id for k in ks}, key=cle_val)
                    self._ajouter("tension_incoherente_noeud", "mineure", "noeud %d" % n,
                                  "Tensions %s kV sur un nœud sans poste (tronçons %s)"
                                  % (" / ".join(_fmt(x) for x in tensions), ",".join(ids)),
                                  QgsGeometry.fromPointXY(coords[n]))

        # ---- 5. Écriture
        champs = QgsFields()
        champs.append(QgsField("id", QVariant.Int))
        champs.append(QgsField("type", QVariant.String))
        champs.append(QgsField("gravite", QVariant.String))
        champs.append(QgsField("id_objet", QVariant.String))
        champs.append(QgsField("detail", QVariant.String))
        (sink_p, id_p) = self.parameterAsSink(parameters, self.SORTIE_POINTS, context, champs,
                                              QgsWkbTypes.MultiPoint, crs)
        (sink_l, id_l) = self.parameterAsSink(parameters, self.SORTIE_LIGNES, context, champs,
                                              QgsWkbTypes.MultiLineString, crs)
        champs_r = QgsFields()
        champs_r.append(QgsField("gravite", QVariant.String))
        champs_r.append(QgsField("type", QVariant.String))
        champs_r.append(QgsField("nombre", QVariant.Int))
        (sink_r, id_r) = self.parameterAsSink(parameters, self.SORTIE_RESUME, context, champs_r,
                                              QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())

        compte = defaultdict(int)
        for i, (type_, gravite, id_objet, detail, geom) in enumerate(self.anomalies, start=1):
            compte[(gravite, type_)] += 1
            f = QgsFeature(champs)
            f.setAttributes([i, type_, gravite, id_objet, detail])
            cible = sink_l
            if geom is not None and not geom.isEmpty():
                gt = QgsWkbTypes.geometryType(geom.wkbType())
                if gt == QgsWkbTypes.PointGeometry:
                    g = QgsGeometry(geom)
                    g.convertToMultiType()
                    f.setGeometry(g)
                    cible = sink_p
                else:
                    parties = _parties_lignes(geom)
                    f.setGeometry(QgsGeometry.fromMultiPolylineXY(parties))
            cible.addFeature(f, QgsFeatureSink.FastInsert)
        for (gravite, type_) in sorted(compte, key=lambda c: (ORDRE_GRAVITE[c[0]], c[1])):
            f = QgsFeature(champs_r)
            f.setAttributes([gravite, type_, compte[(gravite, type_)]])
            sink_r.addFeature(f, QgsFeatureSink.FastInsert)

        nb = defaultdict(int)
        for (g, _), v in compte.items():
            nb[g] += v
        feedback.pushInfo(self.tr("Anomalies : %d bloquante(s), %d majeure(s), %d mineure(s), %d info")
                          % (nb["bloquante"], nb["majeure"], nb["mineure"], nb["info"]))
        feedback.pushInfo(self.tr("Hypothèses : accrochage %s m, quasi-connexion %s m, longueur minimale %s m%s%s")
                          % (_fmt(tol), _fmt(seuil), _fmt(long_min),
                             "" if f_pose else ", sans champ de pose (tout croisement est signalé)",
                             "" if f_etat else ", sans champ d'état (aucun point d'ouverture)"))
        return {self.SORTIE_POINTS: id_p, self.SORTIE_LIGNES: id_l, self.SORTIE_RESUME: id_r,
                "NB_ANOMALIES": len(self.anomalies)}

    @staticmethod
    def _blocs_biconnexes(adj):
        """Composantes biconnexes (blocs) d'un multigraphe non orienté, en listes d'arêtes.
        Algorithme de Tarjan, itératif ; les arêtes parallèles forment un bloc."""
        index, bas, compteur = {}, {}, [0]
        pile_aretes, blocs = [], []
        for depart in sorted(adj):
            if depart in index:
                continue
            index[depart] = bas[depart] = compteur[0]
            compteur[0] += 1
            pile = [(depart, None, iter(adj[depart]))]
            while pile:
                v, arete_parent, voisins = pile[-1]
                avance = False
                for w, k in voisins:
                    if k == arete_parent:
                        continue
                    if w not in index:
                        pile_aretes.append(k)
                        index[w] = bas[w] = compteur[0]
                        compteur[0] += 1
                        pile.append((w, k, iter(adj[w])))
                        avance = True
                        break
                    elif index[w] < index[v]:
                        pile_aretes.append(k)
                        bas[v] = min(bas[v], index[w])
                if avance:
                    continue
                pile.pop()
                if pile:
                    u = pile[-1][0]
                    bas[u] = min(bas[u], bas[v])
                    if bas[v] >= index[u]:
                        bloc = []
                        while True:
                            k = pile_aretes.pop()
                            bloc.append(k)
                            if k == arete_parent:
                                break
                        blocs.append(bloc)
        return blocs
