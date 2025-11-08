// ===============================
// CONFIG
// ===============================
const WS_URL = "ws://127.0.0.1:8000/ws";

// elementos principais
const sendBtn = document.getElementById("sendBtn");
const utterance = document.getElementById("utterance");
const timeline = document.getElementById("timeline");

const wsStatus = document.getElementById("ws-status");
const summarizeBtn = document.getElementById("summarize");
const saveBtn = document.getElementById("save");
const renameBtn = document.getElementById("rename");
const diarizeBtn = document.getElementById("diarize");
const exportBtn = document.getElementById("export");
const endMeetingBtn = document.getElementById("endMeeting");
const loadMeetingsBtn = document.getElementById("loadMeetings");

const logsList = document.getElementById("logs-list");
const refreshLogsBtn = document.getElementById("refresh-logs");
const meetingsList = document.getElementById("meetings-list");
const currentSessionSpan = document.getElementById("current-session");

const micBtn = document.getElementById("micBtn");
const micDot = document.getElementById("mic-dot");

// estado
let socket = null;
let currentSessionId = null;
let recog = null;
let isRecording = false;
let currentOpenedLog = null;
let currentMeetingId = null;

// ===============================
// AUX
// ===============================
function addMessage(who, text) {
  if (!timeline) return;
  const div = document.createElement("div");
  div.classList.add("msg");

  if (who === "user") div.classList.add("user");
  else if (who === "orlem") div.classList.add("bot");
  else div.classList.add("system");

  div.textContent = text;
  timeline.appendChild(div);
  timeline.scrollTop = timeline.scrollHeight;
}

function setSessionLabel(text) {
  if (currentSessionSpan) currentSessionSpan.textContent = text;
}

function setWsConnected(connected) {
  if (!wsStatus) return;
  wsStatus.classList.toggle("online", connected);
  const dot = wsStatus.querySelector(".dot");
  if (connected) {
    wsStatus.lastChild.textContent = " conectado";
    if (dot) dot.style.background = "#22c55e";
  } else {
    wsStatus.lastChild.textContent = " desconectado";
    if (dot) dot.style.background = "#f97373";
  }
}

