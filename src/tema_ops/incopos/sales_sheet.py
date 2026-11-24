"""Writes each branch's IncoPOS sales to the Google Sheet. Three kinds of tabs:

- the branch tab (one per branch): ONE month at a time, picked from the dropdown in B1, in Nino's
  Sheet7 layout: products in sections by IncoPOS group, days 1-15 and 16-31 in half-month blocks,
  each with გაყიდული / შემოსავალი / მოგება. Every number is a formula, so picking another month
  redraws the whole tab.
- "<branch> — მონაცემები" (hidden, one per branch): one row per day and product: how many were
  sold and what customers paid. The robot writes it; the formulas read it.
- "ფასები და თვითღირებულება": costs only, one line per month and product (თვე | პროდუქტი |
  თვითღირებულება). People fill and edit the cost. The robot adds the lines for a new month with
  the previous month's cost, so changing a month's cost changes only that month.

Where the numbers come from (the sheet says the same in its notes):
- a day = 21:00 the evening before -> 21:00, like the cash book (night + day shift)
- შემოსავალი = what customers really paid on the IncoPOS receipts ÷ 1.18 (VAT)
- გაყიდვის ფასი = შემოსავალი ÷ გაყიდული, i.e. the IncoPOS price that month without VAT
- მოგება = შემოსავალი − გაყიდული × that month's თვითღირებულება; empty when there's no cost

Everything is rewritten on every run (B1 goes back to the newest month); people's costs are kept.
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

COSTS_TAB = "ფასები და თვითღირებულება"   # costs per month: თვე | პროდუქტი | თვითღირებულება
MONTHS = ["იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი", "ივლისი",
          "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი"]
NO_GROUP = "სხვა"                         # section for a product that has no group in IncoPOS

# The branch tab's columns never change (Nino's Sheet7): F..T = days 1-15, U empty,
# V/W/X = გაყიდული/შემოსავალი/მოგება, Y empty, Z..AO = days 16-31, AP empty, AQ/AR/AS
DAY_COLUMN = {d: 5 + d if d <= 15 else 10 + d for d in range(1, 32)}
GAPS = (21, 25, 42)
WIDTH = 45
HEAD = 3  # the row with the dates
# Each block: first day, last day (formulas of the month's 1st day in $C$1), its days, its 3 columns
BLOCKS = [("$C$1", "$C$1+14", 1, 15, 22, 23, 24),
          ("$C$1+15", "EOMONTH($C$1,0)", 16, 31, 43, 44, 45)]

QTY = {"numberFormat": {"type": "NUMBER", "pattern": "0;-0;;@"}}           # 0 shows as empty
MONEY = {"numberFormat": {"type": "NUMBER", "pattern": "0.00;-0.00;;@"}}
DATE = {"numberFormat": {"type": "DATE", "pattern": "dd.mm"}}
FULL_DATE = {"numberFormat": {"type": "DATE", "pattern": "dd.mm.yyyy"}}
BOLD = {"textFormat": {"bold": True}}
YELLOW = {"red": 1, "green": 0.8, "blue": 0}             # ნავაჭრი rows (colours from Nino's file)
GREEN = {"red": 0, "green": 1, "blue": 0}                # მოგება rows
DARK_GREEN = {"red": 0.2, "green": 0.6, "blue": 0.4}     # the totals at the bottom
PICK = {"red": 1, "green": 1, "blue": 0}                 # cells people choose or type in
GREY = {"red": 0.5, "green": 0.5, "blue": 0.5}

# Sold and paid per day and product. A day is like the cash book: 21:00 the evening before ->
# 21:00 (night + day shift); adding 3 hours moves 21:00 to midnight, so ::date gives the day.
# (Line discounts are all 0 so far, so they are not used.)
SALES_SQL = """
SELECT (s.paid_at + interval '3 hours')::date AS day,
       g.name AS group_name,                 -- the product's group in IncoPOS, e.g. ყავა
       i.name,
       sum(l.quantity)           AS sold,
       sum(l.quantity * l.price) AS paid     -- VAT included
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

