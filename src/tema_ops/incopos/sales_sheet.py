"""Keeps each branch's tab of the Google Sheet up to date with the IncoPOS sales, in Nino's Sheet7
layout, with the months side by side in order: the oldest on the left, the newest on the right.
B1 is a link that jumps to the newest month, so nobody has to scroll there.

- Rows: every product the branch has sold, in sections by IncoPOS group (ყავა, მზა პროდუქცია…),
  each section followed by its ნავაჭრი (yellow) and მოგება (green) rows; the totals at the bottom.
- Columns: B = product, then one section per month:
  თვითღირებულება | გაყიდვის ფასი | მოგება | days 1-15 | გაყიდული შემოსავალი მოგება |
  days 16-31 | გაყიდული შემოსავალი მოგება. The oldest month's columns are Nino's C..AS.

It never clears the tab (except the very first time); it only adds and updates:
- a new month: a new section is ADDED on the right; the older months stay untouched
- a new product: a row is INSERTED in its section
- every night: the newest month's IncoPOS cells are written again: the price (each product's first
  receipt of the month, IncoPOS's price without VAT), how many were sold per day, and the cost from
  the თვითღირებულებები tab. With --day, that day's month gets its price and sold cells again too.
So whatever people change in past months stays, and so do notes and colours anywhere.

Nino's formulas: შემოსავალი = გაყიდული × ფასი, მოგება = გაყიდული × (ფასი − თვითღირებულება).
A day = 21:00 the evening before -> 21:00, like the cash book (night + day shift).
Needs SALES_SHEET_ID, and SALES_SHEET_TAB_<IncoPOS location id> for each branch to write.

Usage:
  uv run python src/tema_ops/incopos/sales_sheet.py                    (the newest month)
  uv run python src/tema_ops/incopos/sales_sheet.py --day 2026-11-05   (also that day's month)
"""
import argparse
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
TOTAL_MONEY, TOTAL_PROFIT = "ნავაჭრი (საერთო)", "მოგება (საერთო)"

QTY = {"numberFormat": {"type": "NUMBER", "pattern": "0;-0;;@"}}           # 0 shows as empty
MONEY = {"numberFormat": {"type": "NUMBER", "pattern": "0.00;-0.00;;@"}}
BOLD = {"textFormat": {"bold": True}}
TITLE = {"red": 0.85, "green": 0.85, "blue": 0.85}       # month title row
SEPARATOR = {"red": 0.4, "green": 0.4, "blue": 0.4}      # the column between months
YELLOW = {"red": 1, "green": 0.8, "blue": 0}             # ნავაჭრი rows (colours from Nino's file)
GREEN = {"red": 0, "green": 1, "blue": 0}                # მოგება rows
DARK_GREEN = {"red": 0.2, "green": 0.6, "blue": 0.4}     # the totals at the bottom
BLUE = {"red": 0.07, "green": 0.33, "blue": 0.8}         # the link to the newest month
FILL = {"money": YELLOW, "profit": GREEN, "total_money": DARK_GREEN, "total_profit": DARK_GREEN}

# A day is like the cash book: 21:00 the evening before -> 21:00 (night + day shift).
# Adding 3 hours moves 21:00 to midnight, so ::date gives the day.
DAY = "(s.paid_at + interval '3 hours')::date"

# The day of the newest receipt: still going on (or not fully loaded), so only days before it count
NEWEST_SQL = "SELECT (max(paid_at) + interval '3 hours')::date FROM incopos.sales WHERE location_id = %(loc)s"

MONTHS_SQL = f"""
SELECT DISTINCT date_trunc('month', {DAY})::date
FROM incopos.sales s
WHERE s.location_id = %(loc)s AND {DAY} < %(until)s
ORDER BY 1
"""

# Every product the branch has sold, with its group: sets the rows (biggest section first, then most sold)
ORDER_SQL = f"""
SELECT coalesce(g.name, %(no_group)s) AS group_name, i.name,
       sum(l.quantity * l.price) AS paid, sum(l.quantity) AS sold
FROM incopos.sale_lines l
JOIN incopos.sales s ON s.location_id = l.location_id AND s.id = l.sale_id
JOIN incopos.items i ON i.id = l.item_id
LEFT JOIN incopos.item_groups g ON g.id = i.group_id
WHERE l.location_id = %(loc)s AND {DAY} < %(until)s
GROUP BY 1, 2
"""

