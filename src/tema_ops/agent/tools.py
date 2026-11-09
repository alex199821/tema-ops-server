import os
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from langchain.tools import tool

from tema_ops.wolt.excel_report import build_report

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

# The AI calls this when someone asks for the Wolt report file.
# Gemini only gets the text; the file path (the "artifact") goes to our chat code, which delivers the file.
@tool(response_format="content_and_artifact")
def get_wolt_report() -> tuple[str, str]:
    """Build the Wolt sales report as an Excel file and attach it to the chat.
    The report has one sheet per branch, with units sold per product per day and daily totals.
    Use this only when the user asks for the report or the Excel file itself.
    For questions about sales, orders or products, use run_sql instead."""
    path = Path(f"reports/wolt_report_chat_{date.today():%Y-%m-%d}.xlsx").resolve()
    build_report(path)
    return "ვოლტის რეპორტი მიმაგრებულია მესიჯზე", str(path)