NOTES = {
    "pick": "აირჩიეთ თვე ამ უჯრის ისრით: მთელი ჩანართი იმ თვეს აჩვენებს.\n"
            "დღე = წინა დღის 21:00-დან ამ დღის 21:00-მდე (ღამის და დღის ცვლა), როგორც სალაროს წიგნში.\n"
            "მონაცემები IncoPOS-დან მოდის ყოველ ღამე. აქ ხელით შეცვლილი წაიშლება.",
    "first_day": "არჩეული თვის პირველი დღე (B1-დან). ყველა ფორმულა ამას იყენებს.",
    "cost": "ამ თვის თვითღირებულება ჩანართიდან „ფასები და თვითღირებულება“.",
    "price": "შემოსავალი ÷ გაყიდული: IncoPOS-ის ფასი ამ თვეში, დღგ-ის გარეშე.\n"
             "თუ ფასი თვის შუაში შეიცვალა, აქ საშუალოა.",
    "unit_profit": "ერთ ცალზე: გაყიდვის ფასი − თვითღირებულება.",
    "money": "ამ დღეებში IncoPOS-ის ჩეკებით რეალურად გადახდილი თანხა ÷ 1.18 (დღგ-ის გარეშე).\n"
             "თუ ფასი თვის შუაში არ შეცვლილა, ეს = გაყიდული × გაყიდვის ფასი.",
    "profit": "შემოსავალი − გაყიდული × თვითღირებულება. ცარიელია, თუ თვითღირებულება არ აქვს.",
    "cost_table": "აქ შეიყვანეთ ან შეცვალეთ. ახალ თვეს რობოტი წინა თვის თვითღირებულებას გადაიტანს.\n"
                  "ერთი თვის შეცვლა მხოლოდ იმ თვეზე მოქმედებს.",
}


def column(c: int) -> str:
    """3 -> "C", 27 -> "AA"."""
    return "".join(ch for ch in rowcol_to_a1(1, c) if ch.isalpha())


def month_label(day: datetime.date) -> str:
    return f"{MONTHS[day.month - 1]} {day.year}"


def label_to_month(label: str) -> datetime.date:
    """"ნოემბერი 2026" -> 2026-11-01"""
    name, year = label.rsplit(" ", 1)
    return datetime.date(int(year), MONTHS.index(name) + 1, 1)


def number(value):
    value = Decimal(str(value))
    return int(value) if value == value.to_integral_value() else float(value)


def read_sales(conn, location_id):
    return conn.execute(SALES_SQL, (location_id, location_id)).fetchall()


def read_cost_table(tab) -> tuple[dict, dict]:
    """The costs people have in the costs tab, found by the column headings.
    Returns ({(month, product): cost}, {product: cost}). The second one is only for a tab
    without a თვე column (the first layout): its costs then start every month."""
    rows = tab.get_all_values(value_render_option="UNFORMATTED_VALUE")
    head = [str(h).strip() for h in rows[0]] if rows else []
    if "პროდუქტი" not in head or "თვითღირებულება" not in head:
        return {}, {}
    p, c = head.index("პროდუქტი"), head.index("თვითღირებულება")
    m = head.index("თვე") if "თვე" in head else None
    by_month, by_product = {}, {}
    for r in rows[1:]:
        r = list(r) + [""] * len(head)
        name, cost = str(r[p]).strip(), r[c]
        if not name:
            continue
        if m is None:
            if cost != "":
                by_product[name] = cost
        elif str(r[m]).strip():
            by_month[str(r[m]).strip(), name] = cost
    return by_month, by_product


def build_cost_table(by_month: dict, by_product: dict, sales) -> list:
    """A line for every month and product that sold, plus every line people already have.
    A cost people entered is never changed; a new line gets the product's cost from the month before."""
    keys = set(by_month) | {(month_label(day), name) for day, _, name, *_ in sales}
    last_cost = {}  # product -> its cost in the latest month so far
    lines = {}
    for month, name in sorted(keys, key=lambda k: (label_to_month(k[0]), k[1])):  # oldest month first
        if (month, name) in by_month:
            cost = by_month[month, name]
        else:
            cost = last_cost.get(name, by_product.get(name, ""))
        if cost != "":
            last_cost[name] = cost
        lines[month, name] = cost
    values = [["თვე", "პროდუქტი", "თვითღირებულება"]]
    for month, name in sorted(lines, key=lambda k: (-label_to_month(k[0]).toordinal(), k[1])):  # newest first
        cost = lines[month, name]
        values.append([month, name, "" if cost == "" else number(cost)])
    return values


