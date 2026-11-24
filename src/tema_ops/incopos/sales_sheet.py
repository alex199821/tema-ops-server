"""Writes each branch's IncoPOS sales into its tab of the Google Sheet, in Nino's Sheet7 layout.

One tab per branch, built month by month, newest month first. For each month:
1. get that month's prices from the database (each product's first receipt of the month,
   IncoPOS's price without VAT) and write them into the sheet as plain numbers
2. write that month's sales (how many of each product per day) as plain numbers
3. go on to the next month

Each month is a block: a title row, the products in sections by IncoPOS group (ყავა, მზა
პროდუქცია…), each section's ნავაჭრი and მოგება rows, and the month's totals. Column A says
which month a row belongs to; the filter on column A shows one month at a time (the newest
after every run).

Columns: თვითღირებულება (from the თვითღირებულებები tab) | გაყიდვის ფასი | მოგება |
days 1-15 | გაყიდული | შემოსავალი | მოგება | days 16-31 | გაყიდული | შემოსავალი | მოგება
Nino's formulas: შემოსავალი = გაყიდული × ფასი, მოგება = გაყიდული × (ფასი − თვითღირებულება).
A day = 21:00 the evening before -> 21:00, like the cash book (night + day shift).

The tab is rewritten on every run. Runs after daily_update.py.
Needs SALES_SHEET_ID, and SALES_SHEET_TAB_<IncoPOS location id> for each branch to write.

Usage: uv run python src/tema_ops/incopos/sales_sheet.py
"""
import datetime
import os
from decimal import Decimal

import google.auth
import gspread
import psycopg
from dotenv import find_dotenv, load_dotenv
from gspread.utils import rowcol_to_a1

COSTS_TAB = "თვითღირებულებები"           # A = product, B = cost; people keep it, the robot only reads it
MONTHS = ["იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი", "ივლისი",
          "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი"]
NO_GROUP = "სხვა"                        # section for a product that has no group in IncoPOS

# Columns (Nino's Sheet7): A = month (for the filter), B = product, C = cost, D = price, E = profit
# per item, F..T = days 1-15, U empty, V/W/X = გაყიდული/შემოსავალი/მოგება, Y empty,
# Z..AO = days 16-31, AP empty, AQ/AR/AS = გაყიდული/შემოსავალი/მოგება
DAY_COLUMN = {d: 5 + d if d <= 15 else 10 + d for d in range(1, 32)}
BLOCKS = [(1, 15, 22, 23, 24), (16, 31, 43, 44, 45)]  # days from, to, then the 3 total columns
GAPS = (21, 25, 42)
WIDTH = 45

QTY = {"numberFormat": {"type": "NUMBER", "pattern": "0;-0;;@"}}           # 0 shows as empty
MONEY = {"numberFormat": {"type": "NUMBER", "pattern": "0.00;-0.00;;@"}}
BOLD = {"textFormat": {"bold": True}}
GREY_TEXT = {"textFormat": {"foregroundColor": {"red": 0.5, "green": 0.5, "blue": 0.5}}}
TITLE = {"red": 0.85, "green": 0.85, "blue": 0.85}       # month title rows
YELLOW = {"red": 1, "green": 0.8, "blue": 0}             # ნავაჭრი rows (colours from Nino's file)
GREEN = {"red": 0, "green": 1, "blue": 0}                # მოგება rows
DARK_GREEN = {"red": 0.2, "green": 0.6, "blue": 0.4}     # the month's totals

# A day is like the cash book: 21:00 the evening before -> 21:00 (night + day shift).
# Adding 3 hours moves 21:00 to midnight, so ::date gives the day.
DAY = "(s.paid_at + interval '3 hours')::date"

# The months that have finished days, newest first. The newest receipt's day is still going on
# (or not fully loaded), so it doesn't count yet.
MONTHS_SQL = f"""
SELECT DISTINCT date_trunc('month', {DAY})::date
FROM incopos.sales s
WHERE s.location_id = %(loc)s
  AND {DAY} < (SELECT (max(paid_at) + interval '3 hours')::date FROM incopos.sales WHERE location_id = %(loc)s)
ORDER BY 1 DESC
"""

