// client.js
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
      connectionStatus.textContent =
        "Se isso ficar travado, recarrega a página.";
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

    if (type === "summary" || text.startsWith("[RESUMO]")) {
      const clean = text.replace(/^\[RESUMO\]\s*/i, "");
      addPanelItem(summaryItems, summaryEmpty, summaryCount, clean);
      return;
    }

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
          if (answer) addChatMessage("system", answer);
          break;

        case "warn":
          if (answer) addChatMessage("system", answer);
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
          console.log("Tipo desconhecido:", payload);
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
      addChatMessage(
        "system",
        "Ainda não estou conectado. Tenta de novo em alguns segundos."
      );
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
    const text = (inputEl.value || "").trim();
    if (!text) return;

    addChatMessage("user", text);

    const payload = {
      text,
      session_id: sessionId,
    };
    sendPayload(payload);

    inputEl.value = "";
    inputEl.focus();
  }

  function handleSummarize() {
    addChatMessage("system", "↺ Pedindo um resumo rápido para o Orlem…");
    sendPayload({
      action: "summarize",
      session_id: sessionId,
    });
  }

  function handleDiarize() {
    addChatMessage("system", "👥 Pedindo diarização (por falante) para o Orlem…");
    sendPayload({
      action: "diarize",
      session_id: sessionId,
    });
  }

  function handleEnd() {
    addChatMessage(
      "system",
      "🛑 Encerrando reunião — o Orlem vai gerar um resumo final."
    );
    sendPayload({
      action: "end",
      session_id: sessionId,
    });
  }

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
              "Não capturei áudio nenhum. Tenta de novo, por favor."
            );
            return;
          }

          addChatMessage(
            "system",
            "Parando gravação, transcrevendo o áudio…"
          );

          const form = new FormData();
          form.append("file", blob, "audio.webm");

          try {
            const resp = await fetch("/stt", {
              method: "POST",
              body: form,
            });
            const data = await resp.json();

            if (data && data.text) {
              const text = data.text.trim();
              if (!text) {
                addChatMessage(
                  "system",
                  "Não consegui entender o áudio. Tenta falar de novo, mais perto do microfone."
                );
                return;
              }

              // mostra como mensagem do usuário
              addChatMessage("user", text);
              // manda pro Orlem via WebSocket
              sendPayload({
                text,
                session_id: sessionId,
              });
            } else {
              addChatMessage(
                "system",
                "Erro ao transcrever o áudio. Tenta novamente."
              );
            }
          } catch (err) {
            console.error("Erro no /stt:", err);
            addChatMessage(
              "system",
              "Erro ao transcrever o áudio. Tenta novamente."
            );
          }
        };

        mediaRecorder.start();
        btnMic.classList.add("recording");
        addChatMessage(
          "system",
          "Gravando… Clique de novo no microfone para parar."
        );
      } catch (err) {
        console.error("Erro ao acessar microfone:", err);
        addChatMessage(
          "system",
          "Não consegui acessar o microfone. Confere as permissões do navegador."
        );
      }
    } else if (mediaRecorder.state === "recording") {
      mediaRecorder.stop();
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
