"""Writes each branch's IncoPOS sales into its tab of the Google Sheet, in Nino's layout:

- one row per product, one column per day, in sections by IncoPOS group (ყავა, მზა პროდუქცია…)
- half-month blocks (1-15, 16-end of month), each followed by გაყიდული / შემოსავალი / მოგება
- under each section its ნავაჭრი and მოგება per day; at the bottom the totals of all sections

Where the numbers come from (the sheet says the same in its notes):
- a day = 21:00 the evening before -> 21:00, like the cash book (night + day shift)
- შემოსავალი = what customers really paid on the IncoPOS receipts, ÷ 1.18 (VAT)
- თვითღირებულება = from the costs tab, as a formula: an edit there shows here at once
- მოგება = შემოსავალი − გაყიდული × თვითღირებულება; empty when a product has no cost

The whole tab is rewritten on every run. Runs every night after daily_update.py.
Needs SALES_SHEET_ID, and SALES_SHEET_TAB_<IncoPOS location id> for each branch to write.

Usage: uv run python src/tema_ops/incopos/sales_sheet.py
"""
import datetime
import os
from collections import defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo

import google.auth
import gspread
import psycopg
from dotenv import load_dotenv
from gspread.utils import rowcol_to_a1 as a1

VAT = Decimal("1.18")
COSTS_TAB = "ფასები და თვითღირებულება"   # A = product, D = cost; people edit it by hand
FIRST_DAY_COLUMN = 6                     # F: A is empty, B-E = name, cost, price, profit per unit
NO_GROUP = "სხვა"                        # section for a product that has no group in IncoPOS
MONEY = {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}}
YELLOW = {"red": 1, "green": 0.8, "blue": 0}           # ნავაჭრი rows (colours from Nino's file)
GREEN = {"red": 0, "green": 1, "blue": 0}              # მოგება rows
DARK_GREEN = {"red": 0.2, "green": 0.6, "blue": 0.4}   # the totals at the bottom

# How many of each product were sold at each price, per day.
# A day is like the cash book: 21:00 the evening before -> 21:00 (night + day shift).
# Adding 3 hours moves 21:00 to midnight, so ::date gives the right day.
# (Line discounts are all 0 so far, so they are not used.)
SALES_SQL = """
SELECT (s.paid_at + interval '3 hours')::date AS day,
       g.name AS group_name,       -- the product's group in IncoPOS, e.g. ყავა
       i.name,
       l.price,                    -- per unit, VAT included
       sum(l.quantity) AS sold
FROM incopos.sale_lines l
JOIN incopos.sales s ON s.location_id = l.location_id AND s.id = l.sale_id
JOIN incopos.items i ON i.id = l.item_id
LEFT JOIN incopos.item_groups g ON g.id = i.group_id   -- LEFT: a product without a group still counts
WHERE l.location_id = %s
  -- finished days only: the newest receipt's day is still going on (or not fully loaded)
  AND (s.paid_at + interval '3 hours')::date <
      (SELECT (max(paid_at) + interval '3 hours')::date FROM incopos.sales WHERE location_id = %s)
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2, 3, 4
"""

# Today's price of each product = the price on its newest receipt (VAT included)
PRICES_SQL = """
SELECT DISTINCT ON (i.name) i.name, l.price
FROM incopos.sale_lines l
JOIN incopos.sales s ON s.location_id = l.location_id AND s.id = l.sale_id
JOIN incopos.items i ON i.id = l.item_id
WHERE l.location_id = %s
ORDER BY i.name, s.paid_at DESC
"""

