# brain.py
"""
ORLEM — cérebro (fase 1.6) com:
- Modo conversa (sócio na call) SEM ata/lista
- Estilos: interno / cliente / neutro (auto por heurística)
- Comandos de tom: "modo interno", "modo cliente", "tom neutro", "resetar tom"
- Ferramentas: resumo/decisões/próximos passos/etc
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

# Tom global simples (processo). Mantém manual até resetar.
_MEETING_TONE = "auto"  # "auto" | "interno" | "cliente" | "neutro"


# ---------------------------------------------------------
# 1. Prompts base
# ---------------------------------------------------------

# Personalidade: sócio humano na call (fala natural)
BASE_SYSTEM = (
    "Você é o ORLEM, um assistente de reuniões que age como um sócio humano, experiente, "
    "dentro da call AO VIVO. Responda em português do Brasil.\n"
    "\n"
    "MODO CONVERSA (padrão):\n"
    "- Responda em 2 a 4 frases, como se estivesse falando na reunião.\n"
    "- NUNCA use listas, bullets ou numeração (nada de 1), 2), 3) etc.).\n"
    "- NUNCA use 'Contexto rápido', 'Pontos principais', 'Decisões' ou 'Próximos passos'.\n"
    "- Não monte resumo/ata nesse modo.\n"
    "- Fale de forma natural, direta e profissional, como um sócio opinando.\n"
    "- Só use 'pelo que você disse' se o usuário realmente tiver explicado algo antes.\n"
    "- Não repita a pergunta do usuário nem resuma o que ele acabou de falar.\n"
    "- Pode fazer 1 pergunta curta se ajudar a avançar.\n"
)

# Estilos por tom
STYLE_NEUTRO = (
    "TOM: neutro profissional, direto, sem gírias, sem formalidade excessiva. "
    "Foque em clareza e praticidade."
)
STYLE_CLIENTE = (
    "TOM: reunião com cliente. Seja cordial, claro e seguro. Evite gírias, suavize o tom, "
    "mostre segurança sem soar ríspido. Não prometa o que não foi pedido."
)
STYLE_INTERNO = (
    "TOM: reunião interna entre sócios/time. Pode ser mais direto e pragmático, "
    "sem rodeios. Pode usar expressões leves como 'testaria', 'vamos validar rápido', "
    "mas evite palavrões."
)

# Modos especiais (quando pedirem explicitamente)
SUMMARIZER_SYSTEM = (
    "Você é o Orlem e vai resumir uma reunião.\n"
    "Responda SEMPRE neste formato exato:\n\n"
    "Resumo rápido:\n"
    "- ponto 1\n"
    "- ponto 2\n"
    "- ponto 3\n\n"
    "Decisões:\n"
    "- decisão 1 (ou 'Nenhuma decisão registrada.')\n\n"
    "Próximos passos:\n"
    "- Ação — Responsável — Prazo\n"
    "Se faltar responsável ou prazo, preencha de forma razoável e marque com '(inferido)'. "
    "Não faça perguntas e não peça mais contexto."
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

CLIENT_MSG_SYSTEM = (
    "Você vai escrever uma mensagem curta e educada para CLIENTE, explicando status. "
    "Comece com 'Olá, tudo bem?' ou 'Olá, bom dia!'. "
    "Sempre: 1) agradecer, 2) dizer onde estamos, 3) se houve atraso, justificar sem culpar, "
    "4) abrir para dúvidas. Tom profissional. Sem emoji."
)

DELAY_SYSTEM = (
    "Explique o atraso de forma madura: ajustes de escopo, dependências técnicas, "
    "aprovações internas ou bloqueio externo. Termine dizendo quando volta."
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
    "Assunto comercial / demo / proposta. Explique o valor, o que já foi feito, e o que falta. "
    "Se pedirem preço e não houver, diga que depende do escopo."
)

SUPPORT_SYSTEM = (
    "Cliente reclamou ou está com erro. 1) reconheça, 2) diga que está sendo tratado, "
    "3) peça dado que falta, 4) dê retorno."
)

SECURITY_SYSTEM = (
    "Assunto: segurança / LGPD / privacidade. "
    "Diga que dados podem ser anonimizados e que logs podem ser exportados para auditoria."
)

HIRING_SYSTEM = "Assunto: contratação / entrevista. Diga o que falta e qual é o próximo passo."
RETRO_SYSTEM = "Assunto: retrospectiva. Estruture: 1) o que foi bom, 2) o que não foi, 3) o que vamos mudar."
SCOPE_CHANGE_SYSTEM = (
    "Explique mudança de escopo: pediram além do combinado e isso afeta prazo/custo. Sem culpar."
)
BUDGET_SYSTEM = (
    "Assunto: orçamento / desconto. Explique que valor depende de escopo. "
    "Se reduzir preço, precisa reduzir escopo."
)
EMAIL_SYSTEM = (
    "Converta em e-mail formal: saudação, contexto, pontos, pedido, agradecimento, assinatura 'Equipe'."
)
WHATSAPP_SYSTEM = "Mensagem curta de WhatsApp: direta, educada, sem firula."
BRAINSTORM_SYSTEM = "Liste 3 a 6 ideias práticas para o pedido. Seja específico, não genérico."
OKR_SYSTEM = "Monte 2 a 4 objetivos (O) e 2 a 3 KRs por objetivo, com base no que foi dito."
TRAINING_SYSTEM = "Roteiro de treinamento curto, em tópicos, para apresentar na reunião."


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
    return _has(s, ["mensagem pro cliente", "mensagem para o cliente", "status pro cliente", "responde o cliente"])

def is_delay(s: str) -> bool:
    return _has(s, ["explica o atraso", "explicar o atraso", "por que demorou", "justifica a demora", "atrasou"])

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
    return _has(s, ["ideias", "me dá ideias", "me da ideias", "brainstorm", "opções", "opcoes", "alternativas"])

def is_okr(s: str) -> bool:
    return _has(s, ["okr", "metas do trimestre", "objetivos e resultados", "planejamento do time"])

def is_training(s: str) -> bool:
    return _has(s, ["treinamento", "onboard", "onboarding", "apresentar pro time"])

def is_greeting(s: str) -> bool:
    return _has(s, ["bom dia", "boa tarde", "boa noite", "olá", "ola", "oi", "e aí", "e ai", "fala orlem"])


# ---------------------------------------------------------
# 3.1 Pedido vago
# ---------------------------------------------------------
VAGUE_TRIGGERS = [
    "ideia", "ideias", "brainstorm",
    "post", "título", "titulo", "legenda", "copy", "hook",
    "sugestões", "sugestao", "sugestão", "ajuda com",
    "o que fazer", "me ajuda", "planejar", "plano",
    "campanha", "conteúdo", "conteudo"
]

def needs_clarification(s: str) -> bool:
    s = _norm(s)
    if len(s) < 12:
        return True
    if any(k in s for k in VAGUE_TRIGGERS):
        rich = ["objetivo", "público", "publico", "formato", "canal", "restrição", "restricoes",
                "prazo", "deadline", "kpi", "critério de sucesso", "criterio de sucesso"]
        if not any(k in s for k in rich):
            return True
    return False

CLARIFY_MESSAGE = (
    "Pra eu acertar de primeira: qual o objetivo principal, quem é o público-alvo, em qual canal/formato, "
    "alguma restrição de tom/tamanho/política e qual o prazo/critério de sucesso? Com isso eu direciono melhor."
)


# ---------------------------------------------------------
# 3.2 Tom (interno/cliente/neutro) — heurística + comandos
# ---------------------------------------------------------
def _detect_tone_auto(s: str) -> str:
    s = _norm(s)
    if any(k in s for k in ["cliente", "proposta", "contrato", "apresentar ao cliente", "call com o cliente"]):
        return "cliente"
    if any(k in s for k in ["interno", "alinhamento do time", "sprint", "retro", "roadmap", "deploy", "estimativa"]):
        return "interno"
    return "neutro"

def _tone_style(tone: str) -> str:
    if tone == "cliente":
        return STYLE_CLIENTE
    if tone == "interno":
        return STYLE_INTERNO
    return STYLE_NEUTRO

def _maybe_handle_tone_command(raw: str) -> Optional[str]:
    global _MEETING_TONE
    s = _norm(raw)
    if "modo interno" in s:
        _MEETING_TONE = "interno"
        return "Fechado, falo no tom interno daqui pra frente."
    if "modo cliente" in s:
        _MEETING_TONE = "cliente"
        return "Perfeito, sigo no tom para cliente."
    if "tom neutro" in s:
        _MEETING_TONE = "neutro"
        return "Certo, ajustei para tom neutro."
    if "resetar tom" in s or "modo auto" in s or "tom automático" in s:
        _MEETING_TONE = "auto"
        return "Resetado: volto a detectar o tom automaticamente."
    return None


# ---------------------------------------------------------
# 4. Geradores (modos especiais)
# ---------------------------------------------------------
async def gen_client_message(context: str) -> str:
    msgs = [{"role": "system", "content": CLIENT_MSG_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_delay_message(context: str) -> str:
    msgs = [{"role": "system", "content": DELAY_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_summary(context: str) -> str:
    msgs = [{"role": "system", "content": SUMMARIZER_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs), 1400)

async def gen_decisions(context: str) -> str:
    msgs = [{"role": "system", "content": DECISIONS_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs), 1000)

async def gen_actions(context: str) -> str:
    msgs = [{"role": "system", "content": ACTIONS_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs), 1000)

async def gen_conflict_solution(context: str) -> str:
    msgs = [{"role": "system", "content": CONFLICT_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_standup(context: str) -> str:
    msgs = [{"role": "system", "content": STANDUP_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_tasks(context: str) -> str:
    msgs = [{"role": "system", "content": TASKIFY_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs), 1200)

async def gen_sales(context: str) -> str:
    msgs = [{"role": "system", "content": SALES_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_support(context: str) -> str:
    msgs = [{"role": "system", "content": SUPPORT_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_security(context: str) -> str:
    msgs = [{"role": "system", "content": SECURITY_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_hiring(context: str) -> str:
    msgs = [{"role": "system", "content": HIRING_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_retro(context: str) -> str:
    msgs = [{"role": "system", "content": RETRO_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_scope_change(context: str) -> str:
    msgs = [{"role": "system", "content": SCOPE_CHANGE_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_budget(context: str) -> str:
    msgs = [{"role": "system", "content": BUDGET_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_email(context: str) -> str:
    msgs = [{"role": "system", "content": EMAIL_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_whatsapp(context: str) -> str:
    msgs = [{"role": "system", "content": WHATSAPP_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_brainstorm(context: str) -> str:
    msgs = [{"role": "system", "content": BRAINSTORM_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_okr(context: str) -> str:
    msgs = [{"role": "system", "content": OKR_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))

async def gen_training(context: str) -> str:
    msgs = [{"role": "system", "content": TRAINING_SYSTEM},
            {"role": "user", "content": context}]
    return _keep(_chat(msgs))


# ---------------------------------------------------------
# 5. Modo conversa (sócio na call)
# ---------------------------------------------------------
def _compose_system_with_tone(tone: str) -> str:
    return BASE_SYSTEM + "\n" + _tone_style(tone)

async def answer_like_partner(text: str, tone: str) -> str:
    user_prompt = (
        "Responda como se estivesse falando AO VIVO na reunião, "
        "em 2 a 4 frases, SEM usar listas, bullets ou numeração. "
        "NÃO use 'Contexto rápido', 'Pontos principais', "
        "'Decisões' nem 'Próximos passos'.\n\n"
        f"Mensagem da pessoa:\n{text}"
    )
    msgs = [
        {"role": "system", "content": _compose_system_with_tone(tone)},
        {"role": "user", "content": user_prompt},
    ]
    resposta = _keep(_chat(msgs))

    low = resposta.lower()
    tem_ata = (
        "contexto rápido" in low or "contexto rapido" in low or
        "pontos principais" in low or
        "decisões" in low or "decisoes" in low or
        "próximos passos" in low or "proximos passos" in low or
        resposta.strip().startswith(("1)", "1.", "- "))
    )
    if tem_ata:
        msgs2 = [
            {"role": "system", "content": _compose_system_with_tone(tone)},
            {"role": "user",
             "content": (
                 "A resposta abaixo veio em formato de ata/lista, o que é PROIBIDO no modo conversa. "
                 "Reescreva a MESMA ideia em 2 a 4 frases corridas, como fala natural na reunião, "
                 "sem tópicos e sem palavras como 'Contexto rápido', 'Pontos principais', "
                 "'Decisões' ou 'Próximos passos'.\n\n"
                 f"RESPOSTA ORIGINAL:\n{resposta}"
             )},
        ]
        resposta = _keep(_chat(msgs2))
    return resposta


# ---------------------------------------------------------
# 6. Função principal usada pelo app.py
# ---------------------------------------------------------
async def ask_orlem(user_message: str) -> Optional[str]:
    global _MEETING_TONE
    msg = user_message or ""
    low = _norm(msg)

    tone_ack = _maybe_handle_tone_command(low)
    if tone_ack:
        return tone_ack

    is_called = "orlem" in low
    is_command = any([
        is_client_message(low), is_delay(low), is_summary(low), is_decisions(low),
        is_actions(low), is_conflict(low), is_standup(low), is_taskify(low),
        is_sales(low), is_support(low), is_security(low), is_hiring(low),
        is_retro(low), is_scope_change(low), is_budget(low),
        is_email(low), is_whatsapp(low), is_brainstorm(low),
        is_okr(low), is_training(low)
    ])
    if not (is_called or is_command):
        return None

    if is_called and is_greeting(low) and not is_command:
        return "Fala, tudo certo? Tô acompanhando aqui; pode tocar que eu entro quando precisar."

    if is_called and not is_command and needs_clarification(msg):
        return CLARIFY_MESSAGE

    if low.startswith("orlem"):
        msg = msg.split(" ", 1)[1] if " " in msg else ""

    if is_brainstorm(low) and needs_clarification(msg):
        return CLARIFY_MESSAGE

    if is_client_message(low):  return await gen_client_message(msg)
    if is_delay(low):           return await gen_delay_message(msg)
    if is_summary(low):         return await gen_summary(msg)
    if is_decisions(low):       return await gen_decisions(msg)
    if is_actions(low):         return await gen_actions(msg)
    if is_conflict(low):        return await gen_conflict_solution(msg)
    if is_standup(low):         return await gen_standup(msg)
    if is_taskify(low):         return await gen_tasks(msg)
    if is_sales(low):           return await gen_sales(msg)
    if is_support(low):         return await gen_support(msg)
    if is_security(low):        return await gen_security(msg)
    if is_hiring(low):          return await gen_hiring(msg)
    if is_retro(low):           return await gen_retro(msg)
    if is_scope_change(low):    return await gen_scope_change(msg)
    if is_budget(low):          return await gen_budget(msg)
    if is_email(low):           return await gen_email(msg)
    if is_whatsapp(low):        return await gen_whatsapp(msg)
    if is_brainstorm(low):      return await gen_brainstorm(msg)
    if is_okr(low):             return await gen_okr(msg)
    if is_training(low):        return await gen_training(msg)

    if _MEETING_TONE == "auto":
        tone = _detect_tone_auto(user_message)
    else:
        tone = _MEETING_TONE

    return await answer_like_partner(msg, tone)


# ---------------------------------------------------------
# 7. Funções auxiliares usadas pelo app.py
# ---------------------------------------------------------
async def summarize_transcript(transcript: str) -> str:
    """
    Gera um resumo no formato:
    Resumo rápido / Decisões / Próximos passos
    """
    if not transcript or not transcript.strip():
        return (
            "Resumo rápido:\n"
            "- Ainda não há conteúdo suficiente na reunião para gerar um resumo.\n\n"
            "Decisões:\n"
            "- Nenhuma decisão registrada.\n\n"
            "Próximos passos:\n"
            "- Definir próximos passos — Responsável (a definir) — Prazo 3 dias (inferido)."
        )

    text = await gen_summary(transcript)

    if "Resumo rápido:" not in text:
        text = "Resumo rápido:\n- " + text

    if "Decisões:" not in text:
        text += "\n\nDecisões:\n- Nenhuma decisão registrada."

    if "Próximos passos:" not in text:
        text += (
            "\n\nPróximos passos:\n"
            "- Definir próximos passos — Responsável (a definir) — Prazo 3 dias (inferido)."
        )

    return text


async def extract_decisions(transcript: str) -> str:
    return await gen_decisions(transcript)


async def extract_actions(transcript: str) -> str:
    return await gen_actions(transcript)


async def client_status_message(contexto: str) -> str:
    return await gen_client_message(contexto)


# ---------------------------------------------------------
# 8. Diarização (organizar por falante)
# ---------------------------------------------------------
async def diarize_transcript(transcript: str) -> str:
    """
    Agrupa a conversa por falante de forma legível.
    Nunca faz perguntas, só entrega um mapa de quem falou o quê.
    """
    if not transcript or not transcript.strip():
        return "Diarização indisponível: não há falas suficientes na reunião."

    prompt = f"""