# One month's prices: each product's first receipt of the month, IncoPOS's price without VAT
# (Price − Vat, both per item, as on the receipt line). DISTINCT ON keeps only that first line.
PRICES_SQL = f"""
SELECT DISTINCT ON (i.name)
       i.name,
       (d->>'Price')::numeric - (d->>'Vat')::numeric AS price
FROM incopos.sales s
CROSS JOIN LATERAL jsonb_array_elements(s.raw->'Details') AS d
JOIN incopos.items i ON i.id = (d->>'ItemId')::int
WHERE s.location_id = %(loc)s AND {DAY} >= %(start)s AND {DAY} < %(end)s AND {DAY} < %(until)s
ORDER BY i.name, s.paid_at
"""

# One month's sales: how many of each product per day
SALES_SQL = f"""
SELECT i.name, {DAY} AS day, sum(l.quantity) AS sold
FROM incopos.sale_lines l
JOIN incopos.sales s ON s.location_id = l.location_id AND s.id = l.sale_id
JOIN incopos.items i ON i.id = l.item_id
WHERE l.location_id = %(loc)s AND {DAY} >= %(start)s AND {DAY} < %(end)s AND {DAY} < %(until)s
GROUP BY 1, 2
"""

NOTES = {
    "product": "დღე = წინა დღის 21:00-დან ამ დღის 21:00-მდე (ღამის და დღის ცვლა), როგორც სალაროს წიგნში.\n"
               "ყოველ ღამე რობოტი ახლებს მხოლოდ ბოლო თვის IncoPOS-ის უჯრებს (ფასი, გაყიდული დღეებში, "
               "თვითღირებულება). გასული თვეები არ იცვლება: იქ შეგიძლიათ ხელით შეცვალოთ.",
    "cost": "ბოლო თვეში: ჩანართიდან „თვითღირებულებები“ (ყოველ ღამე).\n"
            "გასულ თვეებში რჩება ის, რაც იყო. საჭიროების შემთხვევაში აქ შეცვალეთ.",
    "price": "IncoPOS-ის ფასი დღგ-ის გარეშე (ჩეკის ფასი − დღგ, ორივე IncoPOS-დან), ამ თვის პირველი ჩეკიდან.",
    "unit_profit": "ერთ ცალზე: გაყიდვის ფასი − თვითღირებულება.",
    "money": "გაყიდული × გაყიდვის ფასი",
    "profit": "გაყიდული × მოგება ერთ ცალზე. ცარიელია, თუ თვითღირებულება არ აქვს.",
}


class Columns:
    """The columns of one month's section, which starts at column `first` (Nino's layout from C)."""

    def __init__(self, first: int):
        s = first
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


def label_month(label: str) -> datetime.date:
    """"ნოემბერი 2026" -> 2026-11-01"""
    name, year = label.rsplit(" ", 1)
    return datetime.date(int(year), MONTHS.index(name) + 1, 1)


def next_month(month: datetime.date) -> datetime.date:
    return (month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)


def number(value):
    value = Decimal(str(value))
    return int(value) if value == value.to_integral_value() else float(value)


