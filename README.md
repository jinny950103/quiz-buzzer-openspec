# 課堂搶答系統（Vibe Coding Quiz Buzzer）

NCU SE6005 2026 軟體工程期末專題 —— **OpenSpec 組**。

老師匯入 Guided Notes（填空式學習單 `.xlsx`）後開放搶答，學生以組別為單位作答，最快送出的組別搶答成功；結束後老師可把成功答案寫回原 Guided Notes 的填空格並下載。

- 技術：Python 3.12 以上、Flask（單程序）、openpyxl、原生 HTML/CSS/JavaScript
- 規格：`openspec/specs/`（正式規格）；開發紀錄 `openspec/changes/archive/2026-11-10-add-core-quiz-buzzer/`（proposal、specs、design、tasks）

## 安裝與啟動（Windows PowerShell）

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m app
```

終端機會印出兩個網址：

```
學生頁面：http://127.0.0.1:5000/
老師頁面：http://127.0.0.1:5000/teacher?key=<每次啟動隨機產生>
```

- **老師網址含有隨機金鑰**，只存在記憶體與終端機，每次重啟都會改變；不要分享給學生。沒有金鑰無法開啟老師頁面或呼叫老師 API。
- 可用 `--port 5050` 更換埠號。
- 所有資料只存在程序記憶體，重啟後活動清空（題目也需重新匯入）。

## 操作流程

1. **老師**：開啟老師網址 →「匯入」上傳 Guided Notes →（可選）設定組別數量（1–20，預設 6）→「開啟搶答」。
2. **學生**：開啟學生頁面 → 右上角選擇組別（同一組可多人；選擇會記在瀏覽器）→ 搶答開始後在每題填答並「送出答案」（Enter 也可送出）。
   - 每組每題只能送出一次；題組須所有填空一起送出。
   - 搶答中只看得到自己組別的作答。
3. **老師**：作答狀況表即時顯示各組答案與順位（#1 為搶答成功）→「結束搶答」。
4. 結束後老師與學生都能看到每題的搶答成功組別與各組順位。
5. **老師**：「匯出答案至 Guided Notes」下載 `<原檔名>_搶答結果.xlsx`；可「重置活動」清除作答再來一輪。

Demo 時可在同一台電腦開多個瀏覽器視窗（或無痕視窗）模擬不同組別。

## Guided Notes 格式規則

從 Google Sheets 選「檔案 → 下載 → Microsoft Excel (.xlsx)」後上傳。系統**不寫死任何儲存格位置**，而是：

1. 找到第一個同時含有「**題號**」與「**作答**」文字的列作為表頭（可有「題目」欄）。
2. 表頭以下，題號欄為**數字**的列開始一題，其作答欄儲存格就是填空格（合併儲存格以左上角為準）。
3. 題號欄空白（或屬於同一題號的合併範圍）且題目欄有內容的列，是同一題的**額外填空**（題組）。
4. 題目欄與題號欄都空白的列視為分隔。
5. 填空格原有文字（例如「（1）」）會當作標籤顯示，匯出時以答案取代；無人搶答的填空保留原文字。

範本在 `samples/`：單題範本解析為 6 題；題組範本為 4 題，第 1、2 題各 2 格。

## API 摘要

錯誤格式：`{"error": {"code": "...", "message": "..."}}`；所有回應 `Cache-Control: no-store`。老師 API 需帶 `X-Teacher-Key` 標頭。

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| GET | `/api/student/state?group=N` | 階段、題目、本組作答；結束後附完整結果 |
| POST | `/api/student/submit` | `{"group": 1, "question": "1", "answers": ["..."]}` |
| GET | `/api/teacher/state` | 完整狀態與所有組別作答 |
| POST | `/api/teacher/import` | multipart，欄位 `file` |
| POST | `/api/teacher/groups` | `{"count": 6}` |
| POST | `/api/teacher/open`、`/close`、`/reset` | 階段切換 |
| GET | `/api/teacher/export` | 下載填好答案的 `.xlsx` |

## 測試

```powershell
.venv/Scripts/python.exe -m playwright install chromium
.venv/Scripts/python.exe -m pytest -q               # 全部
.venv/Scripts/python.exe -m pytest -q -m "not browser"  # 只跑解析、服務層與 API
```

瀏覽器測試會自行啟動一個隨機埠的伺服器（Playwright 內建 Chromium 無法啟動時會改用已安裝的 Edge／Chrome），輸出 `test-results/desktop.png`、`test-results/mobile.png`。

| 規格 | 測試 |
| --- | --- |
| guided-notes-io | `tests/test_guided_notes.py`、`test_session.py::test_export_uses_winning_answers`、`test_api.py::test_full_flow`、`test_browser.py::test_full_activity`（匯出） |
| quiz-session | `tests/test_session.py`（狀態機、組別）、`test_api.py`（金鑰、角色頁面）、`test_browser.py`（2 秒同步、斷線提示） |
| buzz-answering | `tests/test_session.py`（驗證、順位、並行、快照隱藏）、`test_api.py::test_student_state_hides_other_groups`、`test_browser.py::test_full_activity` |

### 驗證紀錄

- 2026-11-10：Python 3.14.7 全新 `.venv`，`pip check` 通過；非瀏覽器測試 **63 passed**。
- 2026-11-10：人工以瀏覽器操作完整流程（匯入→開啟→兩組作答→結束→匯出），結果正確。
- 2026-11-10：人工匯入 `samples/自製_表頭位置不同_測試.xlsx`（表頭第 6 列、作答在 F 欄），題組答案正確寫入 F9–F11。
- 2026-11-10：人工確認含 HTML 的答案以文字呈現、不會被執行。
- 2026-11-10：完整測試 **67 passed**（含 Playwright 瀏覽器測試；內建 Chromium 被系統擋住時自動改用 Edge）。已檢視桌面與 390px 手機截圖，無水平溢出。

### 人工驗證清單

- [ ] 用兩份範本與一份自製、表頭位置不同的 Guided Notes 完整操作一次
- [ ] 用 Excel / Google Sheets 開啟匯出檔，確認答案位於正確填空格、格式未跑掉
- [ ] 兩個不同組別的視窗互相看不到對方作答；同組兩個視窗會同步顯示已送出
- [ ] 答案輸入 `<script>alert(1)</script>` 不會被執行
