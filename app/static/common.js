// 老師端與學生端共用的小工具。所有使用者輸入一律以 textContent 呈現。

const PHASE_LABELS = { preparing: "準備中", open: "搶答中", closed: "已結束" };

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "className") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key in el && typeof value !== "string") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function phaseBadge(el, phase) {
  el.className = `badge phase-${phase}`;
  el.textContent = PHASE_LABELS[phase] || phase;
}

function showMessage(el, text, kind) {
  el.textContent = text || "";
  el.className = `message ${kind || ""}`;
}

async function readError(response) {
  try {
    const body = await response.json();
    return body.error?.message || `錯誤（${response.status}）`;
  } catch {
    return `錯誤（${response.status}）`;
  }
}

// 每秒輪詢；連線失敗時顯示提示並持續重試。
function startPolling(fetchState, onState, offlineEl, intervalMs = 1000) {
  let timer = null;
  async function tick() {
    try {
      const state = await fetchState();
      offlineEl.classList.remove("show");
      if (state) onState(state);
    } catch {
      offlineEl.classList.add("show");
    } finally {
      timer = setTimeout(tick, intervalMs);
    }
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      clearTimeout(timer);
      tick();
    }
  });
  tick();
}

// 重繪前後保留焦點與游標位置（依 data-key 對應）。
function withFocusPreserved(render) {
  const active = document.activeElement;
  const key = active?.dataset?.key;
  const start = active?.selectionStart;
  const end = active?.selectionEnd;
  render();
  if (!key) return;
  const next = document.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (next && !next.disabled) {
    next.focus();
    if (typeof start === "number" && next.setSelectionRange) next.setSelectionRange(start, end);
  }
}

function answersText(answers) {
  return answers.length > 1 ? answers.map((a, i) => `(${i + 1}) ${a}`).join("　") : answers[0];
}
