-- Test automatique : compare l'import au contenu de resultats_attendus.md.
-- S'arrête en erreur au premier écart. À lancer après scripts/import_rte_enedis.sql.
DO $$
DECLARE v text;
BEGIN
  SELECT string_agg(couche || ':' || detail || '=' || nb, ',' ORDER BY couche, detail) INTO v FROM reseau_elec.resume;
  IF v IS DISTINCT FROM 'controles:hors_exploitation=1,controles:poste_en_double=1,controles:tension_illisible=1,controles:tension_supposee=3,'
                        'postes:poste_hta_bt=4,postes:poste_htb=4,postes:poste_source=1,'
                        'troncons:BT aerien=1,troncons:HTA aerien=4,troncons:HTA souterrain=2,troncons:HTB aerien=3,troncons:HTB souterrain=1' THEN
    RAISE EXCEPTION 'Résumé : obtenu %', v;
  END IF;

  SELECT string_agg(DISTINCT tension_origine || '->' || coalesce(tension_kv::text, 'NULL'), ',') INTO v
  FROM reseau_elec.troncons WHERE tension_origine IS NOT NULL;
  IF v IS DISTINCT FROM '225 kV->225,63kV->63,BT->0.4,HORS TENSION->NULL,HTA->20' THEN
    RAISE EXCEPTION 'Lecture des tensions : obtenu %', v;
  END IF;

  IF EXISTS (SELECT 1 FROM reseau_elec.troncons WHERE ST_SRID(geom) <> 2154 OR pose IS NULL) THEN
    RAISE EXCEPTION 'Tronçon hors Lambert 93 ou sans pose';
  END IF;
  IF (SELECT count(*) FROM reseau_elec.ouvrages_dtdict WHERE classe_precision IS NULL) <> 11 THEN
    RAISE EXCEPTION 'La vue ouvrages_dtdict doit contenir les 11 tronçons en classe inconnue';
  END IF;
  RAISE NOTICE 'import-donnees-rte-enedis : tous les contrôles sont conformes';
END $$;
