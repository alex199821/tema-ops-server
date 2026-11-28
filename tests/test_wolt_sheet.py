# Checks that an Excel tab is copied cell for cell into Google Sheets requests (no Google, no database).
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from tema_ops.wolt.wolt_sheet import tab_requests


def excel_tab():
    ws = Workbook().active
    ws.column_dimensions["A"].width = 14
    ws.append(["ნოემბერი 2026"])
    ws.merge_cells("A1:C1")
    ws["A1"].fill = PatternFill("solid", fgColor="7030A0")
    ws["A1"].font = Font(bold=True, color="FFFFFF", size=18)
    ws.append(["01.11.2026", 3, None, Decimal("412.50")])
    ws.append(["სულ", "=SUM(B2:B2)"])
    ws["A3"].alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[3].height = 40
    return ws


def test_copies_values_formulas_and_look():
    requests = tab_requests(excel_tab(), sheet_id=7)
    assert list(requests[0]) == ["unmergeCells"] and requests[1]["updateCells"]["fields"] == "*"  # emptied first

    rows = next(r["updateCells"]["rows"] for r in requests if "rows" in r.get("updateCells", {}))
    values = [[cell.get("userEnteredValue") for cell in row["values"]] for row in rows]
    assert values[0][0] == {"stringValue": "ნოემბერი 2026"}
    assert values[1] == [{"stringValue": "01.11.2026"}, {"numberValue": 3.0}, None, {"numberValue": 412.5}]
    assert values[2][:2] == [{"stringValue": "სულ"}, {"formulaValue": "=SUM(B2:B2)"}]
    assert rows[1]["values"][2] == {}  # an empty cell stays empty, with no look

    title = rows[0]["values"][0]["userEnteredFormat"]
    assert title["backgroundColor"] == {"red": 0x70 / 255, "green": 0x30 / 255, "blue": 0xA0 / 255}
    assert title["textFormat"] == {"bold": True, "fontSize": 18,
                                   "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}
    assert rows[2]["values"][0]["userEnteredFormat"] == {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}


def test_copies_merges_and_sizes():
    requests = tab_requests(excel_tab(), sheet_id=7)
    merges = [r["mergeCells"]["range"] for r in requests if "mergeCells" in r]
    assert merges == [{"sheetId": 7, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 3}]
    sizes = [(r["updateDimensionProperties"]["range"]["dimension"],
              r["updateDimensionProperties"]["range"]["startIndex"],
              r["updateDimensionProperties"]["properties"]["pixelSize"])
             for r in requests if "updateDimensionProperties" in r]
    assert ("ROWS", 2, 53) in sizes      # row 3: 40 points
    assert ("COLUMNS", 0, 103) in sizes  # column A: 14 characters
    grid = next(r for r in requests if "updateSheetProperties" in r)["updateSheetProperties"]
    assert grid["properties"]["gridProperties"]["rowCount"] == 3
    assert grid["properties"]["gridProperties"]["columnCount"] == 4
