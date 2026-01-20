import sys
from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QAction
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QFrame, QSpacerItem, QSizePolicy, QDialog, QGridLayout, QCheckBox,
    QSystemTrayIcon, QMenu, QListWidget, QListWidgetItem
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect

from ws_worker import WsWorker


# Простые emoji-стикеры
STICKERS = ["😀", "😂", "😍", "😎", "😭", "👍", "🙏", "🔥", "❤️", "🎉", "😡", "🤝"]

RU_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]


def parse_iso_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        # сервер шлёт ISO8601; Python умеет с +00:00
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def fmt_time_hhmm(iso: str) -> str:
    dt = parse_iso_dt(iso)
    if not dt:
        return ""
    return dt.strftime("%H:%M")


def fmt_date_ru(iso: str) -> str:
    dt = parse_iso_dt(iso)
    if not dt:
        return ""
    day = dt.day
    month = RU_MONTHS[dt.month - 1]
    # как на скрине: "20 января"
    return f"{day} {month}"


def msg_preview(m: Dict[str, Any], limit: int = 60) -> str:
    kind = (m.get("kind") or "text").lower()
    if kind == "sticker":
        return f"стикер {m.get('sticker', '')}"
    t = (m.get("content") or "").replace("\n", " ").strip()
    return (t[:limit] + "…") if len(t) > limit else t


class StickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Стикеры")
        self.setFixedSize(360, 220)

        self.selected: Optional[str] = None
        layout = QGridLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        r = c = 0
        for s in STICKERS:
            b = QPushButton(s)
            b.setMinimumSize(60, 44)
            b.clicked.connect(lambda _, x=s: self._pick(x))
            layout.addWidget(b, r, c)
            c += 1
            if c >= 6:
                c = 0
                r += 1

        self.setStyleSheet("""
            QDialog { background:#ffffff; }
            QPushButton {
                background:#f3f4f6; border:1px solid #e5e7eb; border-radius:12px;
                font-size:16pt; padding:6px;
            }
            QPushButton:hover { background:#e5e7eb; }
        """)

    def _pick(self, s: str):
        self.selected = s
        self.accept()


