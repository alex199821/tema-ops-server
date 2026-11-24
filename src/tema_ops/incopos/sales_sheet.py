"""Writes each branch's IncoPOS sales into its tab of the Google Sheet, in Nino's Sheet7 layout,
with the months side by side: the newest month first, older months to the right.

- Rows: every product the branch has sold, in sections by IncoPOS group (ყავა, მზა პროდუქცია…),
  each section followed by its ნავაჭრი (yellow) and მოგება (green) rows; the totals at the bottom.
- Columns: B = product, then one section per month:
  თვითღირებულება | გაყიდვის ფასი | მოგება | days 1-15 | გაყიდული შემოსავალი მოგება |
  days 16-31 | გაყიდული შემოსავალი მოგება. The newest month's columns are Nino's C..AS.

Built month by month, newest first. For each month:
1. get that month's prices from the database (each product's first receipt of the month,
   IncoPOS's price without VAT) and write them as plain numbers
2. write that month's sales (how many of each product per day) as plain numbers
3. go on to the next month

თვითღირებულება: the current month gets it from the თვითღირებულებები tab every night. Past months
keep the cost they already have in this tab (also one typed over by hand), so changing a cost
changes it only from the current month on.
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
HEAD = 2      # row 1 = month titles, row 2 = headings
SECTION = 43  # columns per month (Nino's C..AS)
STEP = SECTION + 1  # plus a dark column between months

QTY = {"numberFormat": {"type": "NUMBER", "pattern": "0;-0;;@"}}           # 0 shows as empty
MONEY = {"numberFormat": {"type": "NUMBER", "pattern": "0.00;-0.00;;@"}}
BOLD = {"textFormat": {"bold": True}}
TITLE = {"red": 0.85, "green": 0.85, "blue": 0.85}       # month title row
SEPARATOR = {"red": 0.4, "green": 0.4, "blue": 0.4}      # the column between months
YELLOW = {"red": 1, "green": 0.8, "blue": 0}             # ნავაჭრი rows (colours from Nino's file)
GREEN = {"red": 0, "green": 1, "blue": 0}                # მოგება rows
DARK_GREEN = {"red": 0.2, "green": 0.6, "blue": 0.4}     # the totals at the bottom

# A day is like the cash book: 21:00 the evening before -> 21:00 (night + day shift).
# Adding 3 hours moves 21:00 to midnight, so ::date gives the day.
DAY = "(s.paid_at + interval '3 hours')::date"
# The newest receipt's day is still going on (or not fully loaded), so it doesn't count yet
FINISHED = f"{DAY} < (SELECT (max(paid_at) + interval '3 hours')::date FROM incopos.sales WHERE location_id = %(loc)s)"

# The months that have finished days, newest first
MONTHS_SQL = f"""
SELECT DISTINCT date_trunc('month', {DAY})::date
FROM incopos.sales s
WHERE s.location_id = %(loc)s AND {FINISHED}
ORDER BY 1 DESC
"""

# Every product the branch has sold, with its group: sets the rows (biggest section first, then most sold)
ORDER_SQL = f"""
SELECT coalesce(g.name, %(no_group)s) AS group_name, i.name,
       sum(l.quantity * l.price) AS paid, sum(l.quantity) AS sold
