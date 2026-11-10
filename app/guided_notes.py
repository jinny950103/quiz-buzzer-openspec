"""Guided Notes (.xlsx) 的匯入解析與答案匯出。

所有位置都由表頭（「題號」「作答」）動態決定，不寫死任何儲存格座標。
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

NUMBER_HEADER = "題號"
ANSWER_HEADER = "作答"
QUESTION_HEADER = "題目"


class GuidedNotesError(ValueError):
    """Guided Notes 無法匯入或匯出時拋出，訊息可直接顯示給老師。"""


@dataclass(frozen=True)
class Blank:
    sheet: str
    cell: str
    label: str = ""


@dataclass
class Question:
    number: str
    blanks: list[Blank] = field(default_factory=list)


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _number_of(value) -> str | None:
    """把題號欄的值轉成題號字串；不是數字則回傳 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    text = _text(value).rstrip(".、")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return str(int(number)) if number.is_integer() else text


def _load(data: bytes):
    try:
        return load_workbook(io.BytesIO(data))
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise GuidedNotesError("檔案格式錯誤，請上傳有效的 .xlsx Guided Notes。") from exc


def _merged_lookup(ws) -> dict[tuple[int, int], tuple[int, int, int, int]]:
    """(row, col) -> 所屬合併範圍 (min_row, min_col, max_row, max_col)。"""
    lookup = {}
    for rng in ws.merged_cells.ranges:
        bounds = (rng.min_row, rng.min_col, rng.max_row, rng.max_col)
        for row in range(rng.min_row, rng.max_row + 1):
            for col in range(rng.min_col, rng.max_col + 1):
                lookup[(row, col)] = bounds
    return lookup


def _find_header(ws):
    """回傳 (表頭列, 題號欄, 作答欄, 題目欄或 None)；找不到回傳 None。"""
    for row in ws.iter_rows():
        number_col = answer_col = question_col = None
        for cell in row:
            text = _text(cell.value).replace(" ", "")
            if not text:
                continue
            if number_col is None and NUMBER_HEADER in text:
                number_col = cell.column
            elif answer_col is None and ANSWER_HEADER in text:
                answer_col = cell.column
            elif question_col is None and QUESTION_HEADER in text:
                question_col = cell.column
        if number_col is not None and answer_col is not None:
            return row[0].row, number_col, answer_col, question_col
    return None


def _parse_sheet(ws, header) -> list[Question]:
    header_row, number_col, answer_col, question_col = header
    merged = _merged_lookup(ws)

    def value_at(row, col):
        bounds = merged.get((row, col))
        if bounds:
            row, col = bounds[0], bounds[1]
        return ws.cell(row=row, column=col).value

    questions: list[Question] = []
    current: Question | None = None
    current_number_bounds = None
    used_cells: set[str] = set()

    def add_blank(question: Question, row: int):
        bounds = merged.get((row, answer_col))
        anchor_row, anchor_col = (bounds[0], bounds[1]) if bounds else (row, answer_col)
        coord = f"{get_column_letter(anchor_col)}{anchor_row}"
        if coord in used_cells:
            return
        used_cells.add(coord)
        label = _text(ws.cell(row=anchor_row, column=anchor_col).value)
        question.blanks.append(Blank(sheet=ws.title, cell=coord, label=label))

    for row in range(header_row + 1, ws.max_row + 1):
        number_bounds = merged.get((row, number_col))
        in_current_number = (
            current is not None
            and current_number_bounds is not None
            and number_bounds == current_number_bounds
        )
        raw_number = None if in_current_number else ws.cell(row=row, column=number_col).value
        number = _number_of(raw_number)

        if number is not None:
            current = Question(number=number)
            current_number_bounds = number_bounds
            questions.append(current)
            add_blank(current, row)
            continue

        if question_col is not None:
            has_content = bool(_text(value_at(row, question_col)))
        else:
            has_content = bool(_text(value_at(row, answer_col)))
        number_blank = in_current_number or not _text(raw_number)

        if current is not None and number_blank and has_content:
            add_blank(current, row)
        else:
            current = None
            current_number_bounds = None

    return questions


def parse_workbook(data: bytes) -> list[Question]:
    """解析 Guided Notes，回傳題目清單（依學習單中出現順序）。"""
    wb = _load(data)
    for ws in wb.worksheets:
        header = _find_header(ws)
        if header is None:
            continue
        questions = _parse_sheet(ws, header)
        if not questions:
            raise GuidedNotesError("表頭下方找不到任何題號，請確認題號欄為數字。")
        numbers = [q.number for q in questions]
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1}, key=numbers.index)
        if duplicates:
            raise GuidedNotesError(f"題號重複：{', '.join(duplicates)}。")
        return questions
    raise GuidedNotesError("找不到題號或作答表頭，請確認學習單含有「題號」與「作答」欄。")


def export_workbook(data: bytes, questions: list[Question], answers: dict[str, list[str]]) -> bytes:
    """將 answers（題號 -> 各填空答案）寫入原檔的填空格，回傳新的 .xlsx bytes。"""
    wb = _load(data)
    for question in questions:
        filled = answers.get(question.number)
        if not filled:
            continue
        for blank, answer in zip(question.blanks, filled):
            wb[blank.sheet][blank.cell].value = answer
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
