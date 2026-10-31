"""A procedural, animated companion: no downloaded art or external animation loop."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from buddy.core.assistant import State
from buddy.core.config import Config

LABELS = {
    "idle": "Here for you · mic off",
    "wake": "Wake word on · mic on locally",
    "listening": "Listening · mic on",
    "thinking": "Thinking · mic off",
    "talking": "Talking · mic off",
    "muted": "Muted · mic off",
    "sleeping": "Sleeping · mic off",
    "happy": "You got this · mic off",
    "confirming": "Waiting for your approval · mic off",
    "error": "Needs attention · mic off",
}


def draw_buddy(painter: QPainter, rect: QRectF, state: str, phase: float = 0) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.center())
    unit = min(rect.width(), rect.height()) / 180
    painter.scale(unit, unit)
    bob = math.sin(phase * 1.6) * 3 if state not in {"muted", "sleeping"} else 0
    painter.translate(0, bob)
    asleep = state in {"muted", "sleeping"}
    color = QColor("#92a0b2" if asleep else "#67e8ce")
    if state == "listening":
        painter.setPen(QPen(QColor(103, 232, 206, 90), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = 76 + math.sin(phase * 4) * 4
        painter.drawEllipse(QPointF(0, 5), radius, radius)
    shadow = QRadialGradient(QPointF(0, 71), 65)
    shadow.setColorAt(0, QColor(0, 0, 0, 70))
    shadow.setColorAt(1, QColor(0, 0, 0, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(shadow)
    painter.drawEllipse(QRectF(-68, 56, 136, 30))
    painter.setBrush(color.darker(120))
    painter.drawRoundedRect(QRectF(-50, 48, 25, 22), 10, 10)
    painter.drawRoundedRect(QRectF(25, 48, 25, 22), 10, 10)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(-70, -55, 140, 120), 47, 47)
    painter.setBrush(QColor("#c5fff0" if not asleep else "#b7c0cd"))
    painter.drawEllipse(QRectF(-41, -47, 80, 23))
    painter.setBrush(QColor("#142b35"))
    painter.drawRoundedRect(QRectF(-56, -24, 112, 67), 27, 27)
    painter.setPen(QPen(QColor("#c6fff2"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    blink = (phase % 5.7) > 5.5
    if asleep or blink or state == "happy":
        for x in (-24, 24):
            painter.drawLine(QPointF(x - 7, 1), QPointF(x + 7, 1))
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#c6fff2"))
        for x in (-24, 24):
            painter.drawRoundedRect(QRectF(x - 5, -10, 10, 20), 5, 5)
    painter.setPen(QPen(QColor("#c6fff2"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    if state == "talking":
        height = 4 + abs(math.sin(phase * 13)) * 12
        painter.setBrush(QColor("#ffb9d5"))
        painter.drawEllipse(QRectF(-9, 22 - height / 2, 18, height))
    elif state == "thinking":
        for i in range(3):
            painter.drawPoint(QPointF(-10 + i * 10, 23 + math.sin(phase * 5 + i) * 2))
    else:
        painter.drawArc(QRectF(-12, 12, 24, 14), 205 * 16, 130 * 16)
    painter.setPen(QPen(color, 4))
    painter.drawLine(QPointF(0, -55), QPointF(0, -69))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#fcd78e" if state == "confirming" else "#c5fff0"))
    painter.drawEllipse(QPointF(0, -73), 6, 6)
    painter.restore()


def pet_icon() -> QIcon:
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_buddy(painter, QRectF(0, 0, 128, 128), "idle")
    painter.end()
    return QIcon(pixmap)


class PetWidget(QWidget):
    talk = Signal()
    menu_requested = Signal(object)

    def __init__(self, config: Config):
        super().__init__()
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if config.ui.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName("BUDDY desktop companion")
        self.setToolTip("Double-click to talk. Drag to move. Right-click for controls.")
        self.resize(round(270 * config.ui.scale), round(240 * config.ui.scale))
        self.current_state = State.IDLE.value
        self.config, self.drag_offset = config, None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        if not config.ui.reduced_motion:
            self.timer.start(40)

    def set_state(self, state: str):
        self.current_state = state
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        draw_buddy(
            painter,
            QRectF(35, 0, self.width() - 70, self.height() - 37),
            self.current_state,
            0 if self.config.ui.reduced_motion else time.monotonic(),
        )
        painter.setPen(QColor("#eef6ff"))
        painter.setFont(QFont("Arial", 10))
        painter.fillRect(
            QRectF(4, self.height() - 34, self.width() - 8, 30), QColor(18, 28, 42, 225)
        )
        painter.drawText(
            QRectF(6, self.height() - 34, self.width() - 12, 30),
            Qt.AlignmentFlag.AlignCenter,
            LABELS.get(self.current_state, self.current_state),
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.talk.emit()