FROM incopos.sale_lines l
JOIN incopos.sales s ON s.location_id = l.location_id AND s.id = l.sale_id
JOIN incopos.items i ON i.id = l.item_id
LEFT JOIN incopos.item_groups g ON g.id = i.group_id
WHERE l.location_id = %(loc)s AND {FINISHED}
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
WHERE l.location_id = %(loc)s AND {DAY} >= %(start)s AND {DAY} < %(end)s AND {FINISHED}
GROUP BY 1, 2
"""

NOTES = {
    "product": "დღე = წინა დღის 21:00-დან ამ დღის 21:00-მდე (ღამის და დღის ცვლა), როგორც სალაროს წიგნში.\n"
               "ეს ჩანართი ყოველ ღამე IncoPOS-ის მონაცემებით ახლდება: აქ ხელით შეცვლილი წაიშლება, "
               "გარდა გასული თვეების თვითღირებულებისა.",
    "cost": "მიმდინარე თვეში: ჩანართიდან „თვითღირებულებები“ (ყოველ ღამე).\n"
            "გასულ თვეებში რჩება ის, რაც იყო. საჭიროების შემთხვევაში აქ შეცვალეთ.",
    "price": "IncoPOS-ის ფასი დღგ-ის გარეშე (ჩეკის ფასი − დღგ, ორივე IncoPOS-დან), "
             "ამ თვის პირველი ჩეკიდან.",
    "unit_profit": "ერთ ცალზე: გაყიდვის ფასი − თვითღირებულება.",
    "money": "გაყიდული × გაყიდვის ფასი",
    "profit": "გაყიდული × მოგება ერთ ცალზე. ცარიელია, თუ თვითღირებულება არ აქვს.",
}


class Columns:
    """Where everything of the i-th month goes (i = 0 is the newest, in Nino's C..AS)."""

    def __init__(self, i: int):
        s = 3 + i * STEP
        self.first, self.cost, self.price, self.unit = s, s, s + 1, s + 2
        self.day = {d: s + 2 + d if d <= 15 else s + 7 + d for d in range(1, 32)}
        self.blocks = [(1, 15, s + 19, s + 20, s + 21), (16, 31, s + 40, s + 41, s + 42)]  # days, then 3 totals
        self.gaps = (s + 18, s + 22, s + 39)
        self.separator = s + SECTION


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


def is_product(name) -> bool:
    name = str(name).strip()
    return bool(name) and not name.startswith(("ნავაჭრი (", "მოგება ("))


def read_costs_tab(sheet) -> dict:
    """{product: cost} from the თვითღირებულებები tab (empty costs left out)."""
    rows = sheet.worksheet(COSTS_TAB).get_all_values(value_render_option="UNFORMATTED_VALUE")
    return {str(r[0]).strip(): r[1] for r in rows[1:] if len(r) > 1 and str(r[0]).strip() and r[1] != ""}


def read_kept_costs(view) -> dict:
    """The costs already in the branch tab, per month: {(month, product): cost or ""}.
    A month's cost column has the month title in row 1 and "თვითღირებულება" in row 2."""
    rows = view.get_all_values(value_render_option="UNFORMATTED_VALUE")
    if len(rows) <= HEAD:
        return {}
    titles, head = rows[0], rows[1]
    kept = {}
    for c, heading in enumerate(head):
        month = str(titles[c]).strip() if c < len(titles) else ""
        if heading != "თვითღირებულება" or not month:
            continue
        for row in rows[HEAD:]:
            if len(row) > 1 and is_product(row[1]):
                kept[month, str(row[1]).strip()] = row[c] if c < len(row) else ""
    return kept


def build_tab(conn, location_id: int, costs_tab: dict, kept: dict):
    """Builds the branch tab month by month, newest first. Returns (grid, requests-maker, months)."""
    order = conn.execute(ORDER_SQL, {"loc": location_id, "no_group": NO_GROUP}).fetchall()
    months = [m for (m,) in conn.execute(MONTHS_SQL, {"loc": location_id}).fetchall()]
    if not months:
        return [], [], months
    group_paid, by_group = {}, {}
    for group, name, paid, sold in order:
        group_paid[group] = group_paid.get(group, Decimal(0)) + paid
        by_group.setdefault(group, []).append((sold, name))
    groups = sorted(group_paid, key=lambda g: -group_paid[g])  # biggest section first
    products = {g: [n for _, n in sorted(by_group[g], key=lambda x: (-x[0], x[1]))] for g in groups}

    # The rows, the same for every month
    width = 2 + STEP * len(months)
    grid = [[""] * width, [""] * width]
    grid[1][1] = "პროდუქტი"
    product_row, sections = {}, []  # sections: (group, top, bottom, ნავაჭრი row, მოგება row)
    for group in groups:
        top = len(grid) + 1
        for name in products[group]:
            grid.append([""] * width)
            grid[-1][1] = name
            product_row[name] = len(grid)
        bottom = len(grid)
        grid += [[""] * width, [""] * width, [""] * width]  # ნავაჭრი, მოგება, an empty row
        grid[-3][1], grid[-2][1] = f"ნავაჭრი ({group})", f"მოგება ({group})"
        sections.append((group, top, bottom, len(grid) - 2, len(grid) - 1))
    grid += [[""] * width, [""] * width]
    total_money, total_profit = len(grid) - 1, len(grid)
    grid[-2][1], grid[-1][1] = "ნავაჭრი (საერთო)", "მოგება (საერთო)"

    def put(r, c, value):
        grid[r - 1][c - 1] = value

    notes, styles = {(HEAD, 2): NOTES["product"]}, []
    for i, month in enumerate(months):
        col = Columns(i)
        label = month_label(month)
        when = {"loc": location_id, "start": month, "end": next_month(month)}
        prices = dict(conn.execute(PRICES_SQL, when).fetchall())                   # 1. this month's prices
        sold = conn.execute(SALES_SQL, when).fetchall()                             # 2. this month's sales

        put(1, col.first, label)
        for c, title, note in ((col.cost, "თვითღირებულება", "cost"), (col.price, "გაყიდვის ფასი", "price"),
                               (col.unit, "მოგება", "unit_profit")):
            put(HEAD, c, title)
            notes[HEAD, c] = NOTES[note]
        for d, c in col.day.items():
            put(HEAD, c, d)
        for *_, c_sold, c_money, c_profit in col.blocks:
            put(HEAD, c_sold, "გაყიდული")
            put(HEAD, c_money, "შემოსავალი")
            put(HEAD, c_profit, "მოგება")
            notes[HEAD, c_money], notes[HEAD, c_profit] = NOTES["money"], NOTES["profit"]

        for name, r in product_row.items():
            if i == 0 or (label, name) not in kept:  # the current month (or a month not in the tab yet)
                cost = costs_tab.get(name, "")
            else:                                     # a past month keeps its cost
                cost = kept[label, name]
            C, P, U = column(col.cost), column(col.price), column(col.unit)
            put(r, col.cost, "" if cost == "" else number(cost))
            put(r, col.price, number(prices[name]) if name in prices else "")
            put(r, col.unit, f'=IF(OR({C}{r}="",{P}{r}=""),0,{P}{r}-{C}{r})')  # 0 (shown empty) without a cost
            for d1, d2, c_sold, c_money, c_profit in col.blocks:
                put(r, c_sold, f"=SUM({column(col.day[d1])}{r}:{column(col.day[d2])}{r})")
                put(r, c_money, f"={column(c_sold)}{r}*{P}{r}")
                put(r, c_profit, f'=IF({C}{r}="","",{column(c_sold)}{r}*{U}{r})')
        for name, day, count in sold:
            put(product_row[name], col.day[day.day], number(count))

        for group, top, bottom, r_money, r_profit in sections:
            for r, unit, total in ((r_money, col.price, 3), (r_profit, col.unit, 4)):
                u = column(unit)
                for c in col.day.values():
                    put(r, c, f"=SUMPRODUCT({column(c)}{top}:{column(c)}{bottom},${u}${top}:${u}${bottom})")
                for block in col.blocks:
                    c = column(block[total])
                    put(r, block[total], f"=SUM({c}{top}:{c}{bottom})")
        for r, k in ((total_money, 3), (total_profit, 4)):  # k: the money / profit place in blocks and sections
            for c in [*col.day.values(), *(b[k] for b in col.blocks)]:
                put(r, c, "=" + "+".join(f"{column(c)}{s[k]}" for s in sections))

        # This month's formats
        rows = len(grid)
        styles += [(1, col.first, 1, col.first + SECTION - 1, {"backgroundColor": TITLE, "textFormat": {"bold": True, "fontSize": 12}}),
                   (3, col.cost, rows, col.unit, MONEY),
                   (3, col.day[1], rows, col.day[31], QTY),
                   (1, col.separator, rows, col.separator, {"backgroundColor": SEPARATOR})]
        for *_, c_sold, c_money, c_profit in col.blocks:
            styles += [(3, c_sold, rows, c_sold, QTY), (3, c_money, rows, c_profit, MONEY)]

    def requests(sheet_id: int):
        out = [_style(sheet_id, *s) for s in [(HEAD, 1, HEAD, width, BOLD), (3, 2, len(grid), 2, BOLD), *styles]]
        for group, top, bottom, r_money, r_profit in sections:
            out += [_style(sheet_id, r_money, 2, r_money, width, {"backgroundColor": YELLOW, **BOLD, **MONEY}),
                    _style(sheet_id, r_profit, 2, r_profit, width, {"backgroundColor": GREEN, **BOLD, **MONEY})]
        for r in (total_money, total_profit):
            out.append(_style(sheet_id, r, 2, r, width, {"backgroundColor": DARK_GREEN, **BOLD, **MONEY}))
        for i in range(len(months)):  # the month title across its whole section
            col = Columns(i)
            out.append({"mergeCells": {"range": _range(sheet_id, 1, col.first, 1, col.first + SECTION - 1),
                                       "mergeType": "MERGE_ALL"}})
        out += [_note(sheet_id, r, c, text) for (r, c), text in notes.items()]
        widths = {1: 12, 2: 200}
        for i in range(len(months)):
            col = Columns(i)
            widths.update({col.cost: 110, col.price: 100, col.unit: 70, col.separator: 16,
                           **{c: 12 for c in col.gaps}})
            for *_, c_sold, c_money, c_profit in col.blocks:
                widths.update({c_sold: 75, c_money: 90, c_profit: 90})
        out += [_width(sheet_id, c, widths.get(c, 38)) for c in range(1, width + 1)]
        return out

    return grid, requests, months


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
        "properties": {"pixelSize": pixels, "hiddenByUser": False}, "fields": "pixelSize,hiddenByUser"}}


