# -*- coding: utf-8 -*-
"""
Référencement linéaire ferroviaire dans QGIS, sans PostGIS : PK (km+m) <-> coordonnées.
Version PyQGIS du script scripts/referencement_pk.sql : même calage sur les bornes,
mêmes sauts de PK, même convention de décalage, mêmes avertissements.

Installation : dans QGIS, boîte à outils Traitements > icône Python >
« Ajouter un script à la boîte à outils… » et choisir ce fichier. L'algorithme
apparaît dans Scripts > Géomatique des réseaux > Référencement PK ferroviaire.

Testé avec QGIS 3.34. Les couches source ne sont jamais modifiées.

Convention de décalage : positif à GAUCHE dans le sens des PK croissants.
"""

import math
import re
from decimal import ROUND_HALF_UP, Decimal

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsLineString,
    QgsPoint,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsWkbTypes,
)


# --------------------------------------------------------------------------- PK
def pk_vers_m(pk):
    """'15+342' -> 15342.0 ; accepte '15+342.5', '015+342', '15 + 342', '15+342,5'."""
    m = re.match(r"^(-?\d+)\+(\d{1,3}(?:[.,]\d+)?)$", str(pk).replace(" ", ""))
    if not m:
        raise ValueError('PK "%s" illisible : format attendu km+m, par exemple 15+342' % pk)
    return int(m.group(1)) * 1000 + float(m.group(2).replace(",", "."))


