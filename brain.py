# brain.py
"""
ORLEM — cérebro completo (fase 1)

- responde como sócio na call
- cobre: cliente, atraso, resumo, decisões, próximos passos, conflito, vendas, suporte,
  segurança/LGPD, contratação, retro, mudança de escopo, orçamento, e-mail, whatsapp,
  brainstorming, OKR, treinamento
- responde curto (3-5 frases)
- expõe client_status_message(...) pra compat com app.py
"""

import os
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------
# 0. Setup
# ---------------------------------------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------------------------------------
# 1. Prompts base
# ---------------------------------------------------------
BASE_SYSTEM = (
    "Você é o ORLEM, um assistente de reuniões que age como um sócio humano, experiente, "
    "que está dentro da call. Responda em português do Brasil. "
    "Regra padrão: responda em 3 a 5 frases. "
    "Não diga que é IA. Não diga 'como modelo de linguagem'. "
    "Se o usuário falar de cliente, seja profissional. Se for interno, seja direto."
)

SUMMARIZER_SYSTEM = (
    "Você é o Orlem e vai resumir uma reunião. "
    "Estruture assim:\n"
    "1) Contexto rápido (1 frase)\n"
    "2) Pontos principais (bullets curtos)\n"
    "3) Decisões (se houver)\n"
    "4) Próximos passos (com responsáveis se for possível)\n"
    "Se faltar info, diga 'Definir responsável'."
)

DECISIONS_SYSTEM = (
    "Extraia APENAS as decisões realmente tomadas na reunião. "
    "Não invente, não coloque hipótese. "
    "Devolva como lista numerada."
)

ACTIONS_SYSTEM = (
    "Extraia os próximos passos de forma executável. "
    "Formato: 'Responsável — tarefa — prazo (se mencionado)'. "
    "Se não souber o responsável, use 'Time'."
)

# 🔥 aqui eu já tirei o [Nome do Cliente] e deixei pronto pra mandar
CLIENT_MSG_SYSTEM = (
    "Você vai escrever uma mensagem curta e educada para CLIENTE, explicando status. "
    "Comece com: 'Olá, tudo bem?' ou 'Olá, bom dia!' (sem nome). "
    "Sempre: 1) agradecer, 2) dizer onde estamos, 3) se houve atraso, justificar sem culpar, "
    "4) abrir para dúvidas. Tom profissional. Sem emoji."
)

DELAY_SYSTEM = (
    "Explique o atraso de forma madura: ajustes de escopo, dependências técnicas, "
    "aprovações internas ou bloqueio de navegador. Termine dizendo quando volta."
)

CONFLICT_SYSTEM = (
    "Houve discordância na reunião. Mediação em 3 a 5 frases: "
    "1) reconhecer os dois lados, 2) definir critério (prazo, impacto ou cliente), "
    "3) propor próximo passo objetivo."
)

STANDUP_SYSTEM = (
    "Formate em daily/standup: 1) o que foi feito, 2) o que está sendo feito, 3) impedimentos. "
    "Se faltar info, peça."
)

TASKIFY_SYSTEM = (
    "Transforme a conversa em tarefas. "
    "Formato: '- [ ] tarefa (responsável, prazo opcional)'."
)

SALES_SYSTEM = (
    "O assunto é comercial / demo / proposta. "
    "Explique o valor, o que já foi feito e o que falta. "
    "Se pedirem preço e não houver, diga que depende do escopo. Tom firme."
)

SUPPORT_SYSTEM = (
    "Cliente reclamou ou está com erro. "
    "1) reconheça, 2) diga que está sendo tratado, 3) peça dado que falta, 4) dê retorno."
)

SECURITY_SYSTEM = (
    "Assunto: segurança / LGPD / privacidade. "
    "Diga que dados podem ser anonimizados e que logs podem ser exportados para auditoria."
)

HIRING_SYSTEM = (
    "Assunto: contratação / entrevista. "
    "Diga o que falta para aprovar e qual é o próximo passo."
)

RETRO_SYSTEM = (
    "Assunto: retrospectiva. "
    "Estruture: 1) o que foi bom, 2) o que não foi bom, 3) o que vamos mudar."
)

SCOPE_CHANGE_SYSTEM = (
    "Explique mudança de escopo: o cliente pediu mais coisas do que o combinado e isso afeta prazo/custo. "
    "Sem jogar culpa. Mostre que é normal."
)

BUDGET_SYSTEM = (
    "Assunto: orçamento / desconto. "
    "Explique que valor depende de escopo. Se quiser baixar o preço, tem que reduzir escopo."
)

