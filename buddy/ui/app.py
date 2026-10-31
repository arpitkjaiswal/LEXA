"""Native macOS pet, chat controls, tray, settings and exact-action approval dialogs."""

from __future__ import annotations

import asyncio
import html
import json
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from buddy.core.config import Config, load_config
from buddy.core.errors import BuddyError
from buddy.ui.pet import LABELS, PetWidget, pet_icon
from buddy.ui.runtime import DesktopRuntime
from buddy.ui.settings import SettingsDialog

STYLE = """
QWidget { background: #111c2d; color: #e8f1ff; font-size: 13px; }
QTextBrowser, QLineEdit, QPlainTextEdit { background: #19283e; border: 1px solid #30435e;
    border-radius: 10px; padding: 10px; selection-background-color: #245d61; }
QPushButton { background: #253b55; border: 0; border-radius: 8px; padding: 9px 12px; }
QPushButton:hover { background: #345274; }
QPushButton#primary { background: #67e8ce; color: #112d35; font-weight: 600; }
QLabel#status { color: #88b2c1; padding: 4px 0; }
QMenu { background: #19283e; padding: 6px; }
QMenu::item { padding: 7px 18px; }
QMenu::item:selected { background: #30435e; }
"""


class Bridge(QObject):
    event = Signal(str, object)


