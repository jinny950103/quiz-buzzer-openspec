import io
import json

import pytest
from openpyxl import load_workbook

from app import create_app

KEY = "test-teacher-key"
HEAD = {"X-Teacher-Key": KEY}


@pytest.fixture
def client():
    return create_app(KEY).test_client()


def _import(client, data, name="notes.xlsx", headers=HEAD):
    return client.post(
        "/api/teacher/import",
        data={"file": (io.BytesIO(data), name)},
        headers=headers,
        content_type="multipart/form-data",
    )


def _submit(client, group, question, answers):
    return client.post("/api/student/submit", json={"group": group, "question": question, "answers": answers})


def test_full_flow(client, group_bytes):
    r = _import(client, group_bytes, "題組.xlsx")
    assert r.status_code == 200
    assert [q["number"] for q in r.get_json()["questions"]] == ["1", "2", "3", "4"]
    assert client.post("/api/teacher/groups", json={"count": 3}, headers=HEAD).status_code == 200
    assert client.post("/api/teacher/open", headers=HEAD).get_json()["phase"] == "open"

    assert _submit(client, 2, "1", ["CPU", "作業系統"]).status_code == 200
    r = _submit(client, 1, "1", ["GPU", "Linux"])
    assert r.get_json()["mine"] == {"1": {"answers": ["GPU", "Linux"]}}
    assert _submit(client, 1, "3", ["演算法"]).status_code == 200

    teacher = client.get("/api/teacher/state", headers=HEAD).get_json()
    assert teacher["results"][0]["winner"] == 2

    assert client.post("/api/teacher/close", headers=HEAD).get_json()["phase"] == "closed"
    student = client.get("/api/student/state?group=1").get_json()
    assert student["results"][0]["winner"] == 2

    r = client.get("/api/teacher/export", headers=HEAD)
    assert r.status_code == 200
    assert "filename*=UTF-8''" in r.headers["Content-Disposition"]
    ws = load_workbook(io.BytesIO(r.data)).active
    assert (ws["G5"].value, ws["G6"].value, ws["G11"].value) == ("CPU", "作業系統", "演算法")
    assert ws["G8"].value == "（1）"

    assert client.post("/api/teacher/reset", headers=HEAD).get_json()["phase"] == "preparing"


TEACHER_CALLS = [
    ("get", "/api/teacher/state", {}),
    ("post", "/api/teacher/groups", {"json": {"count": 2}}),
    ("post", "/api/teacher/open", {}),
    ("post", "/api/teacher/close", {}),
    ("post", "/api/teacher/reset", {}),
    ("get", "/api/teacher/export", {}),
]


@pytest.mark.parametrize("headers", [{}, {"X-Teacher-Key": "wrong"}])
@pytest.mark.parametrize("method, path, kwargs", TEACHER_CALLS)
def test_teacher_api_requires_key(client, single_bytes, headers, method, path, kwargs):
    _import(client, single_bytes)
    before = client.get("/api/teacher/state", headers=HEAD).get_json()
    r = getattr(client, method)(path, headers=headers, **kwargs)
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "forbidden"
    assert client.get("/api/teacher/state", headers=HEAD).get_json() == before


def test_import_requires_key(client, single_bytes):
    assert _import(client, single_bytes, headers={}).status_code == 403
    assert client.get("/api/teacher/state", headers=HEAD).get_json()["questions"] == []


def test_teacher_page_requires_key(client):
    assert client.get("/teacher").status_code == 403
    assert client.get("/teacher?key=wrong").status_code == 403
    assert client.get(f"/teacher?key={KEY}").status_code == 200


def test_student_page_has_no_teacher_controls(client):
    html = client.get("/").get_data(as_text=True)
    for word in ("開啟搶答", "結束搶答", "匯出", "匯入"):
        assert word not in html


def test_student_state_hides_other_groups(client, single_bytes):
    _import(client, single_bytes)
    client.post("/api/teacher/open", headers=HEAD)
    _submit(client, 1, "1", ["TOP-SECRET"])
    for url in ("/api/student/state?group=2", "/api/student/state"):
        body = client.get(url).get_data(as_text=True)
        assert "TOP-SECRET" not in json.loads(body).__repr__()
        assert "TOP-SECRET" not in body


def test_error_format_and_no_store(client, single_bytes):
    r = _import(client, b"not excel", "x.xlsx")
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "invalid_file"
    assert r.headers["Cache-Control"] == "no-store"

    r = client.post("/api/teacher/open", headers=HEAD)
    assert (r.status_code, r.get_json()["error"]["code"]) == (409, "no_questions")

    _import(client, single_bytes)
    r = _submit(client, 1, "1", ["x"])
    assert (r.status_code, r.get_json()["error"]["code"]) == (409, "wrong_phase")

    r = client.post("/api/student/submit", data="[]", content_type="application/json")
    assert r.get_json()["error"]["code"] == "invalid_request"

    r = client.post("/api/teacher/groups", json={"count": 0}, headers=HEAD)
    assert r.get_json()["error"]["code"] == "invalid_group_count"

    r = client.get("/api/student/state?group=99")
    assert r.get_json()["error"]["code"] == "invalid_group"


def test_import_without_file(client):
    r = client.post("/api/teacher/import", headers=HEAD, data={}, content_type="multipart/form-data")
    assert r.get_json()["error"]["code"] == "invalid_file"
