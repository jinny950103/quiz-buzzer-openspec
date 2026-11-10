import io

import pytest
from openpyxl import Workbook, load_workbook

from app.guided_notes import GuidedNotesError, export_workbook, parse_workbook
from conftest import build_notes


def _cells(questions):
    return {q.number: [b.cell for b in q.blanks] for q in questions}


# 2.1 表頭定位


def test_finds_header_in_both_samples(single_bytes, group_bytes):
    assert parse_workbook(single_bytes)
    assert parse_workbook(group_bytes)


def test_missing_header_is_rejected():
    wb = Workbook()
    wb.active["A1"] = "沒有表頭的工作表"
    wb.active["A2"] = 1
    out = io.BytesIO()
    wb.save(out)
    with pytest.raises(GuidedNotesError, match="找不到題號或作答表頭"):
        parse_workbook(out.getvalue())


# 2.2 題目與填空格解析


def test_single_sample_has_six_single_blank_questions(single_bytes):
    questions = parse_workbook(single_bytes)
    assert [q.number for q in questions] == ["1", "2", "3", "4", "5", "6"]
    assert _cells(questions) == {
        "1": ["G5"], "2": ["G7"], "3": ["G9"], "4": ["G11"], "5": ["G13"], "6": ["G15"],
    }
    assert all(b.label == "" for q in questions for b in q.blanks)


def test_group_sample_detects_multi_blank_questions(group_bytes):
    questions = parse_workbook(group_bytes)
    assert _cells(questions) == {
        "1": ["G5", "G6"], "2": ["G8", "G9"], "3": ["G11"], "4": ["G13"],
    }
    assert [b.label for b in questions[0].blanks] == ["（1）", "（2）"]


# 2.3 位置不同的學習單（證明未寫死儲存格）


def test_header_at_other_position():
    data = build_notes(
        header_row=8, number_col=1, answer_col=5,
        rows=[
            (1, "第一題", None),
            (None, None, None),
            (2, "第二題-1", "（1）"),
            (None, "第二題-2", "（2）"),
            (None, "第二題-3", "（3）"),
            (None, None, None),
            ("3", "第三題", None),
        ],
    )
    questions = parse_workbook(data)
    assert _cells(questions) == {"1": ["E9"], "2": ["E11", "E12", "E13"], "3": ["E15"]}


def test_question_count_matches_notes():
    rows = []
    for n in range(1, 11):
        rows += [(n, f"題目{n}", None), (None, None, None)]
    questions = parse_workbook(build_notes(3, 2, 6, rows))
    assert [q.number for q in questions] == [str(n) for n in range(1, 11)]


# 2.4 無效輸入


def test_non_xlsx_is_rejected():
    with pytest.raises(GuidedNotesError, match="檔案格式錯誤"):
        parse_workbook("這不是 Excel".encode("utf-8"))


def test_corrupted_xlsx_is_rejected(single_bytes):
    with pytest.raises(GuidedNotesError, match="檔案格式錯誤"):
        parse_workbook(single_bytes[: len(single_bytes) // 2])


def test_header_without_numbers_is_rejected():
    data = build_notes(2, 1, 4, [(None, "沒有題號", None)])
    with pytest.raises(GuidedNotesError, match="找不到任何題號"):
        parse_workbook(data)


def test_duplicate_numbers_are_rejected():
    data = build_notes(2, 1, 4, [(1, "a", None), (None, None, None), (1, "b", None)])
    with pytest.raises(GuidedNotesError, match="題號重複"):
        parse_workbook(data)


# 3.1 匯出


def _values(data):
    ws = load_workbook(io.BytesIO(data)).active
    return {c.coordinate: c.value for row in ws.iter_rows() for c in row}, ws


def test_export_single_sample_round_trip(single_bytes):
    questions = parse_workbook(single_bytes)
    exported = export_workbook(single_bytes, questions, {"1": ["CPU"], "4": ["作業系統"]})
    before, ws_before = _values(single_bytes)
    after, ws_after = _values(exported)
    assert after["G5"] == "CPU"
    assert after["G11"] == "作業系統"
    assert after["G7"] is None
    changed = {k for k in after if after[k] != before.get(k)}
    assert changed == {"G5", "G11"}
    assert {str(r) for r in ws_after.merged_cells.ranges} == {str(r) for r in ws_before.merged_cells.ranges}


def test_export_group_sample_replaces_placeholders(group_bytes):
    questions = parse_workbook(group_bytes)
    exported = export_workbook(group_bytes, questions, {"1": ["CPU", "作業系統"], "3": ["演算法"]})
    after, _ = _values(exported)
    assert after["G5"] == "CPU"
    assert after["G6"] == "作業系統"
    assert after["G11"] == "演算法"
    # 無人搶答：保留原本佔位文字
    assert after["G8"] == "（1）"
    assert after["G9"] == "（2）"


def test_exported_file_can_be_reimported(group_bytes):
    questions = parse_workbook(group_bytes)
    exported = export_workbook(group_bytes, questions, {"2": ["A", "B"]})
    assert _cells(parse_workbook(exported)) == _cells(questions)
