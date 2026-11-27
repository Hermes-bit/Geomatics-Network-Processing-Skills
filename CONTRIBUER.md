# Ajouter un skill

1. Copiez `modele-skill/` vers `skills/<nom-du-skill>/` (nom en minuscules, mots séparés par des tirets, sans accents).
2. Remplissez `SKILL.md` :
   - `name` : le nom du dossier ;
   - `description` : une ou deux phrases qui disent **ce que fait le skill et quand l'utiliser**. C'est ce texte que Claude lit pour décider d'utiliser le skill : mettez-y les mots que les gens emploient vraiment (« DT-DICT », « PK », « topologie »…).
   - le corps : étapes, pièges du métier, format de sortie. Restez concret.
3. Mettez les scripts dans `scripts/` et testez-les sur le jeu d'exemple.
4. Dans `exemples/`, fournissez :
   - `donnees_exemple.sql` (ou un GeoPackage / GeoJSON léger) : petit, fictif, en Lambert 93, avec des cas pièges ;
   - `resultats_attendus.md` : ce que le skill doit produire sur ces données ;
   - `demandes_exemple.md` : 3 à 5 demandes à faire à Claude ;
   - si besoin, `lancer_exemple.sql` pour produire les fichiers de sortie.
5. Ajoutez le skill au tableau du `README.md` et à la liste `skills` de `.claude-plugin/marketplace.json`.
6. Vérifiez avec `./outils/tester_exemples.sh` et `./outils/empaqueter.sh <nom-du-skill>`.

## Règles communes
- Ne jamais modifier les données source sans accord : travailler dans un schéma ou une copie dédiés.
- Annoncer les hypothèses (SCR, tolérances, champs utilisés) dans la réponse.
- Pas de données réelles sensibles dans les exemples (réseaux sensibles, données personnelles).
