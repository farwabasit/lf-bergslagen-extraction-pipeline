const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("chat-input");
const chipsEl = document.getElementById("chips");

let history = [];

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Applied to already-escaped text, so only well-formed http(s)/tel/mailto
// URLs get turned into real links -- no way to smuggle a javascript: URI.
function linkify(text) {
  return text.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+|tel:[^\s)]+|mailto:[^\s)]+)\)/g,
    (_match, label, url) =>
      `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
  );
}

function boldify(text) {
  return text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function inline(text) {
  return boldify(linkify(text));
}

// Minimal markdown: paragraphs, bullet/numbered lists, **bold**, [text](url).
// Enough for the agent's structured replies without pulling in a full lib.
function renderMarkdown(raw) {
  const lines = escapeHtml(raw).split("\n");
  let html = "";
  let listType = null;
  let listItems = [];
  let paraLines = [];

  function flushList() {
    if (listItems.length) {
      const tag = listType === "ol" ? "ol" : "ul";
      html += `<${tag}>${listItems.map((li) => `<li>${inline(li)}</li>`).join("")}</${tag}>`;
    }
    listItems = [];
    listType = null;
  }

  function flushPara() {
    if (paraLines.length) {
      html += `<p>${paraLines.map(inline).join("<br>")}</p>`;
    }
    paraLines = [];
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const bullet = line.match(/^[-*]\s+(.*)/);
    const numbered = line.match(/^\d+\.\s+(.*)/);

    if (bullet) {
      flushPara();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      listItems.push(bullet[1]);
    } else if (numbered) {
      flushPara();
      if (listType && listType !== "ol") flushList();
      listType = "ol";
      listItems.push(numbered[1]);
    } else if (line === "") {
      flushList();
      flushPara();
    } else {
      flushList();
      paraLines.push(line);
    }
  }
  flushList();
  flushPara();
  return html;
}

function addBubble(role, text, { markdown = false } = {}) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  if (markdown) {
    div.innerHTML = renderMarkdown(text);
  } else {
    div.textContent = text;
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

async function sendMessage(text) {
  if (!text.trim()) return;

  chipsEl.style.display = "none";
  addBubble("user", text);
  history.push({ role: "user", content: text });

  const pending = addBubble("assistant pending", "Thinking...");
  inputEl.disabled = true;
  formEl.querySelector("button").disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });

    if (!res.ok) {
      throw new Error(`Server responded with ${res.status}`);
    }

    const data = await res.json();
    pending.innerHTML = renderMarkdown(data.content);
    pending.className = "msg assistant";
    history.push({ role: "assistant", content: data.content });
  } catch (err) {
    pending.textContent = "Something went wrong reaching the navigator. Please try again.";
    pending.className = "msg assistant";
    console.error(err);
  } finally {
    inputEl.disabled = false;
    formEl.querySelector("button").disabled = false;
    inputEl.focus();
  }
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value;
  inputEl.value = "";
  sendMessage(text);
});

chipsEl.addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  sendMessage(btn.dataset.text);
});
