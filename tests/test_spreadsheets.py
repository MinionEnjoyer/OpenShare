from pathlib import Path

import pytest

import main
import spreadsheets
from conftest import OpenShareHarness


pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("filename", "mime"),
    [
        ("workbook.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("budget.xlsm", "application/vnd.ms-excel.sheet.macroenabled.12"),
        ("archive.xls", "application/vnd.ms-excel"),
        ("analytics.xlsb", "application/vnd.ms-excel.sheet.binary.macroenabled.12"),
        ("planning.ods", "application/vnd.oasis.opendocument.spreadsheet"),
        ("data.csv", "text/csv"),
        ("data.tsv", "text/tab-separated-values"),
    ],
)
def test_spreadsheet_formats_are_classified(filename: str, mime: str):
    assert main.classify_upload(filename, mime)[0] == "spreadsheet"


def test_csv_upload_uses_spreadsheet_viewer_and_bounded_preview(harness: OpenShareHarness):
    content = b"name,score,active\nAda,99,true\nGrace,98,true\n"
    saved = harness.upload(("scores.csv", content, "text/csv")).json()["saved"][0]

    viewer = harness.client.get(f"/ss/{saved['id']}")
    preview = harness.client.get(
        f"/api/spreadsheets/{saved['id']}?offset=1&limit=1"
    )

    assert saved["media_type"] == "spreadsheet"
    assert viewer.status_code == 200
    assert '"spreadsheetUrl"' in viewer.text
    assert preview.status_code == 200
    assert preview.json() == {
        "sheetNames": ["Sheet 1"],
        "activeSheet": "Sheet 1",
        "rows": [["Ada", "99", "true"]],
        "offset": 1,
        "limit": 1,
        "totalRows": 3,
        "totalColumns": 3,
        "columnsTruncated": False,
    }


def test_binary_workbook_preview_uses_selected_sheet_and_page(
    harness: OpenShareHarness, monkeypatch: pytest.MonkeyPatch
):
    saved = harness.upload((
        "planning.xlsx",
        b"not parsed because the adapter is isolated in this route test",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )).json()["saved"][0]
    calls = []

    def fake_preview(path: Path, sheet: str | None, offset: int, limit: int):
        calls.append((path.name, sheet, offset, limit))
        return {
            "sheetNames": ["Overview", "Costs"], "activeSheet": "Costs",
            "rows": [[42]], "offset": offset, "limit": limit,
            "totalRows": 201, "totalColumns": 1, "columnsTruncated": False,
        }

    monkeypatch.setattr(main.spreadsheets, "preview", fake_preview)
    response = harness.client.get(
        f"/api/spreadsheets/{saved['id']}?sheet=Costs&offset=200&limit=500"
    )

    assert response.status_code == 200
    assert response.json()["activeSheet"] == "Costs"
    assert calls == [(f"{saved['id']}.xlsx", "Costs", 200, 500)]


def test_csv_preview_caps_columns_and_page_size(tmp_path: Path):
    path = tmp_path / "wide.csv"
    path.write_text(",".join(str(index) for index in range(110)) + "\n", encoding="utf-8")

    result = spreadsheets.preview(path, None, 0, 500)

    assert result["limit"] == 200
    assert result["totalColumns"] == 110
    assert result["columnsTruncated"] is True
    assert len(result["rows"][0]) == 100
