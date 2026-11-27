# Résultats attendus

```
python3 scripts/analyser_bilan.py exemples/bilan_enedis_reel_2026-11.csv --sortie resultats_reel
python3 scripts/analyser_bilan.py exemples/bilan_fictif_changement_heure.csv --sortie resultats_fictif
python3 exemples/test_analyse_bilan.py      # vérifie tout automatiquement
```

## Données réelles Enedis (`bilan_enedis_reel_2026-11.csv`)

Bilan électrique demi-heure publié par Enedis en J+4, pas de 15 min, du 14/11/2026 00:00 au 22/11/2026 23:45, 768 pas lus, valeurs en W (consommation de 31 à 48 GW).

| Gravité | Contrôle | Attendu |
|---|---|---|
| majeure | pas_manquants | 96 pas manquants, **toute la journée du 17/11** |
| mineure | colonne_nulle | `temperature_normale_lissee` vaut 0 partout |
| info | unite_supposee | W |
| info | bilan_equilibre | injection + production = soutirages + pertes + consommation à chaque pas |
| info | thermosensibilite | non exploitable (8 jours complets, R² ≈ 0,02) |

Quelques indicateurs journaliers :

| Jour | Conso (MWh) | Pointe (MW) | Production locale | Pertes |
|---|---|---|---|---|
| 14/11 (samedi) | 993 252 | 45 131 à 19:00 | 20,6 % | 7,15 % |
| 16/11 | 991 755 | 47 692 à 19:00 | 26,5 % | 6,53 % |
| 17/11 | absent | | | |
| 18/11 | 956 995 | 45 660 à 19:00 | 42,3 % (éolien fort) | 6,03 % |

## Jeu fictif (`bilan_fictif_changement_heure.csv`)

Trois jours en MW au pas de 30 min, séparateur `;`, virgule décimale, du 24 au 26/10/2026.

| Piège | Détection attendue |
|---|---|
| 24/10 10:00 et 10:30 absents | `pas_manquants` (majeure, 1 h) et `jour_incomplet` (46 pas sur 48) |
| 25/10, passage à l'heure d'hiver (02:00 et 02:30 deux fois) | **pas d'anomalie** : 50 pas attendus, jour complet |
| 26/10 12:00 en double | `horodate_en_double` (majeure) |
| 26/10 08:00 pertes vides | `valeur_manquante` (mineure) ; énergie des pertes du 26/10 non calculée |
| 26/10 18:00 consommation gonflée de 50 MW | `bilan_desequilibre` (majeure, écart 50 MW) |
