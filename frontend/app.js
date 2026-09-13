const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("chat-input");
const chipsEl = document.getElementById("chips");
const attachBtn = document.getElementById("attach-btn");
const fileInput = document.getElementById("file-input");
const attachmentPreviewEl = document.getElementById("attachment-preview");
const micBtn = document.getElementById("mic-btn");
const humanBtn = document.getElementById("human-btn");
const langToggleEl = document.getElementById("lang-toggle");
let greetingLabelEl = document.getElementById("greeting-label");
let greetingTextEl = document.getElementById("greeting-text");
const sendBtn = document.getElementById("send-btn");
const homeBtn = document.getElementById("home-btn");
const newChatBtn = document.getElementById("new-chat-btn");
const chatListEl = document.getElementById("chat-list");

// The toggle sets the UI language and is a fallback for ambiguous messages,
// but the backend still matches whatever language the user actually types
// whenever that's clear -- see the LANGUAGE RULE in backend/agent.py.
const I18N = {
  en: {
    brandSub: "Digital assistant · LF Bergslagen",
    greetingLabel: "Sara · AI assistant",
    greeting:
      "Hej! I'm Sara, LF Bergslagen's digital assistant. Tell me what's changing in your life, and I'll help you think it through.",
    placeholder: "Tell me what's happening in your life...",
    send: "Send",
    humanBtn: "Talk to a person",
    humanConnecting: "Connecting...",
    humanNote:
      "You've asked to speak with a colleague at LF Bergslagen. They'll join this chat as soon as they're available — keep this page open.",
    agentJoinedSuffix: "has joined the chat and will respond shortly.",
    attachTitle: "Attach a document",
    micTitle: "Speak instead of typing",
    supportLabel: "LF Bergslagen · Support",
    aiLabel: "Sara · AI assistant",
    thinking: "Thinking...",
    uploadError: "Couldn't read that file. Try a .txt or .pdf under 5MB.",
    chatError: "Something went wrong reaching the navigator. Please try again.",
    speechLang: "en-US",
    chips: [
      { label: "Buying a house", text: "I'd like help with buying a house" },
      { label: "Moving in together", text: "My partner and I are moving in together" },
      { label: "Having a child", text: "We're having a baby soon" },
      { label: "Divorce", text: "I'm going through a divorce" },
      { label: "Starting a business", text: "I'm starting my own business" },
      { label: "Retirement", text: "I'm retiring soon" },
      { label: "Buying a holiday home", text: "I'd like help with buying a holiday home" },
      { label: "Buying a car", text: "I'd like help with buying a car" },
      { label: "Report Fraud", text: "I want to report fraud" },
      { label: "Dispute a Transaction", text: "I want to dispute a transaction" },
      { label: "My product portfolio", text: "I'd like to see my current products with Länsförsäkringar" },
      { label: "Request a callback", text: "I'd like to request a callback" },
      { label: "Check case status", text: "I'd like to check the status of my case" },
      { label: "Apply for a mortgage", text: "I want to apply for a mortgage" },
    ],
  },
  sv: {
    brandSub: "Digital assistent · LF Bergslagen",
    greetingLabel: "Sara · AI-assistent",
    greeting:
      "Hej! Jag heter Sara och är LF Bergslagens digitala assistent. Berätta vad som händer i ditt liv, så hjälper jag dig tänka igenom det.",
    placeholder: "Berätta vad som händer i ditt liv...",
    send: "Skicka",
    humanBtn: "Prata med en person",
    humanConnecting: "Kopplar upp...",
    humanNote:
      "Du har bett om att prata med en kollega på LF Bergslagen. De ansluter till chatten så snart de kan — håll sidan öppen.",
    agentJoinedSuffix: "har anslutit till chatten och svarar snart.",
    attachTitle: "Bifoga ett dokument",
    micTitle: "Prata istället för att skriva",
    supportLabel: "LF Bergslagen · Support",
    aiLabel: "Sara · AI-assistent",
    thinking: "Tänker...",
    uploadError: "Kunde inte läsa filen. Prova en .txt eller .pdf under 5MB.",
    chatError: "Något gick fel. Försök igen.",
    speechLang: "sv-SE",
    chips: [
      { label: "Köpa hus", text: "Jag skulle vilja ha hjälp med att köpa hus" },
      { label: "Flytta ihop", text: "Min partner och jag ska flytta ihop" },
      { label: "Väntar barn", text: "Vi ska snart få barn" },
      { label: "Skilsmässa", text: "Jag går igenom en skilsmässa" },
      { label: "Starta eget", text: "Jag ska starta eget företag" },
      { label: "Pension", text: "Jag ska snart gå i pension" },
      { label: "Köpa fritidshus", text: "Jag skulle vilja ha hjälp med att köpa ett fritidshus" },
      { label: "Köpa bil", text: "Jag skulle vilja ha hjälp med att köpa en bil" },
      { label: "Anmäl bedrägeri", text: "Jag vill anmäla ett bedrägeri" },
      { label: "Bestrid en transaktion", text: "Jag vill bestrida en transaktion" },
      { label: "Min produktportfölj", text: "Jag skulle vilja se mina nuvarande produkter hos Länsförsäkringar" },
      { label: "Begär återuppringning", text: "Jag skulle vilja begära en återuppringning" },
      { label: "Kolla ärendestatus", text: "Jag skulle vilja kolla status på mitt ärende" },
      { label: "Ansök om bolån", text: "Jag vill ansöka om ett bolån" },
    ],
  },
};

