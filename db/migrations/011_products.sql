-- One product list for all branches. Each branch's IncoPOS names its products its own way
-- (სანაპირო "ქათმის როლი" = the others' "როლი"), so every IncoPOS product points to one shared
-- product here. The links are set by incopos/load_incopos.py from incopos/products.py.
-- In the public schema: Wolt's products can point here too later.
CREATE TABLE IF NOT EXISTS products (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

ALTER TABLE incopos.items ADD COLUMN IF NOT EXISTS product_id INT REFERENCES products (id);
CREATE INDEX IF NOT EXISTS items_product ON incopos.items (product_id);

-- The IncoPOS loader adds new shared products; the AI reads them (ai_reader gets SELECT on new
-- public tables by default, see 003_roles.sql)
GRANT SELECT, INSERT ON products TO incopos_writer;
GRANT USAGE ON SEQUENCE products_id_seq TO incopos_writer;
