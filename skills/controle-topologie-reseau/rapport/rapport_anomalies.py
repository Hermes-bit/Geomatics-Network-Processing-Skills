# -*- coding: utf-8 -*-
"""
Rapport d'anomalies de topologie : PDF (carte + résumé + liste détaillée) et carte
HTML interactive à partager (un seul fichier, ouvrable dans n'importe quel navigateur).

Entrées : les couches d'anomalies produites par l'algorithme QGIS
(qgis/controle_topologie_reseau.py) ou exportées depuis PostGIS avec
rapport/exporter_anomalies_postgis.sh, et la couche du réseau pour le fond de carte.

Exemple (Linux, Python de QGIS), depuis le dossier du skill :
  python3 rapport/rapport_anomalies.py \
      --reseau "exemples/reseau_exemple.gpkg|layername=troncons" \
      --postes "exemples/reseau_exemple.gpkg|layername=postes" \
      --anomalies anomalies_points.gpkg --anomalies anomalies_lignes.gpkg \
      --titre "Contrôle de topologie - réseau HTA exemple" \
      --pdf rapport_anomalies.pdf --html carte_anomalies.html

Sous Windows : même commande dans l'« OSGeo4W Shell » avec python-qgis à la place de python3.
Testé avec QGIS 3.34.
"""

import argparse
import datetime
import html
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app = None


def demarrer_qgis():
    """Démarre QGIS sans interface, sauf si le script tourne déjà dans QGIS."""
    global _app
    from qgis.core import QgsApplication
    if QgsApplication.instance() is not None:
        return QgsApplication.instance()
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    _app = QgsApplication([], False)
    _app.initQgis()
    return _app

ORDRE = ["bloquante", "majeure", "mineure", "info"]
COULEURS = {"bloquante": "#7f0000", "majeure": "#d7301f", "mineure": "#f28e2b", "info": "#4e79a7"}
LIBELLES = {
    "boucle_fermee_radial": "Boucle fermée en exploitation radiale",
    "composante_isolee": "Partie de réseau non reliée à un poste source",
    "croisement_sans_noeud": "Croisement sans nœud",
    "doublon_geometrique": "Tronçon en double",
    "poste_isole": "Poste isolé",
    "quasi_connexion": "Quasi-connexion (extrémités non raccordées)",
    "attribut_incoherent": "Attribut hors des valeurs normalisées",
    "attribut_manquant": "Attribut manquant",
    "extremite_pendante": "Extrémité pendante",
    "tension_incoherente_noeud": "Changement de tension hors poste",
    "troncon_trop_court": "Tronçon trop court",
    "franchissement": "Franchissement (normal)",
    "troncon_multi_fusionne": "Tronçon en plusieurs morceaux fusionné",
    "troncon_discontinu": "Tronçon discontinu",
    "troncon_boucle_sur_lui_meme": "Tronçon bouclé sur lui-même",
    "geometrie_invalide": "Géométrie invalide",
    "geometrie_vide": "Géométrie vide",
    "scr_inattendu": "Système de coordonnées inattendu",
}


def charger(uri, nom):
    from qgis.core import QgsVectorLayer
    couche = QgsVectorLayer(uri, nom, "ogr")
    if not couche.isValid():
        raise SystemExit("Couche illisible : %s" % uri)
    return couche


def lire_anomalies(couches):
    """Liste de dicts (type, gravite, id_objet, detail, couche, fid), triés par gravité."""
    out = []
    for c in couches:
        noms = [f.name() for f in c.fields()]
        for f in c.getFeatures():
            a = {n: (None if f[n] is None or str(f[n]) == "NULL" else f[n])
                 for n in ("type", "gravite", "id_objet", "detail") if n in noms}
            a["couche"], a["geom"] = c, f.geometry()
            out.append(a)
    out.sort(key=lambda a: (ORDRE.index(a.get("gravite") or "info"), a.get("type") or "", str(a.get("id_objet"))))
    return out