def _reset(sheet_id, rows, columns, has_filter: bool):
    """Empties the tab completely (filter, values, colours, notes, merges, dropdowns) and sets its size."""
    return [
        *([{"clearBasicFilter": {"sheetId": sheet_id}}] if has_filter else []),
        {"unmergeCells": {"range": {"sheetId": sheet_id}}},
        {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {
                "rowCount": rows, "columnCount": columns, "frozenRowCount": HEAD, "frozenColumnCount": 2}},
            "fields": "gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)"}},
    ]


def main():
    load_dotenv(find_dotenv(usecwd=True))  # the .env of the folder it's run from
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sheet = gspread.authorize(creds).open_by_key(os.environ["SALES_SHEET_ID"])
    costs_tab = read_costs_tab(sheet)
    with psycopg.connect(os.environ["INCOPOS_DATABASE_URL"]) as conn:
        for location_id, location_name in conn.execute("SELECT id, name FROM incopos.locations ORDER BY id").fetchall():
            tab_name = os.environ.get(f"SALES_SHEET_TAB_{location_id}")
            if not tab_name:
                continue  # this branch has no tab yet
            view = sheet.worksheet(tab_name)
            grid, requests, months = build_tab(conn, location_id, costs_tab, read_kept_costs(view))
            if not months:
                print(f"{tab_name}: no sales yet, skipped")
                continue
            meta = sheet.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,basicFilter)"})
            has_filter = any(s["properties"]["sheetId"] == view.id and "basicFilter" in s for s in meta["sheets"])
            sheet.batch_update({"requests": _reset(view.id, len(grid), len(grid[0]), has_filter)})
            view.update(grid, "A1", value_input_option="USER_ENTERED")
            sheet.batch_update({"requests": requests(view.id)})
            print(f"{tab_name}: {len(grid)} rows, {len(months)} months: {', '.join(month_label(m) for m in months)}")

            # The hidden data tab of an earlier version isn't used any more
            try:
                sheet.del_worksheet(sheet.worksheet(f"{location_name} — მონაცემები"))
                print(f"deleted the old tab {location_name} — მონაცემები")
            except gspread.WorksheetNotFound:
                pass


if __name__ == "__main__":
    main()
