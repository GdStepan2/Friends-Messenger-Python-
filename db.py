import os
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, Boolean,
    DateTime, ForeignKey, Text, select, insert, func, join
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///messenger.db")


def get_engine() -> Engine:
    url = get_database_url()
    connect_args = {}
    if url.startswith("sqlite:///"):
        connect_args = {"check_same_thread": False}
    return create_engine(url, future=True, connect_args=connect_args)


metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(64), unique=True, nullable=False, index=True),
    Column("password_hash", String(255), nullable=False),
    Column("is_admin", Boolean, nullable=False, server_default="0"),
    Column("is_active", Boolean, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# room оставляем ради совместимости, но в приложении комнаты “выключены” (всегда general)
messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("room", String(64), nullable=False, server_default="general", index=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),

    # NEW:
    Column("kind", String(16), nullable=False, server_default="text"),   # text | sticker
    Column("sticker", String(64), nullable=True),                       # emoji/name
    Column("reply_to", Integer, nullable=True, index=True),             # message id

    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now(), index=True),
)


PBKDF2_ITERS_DEFAULT = 200_000


def hash_password(password: str, iters: int = PBKDF2_ITERS_DEFAULT) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be non-empty string")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    hash_b64 = base64.urlsafe_b64encode(dk).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iters}${salt_b64}${hash_b64}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_str, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_str)

        def pad(s: str) -> str:
            return s + "=" * (-len(s) % 4)

        salt = base64.urlsafe_b64decode(pad(salt_b64).encode("ascii"))
        expected = base64.urlsafe_b64decode(pad(hash_b64).encode("ascii"))
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _sqlite_add_column_if_missing(engine: Engine, table: str, column: str, ddl: str) -> None:
    # DDL пример: "ALTER TABLE messages ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'text'"
    url = str(engine.url)
    if not url.startswith("sqlite:///"):
        return

    with engine.connect() as conn:
        cols = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        existing = {c[1] for c in cols}  # name at index 1
        if column in existing:
            return
    with engine.begin() as conn:
        conn.exec_driver_sql(ddl)


def ensure_schema(engine: Engine) -> None:
    metadata.create_all(engine)

    # Миграции для уже существующей SQLite базы (если вы запускали старую версию)
    _sqlite_add_column_if_missing(
        engine, "messages", "kind",
        "ALTER TABLE messages ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'text'"
    )
    _sqlite_add_column_if_missing(
        engine, "messages", "sticker",
        "ALTER TABLE messages ADD COLUMN sticker VARCHAR(64)"
    )
    _sqlite_add_column_if_missing(
        engine, "messages", "reply_to",
        "ALTER TABLE messages ADD COLUMN reply_to INTEGER"
    )


def get_user_by_username(engine: Engine, username: str) -> Optional[Dict[str, Any]]:
    stmt = select(users).where(users.c.username == username)
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None


def create_user(engine: Engine, username: str, password: str, is_admin: bool = False, is_active: bool = True) -> int:
    u = (username or "").strip()
    if not (3 <= len(u) <= 32) or any(ch.isspace() for ch in u):
        raise ValueError("Username must be 3..32 chars, no spaces")
    if len(password or "") < 4:
        raise ValueError("Password must be at least 4 chars")

    stmt = insert(users).values(
        username=u,
        password_hash=hash_password(password),
        is_admin=bool(is_admin),
        is_active=bool(is_active),
        created_at=datetime.now(timezone.utc),
    )
    with engine.begin() as conn:
        try:
            res = conn.execute(stmt)
            pk = res.inserted_primary_key[0] if res.inserted_primary_key else None
            return int(pk) if pk is not None else 0
        except IntegrityError as e:
            raise ValueError("Username already exists") from e


def authenticate(engine: Engine, username: str, password: str) -> Optional[Dict[str, Any]]:
    username = (username or "").strip()
    u = get_user_by_username(engine, username)
    if not u:
        return None
    if not bool(u.get("is_active", True)):
        return None
    if not verify_password(password or "", u["password_hash"]):
        return None
    return u


def insert_message(
    engine: Engine,
    user_id: int,
    content: str,
    kind: str = "text",
    sticker: Optional[str] = None,
    reply_to: Optional[int] = None,
) -> Dict[str, Any]:
    # комнаты выключены: всегда general
    room = "general"

    kind = (kind or "text").strip().lower()
    if kind not in ("text", "sticker"):
        kind = "text"

    content = (content or "").strip()
    if kind == "text" and not content:
        raise ValueError("Empty message")
    if len(content) > 2000:
        raise ValueError("Message is too long (max 2000 chars)")

    if kind == "sticker":
        sticker = (sticker or "").strip()
        if not sticker:
            raise ValueError("Sticker is empty")

    now = datetime.now(timezone.utc)

    stmt = insert(messages).values(
        room=room,
        user_id=int(user_id),
        kind=kind,
        sticker=sticker,
        reply_to=int(reply_to) if reply_to is not None else None,
        content=content if kind == "text" else "",  # для sticker content пустой
        created_at=now,
    )
    with engine.begin() as conn:
        res = conn.execute(stmt)
        msg_id = res.inserted_primary_key[0] if res.inserted_primary_key else None

    return {
        "id": int(msg_id) if msg_id is not None else 0,
        "user_id": int(user_id),
        "kind": kind,
        "sticker": sticker,
        "reply_to": int(reply_to) if reply_to is not None else None,
        "content": content if kind == "text" else "",
        "created_at": now.isoformat(),
    }


def fetch_history(engine: Engine, limit: int = 80) -> List[Dict[str, Any]]:
    limit = max(1, min(200, int(limit)))
    j = join(messages, users, users.c.id == messages.c.user_id)

    stmt = (
        select(
            messages.c.id,
            messages.c.user_id,
            users.c.username.label("username"),
            messages.c.kind,
            messages.c.sticker,
            messages.c.reply_to,
            messages.c.content,
            messages.c.created_at,
        )
        .select_from(j)
        .where(messages.c.room == "general")
        .order_by(messages.c.id.desc())
        .limit(limit)
    )

    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    rows = list(reversed(rows))

    out = []
    for r in rows:
        out.append({
            "id": int(r["id"]),
            "user_id": int(r["user_id"]),
            "username": r["username"],
            "kind": r.get("kind", "text") or "text",
            "sticker": r.get("sticker"),
            "reply_to": int(r["reply_to"]) if r.get("reply_to") is not None else None,
            "content": r.get("content", "") or "",
            "created_at": (r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"])),
        })
    return out