class Tab:
    """The branch tab's shape: its rows from the top (kind, text in B, group) and where each month starts."""

    def __init__(self, rows: list, months: dict, columns: int):
        self.rows, self.months, self.columns = rows, months, columns  # months: {label: first column}

    @classmethod
    def read(cls, values: list, columns: int):
        """The tab as it is now; None if it isn't in this layout yet (empty, or an older layout)."""
        if len(values) < HEAD or len(values[1]) < 2 or values[1][1] != "პროდუქტი":
            return None
        titles, head = values[0], values[1]
        months = {str(titles[c]).strip(): c + 1 for c in range(min(len(titles), len(head)))
                  if head[c] == "თვითღირებულება" and str(titles[c]).strip()}
        rows, waiting = [("title", "", ""), ("head", "პროდუქტი", "")], []  # waiting: products before their section row
        for values_row in values[HEAD:]:
            b = str(values_row[1]).strip() if len(values_row) > 1 else ""
            if b in (TOTAL_MONEY, TOTAL_PROFIT):
                rows.append(("total_money" if b == TOTAL_MONEY else "total_profit", b, ""))
            elif b.startswith("ნავაჭრი (") and b.endswith(")"):
                group = b[len("ნავაჭრი ("):-1]
                for i in waiting:
                    rows[i] = ("product", rows[i][1], group)
                waiting = []
                rows.append(("money", b, group))
            elif b.startswith("მოგება (") and b.endswith(")"):
                rows.append(("profit", b, b[len("მოგება ("):-1]))
            elif b:
                waiting.append(len(rows))
                rows.append(("product", b, None))
            else:
                rows.append(("blank", "", ""))
        return cls(rows, months, columns)

    @classmethod
    def empty(cls):
        rows = [("title", "", ""), ("head", "პროდუქტი", ""),
                ("total_money", TOTAL_MONEY, ""), ("total_profit", TOTAL_PROFIT, "")]
        return cls(rows, {}, 2)

    def products(self) -> dict:
        return {name: i + 1 for i, (kind, name, _) in enumerate(self.rows) if kind == "product"}

    def sections(self) -> list:
        """[(group, first product row, last product row, ნავაჭრი row, მოგება row)]"""
        out, first = [], None
        for i, (kind, _, group) in enumerate(self.rows):
            r = i + 1
            if kind == "product" and first is None:
                first = r
            elif kind == "money":
                out.append([group, first or r, r - 1, r, None])
                first = None
            elif kind == "profit":
                out[-1][4] = r
        return [tuple(s) for s in out]

    def row_of(self, kind: str) -> int:
        return next(i + 1 for i, row in enumerate(self.rows) if row[0] == kind)

    def add_product(self, name: str, group: str, sheet_id: int) -> list:
        """Inserts a row for a new product at the end of its section (a new section before the totals)."""
        money = [i for i, (kind, _, g) in enumerate(self.rows) if kind == "money" and g == group]
        if money:
            at, new = money[0], [("product", name, group)]
        else:
            at = self.row_of("total_money") - 1
            new = [("product", name, group), ("money", f"ნავაჭრი ({group})", group),
                   ("profit", f"მოგება ({group})", group), ("blank", "", "")]
        self.rows[at:at] = new
        return [{"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS",
                                               "startIndex": at, "endIndex": at + len(new)},
                                     "inheritFromBefore": True}}]

    def add_month(self, label: str, sheet_id: int) -> list:
        """Adds a month's section in its place: at the end, or before the first newer month
        (only when an older month is loaded later)."""
        month = label_month(label)
        newer = [first for other, first in self.months.items() if label_month(other) > month]
        at = min(newer) if newer else self.columns + 1
        if at <= self.columns:
            request = {"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                                                     "startIndex": at - 1, "endIndex": at - 1 + STEP},
                                           "inheritFromBefore": False}}
            self.months = {m: f + STEP if f >= at else f for m, f in self.months.items()}
        else:
            request = {"appendDimension": {"sheetId": sheet_id, "dimension": "COLUMNS", "length": STEP}}
        self.months[label] = at
        self.columns += STEP
        return [request]


def product_formulas(r: int, col: Columns) -> dict:
    """The formulas of one product row in one month."""
    C, P, U = column(col.cost), column(col.price), column(col.unit)
    cells = {(r, col.unit): f'=IF(OR({C}{r}="",{P}{r}=""),0,{P}{r}-{C}{r})'}  # 0 (shown empty) without a cost
    for d1, d2, c_sold, c_money, c_profit in col.blocks:
        cells[r, c_sold] = f"=SUM({column(col.day[d1])}{r}:{column(col.day[d2])}{r})"
        cells[r, c_money] = f"={column(c_sold)}{r}*{P}{r}"
        cells[r, c_profit] = f'=IF({C}{r}="","",{column(c_sold)}{r}*{U}{r})'
    return cells


