"""課堂搶答系統的 Flask 應用（HTTP 層，只負責輸入驗證與序列化）。"""

from __future__ import annotations

import hmac
import io
from functools import wraps
from urllib.parse import quote

from flask import Flask, abort, jsonify, render_template, request, send_file

from .session import QuizError, QuizSession

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def create_app(teacher_key: str, session: QuizSession | None = None) -> Flask:
    if not teacher_key:
        raise ValueError("teacher_key 不可為空")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    quiz = session or QuizSession()
    app.extensions["quiz_session"] = quiz

    def key_ok(key: str | None) -> bool:
        return bool(key) and hmac.compare_digest(key.encode(), teacher_key.encode())

    def error(code: str, message: str, status: int):
        return jsonify({"error": {"code": code, "message": message}}), status

    def teacher_only(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not key_ok(request.headers.get("X-Teacher-Key")):
                return error("forbidden", "老師金鑰錯誤或缺少，無法存取。", 403)
            return view(*args, **kwargs)
        return wrapper

    @app.errorhandler(QuizError)
    def handle_quiz_error(exc: QuizError):
        return error(exc.code, exc.message, exc.status)

    @app.errorhandler(413)
    def handle_too_large(_exc):
        return error("invalid_file", "檔案太大，請上傳 10MB 以內的 .xlsx。", 413)

    @app.after_request
    def no_store(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    def json_body() -> dict:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise QuizError("invalid_request", "請求內容必須是 JSON 物件。")
        return body

    # ---- 頁面 -----------------------------------------------------------

    @app.get("/")
    def student_page():
        return render_template("student.html")

    @app.get("/teacher")
    def teacher_page():
        if not key_ok(request.args.get("key")):
            abort(403)
        return render_template("teacher.html")

    # ---- 學生 API --------------------------------------------------------

    @app.get("/api/student/state")
    def student_state():
        group = request.args.get("group") or None
        return jsonify(quiz.student_snapshot(group))

    @app.post("/api/student/submit")
    def student_submit():
        body = json_body()
        quiz.submit(body.get("group"), body.get("question"), body.get("answers"))
        return jsonify(quiz.student_snapshot(body.get("group")))

    # ---- 老師 API --------------------------------------------------------

    @app.get("/api/teacher/state")
    @teacher_only
    def teacher_state():
        return jsonify(quiz.teacher_snapshot())

    @app.post("/api/teacher/import")
    @teacher_only
    def teacher_import():
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            raise QuizError("invalid_file", "請選擇要上傳的 .xlsx 檔案。")
        quiz.import_notes(upload.read(), upload.filename)
        return jsonify(quiz.teacher_snapshot())

    @app.post("/api/teacher/groups")
    @teacher_only
    def teacher_groups():
        quiz.set_group_count(json_body().get("count"))
        return jsonify(quiz.teacher_snapshot())

    @app.post("/api/teacher/<action>")
    @teacher_only
    def teacher_phase(action):
        actions = {"open": quiz.open, "close": quiz.close, "reset": quiz.reset}
        if action not in actions:
            abort(404)
        actions[action]()
        return jsonify(quiz.teacher_snapshot())

    @app.get("/api/teacher/export")
    @teacher_only
    def teacher_export():
        data, filename = quiz.export()
        response = send_file(
            io.BytesIO(data),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename,
        )
        response.headers["Content-Disposition"] = (
            f"attachment; filename=\"export.xlsx\"; filename*=UTF-8''{quote(filename)}"
        )
        return response

    return app