def build_data(sales):
    """The hidden data tab: one row per day and product, and the month list (K:L)."""
    C = f"'{COSTS_TAB}'!"
    values = [["თარიღი", "პროდუქტი", "ჯგუფი", "გაყიდული", "თანხა დღგ-ით", "თვე",
               "შემოსავალი", "თვითღირებულება", "მოგება", "", "თვე", "პირველი დღე"]]
    for day, group, name, sold, paid in sales:
        r = len(values) + 1
        values.append([day.isoformat(), name, group or NO_GROUP, number(sold), number(paid), month_label(day),
                       f"=E{r}/1.18",
                       f'=IFERROR(FILTER({C}$C:$C,{C}$A:$A=F{r},{C}$B:$B=B{r}),"")',  # this month's cost
                       f'=IF(H{r}="","",G{r}-D{r}*H{r})', "", "", ""])
    months = sorted({(day.year, day.month) for day, *_ in sales}, reverse=True)
    for i, (y, m) in enumerate(months):
        values[i + 1][10] = f"{MONTHS[m - 1]} {y}"
        values[i + 1][11] = datetime.date(y, m, 1).isoformat()
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
    y, m = months[0]
    put(row, 2, f"{MONTHS[m - 1]} {y}")
    put(row, 3, f"=VLOOKUP($B$1,{D}$K:$L,2,FALSE)")
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

    sections = []  # (ნავაჭრი row, მოგება row)
    for group in groups:
        top = len(grid) + 1
        for name in sorted((n for n in group_of if group_of[n] == group), key=lambda n: (-sold_all[n], n)):
            r, row = new_row()
            put(row, 2, name)
            put(row, 3, f'=IFERROR(FILTER({C}$C:$C,{C}$A:$A=$B$1,{C}$B:$B=$B{r}),"")')  # this month's cost
            put(row, 4, f'=IFERROR((W{r}+AR{r})/(V{r}+AQ{r}),"")')  # შემოსავალი ÷ გაყიდული
            put(row, 5, f'=IF(OR(C{r}="",D{r}=""),"",D{r}-C{r})')
            for d in range(1, 32):
                c = column(DAY_COLUMN[d])
                put(row, DAY_COLUMN[d], f'=IF({c}${HEAD}="","",SUMIFS({D}$D:$D,{D}$B:$B,$B{r},{D}$A:$A,{c}${HEAD}))')
            for start, end, d1, d2, c_sold, c_money, c_profit in BLOCKS:
                put(row, c_sold, f"=SUM({column(DAY_COLUMN[d1])}{r}:{column(DAY_COLUMN[d2])}{r})")
                span = f'{D}$B:$B,$B{r},{D}$A:$A,">="&{start},{D}$A:$A,"<="&{end}'
                put(row, c_money, f"=SUMIFS({D}$G:$G,{span})")
                put(row, c_profit, f'=IF($C{r}="","",SUMIFS({D}$I:$I,{span}))')
        bottom = len(grid)
        styles += [(top, 2, bottom, 2, BOLD), (top, 3, bottom, 5, MONEY)]
        styles += [(top, DAY_COLUMN[1], bottom, DAY_COLUMN[31], QTY)]
        for *_, c_sold, c_money, c_profit in BLOCKS:
            styles += [(top, c_sold, bottom, c_sold, QTY), (top, c_money, bottom, c_profit, MONEY)]

        pair = []
        for kind, data_column, fill, total in (("ნავაჭრი", "G", YELLOW, 5), ("მოგება", "I", GREEN, 6)):
            r, row = new_row()
            put(row, 2, f"{kind} ({group})")
            for d in range(1, 32):
                c = column(DAY_COLUMN[d])
                put(row, DAY_COLUMN[d], f'=IF({c}${HEAD}="","",SUMIFS({D}${data_column}:${data_column},'
                                        f'{D}$C:$C,"{group}",{D}$A:$A,{c}${HEAD}))')
            for block in BLOCKS:
                c = column(block[total])
                put(row, block[total], f"=SUM({c}{top}:{c}{bottom})")
            styles.append((r, 1, r, WIDTH, {"backgroundColor": fill, **BOLD, **MONEY}))
            merges.append(r)
            pair.append(r)
        sections.append(pair)
        new_row()  # an empty row between sections

    for kind, i, total in (("ნავაჭრი", 0, 5), ("მოგება", 1, 6)):
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
        "condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": f"={D}$K$2:$K${len(months) + 1}"}]},
        "showCustomUi": True, "strict": True}}})
    widths = {1: 12, 2: 200, 3: 110, 4: 110, 5: 80, **{c: 12 for c in GAPS}}
    for *_, c_sold, c_money, c_profit in BLOCKS:
        widths.update({c_sold: 75, c_money: 90, c_profit: 90})
    requests += [_width(view_id, c, widths.get(c, 42)) for c in range(1, WIDTH + 1)]
    return grid, requests


