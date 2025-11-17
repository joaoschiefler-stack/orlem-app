# app.py
import os
import io
import json
from typing import Dict, Any, Optional

from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    Query,
    UploadFile,
    File,
)
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware  # <-- NOVO
from dotenv import load_dotenv
from openai import OpenAI

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

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Orlem - Assistente de Reuniões com IA")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # em dev pode deixar aberto
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# cliente OpenAI único
client = OpenAI()

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
# =========================================

# session_id -> meeting_id
active_sessions: Dict[str, int] = {}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    params = ws.query_params
    session_id: Optional[str] = params.get("session_id") or None
    if session_id is None:
        session_id = "session-local"

    meeting_id: Optional[int] = None
    user_id = get_or_create_default_user()

    # manda status inicial
       # manda status inicial
    try:
        await ws.send_text(
            json.dumps(
                {
                    "type": "status",
                    "status": "connected",   # ajuda o front a trocar o badge
                    "session_id": session_id,  # snake_case (nosso)
                    "sessionId": session_id,   # camelCase (Lovable costuma usar isso)
                }
            )
        )

    except WebSocketDisconnect:
        return

    try:
        while True:
            data = await ws.receive_text()

            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = {"text": data}

            action = payload.get("action")
            text = payload.get("text")
            sess_from_front = payload.get("session_id") or session_id
            session_id = sess_from_front

            # criação on-demand da reunião
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

            # --------- ações especiais ---------

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

            # --------- mensagem normal ---------
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
                    # apenas ouvindo, não responde
                    continue

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
# STT / TRANSCRIÇÃO DO ÁUDIO
# =========================================
import tempfile


@app.post("/stt")
async def stt_endpoint(
    file: UploadFile = File(None),
    audio: UploadFile = File(None),
):
    """
    Recebe áudio do browser (normalmente .webm / .ogg) e devolve o texto transcrito.

    - Suporta dois nomes de campo:
      - `file`  → usado pelo front antigo (index.html/client.js)
      - `audio` → usado pelo app do Lovable
    """
    upload = file or audio

    if upload is None:
        return {"error": "Arquivo de áudio vazio."}

    audio_bytes = await upload.read()
    if not audio_bytes:
        return {"error": "Arquivo de áudio vazio."}

    # 1) Escreve o blob em disco (forma mais estável para a SDK)
    suffix = ".webm" if (upload.filename or "").lower().endswith(".webm") else ".ogg"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        # 2) Envia o arquivo para o Whisper-1
        with open(tmp_path, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,           # file-like real ⇒ evita falhas de mimetype
                response_format="json",
            )

        text = (getattr(result, "text", "") or "").strip()
        return {"text": text}

    except Exception as e:
        print("ERRO /stt:", e)
        return {"error": str(e)}
