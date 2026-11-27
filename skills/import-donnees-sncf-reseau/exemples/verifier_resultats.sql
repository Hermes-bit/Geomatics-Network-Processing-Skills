-- Test automatique : compare l'import au contenu de resultats_attendus.md.
-- S'arrête en erreur au premier écart. À lancer après scripts/import_sncf_reseau.sql.
DO $$
DECLARE v text;
BEGIN
  SELECT string_agg(couche || '=' || nb, ',' ORDER BY couche) INTO v FROM sncf.resume;
  IF v IS DISTINCT FROM 'bornes_pk=5,controles=6,lignes=4,sauts_pk=1' THEN
    RAISE EXCEPTION 'Résumé : obtenu %', v;
  END IF;

  SELECT string_agg(code_ligne || ':' || pk_amont || '=' || pk_aval, ',') INTO v FROM sncf.sauts_pk;
  IF v IS DISTINCT FROM '999000:4+000=4+250' THEN RAISE EXCEPTION 'Sauts de PK : obtenu %', v; END IF;

  -- Le tronçon numérisé à l'envers : 4+250 doit être en 804000 6600000 (porté par le saut),
  -- 6+290 en 806000 6600400.
  IF NOT EXISTS (SELECT 1 FROM sncf.bornes_pk WHERE code_ligne = '999000' AND pk = '6+290'
                 AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(806000, 6600400), 2154), 0.01)) THEN
    RAISE EXCEPTION 'La borne 6+290 n''est pas au bon bout du tronçon numérisé à l''envers';
  END IF;

  SELECT string_agg(couche || ':' || type, ',' ORDER BY id) INTO v FROM sncf.controles;
  IF v IS DISTINCT FROM 'lignes:sens_suppose,lignes:saut_pk_lacune,gares:ligne_inconnue,passages_niveau:pk_illisible,passages_niveau:loin_de_sa_ligne,ouvrages:pk_hors_ligne' THEN
    RAISE EXCEPTION 'Contrôles : obtenu %', v;
  END IF;

  IF (SELECT count(*) FROM sncf.ouvrages) <> 3 OR (SELECT count(*) FROM sncf.gares) <> 3
     OR (SELECT count(*) FROM sncf.passages_niveau) <> 4 THEN
    RAISE EXCEPTION 'Nombre d''objets ponctuels inattendu';
  END IF;
  IF EXISTS (SELECT 1 FROM sncf.lignes WHERE ST_SRID(geom) <> 2154) THEN
    RAISE EXCEPTION 'Les lignes ne sont pas en Lambert 93';
  END IF;
  RAISE NOTICE 'import-donnees-sncf-reseau : tous les contrôles sont conformes';
END $$;