NOTES = {
    "updated": "დღე = წინა დღის 21:00-დან ამ დღის 21:00-მდე (ღამის და დღის ცვლა), როგორც სალაროს წიგნში.\n"
               "ეს ჩანართი ყოველ ღამე თავიდან იწერება IncoPOS-ის მონაცემებით, ამიტომ აქ ხელით შეცვლილი "
               "წაიშლება. თვითღირებულება შეცვალეთ ჩანართში „ფასები და თვითღირებულება“.",
    "cost": "ჩანართიდან „ფასები და თვითღირებულება“. იქ შეცვლილი თვითღირებულება აქაც მაშინვე ჩანს.",
    "price": "IncoPOS-ის ბოლო ფასი ÷ 1.18 (დღგ-ის გარეშე). შემოსავალი ამით არ ითვლება: "
             "ის რეალური ჩეკებიდან მოდის.",
    "unit_profit": "ერთ ცალზე: გაყიდვის ფასი − თვითღირებულება.",
    "money": "რეალურად გადახდილი თანხა IncoPOS-ის ჩეკებიდან ÷ 1.18 (დღგ-ის გარეშე). "
             "თუ ამ პერიოდში ფასი შეიცვალა, უჯრას შენიშვნა აქვს.",
    "profit": "შემოსავალი − გაყიდული × თვითღირებულება. ცარიელია, თუ პროდუქტს თვითღირებულება არ აქვს.",
    "section_profit": "მხოლოდ პროდუქტები, რომლებსაც თვითღირებულება აქვს. ყოველ ღამე თავიდან ითვლება.",
}


def read_sales(conn, location_id):
    return conn.execute(SALES_SQL, (location_id, location_id)).fetchall()


def read_prices(conn, location_id):
    return dict(conn.execute(PRICES_SQL, (location_id,)).fetchall())


def read_costs(costs_tab) -> dict:
    """{product: cost} from the costs tab. Products with an empty cost are left out."""
    costs = {}
    for row in costs_tab.get_all_values()[1:]:
        if len(row) >= 4 and row[0].strip() and row[3].strip():
            costs[row[0].strip()] = Decimal(row[3].strip().replace(",", "."))
    return costs


def half_months(first_day: datetime.date, last_day: datetime.date) -> list:
    """Nino's blocks: the 1st-15th and the 16th-end of each month, starting on the 1st."""
    blocks = []
    start = first_day.replace(day=1)
    while start <= last_day:
        if start.day == 1:
            end = start.replace(day=15)
        else:  # the last day of the month: the 1st of the next month minus one day
            end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
        blocks.append([start + datetime.timedelta(days=n) for n in range((end - start).days + 1)])
        start = end + datetime.timedelta(days=1)
    return blocks


def plan_columns(blocks):
    """Where everything goes: {day: column}, per block (days, გაყიდული, შემოსავალი, მოგება columns),
    the empty columns between blocks, and how many columns there are in all."""
    day_column, totals, gaps = {}, [], []
    column = FIRST_DAY_COLUMN
    for days in blocks:
        for day in days:
            day_column[day] = column
            column += 1
        gaps.append(column)                                  # an empty column, as in Nino's file
        totals.append((days, column + 1, column + 2, column + 3))
        gaps.append(column + 4)
        column += 5
    return day_column, totals, gaps, column - 1


def quantity(q: Decimal) -> str:
    """5.000 -> "5", 0.500 -> "0.5" (for the notes)."""
    return str(int(q)) if q == q.to_integral_value() else f"{q.normalize():f}"


