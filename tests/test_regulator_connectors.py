from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from financial_registry.connectors.ecb import ECBConnector
from financial_registry.connectors.fdic import FDICConnector
from financial_registry.snapshots import FilesystemSnapshotStore


class _FakeResponse:
    def __init__(self, payload=None, content=b""):
        self.payload = payload
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, *, params=None):
        self.calls.append((url, params.copy() if params else None))
        return next(self.responses)


def _fdic_payload(rows, total):
    return {"meta": {"total": total}, "data": [{"data": row, "score": 1} for row in rows]}


def _cell(column, row, value):
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<c r="{column}{row}" t="inlineStr"><is><t>{escaped}</t></is></c>'


def _sheet(rows):
    xml_rows = []
    for row_number, cells in enumerate(rows, start=1):
        xml_rows.append(
            f'<row r="{row_number}">' + "".join(_cell(column, row_number, value) for column, value in cells.items()) + "</row>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        + "".join(xml_rows)
        + "</sheetData></worksheet>"
    ).encode()


def _xlsx(sheet_rows):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for index, rows in enumerate(sheet_rows, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet(rows))
    return output.getvalue()


def test_fdic_fetches_pages_and_normalizes_bank_classification(tmp_path):
    lei = "54930000000000000001"
    row = {
        "ID": "100",
        "CERT": "100",
        "LEI": lei,
        "NAME": "Example National Bank",
        "STALP": "NY",
        "ACTIVE": 1,
        "BKCLASS": "N",
        "WEBADDR": "https://www.examplebank.test/",
    }
    second_row = {
        "ID": "101",
        "CERT": "101",
        "LEI": "",
        "NAME": "Example Savings Bank",
        "STALP": "CA",
        "ACTIVE": 1,
        "BKCLASS": "SB",
        "WEBADDR": "example-savings.test",
    }
    client = _FakeClient(
        [
            _FakeResponse(_fdic_payload([row], 2)),
            _FakeResponse(_fdic_payload([second_row], 2)),
        ]
    )
    retrieved_at = datetime(2026, 8, 27, tzinfo=timezone.utc)
    connector = FDICConnector(
        FilesystemSnapshotStore(tmp_path / "snapshots"),
        client=client,
        page_size=1,
        max_records=None,
        clock=lambda: retrieved_at,
    )

    snapshot = connector.fetch()
    candidates = connector.normalize(snapshot)

    assert connector.definition.id == "src_fdic_bankfind"
    assert snapshot.retrieved_at == retrieved_at
    assert len(candidates) == 2
    assert candidates[0].legal_name == "Example National Bank"
    assert candidates[0].country_code == "US"
    assert candidates[0].categories == ["commercial_bank"]
    assert candidates[0].regulator_identifier == "100"
    assert candidates[0].domains == ["examplebank.test"]
    assert {identifier.type for identifier in candidates[0].identifiers} == {"fdic_id", "fdic_cert", "lei"}
    assert candidates[1].categories == ["savings_bank"]
    assert [call[1]["offset"] for call in client.calls] == [0, 1]
    assert all(call[1]["filters"] == "ACTIVE:1" for call in client.calls)


def test_fdic_fetch_respects_max_records(tmp_path):
    rows = [
        {
            "ID": str(number),
            "CERT": str(number),
            "NAME": f"Bank {number}",
            "STALP": "NY",
            "ACTIVE": 1,
            "BKCLASS": "NM",
        }
        for number in range(1, 4)
    ]
    client = _FakeClient([_FakeResponse(_fdic_payload(rows[:2], 3)), _FakeResponse(_fdic_payload(rows[2:], 3))])
    connector = FDICConnector(
        FilesystemSnapshotStore(tmp_path / "snapshots"),
        client=client,
        page_size=2,
        max_records=3,
    )

    candidates = connector.normalize(connector.fetch())

    assert len(candidates) == 3
    assert [candidate.source_record_id for candidate in candidates] == ["1", "2", "3"]


def test_ecb_discovers_current_workbook_and_normalizes_grouped_rows(tmp_path):
    workbook_url = "https://www.bankingsupervision.europa.eu/ecb/pub/pdf/ssm.listofsupervisedentities202608.en.xlsx"
    html = f'<a href="{workbook_url}">Download XLSX</a>'.encode()
    workbook = _xlsx(
        [
            [
                {"L": "Germany"},
                {
                    "C": "54930000000000000001",
                    "H": "CI",
                    "L": "Example Bank AG ; Example Bank Group AG",
                    "R": "Germany",
                },
            ],
            [
                {"J": "France"},
                {"B": "54930000000000000002", "F": "CI-B", "J": "Example Branch Bank"},
            ],
        ]
    )
    client = _FakeClient([_FakeResponse(content=html), _FakeResponse(content=workbook)])
    connector = ECBConnector(
        FilesystemSnapshotStore(tmp_path / "snapshots"),
        client=client,
        max_records=None,
    )

    candidates = connector.normalize(connector.fetch())

    assert connector.definition.id == "src_ecb_supervised"
    assert [call[0] for call in client.calls] == [connector.index_url, workbook_url]
    assert candidates[0].legal_name == "Example Bank AG"
    assert candidates[0].aliases == ["Example Bank Group AG"]
    assert candidates[0].country_code == "DE"
    assert candidates[0].categories == ["commercial_bank"]
    assert candidates[0].source_uri == workbook_url
    assert candidates[1].country_code == "FR"
    assert candidates[1].categories == ["foreign_branch"]
    assert candidates[1].identifiers[0].type == "lei"


def test_ecb_max_records_bounds_normalization(tmp_path):
    workbook = _xlsx(
        [
            [{"L": "Germany"}, {"C": "54930000000000000001", "H": "CI", "L": "First Bank"}],
            [{"J": "Germany"}, {"B": "54930000000000000002", "F": "CI", "J": "Second Bank"}],
        ]
    )
    connector = ECBConnector(
        FilesystemSnapshotStore(tmp_path / "snapshots"),
        client=_FakeClient([_FakeResponse(content=workbook)]),
        workbook_url="https://www.bankingsupervision.europa.eu/ecb/pub/pdf/current.xlsx",
        max_records=1,
    )

    candidates = connector.normalize(connector.fetch())

    assert len(candidates) == 1
    assert candidates[0].legal_name == "First Bank"
