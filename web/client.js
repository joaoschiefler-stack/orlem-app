// ===============================
// CONFIG
// ===============================

// URL dinâmica, funciona em 127.0.0.1, localhost e depois em produção
const WS_URL =
  (location.protocol === "https:" ? "wss://" : "ws://") +
  location.host +
  "/ws";

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

const logsList = document.getElementById("logs-list");
const refreshLogsBtn = document.getElementById("refresh-logs");
const currentSessionSpan = document.getElementById("current-session");

const meetingsList = document.getElementById("meetings-list");
const loadMeetingsBtn = document.getElementById("loadMeetings");

const micBtn = document.getElementById("micBtn");
const micDot = document.getElementById("mic-dot");

// estado
let socket = null;
let currentSessionId = null;
let recog = null;
let isRecording = false;
let currentOpenedLog = null;

// player de áudio reutilizável para voz do Orlem
const orlemAudio = new Audio();

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
  if (currentSessionSpan) {
    currentSessionSpan.textContent = text;
  }
}

function setWsStatus(online) {
  if (!wsStatus) return;
  const pillLabel = wsStatus.querySelector(".pill-label") || wsStatus;
  const dot = wsStatus.querySelector(".dot");
  if (online) {
    wsStatus.classList.add("online");
    if (pillLabel) pillLabel.textContent = "conectado";
  } else {
    wsStatus.classList.remove("online");
    if (pillLabel) pillLabel.textContent = "desconectado";
  }
  if (dot) {
    dot.style.backgroundColor = online ? "#22c55e" : "#ef4444";
  }
}

// ===============================
// FALA DO ORLEM (TTS)
// ===============================
async function speakText(text) {
  // evita ligar TTS pra vazio
  if (!text || typeof text !== "string" || !text.trim()) return;

  try {
    const res = await fetch("/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    if (!res.ok) {
      console.warn("Falha no TTS:", res.status);
      return;
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);

    // usa sempre o mesmo elemento de áudio
    orlemAudio.src = url;
    orlemAudio.onended = () => {
      URL.revokeObjectURL(url);
    };

    orlemAudio
      .play()
      .catch((err) => {
        console.warn("Navegador bloqueou autoplay de áudio:", err);
      });
  } catch (err) {
    console.error("Erro ao reproduzir voz:", err);
  }
}

// ===============================
// WS
// ===============================
function connectWS() {
  try {
    socket = new WebSocket(WS_URL);
  } catch (e) {
    console.error("Erro ao abrir WebSocket:", e);
    setWsStatus(false);
    return;
  }

  socket.onopen = () => {
    console.log("WS aberto em", WS_URL);
    setWsStatus(true);
    addMessage("system", "🔌 Orlem conectado. Pode começar a reunião.");
  };

  socket.onmessage = (event) => {
    let data = null;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      // mensagem simples de texto
      addMessage("orlem", event.data);
      // se o backend mandar texto puro, ainda assim podemos falar
      speakText(event.data);
      return;
    }

    if (!data || typeof data !== "object") {
      addMessage("system", String(event.data));
      return;
    }

    // mensagens tipadas
    if (data.type === "status") {
      if (!currentSessionId && data.session_id) {
        currentSessionId = data.session_id;
        setSessionLabel("sessão: " + currentSessionId);
      }
      return;
    }

    if (data.type === "answer") {
      const texto = data.answer || "";
      addMessage("orlem", texto);
      speakText(texto);
      return;
    }

    if (data.type === "summary") {
      const texto = "RESUMO: " + (data.answer || "");
      addMessage("orlem", "📄 " + texto);
      speakText(texto);
      return;
    }

    if (data.type === "info") {
      const texto = data.answer || "";
      addMessage("system", texto);
      // infos curtas também podem ser faladas
      speakText(texto);
      return;
    }

    if (data.type === "diarize") {
      const texto = data.answer || "";
      addMessage("orlem", "🧑‍🤝‍🧑 " + texto);
      speakText(texto);
      return;
    }

    if (data.type === "end_summary") {
      const texto = "Reunião encerrada. Resumo final: " + (data.answer || "");
      addMessage(
        "orlem",
        "✅ Reunião encerrada.\n\n📄 RESUMO FINAL:\n" + (data.answer || "")
      );
      speakText(texto);
      return;
    }

    // fallback
    addMessage("system", JSON.stringify(data));
  };

  socket.onclose = () => {
    console.log("WS fechado, tentando reconectar em 2s…");
    setWsStatus(false);
    setTimeout(connectWS, 2000);
  };

  socket.onerror = (err) => {
    console.error("Erro no WebSocket:", err);
  };
}