let currentLang = localStorage.getItem("ltn-lang") || (navigator.language || "").startsWith("sv") ? "sv" : "en";
if (!I18N[currentLang]) currentLang = "en";

function t() {
  return I18N[currentLang];
}

function applyLanguage(lang) {
  currentLang = I18N[lang] ? lang : "en";
  localStorage.setItem("ltn-lang", currentLang);
  const strings = t();

  document.querySelectorAll(".brand-sub").forEach((el) => (el.textContent = strings.brandSub));
  greetingLabelEl.textContent = strings.greetingLabel;
  greetingTextEl.textContent = strings.greeting;
  inputEl.placeholder = strings.placeholder;
  sendBtn.textContent = strings.send;
  humanBtn.textContent = strings.humanBtn;
  attachBtn.title = strings.attachTitle;
  micBtn.title = strings.micTitle;

  chipsEl.innerHTML = "";
  for (const chip of strings.chips) {
    const btn = document.createElement("button");
    btn.className = "chip";
    btn.dataset.text = chip.text;
    btn.textContent = chip.label;
    chipsEl.appendChild(btn);
  }

  langToggleEl.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.lang === currentLang);
  });
}

langToggleEl.addEventListener("click", (e) => {
  const btn = e.target.closest(".lang-btn");
  if (!btn) return;
  applyLanguage(btn.dataset.lang);
});

let history = [];
let sessionMessageCount = 0; // how many session-store messages we've already accounted for
let humanHandoffActive = false; // once true, the composer talks to a human, not the AI
let lastKnownAgent = null; // name of the CS agent assigned to this session, if any
let sessionId =
  sessionStorage.getItem("ltn-session-id") ||
  (() => {
    const id = crypto.randomUUID();
    sessionStorage.setItem("ltn-session-id", id);
    return id;
  })();

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

