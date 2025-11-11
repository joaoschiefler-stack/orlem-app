import os
from textwrap import dedent

os.makedirs("web", exist_ok=True)
os.makedirs("logs", exist_ok=True)

app_py = dedent("""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os
from datetime import datetime
from brain import ask_orlem

load_dotenv()

app = FastAPI(title="Orlem - Assistente de Reuniões com IA")

app.mount("/web", StaticFiles(directory="web"), name="web")

@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse("web/index.html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            answer = await ask_orlem(data)
            await websocket.send_text(answer)
            save_log(data, answer)
    except WebSocketDisconnect:
        print("Cliente desconectado")

def save_log(user_msg: str, bot_msg: str):
    os.makedirs("logs", exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"logs/{now}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"USER: {user_msg}\\n")
        f.write(f"ORLEM: {bot_msg}\\n")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
""")

brain_py = dedent("""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = (
    "Você é o Orlem, assistente de reuniões. "
    "Responda curto, direto e em português do Brasil. "
    "Se o usuário estiver falando sobre pessoas diferentes na call, ajude a identificar. "
    "Se for transcrição de reunião, resuma e organize."
)

async def ask_orlem(user_message: str) -> str:
    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    return completion.choices[0].message.content
""")

index_html = dedent("""
<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8" />
    <title>Orlem — Assistente de Reuniões</title>
    <meta name="viewport" content="width=device-width,initial-scale=1" />
  </head>
  <body>
    <h1>Orlem — Assistente de Reuniões</h1>
    <div id="timeline"></div>
    <input id="utterance" placeholder="Digite algo..." />
    <button id="sendBtn">Enviar</button>
    <script src="client.js"></script>
  </body>
</html>
""")

client_js = dedent("""
const WS_URL = "ws://127.0.0.1:8000/ws";
const sendBtn = document.getElementById("sendBtn");
const utterance = document.getElementById("utterance");
const timeline = document.getElementById("timeline");

let socket = null;

function connectWS() {
  socket = new WebSocket(WS_URL);
  socket.onopen = () => console.log("WS conectado");
  socket.onmessage = (event) => addMessage("orlem", event.data);
}
function addMessage(who, text) {
  const div = document.createElement("div");
  div.textContent = who.toUpperCase() + ": " + text;
  timeline.appendChild(div);
}
sendBtn.onclick = () => {
  const text = utterance.value.trim();
  if (!text) return;
  addMessage("you", text);
  socket.send(text);
  utterance.value = "";
};
connectWS();
""")

env_file = "OPENAI_API_KEY=sua_chave_aqui\nMODEL_NAME=gpt-4o-mini\n"

reqs = "fastapi\nuvicorn\npython-dotenv\nrequests\nopenai\n"

gitignore = ".venv/\n__pycache__/\n*.pyc\n.env\nlogs/\n.vscode/\n"

readme = dedent("""
# Orlem — Assistente de Reuniões com IA
1. python -m venv .venv
2. .venv\\Scripts\\activate
3. pip install -r requirements.txt
4. uvicorn app:app --reload
5. abrir http://127.0.0.1:8000
""")

with open("app.py", "w", encoding="utf-8") as f: f.write(app_py)
with open("brain.py", "w", encoding="utf-8") as f: f.write(brain_py)
with open("requirements.txt", "w", encoding="utf-8") as f: f.write(reqs)
with open(".gitignore", "w", encoding="utf-8") as f: f.write(gitignore)
with open(".env", "w", encoding="utf-8") as f: f.write(env_file)
with open("README.md", "w", encoding="utf-8") as f: f.write(readme)

os.makedirs("web", exist_ok=True)
with open(os.path.join("web", "index.html"), "w", encoding="utf-8") as f: f.write(index_html)
with open(os.path.join("web", "client.js"), "w", encoding="utf-8") as f: f.write(client_js)

os.makedirs("logs", exist_ok=True)
print("✅ Projeto ORLEM criado com sucesso!")