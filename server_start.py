import os
import json
import asyncio
from getpass import getpass

from db import get_engine, ensure_schema, get_user_by_username, create_user
from server import run_server


CONFIG_FILE = "server_config.json"


def load_or_create_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    cfg = {
        "host": "0.0.0.0",
        "port": 8765,
        "database_url": "sqlite:///messenger.db",
        "init_admin_username": "admin"
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def ensure_admin_if_needed(cfg: dict) -> None:
    os.environ["DATABASE_URL"] = cfg.get("database_url", "sqlite:///messenger.db")

    engine = get_engine()
    ensure_schema(engine)

    admin_username = (cfg.get("init_admin_username") or "").strip()
    if not admin_username:
        return

    existing = get_user_by_username(engine, admin_username)
    if existing:
        return

    print(f"First run: creating admin '{admin_username}'")
    pwd = getpass(f"Set password for '{admin_username}': ")
    if not pwd:
        raise SystemExit("Empty password.")

    create_user(engine, admin_username, pwd, is_admin=True, is_active=True)
    print("Admin created.")


def main():
    cfg = load_or_create_config()
    os.environ["DATABASE_URL"] = cfg.get("database_url", "sqlite:///messenger.db")

    ensure_admin_if_needed(cfg)

    host = cfg.get("host", "0.0.0.0")
    port = int(cfg.get("port", 8765))

    asyncio.run(run_server(host, port))


if __name__ == "__main__":
    main()