# The order of sections and products, the same in every month: biggest section first, then most sold
ORDER_SQL = """
SELECT coalesce(g.name, %(no_group)s) AS group_name, i.name,
       sum(l.quantity * l.price) AS paid, sum(l.quantity) AS sold
FROM incopos.sale_lines l
JOIN incopos.items i ON i.id = l.item_id
LEFT JOIN incopos.item_groups g ON g.id = i.group_id
WHERE l.location_id = %(loc)s
GROUP BY 1, 2
"""

# 1. One month's prices: each product's first receipt of the month, IncoPOS's price without VAT
#    (Price − Vat, both per item, as on the receipt line). DISTINCT ON keeps only that first line.
PRICES_SQL = f"""
SELECT DISTINCT ON (i.name)
       i.name,
       (d->>'Price')::numeric - (d->>'Vat')::numeric AS price
FROM incopos.sales s
CROSS JOIN LATERAL jsonb_array_elements(s.raw->'Details') AS d
JOIN incopos.items i ON i.id = (d->>'ItemId')::int
WHERE s.location_id = %(loc)s AND {DAY} >= %(start)s AND {DAY} < %(end)s
ORDER BY i.name, s.paid_at
"""

# 2. One month's sales: how many of each product per day (finished days only)
SALES_SQL = f"""
SELECT i.name, {DAY} AS day, sum(l.quantity) AS sold
FROM incopos.sale_lines l
JOIN incopos.sales s ON s.location_id = l.location_id AND s.id = l.sale_id
JOIN incopos.items i ON i.id = l.item_id
WHERE l.location_id = %(loc)s AND {DAY} >= %(start)s AND {DAY} < %(end)s
  AND {DAY} < (SELECT (max(paid_at) + interval '3 hours')::date FROM incopos.sales WHERE location_id = %(loc)s)
GROUP BY 1, 2
"""

NOTES = {
    "month": "თვის ასარჩევად დააჭირეთ ამ სვეტის ფილტრს ▼: Clear, მონიშნეთ თვე, OK.\n"
             "ყოველ ღამე ფილტრი ბოლო თვეზე დგება.",
    "product": "დღე = წინა დღის 21:00-დან ამ დღის 21:00-მდე (ღამის და დღის ცვლა), როგორც სალაროს წიგნში.\n"
               "ეს ჩანართი ყოველ ღამე IncoPOS-ის მონაცემებით ახლდება; აქ ხელით შეცვლილი წაიშლება.",
    "cost": "ჩანართიდან „თვითღირებულებები“.",
    "price": "IncoPOS-ის ფასი დღგ-ის გარეშე (ჩეკის ფასი − დღგ, ორივე IncoPOS-დან), "
             "ამ თვის პირველი ჩეკიდან. მთელი თვე ამ ფასით ითვლება.",
    "unit_profit": "ერთ ცალზე: გაყიდვის ფასი − თვითღირებულება.",
    "money": "გაყიდული × გაყიდვის ფასი",
    "profit": "გაყიდული × მოგება ერთ ცალზე. ცარიელია, თუ თვითღირებულება არ აქვს.",
}


def column(c: int) -> str:
    """3 -> "C", 27 -> "AA"."""
    return "".join(ch for ch in rowcol_to_a1(1, c) if ch.isalpha())


def month_label(month: datetime.date) -> str:
    return f"{MONTHS[month.month - 1]} {month.year}"


def next_month(month: datetime.date) -> datetime.date:
    return (month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)


def number(value):
    value = Decimal(str(value))
    return int(value) if value == value.to_integral_value() else float(value)