// Minimal markdown: headings, paragraphs, bullet/numbered lists, **bold**,
// [text](url). Enough for the agent's structured replies without a full lib.
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
    const heading = line.match(/^#{1,6}\s+(.*)/);
    const bullet = line.match(/^[-*]\s+(.*)/);
    const numbered = line.match(/^\d+\.\s+(.*)/);

    if (heading) {
      flushList();
      flushPara();
      html += `<p><strong>${inline(heading[1])}</strong></p>`;
    } else if (bullet) {
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

// --- Read-aloud (browser text-to-speech, no backend involved) ---

const speechSupported = "speechSynthesis" in window;
let speakingBtn = null;
let cachedVoices = [];

if (speechSupported) {
  const refreshVoices = () => {
    cachedVoices = window.speechSynthesis.getVoices();
  };
  refreshVoices();
  window.speechSynthesis.addEventListener("voiceschanged", refreshVoices);
}

// Prefer a natural-sounding, clearly-female voice matching the reply's
// language (Sara is presented as a woman) over whatever default voice the
// browser would otherwise pick, which is often a flat/robotic fallback.
function pickVoice(lang) {
  if (!cachedVoices.length) return null;
  const prefix = lang.split("-")[0];
  const sameLang = cachedVoices.filter((v) => v.lang && v.lang.toLowerCase().startsWith(prefix));
  const pool = sameLang.length ? sameLang : cachedVoices;
  const female = pool.find((v) => /female|zira|susan|hedda|elsa|alva|natural/i.test(v.name));
  return female || pool[0] || null;
}

// Strip markdown syntax so the reply is actually spoken as natural language
// instead of literal symbols ("asterisk asterisk", raw URLs, "hashtag", ...).
function stripMarkdownForSpeech(text) {
  return text
    .replace(/\[([^\]]+)\]\((?:https?:\/\/|tel:|mailto:)[^\s)]+\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^[-*]\s+/gm, "")
    .replace(/^\d+\.\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

function speak(text, lang, btn) {
  if (!speechSupported) return;
  if (speakingBtn === btn) {
    window.speechSynthesis.cancel();
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(stripMarkdownForSpeech(text));
  utterance.lang = lang;
  const voice = pickVoice(lang);
  if (voice) utterance.voice = voice;
  utterance.onend = utterance.onerror = () => {
    if (speakingBtn) speakingBtn.classList.remove("speaking");
    speakingBtn = null;
  };
  speakingBtn = btn;
  btn.classList.add("speaking");
  window.speechSynthesis.speak(utterance);
}

function addSpeakButton(labelEl, text) {
  if (!speechSupported) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "speak-btn";
  btn.title = "Listen to this answer";
  btn.textContent = "🔊";
  btn.addEventListener("click", () => speak(text, t().speechLang, btn));
  labelEl.appendChild(btn);
}

function addBubble(role, text, { markdown = false, label = "", speakable = false } = {}) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  let labelEl = null;
  if (label) {
    labelEl = document.createElement("span");
    labelEl.className = "msg-label";
    const labelText = document.createElement("span");
    labelText.className = "msg-label-text";
    labelText.textContent = label;
    labelEl.appendChild(labelText);
    div.appendChild(labelEl);
  }
  if (markdown) {
    div.insertAdjacentHTML("beforeend", renderMarkdown(text));
  } else {
    div.appendChild(document.createTextNode(text));
  }
  if (speakable && labelEl) {
    addSpeakButton(labelEl, text);
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

// --- Follow-up suggestion chips shown under an assistant reply ---

function addSuggestions(suggestions, humanChatOption) {
  if (!suggestions || !suggestions.length) return;
  const div = document.createElement("div");
  div.className = "suggestions";
  for (const suggestion of suggestions) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "suggestion-chip";
    btn.textContent = suggestion;
    if (humanChatOption && suggestion === humanChatOption) {
      btn.addEventListener("click", () => {
        div.remove();
        requestHumanHandoff();
      });
    } else {
      btn.addEventListener("click", () => {
        div.remove();
        sendMessage(suggestion);
      });
    }
    div.appendChild(btn);
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function getAssistantReply() {
  const pending = addBubble("assistant pending", t().thinking, { label: t().aiLabel });
  inputEl.disabled = true;
  sendBtn.disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history, session_id: sessionId, lang: currentLang }),
    });

    if (!res.ok) {
      throw new Error(`Server responded with ${res.status}`);
    }

    const data = await res.json();
    pending.innerHTML = "";
    const labelEl = document.createElement("span");
    labelEl.className = "msg-label";
    const labelText = document.createElement("span");
    labelText.className = "msg-label-text";
    labelText.textContent = t().aiLabel;
    labelEl.appendChild(labelText);
    pending.appendChild(labelEl);
    pending.insertAdjacentHTML("beforeend", renderMarkdown(data.content));
    addSpeakButton(labelEl, data.content);
    pending.className = "msg assistant";
    history.push({ role: "assistant", content: data.content });
    sessionMessageCount += 2; // the server just appended one user + one assistant message
    upsertChatListEntry();
    addSuggestions(data.suggestions, data.human_chat_option);
  } catch (err) {
    pending.textContent = t().chatError;
    pending.className = "msg assistant";
    console.error(err);
  } finally {
    inputEl.disabled = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

async function sendMessage(text) {
  if (!text.trim()) return;
  chipsEl.style.display = "none";
  addBubble("user", text);

  if (humanHandoffActive) {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/customer-message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
      });
      const data = await res.json();
      if (typeof data.message_count === "number") sessionMessageCount = data.message_count;
    } catch (err) {
      console.error(err);
    }
    return;
  }

  history.push({ role: "user", content: text });
  await getAssistantReply();
}

