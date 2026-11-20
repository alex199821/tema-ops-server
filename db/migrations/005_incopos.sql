-- IncoPOS (the cash register): receipts from the IncoCloud API.
-- The raw answers stay in data/incopos/; these tables are loaded from them.
-- The API repeats some receipts: the primary keys keep only one copy.

CREATE SCHEMA IF NOT EXISTS incopos;

-- An IncoPOS location = one of our branches.
-- branch_id stays empty until Nino confirms which branch it is.
CREATE TABLE IF NOT EXISTS incopos.locations (
    id        INT PRIMARY KEY,                -- IncoPOS location Id
    branch_id INT UNIQUE REFERENCES branches(id),
    name      TEXT NOT NULL
);

-- Products (from /item)
CREATE TABLE IF NOT EXISTS incopos.items (
    id           INT PRIMARY KEY,
    name         TEXT NOT NULL,
    group_id     INT,
    measure_unit TEXT,
    retail_price NUMERIC(10,2),
    deleted      BOOLEAN NOT NULL DEFAULT false,
    raw          JSONB NOT NULL
);

-- One row per receipt
CREATE TABLE IF NOT EXISTS incopos.sales (
    location_id INT NOT NULL REFERENCES incopos.locations(id),
    id          INT NOT NULL,                 -- sale Id
    paid_at     TIMESTAMP NOT NULL,           -- Tbilisi time (the "Z" from the API is wrong)
    raw         JSONB NOT NULL,               -- the whole receipt as it came
    PRIMARY KEY (location_id, id)
);
CREATE INDEX IF NOT EXISTS sales_location_time ON incopos.sales (location_id, paid_at);

-- What was on each receipt
CREATE TABLE IF NOT EXISTS incopos.sale_lines (
    location_id INT NOT NULL,
    sale_id     INT NOT NULL,
    id          BIGINT NOT NULL,              -- DetailId
    item_id     INT NOT NULL,                 -- no foreign key: an unknown product must not block a receipt
    quantity    NUMERIC(10,3) NOT NULL,
    price       NUMERIC(10,2) NOT NULL,       -- per unit, VAT included
    cost        NUMERIC(10,4),                -- PriceIn: cost per unit on the day of the sale
    discount    NUMERIC(10,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (location_id, sale_id, id),
    FOREIGN KEY (location_id, sale_id) REFERENCES incopos.sales (location_id, id) ON DELETE CASCADE
);

-- How each receipt was paid
CREATE TABLE IF NOT EXISTS incopos.payments (
    location_id INT NOT NULL,
    sale_id     INT NOT NULL,
    id          BIGINT NOT NULL,
    type_id     INT NOT NULL,                 -- see /payment_type (so far always 1)
    amount      NUMERIC(10,2) NOT NULL,
    created_at  TIMESTAMP NOT NULL,
    PRIMARY KEY (location_id, sale_id, id),
    FOREIGN KEY (location_id, sale_id) REFERENCES incopos.sales (location_id, id) ON DELETE CASCADE
);