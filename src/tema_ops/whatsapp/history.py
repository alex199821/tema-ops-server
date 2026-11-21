import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


# The bot's memory lives in the table whatsapp.questions (db/migrations/007_whatsapp.sql).
# It connects as bot_writer, which may only add and read rows in that one table.

def last_questions(phone, count):
    # The person's last `count` questions with their answers, oldest first
    with psycopg.connect(os.environ["BOT_DATABASE_URL"]) as conn:
        rows = conn.execute(
            "SELECT question, answer FROM whatsapp.questions"
            " WHERE phone = %s ORDER BY id DESC LIMIT %s",
            (phone, count),
        ).fetchall()
    return rows[::-1]


def save_answer(phone, asked_at, question, answer):
    with psycopg.connect(os.environ["BOT_DATABASE_URL"]) as conn:  # saved when the block ends
        conn.execute(
            "INSERT INTO whatsapp.questions (phone, asked_at, question, answer)"
            " VALUES (%s, %s, %s, %s)",
            (phone, asked_at, question, answer),
        )