async function sendAttachment(filename, text) {
  chipsEl.style.display = "none";
  addBubble("attachment", `📎 ${filename}`);
  history.push({ role: "user", content: `[Attached document: ${filename}]\n\n${text}` });
  await getAssistantReply();
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value;
  inputEl.value = "";
  inputEl.style.height = "auto";
  sendMessage(text);
});

// Enter sends the message; Shift+Enter inserts a newline instead.
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

// Auto-grow the textarea as the user types multiple lines.
inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = `${inputEl.scrollHeight}px`;
});

chipsEl.addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  sendMessage(btn.dataset.text);
});

// --- Document upload ---

attachBtn.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  fileInput.value = "";
  if (!file) return;

  attachmentPreviewEl.hidden = false;
  attachmentPreviewEl.textContent = `Uploading ${file.name}...`;

  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Upload failed with ${res.status}`);
    const data = await res.json();
    attachmentPreviewEl.hidden = true;
    await sendAttachment(data.filename, data.text);
  } catch (err) {
    attachmentPreviewEl.textContent = t().uploadError;
    console.error(err);
    setTimeout(() => {
      attachmentPreviewEl.hidden = true;
    }, 4000);
  }
});

// --- Voice input (browser speech-to-text, no backend involved) ---

const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognitionImpl) {
  micBtn.hidden = false;
  const recognition = new SpeechRecognitionImpl();
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  let listening = false;

  recognition.addEventListener("result", (event) => {
    const transcript = event.results[0][0].transcript;
    inputEl.value = transcript;
    inputEl.style.height = "auto";
    inputEl.style.height = `${inputEl.scrollHeight}px`;
    inputEl.focus();
  });

  recognition.addEventListener("end", () => {
    listening = false;
    micBtn.classList.remove("recording");
  });

  recognition.addEventListener("error", () => {
    listening = false;
    micBtn.classList.remove("recording");
  });

  micBtn.addEventListener("click", () => {
    if (listening) {
      recognition.stop();
      return;
    }
    recognition.lang = t().speechLang;
    listening = true;
    micBtn.classList.add("recording");
    recognition.start();
  });
}

// --- Talk to a real person ---

async function requestHumanHandoff() {
  humanBtn.disabled = true;
  humanBtn.textContent = t().humanConnecting;
  try {
    await fetch(`/api/sessions/${sessionId}/request-human`, { method: "POST" });
    addBubble("system-note", t().humanNote);
    humanHandoffActive = true;
  } catch (err) {
    console.error(err);
    humanBtn.disabled = false;
    humanBtn.textContent = t().humanBtn;
  }
}

humanBtn.addEventListener("click", requestHumanHandoff);

// --- Poll for messages a human support colleague sends from the dashboard ---

async function pollForHumanMessages() {
  try {
    const res = await fetch(`/api/sessions/${sessionId}/poll?after=${sessionMessageCount}`);
    if (!res.ok) return;
    const data = await res.json();

    if (data.assigned_agent && data.assigned_agent !== lastKnownAgent) {
      lastKnownAgent = data.assigned_agent;
      addBubble("system-note", `${lastKnownAgent} ${t().agentJoinedSuffix}`);
    }

    for (const msg of data.messages) {
      if (msg.role === "human") {
        addBubble("human", msg.content, {
          markdown: true,
          label: msg.agent_name || t().supportLabel,
          speakable: true,
        });
      }
    }
    sessionMessageCount = data.next_after;
  } catch (err) {
    // silent -- this is a background poll, not a user-initiated action
  }
}

setInterval(pollForHumanMessages, 3000);

// --- Chat history sidebar (past chats, persisted locally; full transcript
// lives server-side in the session store and is refetched when reopened) ---

function loadChatList() {
  try {
    return JSON.parse(localStorage.getItem("ltn-chat-list") || "[]");
  } catch (err) {
    return [];
  }
}

function saveChatList(list) {
  localStorage.setItem("ltn-chat-list", JSON.stringify(list));
}

function upsertChatListEntry() {
  if (!history.length) return;
  const list = loadChatList();
  const existing = list.find((c) => c.id === sessionId);
  if (existing) {
    existing.ts = Date.now();
  } else {
    const firstUserMsg = history.find((m) => m.role === "user");
    const title = firstUserMsg ? firstUserMsg.content.slice(0, 60) : "Chat";
    list.unshift({ id: sessionId, title, ts: Date.now() });
  }
  saveChatList(list);
  renderChatList();
}

function renderChatList() {
  const list = loadChatList().sort((a, b) => b.ts - a.ts);
  chatListEl.innerHTML = "";
  for (const chat of list) {
    const item = document.createElement("div");
    item.className = "chat-item" + (chat.id === sessionId ? " active" : "");
    item.textContent = chat.title || "Chat";
    item.title = chat.title || "Chat";
    item.addEventListener("click", () => loadChat(chat.id));
    chatListEl.appendChild(item);
  }
}

function resetChatView() {
  messagesEl.innerHTML = "";
  const greetingDiv = document.createElement("div");
  greetingDiv.className = "msg assistant";
  greetingDiv.innerHTML = `<span class="msg-label" id="greeting-label"></span><p id="greeting-text"></p>`;
  messagesEl.appendChild(greetingDiv);
  greetingLabelEl = document.getElementById("greeting-label");
  greetingTextEl = document.getElementById("greeting-text");

  chipsEl.style.display = "";
  attachmentPreviewEl.hidden = true;
  inputEl.value = "";
  inputEl.style.height = "auto";
  humanBtn.disabled = false;
  humanBtn.textContent = t().humanBtn;

  applyLanguage(currentLang);
}

function startNewChat() {
  if (speechSupported) window.speechSynthesis.cancel();
  history = [];
  sessionMessageCount = 0;
  humanHandoffActive = false;
  lastKnownAgent = null;
  sessionId = crypto.randomUUID();
  sessionStorage.setItem("ltn-session-id", sessionId);
  resetChatView();
  renderChatList();
}

function attachmentLabelFrom(content) {
  const match = content.match(/^\[Attached document: (.+?)\]/);
  return match ? `📎 ${match[1]}` : null;
}

async function loadChat(id) {
  if (id === sessionId) return;
  if (speechSupported) window.speechSynthesis.cancel();
  try {
    const res = await fetch(`/api/sessions/${id}`);
    if (!res.ok) return;
    const data = await res.json();

    sessionId = id;
    sessionStorage.setItem("ltn-session-id", sessionId);
    sessionMessageCount = data.messages.length;
    humanHandoffActive = Boolean(data.needs_human);
    lastKnownAgent = data.assigned_agent || null;
    history = data.messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content }));

    messagesEl.innerHTML = "";
    chipsEl.style.display = "none";
    for (const msg of data.messages) {
      const attachmentLabel = msg.role === "user" ? attachmentLabelFrom(msg.content) : null;
      if (attachmentLabel) {
        addBubble("attachment", attachmentLabel);
      } else if (msg.role === "user") {
        addBubble("user", msg.content);
      } else if (msg.role === "assistant") {
        addBubble("assistant", msg.content, { markdown: true, label: t().aiLabel, speakable: true });
      } else if (msg.role === "human") {
        addBubble("human", msg.content, {
          markdown: true,
          label: msg.agent_name || t().supportLabel,
          speakable: true,
        });
      }
    }
    renderChatList();
  } catch (err) {
    console.error(err);
  }
}

homeBtn.addEventListener("click", startNewChat);
homeBtn.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    startNewChat();
  }
});
newChatBtn.addEventListener("click", startNewChat);

applyLanguage(currentLang);
renderChatList();
