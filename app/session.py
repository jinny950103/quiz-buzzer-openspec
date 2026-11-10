"""搶答活動的狀態機、作答紀錄與順位判定（不依賴 HTTP）。"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass

from .guided_notes import GuidedNotesError, Question, export_workbook, parse_workbook

PREPARING = "preparing"
OPEN = "open"
CLOSED = "closed"

MIN_GROUPS = 1
MAX_GROUPS = 20
DEFAULT_GROUPS = 6
MAX_ANSWER_LENGTH = 200


class QuizError(Exception):
    """可回報給使用者的操作錯誤。"""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class Submission:
    group: int
    answers: list[str]
    rank: int
    seq: int


class QuizSession:
    def __init__(self):
        self._lock = threading.Lock()
        self.epoch = secrets.token_hex(4)
        self.phase = PREPARING
        self.group_count = DEFAULT_GROUPS
        self.questions: list[Question] = []
        self.filename: str | None = None
        self._source: bytes | None = None
        self._submissions: dict[str, list[Submission]] = {}
        self._seq = 0
        self.version = 0

    # ---- 老師操作 -------------------------------------------------------

    def import_notes(self, data: bytes, filename: str | None = None) -> None:
        with self._lock:
            self._require_phase(PREPARING, "只能在準備中階段匯入 Guided Notes。")
            try:
                questions = parse_workbook(data)
            except GuidedNotesError as exc:
                raise QuizError("invalid_file", str(exc)) from exc
            self.questions = questions
            self.filename = filename
            self._source = data
            self._clear_submissions()
            self._touch()

    def set_group_count(self, count) -> None:
        with self._lock:
            self._require_phase(PREPARING, "只能在準備中階段設定組別數量。")
            if isinstance(count, bool) or not isinstance(count, int) or not MIN_GROUPS <= count <= MAX_GROUPS:
                raise QuizError(
                    "invalid_group_count", f"組別數量必須是 {MIN_GROUPS} 到 {MAX_GROUPS} 之間的整數。"
                )
            self.group_count = count
            self._touch()

    def open(self) -> None:
        with self._lock:
            self._require_phase(PREPARING, "只能從準備中階段開啟搶答。")
            if not self.questions:
                raise QuizError("no_questions", "請先匯入 Guided Notes 再開啟搶答。", 409)
            self.phase = OPEN
            self._touch()

    def close(self) -> None:
        with self._lock:
            self._require_phase(OPEN, "只能在搶答中結束搶答。")
            self.phase = CLOSED
            self._touch()

    def reset(self) -> None:
        with self._lock:
            self._require_phase(CLOSED, "只能在搶答結束後重置活動。")
            self.phase = PREPARING
            self._clear_submissions()
            self._touch()

    def export(self) -> tuple[bytes, str]:
        with self._lock:
            self._require_phase(CLOSED, "請先結束搶答再匯出。")
            winners = {
                number: entries[0].answers for number, entries in self._submissions.items() if entries
            }
            data = export_workbook(self._source, self.questions, winners)
            name = self.filename or "guided-notes.xlsx"
            stem = name[:-5] if name.lower().endswith(".xlsx") else name
            return data, f"{stem}_搶答結果.xlsx"

    # ---- 學生操作 -------------------------------------------------------

    def submit(self, group, number, answers) -> Submission:
        with self._lock:
            if self.phase != OPEN:
                raise QuizError("wrong_phase", "目前不在搶答時間。", 409)
            group = self._check_group(group)
            question = self._question(number)
            if not isinstance(answers, list) or len(answers) != len(question.blanks):
                raise QuizError("invalid_answer", f"此題需要 {len(question.blanks)} 個答案。")
            cleaned = []
            for answer in answers:
                if not isinstance(answer, str) or not answer.strip():
                    raise QuizError("invalid_answer", "所有填空皆須填寫。")
                answer = answer.strip()
                if len(answer) > MAX_ANSWER_LENGTH:
                    raise QuizError("invalid_answer", f"答案不可超過 {MAX_ANSWER_LENGTH} 字。")
                cleaned.append(answer)
            entries = self._submissions.setdefault(question.number, [])
            if any(entry.group == group for entry in entries):
                raise QuizError("already_submitted", "本組已送出此題。", 409)
            self._seq += 1
            submission = Submission(group=group, answers=cleaned, rank=len(entries) + 1, seq=self._seq)
            entries.append(submission)
            self._touch()
            return submission

    # ---- 狀態快照 -------------------------------------------------------

    def teacher_snapshot(self) -> dict:
        with self._lock:
            return {
                "role": "teacher",
                "epoch": self.epoch,
                "version": self.version,
                "phase": self.phase,
                "group_count": self.group_count,
                "filename": self.filename,
                "questions": self._question_list(),
                "results": self._results(),
            }

    def student_snapshot(self, group=None) -> dict:
        with self._lock:
            if group is not None:
                group = self._check_group(group)
            mine = {}
            if group is not None:
                for number, entries in self._submissions.items():
                    for entry in entries:
                        if entry.group == group:
                            mine[number] = {"answers": entry.answers}
            snapshot = {
                "role": "student",
                "epoch": self.epoch,
                "phase": self.phase,
                "group_count": self.group_count,
                "group": group,
                "questions": self._question_list(),
                "mine": mine,
                "results": self._results() if self.phase == CLOSED else None,
            }
            # 學生端版本號只由自己看得到的內容決定，避免透露他組作答動態。
            digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            snapshot["version"] = digest[:16]
            return snapshot

    # ---- 內部 -----------------------------------------------------------

    def _touch(self):
        self.version += 1

    def _clear_submissions(self):
        self._submissions = {}
        self._seq = 0

    def _require_phase(self, phase, message):
        if self.phase != phase:
            raise QuizError("wrong_phase", message, 409)

    def _check_group(self, group) -> int:
        if isinstance(group, str) and group.strip().isdigit():
            group = int(group)
        if isinstance(group, bool) or not isinstance(group, int) or not 1 <= group <= self.group_count:
            raise QuizError("invalid_group", "請先選擇有效的組別。")
        return group

    def _question(self, number) -> Question:
        for question in self.questions:
            if question.number == str(number):
                return question
        raise QuizError("invalid_question", "找不到這一題。")

    def _question_list(self):
        return [
            {"number": q.number, "blanks": [b.label for b in q.blanks]} for q in self.questions
        ]

    def _results(self):
        results = []
        for question in self.questions:
            entries = self._submissions.get(question.number, [])
            results.append({
                "number": question.number,
                "winner": entries[0].group if entries else None,
                "entries": [
                    {"group": e.group, "answers": e.answers, "rank": e.rank} for e in entries
                ],
            })
        return results
