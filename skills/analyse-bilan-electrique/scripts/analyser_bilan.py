#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contrôle et analyse d'un bilan électrique au pas de temps fin (15 ou 30 minutes),
par exemple le « bilan électrique demi-heure » publié par Enedis en open data.

Python 3.8 ou plus, bibliothèque standard uniquement (aucune installation).

Usage :
  python3 analyser_bilan.py bilan.csv --sortie dossier_resultats [--unite auto|W|kW|MW]

Produit dans le dossier de sortie :
  controles.csv                 anomalies de qualité (pas manquants, doublons, bilan déséquilibré…)
  indicateurs_journaliers.csv   énergies, pointes, creux, parts de production, pertes, température
  rapport.html                  rapport lisible avec les courbes (un seul fichier, sans dépendance)
et affiche un résumé. Le fichier source n'est jamais modifié.
"""

import argparse
import csv
import html
import io
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

# Colonnes connues du bilan Enedis (en minuscules). Toutes sont facultatives sauf l'horodate.
COL_HORODATE = ("horodate", "date_heure", "date - heure", "datetime", "date")
COL = {
    "injection_rte": "Injection depuis RTE",
    "soutirage_rte": "Soutirage vers RTE",
    "soutirage_vers_autres_grd": "Soutirage vers d'autres GRD",
    "pertes": "Pertes",
    "consommation_totale": "Consommation totale",
    "production_totale": "Production totale",
    "production_photovoltaique": "Photovoltaïque",
    "production_eolien": "Éolien",
    "production_cogeneration": "Cogénération",
    "production_autre": "Autre production",
    "temperature_reelle_lissee": "Température réelle lissée (°C)",
    "temperature_normale_lissee": "Température normale lissée (°C)",
}
DETAIL_CONSO = ("consommation_telerelevee_hta", "consommation_telerelevee_btsup",
                "consommation_telerelevee_professionnelle", "consommation_telerelevee_residentielle",
                "consommation_profilee_ent_hta", "consommation_profilee_ent_bt",
                "consommation_profilee_pro", "consommation_profilee_res")
DETAIL_PROD = ("production_telerelevee", "production_profilee")
NON_PUISSANCE = ("mois", "temperature", "pseudo_rayonnement")
FACTEUR = {"W": 1e-6, "kW": 1e-3, "MW": 1.0}          # vers MW


# ------------------------------------------------------------------ lecture
def lire(chemin):
    with open(chemin, "rb") as f:
        brut = f.read()
    texte = brut.decode("utf-8-sig") if not brut.startswith(b"\xff\xfe") else brut.decode("utf-16")
    try:
        dialecte = csv.Sniffer().sniff(texte[:5000], delimiters=",;\t")
    except csv.Error:
        dialecte = csv.excel
    lignes = list(csv.reader(io.StringIO(texte), dialecte))
    entete = [c.strip().lower() for c in lignes[0]]
    return entete, lignes[1:], dialecte.delimiter


def nombre(s):
    s = (s or "").strip().replace(" ", "").replace(" ", "")
    if s == "" or s.lower() in ("null", "nan", "nd", "n/a"):
        return None
    if s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def horodate(s):
    s = s.strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                d = datetime.strptime(s, fmt)
                break
            except ValueError:
                d = None
        if d is None:
            raise ValueError("horodate illisible : %r" % s)
    return d


def heure_paris(d_utc):
    """Heure légale française (règle européenne : dernier dimanche de mars / d'octobre à 1 h UTC)."""
    def dernier_dimanche(annee, mois):
        d = datetime(annee, mois, 31 if mois in (3, 10) else 30, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    ete = dernier_dimanche(d_utc.year, 3) <= d_utc < dernier_dimanche(d_utc.year, 10)
    return (d_utc + timedelta(hours=2 if ete else 1)).replace(tzinfo=timezone(timedelta(hours=2 if ete else 1)))


# ---------------------------------------------------------------- analyse
def analyser(chemin, unite="auto", tolerance_bilan=0.001):
    entete, lignes, sep = lire(chemin)
    i_h = next((entete.index(c) for c in COL_HORODATE if c in entete), None)
    if i_h is None:
        raise SystemExit("Aucune colonne d'horodate trouvée (attendu : %s)" % ", ".join(COL_HORODATE))
    controles = []

    def ctrl(type_, gravite, detail, debut="", fin=""):
        controles.append({"type": type_, "gravite": gravite, "detail": detail, "debut": debut, "fin": fin})

    colonnes_puissance = [c for i, c in enumerate(entete) if i != i_h and not any(c.startswith(n) for n in NON_PUISSANCE)]
    donnees = {}            # horodate UTC -> {colonne: valeur}
    vues = Counter()
    naives = 0
    for n, l in enumerate(lignes, start=2):
        if not l or not "".join(l).strip():
            continue
        try:
            d = horodate(l[i_h])
        except ValueError as e:
            ctrl("horodate_illisible", "majeure", "ligne %d : %s" % (n, e))
            continue
        if d.tzinfo is None:
            naives += 1
            d = d.replace(tzinfo=timezone(timedelta(hours=1)))
        d = d.astimezone(timezone.utc)
        vues[d] += 1
        donnees[d] = {c: nombre(l[i]) if i < len(l) else None for i, c in enumerate(entete) if i != i_h}
    if naives:
        ctrl("horodate_sans_fuseau", "majeure",
             "%d horodates sans décalage horaire : lues en UTC+1, résultats faux autour des changements d'heure" % naives)
    if not donnees:
        raise SystemExit("Aucune ligne exploitable")

    ts = sorted(donnees)
    ecarts = Counter((b - a) for a, b in zip(ts, ts[1:]))
    pas = ecarts.most_common(1)[0][0] if ecarts else timedelta(minutes=30)
    pas_h = pas.total_seconds() / 3600

    # Doublons
    for d, n in sorted(vues.items()):
        if n > 1:
            ctrl("horodate_en_double", "majeure", "%d lignes pour la même horodate (dernière gardée)" % n,
                 heure_paris(d).isoformat())

    # Pas manquants, regroupés en périodes
    manquants = []
    attendu = ts[0]
    while attendu <= ts[-1]:
        if attendu not in donnees:
            manquants.append(attendu)
        attendu += pas
    periodes = []
    for d in manquants:
        if periodes and d - periodes[-1][1] == pas:
            periodes[-1][1] = d
        else:
            periodes.append([d, d])
    for a, b in periodes:
        n = int((b - a) / pas) + 1
        ctrl("pas_manquants", "majeure" if n * pas_h >= 1 else "mineure",
             "%d pas de %d min manquants (%s)" % (n, pas.total_seconds() // 60, duree(n * pas_h)),
             heure_paris(a).isoformat(), heure_paris(b).isoformat())
    decales = [d for d in ts if (d - ts[0]) % pas]
    if decales:
        ctrl("pas_irregulier", "majeure", "%d horodates hors de la grille de %d min" % (len(decales), pas.total_seconds() // 60),
             heure_paris(decales[0]).isoformat())

    # Unité
    conso = [v["consommation_totale"] for v in donnees.values() if v.get("consommation_totale") is not None]
    reference = conso or [abs(x) for v in donnees.values() for c, x in v.items() if c in colonnes_puissance and x is not None]
    med = statistics.median(reference) if reference else 0
    if unite == "auto":
        unite = "W" if med > 1e6 else ("kW" if med > 1e3 * 50 else "MW")
        ctrl("unite_supposee", "info",
             "Unité supposée : %s (médiane de la consommation %.3g). À confirmer dans la documentation du jeu de données."
             % (unite, med))
    k = FACTEUR[unite]

    # Valeurs vides et négatives
    for c in colonnes_puissance:
        vides = [d for d in ts if donnees[d].get(c) is None]
        if vides:
            ctrl("valeur_manquante", "mineure", "%s : %d valeur(s) vide(s)" % (c, len(vides)),
                 heure_paris(vides[0]).isoformat(), heure_paris(vides[-1]).isoformat())
        negatifs = [d for d in ts if (donnees[d].get(c) or 0) < 0]
        if negatifs and c not in ("soutirage_rte",):
            ctrl("valeur_negative", "mineure", "%s : %d valeur(s) négative(s)" % (c, len(negatifs)),
                 heure_paris(negatifs[0]).isoformat(), heure_paris(negatifs[-1]).isoformat())

    # Colonnes nulles sur toute la période (souvent une donnée non renseignée codée 0)
    for c in entete:
        if c == entete[i_h] or c == "mois":
            continue
        vals = [donnees[d].get(c) for d in ts if donnees[d].get(c) is not None]
        if vals and all(v == 0 for v in vals):
            ctrl("colonne_nulle", "mineure", "%s vaut 0 sur toute la période : donnée probablement non renseignée, "
                 "à ne pas interpréter" % c)

    # Équilibre du bilan : injection RTE + production = soutirage RTE + autres GRD + pertes + consommation
    termes = ("injection_rte", "production_totale", "soutirage_rte", "soutirage_vers_autres_grd", "pertes",
              "consommation_totale")
    if all(t in entete for t in termes):
        hors = []
        for d in ts:
            v = donnees[d]
            if any(v.get(t) is None for t in termes):
                continue
            e = (v["injection_rte"] + v["production_totale"] - v["soutirage_rte"] - v["soutirage_vers_autres_grd"]
                 - v["pertes"] - v["consommation_totale"])
            if abs(e) > tolerance_bilan * max(abs(v["consommation_totale"]), 1):
                hors.append((d, e))
        if hors:
            ctrl("bilan_desequilibre", "majeure",
                 "%d pas où injection + production ≠ soutirages + pertes + consommation (écart max %.1f MW)"
                 % (len(hors), max(abs(e) for _, e in hors) * k),
                 heure_paris(hors[0][0]).isoformat(), heure_paris(hors[-1][0]).isoformat())
        else:
            ctrl("bilan_equilibre", "info", "Bilan équilibré à chaque pas (tolérance %g %%)" % (tolerance_bilan * 100))
    for total, details in (("consommation_totale", DETAIL_CONSO), ("production_totale", DETAIL_PROD)):
        if total in entete and all(c in entete for c in details):
            hors = [d for d in ts if donnees[d].get(total) is not None and all(donnees[d].get(c) is not None for c in details)
                    and abs(sum(donnees[d][c] for c in details) - donnees[d][total])
                    > tolerance_bilan * max(abs(donnees[d][total]), 1)]
            if hors:
                ctrl("sous_totaux_incoherents", "mineure",
                     "%s ≠ somme du détail sur %d pas" % (total, len(hors)), heure_paris(hors[0]).isoformat())

    # Indicateurs journaliers (jour civil en heure légale)
    pas_par_jour = defaultdict(list)
    for d in ts:
        pas_par_jour[heure_paris(d).date()].append(d)
    jours = []
    j0, j1 = min(pas_par_jour), max(pas_par_jour)
    for n in range((j1 - j0).days + 1):
        pas_par_jour.setdefault(j0 + timedelta(days=n), [])
    for j in sorted(pas_par_jour):
        attendus = _pas_attendus(j, pas)
        dd = pas_par_jour[j]
        ligne = {"date": j.isoformat(), "nb_pas": len(dd), "nb_pas_attendus": attendus,
                 "complet": "oui" if len(dd) >= attendus else "non"}

        def energie(c):
            vals = [donnees[d].get(c) for d in dd]
            return None if not vals or any(x is None for x in vals) else sum(vals) * k * pas_h

        def extr(c, f):
            vals = [(donnees[d][c], d) for d in dd if donnees[d].get(c) is not None]
            if not vals:
                return None, None
            v, d = f(vals)
            return v * k, heure_paris(d).strftime("%H:%M")

        for c, nom in (("consommation_totale", "conso"), ("production_totale", "production"),
                       ("production_photovoltaique", "photovoltaique"), ("production_eolien", "eolien"),
                       ("pertes", "pertes"), ("injection_rte", "injection_rte")):
            if c in entete:
                ligne["energie_%s_mwh" % nom] = arrondi(energie(c), 0)
        if "consommation_totale" in entete:
            p, h = extr("consommation_totale", max)
            ligne["pointe_conso_mw"], ligne["heure_pointe"] = arrondi(p, 0), h
            p, h = extr("consommation_totale", min)
            ligne["creux_conso_mw"], ligne["heure_creux"] = arrondi(p, 0), h
        ec, ep = ligne.get("energie_conso_mwh"), ligne.get("energie_production_mwh")
        if ec and ep is not None:
            ligne["part_production_locale_pct"] = arrondi(100 * ep / ec, 1)
        if ec and ligne.get("energie_pertes_mwh") is not None:
            entrees = (ligne.get("energie_injection_rte_mwh") or 0) + (ep or 0)
            ligne["taux_pertes_pct"] = arrondi(100 * ligne["energie_pertes_mwh"] / entrees, 2) if entrees else None
        if "temperature_reelle_lissee" in entete:
            t = [donnees[d]["temperature_reelle_lissee"] for d in dd if donnees[d].get("temperature_reelle_lissee") is not None]
            ligne["temperature_moyenne"] = arrondi(statistics.mean(t), 1) if t else None
        if "temperature_normale_lissee" in entete:
            t = [donnees[d]["temperature_normale_lissee"] for d in dd if donnees[d].get("temperature_normale_lissee") is not None]
            ligne["temperature_normale"] = arrondi(statistics.mean(t), 1) if t else None
        jours.append(ligne)
        if not dd:
            ligne["complet"] = "absent"
        elif ligne["complet"] == "non":
            ctrl("jour_incomplet", "mineure", "%s : %d pas sur %d attendus, énergies du jour sous-estimées"
                 % (j.isoformat(), len(dd), attendus), j.isoformat())

    # Thermosensibilité : consommation journalière moyenne en fonction de la température
    thermo = None
    complets = [j for j in jours if j["complet"] == "oui" and j.get("temperature_moyenne") is not None
                and j.get("energie_conso_mwh") is not None]
    if len(complets) >= 3:
        x = [j["temperature_moyenne"] for j in complets]
        y = [j["energie_conso_mwh"] / 24 for j in complets]          # puissance moyenne, MW
        if max(x) - min(x) > 0:
            mx, my = statistics.mean(x), statistics.mean(y)
            pente = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sum((a - mx) ** 2 for a in x)
            ss = sum((b - (my + pente * (a - mx))) ** 2 for a, b in zip(x, y))
            st = sum((b - my) ** 2 for b in y)
            thermo = {"pente_mw_par_degre": arrondi(pente, 0), "r2": arrondi(1 - ss / st if st else 0, 2),
                      "nb_jours": len(complets), "plage_temperature": [min(x), max(x)]}
            fiable = len(complets) >= 14 and max(x) - min(x) >= 5 and thermo["r2"] >= 0.5
            ctrl("thermosensibilite", "info",
                 "%+.0f MW par °C (R² %.2f, %d jours complets, %.1f à %.1f °C)%s"
                 % (pente, thermo["r2"], len(complets), min(x), max(x),
                    "" if fiable else " : pas de lien exploitable (il faut au moins 14 jours complets, 5 °C d'écart et un R² ≥ 0,5 ; "
                                      "l'effet jour ouvré / week-end n'est pas séparé)"))

    serie = [(heure_paris(d), {c: (donnees[d].get(c) * k if donnees[d].get(c) is not None and c in colonnes_puissance
                                   else donnees[d].get(c)) for c in donnees[d]}) for d in ts]
    return {"fichier": os.path.basename(chemin), "separateur": sep, "pas_min": int(pas.total_seconds() // 60),
            "unite": unite, "debut": heure_paris(ts[0]), "fin": heure_paris(ts[-1]), "nb_pas": len(ts),
            "nb_manquants": len(manquants), "periodes_manquantes": [(heure_paris(a), heure_paris(b)) for a, b in periodes],
            "controles": controles, "jours": jours, "thermo": thermo, "serie": serie, "colonnes": entete}


def _pas_attendus(jour, pas):
    """Nombre de pas d'un jour civil en heure légale (92 / 96 / 100 au pas de 15 min selon le changement d'heure)."""
    n = 0
    d = datetime(jour.year, jour.month, jour.day, tzinfo=timezone.utc) - timedelta(hours=3)
    fin = d + timedelta(hours=30)
    while d < fin:
        if heure_paris(d).date() == jour:
            n += 1
        d += pas
    return n


def arrondi(v, n):
    return None if v is None else (round(v, n) if n else int(round(v)))


def duree(h):
    if h >= 24 and abs(h / 24 - round(h / 24)) < 1e-9:
        return "%d jour%s" % (round(h / 24), "s" if h >= 48 else "")
    return ("%.2f h" % h).replace(".00", "")


# ----------------------------------------------------------------- sorties
def ecrire_csv(chemin, lignes, champs):
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=champs, extrasaction="ignore")
        w.writeheader()
        for l in lignes:
            w.writerow(l)


def svg_courbes(r, largeur=960, hauteur=320):
    series = [(c, lib, coul) for c, lib, coul in (
        ("consommation_totale", "Consommation", "#1f77b4"), ("production_totale", "Production locale", "#2ca02c"),
        ("production_eolien", "Éolien", "#17becf"), ("production_photovoltaique", "Photovoltaïque", "#ff9f1c"),
        ("injection_rte", "Injection RTE", "#7f7f7f")) if c in r["colonnes"]]
    pts = r["serie"]
    if not pts or not series:
        return ""
    t0, t1 = pts[0][0].timestamp(), pts[-1][0].timestamp()
    vmax = max((v[c] for _, v in pts for c, _, _ in series if v.get(c) is not None), default=1)
    g, d, h, b = 56, 12, 12, 34
    X = lambda t: g + (t - t0) / ((t1 - t0) or 1) * (largeur - g - d)           # noqa: E731
    Y = lambda v: hauteur - b - v / vmax * (hauteur - h - b)                   # noqa: E731
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Courbes de puissance">' % (largeur, hauteur)]
    for a, z in r["periodes_manquantes"]:
        out.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="#d62728" opacity=".12"><title>Données manquantes</title></rect>'
                   % (X(a.timestamp()), h, max(X(z.timestamp()) - X(a.timestamp()), 2), hauteur - h - b))
    pas_y = 10 ** math.floor(math.log10(vmax)) if vmax > 0 else 1
    pas_y = pas_y * (2 if vmax / pas_y < 4 else 5 if vmax / pas_y > 8 else 1)
    y = 0
    while y <= vmax:
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="grille"/><text x="%d" y="%.1f" class="axe" text-anchor="end">%s</text>'
                   % (g, largeur - d, Y(y), Y(y), g - 6, Y(y) + 4, "{:,.0f}".format(y).replace(",", " ")))
        y += pas_y
    jour = pts[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
    while jour.timestamp() <= t1:
        if jour.timestamp() >= t0:
            out.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" class="grille"/><text x="%.1f" y="%d" class="axe">%s</text>'
                       % (X(jour.timestamp()), X(jour.timestamp()), h, hauteur - b, X(jour.timestamp()) + 3, hauteur - b + 16,
                          jour.strftime("%d/%m")))
        jour = (jour + timedelta(hours=26)).replace(hour=0)
    for c, lib, coul in series:
        chemin, levee = [], True
        prec = None
        for t, v in pts:
            if v.get(c) is None or (prec and (t - prec).total_seconds() > r["pas_min"] * 60 * 1.5):
                levee = True
            if v.get(c) is not None:
                chemin.append(("M" if levee else "L") + "%.1f,%.1f" % (X(t.timestamp()), Y(v[c])))
                levee = False
            prec = t
        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.6"><title>%s</title></path>'
                   % (" ".join(chemin), coul, html.escape(lib)))
    out.append("</svg>")
    legende = " ".join('<span class="leg"><i style="background:%s"></i>%s</span>' % (coul, html.escape(lib))
                       for _, lib, coul in series)
    return "\n".join(out) + '<div class="legende">%s <span class="leg"><i style="background:#d62728;opacity:.3"></i>Données manquantes</span> · puissances en MW</div>' % legende


def rapport_html(r, chemin):
    nb = Counter(c["gravite"] for c in r["controles"])
    lignes_ctrl = "".join(
        "<tr><td><span class='g %s'>%s</span></td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (c["gravite"], c["gravite"], html.escape(c["type"]), html.escape(c["detail"]),
           html.escape(" → ".join(x for x in (c["debut"][:16].replace("T", " "), c["fin"][:16].replace("T", " ")) if x)))
        for c in sorted(r["controles"], key=lambda c: ["majeure", "mineure", "info"].index(c["gravite"])))
    cols = [("date", "Jour"), ("nb_pas", "Pas"), ("energie_conso_mwh", "Conso (MWh)"),
            ("energie_production_mwh", "Production (MWh)"), ("part_production_locale_pct", "Prod. locale (%)"),
            ("pointe_conso_mw", "Pointe (MW)"), ("heure_pointe", "à"), ("creux_conso_mw", "Creux (MW)"),
            ("taux_pertes_pct", "Pertes (%)"), ("temperature_moyenne", "T moy. (°C)")]
    cols = [c for c in cols if any(c[0] in j for j in r["jours"])]
    tab = "<tr>%s</tr>" % "".join("<th>%s</th>" % l for _, l in cols) + "".join(
        "<tr class='%s'>%s</tr>" % ("" if j["complet"] == "oui" else "incomplet",
                                    "".join("<td>%s</td>" % fmt(j.get(c)) for c, _ in cols)) for j in r["jours"])
    page = MODELE.format(
        titre=html.escape("Bilan électrique : %s" % r["fichier"]),
        periode="%s → %s, pas de %d min, %d pas lus, unité source %s" % (
            r["debut"].strftime("%d/%m/%Y %H:%M"), r["fin"].strftime("%d/%m/%Y %H:%M"), r["pas_min"], r["nb_pas"], r["unite"]),
        majeures=nb["majeure"], mineures=nb["mineure"], infos=nb["info"],
        courbes=svg_courbes(r), controles=lignes_ctrl, jours=tab)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(page)