def resume(anomalies):
    compte = {}
    for a in anomalies:
        cle = (a.get("gravite") or "info", a.get("type") or "?")
        compte[cle] = compte.get(cle, 0) + 1
    return sorted(compte.items(), key=lambda kv: (ORDRE.index(kv[0][0]), kv[0][1]))


def styler(couche):
    from qgis.core import (QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSymbol, QgsWkbTypes)
    from qgis.PyQt.QtGui import QColor
    cats = []
    for g in ORDRE:
        s = QgsSymbol.defaultSymbol(couche.geometryType())
        s.setColor(QColor(COULEURS[g]))
        if couche.geometryType() == QgsWkbTypes.PointGeometry:
            s.setSize(3.2 if g in ("bloquante", "majeure") else 2.4)
        else:
            s.setWidth(1.4 if g in ("bloquante", "majeure") else 0.9)
        cats.append(QgsRendererCategory(g, s, g))
    couche.setRenderer(QgsCategorizedSymbolRenderer("gravite", cats))


def styler_reseau(couche, postes=False):
    from qgis.core import QgsSingleSymbolRenderer, QgsSymbol
    from qgis.PyQt.QtGui import QColor
    s = QgsSymbol.defaultSymbol(couche.geometryType())
    if postes:
        s.setColor(QColor("#333333"))
        s.setSize(2.0)
    else:
        s.setColor(QColor("#9a9a9a"))
        s.setWidth(0.5)
    couche.setRenderer(QgsSingleSymbolRenderer(s))


