// ===============================
// CONFIG
// ===============================
const WS_URL = "ws://127.0.0.1:8000/ws";

// elementos
const sendBtn = document.getElementById("sendBtn");
const utterance = document.getElementById("utterance");
const timeline = document.getElementById("timeline");

const wsStatus = document.getElementById("ws-status");
const summarizeBtn = document.getElementById("summarize");
const saveBtn = document.getElementById("save");
const renameBtn = document.getElementById("rename");
const diarizeBtn = document.getElementById("diarize");
const exportBtn = document.getElementById("export");

const logsList = document.getElementById("logs-list");
const refreshLogsBtn = document.getElementById("refresh-logs");
const currentSessionSpan = document.getElementById("current-session");

const micBtn = document.getElementById("micBtn");
const micDot = document.getElementById("mic-dot");

// estado
let socket = null;
let currentSessionId = null;
let recog = null;
let isRecording = false;
let currentOpenedLog = null;

// ===============================
// AUX
// ===============================
function addMessage(who, text) {
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

// ===============================
// WS
// ===============================
function connectWS() {
  socket = new WebSocket(WS_URL);

  socket.onopen = () => {
    if (wsStatus) {
      wsStatus.textContent = "conectado";
      wsStatus.classList.remove("offline");
      wsStatus.classList.add("online");
    }
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
      if (!currentSessionId) {
        currentSessionId = data.session_id;
        setSessionLabel("sessão: " + currentSessionId);
      }
      return;
    }

    if (data.type === "answer") {
      addMessage("orlem", data.answer);
      return;
    }

    if (data.type === "summary") {
      addMessage("orlem", "📄 RESUMO: " + data.answer);
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
    if (wsStatus) {
      wsStatus.textContent = "desconectado";
      wsStatus.classList.remove("online");
      wsStatus.classList.add("offline");
    }
    setTimeout(connectWS, 2000);
  };
}

// ===============================
// ENVIO
// ===============================
sendBtn.onclick = () => {
  const text = utterance.value.trim();
  if (!text || !socket || socket.readyState !== WebSocket.OPEN) return;
  addMessage("user", text);
  socket.send(JSON.stringify({ text, session_id: currentSessionId }));
  utterance.value = "";
};
utterance.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendBtn.onclick();
});

// ===============================
// AÇÕES DE TOPO
// ===============================
summarizeBtn.onclick = () => {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;

  // se tem log aberto -> manda esse
  if (currentOpenedLog) {
    socket.send(
      JSON.stringify({
        action: "summarize",
        session_id: currentSessionId,
        target_log: currentOpenedLog,
      })
    );
  } else {
    // senão, resumo da sessão atual
    socket.send(
      JSON.stringify({
        action: "summarize",
        session_id: currentSessionId,
      })
    );
  }
};

saveBtn.onclick = () => {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ action: "save", session_id: currentSessionId }));
};

renameBtn.onclick = async () => {
  let current = currentOpenedLog || currentSessionId;
  if (!current) {
    alert("Nenhuma sessão para renomear.");
    return;
  }
  const newName = window.prompt("Nome novo para o log (ex: cliente-acme-demo):");
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
    const data = await res.json();
    alert("Erro ao renomear: " + (data.detail || res.status));
    return;
  }

  const data = await res.json();
  currentOpenedLog = data.new_name;
  setSessionLabel("log: " + data.new_name);
  loadLogs();
};

diarizeBtn.onclick = () => {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ action: "diarize", session_id: currentSessionId }));
};

exportBtn.onclick = async () => {
  const filename = currentOpenedLog || (currentSessionId ? currentSessionId + ".jsonl" : null);
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

// ===============================
// LOGS
// ===============================
function loadLogs() {
  fetch("/logs")
    .then((r) => r.json())
    .then((data) => {
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
  document.querySelectorAll(".log-item").forEach((el) => el.classList.remove("active"));
  itemEl.classList.add("active");
  currentOpenedLog = logname;

  fetch("/logs/" + logname)
    .then((r) => r.text())
    .then((text) => {
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

refreshLogsBtn.onclick = loadLogs;

// ===============================
// MIC
// ===============================
function initSTT() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
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
    sendBtn.onclick();
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
  recog.start();
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

micBtn.onclick = () => {
  if (isRecording) stopRecording();
  else startRecording();
};

// ===============================
// BOOT
// ===============================
connectWS();
loadLogs();