def m_vers_pk(m):
    """15342.4 -> '15+342.4' ; 15042 -> '15+042' (arrondi au décimètre)."""
    d = Decimal(repr(m)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    km = int(d // 1000)
    reste = d - km * 1000
    ent = int(reste)
    dec = reste - ent
    txt = "%d+%03d" % (km, ent)
    if dec != 0:
        txt += str(dec.normalize())[1:]
    return txt


def _arrondi(x, n):
    return float(Decimal(repr(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def _texte(v):
    if v is None:
        return None
    try:
        if v.isNull():
            return None
    except AttributeError:
        pass
    s = str(v).strip()
    return s if s and s != "NULL" else None


# ------------------------------------------------------------------ géométrie
class AxeMesure:
    """Axe d'une ligne calé sur les bornes, découpé en tronçons mesurés en PK."""

    def __init__(self, ligne, bornes, sauts, distance_max, ecart_max):
        self.ligne = ligne                    # QgsLineString orientée
        self.geom = QgsGeometry(ligne.clone())
        self.longueur = ligne.length()
        self.distance_max = distance_max
        self.ecart_max = ecart_max
        self._caler(bornes, sauts)

    def _caler(self, bornes, sauts):
        cal = []
        for pk, g in bornes:
            cal.append({"origine": "borne", "pk_texte": pk, "pk_m": pk_vers_m(pk),
                        "abscisse": self.geom.lineLocatePoint(g), "dist": self.geom.distance(g)})
        for amont, aval, g in sauts:
            a = self.geom.lineLocatePoint(g)
            d = self.geom.distance(g)
            cal.append({"origine": "saut_amont", "pk_texte": amont, "pk_m": pk_vers_m(amont), "abscisse": a, "dist": d})
            cal.append({"origine": "saut_aval", "pk_texte": aval, "pk_m": pk_vers_m(aval), "abscisse": a, "dist": d})
        if not cal:
            raise QgsProcessingException("Aucune borne kilométrique pour cette ligne : calage impossible")
        cal.sort(key=lambda c: (c["abscisse"], c["pk_m"]))
        premier, dernier = cal[0], cal[-1]
        cal.insert(0, {"origine": "debut_axe", "pk_texte": None, "pk_m": premier["pk_m"] - premier["abscisse"],
                       "abscisse": 0.0, "dist": 0.0})
        cal.append({"origine": "fin_axe", "pk_texte": None,
                    "pk_m": dernier["pk_m"] + (self.longueur - dernier["abscisse"]),
                    "abscisse": self.longueur, "dist": 0.0})
        cal.sort(key=lambda c: (c["abscisse"], c["pk_m"]))
        for i, c in enumerate(cal, start=1):
            c["ordre"] = i
            if c["pk_texte"] is None:
                c["pk_texte"] = m_vers_pk(_arrondi(c["pk_m"], 1))
            av = []
            if c["dist"] > self.distance_max:
                av.append("Borne à %.1f m de l'axe" % c["dist"])
            if i > 1 and c["pk_m"] < cal[i - 2]["pk_m"]:
                av.append("PK non croissant par rapport au point de calage précédent (%s)" % cal[i - 2]["pk_texte"])
            c["avertissement"] = " ; ".join(av) or None
        self.calage = cal

        self.troncons = []
        for c1, c2 in zip(cal, cal[1:]):
            if c2["abscisse"] > c1["abscisse"] and c2["pk_m"] > c1["pk_m"]:
                long_ = c2["abscisse"] - c1["abscisse"]
                self.troncons.append({
                    "ordre": c1["ordre"], "pk_debut": c1["pk_texte"], "pk_fin": c2["pk_texte"],
                    "pk_debut_m": c1["pk_m"], "pk_fin_m": c2["pk_m"], "a1": c1["abscisse"], "a2": c2["abscisse"],
                    "echelle": (c2["pk_m"] - c1["pk_m"]) / long_,
                    "methode": "extrapolation hors bornes" if c1["origine"] == "debut_axe" or c2["origine"] == "fin_axe"
                    else "interpolation entre bornes",
                    "geom": QgsGeometry(self.ligne.curveSubstring(c1["abscisse"], c2["abscisse"])),
                })
        self.lacunes = [(a["pk_m"], b["pk_m"], "%s = %s" % (a["pk_texte"], b["pk_texte"]))
                        for a, b in zip(cal, cal[1:])
                        if a["origine"] == "saut_amont" and b["origine"] == "saut_aval" and b["pk_m"] > a["pk_m"]]

    # -- outils
    def _abscisse(self, t, pk):
        return t["a1"] + (pk - t["pk_debut_m"]) / (t["pk_fin_m"] - t["pk_debut_m"]) * (t["a2"] - t["a1"])

    def _direction(self, abscisse):
        """Vecteur unitaire de l'axe au droit de l'abscisse (segment qui la contient)."""
        cumul = 0.0
        pts = [self.ligne.pointN(i) for i in range(self.ligne.numPoints())]
        for p0, p1 in zip(pts, pts[1:]):
            l = math.hypot(p1.x() - p0.x(), p1.y() - p0.y())
            if cumul + l >= abscisse or p1 is pts[-1]:
                return ((p1.x() - p0.x()) / l, (p1.y() - p0.y()) / l) if l else (1.0, 0.0)
            cumul += l
        return (1.0, 0.0)

    def _avert_echelle(self, t, texte):
        if abs(t["echelle"] - 1) > self.ecart_max:
            return texte % (t["pk_debut"], t["pk_fin"], _arrondi((t["echelle"] - 1) * 100, 1))
        return None

    def bornes_ligne(self):
        return (min((c["pk_texte"] for c in self.calage if c["origine"] == "debut_axe")),
                min((c["pk_texte"] for c in self.calage if c["origine"] == "fin_axe")))

    # -- conversions
    def pk_vers_point(self, pk, decalage=0.0):
        """-> (QgsPointXY ou None, methode, avertissement)"""
        candidats = [t for t in self.troncons if t["pk_debut_m"] <= pk <= t["pk_fin_m"]]
        if not candidats:
            for a, b, lib in self.lacunes:
                if a < pk < b:
                    return None, "aucune", "PK inexistant : dans la lacune " + lib
            deb, fin = self.bornes_ligne()
            return None, "aucune", "PK hors de la ligne (%s à %s)" % (deb, fin)
        t = min(candidats, key=lambda t: t["ordre"])
        a = self._abscisse(t, pk)
        p = self.geom.interpolate(a).asPoint()
        if decalage:
            dx, dy = self._direction(a)
            p = QgsPointXY(p.x() - dy * decalage, p.y() + dx * decalage)   # normale à gauche
        methode = t["methode"] + (", décalage %s m" % ("%g" % decalage) if decalage else "")
        if t["methode"].startswith("extrapolation"):
            av = "PK hors des bornes : position extrapolée, à vérifier"
        else:
            av = self._avert_echelle(t, "Kilomètre %s - %s : écart de %s %% entre PK et longueur mesurée "
                                        "(saut de PK non déclaré ?)")
        return p, methode, av

    def point_vers_pk(self, g):
        """-> (pk_m, pk, distance_axe_m, decalage_m, methode, avertissement)"""
        t = min(self.troncons, key=lambda t: (round(t["geom"].distance(g), 6), t["ordre"]))
        sub = t["geom"]
        loc = sub.lineLocatePoint(g)
        long_ = sub.length()
        m = t["pk_debut_m"] + (loc / long_) * (t["pk_fin_m"] - t["pk_debut_m"]) if long_ else t["pk_debut_m"]
        d = sub.distance(g)
        a = t["a1"] + loc
        dx, dy = self._direction(a)
        p0 = self.geom.interpolate(a).asPoint()
        pt = g.asPoint()
        croix = dx * (pt.y() - p0.y()) - dy * (pt.x() - p0.x())
        cote = (croix > 1e-9) - (croix < -1e-9)
        av = []
        if d > self.distance_max:
            av.append("Point à %.1f m de l'axe : rattachement douteux" % d)
        if t["methode"].startswith("extrapolation"):
            av.append("Hors des bornes : PK extrapolé")
        for a_, b_, lib in self.lacunes:
            if abs(m - a_) < 1 or abs(m - b_) < 1:
                av.append("Au droit du saut de PK %s : les deux PK désignent ce point" % lib)
                break
        if abs(t["echelle"] - 1) > self.ecart_max:
            av.append("Kilomètre %s - %s hors échelle" % (t["pk_debut"], t["pk_fin"]))
        m1 = _arrondi(m, 1)
        return m1, m_vers_pk(m1), _arrondi(d, 2), _arrondi(d * cote, 2), t["methode"], " ; ".join(av) or None

    def evenement_lineaire(self, debut, fin):
        """-> (QgsGeometry ou None, longueur, avertissement)"""
        lo, hi = min(debut, fin), max(debut, fin)
        morceaux = []
        for t in self.troncons:
            if t["pk_fin_m"] >= lo and t["pk_debut_m"] <= hi:
                a = self._abscisse(t, max(lo, t["pk_debut_m"]))
                b = self._abscisse(t, min(hi, t["pk_fin_m"]))
                if b > a:
                    morceaux.append(self.ligne.curveSubstring(a, b))
        av = []
        lac = [lib for a, b, lib in self.lacunes if a < hi and b > lo]
        if lac:
            av.append("Contient la lacune %s : longueur terrain < écart de PK" % ", ".join(lac))
        if not morceaux:
            return None, None, "Intervalle hors de la ligne"
        g = QgsGeometry.unaryUnion([QgsGeometry(m) for m in morceaux]).mergeLines()
        return g, g.length(), " ; ".join(av) or None


# ----------------------------------------------------------------- algorithme
class ReferencementPkFerroviaire(QgsProcessingAlgorithm):
    AXES = "AXES"
    CHAMP_LIGNE_AXE = "CHAMP_LIGNE_AXE"
    CODE_LIGNE = "CODE_LIGNE"
    CHAMP_VOIE = "CHAMP_VOIE"
    VOIE = "VOIE"
    BORNES = "BORNES"
    CHAMP_LIGNE_BORNE = "CHAMP_LIGNE_BORNE"
    CHAMP_PK_BORNE = "CHAMP_PK_BORNE"
    SAUTS = "SAUTS"
    CHAMP_LIGNE_SAUT = "CHAMP_LIGNE_SAUT"
    CHAMP_PK_AMONT = "CHAMP_PK_AMONT"
    CHAMP_PK_AVAL = "CHAMP_PK_AVAL"
    PK_ENTREE = "PK_ENTREE"
    CHAMP_PK = "CHAMP_PK"
    CHAMP_DECALAGE = "CHAMP_DECALAGE"
    POINTS = "POINTS"
    EVENEMENTS = "EVENEMENTS"
    CHAMP_PK_DEBUT = "CHAMP_PK_DEBUT"
    CHAMP_PK_FIN = "CHAMP_PK_FIN"
    DISTANCE_MAX = "DISTANCE_MAX"
    ECART_ECHELLE = "ECART_ECHELLE"
    SORTIE_PK_XY = "SORTIE_PK_XY"
    SORTIE_XY_PK = "SORTIE_XY_PK"
    SORTIE_EVENEMENTS = "SORTIE_EVENEMENTS"
    SORTIE_CALAGE = "SORTIE_CALAGE"

    def tr(self, s):
        return QCoreApplication.translate("ReferencementPkFerroviaire", s)

    def createInstance(self):
        return ReferencementPkFerroviaire()

    def name(self):
        return "referencement_pk_ferroviaire"

    def displayName(self):
        return self.tr("Référencement PK ferroviaire")

    def group(self):
        return self.tr("Géomatique des réseaux")

    def groupId(self):
        return "geomatique_reseaux"

    def shortHelpString(self):
        return self.tr(
            "Convertit des PK (format km+m, ex. 15+342) en points et inversement, le long d'une ligne "
            "ferroviaire. L'axe est fusionné, orienté dans le sens des PK croissants et calé sur les bornes "
            "kilométriques ; les sauts de PK sont pris en compte.\n\n"
            "Entrées facultatives, à donner selon le besoin : une table de PK à convertir (avec un décalage "
            "latéral, positif à gauche dans le sens des PK croissants), une couche de points à localiser, "
            "une table d'événements linéaires (de PK à PK).\n\n"
            "Travaillez dans un SCR projeté en mètres (Lambert 93, EPSG:2154, en métropole). Un point à plus "
            "de la distance maximale de l'axe est signalé. La couche « points de calage » permet de contrôler "
            "les bornes.")

    def initAlgorithm(self, config=None):
        P = self
        P.addParameter(QgsProcessingParameterFeatureSource(P.AXES, P.tr("Axes des lignes"),
                                                           [QgsProcessing.TypeVectorLine]))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_LIGNE_AXE, P.tr("Champ code ligne des axes"),
                                                   parentLayerParameterName=P.AXES, optional=True))
        P.addParameter(QgsProcessingParameterString(P.CODE_LIGNE, P.tr("Code ligne à traiter (ex. 830000)"),
                                                    optional=True))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_VOIE, P.tr("Champ voie des axes (facultatif)"),
                                                   parentLayerParameterName=P.AXES, optional=True))
        P.addParameter(QgsProcessingParameterString(P.VOIE, P.tr("Voie à traiter (ex. V1)"), optional=True))
        P.addParameter(QgsProcessingParameterFeatureSource(P.BORNES, P.tr("Bornes kilométriques"),
                                                           [QgsProcessing.TypeVectorPoint]))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_LIGNE_BORNE, P.tr("Champ code ligne des bornes"),
                                                   parentLayerParameterName=P.BORNES, optional=True))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_PK_BORNE, P.tr("Champ PK des bornes (km+m)"),
                                                   parentLayerParameterName=P.BORNES))
        P.addParameter(QgsProcessingParameterFeatureSource(P.SAUTS, P.tr("Sauts de PK (facultatif)"),
                                                           [QgsProcessing.TypeVectorPoint], optional=True))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_LIGNE_SAUT, P.tr("Champ code ligne des sauts"),
                                                   parentLayerParameterName=P.SAUTS, optional=True))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_PK_AMONT, P.tr("Champ PK amont du saut"),
                                                   parentLayerParameterName=P.SAUTS, optional=True))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_PK_AVAL, P.tr("Champ PK aval du saut"),
                                                   parentLayerParameterName=P.SAUTS, optional=True))
        P.addParameter(QgsProcessingParameterFeatureSource(P.PK_ENTREE, P.tr("PK à convertir en points (table)"),
                                                           [QgsProcessing.TypeVector], optional=True))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_PK, P.tr("Champ PK à convertir"),
                                                   parentLayerParameterName=P.PK_ENTREE, optional=True))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_DECALAGE, P.tr("Champ décalage en m (facultatif)"),
                                                   parentLayerParameterName=P.PK_ENTREE, optional=True))
        P.addParameter(QgsProcessingParameterFeatureSource(P.POINTS, P.tr("Points à localiser en PK"),
                                                           [QgsProcessing.TypeVectorPoint], optional=True))
        P.addParameter(QgsProcessingParameterFeatureSource(P.EVENEMENTS,
                                                           P.tr("Événements linéaires de PK à PK (table)"),
                                                           [QgsProcessing.TypeVector], optional=True))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_PK_DEBUT, P.tr("Champ PK de début"),
                                                   parentLayerParameterName=P.EVENEMENTS, optional=True))
        P.addParameter(QgsProcessingParameterField(P.CHAMP_PK_FIN, P.tr("Champ PK de fin"),
                                                   parentLayerParameterName=P.EVENEMENTS, optional=True))
        P.addParameter(QgsProcessingParameterNumber(P.DISTANCE_MAX, P.tr("Distance maximale à l'axe (m)"),
                                                    QgsProcessingParameterNumber.Double, 20.0, minValue=0))
        P.addParameter(QgsProcessingParameterNumber(P.ECART_ECHELLE,
                                                    P.tr("Écart toléré entre PK et longueur réelle (0,05 = 5 %)"),
                                                    QgsProcessingParameterNumber.Double, 0.05, minValue=0))
        P.addParameter(QgsProcessingParameterFeatureSink(P.SORTIE_PK_XY, P.tr("PK convertis en points"),
                                                         QgsProcessing.TypeVectorPoint))
        P.addParameter(QgsProcessingParameterFeatureSink(P.SORTIE_XY_PK, P.tr("Points localisés en PK"),
                                                         QgsProcessing.TypeVectorPoint))
        P.addParameter(QgsProcessingParameterFeatureSink(P.SORTIE_EVENEMENTS, P.tr("Événements linéaires"),
                                                         QgsProcessing.TypeVectorLine))
        P.addParameter(QgsProcessingParameterFeatureSink(P.SORTIE_CALAGE, P.tr("Points de calage (contrôle)"),
                                                         QgsProcessing.TypeVectorPoint))

    # ----------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        s = lambda n: self.parameterAsString(parameters, n, context)  # noqa: E731
        axes = self.parameterAsSource(parameters, self.AXES, context)
        bornes_src = self.parameterAsSource(parameters, self.BORNES, context)
        sauts_src = self.parameterAsSource(parameters, self.SAUTS, context)
        code = s(self.CODE_LIGNE).strip()
        voie = s(self.VOIE).strip()
        crs = axes.sourceCrs()
        if crs.isGeographic():
            raise QgsProcessingException(self.tr(
                "L'axe est en coordonnées géographiques (%s) : reprojetez-le d'abord, en Lambert 93 "
                "(EPSG:2154) en métropole.") % crs.authid())
        if crs.authid() != "EPSG:2154":
            feedback.pushWarning(self.tr("Axe en %s au lieu de Lambert 93 (EPSG:2154) : calculs faits dans ce SCR.")
                                 % crs.authid())

        def meme_ligne(f, champ, valeur):
            return not champ or not valeur or _texte(f[champ]) == valeur

        def lire_points(src, xform_crs):
            xf = None
            if src.sourceCrs() != xform_crs:
                xf = QgsCoordinateTransform(src.sourceCrs(), xform_crs, context.transformContext())
            for f in src.getFeatures():
                g = QgsGeometry(f.geometry())
                if g.isNull() or g.isEmpty():
                    yield f, None
                    continue
                if xf:
                    g.transform(xf)
                if g.isMultipart():
                    g = QgsGeometry.fromPointXY(g.asMultiPoint()[0])
                yield f, g

        # ---- 1. Axe : une ligne, une voie, fusionnée
        parties = []
        for f in axes.getFeatures():
            if not meme_ligne(f, s(self.CHAMP_LIGNE_AXE), code) or not meme_ligne(f, s(self.CHAMP_VOIE), voie):
                continue
            g = f.geometry()
            parties.extend(g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()])
        if not parties:
            raise QgsProcessingException(self.tr("Aucun axe trouvé pour cette ligne"))
        fusion = QgsGeometry.fromMultiPolylineXY(parties).mergeLines()
        if fusion.isMultipart() and len(fusion.asMultiPolyline()) > 1:
            raise QgsProcessingException(self.tr(
                "L'axe reste en %d morceaux après fusion : trous ou embranchements à traiter avant le calage")
                % len(fusion.asMultiPolyline()))
        pts = fusion.asMultiPolyline()[0] if fusion.isMultipart() else fusion.asPolyline()
        ligne = QgsLineString([QgsPoint(p) for p in pts])

        bornes = [(_texte(f[s(self.CHAMP_PK_BORNE)]), g) for f, g in lire_points(bornes_src, crs)
                  if g is not None and meme_ligne(f, s(self.CHAMP_LIGNE_BORNE), code)
                  and _texte(f[s(self.CHAMP_PK_BORNE)])]
        sauts = []
        if sauts_src is not None and s(self.CHAMP_PK_AMONT) and s(self.CHAMP_PK_AVAL):
            sauts = [(_texte(f[s(self.CHAMP_PK_AMONT)]), _texte(f[s(self.CHAMP_PK_AVAL)]), g)
                     for f, g in lire_points(sauts_src, crs)
                     if g is not None and meme_ligne(f, s(self.CHAMP_LIGNE_SAUT), code)]
        if not bornes:
            raise QgsProcessingException(self.tr("Aucune borne kilométrique pour cette ligne : calage impossible"))

        # Orientation : la borne de plus petit PK doit être vers le début de l'axe
        g_axe = QgsGeometry(ligne.clone())
        bmin = min(bornes, key=lambda b: pk_vers_m(b[0]))
        bmax = max(bornes, key=lambda b: pk_vers_m(b[0]))
        if g_axe.lineLocatePoint(bmin[1]) > g_axe.lineLocatePoint(bmax[1]):
            ligne = ligne.reversed()
            feedback.pushInfo(self.tr("Axe retourné pour suivre le sens des PK croissants"))

        axe = AxeMesure(ligne, bornes, sauts, self.parameterAsDouble(parameters, self.DISTANCE_MAX, context),
                        self.parameterAsDouble(parameters, self.ECART_ECHELLE, context))
        deb, fin = axe.bornes_ligne()
        feedback.pushInfo(self.tr("Ligne %s%s : de %s à %s, %d borne(s), %d saut(s) de PK")
                          % (code or "(toutes)", (" voie " + voie) if voie else "", deb, fin, len(bornes), len(sauts)))
        resultats = {}

        # ---- 2. Points de calage
        ch = QgsFields()
        for n, t in (("ordre", QVariant.Int), ("origine", QVariant.String), ("pk", QVariant.String),
                     ("abscisse_m", QVariant.Double), ("dist_axe_m", QVariant.Double),
                     ("avertissement", QVariant.String)):
            ch.append(QgsField(n, t))
        sink, resultats[self.SORTIE_CALAGE] = self.parameterAsSink(parameters, self.SORTIE_CALAGE, context, ch,
                                                                   QgsWkbTypes.Point, crs)
        for c in axe.calage:
            f = QgsFeature(ch)
            f.setGeometry(axe.geom.interpolate(c["abscisse"]))
            f.setAttributes([c["ordre"], c["origine"], c["pk_texte"], _arrondi(c["abscisse"], 1),
                             _arrondi(c["dist"], 1), c["avertissement"]])
            sink.addFeature(f, QgsFeatureSink.FastInsert)
            if c["avertissement"]:
                feedback.pushWarning("%s %s : %s" % (c["origine"], c["pk_texte"], c["avertissement"]))

        def champs_sortie(src, ajouts):
            ch = QgsFields()
            noms = set()
            if src is not None:
                for fl in src.fields():
                    ch.append(QgsField(fl))
                    noms.add(fl.name().lower())
            for n, t in ajouts:
                ch.append(QgsField(n + "_res" if n.lower() in noms else n, t))
            return ch

        # ---- 3. PK -> points
        src = self.parameterAsSource(parameters, self.PK_ENTREE, context)
        ajouts = [("x_l93", QVariant.Double), ("y_l93", QVariant.Double), ("methode", QVariant.String),
                  ("avertissement", QVariant.String)]
        ch = champs_sortie(src, ajouts)
        sink, resultats[self.SORTIE_PK_XY] = self.parameterAsSink(parameters, self.SORTIE_PK_XY, context, ch,
                                                                  QgsWkbTypes.Point, crs)
        n_ok = n_av = 0
        if src is not None:
            if not s(self.CHAMP_PK):
                raise QgsProcessingException(self.tr("Indiquez le champ PK de la table de PK à convertir"))
            for f in src.getFeatures():
                dec = 0.0
                if s(self.CHAMP_DECALAGE) and _texte(f[s(self.CHAMP_DECALAGE)]):
                    dec = float(_texte(f[s(self.CHAMP_DECALAGE)]).replace(",", "."))
                try:
                    p, methode, av = axe.pk_vers_point(pk_vers_m(_texte(f[s(self.CHAMP_PK)])), dec)
                except ValueError as e:
                    p, methode, av = None, "aucune", str(e)
                g = QgsFeature(ch)
                attrs = list(f.attributes())
                if p is not None:
                    g.setGeometry(QgsGeometry.fromPointXY(p))
                    attrs += [_arrondi(p.x(), 2), _arrondi(p.y(), 2), methode, av]
                    n_ok += 1
                else:
                    attrs += [None, None, methode, av]
                n_av += 1 if av else 0
                g.setAttributes(attrs)
                sink.addFeature(g, QgsFeatureSink.FastInsert)
            feedback.pushInfo(self.tr("PK -> points : %d converti(s), %d avertissement(s)") % (n_ok, n_av))

        # ---- 4. Points -> PK
        src = self.parameterAsSource(parameters, self.POINTS, context)
        ajouts = [("x_l93", QVariant.Double), ("y_l93", QVariant.Double), ("pk", QVariant.String),
                  ("distance_axe_m", QVariant.Double), ("decalage_m", QVariant.Double),
                  ("methode", QVariant.String), ("avertissement", QVariant.String)]
        ch = champs_sortie(src, ajouts)
        sink, resultats[self.SORTIE_XY_PK] = self.parameterAsSink(parameters, self.SORTIE_XY_PK, context, ch,
                                                                  QgsWkbTypes.Point, crs)
        if src is not None:
            n_ok = n_av = 0
            for f, g in lire_points(src, crs):
                h = QgsFeature(ch)
                attrs = list(f.attributes())
                if g is None:
                    attrs += [None, None, None, None, None, "aucune", "Point sans géométrie"]
                else:
                    m, pk, d, dec, methode, av = axe.point_vers_pk(g)
                    h.setGeometry(g)
                    attrs += [_arrondi(g.asPoint().x(), 2), _arrondi(g.asPoint().y(), 2), pk, d, dec, methode, av]
                    n_ok += 1
                    n_av += 1 if av else 0
                h.setAttributes(attrs)
                sink.addFeature(h, QgsFeatureSink.FastInsert)
            feedback.pushInfo(self.tr("Points -> PK : %d localisé(s), %d avertissement(s)") % (n_ok, n_av))

        # ---- 5. Événements linéaires
        src = self.parameterAsSource(parameters, self.EVENEMENTS, context)
        ajouts = [("longueur_terrain_m", QVariant.Double), ("avertissement", QVariant.String)]
        ch = champs_sortie(src, ajouts)
        sink, resultats[self.SORTIE_EVENEMENTS] = self.parameterAsSink(parameters, self.SORTIE_EVENEMENTS, context,
                                                                       ch, QgsWkbTypes.MultiLineString, crs)
        if src is not None:
            if not (s(self.CHAMP_PK_DEBUT) and s(self.CHAMP_PK_FIN)):
                raise QgsProcessingException(self.tr("Indiquez les champs PK de début et de fin des événements"))
            for f in src.getFeatures():
                try:
                    g, longueur, av = axe.evenement_lineaire(pk_vers_m(_texte(f[s(self.CHAMP_PK_DEBUT)])),
                                                             pk_vers_m(_texte(f[s(self.CHAMP_PK_FIN)])))
                except ValueError as e:
                    g, longueur, av = None, None, str(e)
                h = QgsFeature(ch)
                if g is not None:
                    g.convertToMultiType()
                    h.setGeometry(g)
                h.setAttributes(list(f.attributes()) + [None if longueur is None else _arrondi(longueur, 1), av])
                sink.addFeature(h, QgsFeatureSink.FastInsert)

        feedback.pushInfo(self.tr("Convention de décalage : positif à gauche dans le sens des PK croissants"))
        return resultats
