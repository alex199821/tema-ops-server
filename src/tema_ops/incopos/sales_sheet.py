"""Writes each branch's IncoPOS sales to the Google Sheet, in Nino's Sheet7 layout.

Tabs:
- the branch tab (one per branch): ONE month at a time, picked from the dropdown in B1.
  Products in sections by IncoPOS group (ყავა, მზა პროდუქცია…), days 1-15 and 16-31 in
  half-month blocks, each with გაყიდული / შემოსავალი / მოგება.
- "<branch> — მონაცემები" (hidden, one per branch), written by the robot:
  A:D  how many of each product were sold per day
  F:H  each product's price without VAT per month (from IncoPOS)
  J:K  the months for the dropdown
- "თვითღირებულებები": product | cost. People keep it; the robot never writes to it.

Where the numbers come from:
- გაყიდული per day: the IncoPOS receipts. A day = 21:00 the evening before -> 21:00,
  like the cash book (night + day shift).
- გაყიდვის ფასი: IncoPOS's own price without VAT (line price − line VAT) on the product's
  first receipt of the month. The whole month uses that price.
- თვითღირებულება: from the თვითღირებულებები tab.
- შემოსავალი = გაყიდული × ფასი, მოგება = გაყიდული × (ფასი − თვითღირებულება)

The branch tab and its data tab are rewritten on every run (B1 goes back to the newest month).
Runs after daily_update.py. Needs SALES_SHEET_ID, and SALES_SHEET_TAB_<IncoPOS location id>
for each branch to write.

Usage: uv run python src/tema_ops/incopos/sales_sheet.py
"""
import datetime
import os
from collections import defaultdict
from decimal import Decimal

import google.auth
import gspread
import psycopg
from dotenv import find_dotenv, load_dotenv
from gspread.utils import rowcol_to_a1

COSTS_TAB = "თვითღირებულებები"           # A = product, B = cost; people keep it
MONTHS = ["იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი", "ივლისი",
          "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი"]
NO_GROUP = "სხვა"                        # section for a product that has no group in IncoPOS

# The branch tab's columns (Nino's Sheet7): B = product, C = cost, D = price, E = profit per item,
# F..T = days 1-15, U empty, V/W/X = გაყიდული/შემოსავალი/მოგება, Y empty,
# Z..AO = days 16-31, AP empty, AQ/AR/AS = გაყიდული/შემოსავალი/მოგება
DAY_COLUMN = {d: 5 + d if d <= 15 else 10 + d for d in range(1, 32)}
BLOCKS = [(1, 15, 22, 23, 24), (16, 31, 43, 44, 45)]  # days from, to, then the 3 total columns
GAPS = (21, 25, 42)
WIDTH = 45
HEAD = 3  # the row with the dates

QTY = {"numberFormat": {"type": "NUMBER", "pattern": "0;-0;;@"}}           # 0 shows as empty
MONEY = {"numberFormat": {"type": "NUMBER", "pattern": "0.00;-0.00;;@"}}
DATE = {"numberFormat": {"type": "DATE", "pattern": "dd.mm"}}
FULL_DATE = {"numberFormat": {"type": "DATE", "pattern": "dd.mm.yyyy"}}
BOLD = {"textFormat": {"bold": True}}
GREY = {"red": 0.5, "green": 0.5, "blue": 0.5}
PICK = {"red": 1, "green": 1, "blue": 0}                 # the month dropdown
YELLOW = {"red": 1, "green": 0.8, "blue": 0}             # ნავაჭრი rows (colours from Nino's file)
GREEN = {"red": 0, "green": 1, "blue": 0}                # მოგება rows
DARK_GREEN = {"red": 0.2, "green": 0.6, "blue": 0.4}     # the totals at the bottom

# How many of each product were sold per day. A day is like the cash book: 21:00 the evening
# before -> 21:00 (night + day shift); adding 3 hours moves 21:00 to midnight, so ::date gives the day.
SALES_SQL = """
SELECT (s.paid_at + interval '3 hours')::date AS day,
       g.name AS group_name,                 -- the product's group in IncoPOS, e.g. ყავა
       i.name,
       sum(l.quantity) AS sold,
       sum(l.quantity * l.price) AS paid     -- only to put the biggest sections first
FROM incopos.sale_lines l
JOIN incopos.sales s ON s.location_id = l.location_id AND s.id = l.sale_id
JOIN incopos.items i ON i.id = l.item_id
LEFT JOIN incopos.item_groups g ON g.id = i.group_id   -- LEFT: a product without a group still counts
WHERE l.location_id = %s
  -- finished days only: the newest receipt's day is still going on (or not fully loaded)
  AND (s.paid_at + interval '3 hours')::date <
      (SELECT (max(paid_at) + interval '3 hours')::date FROM incopos.sales WHERE location_id = %s)
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 3
"""