def fmt(v):
    if v is None:
        return "–"
    if isinstance(v, float) and v.is_integer() is False:
        return ("%.2f" % v).rstrip("0").rstrip(".").replace(".", ",")
    if isinstance(v, (int, float)):
        return "{:,}".format(int(v)).replace(",", " ")
    return html.escape(str(v))


MODELE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{titre}</title><style>
:root{{--fond:#fff;--texte:#1d1d1f;--doux:#666;--bord:#ddd;--grille:#eee}}
@media (prefers-color-scheme:dark){{:root{{--fond:#1b1b1d;--texte:#eee;--doux:#aaa;--bord:#444;--grille:#333}}}}
body{{margin:0;padding:16px;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--fond);color:var(--texte)}}
main{{max-width:1000px;margin:auto}} h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:24px 0 8px}}
.doux{{color:var(--doux);font-size:13px}} svg{{width:100%;height:auto}} .grille{{stroke:var(--grille)}}
.axe{{fill:var(--doux);font-size:11px}} .legende{{font-size:12px;color:var(--doux)}}
.leg{{margin-right:12px;white-space:nowrap}} .leg i{{display:inline-block;width:12px;height:3px;margin-right:4px;vertical-align:middle}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px solid var(--bord);padding:4px 6px;text-align:left}}
.tab{{overflow-x:auto}} tr.incomplet td{{color:#d62728}}
.g{{padding:1px 6px;border-radius:8px;font-size:12px;color:#fff}} .majeure{{background:#d62728}} .mineure{{background:#ef8a17}} .info{{background:#4e79a7}}
.chiffres span{{display:inline-block;margin-right:18px}}
</style></head><body><main>
<h1>{titre}</h1><div class="doux">{periode}</div>
<p class="chiffres"><span><b>{majeures}</b> anomalie(s) majeure(s)</span><span><b>{mineures}</b> mineure(s)</span><span><b>{infos}</b> information(s)</span></p>
<h2>Courbes</h2>{courbes}
<h2>Contrôles</h2><div class="tab"><table><tr><th>Gravité</th><th>Type</th><th>Détail</th><th>Période (heure légale)</th></tr>{controles}</table></div>
<h2>Indicateurs journaliers</h2><div class="tab"><table>{jours}</table></div>
<p class="doux">Jours en rouge : incomplets, énergies sous-estimées. Énergie = somme des puissances × durée du pas. Rapport produit par analyser_bilan.py.</p>
</main></body></html>"""


def main(argv=None):
    p = argparse.ArgumentParser(description="Contrôle et analyse d'un bilan électrique au pas fin")
    p.add_argument("fichier", help="CSV du bilan (séparateur , ou ; détecté)")
    p.add_argument("--sortie", default="resultats_bilan", help="dossier des résultats")
    p.add_argument("--unite", default="auto", choices=["auto", "W", "kW", "MW"], help="unité des puissances du fichier")
    p.add_argument("--tolerance-bilan", type=float, default=0.001, help="écart relatif toléré (0,001 = 0,1 %%)")
    a = p.parse_args(argv)
    r = analyser(a.fichier, a.unite, a.tolerance_bilan)
    os.makedirs(a.sortie, exist_ok=True)
    ecrire_csv(os.path.join(a.sortie, "controles.csv"), r["controles"], ["type", "gravite", "detail", "debut", "fin"])
    champs = []
    for j in r["jours"]:
        champs += [c for c in j if c not in champs]
    ecrire_csv(os.path.join(a.sortie, "indicateurs_journaliers.csv"), r["jours"], champs)
    rapport_html(r, os.path.join(a.sortie, "rapport.html"))
    nb = Counter(c["gravite"] for c in r["controles"])
    print("Fichier : %s (%s → %s, pas %d min, %d pas, unité %s)" % (
        r["fichier"], r["debut"].strftime("%d/%m/%Y %H:%M"), r["fin"].strftime("%d/%m/%Y %H:%M"),
        r["pas_min"], r["nb_pas"], r["unite"]))
    print("Contrôles : %d majeur(s), %d mineur(s), %d info" % (nb["majeure"], nb["mineure"], nb["info"]))
    for c in r["controles"]:
        if c["gravite"] != "info":
            print("  [%s] %s : %s %s" % (c["gravite"], c["type"], c["detail"], c["debut"][:16]))
    print("Résultats écrits dans %s/" % a.sortie)
    return r


if __name__ == "__main__":
    main()
