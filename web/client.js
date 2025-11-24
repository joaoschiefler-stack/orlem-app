(() => {
  let ws = null;
  let sessionId = null;
  let reconnectTimeout = null;

  const chatEl = document.getElementById("chat-messages");
  const inputEl = document.getElementById("user-input");
  const sendBtn = document.getElementById("send-btn");
  const wsStatusText = document.getElementById("ws-status-text");
  const connectionStatus = document.getElementById("connection-status");
  const sessionLabel = document.getElementById("session-label");
  const sessionDot = document.getElementById("session-dot");

  // painel da direita
  const summaryItems = document.getElementById("panel-summary-items");
  const summaryEmpty = document.getElementById("panel-summary-empty");
  const summaryCount = document.getElementById("panel-summary-count");

  const decisionsItems = document.getElementById("panel-decisions-items");
  const decisionsEmpty = document.getElementById("panel-decisions-empty");
  const decisionsCount = document.getElementById("panel-decisions-count");

  const actionsItems = document.getElementById("panel-actions-items");
  const actionsEmpty = document.getElementById("panel-actions-empty");
  const actionsCount = document.getElementById("panel-actions-count");

  const diarizeItems = document.getElementById("panel-diarize-items");
  const diarizeEmpty = document.getElementById("panel-diarize-empty");
  const diarizeCount = document.getElementById("panel-diarize-count");

  const btnSummarize = document.getElementById("btn-summarize");
  const btnDiarize = document.getElementById("btn-diarize");
  const btnEnd = document.getElementById("btn-end");

  // microfone
  const btnMic = document.getElementById("btn-mic");
  let mediaRecorder = null;
  let recordedChunks = [];

  // === controles visuais / verbosidade (NOVO) ===
  const VERBOSE_SYSTEM = false; // defina true para ver mensagens de sistema no chat (debug)
  function sys(msg) {
    if (VERBOSE_SYSTEM) addChatMessage("system", msg);
  }

  function setMicState(state) {
    // state: "idle" | "recording" | "transcribing" | "error"
    if (!btnMic) return;
    btnMic.classList.remove("recording");
    btnMic.dataset.state = state;
    if (state === "recording") btnMic.classList.add("recording");
  }

  // ----------------- utilidades básicas -----------------
  function loadOrCreateSessionId() {
    const key = "orlem_session_id";
    let stored = window.localStorage.getItem(key);
    if (!stored) {
      stored = "sess-" + Math.random().toString(36).slice(2, 10);
      window.localStorage.setItem(key, stored);
    }
    sessionId = stored;
    updateSessionLabel();
  }

  function updateSessionLabel() {
    if (!sessionLabel) return;
    sessionLabel.textContent = `sessão — ${sessionId || "..."}`;
  }

  function setWsStatus(connected) {
    if (connected) {
      wsStatusText.textContent = "Conectado — ouvindo";
      connectionStatus.textContent = "";
      if (sessionDot) {
        sessionDot.style.background = "#22c55e";
        sessionDot.style.boxShadow = "0 0 10px rgba(34,197,94,0.6)";
      }
    } else {
      wsStatusText.textContent = "Desconectado — tentando reconectar…";
      connectionStatus.textContent = VERBOSE_SYSTEM
        ? "Se isso ficar travado, recarrega a página."
        : "";
      if (sessionDot) {
        sessionDot.style.background = "#f97316";
        sessionDot.style.boxShadow = "0 0 8px rgba(249,115,22,0.6)";
      }
    }
  }

  function autoScroll() {
    if (!chatEl) return;
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  function createMessageElement(role, text) {
    const wrapper = document.createElement("div");
    wrapper.classList.add("message");

    if (role === "user") wrapper.classList.add("user");
    else if (role === "orlem") wrapper.classList.add("orlem");
    else wrapper.classList.add("system");

    const label = document.createElement("div");
    label.classList.add("msg-label");

    if (role === "user") label.textContent = "Você";
    else if (role === "orlem") label.textContent = "Orlem";
    else label.textContent = "Sistema";

    const body = document.createElement("div");
    body.textContent = text;

    wrapper.appendChild(label);
    wrapper.appendChild(body);

    return wrapper;
  }

  function addChatMessage(role, text) {
    if (!chatEl || !text) return;
    const el = createMessageElement(role, text);
    chatEl.appendChild(el);
    autoScroll();
  }

  // ----------------- painel da direita -----------------
  function addPanelItem(container, emptyEl, countEl, text) {
    if (!text || !container) return;
    if (emptyEl) emptyEl.style.display = "none";

    const item = document.createElement("div");
    item.classList.add("panel-item");
    item.textContent = text;
    container.appendChild(item);

    if (countEl) {
      const n = container.children.length;
      const label =
        n === 1
          ? countEl.id.includes("actions")
            ? "1 tarefa"
            : countEl.id.includes("decisions")
            ? "1 item"
            : "1 bloco"
          : countEl.id.includes("actions")
          ? `${n} tarefas`
          : countEl.id.includes("decisions")
          ? `${n} itens`
          : `${n} blocos`;
      countEl.textContent = label;
    }
  }

  function routeToPanels(type, text) {
    if (!text) return;

    // 1) Se for um resumo no formato:
    // "Resumo rápido:\n...\n\nDecisões:\n...\n\nPróximos passos:\n..."
    if (type === "summary") {
      const raw = text || "";

      const idxResumo = raw.indexOf("Resumo rápido:");
      const idxDec = raw.indexOf("Decisões:");
      const idxNext = raw.indexOf("Próximos passos:");

      let resumo = "";
      let decisoes = "";
      let proximos = "";

      if (idxResumo !== -1) {
        if (idxDec !== -1) {
          resumo = raw
            .slice(idxResumo + "Resumo rápido:".length, idxDec)
            .trim();
        } else {
          resumo = raw.slice(idxResumo + "Resumo rápido:".length).trim();
        }
      }

      if (idxDec !== -1) {
        if (idxNext !== -1) {
          decisoes = raw
            .slice(idxDec + "Decisões:".length, idxNext)
            .trim();
        } else {
          decisoes = raw.slice(idxDec + "Decisões:".length).trim();
        }
      }

      if (idxNext !== -1) {
        proximos = raw
          .slice(idxNext + "Próximos passos:".length)
          .trim();
      }

      // joga cada linha (- ...) pro painel certo
      if (resumo) {
        resumo
          .split("\n")
          .map((l) => l.trim())
          .filter((l) => l)
          .forEach((l) => {
            const clean = l.replace(/^-+\s*/, "");
            addPanelItem(summaryItems, summaryEmpty, summaryCount, clean);
          });
      }

      if (decisoes) {
        decisoes
          .split("\n")
          .map((l) => l.trim())
          .filter((l) => l)
          .forEach((l) => {
            const clean = l.replace(/^-+\s*/, "");
            addPanelItem(decisionsItems, decisionsEmpty, decisionsCount, clean);
          });
      }

      if (proximos) {
        proximos
          .split("\n")
          .map((l) => l.trim())
          .filter((l) => l)
          .forEach((l) => {
            const clean = l.replace(/^-+\s*/, "");
            addPanelItem(actionsItems, actionsEmpty, actionsCount, clean);
          });
      }

      return;
    }

    // 2) Resumo vindo em formato antigo [RESUMO]...
    if (type === "summary" || text.startsWith("[RESUMO]")) {
      const clean = text.replace(/^\[RESUMO\]\s*/i, "");
      addPanelItem(summaryItems, summaryEmpty, summaryCount, clean);
      return;
    }

    // 3) Diarização
    if (
      type === "diarize" ||
      text.startsWith("[DIARIZAÇÃO]") ||
      text.startsWith("[DIARIZACAO]")
    ) {
      const clean = text
        .replace(/^\[DIARIZAÇÃO\]\s*/i, "")
        .replace(/^\[DIARIZACAO\]\s*/i, "");
      addPanelItem(diarizeItems, diarizeEmpty, diarizeCount, clean);
      return;
    }

    // 4) Heurísticas pra decisões / tarefas em respostas normais
    const low = text.toLowerCase();
    if (
      low.includes("responsável") ||
      low.includes("responsavel") ||
      low.includes("prazo") ||
      low.includes("tarefa") ||
      low.includes("próximo passo") ||
      low.includes("proximo passo")
    ) {
      addPanelItem(actionsItems, actionsEmpty, actionsCount, text);
      return;
    }

    if (
      low.includes("decidimos") ||
      low.includes("ficou decidido") ||
      low.includes("decisão") ||
      low.includes("decisao")
    ) {
      addPanelItem(decisionsItems, decisionsEmpty, decisionsCount, text);
      return;
    }
  }

  // ----------------- TTS -----------------
  async function speak(text) {
    if (!text) return;
    try {
      const resp = await fetch("/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!resp.ok) return;

      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.play();
    } catch (e) {
      console.error("Erro ao tocar voz do Orlem:", e);
    }
  }

  // ----------------- WebSocket -----------------
  function connect() {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${protocol}://${window.location.host}/ws`;

    try {
      ws = new WebSocket(url);
    } catch (err) {
      console.error("Erro ao criar WebSocket:", err);
      setWsStatus(false);
      return;
    }

    ws.addEventListener("open", () => {
      setWsStatus(true);
      if (sessionId) {
        ws.send(JSON.stringify({ session_id: sessionId }));
      }
    });

    ws.addEventListener("message", (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (e) {
        console.warn("Mensagem inválida:", event.data);
        return;
      }

      const type = payload.type;
      const answer = payload.answer;
      const serverSession = payload.session_id;

      if (serverSession && !sessionId) {
        sessionId = serverSession;
        window.localStorage.setItem("orlem_session_id", sessionId);
        updateSessionLabel();
      }

      switch (type) {
        case "status":
          if (!sessionId && payload.session_id) {
            sessionId = payload.session_id;
            window.localStorage.setItem("orlem_session_id", sessionId);
            updateSessionLabel();
          }
          break;

        case "info":
          if (answer) sys(answer); // oculto por padrão
          break;

        case "warn":
          if (answer) sys(answer); // oculto por padrão
          break;

        case "answer":
          if (answer) {
            addChatMessage("orlem", answer);
            routeToPanels("answer", answer);
            speak(answer); // fala a resposta
          }
          break;

        case "summary":
          if (answer) {
            addChatMessage("orlem", answer);
            routeToPanels("summary", answer);
          }
          break;

        case "diarize":
          if (answer) {
            addChatMessage("orlem", answer);
            routeToPanels("diarize", answer);
          }
          break;

        default:
          // silencioso
          break;
      }
    });

    ws.addEventListener("close", () => {
      setWsStatus(false);
      ws = null;
      if (!reconnectTimeout) {
        reconnectTimeout = setTimeout(() => {
          reconnectTimeout = null;
          connect();
        }, 2000);
      }
    });

    ws.addEventListener("error", (err) => {
      console.error("WebSocket error:", err);
      setWsStatus(false);
    });
  }

  function sendPayload(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      sys("Ainda não estou conectado. Tenta de novo em alguns segundos.");
      return;
    }
    try {
      ws.send(JSON.stringify(payload));
    } catch (e) {
      console.error("Erro ao enviar payload:", e);
    }
  }

  // ----------------- handlers de UI -----------------
  function handleSend() {
    if (!inputEl) return;
    const text = (inputEl.value || "").trim();
    if (!text) return;

    addChatMessage("user", text);

    // detecta encerramento
    if (text.toLowerCase().includes("encerrar") || text.toLowerCase() === "end") {
        const payload = {
            action: "end",
            session_id: sessionId,
        };
        sendPayload(payload);
    } 
    else {
        const payload = {
            text,
            session_id: sessionId,
        };
        sendPayload(payload);
    }

    inputEl.value = "";
    inputEl.focus();
}

  function handleSummarize() {
    sys("↺ Pedindo um resumo rápido para o Orlem…");
    sendPayload({
      action: "summarize",
      session_id: sessionId,
    });
  }

  function handleDiarize() {
    sys("👥 Pedindo diarização (por falante) para o Orlem…");
    sendPayload({
      action: "diarize",
      session_id: sessionId,
    });
  }

  function handleEnd() {
    sys("🛑 Encerrando reunião — o Orlem vai gerar um resumo final.");
    sendPayload({
      action: "end",
      session_id: sessionId,
    });
  }

  // ---------- helper para normalizar o nome "Orlem" vindo do STT ----------
  function normalizeOrlemName(text) {
    if (!text) return text;

    const low = text.toLowerCase();

    // se já tiver "orlem" certinho, só padroniza a capitalização
    if (low.includes("orlem")) {
      return text.replace(/orlem/gi, "Orlem");
    }

    const words = text.split(/\s+/);

    const mapped = words.map((word) => {
      const raw = word;
      const clean = word
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "") // tira acentos
        .replace(/[^a-z]/g, ""); // só letras

      const variants = [
        "orlem",
        "orlen",
        "orlan",
        "orlim",
        "orlin",
        "orlem?",
        "orlem.",
        "orlem!",
        "orlem,",
        "orlem;",
        "orlenn",
        "orlennn",
        "orlemn",
        "orlemr",
      ];

      if (variants.includes(clean)) {
        return "Orlem";
      }

      // heurística: tokens começando com "or" e tamanho 3–6 que parecem "orlem"
      if (clean.startsWith("or") && clean.length >= 3 && clean.length <= 6) {
        return "Orlem";
      }

      return raw;
    });

    let fixed = mapped.join(" ");

    // se ainda não tiver Orlem na frase inteira, prefixa
    if (!fixed.toLowerCase().includes("orlem")) {
      fixed = `Orlem, ${fixed}`;
    }

    return fixed;
  }

  // ----------------- microfone / STT -----------------
  // ----------------- microfone / STT -----------------
  async function toggleRecording() {
    if (!btnMic) return;

    // se não está gravando, começa
    if (!mediaRecorder || mediaRecorder.state === "inactive") {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: true,
        });
        mediaRecorder = new MediaRecorder(stream);
        recordedChunks = [];

        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) recordedChunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
          btnMic.classList.remove("recording");

          const blob = new Blob(recordedChunks, { type: "audio/webm" });
          if (!blob.size) {
            addChatMessage(
              "system",
              "Não veio áudio nenhum. Tenta de novo, mais perto do microfone."
            );
            return;
          }

          const form = new FormData();
          form.append("file", blob, "audio.webm");

          try {
            const resp = await fetch("/stt", {
              method: "POST",
              body: form,
            });
            const data = await resp.json();

            if (data && data.text) {
              const rawText = (data.text || "").trim();
              if (!rawText) {
                addChatMessage(
                  "system",
                  "Não consegui entender o áudio. Tenta falar de novo, mais perto do microfone."
                );
                return;
              }

              // 🔧 corrige o nome Orlem e garante que ele seja chamado
              const finalText = normalizeOrlemName(rawText);

              addChatMessage("user", finalText);
              sendPayload({
                text: finalText,
                session_id: sessionId,
              });
            } else {
              addChatMessage(
                "system",
                "Não consegui entender o áudio. Pode tentar de novo?"
              );
            }
          } catch (err) {
            console.error("Erro no /stt:", err);
            addChatMessage(
              "system",
              "Rolou um erro técnico na transcrição. Tenta novamente em alguns segundos."
            );
          }
        };

        mediaRecorder.start();
        btnMic.classList.add("recording");
        // se precisar, pode chamar setMicState("recording") aqui
      } catch (err) {
        console.error("Erro ao acessar microfone:", err);
        setMicState("error");
        sys(
          "Não consegui acessar o microfone. Confere as permissões do navegador."
        );
      }
    } else if (mediaRecorder.state === "recording") {
      mediaRecorder.stop();
      // aqui poderíamos chamar setMicState("idle") se quiser
    }
  }

  // ----------------- init -----------------
  window.addEventListener("DOMContentLoaded", () => {
    loadOrCreateSessionId();
    connect();

    if (sendBtn) sendBtn.addEventListener("click", handleSend);

    if (inputEl) {
      inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          handleSend();
        }
      });
    }

    if (btnSummarize) btnSummarize.addEventListener("click", handleSummarize);
    if (btnDiarize) btnDiarize.addEventListener("click", handleDiarize);
    if (btnEnd) btnEnd.addEventListener("click", handleEnd);
    if (btnMic) btnMic.addEventListener("click", toggleRecording);

    addChatMessage(
      "system",
      "Orlem conectado. Vai acompanhando a reunião em silêncio; quando quiser que ele entre na conversa, chama pelo nome: “Orlem, …”."
    );
  });
})();

