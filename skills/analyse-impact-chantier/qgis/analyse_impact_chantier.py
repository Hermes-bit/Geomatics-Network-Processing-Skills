# -*- coding: utf-8 -*-
"""
Analyse d'impact d'un chantier dans QGIS, sans PostGIS. Version PyQGIS de
scripts/impact_chantier.sql : mêmes règles, même registre des risques, même dossier.

L'algorithme enchaîne les algorithmes des autres skills du dépôt, qu'il faut avoir ajoutés à la
boîte à outils (Scripts > Géomatique des réseaux) :
  * Proximité DT-DICT (skills/proximite-dt-dict/qgis/proximite_dt_dict.py) : obligatoire ;
  * Référencement PK ferroviaire (skills/referencement-pk-ferroviaire/qgis/referencement_pk_ferroviaire.py) :
    si une voie ferrée est donnée.
La végétation vient du résultat du skill vegetation-lidar-hd (troncons_vegetation.geojson), qui
demande Python avec numpy et laspy et se lance à part.

Installation : boîte à outils Traitements > icône Python > « Ajouter un script à la boîte à
outils… », pour ce fichier et les deux autres. L'algorithme apparaît dans
Scripts > Géomatique des réseaux > Analyse d'impact d'un chantier.

Sorties : registre des risques (points), exploitants, ouvrages, section de voie, végétation,
parcelles, zone, et si demandé le dossier PDF et la carte HTML.
Testé avec QGIS 3.34. Les couches source ne sont jamais modifiées.
"""

import datetime
import html
import json
import re
from decimal import ROUND_HALF_UP, Decimal

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
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
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingUtils,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)

NIVEAUX = {1: "critique", 2: "majeur", 3: "à traiter", 4: "information"}
COULEURS = {1: "#a50f15", 2: "#e6550d", 3: "#f2b701", 4: "#4e79a7"}
THEMES = ["déclaration", "ferroviaire", "voisinage électrique", "réseaux", "végétation", "foncier"]
PARAMETRES = {
    "distance_voie_m": 20.0, "distance_min_moins_50kv": 3.0, "distance_min_50kv_plus": 5.0,
    "marge_engins_m": 5.0, "marge_vegetation_m": 20.0, "marge_riverains_m": 20.0, "surface_min_m2": 2.0,
}