def build_tab(sales, prices: dict, costs: dict, updated: datetime.datetime, sheet_id: int):
    """Returns (values, requests): the grid to write, and the formatting for it."""
    sold = defaultdict(Decimal)                          # (product, day) -> how many
    paid = defaultdict(Decimal)                          # (product, day) -> money, VAT included
    at_price = defaultdict(lambda: defaultdict(Decimal))  # (product, day) -> {price: how many}
    group_of = {}
    for day, group, name, price, count in sales:
        group_of[name] = group or NO_GROUP
        sold[name, day] += count
        paid[name, day] += count * price
        at_price[name, day][price] += count

    # Sections: most money first. Inside a section: most sold first.
    sold_in_all = defaultdict(Decimal)
    group_money = defaultdict(Decimal)
    for (name, day), count in sold.items():
        sold_in_all[name] += count
        group_money[group_of[name]] += paid[name, day]
    groups = sorted(group_money, key=lambda g: -group_money[g])
    products = {g: sorted((n for n in group_of if group_of[n] == g), key=lambda n: (-sold_in_all[n], n))
                for g in groups}

    last_day = max(day for _, day in sold)
    blocks = half_months(min(day for _, day in sold), last_day)
    day_column, totals, gaps, width = plan_columns(blocks)
    past_days = {day: column for day, column in day_column.items() if day <= last_day}

    grid = []
    notes = {}      # (row, column) -> note text
    styles = []     # (row from, column from, row to, column to, format)

    def new_row():
        grid.append([""] * width)
        return len(grid), grid[-1]

    def put(row, column, value):
        row[column - 1] = float(value) if isinstance(value, Decimal) else value

    # Row 1: the headings
    _, row = new_row()
    put(row, 2, f"განახლდა {updated:%d.%m.%Y %H:%M}")
    notes[1, 2] = NOTES["updated"]
    for column, title, note in ((3, "თვითღირებულება", "cost"), (4, "გაყიდვის ფასი", "price"),
                                (5, "მოგება", "unit_profit")):
        put(row, column, title)
        notes[1, column] = NOTES[note]
    for day, column in day_column.items():
        put(row, column, day.isoformat())
    for _, c_sold, c_money, c_profit in totals:
        put(row, c_sold, "გაყიდული")
        put(row, c_money, "შემოსავალი")
        put(row, c_profit, "მოგება")
        notes[1, c_money] = NOTES["money"]
        notes[1, c_profit] = NOTES["profit"]

    section_rows = []
    for group in groups:
        first_row = len(grid) + 1
        for name in products[group]:
            r, row = new_row()
            put(row, 2, name)
            put(row, 3, f"=IFNA(VLOOKUP($B{r},'{COSTS_TAB}'!$A:$D,4,FALSE),\"\")")
            if name in prices:
                put(row, 4, prices[name] / VAT)
            put(row, 5, f'=IF($C{r}="","",$D{r}-$C{r})')
            for day, column in past_days.items():
                if sold.get((name, day)):
                    put(row, column, sold[name, day])
            for days, c_sold, c_money, c_profit in totals:
                put(row, c_sold, f"=SUM({a1(r, day_column[days[0]])}:{a1(r, day_column[days[-1]])})")
                money = sum((paid.get((name, d), Decimal(0)) for d in days), Decimal(0))
                put(row, c_money, money / VAT)
                put(row, c_profit, f'=IF($C{r}="","",{a1(r, c_money)}-{a1(r, c_sold)}*$C{r})')
                # A price change inside the block: show how the money adds up
                mix = defaultdict(Decimal)
                for d in days:
                    for price, count in at_price.get((name, d), {}).items():
                        mix[price] += count
                if len(mix) > 1:
                    parts = " + ".join(f"{quantity(c)} × {p:.2f}" for p, c in sorted(mix.items()))
                    notes[r, c_money] = f"ფასი შეიცვალა:\n{parts} = {money:.2f} (დღგ-ით)\n÷ 1.18 = {money / VAT:.2f}"
        last_row = len(grid)

        # The section's ნავაჭრი and მოგება rows
        r_money, money_row = new_row()
        r_profit, profit_row = new_row()
        put(money_row, 2, f"ნავაჭრი ({group})")
        put(profit_row, 2, f"მოგება ({group})")
        notes[r_profit, 2] = NOTES["section_profit"]
        for day, column in past_days.items():
            money = sum((paid.get((n, day), Decimal(0)) for n in products[group]), Decimal(0))
            profit = sum((paid.get((n, day), Decimal(0)) / VAT - sold.get((n, day), Decimal(0)) * costs[n]
                          for n in products[group] if n in costs), Decimal(0))
            put(money_row, column, money / VAT)
            put(profit_row, column, profit)
        for _, _, c_money, c_profit in totals:
            put(money_row, c_money, f"=SUM({a1(first_row, c_money)}:{a1(last_row, c_money)})")
            put(profit_row, c_profit, f"=SUM({a1(first_row, c_profit)}:{a1(last_row, c_profit)})")
        styles.append((r_money, 1, r_money, width, {"backgroundColor": YELLOW, "textFormat": {"bold": True}, **MONEY}))
        styles.append((r_profit, 1, r_profit, width, {"backgroundColor": GREEN, "textFormat": {"bold": True}, **MONEY}))
        section_rows.append((r_money, r_profit))
        new_row()  # an empty row between sections

    # The totals of all sections
    r_money, money_row = new_row()
    r_profit, profit_row = new_row()
    put(money_row, 2, "ნავაჭრი (საერთო)")
    put(profit_row, 2, "მოგება (საერთო)")
    for column in [*past_days.values(), *(t[2] for t in totals)]:
        put(money_row, column, "=" + "+".join(a1(m, column) for m, _ in section_rows))
    for column in [*past_days.values(), *(t[3] for t in totals)]:
        put(profit_row, column, "=" + "+".join(a1(p, column) for _, p in section_rows))
    for r in (r_money, r_profit):
        styles.append((r, 1, r, width, {"backgroundColor": DARK_GREEN, "textFormat": {"bold": True}, **MONEY}))

    rows = len(grid)
    styles[:0] = [  # first, so the coloured rows above win where they overlap
        (2, 2, rows, 2, {"textFormat": {"bold": True}}),                     # product names
        (2, 3, rows, 5, MONEY),                                              # cost, price, profit
        *((2, c, rows, c, MONEY) for t in totals for c in (t[2], t[3])),     # შემოსავალი, მოგება
        (1, FIRST_DAY_COLUMN, 1, width, {"numberFormat": {"type": "DATE", "pattern": "dd.mm"}}),
    ]
    requests = [_style(sheet_id, *s) for s in styles]
    requests += [_note(sheet_id, r, c, text) for (r, c), text in notes.items()]
    merge_rows = [r for pair in section_rows for r in pair] + [r_money, r_profit]
    requests += [{"mergeCells": {"range": _range(sheet_id, r, 2, r, 5), "mergeType": "MERGE_ALL"}}
                 for r in merge_rows]
    requests.append(_width(sheet_id, 2, 200))           # product names
    requests += [_width(sheet_id, c, 20) for c in gaps]  # the empty columns between blocks
    return grid, requests


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