// ===============================
// ENVIO
// ===============================
if (sendBtn && utterance) {
  sendBtn.onclick = () => {
    const text = utterance.value.trim();
    if (!text || !socket || socket.readyState !== WebSocket.OPEN) return;
    addMessage("user", text);
    socket.send(JSON.stringify({ text, session_id: currentSessionId }));
    utterance.value = "";
  };

  utterance.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendBtn.onclick();
    }
  });
}

// ===============================
// AÇÕES DE TOPO
// ===============================
if (summarizeBtn) {
  summarizeBtn.onclick = () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({
        action: "summarize",
        session_id: currentSessionId,
      })
    );
  };
}

if (saveBtn) {
  saveBtn.onclick = () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({ action: "save", session_id: currentSessionId })
    );
  };
}

if (renameBtn) {
  renameBtn.onclick = async () => {
    let current = currentOpenedLog || currentSessionId;
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

    try {
      const res = await fetch("/logs/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert("Erro ao renomear: " + (data.detail || res.status));
        return;
      }

      const data = await res.json();
      currentOpenedLog = data.new_name;
      setSessionLabel("log: " + data.new_name);
      loadLogs();
    } catch (e) {
      console.error(e);
      alert("Erro de rede ao renomear log.");
    }
  };
}

if (diarizeBtn) {
  diarizeBtn.onclick = () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({ action: "diarize", session_id: currentSessionId })
    );
  };
}

if (exportBtn) {
  exportBtn.onclick = async () => {
    const filename =
      currentOpenedLog || (currentSessionId ? currentSessionId + ".jsonl" : null);
    if (!filename) {
      alert("Nenhum log selecionado pra exportar.");
      return;
    }
    try {
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
    } catch (e) {
      console.error(e);
      alert("Erro ao exportar log.");
    }
  };
}

if (endMeetingBtn) {
  endMeetingBtn.onclick = () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({
        action: "end_meeting",
        session_id: currentSessionId,
      })
    );
  };
}

// ===============================
// LOGS (arquivos .jsonl)
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
  itemEl.classList.add("active");
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
// REUNIÕES (DB)
// ===============================
function loadMeetingsFromDB() {
  fetch("/api/meetings")
    .then((r) => r.json())
    .then((data) => {
      if (!meetingsList) return;
      meetingsList.innerHTML = "";
      (data.meetings || []).forEach((m) => {
        const item = document.createElement("div");
        item.className = "meeting-item";
        const title = m.title || `Reunião #${m.id}`;
        item.innerHTML = `
          <div>${title}</div>
          <span class="meta">id ${m.id}</span>
        `;
        item.onclick = () => viewMeeting(m.id, item);
        meetingsList.appendChild(item);
      });
    })
    .catch((err) => console.error(err));
}

function viewMeeting(meetingId, itemEl) {
  document
    .querySelectorAll(".meeting-item")
    .forEach((el) => el.classList.remove("active"));
  itemEl.classList.add("active");

  fetch(`/api/meetings/${meetingId}`)
    .then((r) => r.json())
    .then((data) => {
      if (!timeline) return;
      timeline.innerHTML = "";
      const msgs = data.messages || [];
      msgs.forEach((m) => {
        addMessage(m.role === "user" ? "user" : "orlem", m.content || "");
      });
      setSessionLabel("reunião id: " + meetingId);
    })
    .catch((err) => console.error(err));
}

if (loadMeetingsBtn) {
  loadMeetingsBtn.onclick = loadMeetingsFromDB;
}

// ===============================
// MIC (Web Speech API)
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
    if (utterance) {
      utterance.value = text;
      if (sendBtn) sendBtn.onclick();
    }
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
  if (micBtn) micBtn.classList.add("recording");
  if (micDot) micDot.classList.add("on");
  try {
    recog.start();
  } catch (e) {
    console.warn("erro ao iniciar STT", e);
  }
}

function stopRecording() {
  isRecording = false;
  if (micBtn) micBtn.classList.remove("recording");
  if (micDot) micDot.classList.remove("on");
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
window.addEventListener("load", () => {
  connectWS();
  loadLogs();
  loadMeetingsFromDB();
});