// ==========================================
// ORLEM HUB – Helpers para falar com a API
// ==========================================

async function hubApiGet(path) {
  const res = await fetch(path);
  if (!res.ok) {
    console.error(`Erro HTTP em ${path}:`, res.status);
    throw new Error(`Erro ao chamar ${path}: ${res.status}`);
  }
  return await res.json();
}

// Lista todos os projetos (tela "Seus Projetos")
async function hubLoadProjects() {
  const projects = await hubApiGet("/api/projects");
  console.log("Projetos do Orlem Hub:", projects);

  // Preenche os cards na landing
  renderHubProjects(projects);
  return projects;
}

// Lista reuniões de um projeto (tela interna do projeto)
async function hubLoadProjectMeetings(projectId) {
  const meetings = await hubApiGet(`/api/hub/projects/${projectId}/meetings`);
  console.log(`Reuniões do projeto ${projectId}:`, meetings);
  return meetings;
}

// Detalhes completos de uma reunião (tela de reunião)
async function hubLoadMeetingDetails(meetingId) {
  const meeting = await hubApiGet(`/api/hub/meetings/${meetingId}`);
  console.log(`Detalhes da reunião ${meetingId}:`, meeting);
  return meeting;
}

// Reprocessa resumo/decisões/ações da reunião (mock por enquanto)
async function hubRefreshMeeting(meetingId) {
  const res = await fetch(`/api/hub/meetings/${meetingId}/refresh`, {
    method: "POST",
  });
  const data = await res.json();
  console.log("Resumo atualizado (mock):", data);
  return data;
}