# One price per product per month: IncoPOS's price without VAT (Price − Vat, both per item, as on
# the receipt line) on the product's first receipt of the month. DISTINCT ON keeps only that one line.
PRICES_SQL = """
SELECT DISTINCT ON (1, 2)
       date_trunc('month', s.paid_at + interval '3 hours')::date AS month,
       i.name,
       (d->>'Price')::numeric - (d->>'Vat')::numeric AS price
FROM incopos.sales s
CROSS JOIN LATERAL jsonb_array_elements(s.raw->'Details') AS d
JOIN incopos.items i ON i.id = (d->>'ItemId')::int
WHERE s.location_id = %s
ORDER BY 1, 2, s.paid_at
"""

NOTES = {
    "pick": "აირჩიეთ თვე ამ უჯრის ისრით: მთელი ჩანართი იმ თვეს აჩვენებს.\n"
            "დღე = წინა დღის 21:00-დან ამ დღის 21:00-მდე (ღამის და დღის ცვლა), როგორც სალაროს წიგნში.\n"
            "მონაცემები IncoPOS-დან მოდის ყოველ ღამე. აქ ხელით შეცვლილი წაიშლება.",
    "first_day": "არჩეული თვის პირველი დღე (B1-დან).",
    "cost": "ჩანართიდან „თვითღირებულებები“.",
    "price": "IncoPOS-ის ფასი დღგ-ის გარეშე (ჩეკის ფასი − დღგ, ორივე IncoPOS-დან), "
             "ამ თვის პირველი ჩეკიდან. მთელი თვე ამ ფასით ითვლება.",
    "unit_profit": "ერთ ცალზე: გაყიდვის ფასი − თვითღირებულება. ცარიელია, თუ თვითღირებულება არ აქვს.",
    "money": "გაყიდული × გაყიდვის ფასი",
    "profit": "გაყიდული × მოგება ერთ ცალზე. ცარიელია, თუ თვითღირებულება არ აქვს.",
}


def column(c: int) -> str:
    """3 -> "C", 27 -> "AA"."""
    return "".join(ch for ch in rowcol_to_a1(1, c) if ch.isalpha())


def month_label(day: datetime.date) -> str:
    return f"{MONTHS[day.month - 1]} {day.year}"


def number(value):
    value = Decimal(str(value))
    return int(value) if value == value.to_integral_value() else float(value)


def build_data(sales, prices):
    """The hidden data tab: sold per day (A:D), price per month (F:H), months for the dropdown (J:K).
    Returns (values, months), months newest first."""
    values = [["თარიღი", "პროდუქტი", "ჯგუფი", "გაყიდული", "",
               "თვე", "პროდუქტი", "ფასი დღგ-ის გარეშე", "", "თვე", "პირველი დღე"]]
    for day, group, name, sold, _ in sales:
        values.append([day.isoformat(), name, group or NO_GROUP, number(sold)] + [""] * 7)

    def row(i):  # the i-th line under the headings, added if the day rows are fewer
        while len(values) < i + 2:
            values.append([""] * 11)
        return values[i + 1]

    for i, (month, name, price) in enumerate(sorted(prices, key=lambda p: (-p[0].toordinal(), p[1]))):
        row(i)[5:8] = [month_label(month), name, number(price)]
    months = sorted({day.replace(day=1) for day, *_ in sales}, reverse=True)
    for i, month in enumerate(months):
        row(i)[9:11] = [month_label(month), month.isoformat()]
    return values, months


