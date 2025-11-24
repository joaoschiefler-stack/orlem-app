# app.py
import os
import io
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI
import tempfile
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from brain import (
    ask_orlem,
    summarize_transcript,
    diarize_transcript,
    extract_decisions,
    extract_actions,
    client_status_message,  # mantido p/ compat
)
from db import (
    init_db,
    get_or_create_default_user,
    create_meeting,
    list_meetings,
    add_message,
    get_meeting_messages,
)

load_dotenv()

app = FastAPI(title="Orlem - Assistente de Reuniões com IA")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # depois podemos restringir
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # em dev pode deixar aberto
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# cliente OpenAI único
client = OpenAI()

MEETINGS_DIR = "meetings"
os.makedirs(MEETINGS_DIR, exist_ok=True)


def save_meeting_json(
    meeting_id: int,
    session_id: str,
    transcript: str,
    summary: str,
    decisions: str,
    actions: str,
    diarization: str,
):
    data = {
        "meeting_id": meeting_id,
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "transcript": transcript,
        "summary": summary,
        "decisions": decisions,
        "actions": actions,
        "diarization": diarization,
    }

    filename = f"meeting_{meeting_id}.json"
    filepath = os.path.join(MEETINGS_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✔ Arquivo salvo: {filepath}")


# =========================================
# FRONTEND
# =========================================

app.mount("/web", StaticFiles(directory="web"), name="web")


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse("web/index.html")


# =========================================
# LOGS EM ARQUIVO
# =========================================
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


def _log_filename(session_id: str) -> str:
    return os.path.join(LOG_DIR, f"{session_id}.jsonl")


def append_to_log(session_id: str, role: str, content: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(_log_filename(session_id), "a", encoding="utf-8") as f:
        f.write(
            json.dumps({"role": role, "content": content}, ensure_ascii=False)
            + "\n"
        )


def list_log_files() -> list[str]:
    """Lista os arquivos de log em /logs em ordem decrescente (mais recente primeiro)."""
    return sorted(
        [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")],
        reverse=True,
    )


def get_latest_meeting_file() -> str | None:
    """
    Retorna o caminho do último arquivo de reunião salvo em /meetings.
    Se não encontrar nada, devolve None.
    """
    folder = MEETINGS_DIR  # já definido lá em cima como "meetings"
    if not os.path.isdir(folder):
        return None

    files = [
        f for f in os.listdir(folder)
        if f.startswith("meeting_") and f.endswith(".json")
    ]
    if not files:
        return None

    # Ordena pelo número depois de "meeting_"
    files.sort(
        key=lambda name: int(name.split("_")[1].split(".")[0]),
        reverse=True,
    )
    return os.path.join(folder, files[0])


@app.get("/logs")
async def list_logs():
    return {"logs": list_log_files()}


@app.get("/api/meeting/latest")
async def get_latest_meeting():
    """
    Devolve os dados da última reunião em um formato amigável pro frontend.
    Usa o JSON salvo em /meetings/meeting_XXX.json.
    """
    path = get_latest_meeting_file()
    if not path:
        raise HTTPException(status_code=404, detail="Nenhuma reunião encontrada")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Campos brutos que já existem no seu JSON
    summary_text = data.get("summary", "") or ""
    decisions_text = data.get("decisions", "") or ""
    actions_text = data.get("actions", "") or ""

    # Quebra em bullets (qualquer linha não vazia)
    def explode_lines(text: str) -> list[str]:
        lines: list[str] = []
        for line in text.split("\n"):
            clean = line.strip().lstrip("-•").strip()
            if clean:
                lines.append(clean)
        return lines

    summary_blocks = explode_lines(summary_text)
    decisions = explode_lines(decisions_text)

    # Transforma ações em MeetingAction[] básico (owner/prazo placeholder por enquanto)
    actions: list[dict[str, Any]] = []
    for idx, line in enumerate(actions_text.split("\n"), start=1):
        clean = line.strip().lstrip("-•").strip()
        if not clean:
            continue
        actions.append(
            {
                "id": idx,
                "text": clean,
                "owner": "Definir responsável",
                "dueDate": None,
            }
        )

    return {
        "meeting_id": data.get("meeting_id"),
        "session_id": data.get("session_id"),
        "timestamp": data.get("timestamp"),
        "summaryBlocks": summary_blocks,
        "decisions": decisions,
        "actions": actions,
    }

@app.get("/logs/{logname}")
async def get_log(logname: str):
    filepath = os.path.join(LOG_DIR, logname)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="log não encontrado")
    with open(filepath, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), media_type="text/plain")


@app.post("/logs/rename")
async def rename_log(payload: Dict[str, Any]):
    old_name = payload.get("old_name")
    new_name = payload.get("new_name")
    if not old_name or not new_name:
        raise HTTPException(
            status_code=400,
            detail="old_name e new_name são obrigatórios",
        )

    old_path = os.path.join(LOG_DIR, old_name)
    new_path = os.path.join(
        LOG_DIR,
        new_name + ("" if new_name.endswith(".jsonl") else ".jsonl"),
    )

    if not os.path.exists(old_path):
        raise HTTPException(status_code=404, detail="log não encontrado")

    os.rename(old_path, new_path)
    return {"ok": True, "new_name": os.path.basename(new_path)}


# =========================================
# API (reuniões / banco)
# =========================================
@app.get("/api/meetings")
async def api_list_meetings():
    user_id = get_or_create_default_user()
    meetings = list_meetings(user_id)
    return {"meetings": meetings}


@app.get("/api/meetings/{meeting_id}")
async def api_get_meeting(meeting_id: int):
    msgs = get_meeting_messages(meeting_id)
    return {"messages": msgs}


@app.get("/api/meeting/open")
async def api_meeting_open(session_id: str = Query(...)):
    """
    Retorna meeting_id existente para session_id (se já houver mensagens),
    senão None — criação passa a ser on-demand (primeira mensagem).
    """
    user_id = get_or_create_default_user()
    logname = f"{session_id}.jsonl"
    has_log = os.path.exists(os.path.join(LOG_DIR, logname))
    return {"meeting_id": None, "has_log": has_log}


def _build_transcript_from_meeting(meeting_id: int) -> str:
    msgs = get_meeting_messages(meeting_id)
    if not msgs:
        return ""
    return "\n".join(f"{m['role']}: {m['content']}" for m in msgs)


@app.get("/api/meetings/{meeting_id}/summary")
async def api_meeting_summary(meeting_id: int):
    transcript = _build_transcript_from_meeting(meeting_id)
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="Reunião sem mensagens.")

    summary = await summarize_transcript(transcript)
    return {"meeting_id": meeting_id, "summary": summary}


