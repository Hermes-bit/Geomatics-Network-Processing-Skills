# -*- coding: utf-8 -*-
"""
Dossier d'impact du chantier à partager : PDF (carte, synthèse, exploitants, registre des
risques, parcelles) et carte HTML interactive en un seul fichier.

Entrée : le GeoPackage écrit par scripts/chainer_postgis.py --gpkg (couches zone, risques,
exploitants, ouvrages, voies, vegetation, parcelles, synthese). Dans QGIS, l'algorithme
qgis/analyse_impact_chantier.py écrit directement le PDF et la carte : ce script n'est utile
que pour la version PostGIS. Le rendu est le même (le code du dossier est celui de l'algorithme).

Exemple (Linux, Python de QGIS), depuis le dossier du skill :
  python3 rapport/dossier_impact.py impact.gpkg --pdf dossier_impact.pdf --html carte_impact.html

Sous Windows : même commande dans l'« OSGeo4W Shell » avec python-qgis à la place de python3.
Testé avec QGIS 3.34.
"""

import argparse
import importlib.util
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def demarrer_qgis():
    from qgis.core import QgsApplication
    if QgsApplication.instance() is not None:
        return QgsApplication.instance()
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    globals()["_app"] = app
    return app


def charger_algorithme():
    spec = importlib.util.spec_from_file_location(
        "analyse_impact_chantier", os.path.join(ICI, "qgis", "analyse_impact_chantier.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def principal(arguments=None):
    ap = argparse.ArgumentParser(description="Dossier PDF et carte HTML de l'analyse d'impact d'un chantier")
    ap.add_argument("gpkg", help="GeoPackage écrit par scripts/chainer_postgis.py --gpkg")
    ap.add_argument("--pdf", help="dossier PDF à écrire")
    ap.add_argument("--html", help="carte HTML à écrire")
    ap.add_argument("--note", action="append", default=[], help="ligne d'hypothèses à ajouter (répétable)")
    a = ap.parse_args(arguments)
    if not a.pdf and not a.html:
        ap.error("indiquez --pdf et/ou --html")

    demarrer_qgis()
    from qgis.core import QgsVectorLayer
    m = charger_algorithme()

    def couche(nom):
        c = QgsVectorLayer("%s|layername=%s" % (a.gpkg, nom), nom, "ogr")
        if not c.isValid():
            raise SystemExit("Couche %s absente de %s" % (nom, a.gpkg))
        return c

    donnees = {n: m.lire_couche(couche(n)) for n in ("zone", "risques", "exploitants", "ouvrages", "voies",
                                                     "vegetation", "parcelles", "synthese")}
    synthese = donnees["synthese"][0]
    for cle in ("emprise_conforme", "urgent"):
        synthese[cle] = synthese[cle] in (True, 1, "1", "true", "t")
    for e in donnees["exploitants"]:
        for cle in ("reseau_sensible", "ic_a_prevoir"):
            if e[cle] is not None:
                e[cle] = e[cle] in (True, 1, "1", "true", "t")
    for r in donnees["risques"]:
        r["id"], r["niveau"] = int(r["id"]), int(r["niveau"])
    donnees["risques"].sort(key=lambda r: r["id"])

    from qgis.core import QgsCoordinateReferenceSystem
    crs = QgsCoordinateReferenceSystem("EPSG:2154")
    wkb = {"zone": "MultiPolygon", "parcelles": "MultiPolygon", "ouvrages": "Geometry", "voies": "LineString",
           "vegetation": "LineString", "risques": "Point"}
    couches = {n: m.memoire(n, m.CHAMPS[n], w, crs, donnees[n]) for n, w in wkb.items()}
    notes = a.note + ["Paramètres : voir la section 0 de scripts/impact_chantier.sql et des scripts DT-DICT et PK.",
                      m.notes_parametres(m.PARAMETRES, 5)[1]]
    if a.pdf:
        m.faire_pdf(a.pdf, synthese, couches, donnees["risques"], donnees["exploitants"], donnees["parcelles"], notes)
        print("Dossier PDF écrit :", a.pdf)
    if a.html:
        m.faire_html(a.html, synthese, couches, donnees["risques"], donnees["exploitants"], donnees["parcelles"], notes)
        print("Carte HTML écrite :", a.html)
    print("%d risque(s), %d exploitant(s) dans le dossier" % (len(donnees["risques"]), len(donnees["exploitants"])))


if __name__ == "__main__":
    principal()
