-- The company's own branches, shared by Wolt, cash register, expenses...
CREATE TABLE IF NOT EXISTS branches (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE SCHEMA IF NOT EXISTS wolt;

CREATE TABLE IF NOT EXISTS wolt.venues (
    id        TEXT PRIMARY KEY,
    branch_id INT NOT NULL REFERENCES branches(id),
    name      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wolt.orders (
    purchase_id    TEXT PRIMARY KEY,
    venue_id       TEXT NOT NULL REFERENCES wolt.venues(id),
    order_number   TEXT,
    status         TEXT NOT NULL,
    received_at    TIMESTAMP NOT NULL,
    delivered_at   TIMESTAMP,
    total_gross    NUMERIC(10,2) NOT NULL,
    total_net      NUMERIC(10,2) NOT NULL,
    is_cash        BOOLEAN,
    rating         INT,
    review_comment TEXT,
    raw            JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_venue_time ON wolt.orders (venue_id, received_at);

CREATE TABLE IF NOT EXISTS wolt.order_items (
    purchase_id TEXT NOT NULL REFERENCES wolt.orders(purchase_id) ON DELETE CASCADE,
    row_number  INT NOT NULL,
    name        TEXT NOT NULL,
    count       INT NOT NULL,
    final_gross NUMERIC(10,2) NOT NULL,
    final_net   NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (purchase_id, row_number)
);