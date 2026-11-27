# Demandes à faire à Claude pour tester le skill

Avec le jeu d'exemple chargé dans PostGIS (schéma `dtdict_exemple`) :

1. « J'ai une emprise de travaux dans `dtdict_exemple.emprise` et les réseaux dans `dtdict_exemple.ouvrages`. Quels exploitants dois-je consulter pour ma DT ? »
2. « Mon emprise est-elle valable pour une seule déclaration ? » (réponse attendue : non, un polygone est à 240 m des autres)
3. « Y a-t-il des réseaux sensibles pour lesquels je dois prévoir des investigations complémentaires ? » (Enedis HTA et le réseau de chaleur)
4. « Sors-moi la liste des exploitants en CSV avec la distance minimale. »
5. « La ligne RTE est à 4,5 m, est-ce que je peux me passer de DICT pour poser un mât ? » (réponse attendue : non, l'exemption des 3 m ne vaut que pour la BT aérienne et la traction ferroviaire)

Sur vos propres données :

- « Voici le KML de mon emprise exporté du guichet unique et les plans des exploitants en DXF. Vérifie que la réponse du guichet unique n'oublie personne. »
- « Je n'ai pas les plans : utilise les données ouvertes RTE et Enedis pour une première idée des réseaux électriques autour de ce chantier. »
- « Mon chantier longe une voie ferrée électrifiée sur 2 km : découpe l'emprise si besoin et liste ce qui est à moins de 5 m. »
