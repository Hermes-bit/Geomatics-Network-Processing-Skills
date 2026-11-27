-- Test automatique : compare les résultats du script au contenu de resultats_attendus.md.
-- S'arrête en erreur au premier écart. À lancer après scripts/proximite_dt_dict.sql.
DO $$
DECLARE
  attendu  text := 'Chaleur Urbaine:zone_incertitude:true|Enedis:dans_emprise:true|GRDF:zone_incertitude:false|Métropole:proximite:false|Orange:proximite:false|RTE:proximite:false|Syndicat intercommunal:dans_emprise:false';
  obtenu   text;
  ouvr     text;
BEGIN
  SELECT string_agg(exploitant || ':' || situation_la_plus_proche || ':' || ic_a_prevoir, '|' ORDER BY exploitant)
    INTO obtenu FROM dtdict.exploitants_concernes;
  IF obtenu IS DISTINCT FROM attendu THEN
    RAISE EXCEPTION 'Exploitants : attendu %, obtenu %', attendu, obtenu;
  END IF;

  SELECT string_agg(id || ':' || situation, ',' ORDER BY id::int) INTO ouvr FROM dtdict.ouvrages_concernes;
  IF ouvr IS DISTINCT FROM '1:dans_emprise,2:zone_incertitude,3:proximite,4:fuseau_aerien,5:proximite,7:proximite,8:zone_incertitude,9:dans_emprise' THEN
    RAISE EXCEPTION 'Ouvrages : obtenu %', ouvr;
  END IF;

  IF (SELECT conforme FROM dtdict.controle_emprise WHERE controle = 'écart entre polygones') THEN
    RAISE EXCEPTION 'L''écart de 240 m entre polygones aurait dû être signalé';
  END IF;
  IF EXISTS (SELECT 1 FROM dtdict.ouvrages_concernes WHERE id = '5' AND alertes LIKE '%exemption%') THEN
    RAISE EXCEPTION 'La ligne RTE 63 kV ne doit pas bénéficier de l''exemption des 3 m';
  END IF;
  RAISE NOTICE 'proximite-dt-dict : tous les contrôles sont conformes';
END $$;
