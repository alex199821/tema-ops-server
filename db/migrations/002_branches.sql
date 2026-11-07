INSERT INTO branches (name) VALUES ('სანაპირო'), ('ლისი'), ('დოლაბაური')
ON CONFLICT (name) DO NOTHING;

INSERT INTO wolt.venues (id, branch_id, name)
SELECT v.id, b.id, v.name
FROM (VALUES
    ('69ca6878108f346b6140eaf1', 'სანაპირო',  'Tema Gamsakhurdia'),
    ('69ca6878108f346b6140eaf2', 'ლისი',      'Tema Amashukeli'),
    ('6a994d56eeb9b13cc11a049d', 'დოლაბაური', 'Tema Dolabauri')
) AS v(id, branch, name)
JOIN branches b ON b.name = v.branch
ON CONFLICT (id) DO NOTHING;