// Deixa disponível no console do navegador:
// OrlemHub.loadProjects(), OrlemHub.loadProjectMeetings(1), etc.
window.OrlemHub = {
  loadProjects: hubLoadProjects,
  loadProjectMeetings: hubLoadProjectMeetings,
  loadMeetingDetails: hubLoadMeetingDetails,
  refreshMeeting: hubRefreshMeeting,
};

function renderHubProjects(projects) {
  const listEl = document.getElementById("hub-projects-list");
  const statusEl = document.getElementById("hub-projects-status");
  if (!listEl) return; // se não tiver a seção, só ignora

  // limpar conteúdo anterior
  listEl.innerHTML = "";

  if (!projects || projects.length === 0) {
    listEl.innerHTML = `
      <div class="hub-empty"
           style="
             border-radius:16px;
             border:1px dashed #374151;
             padding:16px 20px;
             font-size:14px;
             color:#9ca3af;
             background:rgba(15,23,42,0.6);
           ">
        Nenhum projeto ainda. Quando o Orlem processar as primeiras reuniões, eles aparecem aqui.
      </div>
    `;
    if (statusEl) statusEl.textContent = "0 projetos";
    return;
  }

  projects.forEach((p) => {
    const card = document.createElement("button");
    card.type = "button";
    card.style.borderRadius = "16px";
    card.style.border = "1px solid #1f2937";
    card.style.padding = "16px 18px";
    card.style.background = "rgba(15,23,42,0.9)";
    card.style.color = "#e5e7eb";
    card.style.textAlign = "left";
    card.style.cursor = "pointer";
    card.style.display = "flex";
    card.style.flexDirection = "column";
    card.style.gap = "6px";

    card.innerHTML = `
      <div style="font-size:14px; font-weight:600;">
        ${p.name}
      </div>
      <div style="font-size:13px; color:#9ca3af;">
        ${p.description || ""}
      </div>
      <div style="font-size:12px; color:#6b7280; margin-top:4px;">
        ${p.meetings_count || 0} reuniões
      </div>
    `;

    card.addEventListener("click", () => {
      console.log("🔗 Clicou no projeto", p.id, p.name);
      // Próximo passo: carregar reuniões desse projeto
      // hubLoadProjectMeetings(p.id);
    });

    listEl.appendChild(card);
  });

  if (statusEl) {
    const n = projects.length;
    statusEl.textContent = n === 1 ? "1 projeto" : `${n} projetos`;
  }
}
