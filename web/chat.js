"use strict";
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const status = document.querySelector("#status");
const send = document.querySelector("#send");
const newChat = document.querySelector("#new-chat");
let sessionId = null;
try { sessionId = sessionStorage.getItem("goods-session-id"); } catch {}
if (sessionId && !/^[a-f0-9]{32}$/.test(sessionId)) sessionId = null;
// 浏览器只存当前标签页会话ID；历史与需求在后端MySQL，不存Key。
function rememberSession(id) {
  sessionId = id;
  try {
    if (id) sessionStorage.setItem("goods-session-id", id);
    else sessionStorage.removeItem("goods-session-id");
  } catch {} // 浏览器禁止存储时仍可在当前页面聊天。
}
let busy = false;

function addMessage(role, text) {
  const item = document.createElement("article");
  item.className = `message ${role}`;
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = role === "user" ? "你" : "商品助手";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text; // 按纯文本显示，不把模型输出作为HTML执行。
  item.append(speaker, bubble);
  messages.append(item);
  document.querySelector("#welcome").hidden = true;
  item.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return item;
}

function setBusy(value) {
  busy = value;
  send.disabled = value;
  newChat.disabled = value;
  input.disabled = value;
  document.querySelectorAll("[data-prompt]").forEach(button => { button.disabled = value; });
  send.textContent = value ? "查询中…" : "发送 ↑";
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const text = input.value.trim();
  if (busy || !text) return;
  if (text.length > 1000) { status.textContent = "请将消息缩短到1000字以内。"; return; }
  const userItem = addMessage("user", text);
  input.value = "";
  setBusy(true);
  status.className = "status";
  status.textContent = "正在查询，请稍候…";
  try {
    const body = { message: text };
    if (sessionId) body.session_id = sessionId;
    const response = await fetch("/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = new Error("服务暂时不可用，请稍后重试。");
      error.sessionExpired = response.status === 404;
      throw error;
    }
    const data = await response.json();
    if (typeof data.answer !== "string" || !/^[a-f0-9]{32}$/.test(data.session_id)) {
      throw new Error("回复格式异常，请稍后重试。");
    }
    rememberSession(data.session_id);
    addMessage("assistant", data.answer);
    status.textContent = "";
  } catch (error) {
    userItem.remove(); // 后端未确认成功，不在界面伪装成已完成的轮次。
    input.value = text;
    status.className = "status error";
    status.textContent = error.sessionExpired
      ? "会话已失效，请点击“新对话”后重新说明完整需求。"
      : "本轮未完成，内容已放回输入框。请检查后端服务后重试。";
    document.querySelector("#welcome").hidden = messages.childElementCount > 0;
  } finally {
    setBusy(false);
    input.focus();
  }
});

input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});
document.querySelectorAll("[data-prompt]").forEach(button => {
  button.addEventListener("click", () => { input.value = button.dataset.prompt; input.focus(); });
});
newChat.addEventListener("click", () => {
  if (busy) return;
  rememberSession(null);
  messages.replaceChildren();
  input.value = "";
  status.textContent = "";
  status.className = "status";
  document.querySelector("#welcome").hidden = false;
  input.focus();
});

async function restoreConversation() {
  if (!sessionId) return;
  setBusy(true);
  status.textContent = "正在恢复对话…";
  try {
    const response = await fetch(`/sessions/${sessionId}`);
    if (response.status === 404) {
      rememberSession(null);
      status.textContent = "原会话不存在，可以开始新对话。";
      return;
    }
    if (!response.ok) throw new Error("restore failed");
    const saved = await response.json();
    if (!Array.isArray(saved.history) || saved.history.some(row =>
      !["user", "assistant"].includes(row.role) || typeof row.content !== "string")) {
      throw new Error("invalid history");
    }
    for (const row of saved.history) addMessage(row.role, row.content);
    status.textContent = "";
  } catch {
    status.className = "status error";
    status.textContent = "历史暂时未能加载，请检查后端后刷新；原会话ID已保留。";
  } finally { setBusy(false); }
}
restoreConversation();
