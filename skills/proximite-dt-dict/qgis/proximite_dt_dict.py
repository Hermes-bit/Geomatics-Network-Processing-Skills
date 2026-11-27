# -*- coding: utf-8 -*-
"""
Proximité DT-DICT dans QGIS, sans PostGIS : réseaux proches d'une emprise de travaux et
exploitants concernés. Version PyQGIS du script scripts/proximite_dt_dict.sql : mêmes classes
de précision, mêmes zones d'incertitude, même fuseau aérien, mêmes alertes et mêmes contrôles
de l'emprise (arrêté du 15 février 2012 modifié).

Pré-analyse seulement : la liste officielle des exploitants est celle du guichet unique
(reseaux-et-canalisations.ineris.fr).

Installation : dans QGIS, boîte à outils Traitements > icône Python >
« Ajouter un script à la boîte à outils… » et choisir ce fichier. L'algorithme apparaît
dans Scripts > Géomatique des réseaux > Proximité DT-DICT.

Testé avec QGIS 3.34. Les couches source ne sont jamais modifiées.
"""

from decimal import ROUND_HALF_UP, Decimal

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

# Réseaux sensibles pour la sécurité (art. R. 554-2 du code de l'environnement), comme dtdict.categories
CATEGORIES = {
    "electricite": True, "gaz": True, "hydrocarbures": True, "chimie": True, "chaleur": True,
    "ferroviaire": True, "telecom": False, "eau": False, "assainissement": False, "eclairage": False,
    "autre": None,
}
ORDRE = {"dans_emprise": 1, "fuseau_aerien": 2, "zone_incertitude": 3, "proximite": 4}