Você vai receber o LOG cru de uma reunião, com fal falas de várias pessoas.
Algumas linhas podem ter prefixos como "User:", "Orlem:", nomes de pessoas, etc.

Sua missão é ORGANIZAR esse material por falante de forma simples e útil,
como se fosse um mapa rápido da reunião.

REGRAS OBRIGATÓRIAS:
- Se tiver nomes claros (ex.: "Felipe:", "Ana:"), use esses nomes nos títulos.
- Se não tiver nomes claros, use rótulos neutros: Falante A, Falante B, Falante C...
  na ordem em que aparecem.
- Agrupe as fal falas de cada pessoa em bullets curtos, sem repetir tudo palavra por palavra.
- NÃO faça perguntas, NÃO diga que precisa de mais contexto.
- NÃO invente conteúdo novo; apenas compacte o que estiver no log.
- Não use saudação; comece direto.

FORMATO EXATO DE SAÍDA (exemplo de estrutura):

Falante / Nome X:
- ponto 1
- ponto 2

Falante / Nome Y:
- ponto 1
- ponto 2

LOG DA REUNIÃO (cru):
\"\"\"{transcript}\"\"\""""

    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            temperature=0.2,
            max_tokens=700,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você organiza transcrições de reunião por falante, de forma clara, "
                        "sem pedir contexto extra e sem inventar conteúdo."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()

        if "Falante" not in text and ":" not in text:
            text = "Falante A:\n- " + text

        return text

    except Exception as e:
        user_lines, orlem_lines = [], []
        for ln in transcript.splitlines():
            low = ln.lower()
            if low.startswith("user:"):
                user_lines.append(ln.split(":", 1)[1].strip())
            elif low.startswith("orlem:"):
                orlem_lines.append(ln.split(":", 1)[1].strip())

        out = "Falante / Nome A (usuário):\n" + "\n".join(
            f"- {x[:140]}" for x in (user_lines[:6] or ["(sem fal falas)"])
        )
        out += "\n\nFalante / Nome B (Orlem):\n" + "\n".join(
            f"- {x[:140]}" for x in (orlem_lines[:6] or ["(sem fal falas)"])
        )
        out += f"\n\n(observação: diarização simplificada por erro técnico: {type(e).__name__})"
        return out