class ChatWindow(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("BUDDY · Your desktop friend")
        self.setWindowIcon(pet_icon())
        self.resize(520, 700)
        layout = QVBoxLayout(self)
        self.heading = QLabel(
            f"<h2>{html.escape(controller.config.pet.name)} "
            "<span style='color:#67e8ce'>●</span></h2>"
        )
        layout.addWidget(self.heading)
        self.setup_status = QLabel("Starting BUDDY…")
        self.setup_status.setWordWrap(True)
        layout.addWidget(self.setup_status)
        setup = QHBoxLayout()
        configure = QPushButton("Configure AI")
        configure.clicked.connect(controller.settings)
        self.prepare = QPushButton("Prepare voice")
        self.prepare.clicked.connect(lambda: controller.runtime.submit("prepare_voice"))
        self.demo = QCheckBox("Demo")
        self.demo.toggled.connect(lambda checked: controller.runtime.submit("demo", checked))
        for widget in (configure, self.prepare, self.demo):
            setup.addWidget(widget)
        layout.addLayout(setup)
        self.status = QLabel(LABELS["idle"])
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(False)
        layout.addWidget(self.transcript)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Talk to BUDDY…")
        self.input.setMaxLength(controller.config.brain.max_input_chars)
        self.input.returnPressed.connect(self.send)
        layout.addWidget(self.input)
        controls = QHBoxLayout()
        self.talk = QPushButton("Record")
        self.talk.setObjectName("primary")
        self.talk.clicked.connect(lambda: controller.runtime.submit("talk"))
        self.mute = QPushButton("Mute")
        self.mute.setCheckable(True)
        self.mute.toggled.connect(lambda value: controller.runtime.submit("mute", value))
        stop = QPushButton("Stop reply")
        stop.clicked.connect(lambda: controller.runtime.submit("stop"))
        for widget in (self.talk, self.mute, stop):
            controls.addWidget(widget)
        layout.addLayout(controls)
        extras = QHBoxLayout()
        for name, callback in [
            ("Memories", lambda: controller.runtime.submit("memory")),
            ("Settings", controller.settings),
            ("Hide", self.hide),
            ("Quit", controller.quit),
        ]:
            button = QPushButton(name)
            button.clicked.connect(callback)
            extras.addWidget(button)
        layout.addLayout(extras)
        self.answer = ""
        self.document_prefix = ""

    def send(self):
        text = self.input.text().strip()
        if text:
            self.controller.runtime.submit("text", text)
            self.input.clear()

    def add(self, label: str, text: str, color="#88b2c1"):
        self.transcript.append(
            f"<p><b style='color:{color}'>{html.escape(label)}</b><br>"
            f"{html.escape(text).replace(chr(10), '<br>')}</p>"
        )
        # Bound UI retention independently of whether disk history is enabled.
        if self.transcript.document().blockCount() > 300:
            cursor = self.transcript.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            for _ in range(50):
                cursor.select(cursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class DesktopController(QObject):
    def __init__(self, app, config: Config, path: Path, env_path: Path, *, demo=False, wake=False):
        super().__init__()
        self.app, self.config, self.path, self.env_path = app, config, path, env_path
        self.was_ready, self.fatal_error = False, False
        self.bridge = Bridge()
        self.bridge.event.connect(self.receive_event, Qt.ConnectionType.QueuedConnection)
        self.runtime = DesktopRuntime(config, self.bridge.event.emit, demo=demo, wake=wake)
        self.pet = PetWidget(config)
        self.chat = ChatWindow(self)
        self.chat.setStyleSheet(STYLE)
        self.chat.setEnabled(False)
        self.menu = QMenu()
        self.menu.setStyleSheet(STYLE)
        self.menu.addAction("Show chat", self.show_chat)
        self.menu.addAction("Talk / finish recording", lambda: self.runtime.submit("talk"))
        self.wake_action = self.menu.addAction("Wake-word listening · mic on")
        self.wake_action.setCheckable(True)
        self.wake_action.setChecked(wake)
        self.wake_action.toggled.connect(lambda checked: self.runtime.submit("wake", checked))
        self.mute_action = self.menu.addAction("Mute microphone + voice")
        self.mute_action.setCheckable(True)
        self.mute_action.toggled.connect(lambda checked: self.runtime.submit("mute", checked))
        self.menu.addAction("Stop reply", lambda: self.runtime.submit("stop"))
        self.menu.addAction("Sleep", lambda: self.runtime.submit("sleep"))
        self.menu.addAction("Memories", lambda: self.runtime.submit("memory"))
        self.menu.addAction("Settings", self.settings)
        self.menu.addAction("Download wake model", lambda: self.runtime.submit("download_wake"))
        self.menu.addAction("Reset current session", lambda: self.runtime.submit("reset"))
        self.menu.addSeparator()
        self.menu.addAction("Quit BUDDY", self.quit)
        self.pet.talk.connect(lambda: self.runtime.submit("talk"))
        self.pet.menu_requested.connect(self.menu.popup)
        self.tray = QSystemTrayIcon(pet_icon(), self)
        self.tray.setToolTip("BUDDY · mic off")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(
            lambda reason: (
                self.show_chat() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
            )
        )
        self.tray.show()
        screen = app.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.pet.move(
                area.right() - self.pet.width() - 25, area.bottom() - self.pet.height() - 20
            )
        self.pet.show()
        self.chat.show()
        self.confirmations: dict[str, QMessageBox] = {}
        self.memory_window = None
        self.thread = threading.Thread(
            target=lambda: asyncio.run(self.runtime.run()), name="buddy-async", daemon=False
        )
        self.thread.start()
        self.quitting = False
        self.quit_timer = QTimer(self)
        self.quit_timer.timeout.connect(self._finish_quit)

    def show_chat(self):
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()

    def settings(self):
        dialog = SettingsDialog(self.config, self.path, self.env_path, self.chat)
        dialog.setStyleSheet(STYLE)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                # Re-read the separate secrets file, not the dialog's stale Secrets object.
                config = load_config(self.path, self.env_path if self.env_path.is_file() else None)
                self.config = replace(config, data_dir=self.config.data_dir)
            except BuddyError as error:
                self.chat.add("Settings", str(error))
                return
            self.pet.apply_config(self.config)
            self.chat.heading.setText("<h2>" + html.escape(self.config.pet.name) + "</h2>")
            self.chat.input.setMaxLength(self.config.brain.max_input_chars)
            self.runtime.submit("configure", self.config)

    @Slot(str, object)
    def receive_event(self, kind, payload):
        if kind == "ready":
            self.was_ready = True
            self.chat.setEnabled(True)
        elif kind == "mode":
            self.chat.demo.blockSignals(True)
            self.chat.demo.setChecked(payload["demo"])
            self.chat.demo.blockSignals(False)
            self.chat.setup_status.setText(
                "Demo · canned replies; actions disabled"
                if payload["demo"]
                else (
                    f"AI configured: {payload['provider']} · send a message to test access"
                    if payload["configured"]
                    else "Local mode · try ‘what time is it’ or ‘set a timer for 5 minutes’. "
                    "Configure AI to chat freely."
                )
            )
        elif kind == "voice_ready":
            self.chat.prepare.setText("Voice ready ✓" if payload else "Prepare voice")
        elif kind == "state":
            self.pet.set_state(payload)
            label = LABELS.get(payload, payload)
            self.chat.status.setText(label)
            self.tray.setToolTip("BUDDY · " + label)
            self.chat.talk.setText("Finish recording" if payload == "listening" else "Record")
            muted = payload in {"muted", "sleeping"}
            for control in (self.chat.mute, self.mute_action):
                control.blockSignals(True)
                control.setChecked(muted)
                control.blockSignals(False)
            if payload == "muted":
                for dialog in list(self.confirmations.values()):
                    dialog.reject()
        elif kind == "turn":
            self.chat.add("You", payload, "#67e8ce")
            self.chat.answer = ""
            self.chat.document_prefix = self.chat.transcript.toHtml()
        elif kind == "text":
            self.chat.answer += payload
            self.chat.transcript.setHtml(
                self.chat.document_prefix
                + "<p><b>BUDDY</b><br>"
                + html.escape(self.chat.answer).replace("\n", "<br>")
                + "</p>"
            )
            self.chat.transcript.verticalScrollBar().setValue(
                self.chat.transcript.verticalScrollBar().maximum()
            )
        elif kind in {"notice", "fatal"}:
            self.chat.add("BUDDY", str(payload))
            if kind == "fatal":
                self.fatal_error = True
                self.show_chat()
        elif kind == "wake_enabled":
            self.wake_action.blockSignals(True)
            self.wake_action.setChecked(bool(payload))
            self.wake_action.blockSignals(False)
        elif kind == "confirmation":
            self.confirm(payload)
        elif kind == "cancel_confirmations":
            for dialog in list(self.confirmations.values()):
                dialog.reject()
        elif kind == "memory":
            self.show_memory(payload)
        elif kind == "reminder":
            self.chat.add("Reminder", payload, "#fcd78e")
            self.tray.showMessage("BUDDY reminder", payload)
            self.show_chat()
        elif kind == "closed" and self.quitting:
            self._finish_quit()

    def confirm(self, pending):
        identifier = pending["id"]
        dialog = QMessageBox(self.chat)
        dialog.setWindowTitle("Approve BUDDY action")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(f"Allow {pending['tool']}?")
        dialog.setInformativeText(
            pending["arguments"] + f"\n\nID: {identifier}\nExpires in {pending['seconds']} seconds."
        )
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        self.confirmations[identifier] = dialog

        def done(result):
            self.confirmations.pop(identifier, None)
            if result == QMessageBox.StandardButton.Yes:
                self.runtime.submit("confirm", identifier)
            else:
                self.runtime.submit("cancel", identifier)
            dialog.deleteLater()

        dialog.finished.connect(done)
        QTimer.singleShot(pending["seconds"] * 1000, dialog, dialog.reject)
        dialog.open()
        self.show_chat()

    def show_memory(self, data):
        dialog = QDialog(self.chat)
        dialog.setWindowTitle("BUDDY · Saved memory")
        dialog.resize(520, 440)
        layout = QVBoxLayout(dialog)
        view = QTextBrowser()
        view.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))
        layout.addWidget(view)
        key = QLineEdit()
        key.setPlaceholderText("Exact fact key to forget")
        layout.addWidget(key)
        forget = QPushButton("Forget this fact…")
        forget.clicked.connect(
            lambda: self.runtime.submit(
                "tool", {"name": "forget_fact", "arguments": {"key": key.text()}}
            )
        )
        clear = QPushButton("Delete saved chat history…")
        clear.clicked.connect(lambda: self.runtime.submit("tool", {"name": "clear_saved_history"}))
        layout.addWidget(forget)
        layout.addWidget(clear)
        layout.addWidget(QLabel("Deletion requires approval. Reopen this window to refresh."))
        self.memory_window = dialog
        dialog.show()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.chat.status.setText("Closing microphone and voice…")
        self.runtime.submit("quit")
        self.quit_timer.start(50)

    def _finish_quit(self):
        if not self.thread.is_alive():
            self.quit_timer.stop()
            self.tray.hide()
            self.pet.hide()
            self.chat.hide()
            self.app.quit()


def run_desktop(
    config: Config, path: Path, env_path: Path, *, demo=False, wake=False, smoke_test=False
) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("BUDDY")
    app.setQuitOnLastWindowClosed(False)
    config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = QLockFile(str(config.data_dir / "desktop.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(
            None, "BUDDY", "BUDDY is already running. Open it from the menu bar."
        )
        return 1
    controller = DesktopController(app, config, path, env_path, demo=demo, wake=wake)
    if smoke_test:
        QTimer.singleShot(1500, controller.quit)
    # Keep controller and lock alive for the full Qt event loop.
    result = app.exec()
    controller.runtime.submit("quit")
    controller.thread.join(10)
    lock.unlock()
    if smoke_test and (
        not controller.was_ready or controller.fatal_error or controller.thread.is_alive()
    ):
        return 1
    return result
