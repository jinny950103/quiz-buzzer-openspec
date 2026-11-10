(() => {
  const key = new URLSearchParams(location.search).get("key") || "";
  const $ = (id) => document.getElementById(id);
  const els = {
    phase: $("phase"), summary: $("summary"), message: $("message"), offline: $("offline"),
    importForm: $("import-form"), file: $("file"), importBtn: $("import-btn"), fileInfo: $("file-info"),
    groupForm: $("group-form"), groupCount: $("group-count"), groupBtn: $("group-btn"),
    openBtn: $("open-btn"), closeBtn: $("close-btn"), exportBtn: $("export-btn"), resetBtn: $("reset-btn"),
    boardTitle: $("board-title"), board: $("board"),
  };

  let state = null;
  let renderedVersion = null;
  let busy = false;

  function api(path, options = {}) {
    return fetch(path, {
      cache: "no-store",
      ...options,
      headers: { "X-Teacher-Key": key, ...(options.headers || {}) },
    });
  }

  async function fetchState() {
    const response = await api("/api/teacher/state");
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  }

  function onState(next) {
    const changed = !state || next.version !== renderedVersion || next.epoch !== state.epoch;
    const groupChanged = !state || state.group_count !== next.group_count;
    state = next;
    if (groupChanged && document.activeElement !== els.groupCount) {
      els.groupCount.value = next.group_count;
    }
    if (changed) {
      renderedVersion = next.version;
      render();
    }
  }

  async function action(run, okText) {
    if (busy) return;
    busy = true;
    updateButtons();
    try {
      const response = await run();
      if (!response.ok) {
        showMessage(els.message, await readError(response), "error");
      } else {
        showMessage(els.message, okText, "ok");
        onState(await response.json());
      }
    } catch {
      showMessage(els.message, "操作失敗，請檢查伺服器是否仍在執行。", "error");
    } finally {
      busy = false;
      updateButtons();
    }
  }

  els.importForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const file = els.file.files[0];
    if (!file) {
      showMessage(els.message, "請先選擇 .xlsx 檔案。", "error");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    action(() => api("/api/teacher/import", { method: "POST", body: form }), `已匯入「${file.name}」。`)
      .then(() => { els.file.value = ""; });
  });

  els.groupForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const count = Number(els.groupCount.value);
    action(() => api("/api/teacher/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: Number.isInteger(count) ? count : els.groupCount.value }),
    }), `組別數量已設為 ${count} 組。`);
  });

  els.openBtn.addEventListener("click", () =>
    action(() => api("/api/teacher/open", { method: "POST" }), "搶答已開啟！"));
  els.closeBtn.addEventListener("click", () => {
    if (!confirm("確定要結束搶答嗎？結束後學生將無法再送出答案。")) return;
    action(() => api("/api/teacher/close", { method: "POST" }), "搶答已結束。");
  });
  els.resetBtn.addEventListener("click", () => {
    if (!confirm("確定要重置活動嗎？所有作答紀錄將被清除（題目保留）。")) return;
    action(() => api("/api/teacher/reset", { method: "POST" }), "活動已重置。");
  });

  els.exportBtn.addEventListener("click", async () => {
    try {
      const response = await api("/api/teacher/export");
      if (!response.ok) {
        showMessage(els.message, await readError(response), "error");
        return;
      }
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
      const filename = match ? decodeURIComponent(match[1]) : "搶答結果.xlsx";
      const url = URL.createObjectURL(await response.blob());
      const link = h("a", { href: url, download: filename });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      showMessage(els.message, `已匯出「${filename}」。`, "ok");
    } catch {
      showMessage(els.message, "匯出失敗，請檢查伺服器是否仍在執行。", "error");
    }
  });

  function updateButtons() {
    const phase = state?.phase;
    const hasQuestions = !!state?.questions.length;
    els.importBtn.disabled = busy || phase !== "preparing";
    els.file.disabled = phase !== "preparing";
    els.groupBtn.disabled = busy || phase !== "preparing";
    els.groupCount.disabled = phase !== "preparing";
    els.openBtn.disabled = busy || phase !== "preparing" || !hasQuestions;
    els.closeBtn.disabled = busy || phase !== "open";
    els.exportBtn.disabled = busy || phase !== "closed";
    els.resetBtn.disabled = busy || phase !== "closed";
  }

  function render() {
    phaseBadge(els.phase, state.phase);
    const answered = state.results.filter((r) => r.winner !== null).length;
    els.summary.textContent = state.questions.length
      ? `${state.questions.length} 題｜${state.group_count} 組｜已有搶答成功：${answered} 題`
      : `${state.group_count} 組｜尚未匯入題目`;
    els.fileInfo.textContent = state.filename
      ? `目前題目：${state.filename}（${state.questions.length} 題，其中題組 ${state.questions.filter((q) => q.blanks.length > 1).length} 題）`
      : "尚未匯入。請上傳 Google Sheets 下載的 .xlsx 檔。";
    els.boardTitle.textContent = state.phase === "closed" ? "搶答結果" : "作答狀況（即時）";
    updateButtons();
    renderBoard();
  }

  function renderBoard() {
    if (!state.questions.length) {
      els.board.replaceChildren(h("p", { className: "muted" }, "匯入題目後會在這裡顯示各組作答狀況。"));
      return;
    }
    const groups = Array.from({ length: state.group_count }, (_, i) => i + 1);
    const head = h("tr", {}, h("th", {}, "題號"), h("th", {}, "搶答成功"),
      groups.map((g) => h("th", {}, `第 ${g} 組`)));
    const rows = state.results.map((r, idx) => {
      const byGroup = new Map(r.entries.map((e) => [e.group, e]));
      const winner = r.entries[0];
      const blanks = state.questions[idx].blanks.length;
      return h("tr", {},
        h("th", { scope: "row" }, `第 ${r.number} 題${blanks > 1 ? `（題組 ${blanks} 格）` : ""}`),
        h("td", { className: winner ? "winner" : "" },
          winner ? `第 ${winner.group} 組` : h("span", { className: "muted" }, state.phase === "closed" ? "無人搶答" : "—")),
        groups.map((g) => {
          const e = byGroup.get(g);
          if (!e) return h("td", { className: "muted" }, "未作答");
          return h("td", { className: e.rank === 1 ? "winner" : "" },
            h("span", { className: "rank" }, `#${e.rank}`),
            h("span", { className: "answer-text" }, answersText(e.answers)));
        }));
    });
    els.board.replaceChildren(h("table", {}, h("thead", {}, head), h("tbody", {}, rows)));
  }

  updateButtons();
  startPolling(fetchState, onState, els.offline);
})();
