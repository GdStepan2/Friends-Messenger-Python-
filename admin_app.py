import json
import os
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QFrame, QCheckBox, QSpacerItem, QSizePolicy
)

from ws_worker import WsWorker


CONFIG_FILE = "admin_client_config.json"


def load_or_create_config() -> dict:
    default_cfg = {
        "host": "127.0.0.1",
        "port": 8765,
        "admin_username": "admin",
        "admin_password": ""
    }

    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, ensure_ascii=False, indent=2)
        return default_cfg

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # merge defaults
        for k, v in default_cfg.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        # если файл битый — перезапишем дефолтом
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, ensure_ascii=False, indent=2)
        return default_cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class AdminPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Messenger — Admin Panel")
        self.setFixedSize(640, 520)

        self.cfg = load_or_create_config()
        self.worker: Optional[WsWorker] = None
        self.is_authed_admin = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        # Header
        title = QLabel("Admin Panel")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        subtitle = QLabel("Create accounts for your friends")
        subtitle.setStyleSheet("color:#6b7280;")

        self.status = QLabel("Status: not connected")
        self.status.setStyleSheet("color:#6b7280;")

        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(self.status)
        root.addSpacing(6)

        # Connection card
        conn_card = QFrame()
        conn_card.setObjectName("card")
        conn_l = QVBoxLayout(conn_card)
        conn_l.setContentsMargins(14, 14, 14, 14)
        conn_l.setSpacing(10)

        conn_title = QLabel("Connection settings (stored locally)")
        conn_title.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))

        self.host = QLineEdit(str(self.cfg.get("host", "127.0.0.1")))
        self.host.setPlaceholderText("Server host (127.0.0.1 or 192.168.x.x)")

        self.port = QLineEdit(str(self.cfg.get("port", 8765)))
        self.port.setPlaceholderText("Port")

        self.admin_user = QLineEdit(str(self.cfg.get("admin_username", "admin")))
        self.admin_user.setPlaceholderText("Admin username")

        self.admin_pass = QLineEdit(str(self.cfg.get("admin_password", "")))
        self.admin_pass.setPlaceholderText("Admin password")
        self.admin_pass.setEchoMode(QLineEdit.EchoMode.Password)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Host:"), 0)
        row1.addWidget(self.host, 3)
        row1.addWidget(QLabel("Port:"), 0)
        row1.addWidget(self.port, 1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Admin login:"), 0)
        row2.addWidget(self.admin_user, 2)
        row2.addWidget(QLabel("Password:"), 0)
        row2.addWidget(self.admin_pass, 2)

        btn_row = QHBoxLayout()
        self.btn_save_connect = QPushButton("Save & Connect")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        btn_row.addWidget(self.btn_save_connect)
        btn_row.addWidget(self.btn_disconnect)
        btn_row.addStretch(1)

        conn_l.addWidget(conn_title)
        conn_l.addLayout(row1)
        conn_l.addLayout(row2)
        conn_l.addLayout(btn_row)

        root.addWidget(conn_card)

        # Account creation card
        acc_card = QFrame()
        acc_card.setObjectName("card")
        acc_l = QVBoxLayout(acc_card)
        acc_l.setContentsMargins(14, 14, 14, 14)
        acc_l.setSpacing(10)

        acc_title = QLabel("Create account")
        acc_title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))

        self.new_username = QLineEdit()
        self.new_username.setPlaceholderText("New username (3..32, no spaces)")

        self.new_password = QLineEdit()
        self.new_password.setPlaceholderText("New password (min 4 chars)")
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)

        self.new_is_admin = QCheckBox("Admin privileges for this account")

        self.btn_create = QPushButton("Create account")
        self.btn_create.setMinimumHeight(42)
        self.btn_create.setEnabled(False)  # включим только после admin-login

        acc_l.addWidget(acc_title)
        acc_l.addWidget(QLabel("Username"))
        acc_l.addWidget(self.new_username)
        acc_l.addWidget(QLabel("Password"))
        acc_l.addWidget(self.new_password)
        acc_l.addWidget(self.new_is_admin)
        acc_l.addSpacing(6)
        acc_l.addWidget(self.btn_create)

        root.addWidget(acc_card)

        root.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Styling
        self.setStyleSheet("""
            QWidget { background: #ffffff; }
            QLabel { color:#111827; font-size: 11pt; }
            QFrame#card {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 16px;
            }
            QLineEdit {
                border: 1px solid #d1d5db;
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 12pt;
                min-height: 40px;
            }
            QLineEdit:focus { border: 1px solid #3b82f6; }
            QCheckBox { font-size: 11pt; }
            QPushButton {
                background: #2563eb;
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 12pt;
            }
            QPushButton:hover { background: #1d4ed8; }
            QPushButton:disabled { background: #93c5fd; }
        """)

        # Wire events
        self.btn_save_connect.clicked.connect(self.save_and_connect)
        self.btn_disconnect.clicked.connect(self.disconnect)
        self.btn_create.clicked.connect(self.create_user)

        # Auto-connect on start (если в конфиге уже есть пароль)
        if (self.cfg.get("admin_password") or "").strip():
            self._connect_with_cfg(self.cfg)
        else:
            self.status.setText("Status: set admin password, then click 'Save & Connect'.")

    def set_status(self, text: str, error: bool = False):
        self.status.setText(text)
        self.status.setStyleSheet("color:#b91c1c;" if error else "color:#6b7280;")

    def disconnect(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.is_authed_admin = False
        self.btn_create.setEnabled(False)
        self.btn_disconnect.setEnabled(False)
        self.btn_save_connect.setEnabled(True)
        self.set_status("Status: disconnected")

    def save_and_connect(self):
        # persist config
        try:
            port = int((self.port.text() or "").strip())
        except ValueError:
            QMessageBox.warning(self, "Validation", "Port must be a number.")
            return

        cfg = {
            "host": (self.host.text() or "").strip() or "127.0.0.1",
            "port": port,
            "admin_username": (self.admin_user.text() or "").strip() or "admin",
            "admin_password": self.admin_pass.text() or "",
        }

        save_config(cfg)
        self.cfg = cfg

        if not cfg["admin_password"].strip():
            self.set_status("Status: admin password is empty. Please set it and connect.", error=True)
            return

        self._connect_with_cfg(cfg)

    def _connect_with_cfg(self, cfg: dict):
        # disconnect existing worker
        if self.worker:
            self.worker.stop()
            self.worker = None

        self.btn_save_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self.btn_create.setEnabled(False)
        self.is_authed_admin = False

        self.set_status(f"Status: connecting to {cfg['host']}:{cfg['port']} ...")

        self.worker = WsWorker(cfg["host"], int(cfg["port"]), cfg["admin_username"], cfg["admin_password"])
        self.worker.login_ok.connect(self.on_login_ok)
        self.worker.login_error.connect(self.on_login_error)
        self.worker.admin_create_user_ok.connect(self.on_create_ok)
        self.worker.admin_create_user_error.connect(self.on_create_err)
        self.worker.error.connect(lambda m: self.set_status(f"Status: error: {m}", error=True))
        self.worker.disconnected.connect(lambda r: self.set_status(f"Status: disconnected: {r}", error=True))
        self.worker.start()

    def on_login_ok(self, is_admin: bool, room: str):
        if not is_admin:
            self.is_authed_admin = False
            self.btn_create.setEnabled(False)
            self.btn_save_connect.setEnabled(True)
            self.set_status("Status: connected, but this account is NOT admin.", error=True)
            QMessageBox.warning(self, "Access denied", "This account is not admin. Use an admin account.")
            return

        self.is_authed_admin = True
        self.btn_create.setEnabled(True)
        self.set_status("Status: authenticated as admin. Ready.")

    def on_login_error(self, msg: str):
        self.is_authed_admin = False
        self.btn_create.setEnabled(False)
        self.btn_save_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.set_status(f"Status: connection/login failed: {msg}", error=True)

    def create_user(self):
        if not self.worker or not self.is_authed_admin:
            QMessageBox.warning(self, "Not ready", "Not authenticated as admin.")
            return

        u = (self.new_username.text() or "").strip()
        p = self.new_password.text() or ""
        is_admin = self.new_is_admin.isChecked()

        if not u or not p:
            QMessageBox.warning(self, "Validation", "Username and password are required.")
            return

        self.btn_create.setEnabled(False)
        self.worker.submit({"type": "admin_create_user", "username": u, "password": p, "is_admin": is_admin})

    def on_create_ok(self, username: str):
        self.btn_create.setEnabled(True)
        QMessageBox.information(self, "OK", f"User '{username}' created.")
        self.new_username.clear()
        self.new_password.clear()
        self.new_is_admin.setChecked(False)

    def on_create_err(self, msg: str):
        self.btn_create.setEnabled(True)
        QMessageBox.warning(self, "Error", msg)


def main():
    app = QApplication(sys.argv)
    w = AdminPanel()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
