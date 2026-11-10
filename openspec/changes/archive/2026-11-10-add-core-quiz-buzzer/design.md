# Design

## Context

專案從零開始（greenfield），尚無程式碼。需求見 `proposal.md`，行為契約見 `specs/guided-notes-io`、`specs/quiz-session`、`specs/buzz-answering`。

限制條件：
- 只需在本機執行，不必支援多台設備連線部署；Demo 時會在同一台電腦開多個瀏覽器視窗模擬老師與至少 2 組學生。
- Guided Notes 原本是 Google Sheets，以 `.xlsx` 形式交換。助教會用另一份格式相近、但儲存格位置不同的學習單測試。
- 不得在 repo 中放入任何密碼或金鑰。
- 需與 SpecKit 組產出的系統功能一致，因此架構以簡單、可說明為優先。

## Goals / Non-Goals

**Goals:**
- 單一程序就能跑起全部功能，一行指令啟動。
- 搶答順位判定正確，並發送出時也不會出現重複順位。
- 匯入、匯出邏輯與 Web 層分離，能單獨用 pytest 測試。
- 預留擴充點，方便後續加入 CSV 匯出、公平順位機制等額外功能。

**Non-Goals:**
- 不做資料持久化；程序重啟後活動就重置。
- 不同時支援多場活動，整個伺服器只有一場活動。
- 不做 WebSocket 推播，改用輪詢（理由見 Decisions）。
- 不串接 Google Sheets API。

## Decisions

### D1. 技術棧：Python 3.12 以上 + Flask + 原生 JavaScript
- **選擇**：後端用 Flask，前端用 Jinja 模板加原生 JS/CSS，不使用前端框架。
- **理由**：本機單程序就足夠；團隊已有 Flask 經驗（午餐投票作業）；不用建置步驟，也讓 AI 產生的程式碼容易人工審查。
- **替代方案**：Node.js + Socket.IO，即時性較好，但多一套執行環境與建置流程；FastAPI 則會多出非同步複雜度，這裡用不到。

### D2. 分層架構
```
app/
  __init__.py        create_app()：路由與 HTTP 處理，只做輸入驗證與 JSON 序列化
  __main__.py        python -m app 啟動、產生並印出老師金鑰網址
  session.py         QuizSession：活動狀態機、組別、作答、順位（純 Python，無 Flask 相依）
  guided_notes.py    parse_workbook(bytes) -> 題目結構；export_workbook(bytes, 答案) -> bytes
  templates/         teacher.html、student.html
  static/            teacher.js、student.js、style.css
tests/
  test_guided_notes.py、test_session.py、test_api.py、test_browser.py
```
- **理由**：`session.py` 與 `guided_notes.py` 不依賴 HTTP，可直接做單元測試；Flask 層保持很薄。之後加入額外功能（例如 CSV 匯出、公平順位策略）時，只需擴充服務層。

### D3. 狀態模型與並行控制
- `QuizSession` 保存：`phase`（`preparing` / `open` / `closed`）、`group_count`、`questions`、`submissions`、`version`、原始上傳檔的 bytes。
- `Question`：`number`（題號字串）與 `blanks: list[Blank]`。`Blank` 記錄 `sheet`、`cell`（作答格座標）與 `label`（佔位文字，可能為空）。單題的 `blanks` 長度為 1，題組則大於 1。
- `Submission`：`question_number`、`group`、`answers: list[str]`、`rank`、`received_seq`。
- 所有讀寫都在同一把 `threading.Lock` 內完成。送出答案時，在鎖內檢查階段與是否重複，再以全域遞增的 `received_seq` 及「該題目前筆數 + 1」決定順位。
- **理由**：Flask 開發伺服器以多執行緒處理請求，用一把鎖就能保證順位唯一，不必引入資料庫。
- **替代方案**：使用 SQLite 交易。但這次不需要持久化，徒增複雜度。

### D4. 同步方式：每秒輪詢加版本號
- 前端每 1 秒呼叫狀態 API；任何狀態變更都會讓 `version` 加 1，前端只在版本改變時重新繪製畫面，以保留使用者正在輸入的內容。
- **理由**：需求是 2 秒內同步，而人數只是一間教室，輪詢已足夠，實作與除錯也最簡單（午餐投票作業已驗證過這種做法）。
- **替代方案**：SSE 或 WebSocket。即時性更好，但需處理斷線重連，Flask 開發伺服器的支援也有限，留待需要時再改。

