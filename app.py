# app.py
import os
import json
from typing import Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from brain import (
    ask_orlem,
    summarize_transcript,
    diarize_transcript,
    client_status_message,  # continua importado, mesmo se não usar agora
)
from db import (
    init_db,
    get_or_create_default_user,
    create_meeting,
    list_meetings,
    add_message,
    get_meeting_messages,
)

from openai import OpenAI
import io

load_dotenv()

app = FastAPI(title="Orlem - Assistente de Reuniões com IA")
init_db()

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
        # ensure_ascii=False pra não zoar acento
        f.write(
            json.dumps({"role": role, "content": content}, ensure_ascii=False)
            + "\n"
        )


def list_log_files():
    return sorted(
        [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")],
        reverse=True,
    )


@app.get("/logs")
async def list_logs():
    return {"logs": list_log_files()}


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


# =========================================
# WEBSOCKET
# =========================================

# session_id -> meeting_id
active_sessions: Dict[str, int] = {}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # session_id vindo por query param (futuro deploy) ou usa um fallback
    params = ws.query_params
    session_id: Optional[str] = params.get("session_id") or None
    if session_id is None:
        session_id = "session-local"

    meeting_id: Optional[int] = None
    user_id = get_or_create_default_user()

    # status simples, só pra client saber o id da sessão
    try:
        await ws.send_text(
            json.dumps(
                {
                    "type": "status",
                    "session_id": session_id,
                }
            )
        )
    except WebSocketDisconnect:
        return

    try:
        while True:
            data = await ws.receive_text()

            # tenta JSON
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = {"text": data}

            action = payload.get("action")
            text = payload.get("text")
            sess_from_front = payload.get("session_id") or session_id
            session_id = sess_from_front  # normaliza

            # cria meeting apenas no primeiro envio real de mensagem do usuário
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

            # ----- ações especiais -----

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

                await ws.send_text(
                    json.dumps(
                        {
                            "type": "info",
                            "answer": "🛑 Encerrando reunião... gerando resumo.",
                        }
                    )
                )

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
                else:
                    answer = await summarize_transcript(transcript)
                    append_to_log(session_id, "orlem", "[RESUMO] " + answer)
                    add_message(meeting_id, "orlem", "[RESUMO] " + answer)
                    await ws.send_text(
                        json.dumps({"type": "summary", "answer": answer})
                    )
                continue

            # ----- mensagem normal do usuário -----

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

                append_to_log(session_id, "user", text)
                add_message(meeting_id, "user", text)

                # chama o cérebro
                answer = await ask_orlem(text)

                append_to_log(session_id, "orlem", answer)
                add_message(meeting_id, "orlem", answer)

                await ws.send_text(
                    json.dumps({"type": "answer", "answer": answer})
                )
                continue

            # fallback
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
# TTS / FALA DO ORLEM
# =========================================

client = OpenAI()


@app.post("/speak")
async def speak_endpoint(payload: dict):
    text = payload.get("text", "")
    if not text:
        return {"error": "Texto vazio"}

    # Gera voz natural a partir do texto
    speech = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="alloy",  # outras opções: verse, coral, etc.
        input=text,
    )

    # Retorna o áudio como streaming
    return StreamingResponse(
        io.BytesIO(speech.read()),
        media_type="audio/mpeg",
    )
