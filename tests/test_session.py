import json
import threading

import pytest

from app.session import CLOSED, OPEN, PREPARING, QuizError, QuizSession


@pytest.fixture
def session(single_bytes):
    s = QuizSession()
    s.import_notes(single_bytes, "notes.xlsx")
    return s


@pytest.fixture
def open_group_session(group_bytes):
    s = QuizSession()
    s.import_notes(group_bytes, "group.xlsx")
    s.open()
    return s


def _error(fn, *args):
    with pytest.raises(QuizError) as info:
        fn(*args)
    return info.value


# 4.1 狀態機


def test_lifecycle(session):
    assert session.phase == PREPARING
    session.open()
    assert session.phase == OPEN
    session.close()
    assert session.phase == CLOSED
    session.reset()
    assert session.phase == PREPARING
    assert len(session.questions) == 6


def test_cannot_open_without_questions():
    assert _error(QuizSession().open).code == "no_questions"


@pytest.mark.parametrize("action", ["close", "reset", "export"])
def test_invalid_transitions_from_preparing(session, action):
    assert _error(getattr(session, action)).code == "wrong_phase"
    assert session.phase == PREPARING


def test_invalid_transitions_while_open(session, single_bytes):
    session.open()
    for fn, args in [(session.open, ()), (session.reset, ()), (session.export, ()),
                     (session.import_notes, (single_bytes,)), (session.set_group_count, (3,))]:
        assert _error(fn, *args).code == "wrong_phase"
    assert session.phase == OPEN


def test_invalid_transitions_when_closed(session, single_bytes):
    session.open()
    session.close()
    for fn, args in [(session.open, ()), (session.close, ()),
                     (session.import_notes, (single_bytes,)), (session.set_group_count, (3,))]:
        assert _error(fn, *args).code == "wrong_phase"
    assert session.phase == CLOSED


def test_group_count_rules(session):
    assert session.group_count == 6
    session.set_group_count(4)
    assert session.group_count == 4
    for bad in (0, 21, "3", 2.5, True):
        assert _error(session.set_group_count, bad).code == "invalid_group_count"
    assert session.group_count == 4


def test_reimport_replaces_questions_and_clears_answers(session, group_bytes):
    session.open()
    session.submit(1, "1", ["CPU"])
    session.close()
    session.reset()
    assert session.teacher_snapshot()["results"][0]["entries"] == []
    session.import_notes(group_bytes)
    assert [q.number for q in session.questions] == ["1", "2", "3", "4"]


def test_invalid_import_keeps_existing(session):
    assert _error(session.import_notes, b"bad").code == "invalid_file"
    assert len(session.questions) == 6


def test_version_increments_on_change(session):
    v = session.version
    session.open()
    assert session.version == v + 1


# 4.2 送出答案驗證


def test_submit_single_and_group(open_group_session):
    s = open_group_session
    sub = s.submit(2, "1", [" CPU ", "作業系統"])
    assert sub.answers == ["CPU", "作業系統"]
    assert sub.rank == 1


@pytest.mark.parametrize("group, number, answers, code", [
    (None, "3", ["x"], "invalid_group"),
    (0, "3", ["x"], "invalid_group"),
    (7, "3", ["x"], "invalid_group"),
    (1, "99", ["x"], "invalid_question"),
    (1, "1", ["CPU"], "invalid_answer"),          # 題組少一格
    (1, "1", ["CPU", "  "], "invalid_answer"),    # 題組有空白
    (1, "3", [""], "invalid_answer"),
    (1, "3", ["x" * 201], "invalid_answer"),
    (1, "3", "x", "invalid_answer"),
    (1, "3", [3], "invalid_answer"),
])
def test_submit_rejections_do_not_change_state(open_group_session, group, number, answers, code):
    s = open_group_session
    before = s.teacher_snapshot()
    assert _error(s.submit, group, number, answers).code == code
    assert s.teacher_snapshot() == before


def test_submit_rejected_outside_open(session):
    assert _error(session.submit, 1, "1", ["x"]).code == "wrong_phase"
    session.open()
    session.close()
    assert _error(session.submit, 1, "1", ["x"]).code == "wrong_phase"


def test_same_group_cannot_submit_twice(session):
    session.open()
    session.submit(2, "1", ["CPU"])
    assert _error(session.submit, 2, "1", ["GPU"]).code == "already_submitted"
    entries = session.teacher_snapshot()["results"][0]["entries"]
    assert entries == [{"group": 2, "answers": ["CPU"], "rank": 1}]


def test_answer_length_limit_allows_200(session):
    session.open()
    assert session.submit(1, "1", ["字" * 200]).rank == 1


# 4.3 順位與快照


def test_first_come_first_served(session):
    session.open()
    session.submit(3, "1", ["CPU"])
    session.submit(1, "1", ["GPU"])
    result = session.teacher_snapshot()["results"][0]
    assert result["winner"] == 3
    assert [(e["group"], e["rank"]) for e in result["entries"]] == [(3, 1), (1, 2)]


def test_student_snapshot_hides_other_groups_while_open(session):
    session.open()
    session.submit(1, "1", ["SECRET-ANSWER"])
    snap = session.student_snapshot(2)
    assert snap["mine"] == {}
    assert snap["results"] is None
    assert "SECRET-ANSWER" not in json.dumps(snap, ensure_ascii=False)
    own = session.student_snapshot(1)
    assert own["mine"] == {"1": {"answers": ["SECRET-ANSWER"]}}
    assert "rank" not in json.dumps(own)


def test_student_version_ignores_other_groups(session):
    session.open()
    before = session.student_snapshot(2)["version"]
    session.submit(1, "1", ["x"])
    assert session.student_snapshot(2)["version"] == before
    session.submit(2, "1", ["y"])
    assert session.student_snapshot(2)["version"] != before


def test_results_visible_to_students_after_close(session):
    session.open()
    session.submit(2, "1", ["CPU"])
    session.submit(4, "1", ["GPU"])
    session.close()
    results = session.student_snapshot(1)["results"]
    assert results[0]["winner"] == 2
    assert results[0]["entries"][1] == {"group": 4, "answers": ["GPU"], "rank": 2}
    assert results[1] == {"number": "2", "winner": None, "entries": []}


def test_concurrent_submissions_get_unique_ranks(session):
    session.set_group_count(20)
    session.open()
    barrier = threading.Barrier(20)

    def worker(group):
        barrier.wait()
        session.submit(group, "1", [f"答案{group}"])

    threads = [threading.Thread(target=worker, args=(g,)) for g in range(1, 21)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    entries = session.teacher_snapshot()["results"][0]["entries"]
    assert sorted(e["rank"] for e in entries) == list(range(1, 21))
    assert sum(1 for e in entries if e["rank"] == 1) == 1


def test_export_uses_winning_answers(group_bytes):
    from io import BytesIO
    from openpyxl import load_workbook

    s = QuizSession()
    s.import_notes(group_bytes, "題組.xlsx")
    s.open()
    s.submit(5, "1", ["CPU", "作業系統"])
    s.submit(2, "1", ["X", "Y"])
    s.close()
    data, name = s.export()
    ws = load_workbook(BytesIO(data)).active
    assert (ws["G5"].value, ws["G6"].value) == ("CPU", "作業系統")
    assert name == "題組_搶答結果.xlsx"