### D5. 角色與存取控制
- 啟動時用 `secrets.token_urlsafe(16)` 產生老師金鑰，只存在記憶體中，並在終端機印出 `http://127.0.0.1:5000/teacher?key=...`。
- 老師頁面把金鑰放進 `X-Teacher-Key` 標頭呼叫 `/api/teacher/*`；金鑰不符時回應 403。
- 學生頁面 `/` 把選擇的組別存在 `localStorage`，每次請求都帶上 `group`。`/api/student/state?group=N` 只回傳全域階段、題目結構，以及第 N 組自己的作答。
- **理由**：符合「不得在 repo 放金鑰」，也避免學生直接打老師 API 偷看他組答案；同時不需要帳號系統。
- **已知限制**：學生可以自行把 `group` 改成別組來查看那一組的作答，見 Risks。

### D6. Guided Notes 解析演算法（不寫死儲存格）
1. 逐一掃描工作表，找到第一個同時含有「題號」與「作答」文字的列作為表頭列（去除空白後比對，允許「作答區」之類的包含式比對）；記下題號欄、作答欄，以及同列含「題目」的欄（若有）。
2. 從表頭的下一列開始往下掃：
   - 題號欄的值可轉成數字 → 開始新的一題；該列的作答格成為第一個填空。
   - 題號欄空白（或位於上一題題號的合併範圍內）且題目欄有內容 → 視為上一題的下一個填空。
   - 題目欄與題號欄都空白 → 視為分隔列，結束目前這一題的收集。
3. 作答格若屬於合併範圍，一律以合併範圍的左上角為準；格內原有文字當作佔位標籤。
4. 找不到題目欄時，退而以「題號欄或作答欄非空」來判斷子題列。
- 匯出時用 openpyxl 載入原始 bytes，只修改記錄下來的作答格座標，再另存新檔。這樣其他內容、合併儲存格與樣式都不受影響。
- **理由**：完全依表頭與欄位的語意定位，換一份格式相近的學習單也能運作；同時直接相容題組範本的合併題號格與（1）（2）佔位符。

### D7. API 概要
| 方法 | 路徑 | 角色 | 說明 |
| --- | --- | --- | --- |
| GET | `/` | 學生 | 學生頁面 |
| GET | `/teacher?key=` | 老師 | 老師頁面 |
| GET | `/api/student/state?group=` | 學生 | 階段、題目、本組作答；已結束時附完整結果 |
| POST | `/api/student/submit` | 學生 | `{group, question, answers[]}` |
| GET | `/api/teacher/state` | 老師 | 完整狀態與所有作答 |
| POST | `/api/teacher/import` | 老師 | multipart 上傳 `.xlsx` |
| POST | `/api/teacher/groups` | 老師 | `{count}` |
| POST | `/api/teacher/open` · `/close` · `/reset` | 老師 | 階段切換 |
| GET | `/api/teacher/export` | 老師 | 下載填好答案的 `.xlsx` |

錯誤一律回傳 `{"error": {"code", "message"}}`，搭配 400、403、409 等狀態碼；所有回應都加上 `Cache-Control: no-store`。

## Risks / Trade-offs

- [學生可以竄改 `group` 參數，查看別組在結束前的作答] → 只影響本機 Demo 的情境，並不會洩漏「誰最快」以外的資訊；若需要更嚴格的限制，可在選擇組別時由伺服器發出簽章 cookie 綁定組別，列為後續改進。
- [程序重啟後所有狀態消失] → 這是刻意的取捨；在 README 中說明，Demo 期間不要重啟。
- [其他學習單的表頭文字可能不同，例如「答案」] → 表頭比對採用包含式比對，並集中寫成常數，方便擴充同義詞；匯入失敗時給出清楚的錯誤訊息。
- [輪詢會讓伺服器負載隨人數線性增加] → 一間教室的規模影響可忽略。
- [Google Sheets 匯出的 xlsx 用 openpyxl 存檔後，可能遺失部分特殊格式，例如條件式格式的細節] → 用兩份範本做往返測試，並人工開啟確認。

## Migration Plan

全新專案，沒有要遷移的資料。部署步驟：建立 `.venv`、`pip install -r requirements.txt`，再執行 `python -m app`，並開啟終端機印出的老師網址。若要回復，直接停止程序即可。

## Open Questions

- 額外功能（CSV 匯出、公平順位機制等）要做哪些，待與 SpecKit 組討論後另開 change，不影響本 change 的架構。
