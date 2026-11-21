-- The WhatsApp bot's memory: one row per answer the bot actually sent.
-- Before answering, the bot reads the person's last questions and answers from here,
-- so conversations survive restarts and deploys.
--   question = what the person asked. Several quick messages answered together are one
--              question (joined by new lines); a voice message is saved as the text we heard.
--   answer   = the AI's answer only (not the "🎤 heard: ..." line we put in front of it).
-- An answer that was thrown away (new messages came in while thinking) is never saved.
--
-- It is in its own schema on purpose: ai_reader may read every table in public and wolt,
-- but not this one, so one person's questions can never show up in someone else's answer.

CREATE SCHEMA IF NOT EXISTS whatsapp;

CREATE TABLE IF NOT EXISTS whatsapp.questions (
    id          BIGSERIAL PRIMARY KEY,
    phone       TEXT NOT NULL,       -- who asked (as WhatsApp sends it: digits, no +)
    asked_at    TIMESTAMP NOT NULL,  -- when the person's last message arrived
    answered_at TIMESTAMP NOT NULL DEFAULT now(),
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS questions_phone ON whatsapp.questions (phone, id);

-- bot_writer = the WhatsApp bot: may add rows and read them, nothing else
-- (no changing or deleting rows, no other tables).
-- The password is NOT here (the repo is public). It is set by hand on each machine.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bot_writer') THEN
        CREATE ROLE bot_writer LOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA whatsapp TO bot_writer;
GRANT SELECT, INSERT ON whatsapp.questions TO bot_writer;
GRANT USAGE ON SEQUENCE whatsapp.questions_id_seq TO bot_writer;  -- to number new rows
