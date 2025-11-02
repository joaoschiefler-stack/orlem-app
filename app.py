# app.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from datetime import datetime
from uuid import uuid4

from brain import (
    ask_orlem,
    summarize_transcript,
    extract_decisions,
    extract_actions,
    client_status_message,
)

app = FastAPI(title="Orlem - Assistente de Reuniões com IA")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/web", StaticFiles(directory="web"), name="web")

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


def _new_session_id() -> str:
    return f"sess-{datetime.now().strftime('%Y%m%d-%H%M%S')}{uuid4().hex[:4]}"


def append_log(session_id: str, role: str, content: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{session_id}.jsonl")
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "role": role,
        "content": content,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_logs() -> list[str]:
    return [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")]


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse("web/index.html")


@app.get("/logs")
async def get_logs():
    return {"logs": list_logs()}


@app.get("/logs/{logname}", response_class=PlainTextResponse)
async def get_log_content(logname: str):
    path = os.path.join(LOG_DIR, logname)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Log não encontrado")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/logs/rename")
async def rename_log(payload: dict):
    old_name = payload.get("old_name")
    new_name = payload.get("new_name")
    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="old_name e new_name são obrigatórios")

    old_path = os.path.join(LOG_DIR, old_name)
    if not os.path.exists(old_path):
        raise HTTPException(status_code=404, detail="Log não encontrado")

    if not new_name.endswith(".jsonl"):
        new_name = new_name + ".jsonl"

    new_path = os.path.join(LOG_DIR, new_name)
    os.rename(old_path, new_path)
    return {"ok": True, "new_name": new_name}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    session_id = _new_session_id()
    await websocket.send_text(
        json.dumps(
            {
                "type": "status",
                "session_id": session_id,
                "answer": "Conectado. Reunião será salva automaticamente.",
            },
            ensure_ascii=False,
        )
    )

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"text": raw}

            text = data.get("text", "").strip()
            action = data.get("action")
            req_session_id = data.get("session_id") or session_id

            # ======== AÇÃO: RESUMIR =========
            if action == "summarize":
                target_log = data.get("target_log")  # nome do arquivo .jsonl vindo do front
                transcript = ""

                # 1) se veio alvo -> resumir o log clicado
                if target_log:
                    path = os.path.join(LOG_DIR, target_log)
                    if os.path.exists(path):
                        with open(path, "r", encoding="utf-8") as f:
                            parts = []
                            for line in f:
                                try:
                                    obj = json.loads(line)
                                    parts.append(f"{obj.get('role')}: {obj.get('content')}")
                                except Exception:
                                    pass
                            transcript = "\n".join(parts)
                    else:
                        transcript = "Log não encontrado."
                else:
                    # 2) senão, resumir sessão atual
                    path = os.path.join(LOG_DIR, f"{req_session_id}.jsonl")
                    if os.path.exists(path):
                        with open(path, "r", encoding="utf-8") as f:
                            parts = []
                            for line in f:
                                try:
                                    obj = json.loads(line)
                                    parts.append(f"{obj.get('role')}: {obj.get('content')}")
                                except Exception:
                                    pass
                            transcript = "\n".join(parts)
                    else:
                        transcript = "Nenhum conteúdo salvo para esta sessão."

                summary = await summarize_transcript(transcript)
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "summary",
                            "session_id": req_session_id,
                            "answer": summary,
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            # ======== AÇÃO: SAVE (já salva automático) =========
            if action == "save":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "info",
                            "session_id": req_session_id,
                            "answer": "Reunião já está sendo salva automaticamente em logs/.",
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            # ======== AÇÃO: DIARIZE (fake) =========
            if action == "diarize":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "diarize",
                            "session_id": req_session_id,
                            "answer": "Diarização (mock): Speaker 1 (João), Speaker 2 (Maria), Speaker 3 (Pedro).",
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            # ======== MENSAGEM NORMAL =========
            if text:
                append_log(req_session_id, "user", text)
                answer = await ask_orlem(text)
                append_log(req_session_id, "assistant", answer)
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "answer",
                            "session_id": req_session_id,
                            "answer": answer,
                        },
                        ensure_ascii=False,
                    )
                )

    except WebSocketDisconnect:
        print("Cliente desconectado")