def _arrondi(x, n=2):
    return float(Decimal(repr(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def _val(v):
    if v is None:
        return None
    try:
        if v.isNull():
            return None
    except AttributeError:
        pass
    if isinstance(v, str):
        v = v.strip()
        return v if v and v != "NULL" else None
    return v


def _bool(v):
    v = _val(v)
    if v is None:
        return None
    if isinstance(v, str):
        return v.lower() in ("true", "t", "1", "oui", "o", "yes", "vrai")
    return bool(v)


def _num(v):
    v = _val(v)
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def _texte_nombre(x):
    """20.0 -> '20', 0.4 -> '0.4' (comme PostgreSQL pour un numeric)."""
    return ("%f" % x).rstrip("0").rstrip(".")


def analyser(emprise_geoms, urgent, ouvrages, exploitants, p):
    """Cœur du calcul, sans dépendance aux Traitements (réutilisé par analyse-impact-chantier).

    emprise_geoms : liste de QgsGeometry (polygones) ; ouvrages : liste de dicts avec id, exploitant,
    categorie, pose, classe_precision, flexible, branchement, tension_kv, geom ; exploitants : dict
    exploitant -> (contact, telephone_urgence) ; p : paramètres (voir PARAMETRES).
    Renvoie (emprise_union, controles, ouvrages_concernes, exploitants_concernes).
    """
    valide = all(g.isGeosValid() for g in emprise_geoms)
    reparees = [g.makeValid() for g in emprise_geoms]
    union = QgsGeometry.unaryUnion(reparees)

    controles = [("géométrie valide", "oui" if valide else "non : réparée avec makeValid", valide)]
    smax = p["surface_max_urgent_ha"] if urgent else p["surface_max_ha"]
    surface = union.area() / 10000
    controles.append(("surface totale", "%s ha (maximum %s ha)" % (
        "%.2f" % _arrondi(surface, 2), _texte_nombre(smax)), surface <= smax))
    sommets = [QgsGeometry.fromPointXY(v) for v in
               (union.convexHull().asPolygon() or [[]])[0]] if not union.isEmpty() else []
    etendue = max((a.distance(b) for a in sommets for b in sommets), default=0.0)
    controles.append(("étendue (points les plus éloignés)", "%d m (maximum %s m)" % (
        int(_arrondi(etendue, 0)), _texte_nombre(p["etendue_max"])), etendue <= p["etendue_max"]))
    if len(reparees) < 2:
        controles.append(("écart entre polygones", "un seul polygone", True))
    else:
        ecarts = [min(a.distance(b) for j, b in enumerate(reparees) if j != i) for i, a in enumerate(reparees)]
        controles.append(("écart entre polygones", "plus grand écart au voisin le plus proche : %.1f m (maximum %s m)"
                          % (_arrondi(max(ecarts), 1), _texte_nombre(p["ecart_max_polygones"])),
                          max(ecarts) <= p["ecart_max_polygones"]))

    rayon = max(p["marge_proximite"], p["fuseau_aerien"], p["incertitude_c_min"])
    zone_recherche = union.boundingBox().buffered(rayon)
    retenus = []
    for o in ouvrages:
        g = o["geom"]
        if g is None or g.isEmpty() or not g.boundingBox().intersects(zone_recherche):
            continue
        dist = g.distance(union)
        if dist > rayon:
            continue
        categorie = (o.get("categorie") or None)
        pose = (o.get("pose") or None)
        classe_brute = o.get("classe_precision")
        classe = (classe_brute or "C").upper()
        sensible = CATEGORIES.get(categorie) if categorie in CATEGORIES else None
        if classe == "A":
            incert = p["incertitude_a_flexible"] if o.get("flexible") else p["incertitude_a_rigide"]
        elif classe == "B":
            incert = p["incertitude_b_branch"] if o.get("branchement") else p["incertitude_b"]
        else:
            incert = p["incertitude_c_min"]
        tension = o.get("tension_kv")
        if dist == 0:
            situation = "dans_emprise"
        elif pose == "aerien" and dist <= p["fuseau_aerien"]:
            situation = "fuseau_aerien"
        elif dist <= incert:
            situation = "zone_incertitude"
        else:
            situation = "proximite"
        alertes = []
        if sensible is None:
            alertes.append("catégorie « %s » : sensibilité à vérifier" % (categorie or "vide"))
        if classe_brute is None:
            alertes.append("classe de précision inconnue : traitée comme C")
        if classe == "C":
            alertes.append("classe C : position réelle inconnue, ne pas se fier à la distance")
        if sensible and pose == "souterrain" and classe in ("B", "C") and dist <= incert:
            alertes.append("ouvrage sensible enterré non classé A dans l'emprise ou sa zone d'incertitude : "
                           "investigations complémentaires ou mesures de localisation à prévoir")
        if pose == "aerien" and categorie == "electricite" and (tension or 0) > 1:
            alertes.append("ligne aérienne HTA ou HTB : distances de sécurité du code du travail à respecter, "
                           "consulter l'exploitant")
        if pose == "aerien" and dist > p["fuseau_aerien"] and (
                categorie == "ferroviaire" or (categorie == "electricite" and (tension or 0) <= 1)):
            alertes.append("aérien au-delà de %s m en projection horizontale : exemption possible pour des "
                           "travaux aériens sans permis, à vérifier" % _texte_nombre(p["fuseau_aerien"]))
        retenus.append({
            "id": str(o["id"]), "exploitant": o.get("exploitant"), "categorie": categorie, "sensible": sensible,
            "pose": pose, "classe": classe, "incertitude_m": incert, "tension_kv": tension,
            "distance_m": _arrondi(dist, 2), "situation": situation, "alertes": " ; ".join(alertes),
            "ordre": ORDRE[situation], "geom": g})
    retenus.sort(key=lambda o: (o["ordre"], o["distance_m"], o["id"]))

    groupes = {}
    for o in retenus:
        groupes.setdefault(o["exploitant"], []).append(o)
    expl = []
    for nom, liste in groupes.items():
        sens = [o["sensible"] for o in liste if o["sensible"] is not None]
        contact, tel = exploitants.get(nom, (None, None))
        expl.append({
            "exploitant": nom,
            "categories": ", ".join(sorted({o["categorie"] for o in liste if o["categorie"]})),
            "reseau_sensible": any(sens) if sens else None,
            "nb_ouvrages": len(liste),
            "distance_min_m": min(o["distance_m"] for o in liste),
            "situation_la_plus_proche": min(liste, key=lambda o: o["ordre"])["situation"],
            "ic_a_prevoir": any("investigations complémentaires" in o["alertes"] for o in liste),
            "contact": contact, "telephone_urgence": tel})
    expl.sort(key=lambda e: ({True: 0, False: 1, None: 2}[e["reseau_sensible"]], e["distance_min_m"],
                             e["exploitant"] or ""))
    return union, controles, retenus, expl


PARAMETRES = {
    "marge_proximite": 5.0, "fuseau_aerien": 3.0, "incertitude_a_rigide": 0.40, "incertitude_a_flexible": 0.50,
    "incertitude_b": 1.50, "incertitude_b_branch": 1.00, "incertitude_c_min": 1.50, "surface_max_ha": 20.0,
    "surface_max_urgent_ha": 2.0, "ecart_max_polygones": 50.0, "etendue_max": 20000.0,
}


class ProximiteDtDict(QgsProcessingAlgorithm):
    EMPRISE = "EMPRISE"
    URGENT = "URGENT"
    OUVRAGES = "OUVRAGES"
    CHAMPS = (  # (paramètre, champ normalisé par défaut, libellé)
        ("CHAMP_ID", "id", "Champ identifiant de l'ouvrage"),
        ("CHAMP_EXPLOITANT", "exploitant", "Champ exploitant"),
        ("CHAMP_CATEGORIE", "categorie", "Champ catégorie (electricite, gaz, telecom…)"),
        ("CHAMP_POSE", "pose", "Champ mode de pose (souterrain, aerien, subaquatique)"),
        ("CHAMP_CLASSE", "classe_precision", "Champ classe de précision (A, B, C)"),
        ("CHAMP_FLEXIBLE", "flexible", "Champ ouvrage flexible (vrai / faux)"),
        ("CHAMP_BRANCHEMENT", "branchement", "Champ branchement (vrai / faux)"),
        ("CHAMP_TENSION", "tension_kv", "Champ tension en kV"),
    )
    EXPLOITANTS = "EXPLOITANTS"
    MARGE = "MARGE"
    SORTIE_OUVRAGES = "SORTIE_OUVRAGES"
    SORTIE_EXPLOITANTS = "SORTIE_EXPLOITANTS"
    SORTIE_CONTROLE = "SORTIE_CONTROLE"

    def tr(self, texte):
        return QCoreApplication.translate("ProximiteDtDict", texte)

    def createInstance(self):
        return ProximiteDtDict()

    def name(self):
        return "proximite_dt_dict"

    def displayName(self):
        return self.tr("Proximité DT-DICT")

    def group(self):
        return self.tr("Géomatique des réseaux")

    def groupId(self):
        return "geomatique_reseaux"

    def shortHelpString(self):
        return self.tr(
            "Repère les réseaux proches d'une emprise de travaux et liste les exploitants à consulter pour une "
            "DT, une DICT ou une ATU : classes de précision A, B, C, zones d'incertitude, fuseau de 3 m des "
            "réseaux aériens, investigations complémentaires, contrôles de l'emprise (20 ha, 50 m entre "
            "polygones, 20 km). Ne remplace pas le guichet unique. Couches en Lambert 93 (EPSG:2154). "
            "Une classe vide est traitée comme C.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.EMPRISE, self.tr("Emprise des travaux (polygones d'une même déclaration)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterBoolean(self.URGENT, self.tr("Travaux urgents (2 ha au plus)"), False))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.OUVRAGES, self.tr("Ouvrages (réseaux)"), [QgsProcessing.TypeVectorAnyGeometry]))
        for nom, defaut, libelle in self.CHAMPS:
            self.addParameter(QgsProcessingParameterField(nom, self.tr(libelle), defaultValue=defaut,
                                                          parentLayerParameterName=self.OUVRAGES, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.EXPLOITANTS, self.tr("Exploitants : champs exploitant, contact, telephone_urgence (facultatif)"),
            [QgsProcessing.TypeVector], optional=True))
        self.addParameter(QgsProcessingParameterNumber(self.MARGE, self.tr("Marge de proximité (m)"),
                                                       QgsProcessingParameterNumber.Double, 5.0, minValue=0))
        self.addParameter(QgsProcessingParameterFeatureSink(self.SORTIE_OUVRAGES, self.tr("Ouvrages concernés"),
                                                            QgsProcessing.TypeVectorAnyGeometry))
        self.addParameter(QgsProcessingParameterFeatureSink(self.SORTIE_EXPLOITANTS, self.tr("Exploitants concernés"),
                                                            QgsProcessing.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(self.SORTIE_CONTROLE, self.tr("Contrôle de l'emprise"),
                                                            QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        emprise = self.parameterAsSource(parameters, self.EMPRISE, context)
        ouvr = self.parameterAsSource(parameters, self.OUVRAGES, context)
        crs = ouvr.sourceCrs()
        if crs.isGeographic():
            raise QgsProcessingException(self.tr("Ouvrages en coordonnées géographiques (%s) : reprojetez-les en "
                                                 "Lambert 93 (EPSG:2154)") % crs.authid())
        if crs.authid() != "EPSG:2154":
            feedback.pushWarning(self.tr("Couches en %s au lieu de Lambert 93 : calculs faits dans ce SCR")
                                 % crs.authid())
        xf = None
        if emprise.sourceCrs() != crs:
            xf = QgsCoordinateTransform(emprise.sourceCrs(), crs, context.transformContext())
        geoms = []
        for f in emprise.getFeatures():
            g = QgsGeometry(f.geometry())
            if g.isNull() or g.isEmpty():
                continue
            if xf:
                g.transform(xf)
            geoms.append(g)
        if not geoms:
            raise QgsProcessingException(self.tr("Aucun polygone d'emprise trouvé"))

        champ = {nom: self.parameterAsString(parameters, nom, context) for nom, _, _ in self.CHAMPS}
        noms_champs = ouvr.fields().names()

        def lire(f, nom):
            c = champ[nom]
            return f[c] if c and c in noms_champs else None

        ouvrages = []
        for f in ouvr.getFeatures():
            ident = _val(lire(f, "CHAMP_ID"))
            ouvrages.append({
                "id": f.id() if ident is None else (int(ident) if isinstance(ident, float) and ident.is_integer()
                                                     else ident),
                "exploitant": _val(lire(f, "CHAMP_EXPLOITANT")),
                "categorie": (_val(lire(f, "CHAMP_CATEGORIE")) or None) and str(_val(lire(f, "CHAMP_CATEGORIE"))).lower(),
                "pose": (_val(lire(f, "CHAMP_POSE")) or None) and str(_val(lire(f, "CHAMP_POSE"))).lower(),
                "classe_precision": _val(lire(f, "CHAMP_CLASSE")),
                "flexible": _bool(lire(f, "CHAMP_FLEXIBLE")), "branchement": _bool(lire(f, "CHAMP_BRANCHEMENT")),
                "tension_kv": _num(lire(f, "CHAMP_TENSION")), "geom": QgsGeometry(f.geometry())})
        exploitants = {}
        src_expl = self.parameterAsSource(parameters, self.EXPLOITANTS, context)
        if src_expl is not None:
            n = src_expl.fields().names()
            for f in src_expl.getFeatures(QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)):
                if "exploitant" in n:
                    exploitants[_val(f["exploitant"])] = (_val(f["contact"]) if "contact" in n else None,
                                                          _val(f["telephone_urgence"]) if "telephone_urgence" in n
                                                          else None)

        p = dict(PARAMETRES, marge_proximite=self.parameterAsDouble(parameters, self.MARGE, context))
        _, controles, retenus, expl = analyser(geoms, self.parameterAsBoolean(parameters, self.URGENT, context),
                                               ouvrages, exploitants, p)
        resultats = {}

        ch = QgsFields()
        for n, t in (("id", QVariant.String), ("exploitant", QVariant.String), ("categorie", QVariant.String),
                     ("sensible", QVariant.Bool), ("pose", QVariant.String), ("classe", QVariant.String),
                     ("incertitude_m", QVariant.Double), ("tension_kv", QVariant.Double),
                     ("distance_m", QVariant.Double), ("situation", QVariant.String), ("alertes", QVariant.String),
                     ("ordre", QVariant.Int)):
            ch.append(QgsField(n, t))
        sink, resultats[self.SORTIE_OUVRAGES] = self.parameterAsSink(parameters, self.SORTIE_OUVRAGES, context, ch,
                                                                     ouvr.wkbType(), crs)
        for o in retenus:
            f = QgsFeature(ch)
            f.setGeometry(o["geom"])
            f.setAttributes([o[n] for n in ch.names()])
            sink.addFeature(f, QgsFeatureSink.FastInsert)

        ch = QgsFields()
        for n, t in (("exploitant", QVariant.String), ("categories", QVariant.String),
                     ("reseau_sensible", QVariant.Bool), ("nb_ouvrages", QVariant.Int),
                     ("distance_min_m", QVariant.Double), ("situation_la_plus_proche", QVariant.String),
                     ("ic_a_prevoir", QVariant.Bool), ("contact", QVariant.String),
                     ("telephone_urgence", QVariant.String)):
            ch.append(QgsField(n, t))
        sink, resultats[self.SORTIE_EXPLOITANTS] = self.parameterAsSink(parameters, self.SORTIE_EXPLOITANTS, context,
                                                                        ch, QgsWkbTypes.NoGeometry, crs)
        for e in expl:
            f = QgsFeature(ch)
            f.setAttributes([e[n] for n in ch.names()])
            sink.addFeature(f, QgsFeatureSink.FastInsert)

        ch = QgsFields()
        for n, t in (("controle", QVariant.String), ("resultat", QVariant.String), ("conforme", QVariant.Bool)):
            ch.append(QgsField(n, t))
        sink, resultats[self.SORTIE_CONTROLE] = self.parameterAsSink(parameters, self.SORTIE_CONTROLE, context, ch,
                                                                     QgsWkbTypes.NoGeometry, crs)
        for c in controles:
            f = QgsFeature(ch)
            f.setAttributes(list(c))
            sink.addFeature(f, QgsFeatureSink.FastInsert)
            if not c[2]:
                feedback.pushWarning(self.tr("Emprise non conforme : %s, %s") % (c[0], c[1]))

        feedback.pushInfo(self.tr("%d ouvrage(s) retenu(s), %d exploitant(s). Pré-analyse : la liste officielle "
                                  "vient du guichet unique.") % (len(retenus), len(expl)))
        return resultats
