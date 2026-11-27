# -*- coding: utf-8 -*-
"""
Lance en une fois, sur la même base PostGIS, les skills dont l'analyse d'impact a besoin, puis
la synthèse, et exporte le résultat en GeoPackage pour le dossier (rapport/dossier_impact.py) :

  1. ../proximite-dt-dict/scripts/proximite_dt_dict.sql        (obligatoire)
  2. ../referencement-pk-ferroviaire/scripts/referencement_pk.sql (si --pk est donné)
  3. scripts/impact_chantier.sql                               (synthèse et registre des risques)

Les scripts des autres skills ne sont pas copiés ni modifiés sur le disque : seule leur
section 0 (paramètres et sources) est remplacée, à la volée, par le fichier que vous donnez.
Un fichier de section 0 contient les CREATE TABLE ... parametres et CREATE VIEW ... src_*
du script concerné, adaptés à vos tables (voir exemples/sources_*.sql).

Usage :
  python3 scripts/chainer_postgis.py --base "dbname=ma_base" \\
      --dtdict mes_sources_dtdict.sql [--pk mes_sources_pk.sql] [--impact mes_sources_impact.sql] \\
      [--gpkg impact.gpkg]

Prérequis : psql (et ogr2ogr pour --gpkg). Les skills proximite-dt-dict et, pour une voie
ferrée, referencement-pk-ferroviaire doivent être installés à côté de ce skill (même dossier
parent), ou indiqués avec --skills.
"""

import argparse
import os
import re
import subprocess
import sys

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLES_EXPORT = {"zone": "impact.zone", "risques": "impact.risques", "exploitants": "impact.exploitants",
                 "ouvrages": "dtdict.ouvrages_concernes", "voies": "impact.voies", "vegetation": "impact.vegetation",
                 "parcelles": "impact.parcelles", "synthese": "impact.synthese"}


def remplacer_section0(sql, section0, nom):
    """Remplace le contenu de la section « 0. PARAMÈTRES ET SOURCES » d'un script du dépôt."""
    debut = re.search(r"^-- 0\. PARAMÈTRES ET SOURCES.*\n-- -+\n", sql, re.M)
    fin = re.search(r"^-- -+\n-- 1\. ", sql, re.M)
    if not debut or not fin or fin.start() < debut.end():
        raise SystemExit("%s : section 0 introuvable (le script a-t-il changé de structure ?)" % nom)
    return sql[:debut.end()] + "\n" + section0.strip() + "\n\n" + sql[fin.start():]


def psql(base, sql, nom):
    print("=== %s" % nom, flush=True)
    r = subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", base], input=sql, text=True,
                       capture_output=True, env=dict(os.environ, PGOPTIONS="-c client_min_messages=warning"))
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        raise SystemExit("Échec de %s" % nom)


def lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return f.read()


def script_skill(dossier_skills, skill, fichier):
    chemin = os.path.join(dossier_skills, skill, "scripts", fichier)
    if not os.path.exists(chemin):
        raise SystemExit("Skill %s introuvable (%s) : l'installer à côté de analyse-impact-chantier "
                         "ou donner --skills" % (skill, chemin))
    return chemin


def principal(arguments=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="", help="connexion PostgreSQL (ex. \"dbname=ma_base\"), sinon PGDATABASE")
    ap.add_argument("--dtdict", required=True, help="section 0 du script proximite_dt_dict.sql")
    ap.add_argument("--pk", help="section 0 du script referencement_pk.sql (voie ferrée près du chantier)")
    ap.add_argument("--impact", help="section 0 de impact_chantier.sql (sinon : celle du script)")
    ap.add_argument("--skills", default=os.path.dirname(ICI), help="dossier qui contient les skills")
    ap.add_argument("--gpkg", help="GeoPackage à écrire avec les tables du schéma impact")
    a = ap.parse_args(arguments)

    dt = script_skill(a.skills, "proximite-dt-dict", "proximite_dt_dict.sql")
    psql(a.base, remplacer_section0(lire(dt), lire(a.dtdict), dt), "proximite-dt-dict")
    if a.pk:
        pk = script_skill(a.skills, "referencement-pk-ferroviaire", "referencement_pk.sql")
        psql(a.base, remplacer_section0(lire(pk), lire(a.pk), pk), "referencement-pk-ferroviaire")
    else:
        psql(a.base, "DROP SCHEMA IF EXISTS pk_ref CASCADE;", "pas de voie ferrée (--pk absent)")
    imp = os.path.join(ICI, "scripts", "impact_chantier.sql")
    sql = lire(imp)
    if a.impact:
        sql = remplacer_section0(sql, lire(a.impact), imp)
    psql(a.base, sql, "analyse-impact-chantier")

    if a.gpkg:
        if os.path.exists(a.gpkg):
            os.remove(a.gpkg)
        pg = "PG:" + (a.base or "dbname=" + os.environ.get("PGDATABASE", ""))
        for i, (nom, table) in enumerate(TABLES_EXPORT.items()):
            subprocess.run(["ogr2ogr", "-f", "GPKG", a.gpkg, pg, "-sql", "SELECT * FROM %s" % table, "-nln", nom,
                            "-a_srs", "EPSG:2154"] + (["-update"] if i else []), check=True)
        print("GeoPackage écrit : %s (couches %s)" % (a.gpkg, ", ".join(TABLES_EXPORT)))


if __name__ == "__main__":
    principal()
