"""Keeps the Google Sheet "თემა - ვოლტის რეპორტი" the same as the Wolt Excel report.

It builds the Excel in memory (excel_report.build_workbook) and copies every tab into the sheet:
values, SUM formulas, colours, fonts, merged cells, row heights and column widths. So the sheet and
the Excel always look the same, and a change to the Excel shows up in the sheet by itself.

Nobody types into this sheet, so every run rebuilds each of its tabs from scratch, one tab at a time
(a tab is either fully rebuilt or left as it was). Tabs that are not in the Excel are left alone;
only the empty "Sheet1" a new Google Sheet comes with is deleted.
Runs as the last step of wolt/daily_update.py (cron 12:00), after the day's orders are loaded.
Needs WOLT_SHEET_ID in .env (without it, it does nothing). The robot (tema-ops-vm) must be Editor.

Usage:
  uv run python src/tema_ops/wolt/wolt_sheet.py            (rebuild the sheet)
  uv run python src/tema_ops/wolt/wolt_sheet.py --dry-run  (build it and print the sizes; sends nothing)
"""
import argparse
import json
import os

import google.auth
import gspread
from dotenv import find_dotenv, load_dotenv
from openpyxl.utils import column_index_from_string

from tema_ops.wolt.excel_report import build_workbook

DEFAULT_TABS = {"Sheet1", "ფურცელი1"}  # the empty tab a new Google Sheet starts with
ROW_PIXELS = 21                         # Google's normal row height
COLUMN_PIXELS = 100                     # Google's normal column width


def color(argb: str) -> dict:
    """Excel's "007030A0" (alpha + red green blue) -> Google's {"red": 0.44, "green": 0.19, "blue": 0.63}."""
    rgb = argb[-6:]
    return {name: int(rgb[i:i + 2], 16) / 255 for name, i in (("red", 0), ("green", 2), ("blue", 4))}


def cell_data(cell) -> dict:
    """One Excel cell -> one Google cell: its value (formula, text or number) and its look."""
    data = {}
    value = cell.value
    if isinstance(value, str) and value.startswith("="):
        data["userEnteredValue"] = {"formulaValue": value}
    elif isinstance(value, str):
        data["userEnteredValue"] = {"stringValue": value}   # dates are text in the Excel, so they stay text
    elif value is not None:
        data["userEnteredValue"] = {"numberValue": float(value)}

    look, text = {}, {}
    if cell.fill.patternType == "solid" and cell.fill.fgColor.type == "rgb":
        look["backgroundColor"] = color(cell.fill.fgColor.rgb)
    if cell.font.b:
        text["bold"] = True
    if cell.font.sz and cell.font.sz != 11:                 # 11 = Excel's normal size
        text["fontSize"] = int(cell.font.sz)
    if cell.font.color is not None and cell.font.color.type == "rgb":
        text["foregroundColor"] = color(cell.font.color.rgb)
    if text:
        look["textFormat"] = text
    if cell.alignment.wrap_text:
        look["wrapStrategy"] = "WRAP"
    if cell.alignment.vertical == "center":
        look["verticalAlignment"] = "MIDDLE"
    if look:
        data["userEnteredFormat"] = look
    return data


def tab_requests(ws, sheet_id: int) -> list:
    """Everything that turns one Google tab into this Excel tab. Sent as one batch: all or nothing."""
    rows, columns = max(ws.max_row, 1), max(ws.max_column, 1)
    requests = [
        # 1. Empty the tab (merges, values, colours, notes), give it the Excel's size, normal heights and widths
        {"unmergeCells": {"range": {"sheetId": sheet_id}}},
        {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {
                "rowCount": rows, "columnCount": columns, "frozenRowCount": 0, "frozenColumnCount": 0}},
            "fields": "gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)"}},
        _size(sheet_id, "ROWS", 1, rows, ROW_PIXELS),
        _size(sheet_id, "COLUMNS", 1, columns, COLUMN_PIXELS),
        # 2. Every cell, row by row from A1
        {"updateCells": {
            "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
            "rows": [{"values": [cell_data(cell) for cell in row]}
                     for row in ws.iter_rows(max_row=rows, max_col=columns)],
            "fields": "userEnteredValue,userEnteredFormat"}},
    ]
    # 3. The merged cells, and the rows / columns the Excel made higher / wider
    for merged in ws.merged_cells.ranges:
        requests.append({"mergeCells": {"mergeType": "MERGE_ALL", "range": {
            "sheetId": sheet_id, "startRowIndex": merged.min_row - 1, "endRowIndex": merged.max_row,
            "startColumnIndex": merged.min_col - 1, "endColumnIndex": merged.max_col}}})
    for r, dim in ws.row_dimensions.items():
        if dim.customHeight and dim.height:
            requests.append(_size(sheet_id, "ROWS", r, r, round(dim.height * 4 / 3)))       # points -> pixels
    for letter, dim in ws.column_dimensions.items():
        if dim.customWidth and dim.width:
            c = column_index_from_string(letter)
            requests.append(_size(sheet_id, "COLUMNS", c, c, round(dim.width * 7 + 5)))     # characters -> pixels
    return requests


def _size(sheet_id, dimension, first, last, pixels):
    """Rows or columns first..last (counting from 1, both included) get this height / width."""
    return {"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": dimension, "startIndex": first - 1, "endIndex": last},
        "properties": {"pixelSize": pixels}, "fields": "pixelSize"}}


def rebuild(sheet, wb) -> None:
    """Every Excel tab -> the Google tab of the same name (added if missing), in the Excel's order."""
    tabs = {tab.title: tab for tab in sheet.worksheets()}
    for index, ws in enumerate(wb.worksheets):
        tab = tabs.get(ws.title) or sheet.add_worksheet(ws.title, rows=1, cols=1)
        requests = tab_requests(ws, tab.id)
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": tab.id, "index": index}, "fields": "index"}})
        sheet.batch_update({"requests": requests})
        print(f"{ws.title}: {ws.max_row} rows × {ws.max_column} columns")
    for title in DEFAULT_TABS & tabs.keys():
        if not tabs[title].get_all_values():  # only if nobody wrote anything in it
            sheet.del_worksheet(tabs[title])
            print(f"deleted the empty tab {title}")


def main():
    parser = argparse.ArgumentParser(description="Copy the Wolt Excel report into its Google Sheet.")
    parser.add_argument("--dry-run", action="store_true", help="build it and print the sizes; send nothing")
    args = parser.parse_args()
    load_dotenv(find_dotenv(usecwd=True))  # the .env of the folder it's run from
    wb = build_workbook()
    if args.dry_run:
        for ws in wb.worksheets:
            size = len(json.dumps(tab_requests(ws, 0))) / 1e6
            print(f"{ws.title}: {ws.max_row} rows × {ws.max_column} columns, {size:.1f} MB to send")
        return
    sheet_id = os.environ.get("WOLT_SHEET_ID")
    if not sheet_id:
        print("WOLT_SHEET_ID is not in .env, so the Wolt Google Sheet was not updated")
        return
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    rebuild(gspread.authorize(creds).open_by_key(sheet_id), wb)


if __name__ == "__main__":
    main()
