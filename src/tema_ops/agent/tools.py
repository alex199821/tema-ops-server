import os

import psycopg
from dotenv import load_dotenv
from langchain.tools import tool

load_dotenv()

MAX_ROWS = 200


# The AI writes a SQL query and calls this tool with it. The tool runs that query.
# It connects as ai_reader, so it can only read data, never change it.
@tool
def run_sql(query: str) -> str:
    """Run a read-only PostgreSQL query on Tema's database and return the result.
    Returns at most 200 rows."""
    try:
        with psycopg.connect(os.environ["AI_DATABASE_URL"]) as conn:
            cur = conn.execute(query, prepare=True)  # Postgres refuses more than one statement
            if cur.description is None:
                return "The query ran but did not return a table."
            columns = [c.name for c in cur.description]
            rows = cur.fetchmany(MAX_ROWS + 1)  # 1 extra, to know if there are more
    except psycopg.Error as e:
        return f"SQL error: {e}"

    more = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    lines = [" | ".join(columns)] + [" | ".join(str(v) for v in row) for row in rows]
    if more:
        lines.append(f"(only the first {MAX_ROWS} rows are shown. Use SUM/COUNT/GROUP BY to get fewer rows.)")
    else:
        lines.append(f"({len(rows)} rows)")
    return "\n".join(lines)


if __name__ == "__main__":
    print(run_sql.invoke("SELECT id, name FROM branches ORDER BY id"))
    print(run_sql.invoke("DELETE FROM wolt.orders"))
    print(run_sql.invoke("SET statement_timeout = 0; SELECT 1"))