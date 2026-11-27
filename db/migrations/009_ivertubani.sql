-- New branch ივერთუბანი (opened 2026-11-02) and its Wolt store "Tema Ivertubani".
-- The id is set by hand (4) so it is the same in every database: the AI's glossary names the ids.
INSERT INTO branches (id, name) VALUES (4, 'ივერთუბანი')
ON CONFLICT (name) DO NOTHING;

-- Move the id counter to the highest id in use, so the next new branch gets 5 and never clashes.
DO $$ BEGIN
    PERFORM setval('branches_id_seq', (SELECT MAX(id) FROM branches));
END $$;

INSERT INTO wolt.venues (id, branch_id, name)
SELECT '6a2febc3416593778df4ef9a', id, 'Tema Ivertubani'
FROM branches WHERE name = 'ივერთუბანი'
ON CONFLICT (id) DO NOTHING;