@app.get("/api/meetings/{meeting_id}/decisions")
async def api_meeting_decisions(meeting_id: int):
    transcript = _build_transcript_from_meeting(meeting_id)
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="Reunião sem mensagens.")

    decisions = await extract_decisions(transcript)
    return {"meeting_id": meeting_id, "decisions": decisions}


@app.get("/api/meetings/{meeting_id}/actions")
async def api_meeting_actions(meeting_id: int):
    transcript = _build_transcript_from_meeting(meeting_id)
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="Reunião sem mensagens.")

    actions = await extract_actions(transcript)
    return {"meeting_id": meeting_id, "actions": actions}


# =========================================
# WEBSOCKET
# session_id -> meeting_id
# =========================================
active_sessions: Dict[str, int] = {}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # pega session_id da URL (?session_id=...)
    params = ws.query_params
    session_id: Optional[str] = params.get("session_id") or "session-local"

    meeting_id: Optional[int] = None
    user_id = get_or_create_default_user()

    # manda status inicial pro front (Lovable)
    try:
        await ws.send_text(
            json.dumps(
                {
                    "type": "status",
                    "status": "connected",
                    "session_id": session_id,   # snake_case
                    "sessionId": session_id,    # camelCase (Lovable gosta)
                }
            )
        )
    except WebSocketDisconnect:
        return

    try:
        while True:
            # recebe mensagem do front
            data = await ws.receive_text()

            # tenta parsear JSON; se não for, trata como texto puro
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = {"text": data}

            action = payload.get("action")
            text = payload.get("text")

            # se o front enviar outro session_id, atualiza
            sess_from_front = payload.get("session_id")
            if sess_from_front:
                session_id = sess_from_front

            # criação on-demand da reunião (primeira mensagem ou primeiro comando)
            if meeting_id is None and (text or action in {"summarize", "diarize", "end"}):
                meeting_id = create_meeting(
                    user_id,
                    title="Reunião via WebSocket",
                    source="local",
                )
                active_sessions[session_id] = meeting_id
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "info",
                            "answer": f"🔗 sessão vinculada à reunião #{meeting_id}",
                        }
                    )
                )

            # ---------------------------------
            # AÇÃO: RESUMO RÁPIDO ("Resumo")
            # ---------------------------------
            if action == "summarize":
                if meeting_id is None:
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "warn",
                                "answer": "⚠️ Sem mensagens para resumir.",
                            }
                        )
                    )
                    continue

                msgs = get_meeting_messages(meeting_id)
                transcript = "\n".join(
                    f"{m['role']}: {m['content']}" for m in msgs
                )

                answer = await summarize_transcript(transcript)
                append_to_log(session_id, "orlem", "[RESUMO] " + answer)
                add_message(meeting_id, "orlem", "[RESUMO] " + answer)

                await ws.send_text(
                    json.dumps({"type": "summary", "answer": answer})
                )
                continue

            # ---------------------------------
            # AÇÃO: DIARIZAÇÃO ("Diarizar")
            # ---------------------------------
            if action == "diarize":
                if meeting_id is None:
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "warn",
                                "answer": "⚠️ Sem mensagens para diarizar.",
                            }
                        )
                    )
                    continue

                msgs = get_meeting_messages(meeting_id)
                transcript = "\n".join(
                    f"{m['role']}: {m['content']}" for m in msgs
                )

                answer = await diarize_transcript(transcript)
                append_to_log(session_id, "orlem", "[DIARIZAÇÃO] " + answer)
                add_message(meeting_id, "orlem", "[DIARIZAÇÃO] " + answer)

                await ws.send_text(
                    json.dumps({"type": "diarize", "answer": answer})
                )
                continue

            # ---------------------------------
            # AÇÃO: ENCERRAR REUNIÃO ("Encerrar")
            # ---------------------------------
            if action == "end":
                if meeting_id is None:
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "warn",
                                "answer": "⚠️ Nenhuma mensagem na reunião.",
                            }
                        )
                    )
                    continue

                # avisa o front que vai encerrar
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "info",
                            "answer": "🛑 Encerrando reunião... gerando resumo.",
                        }
                    )
                )

                # pega todo o histórico da reunião
                msgs = get_meeting_messages(meeting_id)
                transcript = "\n".join(
                    f"{m['role']}: {m['content']}" for m in msgs
                )

                if not transcript.strip():
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "warn",
                                "answer": "⚠️ Sem mensagens para resumir.",
                            }
                        )
                    )
                    continue

                # resumo final
                summary = await summarize_transcript(transcript)
                append_to_log(session_id, "orlem", "[RESUMO] " + summary)
                add_message(meeting_id, "orlem", "[RESUMO] " + summary)

                # tenta extrair decisões / ações / diarização do histórico
                decisions = "\n".join(
                    m["content"]
                    for m in msgs
                    if "[DECISÃO]" in m.get("content", "")
                )

                actions = "\n".join(
                    m["content"]
                    for m in msgs
                    if any(
                        tag in m.get("content", "")
                        for tag in ["[TAREFA]", "[ACTION]", "[PRÓXIMO PASSO]"]
                    )
                )

                diarization = "\n".join(
                    m["content"]
                    for m in msgs
                    if "[DIARIZAÇÃO]" in m.get("content", "")
                )

                # salva a reunião em JSON na pasta meetings/
                try:
                    save_meeting_json(
                        meeting_id=meeting_id,
                        session_id=session_id,
                        transcript=transcript,
                        summary=summary,
                        decisions=decisions,
                        actions=actions,
                        diarization=diarization,
                    )
                except Exception as e:
                    print("Erro ao salvar reunião:", e)

                # manda o resumo pro frontend
                await ws.send_text(
                    json.dumps({"type": "summary", "answer": summary})
                )
                continue

            # ---------------------------------
            # MENSAGEM NORMAL DA REUNIÃO
            # ---------------------------------
            if text:
                if meeting_id is None:
                    meeting_id = create_meeting(
                        user_id,
                        title="Reunião via WebSocket",
                        source="local",
                    )
                    active_sessions[session_id] = meeting_id
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "info",
                                "answer": f"🔗 sessão vinculada à reunião #{meeting_id}",
                            }
                        )
                    )

                # registra sempre (Orlem está ouvindo)
                append_to_log(session_id, "user", text)
                add_message(meeting_id, "user", text)

                lower_text = text.lower()
                if "orlem" not in lower_text:
                    # só ouvindo; não responde
                    continue

                # aqui ele realmente responde
                answer = await ask_orlem(text)
                if answer is None:
                    continue

                if isinstance(answer, dict):
                    answer = (
                        answer.get("answer")
                        or answer.get("text")
                        or json.dumps(answer, ensure_ascii=False)
                    )

                answer = str(answer)
                if not answer.strip():
                    continue

                append_to_log(session_id, "orlem", answer)
                add_message(meeting_id, "orlem", answer)

                await ws.send_text(
                    json.dumps({"type": "answer", "answer": answer})
                )
                continue

            # ---------------------------------
            # FALLBACK (nenhum caso bateu)
            # ---------------------------------
            await ws.send_text(
                json.dumps(
                    {
                        "type": "warn",
                        "answer": "⚠️ Comando desconhecido.",
                    }
                )
            )

    except WebSocketDisconnect:
        return


