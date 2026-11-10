(() => {
  const GROUP_KEY = "quiz-buzzer.group";
  const els = {
    phase: document.getElementById("phase"),
    select: document.getElementById("group-select"),
    identity: document.getElementById("identity"),
    message: document.getElementById("message"),
    content: document.getElementById("content"),
    offline: document.getElementById("offline"),
  };

  let group = loadGroup();
  let state = null;
  let renderedVersion = null;
  let epoch = null;
  let drafts = {};
  const pending = new Set();

  function loadGroup() {
    try {
      const value = parseInt(localStorage.getItem(GROUP_KEY), 10);
      return Number.isInteger(value) ? value : null;
    } catch {
      return null;
    }
  }

  function saveGroup(value) {
    group = value;
    try {
      if (value === null) localStorage.removeItem(GROUP_KEY);
      else localStorage.setItem(GROUP_KEY, String(value));
    } catch {
      /* 無法儲存時仍可在本頁使用 */
    }
  }

  async function fetchState() {
    const query = group ? `?group=${group}` : "";
    const response = await fetch(`/api/student/state${query}`, { cache: "no-store" });
    if (response.status === 400 && group) {
      // 組別已不存在（例如老師減少組別數量），請學生重新選擇。
      saveGroup(null);
      state = null;
      renderedVersion = null;
      return null;
    }
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  }

  function onState(next) {
    if (epoch && next.epoch !== epoch) drafts = {};
    epoch = next.epoch;
    if ((next.group ?? null) !== group) return; // 組別切換中的過期回應
    const groupOptionsChanged = !state || state.group_count !== next.group_count;
    state = next;
    if (groupOptionsChanged) renderGroupSelect();
    if (next.version !== renderedVersion) {
      renderedVersion = next.version;
      withFocusPreserved(render);
    }
  }

  function renderGroupSelect() {
    els.select.replaceChildren(
      h("option", { value: "" }, "請選擇"),
      ...Array.from({ length: state.group_count }, (_, i) =>
        h("option", { value: String(i + 1) }, `第 ${i + 1} 組`)),
    );
    els.select.value = group ? String(group) : "";
  }

  els.select.addEventListener("change", () => {
    const value = parseInt(els.select.value, 10);
    saveGroup(Number.isInteger(value) ? value : null);
    drafts = {};
    renderedVersion = null;
    showMessage(els.message, "");
    refresh();
  });

  async function refresh() {
    try {
      const next = await fetchState();
      if (next) onState(next);
      else { state = null; renderedVersion = null; }
    } catch {
      els.offline.classList.add("show");
    }
  }

  function render() {
    phaseBadge(els.phase, state.phase);
    els.identity.textContent = group ? `目前身分：第 ${group} 組` : "請先在右上角選擇組別";
    if (!group) {
      els.content.replaceChildren(h("div", { className: "card center" }, "請先選擇你的組別。"));
      return;
    }
    if (state.phase === "preparing") {
      const count = state.questions.length;
      els.content.replaceChildren(h("div", { className: "card center" },
        h("p", {}, "等待老師開始搶答…"),
        h("p", { className: "muted" }, count ? `本次共 ${count} 題` : "老師尚未匯入題目")));
    } else if (state.phase === "open") {
      renderQuestions();
    } else {
      renderResults();
    }
  }

  function renderQuestions() {
    const cards = state.questions.map((q) => {
      const mine = state.mine[q.number];
      if (mine) {
        return h("div", { className: "question done" },
          h("h3", {}, `第 ${q.number} 題 ✔ 本組已送出`),
          h("div", { className: "answer-text" }, answersText(mine.answers)));
      }
      const blanks = q.blanks.map((label, i) => {
        const key = `${q.number}:${i}`;
        const input = h("input", {
          type: "text",
          maxLength: 200,
          value: drafts[key] || "",
          placeholder: q.blanks.length > 1 ? `填空 ${i + 1}` : "輸入答案",
          dataset: { key },
          "aria-label": `第 ${q.number} 題 ${label || `填空 ${i + 1}`}`,
          oninput: (e) => { drafts[key] = e.target.value; },
          onkeydown: (e) => { if (e.key === "Enter") submit(q); },
        });
        return h("label", { className: "blank" },
          q.blanks.length > 1 || label ? h("span", { className: "muted" }, label || `填空 ${i + 1}`) : null,
          input);
      });
      return h("div", { className: "question" },
        h("h3", {}, `第 ${q.number} 題${q.blanks.length > 1 ? `（題組，共 ${q.blanks.length} 格，須一起送出）` : ""}`),
        blanks,
        h("button", {
          type: "button",
          dataset: { key: `submit:${q.number}` },
          disabled: pending.has(q.number),
          onclick: () => submit(q),
        }, "送出答案"));
    });
    els.content.replaceChildren(h("div", { className: "card" },
      h("h2", {}, "搶答中：最快送出的組別搶答成功"),
      h("div", { className: "questions" }, cards)));
  }

  async function submit(q) {
    if (pending.has(q.number)) return;
    const answers = q.blanks.map((_, i) => (drafts[`${q.number}:${i}`] || "").trim());
    if (answers.some((a) => !a)) {
      showMessage(els.message, "所有填空皆須填寫。", "error");
      return;
    }
    pending.add(q.number);
    try {
      const response = await fetch("/api/student/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group, question: q.number, answers }),
      });
      if (!response.ok) {
        showMessage(els.message, await readError(response), "error");
      } else {
        q.blanks.forEach((_, i) => delete drafts[`${q.number}:${i}`]);
        showMessage(els.message, `第 ${q.number} 題已送出！`, "ok");
        onState(await response.json());
      }
    } catch {
      showMessage(els.message, "送出失敗，請檢查連線後再試一次。", "error");
    } finally {
      pending.delete(q.number);
      renderedVersion = null;
      refresh();
    }
  }

  function renderResults() {
    const rows = state.results.map((r) => {
      const winner = r.entries[0];
      return h("tr", {},
        h("th", { scope: "row" }, `第 ${r.number} 題`),
        h("td", { className: winner ? "winner" : "" },
          winner ? [h("strong", {}, `第 ${winner.group} 組`), h("div", { className: "answer-text" }, answersText(winner.answers))]
            : h("span", { className: "muted" }, "無人搶答")),
        h("td", {}, r.entries.length
          ? h("ol", { className: "result-list" }, r.entries.map((e) =>
            h("li", {}, `第 ${e.group} 組${e.group === group ? "（本組）" : ""}：`, h("span", { className: "answer-text" }, answersText(e.answers)))))
          : "—"));
    });
    els.content.replaceChildren(h("div", { className: "card" },
      h("h2", {}, "搶答結果"),
      h("div", { className: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "題號"), h("th", {}, "搶答成功"), h("th", {}, "各組順位與答案"))),
        h("tbody", {}, rows)))));
  }

  startPolling(fetchState, onState, els.offline);
})();