EMAIL_SYSTEM = (
    "Converta em e-mail formal: saudação, contexto, pontos, pedido, agradecimento, assinatura 'Equipe'."
)

WHATSAPP_SYSTEM = (
    "Converta em mensagem curta de WhatsApp: direta, educada, sem firula."
)

BRAINSTORM_SYSTEM = (
    "Liste 3 a 6 ideias práticas para o que o usuário pediu. "
    "Seja prático, não genérico."
)

OKR_SYSTEM = (
    "Monte 2 a 4 objetivos (O) e 2 a 3 resultados-chave (KR) para cada, baseado no que o usuário disse."
)

TRAINING_SYSTEM = (
    "Monte um mini roteiro de treinamento / onboarding em tópicos, para apresentar na reunião."
)

# ---------------------------------------------------------
# 2. Helpers
# ---------------------------------------------------------
def _chat(messages: List[Dict[str, Any]], model: Optional[str] = None) -> str:
    resp = client.chat.completions.create(
        model=model or MODEL_NAME,
        messages=messages,
    )
    return resp.choices[0].message.content

def _keep(text: str, max_len: int = 1100) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."

def _norm(s: str) -> str:
    return (s or "").lower().strip()

def _has(s: str, kws: List[str]) -> bool:
    s = _norm(s)
    return any(kw in s for kw in kws)

# ---------------------------------------------------------
# 3. Detectores de intenção
# ---------------------------------------------------------
def is_client_message(s: str) -> bool:
    return _has(s, [
        "mensagem pro cliente", "mensagem para o cliente",
        "fala pro cliente", "status pro cliente",
        "manda pro cliente", "responde o cliente"
    ])

def is_delay(s: str) -> bool:
    return _has(s, [
        "explica o atraso", "explicar o atraso",
        "por que demorou", "por que está demorando",
        "justifica a demora", "atrasou", "demorou"
    ])

def is_summary(s: str) -> bool:
    return _has(s, ["resumo", "resuma", "resumir a reunião", "ata"])

def is_decisions(s: str) -> bool:
    return _has(s, ["decisões", "decisoes", "o que foi decidido"])

def is_actions(s: str) -> bool:
    return _has(s, ["próximos passos", "proximos passos", "o que falta", "ações", "acoes"])

def is_conflict(s: str) -> bool:
    return _has(s, ["conflito", "discordou", "discordaram", "não concordou", "nao concordou"])

def is_standup(s: str) -> bool:
    return _has(s, ["standup", "daily", "atualização rápida", "atualizacao rapida"])

def is_taskify(s: str) -> bool:
    return _has(s, ["transforma em tarefa", "gera tasks", "to do list", "lista de tarefas"])

def is_sales(s: str) -> bool:
    return _has(s, ["proposta", "orçamento pro cliente", "demo", "apresentação", "venda"])

def is_support(s: str) -> bool:
    return _has(s, ["cliente reclamou", "cliente bravo", "ticket", "suporte", "erro no cliente"])

def is_security(s: str) -> bool:
    return _has(s, ["lgpd", "segurança", "privacidade", "dados sensíveis", "pode gravar"])

def is_hiring(s: str) -> bool:
    return _has(s, ["vaga", "entrevista", "candidato", "contratar", "recrutamento"])

def is_retro(s: str) -> bool:
    return _has(s, ["retro", "retrospectiva", "post-mortem", "post mortem", "lições aprendidas"])

def is_scope_change(s: str) -> bool:
    return _has(s, ["mudança de escopo", "escopo mudou", "não estava no escopo", "nao estava no escopo"])

def is_budget(s: str) -> bool:
    return _has(s, ["orçamento", "desconto", "valor do projeto", "pricing"])

def is_email(s: str) -> bool:
    return _has(s, ["transforma em email", "transformar em email", "vira email"])

def is_whatsapp(s: str) -> bool:
    return _has(s, ["mensagem de whatsapp", "whatsapp", "manda no zap"])

def is_brainstorm(s: str) -> bool:
    return _has(s, ["ideias", "me dá ideias", "brainstorm", "opções", "alternativas"])

def is_okr(s: str) -> bool:
    return _has(s, ["okr", "metas do trimestre", "objetivos e resultados", "planejamento do time"])

def is_training(s: str) -> bool:
    return _has(s, ["treinamento", "onboard", "onboarding", "apresentar pro time"])