# =========================================
# STT / TRANSCRIÇÃO DO ÁUDIO (versão final)
# =========================================
@app.post("/stt")
@app.post("/api/stt")  # alias para compat com Lovable
async def stt_endpoint(
    file: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    session_id: str = Form("session-local"),
):
    """
    Recebe áudio (campo 'file' OU 'audio'),
    transcreve usando gpt-4o-mini-transcribe e devolve {"text": "..."}.

    Também registra no log / reunião automaticamente se houver
    uma meeting ativa para esse session_id.
    """
    upload = file or audio
    if upload is None:
        raise HTTPException(
            status_code=400,
            detail="Nenhum arquivo de áudio enviado."
        )

    tmp_path: Optional[str] = None

    try:
        suffix = ".webm"
        filename = (upload.filename or "").lower()
        if filename.endswith(".ogg"):
            suffix = ".ogg"
        elif filename.endswith(".mp3"):
            suffix = ".mp3"
        elif filename.endswith(".wav"):
            suffix = ".wav"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await upload.read())
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=f,
                response_format="json",
            )

        text = ""
        if isinstance(resp, dict):
            text = resp.get("text", "") or ""
        else:
            text = getattr(resp, "text", "") or ""
        text = (text or "").strip()

        if text:
            meeting_id = active_sessions.get(session_id)
            if meeting_id is not None:
                append_to_log(session_id, "user-voice", text)
                add_message(meeting_id, "user", text)

        return {"text": text}

    except Exception as e:
        print("ERRO /stt:", repr(e))
        return {"error": f"Erro ao transcrever: {e}"}

    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# =========================================