def build_view(sales, months, data_tab: str, view_id: int):
    """The branch tab: the newest month in B1, everything else formulas. Returns (values, requests)."""
    D, C = f"'{data_tab}'!", f"'{COSTS_TAB}'!"
    group_of, group_paid, sold_all = {}, defaultdict(Decimal), defaultdict(Decimal)
    for _, group, name, sold, paid in sales:
        group_of[name] = group or NO_GROUP
        group_paid[group_of[name]] += paid
        sold_all[name] += sold
    groups = sorted(group_paid, key=lambda g: -group_paid[g])  # most money first

    grid, notes, styles, merges = [], {}, [], []

    def new_row():
        grid.append([""] * WIDTH)
        return len(grid), grid[-1]

    def put(row, c, value):
        row[c - 1] = value

    # Row 1: the month dropdown (B1) and the month's first day (C1)
    _, row = new_row()
    put(row, 2, month_label(months[0]))
    put(row, 3, f"=VLOOKUP($B$1,{D}$J:$K,2,FALSE)")
    notes[1, 2], notes[1, 3] = NOTES["pick"], NOTES["first_day"]
    new_row()

    # Row 3: headings and the month's dates
    _, row = new_row()
    for c, title, note in ((3, "თვითღირებულება", "cost"), (4, "გაყიდვის ფასი", "price"), (5, "მოგება", "unit_profit")):
        put(row, c, title)
        notes[HEAD, c] = NOTES[note]
    for d in range(1, 32):
        day = "$C$1" if d == 1 else f"$C$1+{d - 1}"
        put(row, DAY_COLUMN[d], f"={day}" if d <= 28 else f'=IF(MONTH({day})=MONTH($C$1),{day},"")')
    for *_, c_sold, c_money, c_profit in BLOCKS:
        put(row, c_sold, "გაყიდული")
        put(row, c_money, "შემოსავალი")
        put(row, c_profit, "მოგება")
        notes[HEAD, c_money], notes[HEAD, c_profit] = NOTES["money"], NOTES["profit"]

    sections = []  # (ნავაჭრი row, მოგება row) of each section
    for group in groups:
        top = len(grid) + 1
        for name in sorted((n for n in group_of if group_of[n] == group), key=lambda n: (-sold_all[n], n)):
            r, row = new_row()
            put(row, 2, name)
            put(row, 3, f'=IFNA(VLOOKUP($B{r},{C}$A:$B,2,FALSE),"")')
            put(row, 4, f"=SUMIFS({D}$H:$H,{D}$F:$F,$B$1,{D}$G:$G,$B{r})")   # this month's price
            put(row, 5, f'=IF(OR(C{r}="",D{r}=0),0,D{r}-C{r})')              # 0 (shown empty) without a cost
            for d in range(1, 32):
                c = column(DAY_COLUMN[d])
                put(row, DAY_COLUMN[d], f'=IF({c}${HEAD}="","",SUMIFS({D}$D:$D,{D}$B:$B,$B{r},{D}$A:$A,{c}${HEAD}))')
            for d1, d2, c_sold, c_money, c_profit in BLOCKS:
                put(row, c_sold, f"=SUM({column(DAY_COLUMN[d1])}{r}:{column(DAY_COLUMN[d2])}{r})")
                put(row, c_money, f"={column(c_sold)}{r}*$D{r}")
                put(row, c_profit, f'=IF($C{r}="","",{column(c_sold)}{r}*$E{r})')
        bottom = len(grid)
        styles += [(top, 2, bottom, 2, BOLD), (top, 3, bottom, 5, MONEY),
                   (top, DAY_COLUMN[1], bottom, DAY_COLUMN[31], QTY)]
        for *_, c_sold, c_money, c_profit in BLOCKS:
            styles += [(top, c_sold, bottom, c_sold, QTY), (top, c_money, bottom, c_profit, MONEY)]

        pair = []
        for kind, unit, fill, total in (("ნავაჭრი", "D", YELLOW, 3), ("მოგება", "E", GREEN, 4)):
            r, row = new_row()
            put(row, 2, f"{kind} ({group})")
            for d in range(1, 32):
                c = column(DAY_COLUMN[d])
                put(row, DAY_COLUMN[d], f'=IF({c}${HEAD}="","",SUMPRODUCT({c}{top}:{c}{bottom},${unit}${top}:${unit}${bottom}))')
            for block in BLOCKS:
                c = column(block[total])
                put(row, block[total], f"=SUM({c}{top}:{c}{bottom})")
            styles.append((r, 1, r, WIDTH, {"backgroundColor": fill, **BOLD, **MONEY}))
            merges.append(r)
            pair.append(r)
        sections.append(pair)
        new_row()  # an empty row between sections

    for kind, i, total in (("ნავაჭრი", 0, 3), ("მოგება", 1, 4)):
        r, row = new_row()
        put(row, 2, f"{kind} (საერთო)")
        for c in [DAY_COLUMN[d] for d in range(1, 32)] + [b[total] for b in BLOCKS]:
            put(row, c, "=" + "+".join(f"{column(c)}{pair[i]}" for pair in sections))
        styles.append((r, 1, r, WIDTH, {"backgroundColor": DARK_GREEN, **BOLD, **MONEY}))
        merges.append(r)

    styles = [(HEAD, 1, HEAD, WIDTH, BOLD), (HEAD, DAY_COLUMN[1], HEAD, DAY_COLUMN[31], DATE),
              (1, 2, 1, 2, {"backgroundColor": PICK, "textFormat": {"bold": True, "fontSize": 12}}),
              (1, 3, 1, 3, {**FULL_DATE, "textFormat": {"foregroundColor": GREY}}),
              *styles]
    requests = [_style(view_id, *s) for s in styles]
    requests += [{"mergeCells": {"range": _range(view_id, r, 2, r, 5), "mergeType": "MERGE_ALL"}} for r in merges]
    requests += [_note(view_id, r, c, text) for (r, c), text in notes.items()]
    requests.append({"setDataValidation": {"range": _range(view_id, 1, 2, 1, 2), "rule": {
        "condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": f"={D}$J$2:$J${len(months) + 1}"}]},
        "showCustomUi": True, "strict": True}}})
    widths = {1: 12, 2: 200, 3: 110, 4: 110, 5: 80, **{c: 12 for c in GAPS}}
    for *_, c_sold, c_money, c_profit in BLOCKS:
        widths.update({c_sold: 75, c_money: 90, c_profit: 90})
    requests += [_width(view_id, c, widths.get(c, 42)) for c in range(1, WIDTH + 1)]
    return grid, requests


