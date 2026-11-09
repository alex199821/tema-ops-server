import calendar
import os
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

load_dotenv()

MONTHS_KA = ["იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
             "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი"]

TITLE_FILL = PatternFill("solid", fgColor="7030A0")
TOTAL_FILL = PatternFill("solid", fgColor="002060")
NOTE_FONT = Font(bold=True, size=14, color="C00000")  # dark red
NOTE_FILL = PatternFill("solid", fgColor="FFF2CC")    # light yellow
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

SHIFTS_SQL = """
SELECT v.branch_id,
       (o.received_at - interval '9 hours')::date,  -- the date the shift started
       CASE WHEN o.received_at::time >= '09:00' AND o.received_at::time < '21:00'
            THEN 'day' ELSE 'night' END,
       SUM(o.total_gross)
FROM wolt.orders o
JOIN wolt.venues v ON v.id = o.venue_id
WHERE o.status = 'DELIVERED'
GROUP BY 1, 2, 3
"""

DATA_RANGE_SQL = """
SELECT v.branch_id, MIN(o.received_at::date), MAX(o.received_at::date)
FROM wolt.orders o
JOIN wolt.venues v ON v.id = o.venue_id
GROUP BY 1
"""

def load_branch(cur, branch_id):
    items = defaultdict(Counter)  # day -> {item name: count}
    for day, name, count in cur.execute(ITEMS_SQL, (branch_id,)):
        items[day][name] = count
    totals = dict(cur.execute(TOTALS_SQL, (branch_id,)).fetchall())  # day -> total
    return items, totals

def load_shifts(cur):
    shifts = defaultdict(dict)  # (branch_id, shift date) -> {"day": GEL, "night": GEL}
    for branch_id, day, shift, total in cur.execute(SHIFTS_SQL):
        shifts[(branch_id, day)][shift] = total
    # first and last loaded day per branch, to leave out incomplete shifts
    data_range = {branch_id: (first, last) for branch_id, first, last in cur.execute(DATA_RANGE_SQL)}
    return shifts, data_range

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

SHIFT_RULES = [
    "თვის ათვლა იწყება 1 რიცხვის დილის ცვლიდან",
    "ღამის ცვლა მოიცავს 21:00-დან მეორე დილის 09:00-მდე",
    "თუ შეკვეთა შემოვიდა 20.59 და მიტანილი იყო 21.24-ზე, შეკვეთა მიეწერება დღის ცვლას",
    "ყურადღება: თვის ჯამები ფილიალების გაყიდვებს არ ემთხვევა — ცვლების რეპორტში თვე იწყება 1 რიცხვის 09:00-ზე, ფილიალის გაყიდვები კი 00:00-ზე",
]


def shift_value(shifts, data_range, branch_id, d, shift):
    # Empty if the shift isn't fully loaded (the first and the newest night are half-loaded)
    if branch_id not in data_range:
        return None
    first, last = data_range[branch_id]
    end = d if shift == "day" else d + timedelta(days=1)  # a night shift ends the next morning
    if d < first or end > last:
        return None
    return shifts.get((branch_id, d), {}).get(shift, 0)


def write_shift_month(sheet, year, month, branches, shifts, data_range):
    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    last_col = 1 + 2 * len(branches)  # date + (day, night) per branch

    # Title row, e.g. "ოქტომბერი 2026"
    sheet.append([f"{MONTHS_KA[month - 1]} {year}"])
    title_row = sheet.max_row
    sheet.merge_cells(start_row=title_row, start_column=1, end_row=title_row, end_column=last_col)
    sheet.cell(title_row, 1).fill = TITLE_FILL
    sheet.cell(title_row, 1).font = Font(bold=True, color="FFFFFF", size=18)

    # Branch names (each over its 2 columns), then დღე / ღამე
    sheet.append([None] + [cell for _, name in branches for cell in (name, None)])
    for i in range(len(branches)):
        sheet.merge_cells(start_row=sheet.max_row, start_column=2 + 2 * i,
                          end_row=sheet.max_row, end_column=3 + 2 * i)
    sheet.append(["თარიღი"] + ["დღე", "ღამე"] * len(branches))
    for row in (sheet.max_row - 1, sheet.max_row):
        for cell in sheet[row]:
            cell.font = Font(bold=True)

    # One row per shift date
    for d in days:
        row = [d.strftime("%d.%m.%Y")]
        for branch_id, _ in branches:
            row += [shift_value(shifts, data_range, branch_id, d, "day"),
                    shift_value(shifts, data_range, branch_id, d, "night")]
        sheet.append(row)
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

        # One sheet per branch: units per product per calendar day
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

        # Shift sheet: day / night GEL per branch
        shifts, data_range = load_shifts(cur)
        sheet = wb.create_sheet("ცვლები")
        sheet.column_dimensions["A"].width = 14
        for rule in SHIFT_RULES:
            sheet.append([rule])
            row = sheet.max_row
            sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)
            sheet.cell(row, 1).font = NOTE_FONT
            sheet.cell(row, 1).fill = NOTE_FILL
            sheet.cell(row, 1).alignment = Alignment(wrap_text=True, vertical="center")
            sheet.row_dimensions[row].height = 40
        sheet.append([])
        first_day = min(first for first, _ in data_range.values())
        last_day = max(last for _, last in data_range.values())
        year, month = first_day.year, first_day.month
        while (year, month) <= (last_day.year, last_day.month):
            write_shift_month(sheet, year, month, branches, shifts, data_range)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    Path(path).parent.mkdir(exist_ok=True)
    wb.save(path)


if __name__ == "__main__":
    build_report("reports/wolt_report.xlsx")
    print("Saved reports/wolt_report.xlsx")