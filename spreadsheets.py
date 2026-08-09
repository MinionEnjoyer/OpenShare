"""Read-only, bounded spreadsheet previews for OpenShare."""

import csv
import io
from contextlib import suppress
from datetime import date, datetime, time
from pathlib import Path


SPREADSHEET_EXTS = {".xlsx", ".xlsm", ".xls", ".xlsb", ".ods", ".csv", ".tsv"}
SPREADSHEET_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/vnd.ms-excel",
    "application/vnd.ms-excel.sheet.binary.macroenabled.12",
    "application/vnd.oasis.opendocument.spreadsheet",
    "text/csv",
    "text/tab-separated-values",
}
PREVIEW_MAX_COLUMNS = 100
PREVIEW_MAX_ROWS_PER_PAGE = 200


def is_spreadsheet(filename: str, mime: str) -> bool:
    return Path(filename).suffix.lower() in SPREADSHEET_EXTS or mime.lower() in SPREADSHEET_MIMES


def _json_cell(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)


def _trim_rows(rows: list[list], offset: int, limit: int) -> tuple[list[list], int, int, bool]:
    total_rows = len(rows)
    total_columns = max((len(row) for row in rows), default=0)
    page = [
        [_json_cell(value) for value in row[:PREVIEW_MAX_COLUMNS]]
        for row in rows[offset:offset + limit]
    ]
    return page, total_rows, total_columns, total_columns > PREVIEW_MAX_COLUMNS


def _csv_preview(path: Path, offset: int, limit: int) -> dict:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    if path.suffix.lower() == ".csv":
        with suppress(csv.Error):
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    page, total_rows, total_columns, columns_truncated = _trim_rows(rows, offset, limit)
    return {
        "sheetNames": ["Sheet 1"], "activeSheet": "Sheet 1", "rows": page,
        "offset": offset, "limit": limit, "totalRows": total_rows,
        "totalColumns": total_columns, "columnsTruncated": columns_truncated,
    }


def preview(path: Path, requested_sheet: str | None, offset: int, limit: int) -> dict:
    offset = max(0, offset)
    limit = max(1, min(limit, PREVIEW_MAX_ROWS_PER_PAGE))
    if path.suffix.lower() in {".csv", ".tsv"}:
        return _csv_preview(path, offset, limit)

    try:
        from python_calamine import CalamineWorkbook
    except ImportError as exc:
        raise RuntimeError("spreadsheet preview support is not installed") from exc

    workbook = CalamineWorkbook.from_path(str(path))
    sheet_names = list(workbook.sheet_names)
    if not sheet_names:
        return {
            "sheetNames": [], "activeSheet": None, "rows": [], "offset": 0,
            "limit": limit, "totalRows": 0, "totalColumns": 0, "columnsTruncated": False,
        }
    active_sheet = requested_sheet if requested_sheet in sheet_names else sheet_names[0]
    rows = workbook.get_sheet_by_name(active_sheet).to_python(skip_empty_area=False)
    page, total_rows, total_columns, columns_truncated = _trim_rows(rows, offset, limit)
    return {
        "sheetNames": sheet_names, "activeSheet": active_sheet, "rows": page,
        "offset": offset, "limit": limit, "totalRows": total_rows,
        "totalColumns": total_columns, "columnsTruncated": columns_truncated,
    }
