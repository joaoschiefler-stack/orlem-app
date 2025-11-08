// web/client.js
let ws = null;
let sessionId = localStorage.getItem("orlem_session_id") || `session-${crypto.randomUUID().slice(0,8)}`;
localStorage.setItem("orlem_session_id", sessionId);

const $ = (q) => document.querySelector(q);
const timeline = $("#timeline");
const wsStatus = $("#ws-status");
const currentSession = $("#current-session");

function pillOnline(on){
  if(on){ wsStatus.classList.add("online"); wsStatus.innerHTML = `<span class="dot"></span>conectado`; }
  else { wsStatus.classList.remove("online"); wsStatus.innerHTML = `<span class="dot"></span>desconectado`; }
}
function pushMsg(role, text, cls=""){
  const div = document.createElement("div");
  div.className = `msg ${cls} ${role==='user'?'user':role==='system'?'system':'bot'}`;
  div.textContent = text;
  timeline.appendChild(div);
  timeline.scrollTop = timeline.scrollHeight;
}

async function loadLogs(){
  const res = await fetch("/logs");
  const data = await res.json();
  const box = $("#logs-list"); box.innerHTML = "";
  data.logs.forEach(name=>{
    const item = document.createElement("div");
    item.className = "log-item"; item.textContent = name;
    item.onclick = async ()=>{
      const r = await fetch(`/logs/${name}`);
      const txt = await r.text();
      pushMsg("system", `Abrindo log: ${name}`);
      txt.trim().split("\n").forEach(line=>{
        try{
          const obj = JSON.parse(line);
          pushMsg(obj.role, obj.content, obj.role==="orlem"?"bot":"");
        }catch{}
      });
    };
    box.appendChild(item);
  });
}

async function loadMeetings(){
  const res = await fetch("/api/meetings");
  const data = await res.json();
  const box = $("#meetings-list"); box.innerHTML = "";
  data.meetings.forEach(m=>{
    const item = document.createElement("div");
    item.className = "log-item";
    item.textContent = `${m.title} — ${m.created_at} #${m.id}`;
    item.onclick = async ()=>{
      pushMsg("system", `Abrindo reunião do DB: #${m.id} — ${m.title}`);
      const r = await fetch(`/api/meetings/${m.id}`);
      const js = await r.json();
      const msgs = js.messages || [];
      if(!msgs.length){ pushMsg("system","Esta reunião não tem mensagens salvas."); return; }
      msgs.forEach(mm=>{
        const role = mm.role; const txt = mm.content;
        pushMsg(role, txt, role==="orlem"?"bot":"");
      });
    };
    box.appendChild(item);
  });
}

function connectWs(){
  const url = `ws://${location.host}/ws?session_id=${encodeURIComponent(sessionId)}`;
  ws = new WebSocket(url);

  ws.onopen = ()=>{
    pillOnline(true);
    currentSession.textContent = `log: ${sessionId}.jsonl`;
  };
  ws.onclose = ()=> pillOnline(false);

  ws.onmessage = (ev)=>{
    try{
      const data = JSON.parse(ev.data);
      if(data.type==="answer"){ pushMsg("orlem", data.answer, "bot"); }
      else if(data.type==="summary"){ pushMsg("orlem", "📄 [RESUMO] " + data.answer, "bot"); }
      else if(data.type==="diarize"){ pushMsg("orlem", "🧑‍🤝‍🧑 [DIARIZAÇÃO] " + data.answer, "bot"); }
      else if(data.type==="info"){ pushMsg("system", data.answer); }
      else if(data.type==="warn"){ pushMsg("system", data.answer, "warn"); }
      else{
        // status inicial ou payload não tipado
        pushMsg("system", "Conexão pronta.");
      }
    }catch{
      pushMsg("system", ev.data);
    }
  };
}

$("#sendBtn").onclick = ()=>{
  const txt = $("#utterance").value.trim();
  if(!txt) return;
  pushMsg("user", txt);
  $("#utterance").value = "";

  ws.send(JSON.stringify({ session_id: sessionId, text: txt }));
};

$("#summarize").onclick = ()=> ws.send(JSON.stringify({ session_id: sessionId, action: "summarize" }));
$("#diarize").onclick   = ()=> ws.send(JSON.stringify({ session_id: sessionId, action: "diarize" }));
$("#endMeeting").onclick= ()=> ws.send(JSON.stringify({ session_id: sessionId, action: "end" }));
$("#save").onclick      = ()=> pushMsg("system","✅ reunião já está sendo salva automaticamente.");
$("#rename").onclick    = async ()=>{
  const newName = prompt("Novo nome do log (sem .jsonl):", sessionId);
  if(!newName) return;
  const old = `${sessionId}.jsonl`;
  const payload = { old_name: old, new_name: newName };
  const res = await fetch("/logs/rename", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(payload) });
  if(res.ok){
    sessionId = newName;
    localStorage.setItem("orlem_session_id", sessionId);
    currentSession.textContent = `log: ${sessionId}.jsonl`;
    pushMsg("system", "✅ log renomeado.");
    loadLogs();
  }else{
    pushMsg("system", "❌ não foi possível renomear.", "warn");
  }
};
$("#export").onclick    = ()=> window.open(`/logs/${sessionId}.jsonl`, "_blank");
$("#loadMeetings").onclick = ()=> loadMeetings();
$("#refresh-logs").onclick = ()=> loadLogs();

// BOOT
connectWs();
loadLogs();
loadMeetings();