# TTS / FALA DO ORLEM
# =========================================
@app.post("/speak")
async def speak_endpoint(payload: dict):
    text = payload.get("text", "")
    if not text:
        return {"error": "Texto vazio"}

    try:
        speech = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="coral",
            input=text,
        )
        audio_bytes = speech.read()
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
        )
    except Exception as e:
        print("ERRO /speak:", e)
        return {
            "error": "Falha na voz, continuo por texto",
            "detail": str(e),
            "text": text,
        }


# =========================================
# "BANCO" FAKE PARA O ORLEM HUB (MVP)
# =========================================

# Projetos fake
PROJECTS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "name": "Product Team Q1",
        "description": "Reuniões de produto do primeiro trimestre",
        "meetings_count": 3,
    },
    {
        "id": 2,
        "name": "Engineering Sprint Planning",
        "description": "Planejamento de sprints da engenharia",
        "meetings_count": 2,
    },
    {
        "id": 3,
        "name": "Marketing Strategy",
        "description": "Estratégia de marketing e crescimento",
        "meetings_count": 2,
    },
]

# Relação projeto -> lista de IDs de reuniões
PROJECT_MEETINGS: Dict[int, List[int]] = {
    1: [101, 102, 103],
    2: [201, 202],
    3: [301, 302],
}

