# db.py
from typing import List, Dict, Optional
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session
from models import Base, User, Meeting, Message

# ================================
# CONFIGURAÇÃO DO BANCO
# ================================
DATABASE_URL = "sqlite:///orlem.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # necessário pro SQLite + threads
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Session:
    """Abre uma sessão de banco e garante fechamento depois."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ================================
# INICIALIZAÇÃO
# ================================
def init_db() -> None:
    """Cria as tabelas se ainda não existirem."""
    Base.metadata.create_all(bind=engine)


# ================================
# USUÁRIO PADRÃO
# ================================
def get_or_create_default_user() -> int:
    """
    Retorna o id de um usuário 'padrão'.
    Se não existir ainda, cria um.
    """
    db = SessionLocal()
    try:
        # pega o primeiro usuário que existir
        user = db.execute(select(User).order_by(User.id.asc())).scalars().first()
        if user:
            return user.id

        # se não tiver ninguém, cria um usuário default
        user = User(
            name="Usuário Orlem",
            email="orlem@local",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


# ================================
# REUNIÕES
# ================================
def create_meeting(
    user_id: int,
    title: str = "Reunião local",
    source: str = "local",
) -> int:
    """
    Cria uma reunião e retorna o id.

    OBS: o modelo Meeting tem workspace_id NOT NULL.
    Como estamos em modo single-workspace, usamos workspace_id=1 sempre.
    """
    db = SessionLocal()
    try:
        meeting = Meeting(
            workspace_id=1,   # 🔥 FIX: obrigatório para não quebrar NOT NULL
            title=title,
            source=source,
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        return meeting.id
    finally:
        db.close()


def list_meetings(user_id: int) -> List[Dict]:
    """
    Lista reuniões em ordem decrescente de criação.

    OBS: user_id é ignorado porque Meeting não tem essa coluna.
    """
    db = SessionLocal()
    try:
        meetings = (
            db.execute(
                select(Meeting).order_by(Meeting.created_at.desc())
            )
            .scalars()
            .all()
        )

        out: List[Dict] = []
        for m in meetings:
            out.append(
                {
                    "id": m.id,
                    "title": m.title,
                    "source": m.source,
                    "status": getattr(m, "status", None),
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
            )
        return out
    finally:
        db.close()


def get_last_meeting(user_id: int) -> Optional[Dict]:
    """
    Última reunião criada (se existir).

    OBS: user_id é ignorado porque Meeting não tem essa coluna.
    """
    db = SessionLocal()
    try:
        m = (
            db.execute(
                select(Meeting).order_by(Meeting.created_at.desc())
            )
            .scalars()
            .first()
        )
        if not m:
            return None

        return {
            "id": m.id,
            "title": m.title,
            "source": m.source,
            "status": getattr(m, "status", None),
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
    finally:
        db.close()


# ================================
# MENSAGENS
# ================================
def add_message(
    meeting_id: int,
    role: str,
    content: str,
    meta_json: Optional[str] = None,
) -> int:
    """Adiciona mensagem a uma reunião."""
    db = SessionLocal()
    try:
        msg = Message(
            meeting_id=meeting_id,
            role=role,
            content=content,
            meta_json=meta_json,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return msg.id
    finally:
        db.close()


def get_meeting_messages(meeting_id: int) -> List[Dict]:
    """Retorna todas as mensagens de uma reunião em ordem cronológica."""
    db = SessionLocal()
    try:
        msgs = (
            db.execute(
                select(Message)
                .where(Message.meeting_id == meeting_id)
                .order_by(Message.created_at.asc())
            )
            .scalars()
            .all()
        )

        out: List[Dict] = []
        for m in msgs:
            out.append(
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "meta_json": m.meta_json,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
            )
        return out
    finally:
        db.close()
