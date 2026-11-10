import io
from pathlib import Path

import pytest
from openpyxl import Workbook

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
SINGLE_SAMPLE = SAMPLES / "軟工期末專案_單題_範例.xlsx"
GROUP_SAMPLE = SAMPLES / "軟工期末專案_題組_範例.xlsx"


@pytest.fixture
def single_bytes() -> bytes:
    return SINGLE_SAMPLE.read_bytes()


@pytest.fixture
def group_bytes() -> bytes:
    return GROUP_SAMPLE.read_bytes()


def build_notes(header_row: int, number_col: int, answer_col: int, rows: list[tuple]) -> bytes:
    """產生自訂位置的 Guided Notes：rows 為 (題號, 題目, 作答) 三元組，None 表示空白。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "學習單"
    question_col = number_col + 1
    ws.cell(row=1, column=1, value="自製測試學習單")
    ws.cell(row=header_row, column=number_col, value="題號")
    ws.cell(row=header_row, column=question_col, value="題目")
    ws.cell(row=header_row, column=answer_col, value="作答")
    for offset, (number, prompt, answer) in enumerate(rows, start=1):
        row = header_row + offset
        if number is not None:
            ws.cell(row=row, column=number_col, value=number)
        if prompt is not None:
            ws.cell(row=row, column=question_col, value=prompt)
        if answer is not None:
            ws.cell(row=row, column=answer_col, value=answer)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