def faire_pdf(chemin, titre, couches_fond, couches_anom, anomalies, notes):
    from qgis.core import (QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutItemMap,
                           QgsLayoutItemPage, QgsLayoutItemScaleBar, QgsLayoutPoint, QgsLayoutSize,
                           QgsPrintLayout, QgsProject, QgsRectangle, QgsUnitTypes, QgsLayoutItemHtml,
                           QgsLayoutFrame, QgsLayoutMultiFrame, QgsTextFormat)
    from qgis.PyQt.QtCore import QRectF
    from qgis.PyQt.QtGui import QFont

    projet = QgsProject.instance()
    for c in couches_fond + couches_anom:
        projet.addMapLayer(c)
    mise_en_page = QgsPrintLayout(projet)
    mise_en_page.initializeDefaults()          # A4 paysage
    mise_en_page.setName(titre)
    mm = QgsUnitTypes.LayoutMillimeters
    page = mise_en_page.pageCollection().page(0)
    page.setPageSize("A4", QgsLayoutItemPage.Landscape)

    def etiquette(texte, x, y, l, h, taille=10, gras=False):
        lab = QgsLayoutItemLabel(mise_en_page)
        lab.setText(texte)
        f = QFont("DejaVu Sans", taille)
        f.setBold(gras)
        if hasattr(lab, "setTextFormat"):          # QGIS >= 3.24
            fmt = QgsTextFormat.fromQFont(f)
            fmt.setSize(taille)
            lab.setTextFormat(fmt)
        else:
            lab.setFont(f)
        mise_en_page.addLayoutItem(lab)
        lab.attemptMove(QgsLayoutPoint(x, y, mm))
        lab.attemptResize(QgsLayoutSize(l, h, mm))
        return lab

    etiquette(titre, 10, 7, 277, 10, 16, True)
    etiquette("Rapport généré le %s" % datetime.date.today().strftime("%d/%m/%Y"), 10, 16, 180, 6, 9)

    carte = QgsLayoutItemMap(mise_en_page)
    carte.setRect(0, 0, 185, 170)
    carte.setLayers(couches_anom + couches_fond)
    etendue = QgsRectangle()
    for c in couches_fond + couches_anom:
        if c.featureCount():
            etendue.combineExtentWith(c.extent())
    etendue.scale(1.08)
    carte.setFrameEnabled(True)
    mise_en_page.addLayoutItem(carte)
    carte.attemptMove(QgsLayoutPoint(10, 24, mm))
    carte.attemptResize(QgsLayoutSize(185, 170, mm))
    carte.zoomToExtent(etendue)

    echelle = QgsLayoutItemScaleBar(mise_en_page)
    echelle.setStyle("Single Box")
    echelle.setLinkedMap(carte)
    echelle.applyDefaultSize()
    echelle.setUnits(QgsUnitTypes.DistanceMeters)
    echelle.setUnitLabel("m")
    mise_en_page.addLayoutItem(echelle)
    echelle.attemptMove(QgsLayoutPoint(12, 180, mm))

    # Résumé (colonne de droite) puis liste détaillée sur les pages suivantes, en HTML
    nb = {g: 0 for g in ORDRE}
    for a in anomalies:
        nb[a.get("gravite") or "info"] += 1
    lignes = "".join(
        "<tr><td style='color:%s;width:4mm'>&#9632;</td><td>%s <span style='color:#777'>(%s)</span></td>"
        "<td style='text-align:right'>%d</td></tr>"
        % (COULEURS[g], html.escape(LIBELLES.get(t, t)), g, n) for (g, t), n in resume(anomalies))
    css = ("<style>body{font-family:'DejaVu Sans',sans-serif;font-size:8pt;margin:0}"
           "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:2px 3px;"
           "vertical-align:top}th{text-align:left;background:#f0f0f0}h3{font-size:10pt;margin:0 0 4px}</style>")
    resume_html = (css + "<h3>Résumé</h3><p><b>%d</b> majeure(s) ou bloquante(s), <b>%d</b> mineure(s), "
                   "<b>%d</b> pour information.</p><table>%s</table>"
                   "<p><span style='color:#9a9a9a'>&#9644;</span> réseau &nbsp; "
                   "<span style='color:#333'>&#9679;</span> postes &nbsp; couleur = gravité</p>"
                   "<p style='color:#555'>%s</p>"
                   % (nb["bloquante"] + nb["majeure"], nb["mineure"], nb["info"], lignes,
                      "<br>".join(html.escape(n) for n in notes)))
    bloc = QgsLayoutItemHtml(mise_en_page)
    cadre = QgsLayoutFrame(mise_en_page, bloc)
    cadre.attemptSetSceneRect(QRectF(200, 24, 87, 172))
    bloc.addFrame(cadre)
    bloc.setContentMode(QgsLayoutItemHtml.ManualHtml)
    bloc.setHtml(resume_html)
    bloc.loadHtml()

    detail = (css + "<h3>Liste des anomalies</h3><table><tr><th>Gravité</th><th>Type</th><th>Objet</th>"
              "<th>Détail</th></tr>" + "".join(
                  "<tr><td style='white-space:nowrap;width:22mm'><span style='color:%s'>&#9632;</span> %s</td>"
                  "<td style='width:70mm'>%s</td><td style='width:35mm'>%s</td><td>%s</td></tr>"
                  % (COULEURS.get(a.get("gravite"), "#000"), a.get("gravite"),
                     html.escape(LIBELLES.get(a.get("type"), a.get("type") or "")),
                     html.escape(str(a.get("id_objet") or "")), html.escape(str(a.get("detail") or "")))
                  for a in anomalies) + "</table>")
    liste = QgsLayoutItemHtml(mise_en_page)
    liste.setContentMode(QgsLayoutItemHtml.ManualHtml)
    liste.setResizeMode(QgsLayoutMultiFrame.RepeatUntilFinished)
    page2 = QgsLayoutItemPage(mise_en_page)
    page2.setPageSize("A4", QgsLayoutItemPage.Landscape)
    mise_en_page.pageCollection().addPage(page2)
    y0 = mise_en_page.pageCollection().page(1).pos().y()
    cadre2 = QgsLayoutFrame(mise_en_page, liste)
    cadre2.attemptSetSceneRect(QRectF(10, y0 + 10, 277, 190))
    liste.addFrame(cadre2)
    liste.setHtml(detail)
    liste.loadHtml()

    exp = QgsLayoutExporter(mise_en_page)
    reglages = QgsLayoutExporter.PdfExportSettings()
    reglages.dpi = 200
    r = exp.exportToPdf(chemin, reglages)
    if r != QgsLayoutExporter.Success:
        raise SystemExit("Échec de l'export PDF (code %s)" % r)


