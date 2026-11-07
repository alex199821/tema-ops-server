import calendar
import os
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

load_dotenv()

MONTHS_KA = ["იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
             "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი"]

TITLE_FILL = PatternFill("solid", fgColor="7030A0")
TOTAL_FILL = PatternFill("solid", fgColor="002060")
WHITE_BOLD = Font(bold=True, color="FFFFFF", size=14)

ITEMS_SQL = """
SELECT o.received_at::date, i.name, SUM(i.count)
FROM wolt.order_items i
JOIN wolt.orders o ON o.purchase_id = i.purchase_id
JOIN wolt.venues v ON v.id = o.venue_id
WHERE o.status = 'DELIVERED' AND v.branch_id = %s
GROUP BY 1, 2
"""

TOTALS_SQL = """
SELECT o.received_at::date, SUM(o.total_gross)
FROM wolt.orders o
JOIN wolt.venues v ON v.id = o.venue_id
WHERE o.status = 'DELIVERED' AND v.branch_id = %s
GROUP BY 1
"""


def load_branch(cur, branch_id):
    items = defaultdict(Counter)  # day -> {item name: count}
    for day, name, count in cur.execute(ITEMS_SQL, (branch_id,)):
        items[day][name] = count
    totals = dict(cur.execute(TOTALS_SQL, (branch_id,)).fetchall())  # day -> total
    return items, totals


def write_month(sheet, year, month, items, totals):
    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    month_counts = sum((items[d] for d in days), Counter())
    names = [name for name, _ in month_counts.most_common()]
    last_col = len(names) + 2

    # Title row, e.g. "ოქტომბერი 2026"
    sheet.append([f"{MONTHS_KA[month - 1]} {year}"])
    title_row = sheet.max_row
    sheet.merge_cells(start_row=title_row, start_column=1, end_row=title_row, end_column=last_col)
    sheet.cell(title_row, 1).fill = TITLE_FILL
    sheet.cell(title_row, 1).font = Font(bold=True, color="FFFFFF", size=18)

    # Header row: item names + total
    sheet.append(["თარიღი"] + names + ["თანხა მთლიანი"])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)

    # One row per day
    for d in days:
        sheet.append([d.strftime("%d.%m.%Y")] + [items[d][n] or None for n in names] + [totals.get(d, 0)])
    first, last = sheet.max_row - len(days) + 1, sheet.max_row

    # Total row with SUM formulas
    sheet.append(["სულ"] + [f"=SUM({get_column_letter(c)}{first}:{get_column_letter(c)}{last})"
                            for c in range(2, last_col + 1)])
    for cell in sheet[sheet.max_row]:
        cell.fill = TOTAL_FILL
        cell.font = WHITE_BOLD

    sheet.append([])
    sheet.append([])


def build_report(path):
    wb = Workbook()
    wb.remove(wb.active)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        branches = cur.execute("SELECT id, name FROM branches ORDER BY id").fetchall()
        for branch_id, branch_name in branches:
            sheet = wb.create_sheet(branch_name)
            sheet.column_dimensions["A"].width = 14
            items, totals = load_branch(cur, branch_id)
            if not totals:
                continue
            first_day, last_day = min(totals), max(totals)
            year, month = first_day.year, first_day.month
            while (year, month) <= (last_day.year, last_day.month):
                write_month(sheet, year, month, items, totals)
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    Path(path).parent.mkdir(exist_ok=True)
    wb.save(path)


if __name__ == "__main__":
    build_report("reports/wolt_report.xlsx")
    print("Saved reports/wolt_report.xlsx")