def summary_formulas(tab: Tab, col: Columns) -> dict:
    """The formulas of the yellow/green rows and the totals in one month."""
    cells, sections = {}, tab.sections()
    for _, top, bottom, r_money, r_profit in sections:
        for r, unit, total in ((r_money, col.price, 3), (r_profit, col.unit, 4)):
            u = column(unit)
            for c in col.day.values():
                cells[r, c] = f"=SUMPRODUCT({column(c)}{top}:{column(c)}{bottom},${u}${top}:${u}${bottom})"
            for block in col.blocks:
                cells[r, block[total]] = f"=SUM({column(block[total])}{top}:{column(block[total])}{bottom})"
    for kind, k in (("total_money", 3), ("total_profit", 4)):  # k: the money / profit place in blocks and sections
        r = tab.row_of(kind)
        for c in [*col.day.values(), *(b[k] for b in col.blocks)]:
            cells[r, c] = "=" + "+".join(f"{column(c)}{s[k]}" for s in sections)
    return cells


def month_values(tab: Tab, col: Columns, prices: dict, sold: list, costs: dict | None) -> dict:
    """A month's IncoPOS cells for every product: price and sold per day (and the cost, if given).
    Cells without a value are written empty, so a number that went away is cleared."""
    cells = {}
    for name, r in tab.products().items():
        cells[r, col.price] = number(prices[name]) if name in prices else ""
        for c in col.day.values():
            cells[r, c] = ""
        if costs is not None:
            cells[r, col.cost] = number(costs[name]) if costs.get(name, "") != "" else ""
    rows = tab.products()
    for name, day, count in sold:
        cells[rows[name], col.day[day.day]] = number(count)
    return cells


def month_head(label: str, col: Columns) -> dict:
    cells = {(1, col.first): label, (HEAD, col.cost): "თვითღირებულება", (HEAD, col.price): "გაყიდვის ფასი",
             (HEAD, col.unit): "მოგება"}
    cells.update({(HEAD, c): d for d, c in col.day.items()})
    for *_, c_sold, c_money, c_profit in col.blocks:
        cells.update({(HEAD, c_sold): "გაყიდული", (HEAD, c_money): "შემოსავალი", (HEAD, c_profit): "მოგება"})
    return cells


def month_formats(tab: Tab, col: Columns, sheet_id: int) -> list:
    """Colours, number formats, widths and notes of one month's columns."""
    rows = len(tab.rows)
    out = [{"mergeCells": {"range": _range(sheet_id, 1, col.first, 1, col.first + SECTION - 1), "mergeType": "MERGE_ALL"}},
           _style(sheet_id, 1, col.first, 1, col.first + SECTION - 1,
                  {"backgroundColor": TITLE, "textFormat": {"bold": True, "fontSize": 12}}),
           _style(sheet_id, HEAD, col.first, HEAD, col.first + SECTION - 1, BOLD),
           _style(sheet_id, 1, col.separator, rows, col.separator, {"backgroundColor": SEPARATOR}),
           _style(sheet_id, 3, col.cost, rows, col.unit, MONEY),
           _style(sheet_id, 3, col.day[1], rows, col.day[31], QTY)]
    for *_, c_sold, c_money, c_profit in col.blocks:
        out += [_style(sheet_id, 3, c_sold, rows, c_sold, QTY), _style(sheet_id, 3, c_money, rows, c_profit, MONEY)]
    for i, (kind, _, _) in enumerate(tab.rows):  # after the columns, so the coloured rows win
        if kind in FILL:
            out.append(_style(sheet_id, i + 1, col.first, i + 1, col.first + SECTION - 1,
                              {"backgroundColor": FILL[kind], **BOLD, **MONEY}))
    for c, key in ((col.cost, "cost"), (col.price, "price"), (col.unit, "unit_profit"),
                   *((b[3], "money") for b in col.blocks), *((b[4], "profit") for b in col.blocks)):
        out.append(_note(sheet_id, HEAD, c, NOTES[key]))
    widths = {col.cost: 110, col.price: 100, col.unit: 70, col.separator: 16, **{c: 12 for c in col.gaps}}
    for *_, c_sold, c_money, c_profit in col.blocks:
        widths.update({c_sold: 75, c_money: 90, c_profit: 90})
    out += [_width(sheet_id, c, widths.get(c, 38)) for c in range(col.first, col.separator + 1)]
    return out