def geojson(couche, champs, filtre=None):
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
    xf = QgsCoordinateTransform(couche.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
    feats = []
    for f in couche.getFeatures():
        g = f.geometry()
        if g.isNull() or g.isEmpty():
            continue
        g.transform(xf)
        props = {n: (None if f[n] is None or str(f[n]) == "NULL" else str(f[n])) for n in champs
                 if n in couche.fields().names()}
        feats.append({"type": "Feature", "properties": props, "geometry": json.loads(g.asJson(7))})
    return {"type": "FeatureCollection", "features": feats}


def faire_html(chemin, titre, reseau, postes, couches_anom, anomalies, notes):
    anom = {"type": "FeatureCollection", "features": []}
    for c in couches_anom:
        anom["features"].extend(geojson(c, ["type", "gravite", "id_objet", "detail"])["features"])
    for f in anom["features"]:
        f["properties"]["libelle"] = LIBELLES.get(f["properties"].get("type"), f["properties"].get("type"))
    fond = geojson(reseau, [n for n in reseau.fields().names()][:8])
    pts = geojson(postes, [n for n in postes.fields().names()][:6]) if postes else {"type": "FeatureCollection",
                                                                                    "features": []}
    lignes = "".join("<tr><td><span class='pastille' style='background:%s'></span>%s</td><td>%s</td>"
                     "<td class='n'>%d</td></tr>" % (COULEURS[g], g, html.escape(LIBELLES.get(t, t)), n)
                     for (g, t), n in resume(anomalies))
    modele = MODELE_HTML
    for cle, val in {
        "{{TITRE}}": html.escape(titre),
        "{{DATE}}": datetime.date.today().strftime("%d/%m/%Y"),
        "{{RESUME}}": lignes,
        "{{NOTES}}": "<br>".join(html.escape(n) for n in notes),
        "{{ANOMALIES}}": json.dumps(anom, ensure_ascii=False),
        "{{RESEAU}}": json.dumps(fond, ensure_ascii=False),
        "{{POSTES}}": json.dumps(pts, ensure_ascii=False),
        "{{COULEURS}}": json.dumps(COULEURS),
    }.items():
        modele = modele.replace(cle, val)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(modele)


MODELE_HTML = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITRE}}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 :root{--fond:#fff;--texte:#1d1d1f;--doux:#666;--bord:#ddd}
 @media (prefers-color-scheme: dark){:root{--fond:#1e1e1e;--texte:#eee;--doux:#aaa;--bord:#444}}
 html,body{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--fond);color:var(--texte)}
 #app{display:flex;height:100%}
 #panneau{width:340px;max-width:40%;overflow:auto;padding:16px;box-sizing:border-box;border-right:1px solid var(--bord)}
 #carte{flex:1}
 h1{font-size:18px;margin:0 0 4px} .date{color:var(--doux);font-size:12px;margin-bottom:12px}
 table{border-collapse:collapse;width:100%;font-size:13px} td{padding:4px 2px;border-bottom:1px solid var(--bord)} td:first-child{white-space:nowrap} #filtres{margin-bottom:10px}
 td.n{text-align:right;font-variant-numeric:tabular-nums}
 .pastille{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
 .notes{color:var(--doux);font-size:12px;margin-top:12px}
 label{display:block;font-size:13px;margin:2px 0}
 @media (max-width:700px){#app{flex-direction:column}#panneau{width:auto;max-width:none;max-height:40%;border-right:0;border-bottom:1px solid var(--bord)}}
</style></head><body><div id="app">
<div id="panneau"><h1>{{TITRE}}</h1><div class="date">Carte générée le {{DATE}}</div>
<div id="filtres"></div>
<table>{{RESUME}}</table><div class="notes">{{NOTES}}</div></div>
<div id="carte"></div></div>
<script>
const anomalies = {{ANOMALIES}}, reseau = {{RESEAU}}, postes = {{POSTES}}, couleurs = {{COULEURS}};
const carte = L.map('carte');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19,
  attribution: '&copy; contributeurs OpenStreetMap'}).addTo(carte);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fond = L.geoJSON(reseau, {style: {color: '#555', weight: 2, opacity: .7}}).addTo(carte);
L.geoJSON(postes, {pointToLayer: (f, ll) => L.circleMarker(ll, {radius: 4, color: '#222', fillOpacity: 1})}).addTo(carte);
const groupes = {};
for (const g of ['bloquante', 'majeure', 'mineure', 'info']) {
  groupes[g] = L.geoJSON({type: 'FeatureCollection', features: anomalies.features.filter(f => f.properties.gravite === g)}, {
    style: {color: couleurs[g], weight: g === 'info' ? 3 : 5, opacity: .9},
    pointToLayer: (f, ll) => L.circleMarker(ll, {radius: g === 'info' ? 5 : 7, color: '#fff', weight: 1.5, fillColor: couleurs[g], fillOpacity: 1}),
    onEachFeature: (f, l) => l.bindPopup('<b>' + esc(f.properties.libelle) + '</b><br>Gravité : ' + esc(f.properties.gravite) +
      '<br>Objet : ' + esc(f.properties.id_objet) + '<br>' + esc(f.properties.detail))
  }).addTo(carte);
  const n = groupes[g].getLayers().length;
  const lab = document.createElement('label');
  lab.innerHTML = '<input type="checkbox" checked> <span class="pastille" style="background:' + couleurs[g] + '"></span>' + g + ' (' + n + ')';
  lab.querySelector('input').onchange = e => e.target.checked ? groupes[g].addTo(carte) : carte.removeLayer(groupes[g]);
  document.getElementById('filtres').appendChild(lab);
}
const b = fond.getBounds();
for (const g in groupes) if (groupes[g].getLayers().length) b.extend(groupes[g].getBounds());
carte.fitBounds(b.isValid() ? b : [[46, 2], [47, 3]], {padding: [20, 20]});
</script></body></html>
"""


def main():
    p = argparse.ArgumentParser(description="Rapport PDF et carte HTML des anomalies de topologie")
    p.add_argument("--reseau", required=True, help="couche des tronçons (fond de carte)")
    p.add_argument("--postes", help="couche des postes (facultatif)")
    p.add_argument("--anomalies", action="append", required=True,
                   help="couche d'anomalies (répéter l'option pour les points et les lignes)")
    p.add_argument("--titre", default="Contrôle de topologie du réseau")
    p.add_argument("--note", action="append", default=[],
                   help="ligne d'hypothèses à afficher (tolérances, champs utilisés…), répétable")
    p.add_argument("--pdf", help="fichier PDF à écrire")
    p.add_argument("--html", help="carte HTML à écrire")
    a = p.parse_args()
    if not a.pdf and not a.html:
        p.error("indiquez --pdf et/ou --html")

    demarrer_qgis()
    reseau = charger(a.reseau, "Réseau")
    postes = charger(a.postes, "Postes") if a.postes else None
    couches = [charger(u, "Anomalies %d" % i) for i, u in enumerate(a.anomalies, start=1)]
    anomalies = lire_anomalies(couches)
    notes = a.note or ["Anomalies issues du contrôle de topologie. Les identifiants de nœuds dépendent "
                       "de l'ordre de calcul ; ceux des tronçons et postes sont stables."]
    if a.pdf:
        for c in couches:
            styler(c)
        styler_reseau(reseau)
        fond = [reseau] + ([postes] if postes else [])
        if postes:
            styler_reseau(postes, True)
        faire_pdf(a.pdf, a.titre, fond, couches, anomalies, notes)
        print("PDF écrit :", a.pdf)
    if a.html:
        faire_html(a.html, a.titre, reseau, postes, couches, anomalies, notes)
        print("Carte HTML écrite :", a.html)
    print("%d anomalie(s) dans le rapport" % len(anomalies))


if __name__ == "__main__":
    main()
