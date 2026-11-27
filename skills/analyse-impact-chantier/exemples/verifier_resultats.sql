-- Test automatique : compare le résultat de la chaîne (exemples/chainer_exemple.sh) au contenu
-- de resultats_attendus.md. S'arrête en erreur au premier écart.
-- Variable psql vegetation = oui si les tronçons de végétation ont été produits par le skill LiDAR.
\set ON_ERROR_STOP 1
SET client_min_messages = notice;
SELECT set_config('impact_test.vegetation', :'vegetation', false) \gset
DO $$
DECLARE
  avec_veg boolean := current_setting('impact_test.vegetation') = 'oui';
  attendu text;
  obtenu  text;
  v record;
BEGIN
  -- Registre des risques hors végétation : niveau, thème et objet, dans l'ordre du registre
  attendu := '1:ferroviaire|1:voisinage électrique:Ouvrage 4 : electricite aérien, 63 kV|1:voisinage électrique:Ouvrage 5 : ferroviaire aérien, 25 kV|'
          || '1:réseaux:Ouvrage 1 : electricite souterrain, classe B, 20 kV|1:réseaux:Ouvrage 6 : ferroviaire souterrain, classe C|'
          || '2:déclaration:Emprise : écart entre polygones|2:réseaux:Ouvrage 2 : gaz souterrain, classe A|'
          || '3:réseaux:Ouvrage 3 : telecom souterrain, classe C|3:foncier:Parcelle AB 0101 (99001)|3:foncier:Parcelle AB 0102 (99001)|'
          || '3:foncier:Parcelle AB 0103 (99001)|3:foncier:Parcelle AB 0104 (99001)|3:foncier:Parcelle AC 0202 (99001)|'
          || '4:foncier:Parcelle AB 0105 (99001)|4:foncier:Parcelle AC 0203 (99001)';
  SELECT string_agg(niveau || ':' || theme || CASE WHEN theme = 'ferroviaire' THEN '' ELSE ':' || objet END, '|' ORDER BY id)
    INTO obtenu FROM impact.risques WHERE theme <> 'végétation';
  IF obtenu IS DISTINCT FROM attendu THEN
    RAISE EXCEPTION 'Registre des risques : attendu %, obtenu %', attendu, obtenu;
  END IF;
  IF EXISTS (SELECT 1 FROM impact.risques WHERE objet LIKE 'Ouvrage 7%' OR objet LIKE '%AB 0106%' OR objet LIKE '%AC 0201%' OR objet LIKE '%AC 0204%') THEN
    RAISE EXCEPTION 'La conduite d''eau à 54 m et les parcelles à plus de 20 m ne doivent pas être retenues';
  END IF;

  -- Voie : section à moins de 20 m, PK calés par le skill PK, saut de PK signalé
  SELECT * INTO v FROM impact.voies;
  IF abs(pk_ref.pk_vers_m(v.pk_debut) - 15264.4) > 0.5 OR abs(pk_ref.pk_vers_m(v.pk_fin) - 15699.1) > 0.5
     OR v.pk_emprise_debut <> '15+674' OR v.pk_emprise_fin <> '15+676' OR abs(v.longueur_m - 184.9) > 0.3 THEN
    RAISE EXCEPTION 'Voie : obtenu % à %, emprise % à %, % m', v.pk_debut, v.pk_fin, v.pk_emprise_debut, v.pk_emprise_fin, v.longueur_m;
  END IF;
  IF v.avertissement NOT LIKE '%lacune de PK 15+400 = 15+650%' THEN
    RAISE EXCEPTION 'Le saut de PK dans la section aurait dû être signalé : %', v.avertissement;
  END IF;

  -- Exploitants et leur niveau de risque le plus grave
  SELECT string_agg(exploitant || ':' || niveau_max || ':' || ic_a_prevoir, '|' ORDER BY exploitant) INTO obtenu FROM impact.exploitants;
  IF obtenu IS DISTINCT FROM 'Enedis:1:true|GRDF:2:false|Orange:3:false|RTE:1:false|SNCF Réseau:1:true' THEN
    RAISE EXCEPTION 'Exploitants : obtenu %', obtenu;
  END IF;

  -- Parcelles : surfaces dans l'emprise et propriétaires personnes morales
  SELECT string_agg(right(id, 6) || ':' || situation || ':' || surface_emprise_m2, '|' ORDER BY id) INTO obtenu FROM impact.parcelles;
  IF obtenu IS DISTINCT FROM 'AB0101:occupee:104.0|AB0102:occupee:400.0|AB0103:occupee:280.0|AB0104:occupee:340.0|AB0105:riveraine:0.0|AC0202:occupee:216.0|AC0203:contact_negligeable:1.2' THEN
    RAISE EXCEPTION 'Parcelles : obtenu %', obtenu;
  END IF;
  IF (SELECT proprietaire FROM impact.parcelles WHERE id = '99001000AB0101') <> 'SNCF RESEAU' THEN
    RAISE EXCEPTION 'Propriétaire de la parcelle ferroviaire non repris';
  END IF;

  -- Végétation : tronçons produits par le vrai script du skill vegetation-lidar-hd
  IF avec_veg THEN
    SELECT string_agg(niveau || ':' || objet, '|' ORDER BY id) INTO obtenu FROM impact.risques WHERE theme = 'végétation';
    IF obtenu IS DISTINCT FROM '2:Ligne 830000 voie V1, tronçon 6 gauche|2:Ligne RTE 63 kV fictive, tronçon 3 droite|3:Ligne 830000 voie V1, tronçon 7 droite|4:Ligne 830000 voie V1, tronçon 9 gauche|4:Ligne 830000 voie V1, tronçon 9 droite' THEN
      RAISE EXCEPTION 'Végétation : obtenu %', obtenu;
    END IF;
  END IF;

  SELECT niveau_global || ':' || nb_critiques || ':' || nb_majeurs || ':' || nb_a_traiter || ':' || nb_info INTO obtenu FROM impact.synthese;
  attendu := '1:5:2:6:2';
  IF avec_veg THEN attendu := '1:5:4:7:4'; END IF;
  IF obtenu IS DISTINCT FROM attendu THEN
    RAISE EXCEPTION 'Synthèse : obtenu %', obtenu;
  END IF;
  IF avec_veg THEN
    RAISE NOTICE 'analyse-impact-chantier : tous les contrôles sont conformes';
  ELSE
    RAISE NOTICE 'analyse-impact-chantier : tous les contrôles sont conformes (sans la végétation)';
  END IF;
END $$;
