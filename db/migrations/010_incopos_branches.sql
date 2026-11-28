-- IncoPOS for every branch. Each branch has its own IncoCloud account, and each account numbers its
-- shop, receipts, products and product groups from 1: receipt 5 of ლისი is not receipt 5 of სანაპირო,
-- and the same product number can be a different product in another branch. So every IncoPOS row now
-- says which branch it is from, and branch_id is part of every key. It replaces location_id: each
-- account has exactly one shop (the loader checks that).
-- Everything loaded so far came from the first key: POS name ახალი კაფე = the new დოლაბაური.

-- 1. Which branch each row is from
UPDATE incopos.locations SET branch_id = (SELECT id FROM branches WHERE name = 'დოლაბაური') WHERE id = 2;

ALTER TABLE incopos.sales       ADD COLUMN branch_id INT;
ALTER TABLE incopos.sale_lines  ADD COLUMN branch_id INT;
ALTER TABLE incopos.payments    ADD COLUMN branch_id INT;
ALTER TABLE incopos.items       ADD COLUMN branch_id INT;
ALTER TABLE incopos.item_groups ADD COLUMN branch_id INT;

UPDATE incopos.sales s      SET branch_id = l.branch_id FROM incopos.locations l WHERE l.id = s.location_id;
UPDATE incopos.sale_lines x SET branch_id = l.branch_id FROM incopos.locations l WHERE l.id = x.location_id;
UPDATE incopos.payments x   SET branch_id = l.branch_id FROM incopos.locations l WHERE l.id = x.location_id;
UPDATE incopos.items        SET branch_id = (SELECT id FROM branches WHERE name = 'დოლაბაური');
UPDATE incopos.item_groups  SET branch_id = (SELECT id FROM branches WHERE name = 'დოლაბაური');

-- 2. The old keys go: they used numbers that clash between branches
ALTER TABLE incopos.sale_lines  DROP CONSTRAINT sale_lines_location_id_sale_id_fkey;
ALTER TABLE incopos.payments    DROP CONSTRAINT payments_location_id_sale_id_fkey;
ALTER TABLE incopos.sales       DROP CONSTRAINT sales_location_id_fkey;
ALTER TABLE incopos.sales       DROP CONSTRAINT sales_pkey;
ALTER TABLE incopos.sale_lines  DROP CONSTRAINT sale_lines_pkey;
ALTER TABLE incopos.payments    DROP CONSTRAINT payments_pkey;
ALTER TABLE incopos.items       DROP CONSTRAINT items_pkey;
ALTER TABLE incopos.item_groups DROP CONSTRAINT item_groups_pkey;
ALTER TABLE incopos.locations   DROP CONSTRAINT locations_pkey;
ALTER TABLE incopos.locations   DROP CONSTRAINT locations_branch_id_key;
DROP INDEX incopos.sales_location_time;

ALTER TABLE incopos.sales      DROP COLUMN location_id;
ALTER TABLE incopos.sale_lines DROP COLUMN location_id;
ALTER TABLE incopos.payments   DROP COLUMN location_id;

-- 3. The new keys. A row without a branch makes this fail, so nothing is half done.
-- locations: one row per branch; id = the IncoPOS location Id inside that branch's account
ALTER TABLE incopos.locations
    ALTER COLUMN id SET NOT NULL,
    ALTER COLUMN branch_id SET NOT NULL,
    ADD PRIMARY KEY (branch_id);

ALTER TABLE incopos.sales
    ALTER COLUMN branch_id SET NOT NULL,
    ADD PRIMARY KEY (branch_id, id),
    ADD FOREIGN KEY (branch_id) REFERENCES incopos.locations (branch_id);
CREATE INDEX sales_branch_time ON incopos.sales (branch_id, paid_at);

ALTER TABLE incopos.sale_lines
    ALTER COLUMN branch_id SET NOT NULL,
    ADD PRIMARY KEY (branch_id, sale_id, id),
    ADD FOREIGN KEY (branch_id, sale_id) REFERENCES incopos.sales (branch_id, id) ON DELETE CASCADE;

ALTER TABLE incopos.payments
    ALTER COLUMN branch_id SET NOT NULL,
    ADD PRIMARY KEY (branch_id, sale_id, id),
    ADD FOREIGN KEY (branch_id, sale_id) REFERENCES incopos.sales (branch_id, id) ON DELETE CASCADE;

-- items and groups: a product number means something only together with its branch
ALTER TABLE incopos.items
    ALTER COLUMN branch_id SET NOT NULL,
    ADD PRIMARY KEY (branch_id, id),
    ADD FOREIGN KEY (branch_id) REFERENCES branches (id);

ALTER TABLE incopos.item_groups
    ALTER COLUMN branch_id SET NOT NULL,
    ADD PRIMARY KEY (branch_id, id),
    ADD FOREIGN KEY (branch_id) REFERENCES branches (id);
