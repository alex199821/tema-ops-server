-- IncoPOS product groups (from /item_group), e.g. 8 = ყავა. incopos.items.group_id points here.
-- Rights come from 006: new incopos tables are writable by incopos_writer, readable by ai_reader.
CREATE TABLE IF NOT EXISTS incopos.item_groups (
    id   INT PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL          -- the group tree: AAGAAA is a subgroup of AAG
);