def data_requests(data_id: int, rows: int):
    """Formats for the hidden data tab, and hiding it."""
    return [
        _style(data_id, 1, 1, 1, 11, BOLD),
        _style(data_id, 2, 1, rows, 1, FULL_DATE),
        _style(data_id, 2, 8, rows, 8, MONEY),
        _style(data_id, 2, 11, rows, 11, FULL_DATE),
        _width(data_id, 2, 200), _width(data_id, 7, 200),
        {"updateSheetProperties": {"properties": {"sheetId": data_id, "hidden": True}, "fields": "hidden"}},
    ]


def _range(sheet_id, r1, c1, r2, c2):
    """Rows and columns count from 1 and include both ends, like in the sheet."""
    return {"sheetId": sheet_id, "startRowIndex": r1 - 1, "endRowIndex": r2,
            "startColumnIndex": c1 - 1, "endColumnIndex": c2}


def _style(sheet_id, r1, c1, r2, c2, cell_format):
    return {"repeatCell": {"range": _range(sheet_id, r1, c1, r2, c2),
                           "cell": {"userEnteredFormat": cell_format},
                           "fields": ",".join(f"userEnteredFormat.{key}" for key in cell_format)}}


def _note(sheet_id, r, c, text):
    return {"updateCells": {"range": _range(sheet_id, r, c, r, c),
                            "rows": [{"values": [{"note": text}]}], "fields": "note"}}


def _width(sheet_id, c, pixels):
    return {"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c - 1, "endIndex": c},
        "properties": {"pixelSize": pixels}, "fields": "pixelSize"}}


def _reset(sheet_id, rows, columns, frozen_rows, frozen_columns):
    """Empties a tab completely (values, colours, notes, merges, dropdowns) and sets its size."""
    return [
        {"unmergeCells": {"range": {"sheetId": sheet_id}}},
        {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {
                "rowCount": rows, "columnCount": columns,
                "frozenRowCount": frozen_rows, "frozenColumnCount": frozen_columns}},
            "fields": "gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)"}},
    ]


def main():
    load_dotenv(find_dotenv(usecwd=True))  # the .env of the folder it's run from
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sheet = gspread.authorize(creds).open_by_key(os.environ["SALES_SHEET_ID"])
    with psycopg.connect(os.environ["INCOPOS_DATABASE_URL"]) as conn:
        for location_id, location_name in conn.execute("SELECT id, name FROM incopos.locations ORDER BY id").fetchall():
            tab_name = os.environ.get(f"SALES_SHEET_TAB_{location_id}")
            if not tab_name:
                continue  # this branch has no tab yet
            sales = conn.execute(SALES_SQL, (location_id, location_id)).fetchall()
            if not sales:
                print(f"{tab_name}: no sales yet, skipped")
                continue
            prices = conn.execute(PRICES_SQL, (location_id,)).fetchall()

            data_name = f"{location_name} — მონაცემები"
            data_values, months = build_data(sales, prices)
            try:
                data = sheet.worksheet(data_name)
            except gspread.WorksheetNotFound:
                data = sheet.add_worksheet(data_name, rows=len(data_values), cols=11)
            view = sheet.worksheet(tab_name)
            view_values, view_requests = build_view(sales, months, data_name, view.id)

            sheet.batch_update({"requests": _reset(data.id, len(data_values), 11, 1, 0)
                                + _reset(view.id, len(view_values), WIDTH, HEAD, 5)})
            data.update(data_values, "A1", value_input_option="USER_ENTERED")
            view.update(view_values, "A1", value_input_option="USER_ENTERED")
            sheet.batch_update({"requests": data_requests(data.id, len(data_values)) + view_requests})
            print(f"{tab_name}: {len(view_values)} rows, {len(months)} months; "
                  f"{data_name}: {len(data_values) - 1} rows")


if __name__ == "__main__":
    main()