def data_requests(data_id: int, rows: int):
    """Formats for the hidden data tab, and hiding it."""
    return [
        _style(data_id, 1, 1, 1, 12, BOLD),
        _style(data_id, 2, 1, rows, 1, FULL_DATE),
        _style(data_id, 2, 5, rows, 5, MONEY),
        _style(data_id, 2, 7, rows, 9, MONEY),
        _style(data_id, 2, 12, rows, 12, FULL_DATE),
        _width(data_id, 2, 200),
        {"updateSheetProperties": {"properties": {"sheetId": data_id, "hidden": True}, "fields": "hidden"}},
    ]


def cost_requests(tab_id: int, rows: int):
    """Formats for the costs tab: the cost column is marked as the one people fill in."""
    return [
        _style(tab_id, 1, 1, 1, 3, BOLD),
        _style(tab_id, 2, 3, rows, 3, {"backgroundColor": PICK, **MONEY}),
        _note(tab_id, 1, 3, NOTES["cost_table"]),
        _width(tab_id, 1, 130), _width(tab_id, 2, 220), _width(tab_id, 3, 120),
        {"setBasicFilter": {"filter": {"range": _range(tab_id, 1, 1, rows, 3)}}},  # filter by month
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
    """Empties a tab completely (values, colours, notes, merges, dropdowns) and sets its size.
    (The costs tab's filter isn't cleared: setBasicFilter replaces it afterwards.)"""
    return [
        {"unmergeCells": {"range": {"sheetId": sheet_id}}},
        {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {
                "rowCount": rows, "columnCount": columns,
                "frozenRowCount": frozen_rows, "frozenColumnCount": frozen_columns}},
            "fields": "gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)"}},
    ]


def tab(sheet, name, rows, columns):
    """The tab with this name; created if it doesn't exist yet."""
    try:
        return sheet.worksheet(name)
    except gspread.WorksheetNotFound:
        return sheet.add_worksheet(name, rows=rows, cols=columns)


def main():
    load_dotenv(find_dotenv(usecwd=True))  # the .env of the folder it's run from
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sheet = gspread.authorize(creds).open_by_key(os.environ["SALES_SHEET_ID"])
    costs_tab = tab(sheet, COSTS_TAB, 2, 3)
    by_month, by_product = read_cost_table(costs_tab)

    branches, all_sales = [], []
    with psycopg.connect(os.environ["INCOPOS_DATABASE_URL"]) as conn:
        for location_id, location_name in conn.execute("SELECT id, name FROM incopos.locations ORDER BY id").fetchall():
            tab_name = os.environ.get(f"SALES_SHEET_TAB_{location_id}")
            if not tab_name:
                continue  # this branch has no tab yet
            sales = read_sales(conn, location_id)
            if not sales:
                print(f"{tab_name}: no sales yet, skipped")
                continue
            all_sales += sales
            branches.append((tab_name, f"{location_name} — მონაცემები", sales))

    # 1. The costs tab (one for all branches): people's costs are read above and written back unchanged
    cost_values = build_cost_table(by_month, by_product, all_sales)
    sheet.batch_update({"requests": _reset(costs_tab.id, len(cost_values), 3, 1, 2)})
    costs_tab.update(cost_values, "A1", value_input_option="USER_ENTERED")
    sheet.batch_update({"requests": cost_requests(costs_tab.id, len(cost_values))})
    print(f"{COSTS_TAB}: {len(cost_values) - 1} lines")

    # 2. Each branch: its hidden data tab and its month tab
    for tab_name, data_name, sales in branches:
        data_values, months = build_data(sales)
        data = tab(sheet, data_name, len(data_values), 12)
        view = sheet.worksheet(tab_name)
        view_values, view_requests = build_view(sales, months, data_name, view.id)
        sheet.batch_update({"requests": _reset(data.id, len(data_values), 12, 1, 0)
                            + _reset(view.id, len(view_values), WIDTH, HEAD, 5)})
        data.update(data_values, "A1", value_input_option="USER_ENTERED")
        view.update(view_values, "A1", value_input_option="USER_ENTERED")
        sheet.batch_update({"requests": data_requests(data.id, len(data_values)) + view_requests})
        print(f"{tab_name}: {len(view_values)} rows; hidden data tab: {len(data_values) - 1} rows")


if __name__ == "__main__":
    main()