class Tab:
    """The rows of one branch tab, and its formatting, built month by month."""

    def __init__(self):
        self.grid, self.notes, self.styles, self.merges = [], {}, [], []

    def new_row(self, month_text=""):
        self.grid.append([month_text] + [""] * (WIDTH - 1))
        return len(self.grid), self.grid[-1]

    def headings(self):
        """Row 1: headings, day numbers, and the filter buttons."""
        _, row = self.new_row("თვე")
        row[1:5] = ["პროდუქტი", "თვითღირებულება", "გაყიდვის ფასი", "მოგება"]
        for d, c in DAY_COLUMN.items():
            row[c - 1] = d
        for *_, c_sold, c_money, c_profit in BLOCKS:
            row[c_sold - 1], row[c_money - 1], row[c_profit - 1] = "გაყიდული", "შემოსავალი", "მოგება"
            self.notes[1, c_money], self.notes[1, c_profit] = NOTES["money"], NOTES["profit"]
        for c, key in ((1, "month"), (2, "product"), (3, "cost"), (4, "price"), (5, "unit_profit")):
            self.notes[1, c] = NOTES[key]

    def month(self, month, prices: dict, sold: dict, groups: list, products: dict):
        """One month's block. prices = {product: price without VAT}, sold = {(product, day): how many}."""
        label = month_label(month)
        C = f"'{COSTS_TAB}'!"
        r, row = self.new_row(label)
        row[1] = label
        self.styles.append((r, 2, r, WIDTH, {"backgroundColor": TITLE, "textFormat": {"bold": True, "fontSize": 12}}))

        sections = []
        for group in groups:
            names = [n for n in products[group] if any(p == n for p, _ in sold)]  # sold this month
            if not names:
                continue
            top = len(self.grid) + 1
            for name in names:
                r, row = self.new_row(label)
                row[1] = name
                row[2] = f'=IFNA(VLOOKUP(B{r},{C}$A:$B,2,FALSE),"")'
                row[3] = number(prices[name]) if name in prices else ""
                row[4] = f'=IF(C{r}="","",D{r}-C{r})'
                for (n, day), count in sold.items():
                    if n == name:
                        row[DAY_COLUMN[day.day] - 1] = number(count)
                for d1, d2, c_sold, c_money, c_profit in BLOCKS:
                    row[c_sold - 1] = f"=SUM({column(DAY_COLUMN[d1])}{r}:{column(DAY_COLUMN[d2])}{r})"
                    row[c_money - 1] = f"={column(c_sold)}{r}*D{r}"
                    row[c_profit - 1] = f'=IF(E{r}="","",{column(c_sold)}{r}*E{r})'
            bottom = len(self.grid)
            self.styles += [(top, 2, bottom, 2, BOLD), (top, 3, bottom, 5, MONEY)]
            for *_, c_sold, c_money, c_profit in BLOCKS:
                self.styles += [(top, c_sold, bottom, c_sold, QTY), (top, c_money, bottom, c_profit, MONEY)]

            pair = []
            for kind, unit, fill, total in (("ნავაჭრი", "D", YELLOW, 3), ("მოგება", "E", GREEN, 4)):
                r, row = self.new_row(label)
                row[1] = f"{kind} ({group})"
                for c in DAY_COLUMN.values():
                    row[c - 1] = f"=SUMPRODUCT({column(c)}{top}:{column(c)}{bottom},${unit}${top}:${unit}${bottom})"
                for block in BLOCKS:
                    c = column(block[total])
                    row[block[total] - 1] = f"=SUM({c}{top}:{c}{bottom})"
                self.styles.append((r, 2, r, WIDTH, {"backgroundColor": fill, **BOLD, **MONEY}))
                self.merges.append(r)
                pair.append(r)
            sections.append(pair)
            self.new_row(label)  # an empty row between sections

        for kind, i, total in (("ნავაჭრი", 0, 3), ("მოგება", 1, 4)):
            r, row = self.new_row(label)
            row[1] = f"{kind} (საერთო) — {label}"
            for c in [*DAY_COLUMN.values(), *(b[total] for b in BLOCKS)]:
                row[c - 1] = "=" + "+".join(f"{column(c)}{pair[i]}" for pair in sections)
            self.styles.append((r, 2, r, WIDTH, {"backgroundColor": DARK_GREEN, **BOLD, **MONEY}))
            self.merges.append(r)
        self.new_row(label)  # space before the next (older) month

    def requests(self, sheet_id: int, newest: str):
        """The formatting, and the filter that shows only the newest month."""
        rows = len(self.grid)
        styles = [(1, 1, 1, WIDTH, BOLD), (2, 1, rows, 1, GREY_TEXT), *self.styles]
        out = [_style(sheet_id, *s) for s in styles]
        out += [{"mergeCells": {"range": _range(sheet_id, r, 2, r, 5), "mergeType": "MERGE_ALL"}} for r in self.merges]
        out += [_note(sheet_id, r, c, text) for (r, c), text in self.notes.items()]
        widths = {1: 110, 2: 200, 3: 110, 4: 100, 5: 70, **{c: 12 for c in GAPS}}
        for *_, c_sold, c_money, c_profit in BLOCKS:
            widths.update({c_sold: 75, c_money: 90, c_profit: 90})
        out += [_width(sheet_id, c, widths.get(c, 38)) for c in range(1, WIDTH + 1)]
        hidden = sorted({row[0] for row in self.grid[1:]} - {newest})
        out.append({"setBasicFilter": {"filter": {
            "range": _range(sheet_id, 1, 1, rows, WIDTH),
            "filterSpecs": [{"columnIndex": 0, "filterCriteria": {"hiddenValues": hidden}}]}}})
        return out


