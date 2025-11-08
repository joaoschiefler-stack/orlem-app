# db.py
from __future__ import annotations
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from models import Base, User, Workspace, Member, Meeting, Message

DB_URL = "sqlite:///orlem.db"

engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)


def _get_or_create_default_workspace(session, user_id: int) -> Workspace:
    ws = session.execute(
        select(Workspace).join(Member, Member.workspace_id == Workspace.id).where(Member.user_id == user_id)
    ).scalar_one_or_none()
    if ws:
        return ws
    # cria workspace + membership
    ws = Workspace(name="Default Workspace")
    session.add(ws)
    session.flush()
    m = Member(user_id=user_id, workspace_id=ws.id, role="owner")
    session.add(m)
    return ws


def get_or_create_default_user() -> int:
    with SessionLocal() as session:
        user = session.execute(select(User).order_by(User.id)).scalar_one_or_none()
        if not user:
            user = User(name="Default User", email=None)
            session.add(user)
            session.flush()
        _get_or_create_default_workspace(session, user.id)
        session.commit()
        return user.id


def create_meeting(user_id: int, title: str, source: str = "local") -> int:
    with SessionLocal() as session:
        ws = _get_or_create_default_workspace(session, user_id)
        meeting = Meeting(workspace_id=ws.id, title=title, source=source, status="open")
        session.add(meeting)
        session.flush()
        session.commit()
        return meeting.id


def list_meetings(user_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        ws = _get_or_create_default_workspace(session, user_id)
        rows = (
            session.execute(
                select(Meeting)
                .where(Meeting.workspace_id == ws.id)
                .order_by(Meeting.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "source": r.source,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]


def add_message(meeting_id: int, role: str, content: str, meta: Optional[Dict[str, Any]] = None) -> int:
    with SessionLocal() as session:
        msg = Message(
            meeting_id=meeting_id,
            role=role,
            content=content,
            meta_json=(json.dumps(meta, ensure_ascii=False) if meta else None),
        )
        session.add(msg)
        session.flush()
        session.commit()
        return msg.id


def get_meeting_messages(meeting_id: int) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        msgs = (
            session.execute(
                select(Message).where(Message.meeting_id == meeting_id).order_by(Message.created_at.asc())
            )
            .scalars()
            .all()
        )
        out: List[Dict[str, Any]] = []
        for m in msgs:
            out.append(
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "meta_json": m.meta_json,
                    "created_at": m.created_at.isoformat(),
                }
            )
        return out