# ----------------------------------------------------------------- utilitaires
def _arrondi(x, n=1):
    return float(Decimal(repr(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def _nb(x):
    """Nombre sans zéros inutiles : 63.0 -> '63', 0.3 -> '0.3'."""
    if x is None:
        return ""
    return ("%f" % x).rstrip("0").rstrip(".")


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


def pk_vers_m(pk):
    m = re.match(r"^(-?\d+)\+(\d{1,3}(?:[.,]\d+)?)$", str(pk).replace(" ", ""))
    if not m:
        raise ValueError('PK "%s" illisible' % pk)
    return int(m.group(1)) * 1000 + float(m.group(2).replace(",", "."))


def m_vers_pk(m):
    d = Decimal(repr(m)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    km = int(d // 1000)
    reste = d - km * 1000
    txt = "%d+%03d" % (km, int(reste))
    if reste - int(reste) != 0:
        txt += str((reste - int(reste)).normalize())[1:]
    return txt


def point_risque(g, zone):
    """Point qui situe un risque : dans l'emprise si l'objet la touche, sinon au plus près."""
    if g.intersects(zone):
        return g.intersection(zone).pointOnSurface()
    return g.nearestPoint(zone)


def lignes_simples(g):
    if g is None or g.isEmpty():
        return []
    if g.type() != QgsWkbTypes.LineGeometry:
        if g.wkbType() in (QgsWkbTypes.GeometryCollection,):
            return [p for x in g.asGeometryCollection() for p in lignes_simples(x)]
        return []
    return g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]


def trouver_algorithme(nom):
    for a in QgsApplication.processingRegistry().algorithms():
        if a.name() == nom:
            return a.id()
    return None


# ------------------------------------------------------------- règles métier
def risques_ouvrages(ouvrages, p):
    """Mêmes règles que les sections 3a, 3b et 3c de impact_chantier.sql."""
    out = []
    for o in ouvrages:
        cat, pose, tension = o["categorie"], o["pose"], o["tension_kv"]
        situation, dist = o["situation"], o["distance_m"]
        alertes = o["alertes"] or ""
        if pose != "aerien":
            sens = o["sensible"]
            if situation == "dans_emprise" and sens is not False:
                niveau = 1
            elif situation == "zone_incertitude" and sens is not False:
                niveau = 2
            elif situation in ("dans_emprise", "zone_incertitude"):
                niveau = 3
            else:
                niveau = 4
            desc = {"dans_emprise": "Traverse l'emprise",
                    "zone_incertitude": "À %s m de l'emprise, dans sa zone d'incertitude (%s m)" % (
                        _nb(dist), _nb(o["incertitude_m"]))}.get(situation, "À %s m de l'emprise" % _nb(dist))
            desc += {True: " ; réseau sensible", None: " ; sensibilité à vérifier"}.get(sens, "")
            desc += (" ; " + alertes) if alertes else ""
            mesures = []
            if "investigations complémentaires" in alertes:
                mesures.append("Investigations complémentaires ou mesures de localisation avant les travaux")
            if situation in ("dans_emprise", "zone_incertitude"):
                mesures.append("Marquage-piquetage ; techniques douces au droit de l'ouvrage et dans sa zone "
                               "d'incertitude")
            if situation == "proximite":
                mesures.append("Reporter l'ouvrage sur les plans d'exécution")
            out.append((niveau, "réseaux", "Ouvrage %s : %s %s, classe %s%s" % (
                o["id"], cat or "?", pose or "", o["classe"], (", %s kV" % _nb(tension)) if tension is not None else ""),
                o["exploitant"], desc, " ; ".join(mesures), "proximite-dt-dict", o["geom"]))
        elif cat == "electricite" or (cat == "ferroviaire" and tension is not None):
            dmin = p["distance_min_moins_50kv"] if tension is not None and tension < 50 else p["distance_min_50kv_plus"]
            niveau = 1 if dist <= dmin else 2 if dist <= dmin + p["marge_engins_m"] else 4
            out.append((niveau, "voisinage électrique", "Ouvrage %s : %s aérien%s" % (
                o["id"], cat, (", %s kV" % _nb(tension)) if tension is not None else ", tension inconnue"),
                o["exploitant"],
                ("Surplombe l'emprise" if dist == 0 else "À %s m de l'emprise en projection horizontale" % _nb(dist))
                + " ; distance minimale de sécurité %s m%s" % (
                    _nb(dmin), " (tension inconnue : 5 m retenus)" if tension is None else ""),
                "Travaux au voisinage : demander à l'exploitant la consignation ou des mesures de protection "
                "(balisage, gabarit, limitation de hauteur des engins) ; AIPR et habilitation des intervenants"
                if niveau < 4 else "Vérifier la hauteur des engins et leur débattement",
                "proximite-dt-dict", o["geom"]))
        else:
            out.append((3 if situation in ("dans_emprise", "fuseau_aerien") else 4, "réseaux",
                        "Ouvrage %s : %s aérien" % (o["id"], cat or "?"), o["exploitant"],
                        "À %s m de l'emprise en projection horizontale%s" % (_nb(dist), (" ; " + alertes) if alertes else ""),
                        "Vérifier la hauteur des engins", "proximite-dt-dict", o["geom"]))
    return out


def risque_voie(v, p):
    coupe = v["pk_emprise_debut"] is not None
    desc = ("L'emprise coupe la voie entre les PK %s et %s" % (v["pk_emprise_debut"], v["pk_emprise_fin"]) if coupe
            else "Travaux à %s m de la voie" % _nb(v["distance_min_m"]))
    desc += " ; %s m de voie à moins de %s m de l'emprise" % (_nb(v["longueur_m"]), _nb(p["distance_voie_m"]))
    desc += (" ; " + v["avertissement"]) if v["avertissement"] else ""
    mesure = ("Convention de travaux avec SNCF Réseau ; protection du chantier contre le risque ferroviaire "
              "(interruption temporaire de circulation ou limitation de vitesse) ; suivi topographique de la voie "
              "pendant un fonçage ou un forage" if coupe else
              "Consulter SNCF Réseau ; protection du personnel contre le risque ferroviaire ; engins hors du "
              "gabarit de la voie")
    return (1 if coupe else 2, "ferroviaire", "Ligne %s, PK %s à %s" % (v["code_ligne"], v["pk_debut"], v["pk_fin"]),
            "SNCF Réseau", desc, mesure, "referencement-pk-ferroviaire", v["geom"])


def risque_vegetation(v):
    pr = v["priorite"]
    if pr == "sans_donnees":
        desc = "Pas de données LiDAR HD sur ce tronçon : végétation non contrôlée"
    else:
        desc = "Végétation de %s m à %s m de l'axe (%s)" % (_nb(v["hauteur_max_m"]), _nb(v["distance_min_m"]),
                                                          "à traiter" if pr == "1_intervenir" else "à surveiller")
    desc += ", à %s m de l'emprise" % _nb(v["distance_emprise_m"])
    mesure = {"1_intervenir": "Élagage ou abattage avant le chantier, avec l'exploitant (risque de chute sur la ligne "
                              "ou la voie) ; ces travaux sont eux-mêmes soumis à DT-DICT",
              "2_surveiller": "Contrôler sur place avant les travaux"}.get(pr, "Visite de terrain pour la végétation")
    return ({"1_intervenir": 2, "2_surveiller": 3}.get(pr, 4), "végétation",
            "%s, tronçon %s %s" % (v["nom"] or v["id_ligne"], v["troncon"], v["cote"]), None, desc, mesure,
            "vegetation-lidar-hd", v["geom"])


def risque_parcelle(c):
    s = c["situation"]
    desc = {"occupee": "%s m² dans l'emprise" % _nb(c["surface_emprise_m2"]),
            "contact_negligeable": "Contact de %s m² seulement : probablement l'imprécision du cadastre"
                                   % _nb(c["surface_emprise_m2"])}.get(
        s, "Riveraine, à %s m de l'emprise" % _nb(c["distance_m"])) + " ; propriétaire : " + c["proprietaire"]
    pr = c["proprietaire"].upper()
    if s == "occupee":
        if "SNCF" in pr:
            mesure = "Autorisation d'occupation du domaine ferroviaire (SNCF Réseau)"
        elif pr.startswith("COMMUNE") or "DEPARTEMENT" in pr:
            mesure = "Permission de voirie ou convention d'occupation avec la collectivité"
        else:
            mesure = "Accord du propriétaire (convention d'occupation temporaire ou de servitude)"
    elif s == "contact_negligeable":
        mesure = "Vérifier la limite sur place ou sur le plan de bornage"
    else:
        mesure = "Information des riverains (accès, nuisances)"
    return (3 if s == "occupee" else 4, "foncier", "Parcelle %s %s (%s)" % (c["section"], c["numero"], c["commune"]),
            None, desc, mesure, "cadastre", c["geom"])


def numeroter(bruts, zone):
    """Registre final trié par niveau puis thème, un point par risque (comme la section 7 du SQL)."""
    ordre = sorted(range(len(bruts)), key=lambda i: (bruts[i][0], THEMES.index(bruts[i][1]), i))
    out = []
    for k, i in enumerate(ordre, start=1):
        n, theme, objet, expl, desc, mesure, source, g = bruts[i]
        out.append({"id": k, "niveau": n, "gravite": NIVEAUX[n], "theme": theme, "objet": objet, "exploitant": expl,
                    "description": desc, "mesure": mesure, "source": source, "geom": point_risque(g, zone)})
    return out


# --------------------------------------------------------------- algorithme
class AnalyseImpactChantier(QgsProcessingAlgorithm):
    EMPRISE, URGENT, NOM = "EMPRISE", "URGENT", "NOM_CHANTIER"
    OUVRAGES, EXPLOITANTS = "OUVRAGES", "EXPLOITANTS"
    AXES, CODE_LIGNE, VOIE, BORNES, SAUTS = "AXES", "CODE_LIGNE", "VOIE", "BORNES", "SAUTS"
    VEGETATION, PARCELLES, PROPRIETAIRES = "VEGETATION", "PARCELLES", "PROPRIETAIRES"
    MARGES = (("MARGE_PROXIMITE", "Marge de proximité DT-DICT (m)", 5.0),
              ("DISTANCE_VOIE", "Distance de travaux à proximité des voies (m)", 20.0),
              ("MARGE_ENGINS", "Débattement des engins ajouté aux distances de sécurité électriques (m)", 5.0),
              ("MARGE_VEGETATION", "Marge pour la végétation (m)", 20.0),
              ("MARGE_RIVERAINS", "Marge pour les parcelles riveraines (m)", 20.0))
    SORTIES = (("SORTIE_RISQUES", "Registre des risques", QgsProcessing.TypeVectorPoint),
               ("SORTIE_EXPLOITANTS", "Exploitants à consulter", QgsProcessing.TypeVector),
               ("SORTIE_OUVRAGES", "Ouvrages concernés", QgsProcessing.TypeVectorAnyGeometry),
               ("SORTIE_VOIES", "Section de voie concernée", QgsProcessing.TypeVectorLine),
               ("SORTIE_VEGETATION", "Végétation à traiter", QgsProcessing.TypeVectorLine),
               ("SORTIE_PARCELLES", "Parcelles occupées ou riveraines", QgsProcessing.TypeVectorPolygon),
               ("SORTIE_ZONE", "Zone de travaux", QgsProcessing.TypeVectorPolygon))
    PDF, HTML = "DOSSIER_PDF", "CARTE_HTML"

    def tr(self, texte):
        return QCoreApplication.translate("AnalyseImpactChantier", texte)

    def createInstance(self):
        return AnalyseImpactChantier()

    def name(self):
        return "analyse_impact_chantier"

    def displayName(self):
        return self.tr("Analyse d'impact d'un chantier")

    def group(self):
        return self.tr("Géomatique des réseaux")

    def groupId(self):
        return "geomatique_reseaux"

    def shortHelpString(self):
        return self.tr(
            "À partir d'une emprise de travaux, enchaîne la pré-analyse DT-DICT, le référencement PK de la voie "
            "ferrée, la végétation (résultat du skill LiDAR HD) et les parcelles cadastrales, puis rend un "
            "registre des risques (1 critique à 4 information), la liste des exploitants à consulter, et un "
            "dossier PDF et une carte HTML. Les algorithmes « Proximité DT-DICT » et « Référencement PK "
            "ferroviaire » doivent être dans la boîte à outils. Champs attendus : ceux des skills d'import "
            "(exploitant, categorie, pose, classe_precision, flexible, branchement, tension_kv ; code_ligne, voie, "
            "pk, pk_amont, pk_aval). Pré-analyse : ne remplace ni le guichet unique ni l'avis des exploitants.")

    def initAlgorithm(self, config=None):
        A = self.addParameter
        A(QgsProcessingParameterFeatureSource(self.EMPRISE, self.tr("Emprise des travaux"),
                                              [QgsProcessing.TypeVectorPolygon]))
        A(QgsProcessingParameterBoolean(self.URGENT, self.tr("Travaux urgents"), False))
        A(QgsProcessingParameterString(self.NOM, self.tr("Nom du chantier"), "Chantier"))
        A(QgsProcessingParameterFeatureSource(self.OUVRAGES, self.tr("Ouvrages (réseaux)"),
                                              [QgsProcessing.TypeVectorAnyGeometry]))
        A(QgsProcessingParameterFeatureSource(self.EXPLOITANTS, self.tr("Exploitants et contacts (facultatif)"),
                                              [QgsProcessing.TypeVector], optional=True))
        A(QgsProcessingParameterFeatureSource(self.AXES, self.tr("Axes des voies ferrées (facultatif)"),
                                              [QgsProcessing.TypeVectorLine], optional=True))
        A(QgsProcessingParameterString(self.CODE_LIGNE, self.tr("Code ligne (ex. 830000)"), optional=True))
        A(QgsProcessingParameterString(self.VOIE, self.tr("Voie (ex. V1)"), optional=True))
        A(QgsProcessingParameterFeatureSource(self.BORNES, self.tr("Bornes kilométriques"),
                                              [QgsProcessing.TypeVectorPoint], optional=True))
        A(QgsProcessingParameterFeatureSource(self.SAUTS, self.tr("Sauts de PK"),
                                              [QgsProcessing.TypeVectorPoint], optional=True))
        A(QgsProcessingParameterFeatureSource(self.VEGETATION,
                                              self.tr("Tronçons de végétation (skill vegetation-lidar-hd, facultatif)"),
                                              [QgsProcessing.TypeVectorLine], optional=True))
        A(QgsProcessingParameterFeatureSource(self.PARCELLES, self.tr("Parcelles cadastrales (facultatif)"),
                                              [QgsProcessing.TypeVectorPolygon], optional=True))
        A(QgsProcessingParameterFeatureSource(self.PROPRIETAIRES,
                                              self.tr("Propriétaires personnes morales : id_parcelle, proprietaire"),
                                              [QgsProcessing.TypeVector], optional=True))
        for nom, libelle, defaut in self.MARGES:
            A(QgsProcessingParameterNumber(nom, self.tr(libelle), QgsProcessingParameterNumber.Double, defaut,
                                           minValue=0))
        for nom, libelle, t in self.SORTIES:
            A(QgsProcessingParameterFeatureSink(nom, self.tr(libelle), t))
        A(QgsProcessingParameterFileDestination(self.PDF, self.tr("Dossier PDF"), "PDF (*.pdf)", optional=True,
                                                createByDefault=False))
        A(QgsProcessingParameterFileDestination(self.HTML, self.tr("Carte HTML"), "HTML (*.html)", optional=True,
                                                createByDefault=False))

    # ------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        import processing
        num = lambda n: self.parameterAsDouble(parameters, n, context)  # noqa: E731
        p = dict(PARAMETRES, distance_voie_m=num("DISTANCE_VOIE"), marge_engins_m=num("MARGE_ENGINS"),
                 marge_vegetation_m=num("MARGE_VEGETATION"), marge_riverains_m=num("MARGE_RIVERAINS"))
        crs = QgsCoordinateReferenceSystem("EPSG:2154")
        src_ouvr = self.parameterAsSource(parameters, self.OUVRAGES, context)
        if src_ouvr.sourceCrs().isGeographic():
            raise QgsProcessingException(self.tr("Couches en degrés : reprojetez-les en Lambert 93 (EPSG:2154)"))
        crs = src_ouvr.sourceCrs()

        # ---- 1. DT-DICT (algorithme du skill proximite-dt-dict)
        algo_dt = trouver_algorithme("proximite_dt_dict")
        if not algo_dt:
            raise QgsProcessingException(self.tr(
                "Algorithme « Proximité DT-DICT » introuvable : ajoutez skills/proximite-dt-dict/qgis/"
                "proximite_dt_dict.py à la boîte à outils"))
        feedback.pushInfo(self.tr("1. Pré-analyse DT-DICT (%s)") % algo_dt)
        r = processing.run(algo_dt, {
            "EMPRISE": parameters[self.EMPRISE], "URGENT": self.parameterAsBoolean(parameters, self.URGENT, context),
            "OUVRAGES": parameters[self.OUVRAGES], "EXPLOITANTS": parameters.get(self.EXPLOITANTS),
            "MARGE": num("MARGE_PROXIMITE"), "SORTIE_OUVRAGES": "TEMPORARY_OUTPUT",
            "SORTIE_EXPLOITANTS": "TEMPORARY_OUTPUT", "SORTIE_CONTROLE": "TEMPORARY_OUTPUT"},
            context=context, feedback=feedback, is_child_algorithm=True)
        couche = lambda k: QgsProcessingUtils.mapLayerFromString(r[k], context)  # noqa: E731
        c_ouvr, c_expl, c_ctrl = couche("SORTIE_OUVRAGES"), couche("SORTIE_EXPLOITANTS"), couche("SORTIE_CONTROLE")
        ouvrages = [dict({n: _val(f[n]) for n in c_ouvr.fields().names()}, geom=QgsGeometry(f.geometry()))
                    for f in c_ouvr.getFeatures()]
        exploitants = [{n: _val(f[n]) for n in c_expl.fields().names()} for f in c_expl.getFeatures()]
        controles = [{n: _val(f[n]) for n in c_ctrl.fields().names()} for f in c_ctrl.getFeatures()]

        emprise = self.parameterAsSource(parameters, self.EMPRISE, context)
        xf = QgsCoordinateTransform(emprise.sourceCrs(), crs, context.transformContext())
        geoms = []
        for f in emprise.getFeatures():
            g = QgsGeometry(f.geometry())
            if not g.isEmpty():
                g.transform(xf)
                geoms.append(g.makeValid())
        zone = QgsGeometry.unaryUnion(geoms)

        bruts = []
        for c in controles:
            if not c["conforme"] and c["controle"] != "géométrie valide":
                bruts.append((2, "déclaration", "Emprise : " + c["controle"], None, c["resultat"],
                              "Découper en plusieurs déclarations DT-DICT (arrêté du 15/02/2012, art. 4) ou revoir "
                              "l'emprise", "proximite-dt-dict", zone))
        bruts += risques_ouvrages(ouvrages, p)

        # ---- 2. Voie ferrée (algorithme du skill referencement-pk-ferroviaire)
        voies = []
        src_axes = self.parameterAsSource(parameters, self.AXES, context)
        if src_axes is not None:
            voies = self.voies(parameters, context, feedback, src_axes, zone, crs, p)
            bruts += [risque_voie(v, p) for v in voies]

        # ---- 3. Végétation
        vegetation = []
        src_veg = self.parameterAsSource(parameters, self.VEGETATION, context)
        if src_veg is not None:
            xv = QgsCoordinateTransform(src_veg.sourceCrs(), crs, context.transformContext())
            for f in src_veg.getFeatures():
                pr = _val(f["priorite"])
                g = QgsGeometry(f.geometry())
                g.transform(xv)
                if pr in ("1_intervenir", "2_surveiller", "sans_donnees") and g.distance(zone) <= p["marge_vegetation_m"]:
                    v = {n: _val(f[n]) for n in ("id_ligne", "type", "nom", "troncon", "cote", "hauteur_max_m",
                                                 "distance_min_m", "marge_chute_min_m", "priorite")}
                    v.update(distance_emprise_m=_arrondi(g.distance(zone), 1), geom=g)
                    vegetation.append(v)
            bruts += [risque_vegetation(v) for v in vegetation]
            feedback.pushInfo(self.tr("3. Végétation : %d tronçon(s) à traiter près du chantier") % len(vegetation))

        # ---- 4. Parcelles
        parcelles = []
        src_parc = self.parameterAsSource(parameters, self.PARCELLES, context)
        if src_parc is not None:
            proprietaires = {}
            src_prop = self.parameterAsSource(parameters, self.PROPRIETAIRES, context)
            if src_prop is not None:
                for f in src_prop.getFeatures(QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)):
                    proprietaires.setdefault(str(_val(f["id_parcelle"])), set()).add(_val(f["proprietaire"]))
            xp = QgsCoordinateTransform(src_parc.sourceCrs(), crs, context.transformContext())
            req = QgsFeatureRequest().setFilterRect(
                xp.transformBoundingBox(zone.boundingBox().buffered(p["marge_riverains_m"]),
                                        QgsCoordinateTransform.ReverseTransform))
            for f in src_parc.getFeatures(req):
                g = QgsGeometry(f.geometry())
                g.transform(xp)
                d = g.distance(zone)
                if d > p["marge_riverains_m"]:
                    continue
                inter = g.intersection(zone).area() if g.intersects(zone) else 0.0
                ident = str(_val(f["id"]))
                parcelles.append({
                    "id": ident, "commune": _val(f["commune"]), "section": _val(f["section"]),
                    "numero": _val(f["numero"]), "contenance": _val(f["contenance"]),
                    "surface_emprise_m2": _arrondi(inter, 1), "part_emprise_pct": _arrondi(100 * inter / g.area(), 2),
                    "distance_m": _arrondi(d, 1),
                    "situation": "occupee" if inter >= p["surface_min_m2"] else "contact_negligeable" if inter > 0
                    else "riveraine",
                    "proprietaire": ", ".join(sorted(proprietaires[ident])) if ident in proprietaires
                    else "non publié (personne physique ou non renseigné)", "geom": g})
            parcelles.sort(key=lambda c: c["id"])
            bruts += [risque_parcelle(c) for c in parcelles]
            feedback.pushInfo(self.tr("4. Parcelles : %d occupée(s) ou riveraine(s)") % len(parcelles))

        # ---- 5. Registre, exploitants, synthèse
        risques = numeroter(bruts, zone)
        for e in exploitants:
            e["niveau_max"] = min((x["niveau"] for x in risques if x["exploitant"] == e["exploitant"]), default=None)
        if voies and not any(e["exploitant"] == "SNCF Réseau" for e in exploitants):
            exploitants.append({"exploitant": "SNCF Réseau", "categories": "ferroviaire", "reseau_sensible": True,
                                "nb_ouvrages": 0, "distance_min_m": min(v["distance_min_m"] for v in voies),
                                "situation_la_plus_proche": "voie à proximité", "ic_a_prevoir": False,
                                "niveau_max": min(x["niveau"] for x in risques if x["theme"] == "ferroviaire"),
                                "contact": None, "telephone_urgence": None})
        synthese = faire_synthese(self.parameterAsString(parameters, self.NOM, context), zone, len(geoms),
                                  self.parameterAsBoolean(parameters, self.URGENT, context), risques, exploitants,
                                  controles, voies, parcelles, vegetation)
        for n, v in synthese.items():
            feedback.pushInfo("   %s : %s" % (n, v))

        res = {}
        ecrire = lambda nom, champs, wkb, objets: res.__setitem__(nom, ecrire_sink(  # noqa: E731
            self, parameters, context, nom, champs, wkb, crs, objets))
        ecrire("SORTIE_RISQUES", CHAMPS["risques"], QgsWkbTypes.Point, risques)
        ecrire("SORTIE_EXPLOITANTS", CHAMPS["exploitants"], QgsWkbTypes.NoGeometry, exploitants)
        ecrire("SORTIE_OUVRAGES", CHAMPS["ouvrages"], c_ouvr.wkbType(), ouvrages)
        ecrire("SORTIE_VOIES", CHAMPS["voies"], QgsWkbTypes.LineString, voies)
        ecrire("SORTIE_VEGETATION", CHAMPS["vegetation"], QgsWkbTypes.LineString, vegetation)
        ecrire("SORTIE_PARCELLES", CHAMPS["parcelles"], QgsWkbTypes.MultiPolygon, parcelles)
        ecrire("SORTIE_ZONE", CHAMPS["zone"], QgsWkbTypes.MultiPolygon,
               [{"surface_m2": synthese["surface_m2"], "geom": zone}])

        pdf = self.parameterAsFileOutput(parameters, self.PDF, context)
        carte = self.parameterAsFileOutput(parameters, self.HTML, context)
        if pdf or carte:
            couches = {n: memoire(n, CHAMPS[n], wkb, crs, objets) for n, wkb, objets in (
                ("zone", "MultiPolygon", [{"surface_m2": synthese["surface_m2"], "geom": zone}]),
                ("parcelles", "MultiPolygon", parcelles), ("ouvrages", "Geometry", ouvrages),
                ("voies", "LineString", voies), ("vegetation", "LineString", vegetation),
                ("risques", "Point", risques))}
            notes = notes_parametres(p, num("MARGE_PROXIMITE"))
            if pdf:
                faire_pdf(pdf, synthese, couches, risques, exploitants, parcelles, notes)
                res[self.PDF] = pdf
                feedback.pushInfo(self.tr("Dossier PDF écrit : %s") % pdf)
            if carte:
                faire_html(carte, synthese, couches, risques, exploitants, parcelles, notes)
                res[self.HTML] = carte
                feedback.pushInfo(self.tr("Carte HTML écrite : %s") % carte)
        return res

    # ------------------------------------------------------------------
    def voies(self, parameters, context, feedback, src_axes, zone, crs, p):
        import processing
        algo_pk = trouver_algorithme("referencement_pk_ferroviaire")
        if not algo_pk:
            raise QgsProcessingException(self.tr(
                "Algorithme « Référencement PK ferroviaire » introuvable : ajoutez skills/referencement-pk-ferroviaire/"
                "qgis/referencement_pk_ferroviaire.py à la boîte à outils"))
        code = self.parameterAsString(parameters, self.CODE_LIGNE, context).strip()
        voie = self.parameterAsString(parameters, self.VOIE, context).strip()
        xa = QgsCoordinateTransform(src_axes.sourceCrs(), crs, context.transformContext())
        parties = []
        for f in src_axes.getFeatures():
            if code and "code_ligne" in f.fields().names() and str(_val(f["code_ligne"])) != code:
                continue
            if voie and "voie" in f.fields().names() and str(_val(f["voie"])) != voie:
                continue
            g = QgsGeometry(f.geometry())
            g.transform(xa)
            parties += lignes_simples(g)
        if not parties:
            feedback.pushWarning(self.tr("Aucun axe pour la ligne %s %s : voie ignorée") % (code, voie))
            return []
        axe = QgsGeometry.fromMultiPolylineXY(parties).mergeLines()
        morceaux = lignes_simples(axe.intersection(zone.buffer(p["distance_voie_m"], 8)))
        if not morceaux:
            feedback.pushInfo(self.tr("2. Voie %s : à plus de %s m de l'emprise") % (code, _nb(p["distance_voie_m"])))
            return []
        # Points à localiser en PK : extrémités de chaque morceau et de sa partie dans l'emprise
        pts = QgsVectorLayer("Point?crs=%s&field=id:string" % crs.authid(), "points_pk", "memory")
        feats, dans = [], {}
        for i, m in enumerate(morceaux):
            for nom, xy in (("%d_debut" % i, m[0]), ("%d_fin" % i, m[-1])):
                f = QgsFeature(pts.fields())
                f.setAttributes([nom])
                f.setGeometry(QgsGeometry.fromPointXY(xy))
                feats.append(f)
            dans[i] = lignes_simples(QgsGeometry.fromPolylineXY(m).intersection(zone))
            for j, d in enumerate(dans[i]):
                for nom, xy in (("%d_e%d_debut" % (i, j), d[0]), ("%d_e%d_fin" % (i, j), d[-1])):
                    f = QgsFeature(pts.fields())
                    f.setAttributes([nom])
                    f.setGeometry(QgsGeometry.fromPointXY(xy))
                    feats.append(f)
        pts.dataProvider().addFeatures(feats)
        feedback.pushInfo(self.tr("2. Voie %s : PK de la section proche du chantier (%s)") % (code, algo_pk))
        r = processing.run(algo_pk, {
            "AXES": parameters[self.AXES], "CHAMP_LIGNE_AXE": "code_ligne", "CODE_LIGNE": code,
            "CHAMP_VOIE": "voie" if voie else None, "VOIE": voie,
            "BORNES": parameters[self.BORNES], "CHAMP_LIGNE_BORNE": "code_ligne", "CHAMP_PK_BORNE": "pk",
            "SAUTS": parameters.get(self.SAUTS), "CHAMP_LIGNE_SAUT": "code_ligne",
            "CHAMP_PK_AMONT": "pk_amont" if parameters.get(self.SAUTS) else None,
            "CHAMP_PK_AVAL": "pk_aval" if parameters.get(self.SAUTS) else None, "POINTS": pts,
            "SORTIE_PK_XY": "TEMPORARY_OUTPUT", "SORTIE_XY_PK": "TEMPORARY_OUTPUT",
            "SORTIE_EVENEMENTS": "TEMPORARY_OUTPUT", "SORTIE_CALAGE": "TEMPORARY_OUTPUT"},
            context=context, feedback=feedback, is_child_algorithm=True)
        loc = {f["id"]: pk_vers_m(f["pk"]) for f in
               QgsProcessingUtils.mapLayerFromString(r["SORTIE_XY_PK"], context).getFeatures() if _val(f["pk"])}
        calage = sorted(QgsProcessingUtils.mapLayerFromString(r["SORTIE_CALAGE"], context).getFeatures(),
                        key=lambda f: f["ordre"])
        lacunes = [(pk_vers_m(a["pk"]), pk_vers_m(b["pk"]), "%s = %s" % (a["pk"], b["pk"]))
                   for a, b in zip(calage, calage[1:])
                   if a["origine"] == "saut_amont" and b["origine"] == "saut_aval" and pk_vers_m(b["pk"]) > pk_vers_m(a["pk"])]
        voies = []
        for i, m in enumerate(morceaux):
            m0, m1 = loc["%d_debut" % i], loc["%d_fin" % i]
            if m1 < m0:
                m0, m1 = m1, m0
                m = list(reversed(m))
            g = QgsGeometry.fromPolylineXY(m)
            e0 = [loc["%d_e%d_debut" % (i, j)] for j in range(len(dans[i]))]
            e1 = [loc["%d_e%d_fin" % (i, j)] for j in range(len(dans[i]))]
            ext = e0 + e1
            lac = [l for l in lacunes if l[0] >= m0 and l[1] <= m1]
            voies.append({
                "code_ligne": code, "pk_debut": m_vers_pk(m0), "pk_fin": m_vers_pk(m1),
                "longueur_m": _arrondi(g.length(), 1), "ecart_pk_m": _arrondi(m1 - m0, 1),
                "distance_min_m": _arrondi(g.distance(zone), 2),
                "pk_emprise_debut": m_vers_pk(min(ext)) if ext else None,
                "pk_emprise_fin": m_vers_pk(max(ext)) if ext else None,
                "avertissement": ("Contient la lacune de PK %s : %d m sur le terrain pour %d m d'écart de PK" % (
                    ", ".join(l[2] for l in lac), int(_arrondi(g.length(), 0)), int(_arrondi(m1 - m0, 0)))) if lac else "",
                "geom": g})
        voies.sort(key=lambda v: pk_vers_m(v["pk_debut"]))
        return voies


def faire_synthese(nom, zone, nb_polygones, urgent, risques, exploitants, controles, voies, parcelles, vegetation):
    return {
        "nom_chantier": nom, "surface_m2": _arrondi(zone.area(), 1), "nb_polygones": nb_polygones, "urgent": urgent,
        "niveau_global": min((r["niveau"] for r in risques), default=None),
        "nb_critiques": sum(r["niveau"] == 1 for r in risques), "nb_majeurs": sum(r["niveau"] == 2 for r in risques),
        "nb_a_traiter": sum(r["niveau"] == 3 for r in risques), "nb_info": sum(r["niveau"] == 4 for r in risques),
        "nb_exploitants": len(exploitants),
        "nb_exploitants_sensibles": sum(bool(e["reseau_sensible"]) for e in exploitants),
        "emprise_conforme": all(c["conforme"] for c in controles),
        "voies": ", ".join("%s PK %s à %s" % (v["code_ligne"], v["pk_debut"], v["pk_fin"]) for v in voies) or None,
        "nb_parcelles_occupees": sum(c["situation"] == "occupee" for c in parcelles),
        "nb_parcelles_riveraines": sum(c["situation"] != "occupee" for c in parcelles),
        "nb_troncons_vegetation": sum(v["priorite"] == "1_intervenir" for v in vegetation)}


def notes_parametres(p, marge_dtdict):
    return ["Marge DT-DICT %s m ; voies : %s m ; distances de sécurité électriques %s m (< 50 kV) et %s m "
            "(≥ 50 kV), plus %s m de débattement des engins ; végétation et riverains : %s m et %s m."
            % (_nb(marge_dtdict), _nb(p["distance_voie_m"]), _nb(p["distance_min_moins_50kv"]),
               _nb(p["distance_min_50kv_plus"]), _nb(p["marge_engins_m"]), _nb(p["marge_vegetation_m"]),
               _nb(p["marge_riverains_m"])),
            "Pré-analyse : la liste officielle des exploitants vient du guichet unique "
            "(reseaux-et-canalisations.ineris.fr) ; seules les couches fournies sont analysées. Les seuils sont des "
            "valeurs de départ à confirmer avec les exploitants et le gestionnaire de la voie."]


# ------------------------------------------------------------ couches
S, D, I, B = QVariant.String, QVariant.Double, QVariant.Int, QVariant.Bool
CHAMPS = {
    "risques": [("id", I), ("niveau", I), ("gravite", S), ("theme", S), ("objet", S), ("exploitant", S),
                ("description", S), ("mesure", S), ("source", S)],
    "exploitants": [("exploitant", S), ("categories", S), ("reseau_sensible", B), ("nb_ouvrages", I),
                    ("distance_min_m", D), ("situation_la_plus_proche", S), ("ic_a_prevoir", B), ("niveau_max", I),
                    ("contact", S), ("telephone_urgence", S)],
    "ouvrages": [("id", S), ("exploitant", S), ("categorie", S), ("sensible", B), ("pose", S), ("classe", S),
                 ("incertitude_m", D), ("tension_kv", D), ("distance_m", D), ("situation", S), ("alertes", S),
                 ("ordre", I)],
    "voies": [("code_ligne", S), ("pk_debut", S), ("pk_fin", S), ("longueur_m", D), ("ecart_pk_m", D),
              ("distance_min_m", D), ("pk_emprise_debut", S), ("pk_emprise_fin", S), ("avertissement", S)],
    "vegetation": [("id_ligne", S), ("type", S), ("nom", S), ("troncon", I), ("cote", S), ("hauteur_max_m", D),
                   ("distance_min_m", D), ("marge_chute_min_m", D), ("priorite", S), ("distance_emprise_m", D)],
    "parcelles": [("id", S), ("commune", S), ("section", S), ("numero", S), ("contenance", D),
                  ("surface_emprise_m2", D), ("part_emprise_pct", D), ("distance_m", D), ("situation", S),
                  ("proprietaire", S)],
    "zone": [("surface_m2", D)],
}


def _champs(defs):
    ch = QgsFields()
    for n, t in defs:
        ch.append(QgsField(n, t))
    return ch


def _entite(ch, defs, o):
    f = QgsFeature(ch)
    f.setAttributes([o.get(n) for n, _ in defs])
    if o.get("geom") is not None:
        g = QgsGeometry(o["geom"])
        f.setGeometry(g)
    return f


def ecrire_sink(algo, parameters, context, nom, defs, wkb, crs, objets):
    ch = _champs(defs)
    sink, dest = algo.parameterAsSink(parameters, nom, context, ch, wkb, crs)
    for o in objets:
        f = _entite(ch, defs, o)
        if f.hasGeometry() and QgsWkbTypes.isMultiType(wkb):
            g = f.geometry()
            g.convertToMultiType()
            f.setGeometry(g)
        sink.addFeature(f, QgsFeatureSink.FastInsert)
    return dest


def memoire(nom, defs, wkb, crs, objets):
    """Couche en mémoire pour la carte du dossier. wkb « Geometry » : type déduit des objets."""
    if wkb == "Geometry":
        types = {o["geom"].type() for o in objets if o.get("geom") is not None and not o["geom"].isEmpty()}
        wkb = ("MultiPoint" if types == {QgsWkbTypes.PointGeometry} else
               "MultiPolygon" if types == {QgsWkbTypes.PolygonGeometry} else "MultiLineString")
    c = QgsVectorLayer("%s?crs=%s" % (wkb, crs.authid()), nom, "memory")
    c.dataProvider().addAttributes(_champs(defs).toList())
    c.updateFields()
    entites = []
    for o in objets:
        f = _entite(c.fields(), defs, o)
        if f.hasGeometry() and wkb.startswith("Multi"):
            g = f.geometry()
            g.convertToMultiType()
            f.setGeometry(g)
        entites.append(f)
    c.dataProvider().addFeatures(entites)
    c.updateExtents()
    return c


def lire_couche(c):
    """Couche -> liste de dicts (pour le dossier construit depuis un GeoPackage)."""
    noms = c.fields().names()
    return [dict({n: _val(f[n]) for n in noms}, geom=QgsGeometry(f.geometry()) if f.hasGeometry() else None)
            for f in c.getFeatures()]


# ------------------------------------------------------------- dossier
def _styler(couches):
    from qgis.core import (QgsCategorizedSymbolRenderer, QgsPalLayerSettings, QgsRendererCategory,
                           QgsSingleSymbolRenderer, QgsSymbol, QgsTextFormat, QgsVectorLayerSimpleLabeling,
                           QgsTextBufferSettings)
    from qgis.PyQt.QtGui import QColor, QFont

    def simple(c, couleur, largeur=None, remplissage=None, taille=None):
        s = QgsSymbol.defaultSymbol(c.geometryType())
        s.setColor(QColor(couleur))
        if remplissage is not None:
            s.symbolLayer(0).setFillColor(QColor(remplissage))
            s.symbolLayer(0).setStrokeColor(QColor(couleur))
            s.symbolLayer(0).setStrokeWidth(largeur or 0.4)
        elif largeur is not None:
            s.setWidth(largeur)
        if taille is not None:
            s.setSize(taille)
        c.setRenderer(QgsSingleSymbolRenderer(s))

    for n, libelle in (("zone", "Emprise"), ("parcelles", "Parcelles"), ("voies", "Voie ferrée (section concernée)"),
                       ("vegetation", "Végétation"), ("ouvrages", "Réseaux"), ("risques", "Risques (n° du registre)")):
        couches[n].setName(libelle)
    simple(couches["zone"], "#d7301f", 0.6, "#40d7301f")
    simple(couches["parcelles"], "#8c8c8c", 0.25, "#00ffffff")
    simple(couches["voies"], "#222222", 1.2)
    cats = []
    for prio, coul in (("1_intervenir", "#2b8c3e"), ("2_surveiller", "#9acd32"), ("sans_donnees", "#bbbbbb")):
        s = QgsSymbol.defaultSymbol(couches["vegetation"].geometryType())
        s.setColor(QColor(coul))
        s.setWidth(2.2)
        cats.append(QgsRendererCategory(prio, s, prio))
    couches["vegetation"].setRenderer(QgsCategorizedSymbolRenderer("priorite", cats))
    simple(couches["ouvrages"], "#1f78b4", 0.5, None)
    cats = []
    for n, coul in COULEURS.items():
        s = QgsSymbol.defaultSymbol(couches["risques"].geometryType())
        s.setColor(QColor(coul))
        s.setSize(3.6 if n <= 2 else 2.8)
        cats.append(QgsRendererCategory(n, s, NIVEAUX[n]))
    couches["risques"].setRenderer(QgsCategorizedSymbolRenderer("niveau", cats))
    reglage = QgsPalLayerSettings()
    reglage.fieldName = "id"
    fmt = QgsTextFormat()
    fmt.setFont(QFont("DejaVu Sans"))
    fmt.setSize(7)
    tampon = QgsTextBufferSettings()
    tampon.setEnabled(True)
    tampon.setSize(0.8)
    fmt.setBuffer(tampon)
    reglage.setFormat(fmt)
    couches["risques"].setLabeling(QgsVectorLayerSimpleLabeling(reglage))
    couches["risques"].setLabelsEnabled(True)
    reglage = QgsPalLayerSettings()
    reglage.fieldName = "section || ' ' || numero"
    reglage.isExpression = True
    fmt = QgsTextFormat()
    fmt.setFont(QFont("DejaVu Sans"))
    fmt.setSize(6)
    fmt.setColor(QColor("#777777"))
    reglage.setFormat(fmt)
    couches["parcelles"].setLabeling(QgsVectorLayerSimpleLabeling(reglage))
    couches["parcelles"].setLabelsEnabled(True)


def _tableau(entetes, lignes, largeurs=None):
    largeurs = largeurs or [None] * len(entetes)
    return ("<table><tr>%s</tr>%s</table>" % ("".join(
        "<th%s>%s</th>" % (" style='width:%d%%'" % l if l else "", html.escape(e)) for e, l in zip(entetes, largeurs)), "".join(
        "<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in l) for l in lignes)))


def _e(v):
    return html.escape("" if v is None else str(v))


def _oui(v):
    return {True: "oui", False: "non"}.get(v, "?")


def contenu_dossier(synthese, risques, exploitants, parcelles, notes):
    """Blocs HTML communs au PDF et à la carte : synthèse, exploitants, risques, parcelles."""
    ng = synthese.get("niveau_global")
    resume = ("<p class='global' style='border-color:%s'>Niveau global : <b style='color:%s'>%s</b></p>"
              "<p><b>%s</b> critique(s), <b>%s</b> majeur(s), <b>%s</b> à traiter, <b>%s</b> pour information.</p>"
              "<p>Emprise : %s m² en %s polygone(s)%s ; %s.</p><p>Exploitants à consulter : <b>%s</b> (%s de réseaux "
              "sensibles).</p><p>Voie ferrée : %s.</p><p>Parcelles : %s occupée(s), %s riveraine(s) ou à vérifier."
              "</p><p>Végétation à traiter avant travaux : %s tronçon(s).</p>"
              % (COULEURS.get(ng, "#777"), COULEURS.get(ng, "#777"), NIVEAUX.get(ng, "aucun risque").upper(),
                 synthese["nb_critiques"], synthese["nb_majeurs"], synthese["nb_a_traiter"], synthese["nb_info"],
                 _nb(synthese["surface_m2"]), synthese["nb_polygones"], ", travaux urgents" if synthese.get("urgent") else "",
                 "conforme pour une seule déclaration" if synthese["emprise_conforme"]
                 else "<b>non conforme pour une seule déclaration</b>",
                 synthese["nb_exploitants"], synthese["nb_exploitants_sensibles"], _e(synthese["voies"] or "aucune"),
                 synthese["nb_parcelles_occupees"], synthese["nb_parcelles_riveraines"],
                 synthese["nb_troncons_vegetation"]))
    expl = _tableau(["Exploitant", "Réseaux", "Sensible", "Ouvrages", "Distance min.", "Situation", "IC", "Niveau",
                     "Contact"], [
        [_e(e["exploitant"]), _e(e["categories"]), _oui(e["reseau_sensible"]), _e(e["nb_ouvrages"]),
         _e(_nb(e["distance_min_m"])) + " m", _e(e["situation_la_plus_proche"]), _oui(e["ic_a_prevoir"]),
         "<span style='color:%s'>&#9632;</span> %s" % (COULEURS.get(e["niveau_max"], "#777"),
                                                      NIVEAUX.get(e["niveau_max"], "")),
         _e(" ; ".join(x for x in (e.get("contact"), e.get("telephone_urgence")) if x))] for e in exploitants])
    risq = _tableau(["N°", "Niveau", "Thème", "Objet", "Constat", "Mesure"], [
        ["<b>%d</b>" % r["id"], "<span style='color:%s'>&#9632;</span> %s" % (COULEURS[r["niveau"]], r["gravite"]),
         _e(r["theme"]), _e(r["objet"]) + ("<br><i>%s</i>" % _e(r["exploitant"]) if r.get("exploitant") else ""),
         _e(r["description"]), _e(r["mesure"])] for r in risques], [3, 9, 9, 20, 30, 29])
    parc = _tableau(["Parcelle", "Commune", "Situation", "Surface dans l'emprise", "Distance", "Propriétaire"], [
        [_e("%s %s" % (c["section"], c["numero"])), _e(c["commune"]), _e(c["situation"].replace("_", " ")),
         _e(_nb(c["surface_emprise_m2"])) + " m²", _e(_nb(c["distance_m"])) + " m", _e(c["proprietaire"])]
        for c in parcelles]) if parcelles else "<p>Aucune parcelle fournie.</p>"
    hyp = "".join("<p class='note'>%s</p>" % _e(n) for n in notes)
    return resume, expl, risq, parc, hyp


CSS = ("<style>body{font-family:'DejaVu Sans',sans-serif;font-size:7.5pt;margin:0}"
       "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:2px 3px;"
       "vertical-align:top;text-align:left}th{background:#f0f0f0}h3{font-size:10pt;margin:8px 0 4px}"
       "p{margin:3px 0}.global{border-left:4px solid;padding-left:6px;font-size:10pt}.note{color:#555}</style>")


def faire_pdf(chemin, synthese, couches, risques, exploitants, parcelles, notes):
    from qgis.core import (QgsLayoutExporter, QgsLayoutFrame, QgsLayoutItemHtml, QgsLayoutItemLabel,
                           QgsLayoutItemLegend, QgsLayoutItemMap, QgsLegendStyle, QgsLayoutItemPage, QgsLayoutItemScaleBar,
                           QgsLayoutMultiFrame, QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout, QgsRectangle,
                           QgsTextFormat, QgsUnitTypes)
    from qgis.PyQt.QtCore import QRectF
    from qgis.PyQt.QtGui import QFont

    _styler(couches)
    projet = QgsProject.instance()
    ordre = ["risques", "vegetation", "voies", "ouvrages", "zone", "parcelles"]
    for n in ordre:
        projet.addMapLayer(couches[n], False)
    mp = QgsPrintLayout(projet)
    mp.initializeDefaults()
    mm = QgsUnitTypes.LayoutMillimeters
    mp.pageCollection().page(0).setPageSize("A4", QgsLayoutItemPage.Landscape)

    def etiquette(texte, x, y, l, h, taille, gras=False):
        lab = QgsLayoutItemLabel(mp)
        lab.setText(texte)
        f = QFont("DejaVu Sans", taille)
        f.setBold(gras)
        if hasattr(lab, "setTextFormat"):
            fmt = QgsTextFormat.fromQFont(f)
            fmt.setSize(taille)
            lab.setTextFormat(fmt)
        else:
            lab.setFont(f)
        mp.addLayoutItem(lab)
        lab.attemptMove(QgsLayoutPoint(x, y, mm))
        lab.attemptResize(QgsLayoutSize(l, h, mm))

    etiquette("Analyse d'impact du chantier", 10, 5, 277, 8, 14, True)
    etiquette(synthese["nom_chantier"], 10, 12, 277, 7, 11)
    etiquette("Dossier généré le %s. Pré-analyse à faire valider : ne remplace ni le guichet unique ni l'avis "
              "des exploitants." % datetime.date.today().strftime("%d/%m/%Y"), 10, 18, 277, 5, 8)

    carte = QgsLayoutItemMap(mp)
    carte.setRect(0, 0, 175, 145)
    carte.setLayers([couches[n] for n in ordre])
    etendue = QgsRectangle(couches["zone"].extent())
    etendue.combineExtentWith(couches["risques"].extent())
    etendue.scale(1.15)
    carte.setFrameEnabled(True)
    mp.addLayoutItem(carte)
    carte.attemptMove(QgsLayoutPoint(10, 25, mm))
    carte.attemptResize(QgsLayoutSize(175, 145, mm))
    carte.zoomToExtent(etendue)
    echelle = QgsLayoutItemScaleBar(mp)
    echelle.setStyle("Single Box")
    echelle.setLinkedMap(carte)
    echelle.applyDefaultSize()
    echelle.setUnits(QgsUnitTypes.DistanceMeters)
    echelle.setUnitLabel("m")
    mp.addLayoutItem(echelle)
    echelle.attemptMove(QgsLayoutPoint(10, 174, mm))
    legende = QgsLayoutItemLegend(mp)
    legende.setLinkedMap(carte)
    legende.setTitle("")
    legende.setAutoUpdateModel(False)
    racine = legende.model().rootGroup()
    racine.clear()
    for n in ordre:
        racine.addLayer(couches[n])
    legende.setColumnCount(4)
    legende.setSymbolHeight(2.5)
    legende.setSymbolWidth(5)
    for style, taille in ((QgsLegendStyle.Subgroup, 7), (QgsLegendStyle.SymbolLabel, 6.5)):
        police = QFont("DejaVu Sans", int(taille))
        police.setBold(style == QgsLegendStyle.Subgroup)
        fmt = QgsTextFormat.fromQFont(police)
        fmt.setSize(taille)
        legende.rstyle(style).setTextFormat(fmt)
    mp.addLayoutItem(legende)
    legende.attemptMove(QgsLayoutPoint(55, 172, mm))

    resume, expl, risq, parc, hyp = contenu_dossier(synthese, risques, exploitants, parcelles, notes)
    bloc = QgsLayoutItemHtml(mp)
    cadre = QgsLayoutFrame(mp, bloc)
    cadre.attemptSetSceneRect(QRectF(192, 25, 95, 175))
    bloc.addFrame(cadre)
    bloc.setContentMode(QgsLayoutItemHtml.ManualHtml)
    bloc.setHtml(CSS + "<h3>Synthèse</h3>" + resume + hyp)
    bloc.loadHtml()

    liste = QgsLayoutItemHtml(mp)
    liste.setContentMode(QgsLayoutItemHtml.ManualHtml)
    liste.setResizeMode(QgsLayoutMultiFrame.RepeatUntilFinished)
    page2 = QgsLayoutItemPage(mp)
    page2.setPageSize("A4", QgsLayoutItemPage.Landscape)
    mp.pageCollection().addPage(page2)
    y0 = mp.pageCollection().page(1).pos().y()
    cadre2 = QgsLayoutFrame(mp, liste)
    cadre2.attemptSetSceneRect(QRectF(10, y0 + 10, 277, 190))
    liste.addFrame(cadre2)
    liste.setHtml(CSS + "<h3>Exploitants à consulter</h3>" + expl + "<h3>Registre des risques</h3>" + risq +
                  "<h3>Parcelles occupées ou riveraines</h3>" + parc)
    liste.loadHtml()

    exp = QgsLayoutExporter(mp)
    reglages = QgsLayoutExporter.PdfExportSettings()
    reglages.dpi = 200
    if exp.exportToPdf(chemin, reglages) != QgsLayoutExporter.Success:
        raise QgsProcessingException("Échec de l'export PDF : %s" % chemin)
    for n in ordre:
        projet.takeMapLayer(couches[n])


def _geojson(couche):
    xf = QgsCoordinateTransform(couche.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
    feats = []
    for f in couche.getFeatures():
        g = QgsGeometry(f.geometry())
        if g.isNull() or g.isEmpty():
            continue
        g.transform(xf)
        props = {n: (None if _val(f[n]) is None else _val(f[n])) for n in couche.fields().names()}
        feats.append({"type": "Feature", "properties": props, "geometry": json.loads(g.asJson(7))})
    return {"type": "FeatureCollection", "features": feats}


def faire_html(chemin, synthese, couches, risques, exploitants, parcelles, notes):
    resume, expl, risq, parc, hyp = contenu_dossier(synthese, risques, exploitants, parcelles, notes)
    donnees = {n: _geojson(couches[n]) for n in ("zone", "parcelles", "ouvrages", "voies", "vegetation", "risques")}
    page = MODELE_HTML
    for cle, val in {"{{TITRE}}": html.escape(synthese["nom_chantier"]),
                     "{{DATE}}": datetime.date.today().strftime("%d/%m/%Y"),
                     "{{RESUME}}": resume, "{{EXPLOITANTS}}": expl, "{{RISQUES}}": risq, "{{PARCELLES}}": parc,
                     "{{NOTES}}": hyp, "{{DONNEES}}": json.dumps(donnees, ensure_ascii=False, default=str),
                     "{{COULEURS}}": json.dumps(COULEURS)}.items():
        page = page.replace(cle, val)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(page)


MODELE_HTML = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Impact du chantier : {{TITRE}}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 :root{--fond:#fff;--texte:#1d1d1f;--doux:#666;--bord:#ddd;--entete:#f3f3f3}
 @media (prefers-color-scheme: dark){:root{--fond:#1e1e1e;--texte:#eee;--doux:#aaa;--bord:#444;--entete:#2a2a2a}}
 html,body{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--fond);color:var(--texte)}
 #app{display:flex;height:100%}
 #panneau{width:460px;max-width:45%;overflow-y:auto;overflow-x:hidden;padding:16px;box-sizing:border-box;border-right:1px solid var(--bord);font-size:13px}
 #carte{flex:1}
 h1{font-size:18px;margin:0 0 4px} h3{font-size:15px;margin:18px 0 6px} .date{color:var(--doux);font-size:12px}
 p{margin:4px 0} .global{border-left:4px solid;padding-left:8px;font-size:15px} .note{color:var(--doux);font-size:12px}
 table{border-collapse:collapse;width:100%;font-size:12px} td,th{padding:4px 3px;border-bottom:1px solid var(--bord);vertical-align:top;text-align:left}
 th{background:var(--entete)} #risques tr{cursor:pointer} #risques tr:hover td{background:var(--entete)}
 .onglets button{font:inherit;padding:4px 10px;margin:0 4px 6px 0;border:1px solid var(--bord);background:var(--fond);color:var(--texte);border-radius:4px;cursor:pointer}
 .onglets button.actif{background:var(--texte);color:var(--fond)} .vue{display:none;overflow-x:auto} .vue.actif{display:block}
 #risques tr:first-child{display:none} #risques tr{display:grid;grid-template-columns:30px 1fr;border-bottom:1px solid var(--bord);padding:6px 0}
 #risques td{border:0;padding:1px 3px} #risques td:first-child{grid-row:span 5;font-size:14px} #risques td:nth-child(3){color:var(--doux)}
 #risques td:nth-child(4){font-weight:600} #risques td:nth-child(6){font-style:italic;color:var(--doux)}
 @media (max-width:760px){#app{flex-direction:column}#panneau{width:auto;max-width:none;max-height:50%;border-right:0;border-bottom:1px solid var(--bord)}}
</style></head><body><div id="app">
<div id="panneau"><h1>{{TITRE}}</h1><div class="date">Analyse d'impact générée le {{DATE}}</div>
<h3>Synthèse</h3>{{RESUME}}
<div class="onglets"><button data-v="risques" class="actif">Risques</button><button data-v="exploitants">Exploitants</button><button data-v="parcelles">Parcelles</button></div>
<div id="risques" class="vue actif">{{RISQUES}}</div><div id="exploitants" class="vue">{{EXPLOITANTS}}</div>
<div id="parcelles" class="vue">{{PARCELLES}}</div>{{NOTES}}</div>
<div id="carte"></div></div>
<script>
const D = {{DONNEES}}, C = {{COULEURS}};
const carte = L.map('carte');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 20, attribution: '&copy; contributeurs OpenStreetMap'}).addTo(carte);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fiche = p => Object.entries(p).filter(([k, v]) => v !== null && v !== '').map(([k, v]) => '<b>' + esc(k) + '</b> : ' + esc(v)).join('<br>');
const couches = {
  'Parcelles': L.geoJSON(D.parcelles, {style: f => ({color: '#888', weight: 1, fillOpacity: f.properties.situation === 'occupee' ? .12 : 0}), onEachFeature: (f, l) => l.bindPopup(fiche(f.properties))}),
  'Emprise': L.geoJSON(D.zone, {style: {color: '#d7301f', weight: 2, fillOpacity: .25}}),
  'Ouvrages': L.geoJSON(D.ouvrages, {style: {color: '#1f78b4', weight: 3}, pointToLayer: (f, ll) => L.circleMarker(ll, {radius: 4}), onEachFeature: (f, l) => l.bindPopup(fiche(f.properties))}),
  'Voie ferrée': L.geoJSON(D.voies, {style: {color: '#222', weight: 5, dashArray: '8 4'}, onEachFeature: (f, l) => l.bindPopup(fiche(f.properties))}),
  'Végétation': L.geoJSON(D.vegetation, {style: f => ({color: {'1_intervenir': '#2b8c3e', '2_surveiller': '#9acd32'}[f.properties.priorite] || '#aaa', weight: 7, opacity: .8}), onEachFeature: (f, l) => l.bindPopup(fiche(f.properties))}),
};
const marques = {};
couches['Risques'] = L.geoJSON(D.risques, {
  pointToLayer: (f, ll) => L.marker(ll, {icon: L.divIcon({className: '', iconSize: [22, 22], html: '<div style="width:22px;height:22px;border-radius:50%;background:' + C[f.properties.niveau] + ';color:#fff;font:bold 11px/22px system-ui;text-align:center;border:2px solid #fff;box-shadow:0 0 2px #000">' + f.properties.id + '</div>'})}),
  onEachFeature: (f, l) => { marques[f.properties.id] = l; l.bindPopup('<b>' + f.properties.id + '. ' + esc(f.properties.objet) + '</b><br>' + esc(f.properties.gravite) + ' : ' + esc(f.properties.description) + '<br><i>' + esc(f.properties.mesure) + '</i>'); }
});
for (const c of Object.values(couches)) c.addTo(carte);
L.control.layers(null, couches, {collapsed: true}).addTo(carte);
carte.fitBounds(couches['Emprise'].getBounds().pad(0.4));
document.querySelectorAll('#risques tr').forEach((tr, i) => { if (i) tr.onclick = () => { const m = marques[i]; if (m) { carte.setView(m.getLatLng(), 19); m.openPopup(); } }; });
document.querySelectorAll('.onglets button').forEach(b => b.onclick = () => {
  document.querySelectorAll('.onglets button, .vue').forEach(x => x.classList.remove('actif'));
  b.classList.add('actif'); document.getElementById(b.dataset.v).classList.add('actif'); });
</script></body></html>
"""
