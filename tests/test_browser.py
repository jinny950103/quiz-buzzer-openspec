"""Playwright 端到端測試：老師 + 3 個學生視窗（2 組，其中第 1 組有 2 人）。"""

import io
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from openpyxl import load_workbook

from conftest import GROUP_SAMPLE

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "test-results"
SYNC_MS = 2000


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "app", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8",
    )
    teacher_url = None
    deadline = time.time() + 15
    while time.time() < deadline and teacher_url is None:
        line = proc.stdout.readline()
        match = re.search(r"(http://\S+/teacher\?key=\S+)", line)
        if match:
            teacher_url = match.group(1)
    if teacher_url is None:
        proc.kill()
        pytest.fail("伺服器未印出老師網址")
    # 持續讀掉伺服器輸出，避免管道塞滿使伺服器卡住。
    threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield {"base": base, "teacher": teacher_url}
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # 先用 Playwright 內建的 Chromium；若被系統擋住（例如 Windows 智慧型應用程式控制），
        # 改用電腦上已安裝的 Edge 或 Chrome。
        errors = []
        b = None
        for channel in (None, "msedge", "chrome"):
            try:
                b = p.chromium.launch(channel=channel) if channel else p.chromium.launch()
                break
            except Exception as exc:  # noqa: BLE001 - 收集錯誤後再嘗試下一個瀏覽器
                errors.append(f"{channel or 'chromium'}: {str(exc).splitlines()[0]}")
        if b is None:
            pytest.fail("無法啟動任何瀏覽器：\n" + "\n".join(errors))
        yield b
        b.close()


def _student(browser, base, group):
    context = browser.new_context()
    page = context.new_page()
    page.goto(base + "/")
    page.select_option("#group-select", str(group))
    page.wait_for_selector(f"text=目前身分：第 {group} 組")
    return context, page


