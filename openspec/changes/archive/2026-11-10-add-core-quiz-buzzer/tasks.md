# Tasks

## 1. 專案骨架與相依套件

- [x] 1.1 建立 `app/`（`__init__.py`、`__main__.py`、`session.py`、`guided_notes.py`、`templates/`、`static/`）與 `tests/` 目錄結構，`python -c "import app"` 可成功執行
- [x] 1.2 建立 `requirements.txt`（flask、openpyxl、pytest、playwright）、`pytest.ini`（註冊 `browser` marker）與 `.gitignore`（`.venv/`、`__pycache__/`、`test-results/`），在全新 `.venv` 中 `pip install -r requirements.txt` 與 `pip check` 皆成功

## 2. Guided Notes 匯入解析（guided-notes-io）

- [x] 2.1 在 `guided_notes.py` 實作依表頭（「題號」「作答」，包含式比對）定位表頭列與欄位，找不到時拋出明確錯誤；以 pytest 驗證兩份範本都能找到表頭、缺表頭檔案會得到錯誤
- [x] 2.2 實作題目與填空格解析：數字題號開始新題、合併範圍左上角為作答格、題組子列、分隔列結束、佔位文字作為標籤；pytest 驗證單題範本解析為 6 題各 1 格、題組範本第 1、2 題各 2 格，且作答格座標正確
- [x] 2.3 以 openpyxl 程式產生「表頭位於不同列/欄」的測試學習單，pytest 驗證解析結果的題數與作答格座標隨位置正確變動（證明未寫死儲存格）
- [x] 2.4 處理無效輸入（非 xlsx、損壞檔、表頭下無題號），pytest 驗證皆回傳說明原因的錯誤

## 3. Guided Notes 匯出（guided-notes-io）

- [x] 3.1 在 `guided_notes.py` 實作 `export_workbook`：載入原始 bytes，只寫入有搶答成功答案的作答格（取代佔位文字），回傳新 bytes；pytest 對兩份範本做往返測試，驗證答案寫入正確格子、無人搶答格保留原文字、非作答格內容與合併範圍不變

## 4. 活動狀態與搶答判定（quiz-session、buzz-answering）

- [x] 4.1 在 `session.py` 實作 `QuizSession` 狀態機（準備中/搶答中/已結束、開啟/結束/重置、版本號），以及匯入與組別數量（1–20，預設 6）只能在準備中變更的規則；pytest 驗證所有合法與非法切換
- [x] 4.2 實作送出答案：階段檢查、組別範圍檢查、去空白後非空、200 字上限、題組所有填空皆需填寫、每組每題只能送出一次；pytest 涵蓋每種拒絕情境，並確認被拒絕時狀態不變
- [x] 4.3 以鎖保護的先到先得順位計算，並提供依角色過濾的狀態快照（學生快照只含本組資料，結束後才附完整結果；老師快照含全部）；pytest 驗證順位、搶答成功組別、學生快照不含他組資訊，並用多執行緒同時送出驗證順位唯一且只有一組成功

## 5. HTTP API 與存取控制

- [x] 5.1 在 `__main__.py` 啟動時以 `secrets` 產生老師金鑰並印出老師網址（單程序、多執行緒、停用 reloader，支援 `--port`）；手動執行 `python -m app` 確認終端機顯示網址，且 repo 中搜尋不到任何寫死的金鑰
- [x] 5.2 在 `__init__.py` 實作 design D7 的所有路由、統一錯誤格式與 `Cache-Control: no-store`；老師 API 驗證 `X-Teacher-Key`；以 Flask test client 撰寫 `tests/test_api.py`，驗證完整流程（匯入→開啟→兩組送出→結束→匯出）、無金鑰或錯誤金鑰回 403 且狀態不變、學生 API 回應不含他組資料

## 6. 前端頁面

- [x] 6.1 實作老師頁面（`teacher.html`、`teacher.js`）：上傳 xlsx、設定組別、開啟/結束/重置、即時作答表格（題號 × 組別，顯示答案與順位、標示搶答成功者）、結束後的匯出按鈕，每秒輪詢並依版本號重繪；手動以範本操作一次並確認畫面
- [x] 6.2 實作學生頁面（`student.html`、`student.js`）：選擇組別並存入 localStorage、依階段顯示等待／作答／結果畫面、題組多欄一次送出、本組已送出題目鎖定並顯示內容、斷線提示與自動恢復、重繪時保留尚未送出的輸入；手動開兩個不同組別的視窗確認互相看不到對方作答
- [x] 6.3 確保所有使用者輸入都以文字節點呈現（不使用 innerHTML 插入答案），桌面與 390px 手機寬度無水平溢出；以含 `<script>` 的答案人工驗證不會被執行

## 7. 整合驗證與文件

- [x] 7.1 撰寫 `tests/test_browser.py`（Playwright）：自行啟動伺服器，以老師加 2 組學生視窗跑完匯入→開啟→搶答→結束→檢視結果→匯出，驗證 2 秒內階段同步、結束前學生看不到他組、同組成員同步顯示已送出，並輸出桌面與手機截圖到 `test-results/`；`pytest -q` 全數通過
- [x] 7.2 撰寫 `README.md`：安裝與啟動、老師網址取得方式、Guided Notes 格式規則（表頭定位、題組判定）、API 摘要、測試指令與規格對應表；依 README 步驟在全新 `.venv` 從頭操作一次確認可行
- [x] 7.3 人工驗證：使用兩份範本與一份自製、位置不同的 Guided Notes 完整操作，並用 Excel/Google Sheets 開啟匯出檔確認答案位於正確填空格，將結果記錄在 README 的驗證紀錄

## Workflow follow-up

- 執行 `/opsx:verify` 確認實作與 specs 一致後，再執行 `/opsx:archive` 將 specs 合併到 `openspec/specs/`。
- 與 SpecKit 組對齊功能範圍後，以新的 change 規劃額外功能（CSV 匯出、公平順位等）。
