"""Run in a separate Qt process; no microphone, network or actual OS action is used."""

import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from buddy.core.config import Config
from buddy.ui.app import DesktopController
from buddy.ui.pet import draw_buddy
from buddy.ui.settings import SettingsDialog


def smoke(directory: Path):
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = Config(data_dir=directory)
    config = replace(
        config,
        tts=replace(config.tts, backend="none"),
        logging=replace(config.logging, enabled=False),
    )
    controller = DesktopController(
        app, config, directory / "config.yaml", directory / ".env", demo=True
    )
    errors = []

    def check():
        try:
            assert "Demo mode is working" in controller.chat.transcript.toPlainText()
            controller.chat.grab().save(str(directory / "desktop-chat.png"))
            sheet = QPixmap(720, 400)
            sheet.fill(QColor("#111c2d"))
            painter = QPainter(sheet)
            from PySide6.QtCore import QRectF

            for i, state in enumerate(
                [
                    "idle",
                    "listening",
                    "thinking",
                    "talking",
                    "happy",
                    "sleeping",
                    "muted",
                    "confirming",
                ]
            ):
                rect = QRectF((i % 4) * 180, (i // 4) * 200, 180, 170)
                draw_buddy(painter, rect, state, 1.4)
                painter.setPen(QColor("#e8f1ff"))
                painter.drawText(int(rect.x()) + 45, int(rect.y()) + 185, state)
            painter.end()
            sheet.save(str(directory / "pet-states.png"))
            settings = SettingsDialog(
                config, directory / "config.yaml", directory / ".env", controller.chat
            )
            settings.name.setText("BUDDY QA")
            settings.save()
            assert "BUDDY QA" in (directory / "config.yaml").read_text()
            controller.confirm(
                {"id": "test-only", "tool": "test action", "arguments": "{}", "seconds": 60}
            )
            controller.confirmations["test-only"].button(QMessageBox.StandardButton.Cancel).click()
            assert controller.confirmations == {}
        except BaseException as error:
            errors.append(error)
        finally:
            controller.quit()

    QTimer.singleShot(300, lambda: controller.runtime.submit("text", "Hello BUDDY"))
    QTimer.singleShot(900, check)
    QTimer.singleShot(10000, app.quit)
    app.exec()
    controller.runtime.submit("quit")
    controller.thread.join(5)
    assert not controller.thread.is_alive(), "The desktop worker did not close"
    if errors:
        raise errors[0]
    print("desktop smoke OK")


if __name__ == "__main__":
    destination = Path(sys.argv[1])
    destination.mkdir(parents=True, exist_ok=True)
    smoke(destination)