def _width(sheet_id, column, pixels):
    return {"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": column - 1, "endIndex": column},
        "properties": {"pixelSize": pixels}, "fields": "pixelSize"}}


def write_tab(sheet, tab, values, requests):
    """Empties the tab completely (values, colours, notes, merges), then writes it again."""
    sheet.batch_update({"requests": [
        {"unmergeCells": {"range": {"sheetId": tab.id}}},
        {"updateCells": {"range": {"sheetId": tab.id}, "fields": "*"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": tab.id, "gridProperties": {
                "rowCount": len(values), "columnCount": len(values[0]),
                "frozenRowCount": 1, "frozenColumnCount": 5}},
            "fields": "gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)"}},
    ]})
    tab.update(values, "A1", value_input_option="USER_ENTERED")
    sheet.batch_update({"requests": requests})


def main():
    load_dotenv()
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sheet = gspread.authorize(creds).open_by_key(os.environ["SALES_SHEET_ID"])
    costs = read_costs(sheet.worksheet(COSTS_TAB))
    updated = datetime.datetime.now(ZoneInfo("Asia/Tbilisi"))
    with psycopg.connect(os.environ["INCOPOS_DATABASE_URL"]) as conn:
        for (location_id,) in conn.execute("SELECT id FROM incopos.locations ORDER BY id").fetchall():
            tab_name = os.environ.get(f"SALES_SHEET_TAB_{location_id}")
            if not tab_name:
                continue  # this branch has no tab yet
            sales = read_sales(conn, location_id)
            if not sales:
                print(f"{tab_name}: no sales yet, skipped")
                continue
            tab = sheet.worksheet(tab_name)
            values, requests = build_tab(sales, read_prices(conn, location_id), costs, updated, tab.id)
            write_tab(sheet, tab, values, requests)
            print(f"{tab_name}: {len(values)} rows x {len(values[0])} columns written")


if __name__ == "__main__":
    main()