// formatador bonitinho p/ datas das reuniões
function formatDateTimeLabel(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const dia = String(d.getDate()).padStart(2, "0");
  const mes = String(d.getMonth() + 1).padStart(2, "0");
  const hora = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${dia}/${mes} ${hora}:${min}`;
}

// ===============================
// WS
// ===============================
function connectWS() {
  socket = new WebSocket(WS_URL);

  socket.onopen = () => {
    setWsConnected(true);
    addMessage("system", "Conexão pronta.");
  };

  socket.onmessage = (event) => {
    let data = null;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      addMessage("orlem", event.data);
      return;
    }

    if (data.type === "status") {
      // compat antigo, mas hoje quase não usamos
      if (!currentSessionId && data.session_id) {
        currentSessionId = data.session_id;
        setSessionLabel("log: " + currentSessionId + ".jsonl");
      }
      return;
    }

    if (data.type === "answer") {
      addMessage("orlem", data.answer);
      return;
    }

    if (data.type === "summary") {
      addMessage("orlem", "📄 [RESUMO] " + data.answer);
      return;
    }

    if (data.type === "info") {
      addMessage("system", data.answer);
      return;
    }

    if (data.type === "diarize") {
      addMessage("orlem", "🧑‍🤝‍🧑 " + data.answer);
      return;
    }
  };

  socket.onclose = () => {
    setWsConnected(false);
    setTimeout(connectWS, 2000);
  };
}

// ===============================
// ENVIO
// ===============================
function sendCurrentText() {
  const text = utterance.value.trim();
  if (!text || !socket || socket.readyState !== WebSocket.OPEN) return;

  addMessage("user", text);

  socket.send(
    JSON.stringify({
      text,
      session_id: currentSessionId,
    })
  );

  utterance.value = "";
}

if (sendBtn) {
  sendBtn.onclick = sendCurrentText;
}

if (utterance) {
  utterance.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendCurrentText();
    }
  });
}

// ===============================
// TOPO (resumir / salvar / etc.)
// ===============================
if (summarizeBtn) {
  summarizeBtn.onclick = () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;

    // se tiver log aberto, manda esse
    if (currentOpenedLog) {
      socket.send(
        JSON.stringify({
          action: "summarize",
          session_id: currentSessionId,
          target_log: currentOpenedLog,
        })
      );
    } else {
      socket.send(
        JSON.stringify({
          action: "summarize",
          session_id: currentSessionId,
        })
      );
    }
  };
}

if (saveBtn) {
  saveBtn.onclick = () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({
        action: "save",
        session_id: currentSessionId,
      })
    );
  };
}

if (renameBtn) {
  renameBtn.onclick = async () => {
    const current = currentOpenedLog || currentSessionId;
    if (!current) {
      alert("Nenhuma sessão para renomear.");
      return;
    }
    const newName = window.prompt(
      "Nome novo para o log (ex: cliente-acme-demo):"
    );
    if (!newName) return;

    const body = {
      old_name: current.endsWith(".jsonl") ? current : current + ".jsonl",
      new_name: newName,
    };

    const res = await fetch("/logs/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      let msg = "Erro ao renomear.";
      try {
        const data = await res.json();
        msg = data.detail || msg;
      } catch {}
      alert(msg);
      return;
    }

    const data = await res.json();
    currentOpenedLog = data.new_name;
    setSessionLabel("log: " + data.new_name);
    loadLogs();
  };
}

if (diarizeBtn) {
  diarizeBtn.onclick = () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({
        action: "diarize",
        session_id: currentSessionId,
      })
    );
  };
}

if (exportBtn) {
  exportBtn.onclick = async () => {
    const filename =
      currentOpenedLog ||
      (currentSessionId ? currentSessionId + ".jsonl" : null);
    if (!filename) {
      alert("Nenhum log selecionado pra exportar.");
      return;
    }
    const res = await fetch("/logs/" + filename);
    if (!res.ok) {
      alert("Não consegui baixar o log.");
      return;
    }
    const text = await res.text();
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };
}

// botão ENCERRAR: faz um resumo final e registra no chat
if (endMeetingBtn) {
  endMeetingBtn.onclick = () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    addMessage("system", "Encerrando reunião... gerando resumo.");
    socket.send(
      JSON.stringify({
        action: "summarize",
        session_id: currentSessionId,
      })
    );
  };
}

// botão "Reuniões (DB)" -> recarrega lista
if (loadMeetingsBtn) {
  loadMeetingsBtn.onclick = () => {
    loadMeetings();
  };
}

// ===============================
// LOGS (.jsonl) - LADO ESQUERDO
// ===============================
function loadLogs() {
  fetch("/logs")
    .then((r) => r.json())
    .then((data) => {
      if (!logsList) return;
      logsList.innerHTML = "";
      (data.logs || []).forEach((logname) => {
        const item = document.createElement("div");
        item.textContent = logname;
        item.className = "log-item";
        item.onclick = () => viewLog(logname, item);
        logsList.appendChild(item);
      });
    })
    .catch((err) => console.error(err));
}

function viewLog(logname, itemEl) {
  document
    .querySelectorAll(".log-item")
    .forEach((el) => el.classList.remove("active"));
  if (itemEl) itemEl.classList.add("active");
  currentOpenedLog = logname;

  fetch("/logs/" + logname)
    .then((r) => r.text())
    .then((text) => {
      if (!timeline) return;
      timeline.innerHTML = "";
      const lines = text.split("\n").filter(Boolean);
      lines.forEach((line) => {
        try {
          const obj = JSON.parse(line);
          const role = obj.role;
          const content = obj.content;
          addMessage(role === "user" ? "user" : "orlem", content);
        } catch (e) {
          addMessage("system", line);
        }
      });
      setSessionLabel("log: " + logname);
    });
}

if (refreshLogsBtn) {
  refreshLogsBtn.onclick = loadLogs;
}

// ===============================
// MEETINGS DO DB
// ===============================
function renderMeetingsList(meetings) {
  if (!meetingsList) return;
  meetingsList.innerHTML = "";

  (meetings || []).forEach((m) => {
    const item = document.createElement("div");
    item.className = "meeting-item";

    const when = formatDateTimeLabel(m.created_at);
    let title = m.title || "Reunião";
    // deixar mais bonito: esconder "via WebSocket"
    if (title.toLowerCase().includes("websocket")) {
      title = "Reunião local";
    }

    item.innerHTML = `
      <strong>${title}</strong>
      <div class="meeting-meta">${when} — #${m.id}</div>
    `;

    item.onclick = () => {
      document
        .querySelectorAll(".meeting-item")
        .forEach((el) => el.classList.remove("active"));
      item.classList.add("active");
      openMeetingFromDb(m.id, item);
    };

    meetingsList.appendChild(item);
  });
}

function loadMeetings() {
  fetch("/api/meetings")
    .then((r) => r.json())
    .then((data) => {
      renderMeetingsList(data.meetings || []);
    })
    .catch((err) => console.error(err));
}

function openMeetingFromDb(meetingId) {
  currentMeetingId = meetingId;

  fetch(`/api/meetings/${meetingId}`)
    .then((r) => r.json())
    .then((data) => {
      const msgs = data.messages || [];
      if (!timeline) return;
      timeline.innerHTML = "";

      addMessage(
        "system",
        `Abrindo reunião do DB: #${meetingId} — Reunião registrada`
      );

      if (!msgs.length) {
        addMessage("system", "Esta reunião não tem mensagens salvas.");
      } else {
        msgs.forEach((m) => {
          addMessage(m.role === "user" ? "user" : "orlem", m.content);
        });
      }

      setSessionLabel("reunião #" + meetingId);
    })
    .catch((err) => console.error(err));
}

// ===============================
// MIC / STT
// ===============================
function initSTT() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("Seu navegador não suporta reconhecimento de voz (use Chrome).");
    return null;
  }
  const rec = new SpeechRecognition();
  rec.lang = "pt-BR";
  rec.continuous = false;
  rec.interimResults = false;

  rec.onresult = (e) => {
    const text = e.results[0][0].transcript;
    utterance.value = text;
    sendCurrentText();
  };
  rec.onerror = (e) => {
    console.warn("erro no mic", e);
    stopRecording();
  };
  rec.onend = () => {
    stopRecording();
  };
  return rec;
}

function startRecording() {
  if (!recog) recog = initSTT();
  if (!recog) return;
  isRecording = true;
  micBtn.classList.add("recording");
  micDot.classList.add("on");
  try {
    recog.start();
  } catch (e) {
    console.warn(e);
  }
}

function stopRecording() {
  isRecording = false;
  micBtn.classList.remove("recording");
  micDot.classList.remove("on");
  if (recog) {
    try {
      recog.stop();
    } catch (e) {}
  }
}

if (micBtn) {
  micBtn.onclick = () => {
    if (isRecording) stopRecording();
    else startRecording();
  };
}

// ===============================
// BOOT
// ===============================
connectWS();
loadLogs();
loadMeetings();