def update_branch(sheet, conn, location_id: int, view, costs: dict, day: datetime.date | None) -> str:
    """Brings one branch tab up to date. Returns a line for the log."""
    newest = conn.execute(NEWEST_SQL, {"loc": location_id}).fetchone()[0]
    if newest is None:
        return f"{view.title}: no sales yet, skipped"
    until = {"loc": location_id, "until": newest, "no_group": NO_GROUP}
    months = [m for (m,) in conn.execute(MONTHS_SQL, until).fetchall()]
    if not months:
        return f"{view.title}: no finished day yet, skipped"
    order = conn.execute(ORDER_SQL, until).fetchall()
    group_paid, by_group = {}, {}
    for group, name, paid, count in order:
        group_paid[group] = group_paid.get(group, Decimal(0)) + paid
        by_group.setdefault(group, []).append((count, name))
    groups = sorted(group_paid, key=lambda g: -group_paid[g])  # biggest section first, then most sold
    wanted = [(g, n) for g in groups for _, n in sorted(by_group[g], key=lambda x: (-x[0], x[1]))]

    # 1. The tab's shape as it is now (the first time: start empty)
    structure, formats, cells = [], [], {}
    tab = Tab.read(view.get_all_values(value_render_option="UNFORMATTED_VALUE"), view.col_count)
    if tab is None:
        meta = sheet.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,basicFilter)"})
        if any(s["properties"]["sheetId"] == view.id and "basicFilter" in s for s in meta["sheets"]):
            structure.append({"clearBasicFilter": {"sheetId": view.id}})
        tab = Tab.empty()
        structure += _reset(view.id, len(tab.rows), tab.columns)
        cells[HEAD, 2] = "პროდუქტი"
        formats += [_style(view.id, HEAD, 2, HEAD, 2, BOLD), _note(view.id, HEAD, 2, NOTES["product"]),
                    _width(view.id, 1, 12), _width(view.id, 2, 200),
                    {"updateSheetProperties": {"properties": {"sheetId": view.id, "gridProperties": {"frozenColumnCount": 2}},
                                               "fields": "gridProperties.frozenColumnCount"}}]

    # 2. New products: a row each (a new group: a new section)
    known = set(tab.products())
    new_products = [(g, n) for g, n in wanted if n not in known]
    for group, name in new_products:
        structure += tab.add_product(name, group, view.id)

    # 3. New months: a section each, in its place (newest on the left)
    new_months = [month_label(m) for m in months if month_label(m) not in tab.months]
    for label in new_months:
        structure += tab.add_month(label, view.id)

    # 4. Formulas and labels for what is new (new rows take their formats from the row above)
    products = tab.products()
    new_names = {n for _, n in new_products}
    for i, (kind, text, _) in enumerate(tab.rows):
        r = i + 1
        if kind == "product" and text in new_names:
            cells[r, 2] = text
            formats.append(_style(view.id, r, 2, r, 2, BOLD))
        elif kind in FILL and new_products:  # the section / total labels (a new section adds two)
            cells[r, 2] = text
            formats.append(_style(view.id, r, 2, r, 2, {"backgroundColor": FILL[kind], **BOLD}))
    for label, first in tab.months.items():
        col = Columns(first)
        if label in new_months:
            cells.update(month_head(label, col))
            for r in products.values():
                cells.update(product_formulas(r, col))
            formats += month_formats(tab, col, view.id)
        elif new_products:  # rows were added: their formulas, and colours for a new section's rows
            for name in new_names:
                cells.update(product_formulas(products[name], col))
            for i, (kind, _, _) in enumerate(tab.rows):
                if kind in FILL:
                    formats.append(_style(view.id, i + 1, col.first, i + 1, col.first + SECTION - 1,
                                          {"backgroundColor": FILL[kind], **BOLD, **MONEY}))
        if label in new_months or new_products:  # the yellow/green rows' ranges cover the new rows
            cells.update(summary_formulas(tab, col))

    # 5. B1: a link that jumps to the newest month (its title cell)
    newest_label = month_label(months[-1])
    cells[1, 2] = f'=HYPERLINK("#gid={view.id}&range={column(tab.months[newest_label])}1","→ {newest_label}")'
    formats += [_style(view.id, 1, 2, 1, 2, {"textFormat": {"bold": True, "fontSize": 12, "foregroundColor": BLUE}}),
                _note(view.id, 1, 2, "")]  # no note here: it would hide the link's pop-up

    # 6. The IncoPOS cells: new months, the newest month, and the month(s) of --day
    refresh = set(new_months) | {newest_label}
    if day:
        refresh |= {month_label(d.replace(day=1)) for d in (day, day + datetime.timedelta(days=1))} & set(tab.months)
    for label in refresh:
        month = label_month(label)
        when = {**until, "start": month, "end": next_month(month)}
        prices = dict(conn.execute(PRICES_SQL, when).fetchall())
        sold = conn.execute(SALES_SQL, when).fetchall()
        with_costs = costs if (label == newest_label or label in new_months) else None  # past months keep theirs
        cells.update(month_values(tab, Columns(tab.months[label]), prices, sold, with_costs))

    if structure:
        sheet.batch_update({"requests": structure})
    if cells:
        sheet.values_batch_update({"valueInputOption": "USER_ENTERED", "data": _ranges(view.title, cells)})
    if formats:
        sheet.batch_update({"requests": formats})
    parts = [f"{len(new_months)} new month(s)" if new_months else "",
             f"{len(new_products)} new product(s)" if new_products else "",
             f"updated {', '.join(sorted(refresh, key=label_month, reverse=True))}"]
    return f"{view.title}: " + "; ".join(p for p in parts if p)