# Reuniões fake
MEETINGS: Dict[int, Dict[str, Any]] = {
    101: {
        "id": 101,
        "project_id": 1,
        "title": "Sprint Planning Q1",
        "platform": "Zoom",
        "date": "2024-01-15T10:00:00",
        "duration_minutes": 45,
        "decisions_count": 5,
        "actions_count": 8,
        "summary_blocks": [
            "A equipe priorizou a nova área de analytics para Q1.",
            "Decidido reduzir débitos técnicos críticos e focar em PLG para trials pagos.",
        ],
        "decisions": [
            "Priorizar feature de analytics no Q1.",
            "Reduzir débitos técnicos críticos antes de novos lançamentos.",
            "Focar aquisição via produto (PLG) em trials pagos.",
            "Realocar 1 dev full-time para o squad de analytics.",
            "Rever budget de marketing com base nas novas métricas.",
        ],
        "actions": [
            "João: revisar backlog de débitos técnicos até sexta.",
            "Maria: atualizar roadmap e compartilhar com stakeholders.",
            "Ana: preparar métricas de PLG para o próximo comitê.",
            "Time de dados: validar eventos de produto até o dia 25.",
            "Pedro: alinhar com CS sobre impacto nas contas enterprise.",
        ],
        "transcript": "Aqui iria o texto longo da transcrição da reunião Sprint Planning Q1...",
    },
    102: {
        "id": 102,
        "project_id": 1,
        "title": "Product Roadmap Review",
        "platform": "Meet",
        "date": "2024-01-14T14:00:00",
        "duration_minutes": 30,
        "decisions_count": 3,
        "actions_count": 4,
        "summary_blocks": [
            "Revisão do roadmap de produto para o semestre.",
            "Ajustes em prioridades de features B2B.",
        ],
        "decisions": [
            "Despriorizar feature de relatórios customizados.",
            "Aumentar foco em integrações com ferramentas de analytics.",
            "Rever timeline de lançamento da nova dashboard.",
        ],
        "actions": [
            "Time de produto: atualizar roadmap público.",
            "Dev líder: revisar estimativas das novas integrações.",
            "Marketing: ajustar mensagens para clientes enterprise.",
            "CS: preparar FAQ sobre mudanças no roadmap.",
        ],
        "transcript": "Transcrição fake da reunião Product Roadmap Review...",
    },
    # Você pode duplicar/ajustar mais reuniões se quiser
}


# =========================================
# ENDPOINTS PARA O ORLEM HUB
# =========================================

@app.get("/api/projects")
async def list_projects():
    """
    Lista todos os projetos disponíveis no Orlem Hub.
    Esse endpoint é para a tela 'Seus Projetos'.
    """
    return PROJECTS


@app.get("/api/hub/projects/{project_id}/meetings")
async def list_project_meetings(project_id: int):
    """
    Lista todas as reuniões de um projeto específico.
    Tela: dentro do projeto (lista de reuniões).
    """
    if project_id not in PROJECT_MEETINGS:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    meeting_ids = PROJECT_MEETINGS[project_id]
    meetings = [MEETINGS[mid] for mid in meeting_ids if mid in MEETINGS]
    return meetings


@app.get("/api/hub/meetings/{meeting_id}")
async def get_meeting(meeting_id: int):
    """
    Retorna os detalhes completos de uma reunião:
    - resumo
    - decisões
    - ações
    - transcrição
    Tela: página da reunião (Sprint Planning Q1, etc.).
    """
    meeting = MEETINGS.get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")
    return meeting


@app.post("/api/hub/meetings/{meeting_id}/refresh")
async def refresh_meeting_summary(meeting_id: int):
    """
    Reprocessa o resumo/decisões/ações de uma reunião.
    Por enquanto é só um mock que altera um texto.
    Depois podemos plugar aqui sua função de IA de resumo.
    """
    meeting = MEETINGS.get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")

    # Mock simples só pra mostrar que "atualizou"
    meeting["summary_blocks"] = [
        "Resumo atualizado automaticamente pelo Orlem.",
        "Esta é apenas uma simulação — depois conectamos na IA real.",
    ]

    return {
        "status": "ok",
        "message": "Resumo reprocessado (mock).",
        "meeting": meeting,
    }