def build_tab(conn, location_id: int) -> tuple[Tab, list]:
    """Builds the branch tab month by month, newest first. Returns (tab, months)."""
    order = conn.execute(ORDER_SQL, {"loc": location_id, "no_group": NO_GROUP}).fetchall()
    group_paid, products = {}, {}
    for group, name, paid, sold in order:
        group_paid[group] = group_paid.get(group, Decimal(0)) + paid
        products.setdefault(group, []).append((sold, name))
    groups = sorted(group_paid, key=lambda g: -group_paid[g])          # biggest section first
    products = {g: [n for _, n in sorted(items, key=lambda x: (-x[0], x[1]))] for g, items in products.items()}

    months = [m for (m,) in conn.execute(MONTHS_SQL, {"loc": location_id}).fetchall()]
    tab = Tab()
    tab.headings()
    for month in months:
        when = {"loc": location_id, "start": month, "end": next_month(month)}
        prices = dict(conn.execute(PRICES_SQL, when).fetchall())                   # 1. this month's prices
        sold = {(n, d): s for n, d, s in conn.execute(SALES_SQL, when).fetchall()}  # 2. this month's sales
        tab.month(month, prices, sold, groups, products)                            # 3. write the block
    return tab, months


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


def _reset(sheet_id, rows):
    """Empties the tab completely (values, colours, notes, merges, dropdowns) and sets its size.
    The month filter isn't cleared here: setBasicFilter replaces it afterwards."""
    return [
        {"unmergeCells": {"range": {"sheetId": sheet_id}}},
        {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {
                "rowCount": rows, "columnCount": WIDTH, "frozenRowCount": 1, "frozenColumnCount": 5}},
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
            tab, months = build_tab(conn, location_id)
            if not months:
                print(f"{tab_name}: no sales yet, skipped")
                continue
            view = sheet.worksheet(tab_name)
            sheet.batch_update({"requests": _reset(view.id, len(tab.grid))})
            view.update(tab.grid, "A1", value_input_option="USER_ENTERED")
            sheet.batch_update({"requests": tab.requests(view.id, month_label(months[0]))})
            print(f"{tab_name}: {len(tab.grid)} rows, {len(months)} months, showing {month_label(months[0])}")

            # The hidden data tab of an earlier version isn't used any more
            try:
                sheet.del_worksheet(sheet.worksheet(f"{location_name} — მონაცემები"))
                print(f"deleted the old tab {location_name} — მონაცემები")
            except gspread.WorksheetNotFound:
                pass


if __name__ == "__main__":
    main()