class OnlineDialog(QDialog):
    def __init__(self, online: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("В сети")
        self.setFixedSize(300, 360)

        root = QVBoxLayout(self)
        title = QLabel("Сейчас в сети")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        root.addWidget(title)

        box = QLabel("\n".join(online) if online else "(никого нет)")
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.setStyleSheet("""
            QLabel { border:1px solid #e5e7eb; border-radius:12px; padding:10px; }
        """)
        box.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        root.addWidget(box, 1)

        btn = QPushButton("Закрыть")
        btn.clicked.connect(self.accept)
        root.addWidget(btn)

        self.setStyleSheet("""
            QDialog { background:#ffffff; }
            QLabel { color:#111827; }
            QPushButton {
                background:#2563eb; color:white; border:none; border-radius:12px;
                padding:10px 12px; font-size:11pt;
            }
            QPushButton:hover { background:#1d4ed8; }
        """)


class DateSeparator(QFrame):
    def __init__(self, text: str):
        super().__init__()
        self.setObjectName("date_sep")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.addStretch(1)

        lbl = QLabel(text)
        lbl.setObjectName("date_lbl")
        lay.addWidget(lbl)

        lay.addStretch(1)

        self.setStyleSheet("""
            QFrame#date_sep { background: transparent; border: none; }
            QLabel#date_lbl {
                background:#f3f4f6;
                border:1px solid #e5e7eb;
                border-radius:12px;
                padding:6px 10px;
                color:#374151;
                font-size:10pt;
            }
        """)


class MessageBubble(QFrame):
    """
    Пузырь сообщения. ПКМ по пузырю -> Reply / Copy / etc.
    """
    def __init__(
        self,
        message: Dict[str, Any],
        is_outgoing: bool,
        highlight: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.message = message
        self.is_outgoing = is_outgoing
        self.highlight = highlight

        self.setObjectName("bubble")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # выравнивание пузыря влево/вправо
        if is_outgoing:
            outer.addStretch(1)

        self.card = QFrame()
        self.card.setObjectName("card")
        self.card_l = QVBoxLayout(self.card)
        self.card_l.setContentsMargins(10, 8, 10, 6)
        self.card_l.setSpacing(4)

        # Username (для входящих)
        if not is_outgoing:
            name = QLabel(str(message.get("username", "")))
            name.setObjectName("username_lbl")
            name.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            self.card_l.addWidget(name)

        # Reply preview (если это ответ)
        reply_to = message.get("reply_to")
        if reply_to is not None:
            rp = QLabel(f"↪ ответ на #{reply_to}")
            rp.setObjectName("reply_lbl")
            rp.setFont(QFont("Segoe UI", 9))
            rp.setWordWrap(True)
            self.card_l.addWidget(rp)

        # Content
        kind = (message.get("kind") or "text").lower()
        if kind == "sticker":
            c = QLabel(str(message.get("sticker", "")))
            c.setObjectName("sticker_lbl")
            c.setFont(QFont("Segoe UI", 22))
        else:
            c = QLabel(str(message.get("content", "")))
            c.setObjectName("text_lbl")
            c.setFont(QFont("Segoe UI", 11))
            c.setWordWrap(True)
            c.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.card_l.addWidget(c)

        # Bottom row: time + checks
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)

        bottom.addStretch(1)
        t = QLabel(fmt_time_hhmm(str(message.get("created_at", ""))))
        t.setObjectName("time_lbl")
        t.setFont(QFont("Segoe UI", 9))
        bottom.addWidget(t)

        if is_outgoing:
            checks = QLabel("  ✓✓")
            checks.setObjectName("checks_lbl")
            checks.setFont(QFont("Segoe UI", 9))
            bottom.addWidget(checks)

        self.card_l.addLayout(bottom)

        outer.addWidget(self.card)

        if not is_outgoing:
            outer.addStretch(1)

        self._apply_styles()

    def _apply_styles(self):
        # Цвета максимально близко к WhatsApp-стилю
        outgoing_bg = "#d9fdd3"   # светло-зелёный
        incoming_bg = "#ffffff"   # белый
        border = "#e5e7eb"

        # подсветка новых
        hl_bg = "#fff7cc"         # светло-жёлтый

        bg = outgoing_bg if self.is_outgoing else incoming_bg
        if self.highlight:
            bg = hl_bg

        self.card.setStyleSheet(f"""
            QFrame#card {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 14px;
            }}
            QLabel#username_lbl {{ color:#128C7E; }}
            QLabel#reply_lbl {{ color:#6b7280; }}
            QLabel#time_lbl {{ color:#6b7280; }}
            QLabel#checks_lbl {{ color:#6b7280; }}
        """)

    def set_highlight(self, on: bool):
        self.highlight = on
        self._apply_styles()

    def contextMenuEvent(self, event):
        m = self.message
        mid = int(m.get("id") or 0)
        kind = (m.get("kind") or "text").lower()

        menu = QMenu(self)

        act_reply = QAction("Ответить", self)
        menu.addAction(act_reply)

        if kind == "sticker":
            act_copy = QAction("Скопировать стикер", self)
        else:
            act_copy = QAction("Скопировать текст", self)
        menu.addAction(act_copy)

        act_copy_user = QAction("Скопировать имя", self)
        menu.addAction(act_copy_user)

        act_copy_id = QAction("Скопировать ID", self)
        menu.addAction(act_copy_id)

        chosen = menu.exec(event.globalPos())
        if not chosen:
            return

        cb = QApplication.clipboard()

        if chosen == act_reply:
            # передадим наверх через parent() цепочку
            w = self.parent()
            while w is not None and not hasattr(w, "request_reply"):
                w = w.parent()
            if w is not None:
                w.request_reply(mid)
            return

        if chosen == act_copy:
            if kind == "sticker":
                cb.setText(str(m.get("sticker") or ""))
            else:
                cb.setText(str(m.get("content") or ""))
            return

        if chosen == act_copy_user:
            cb.setText(str(m.get("username") or ""))
            return

        if chosen == act_copy_id:
            cb.setText(str(mid))
            return


class ChatWindow(QWidget):
    def __init__(self, worker: WsWorker, username: str):
        super().__init__()
        self.worker = worker
        self.username = username

        self.messages: List[Dict[str, Any]] = []
        self.msg_widgets: Dict[int, MessageBubble] = {}
        self.new_highlight_ids: Set[int] = set()

        self.online: List[str] = []
        self.presence_initialized = False
        self.prev_online_set: Set[str] = set()

        self.reply_to_id: Optional[int] = None
        self.reply_preview: str = ""

        self.setWindowTitle(f"Messenger — {username}")
        self.resize(920, 700)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Top bar
        top = QHBoxLayout()
        self.lbl_status = QLabel("Connected")
        self.lbl_online = QLabel("Online: 0")
        self.btn_online = QPushButton("Who is online")

        self.chk_notify = QCheckBox("Message notifications")
        self.chk_notify.setChecked(True)

        self.chk_presence_notify = QCheckBox("Online alerts")
        self.chk_presence_notify.setChecked(True)

        top.addWidget(self.lbl_status, 1)
        top.addWidget(self.lbl_online)
        top.addWidget(self.btn_online)
        top.addSpacing(10)
        top.addWidget(self.chk_notify)
        top.addWidget(self.chk_presence_notify)

        # Chat list
        self.list = QListWidget()
        self.list.setObjectName("chat_list")
        self.list.setSpacing(6)
        self.list.setUniformItemSizes(False)
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Reply bar
        self.reply_bar = QFrame()
        self.reply_bar.setObjectName("reply_bar")
        rb = QHBoxLayout(self.reply_bar)
        rb.setContentsMargins(10, 6, 10, 6)
        self.reply_label = QLabel("")
        self.btn_cancel_reply = QPushButton("Cancel reply")
        self.btn_cancel_reply.clicked.connect(self.clear_reply)
        rb.addWidget(self.reply_label, 1)
        rb.addWidget(self.btn_cancel_reply)
        self.reply_bar.setVisible(False)

        # Bottom
        bottom = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message...")
        self.input.textChanged.connect(self.on_input_changed)

        self.btn_sticker = QPushButton("Stickers")
        self.btn_send = QPushButton("Send")

        bottom.addWidget(self.input, 1)
        bottom.addWidget(self.btn_sticker)
        bottom.addWidget(self.btn_send)

        root.addLayout(top)
        root.addWidget(self.list, 1)
        root.addWidget(self.reply_bar)
        root.addLayout(bottom)

        # Actions
        self.btn_send.clicked.connect(self.send_text)
        self.input.returnPressed.connect(self.send_text)
        self.btn_sticker.clicked.connect(self.send_sticker)
        self.btn_online.clicked.connect(self.show_online_dialog)

        # Worker signals
        self.worker.message_received.connect(self.on_message)
        self.worker.history_received.connect(self.on_history)
        self.worker.presence_received.connect(self.on_presence)
        self.worker.error.connect(self.on_error)
        self.worker.disconnected.connect(self.on_disconnected)

        # Tray
        self.tray = QSystemTrayIcon(self)
        icon = QApplication.style().standardIcon(QApplication.style().StandardPixmap.SP_ComputerIcon)
        self.tray.setIcon(icon)
        self.tray.setVisible(True)

        menu = QMenu()
        act_toggle_msg = QAction("Toggle message notifications", self)
        act_toggle_msg.triggered.connect(lambda: self.chk_notify.setChecked(not self.chk_notify.isChecked()))
        menu.addAction(act_toggle_msg)

        act_toggle_online = QAction("Toggle online alerts", self)
        act_toggle_online.triggered.connect(lambda: self.chk_presence_notify.setChecked(not self.chk_presence_notify.isChecked()))
        menu.addAction(act_toggle_online)

        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(QApplication.instance().quit)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)

        # Styles
        self.setStyleSheet("""
            QWidget { background: #ffffff; }
            QLabel { color:#111827; font-size: 11pt; }
            QLineEdit {
                border: 1px solid #d1d5db; border-radius: 10px;
                padding: 8px 10px; font-size: 11pt; min-height: 40px;
            }
            QLineEdit:focus { border: 1px solid #3b82f6; }
            QListWidget#chat_list {
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 6px;
                background: #ffffff;
            }
            QFrame#reply_bar {
                border: 1px solid #fde68a;
                background: #fffbeb;
                border-radius: 12px;
            }
            QCheckBox { font-size: 11pt; }
            QPushButton {
                background: #2563eb; color: white; border: none;
                border-radius: 10px; padding: 10px 14px; font-size: 11pt;
            }
            QPushButton:hover { background: #1d4ed8; }
        """)

        # initial online list
        self.worker.submit({"type": "who_online"})

    def closeEvent(self, event):
        try:
            if self.worker:
                self.worker.stop()
                self.worker.wait(1500)
        except Exception:
            pass
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_item_sizes()

    def _refresh_item_sizes(self):
        # при изменении ширины пересчитываем высоту виджетов
        for i in range(self.list.count()):
            item = self.list.item(i)
            w = self.list.itemWidget(item)
            if w is not None:
                item.setSizeHint(w.sizeHint())

    # ---------- Reply (called from MessageBubble via parent chain) ----------
    def request_reply(self, mid: int):
        m = self._find_message(mid)
        if not m:
            return
        self.reply_to_id = mid
        self.reply_preview = msg_preview(m)
        user = str(m.get("username") or "")
        self.reply_label.setText(f"Reply to #{mid} ({user}): {self.reply_preview}")
        self.reply_bar.setVisible(True)
        self.input.setFocus()

    def clear_reply(self):
        self.reply_to_id = None
        self.reply_preview = ""
        self.reply_bar.setVisible(False)

    def _find_message(self, mid: int) -> Optional[Dict[str, Any]]:
        for m in self.messages:
            if int(m.get("id") or 0) == mid:
                return m
        return None

    # ---------- New highlight ----------
    def on_input_changed(self, text: str):
        if text and self.new_highlight_ids:
            # снять подсветку со всех новых
            for mid in list(self.new_highlight_ids):
                w = self.msg_widgets.get(mid)
                if w:
                    w.set_highlight(False)
            self.new_highlight_ids.clear()

    # ---------- Render list ----------
    def _add_date_separator_if_needed(self, last_date: Optional[str], cur_date: str) -> Tuple[Optional[str], bool]:
        if not cur_date:
            return last_date, False
        if last_date != cur_date:
            sep = DateSeparator(cur_date)
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
            self.list.setItemWidget(item, sep)
            item.setSizeHint(sep.sizeHint())
            return cur_date, True
        return last_date, False

    def _add_message_widget(self, m: Dict[str, Any], highlight: bool):
        mid = int(m.get("id") or 0)
        is_out = (str(m.get("username") or "") == self.username)

        bubble = MessageBubble(m, is_outgoing=is_out, highlight=highlight, parent=self.list)
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(item)
        self.list.setItemWidget(item, bubble)
        item.setSizeHint(bubble.sizeHint())

        self.msg_widgets[mid] = bubble

    def _scroll_to_bottom(self):
        sb = self.list.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---------- Worker events ----------
    def on_history(self, messages: list):
        self.messages = messages or []
        self.msg_widgets.clear()
        self.new_highlight_ids.clear()

        self.list.clear()

        last_date = None
        for m in self.messages:
            d = fmt_date_ru(str(m.get("created_at", "")))
            last_date, _ = self._add_date_separator_if_needed(last_date, d)
            self._add_message_widget(m, highlight=False)

        self._refresh_item_sizes()
        self._scroll_to_bottom()

    def on_message(self, m: dict):
        if not m:
            return
        self.messages.append(m)

        d = fmt_date_ru(str(m.get("created_at", "")))
        # проверим, нужен ли новый разделитель даты
        last_date = None
        # найдём последнюю дату по последнему реальному сообщению в листе
        for mm in reversed(self.messages[:-1]):
            last_date = fmt_date_ru(str(mm.get("created_at", "")))
            if last_date:
                break
        if d and d != last_date:
            self._add_date_separator_if_needed(last_date, d)

        highlight = False
        if not self.input.text():
            highlight = True
            try:
                self.new_highlight_ids.add(int(m.get("id") or 0))
            except Exception:
                pass

        self._add_message_widget(m, highlight=highlight)
        self._refresh_item_sizes()
        self._scroll_to_bottom()

        # уведомление о сообщении
        if self.chk_notify.isChecked():
            try:
                if (m.get("username") or "") != self.username:
                    title = f"New message from {m.get('username','')}"
                    kind = (m.get("kind") or "text").lower()
                    if kind == "sticker":
                        body = f"Sticker: {m.get('sticker','')}"
                    else:
                        body = (m.get("content") or "")
                        body = body[:120] + ("…" if len(body) > 120 else "")
                    self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 4000)
            except Exception:
                pass

    def on_presence(self, online: list):
        self.online = online or []
        self.lbl_online.setText(f"Online: {len(self.online)}")

        current = set(self.online)

        # первое presence — без уведомлений (иначе будет спам при входе)
        if not self.presence_initialized:
            self.presence_initialized = True
            self.prev_online_set = current
            return

        joined = current - self.prev_online_set
        self.prev_online_set = current
        if not joined:
            return

        if self.chk_presence_notify.isChecked():
            for name in sorted(joined, key=lambda x: x.lower()):
                if name == self.username:
                    continue
                try:
                    self.tray.showMessage(
                        "User online",
                        f"{name} is now online",
                        QSystemTrayIcon.MessageIcon.Information,
                        3000
                    )
                except Exception:
                    pass

    def on_error(self, msg: str):
        QMessageBox.warning(self, "Error", msg)

    def on_disconnected(self, reason: str):
        self.lbl_status.setText("Disconnected")
        self.btn_send.setEnabled(False)
        self.btn_sticker.setEnabled(False)
        self.input.setEnabled(False)
        QMessageBox.warning(self, "Disconnected", reason)

    # ---------- Actions ----------
    def send_text(self):
        txt = self.input.text().strip()
        if not txt:
            return
        self.input.clear()

        payload = {"type": "send", "kind": "text", "content": txt}
        if self.reply_to_id is not None:
            payload["reply_to"] = self.reply_to_id
            self.clear_reply()

        self.worker.submit(payload)

    def send_sticker(self):
        dlg = StickerDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected:
            return

        payload = {"type": "send", "kind": "sticker", "sticker": dlg.selected}
        if self.reply_to_id is not None:
            payload["reply_to"] = self.reply_to_id
            self.clear_reply()

        self.worker.submit(payload)

    def show_online_dialog(self):
        dlg = OnlineDialog(self.online, self)
        dlg.exec()


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Messenger — Login")
        self.setFixedSize(520, 420)

        self.worker: Optional[WsWorker] = None
        self.chat_window: Optional[ChatWindow] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)

        root.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(430)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(22, 22, 22, 22)
        card_l.setSpacing(12)

        title = QLabel("Friends Messenger")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        subtitle = QLabel("Sign in to continue")
        subtitle.setFont(QFont("Segoe UI", 11))
        subtitle.setStyleSheet("color:#6b7280;")

        self.host = QLineEdit()
        self.host.setPlaceholderText("Server host (e.g. 192.168.1.10)")
        self.host.setText("127.0.0.1")

        self.port = QLineEdit()
        self.port.setPlaceholderText("Port")
        self.port.setText("8765")

        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")

        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        self.btn = QPushButton("Login")
        self.btn.setMinimumHeight(42)

        card_l.addWidget(title)
        card_l.addWidget(subtitle)
        card_l.addSpacing(6)
        card_l.addWidget(QLabel("Server"))
        row = QHBoxLayout()
        row.addWidget(self.host, 3)
        row.addWidget(self.port, 1)
        card_l.addLayout(row)
        card_l.addSpacing(4)
        card_l.addWidget(QLabel("Account"))
        card_l.addWidget(self.username)
        card_l.addWidget(self.password)
        card_l.addSpacing(8)
        card_l.addWidget(self.btn)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 10)
        card.setGraphicsEffect(shadow)

        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(card)
        wrap.addStretch(1)

        root.addLayout(wrap)
        root.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        self.setStyleSheet("""
            QWidget { background: #ffffff; }
            QFrame#card {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 18px;
            }
            QLabel { color:#111827; }
            QLineEdit {
                border: 1px solid #d1d5db;
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 12pt;
                min-height: 40px;
            }
            QLineEdit:focus { border: 1px solid #3b82f6; }
            QPushButton {
                background: #2563eb;
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 12pt;
            }
            QPushButton:hover { background: #1d4ed8; }
        """)

        self.btn.clicked.connect(self.do_login)
        self.password.returnPressed.connect(self.do_login)

    def do_login(self):
        host = self.host.text().strip() or "127.0.0.1"
        try:
            port = int(self.port.text().strip() or "8765")
        except ValueError:
            QMessageBox.warning(self, "Validation", "Port must be a number.")
            return

        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            QMessageBox.warning(self, "Validation", "Username and password are required.")
            return

        if self.worker:
            try:
                self.worker.stop()
                self.worker.wait(1000)
            except Exception:
                pass
            self.worker = None

        self.btn.setEnabled(False)
        self.btn.setText("Connecting...")

        self.worker = WsWorker(host, port, username, password)
        self.worker.login_ok.connect(lambda is_admin: self.on_login_ok(username))
        self.worker.login_error.connect(self.on_login_error)
        self.worker.start()

    def on_login_ok(self, username: str):
        self.chat_window = ChatWindow(self.worker, username=username)
        self.chat_window.show()
        self.close()

    def on_login_error(self, msg: str):
        QMessageBox.warning(self, "Login failed", msg)
        self.btn.setEnabled(True)
        self.btn.setText("Login")
        if self.worker:
            try:
                self.worker.stop()
                self.worker.wait(1500)
            except Exception:
                pass
            self.worker = None


def main():
    app = QApplication(sys.argv)
    w = LoginWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