def _no_horizontal_overflow(page):
    return page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_full_activity(server, browser):
    from playwright.sync_api import expect

    RESULTS.mkdir(exist_ok=True)
    teacher_ctx = browser.new_context(accept_downloads=True)
    teacher = teacher_ctx.new_page()
    teacher.on("dialog", lambda d: d.accept())
    teacher.goto(server["teacher"])
    expect(teacher.locator("#phase")).to_have_text("準備中")

    # 匯入題組範本並設定 2 組
    teacher.set_input_files("#file", str(GROUP_SAMPLE))
    teacher.click("#import-btn")
    expect(teacher.locator("#file-info")).to_contain_text("4 題")
    teacher.fill("#group-count", "2")
    teacher.click("#group-btn")
    expect(teacher.locator("#summary")).to_contain_text("2 組")

    ctx1, s1 = _student(browser, server["base"], 1)
    ctx1b, s1b = _student(browser, server["base"], 1)
    ctx2, s2 = _student(browser, server["base"], 2)
    for page in (s1, s1b, s2):
        expect(page.locator("text=等待老師開始搶答")).to_be_visible()

    # 開啟搶答 → 2 秒內同步到所有學生
    teacher.click("#open-btn")
    for page in (s1, s1b, s2):
        expect(page.locator("#phase")).to_have_text("搶答中", timeout=SYNC_MS)

    # 第 1 組成員 A 先打草稿，成員 B 送出題組 → A 的頁面重繪但草稿保留
    s1.get_by_label("第 4 題 填空 1").fill("草稿保留中")
    s1b.get_by_label("第 1 題 （1）").fill("CPU")
    s1b.get_by_label("第 1 題 （2）").fill("作業系統")
    s1b.locator(".question", has_text="第 1 題").get_by_role("button", name="送出答案").click()
    expect(s1.locator("text=第 1 題 ✔ 本組已送出")).to_be_visible(timeout=SYNC_MS)
    expect(s1.get_by_label("第 4 題 填空 1")).to_have_value("草稿保留中")

    # 第 2 組較晚送出第 1 題；第 3 題送出含 HTML 的答案（須以文字呈現）
    s2.get_by_label("第 1 題 （1）").fill("GPU")
    s2.get_by_label("第 1 題 （2）").fill("Linux")
    s2.locator(".question", has_text="第 1 題").get_by_role("button", name="送出答案").click()
    expect(s2.locator("text=第 1 題 ✔ 本組已送出")).to_be_visible()
    s2.get_by_label("第 3 題 填空 1").fill("<img src=x onerror=window.pwned=1>")
    s2.get_by_label("第 3 題 填空 1").press("Enter")
    expect(s2.locator("text=第 3 題 ✔ 本組已送出")).to_be_visible()

    # 題組空白填空被拒絕
    s1.get_by_label("第 2 題 （1）").fill("只填一格")
    s1.locator(".question", has_text="第 2 題").get_by_role("button", name="送出答案").click()
    expect(s1.locator("#message")).to_have_text("所有填空皆須填寫。")

    # 結束前：學生看不到他組；老師 2 秒內看到所有作答
    assert "GPU" not in s1.content() and "CPU" not in s2.content()
    expect(teacher.locator("#board")).to_contain_text("GPU", timeout=SYNC_MS)
    expect(teacher.locator("#board")).to_contain_text("(1) CPU")
    teacher.set_viewport_size({"width": 1280, "height": 800})
    teacher.screenshot(path=str(RESULTS / "desktop.png"), full_page=True)

    # 結束搶答 → 學生 2 秒內看到結果
    teacher.click("#close-btn")
    for page in (s1, s1b, s2):
        expect(page.locator("text=搶答結果")).to_be_visible(timeout=SYNC_MS)
    first_row = s2.locator("tbody tr").first
    expect(first_row.locator("td.winner")).to_contain_text("第 1 組")
    expect(first_row).to_contain_text("第 2 組（本組）")
    expect(s2.locator("tbody tr").nth(1)).to_contain_text("無人搶答")
    expect(s1.locator("tbody")).to_contain_text("<img src=x onerror=window.pwned=1>")
    assert s1.evaluate("window.pwned") is None

    # 手機寬度無水平溢出
    s2.set_viewport_size({"width": 390, "height": 844})
    s2.screenshot(path=str(RESULTS / "mobile.png"), full_page=True)
    assert _no_horizontal_overflow(s2)
    teacher.set_viewport_size({"width": 390, "height": 844})
    assert _no_horizontal_overflow(teacher)

    # 匯出：答案寫入原填空格
    with teacher.expect_download() as info:
        teacher.click("#export-btn")
    download = info.value
    assert download.suggested_filename.endswith("_搶答結果.xlsx")
    ws = load_workbook(io.BytesIO(Path(download.path()).read_bytes())).active
    assert (ws["G5"].value, ws["G6"].value) == ("CPU", "作業系統")
    assert ws["G11"].value == "<img src=x onerror=window.pwned=1>"
    assert ws["G8"].value == "（1）"

    for ctx in (ctx1, ctx1b, ctx2):
        ctx.close()
    teacher_ctx.close()


def test_disconnect_banner(server, browser):
    from playwright.sync_api import expect

    context = browser.new_context()
    page = context.new_page()
    page.goto(server["base"] + "/")
    expect(page.locator("#offline")).to_be_hidden()
    context.set_offline(True)
    expect(page.locator("#offline")).to_be_visible(timeout=3000)
    context.set_offline(False)
    expect(page.locator("#offline")).to_be_hidden(timeout=3000)
    context.close()


def test_group_choice_survives_reload(server, browser):
    from playwright.sync_api import expect

    context, page = _student(browser, server["base"], 2)
    page.reload()
    expect(page.locator("#identity")).to_have_text("目前身分：第 2 組")
    expect(page.locator("#group-select")).to_have_value("2")
    context.close()


def test_teacher_page_without_key_is_forbidden(server, browser):
    page = browser.new_page()
    response = page.goto(server["base"] + "/teacher")
    assert response.status == 403
    page.close()