def _ranges(title: str, cells: dict) -> list:
    """Cells -> one range per run of neighbouring cells in a row (fewer, bigger writes)."""
    out = []
    for r in sorted({r for r, _ in cells}):
        cols = sorted(c for rr, c in cells if rr == r)
        start = prev = cols[0]
        for c in cols[1:] + [None]:
            if c != prev + 1:
                out.append({"range": f"'{title}'!{rowcol_to_a1(r, start)}:{rowcol_to_a1(r, prev)}",
                            "values": [[cells[r, x] for x in range(start, prev + 1)]]})
                start = c
            prev = c
    return out


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


def _reset(sheet_id, rows, columns):
    """Only the first time: empties the tab (values, colours, notes, merges, dropdowns), sets its size.
    Unfreezes first: Google refuses a size that would leave no unfrozen column."""
    return [
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 0, "frozenColumnCount": 0}},
            "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
        {"unmergeCells": {"range": {"sheetId": sheet_id}}},
        {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {
                "rowCount": rows, "columnCount": columns, "frozenRowCount": HEAD, "frozenColumnCount": 0}},
            "fields": "gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)"}},
    ]


def main():
    parser = argparse.ArgumentParser(description="Update the sales tabs of the Google Sheet.")
    parser.add_argument("--day", type=datetime.date.fromisoformat,
                        help="a day that was (re)loaded: its month's IncoPOS cells are written again too")
    args = parser.parse_args()
    load_dotenv(find_dotenv(usecwd=True))  # the .env of the folder it's run from
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sheet = gspread.authorize(creds).open_by_key(os.environ["SALES_SHEET_ID"])
    rows = sheet.worksheet(COSTS_TAB).get_all_values(value_render_option="UNFORMATTED_VALUE")
    costs = {str(r[0]).strip(): r[1] for r in rows[1:] if len(r) > 1 and str(r[0]).strip() and r[1] != ""}
    with psycopg.connect(os.environ["INCOPOS_DATABASE_URL"]) as conn:
        for location_id, location_name in conn.execute("SELECT id, name FROM incopos.locations ORDER BY id").fetchall():
            tab_name = os.environ.get(f"SALES_SHEET_TAB_{location_id}")
            if not tab_name:
                continue  # this branch has no tab yet
            print(update_branch(sheet, conn, location_id, sheet.worksheet(tab_name), costs, args.day))
            try:  # the hidden data tab of an earlier version isn't used any more
                sheet.del_worksheet(sheet.worksheet(f"{location_name} — მონაცემები"))
                print(f"deleted the old tab {location_name} — მონაცემები")
            except gspread.WorksheetNotFound:
                pass


if __name__ == "__main__":
    main()