# ---------------------------------------------------------
# 4. Geradores especializados
# ---------------------------------------------------------
async def gen_client_message(context: str) -> str:
    msgs = [
        {"role": "system", "content": CLIENT_MSG_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_delay_message(context: str) -> str:
    msgs = [
        {"role": "system", "content": DELAY_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_summary(context: str) -> str:
    msgs = [
        {"role": "system", "content": SUMMARIZER_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs), 1400)

async def gen_decisions(context: str) -> str:
    msgs = [
        {"role": "system", "content": DECISIONS_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs), 1000)

async def gen_actions(context: str) -> str:
    msgs = [
        {"role": "system", "content": ACTIONS_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs), 1000)

async def gen_conflict_solution(context: str) -> str:
    msgs = [
        {"role": "system", "content": CONFLICT_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_standup(context: str) -> str:
    msgs = [
        {"role": "system", "content": STANDUP_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_tasks(context: str) -> str:
    msgs = [
        {"role": "system", "content": TASKIFY_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs), 1200)

async def gen_sales(context: str) -> str:
    msgs = [
        {"role": "system", "content": SALES_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_support(context: str) -> str:
    msgs = [
        {"role": "system", "content": SUPPORT_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_security(context: str) -> str:
    msgs = [
        {"role": "system", "content": SECURITY_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_hiring(context: str) -> str:
    msgs = [
        {"role": "system", "content": HIRING_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_retro(context: str) -> str:
    msgs = [
        {"role": "system", "content": RETRO_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_scope_change(context: str) -> str:
    msgs = [
        {"role": "system", "content": SCOPE_CHANGE_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_budget(context: str) -> str:
    msgs = [
        {"role": "system", "content": BUDGET_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_email(context: str) -> str:
    msgs = [
        {"role": "system", "content": EMAIL_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_whatsapp(context: str) -> str:
    msgs = [
        {"role": "system", "content": WHATSAPP_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_brainstorm(context: str) -> str:
    msgs = [
        {"role": "system", "content": BRAINSTORM_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_okr(context: str) -> str:
    msgs = [
        {"role": "system", "content": OKR_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

async def gen_training(context: str) -> str:
    msgs = [
        {"role": "system", "content": TRAINING_SYSTEM},
        {"role": "user", "content": context},
    ]
    return _keep(_chat(msgs))

# ---------------------------------------------------------
# 5. fallback: sócio na call
# ---------------------------------------------------------
async def answer_like_partner(text: str) -> str:
    msgs = [
        {"role": "system", "content": BASE_SYSTEM},
        {"role": "user", "content": text},
    ]
    return _keep(_chat(msgs))

# ---------------------------------------------------------
# 6. Função principal usada pelo app.py
# ---------------------------------------------------------
async def ask_orlem(user_message: str) -> str:
    msg = user_message or ""
    low = _norm(msg)

    if is_client_message(low):
        return await gen_client_message(msg)
    if is_delay(low):
        return await gen_delay_message(msg)
    if is_summary(low):
        return await gen_summary(msg)
    if is_decisions(low):
        return await gen_decisions(msg)
    if is_actions(low):
        return await gen_actions(msg)
    if is_conflict(low):
        return await gen_conflict_solution(msg)
    if is_standup(low):
        return await gen_standup(msg)
    if is_taskify(low):
        return await gen_tasks(msg)
    if is_sales(low):
        return await gen_sales(msg)
    if is_support(low):
        return await gen_support(msg)
    if is_security(low):
        return await gen_security(msg)
    if is_hiring(low):
        return await gen_hiring(msg)
    if is_retro(low):
        return await gen_retro(msg)
    if is_scope_change(low):
        return await gen_scope_change(msg)
    if is_budget(low):
        return await gen_budget(msg)
    if is_email(low):
        return await gen_email(msg)
    if is_whatsapp(low):
        return await gen_whatsapp(msg)
    if is_brainstorm(low):
        return await gen_brainstorm(msg)
    if is_okr(low):
        return await gen_okr(msg)
    if is_training(low):
        return await gen_training(msg)

    # se não bateu em nada, responde como sócio
    return await answer_like_partner(msg)

# ---------------------------------------------------------
# 7. Funções auxiliares que o app.py chama direto
# ---------------------------------------------------------
async def summarize_transcript(transcript: str) -> str:
    return await gen_summary(transcript)

async def extract_decisions(transcript: str) -> str:
    return await gen_decisions(transcript)

async def extract_actions(transcript: str) -> str:
    return await gen_actions(transcript)

# compat com app.py antigo
async def client_status_message(contexto: str) -> str:
    return await gen_client_message(contexto)
