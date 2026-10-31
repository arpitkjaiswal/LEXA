"""Native settings editor; no credentials are displayed or written into YAML."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from buddy.core.errors import BuddyError
from buddy.core.settings import save_api_key, save_settings, sync_env_overrides


class SettingsDialog(QDialog):
    def __init__(self, config, path: Path, env_path: Path, parent=None):
        super().__init__(parent)
        self.config, self.path, self.env_path = config, path, env_path
        self.setWindowTitle("BUDDY · Settings")
        self.resize(500, 640)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        self.name, self.user = QLineEdit(config.pet.name), QLineEdit(config.pet.user_name)
        self.personality = QPlainTextEdit(config.pet.personality)
        self.personality.setMaximumHeight(90)
        self.provider = QComboBox()
        self.provider.addItems(["anthropic", "openai", "ollama"])
        self.provider.setCurrentText(config.brain.provider)
        self.model = QLineEdit(config.brain.model)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Leave blank to keep existing key")
        self.endpoint = QLineEdit(config.brain.ollama_base_url)
        self.backend = QComboBox()
        self.backend.addItems(["edge", "say", "pyttsx3", "piper", "none"])
        self.backend.setCurrentText(config.tts.backend)
        self.voice = QLineEdit(config.tts.voice)
        self.local_voice = QLineEdit(config.tts.local_voice)
        self.piper_model = QLineEdit(config.tts.piper_model)
        self.piper_rate = QSpinBox()
        self.piper_rate.setRange(8000, 48000)
        self.piper_rate.setValue(config.tts.piper_sample_rate)
        self.stt_model = QComboBox()
        self.stt_model.setEditable(True)
        self.stt_model.addItems(["tiny", "base", "small", "medium"])
        self.stt_model.setCurrentText(config.stt.model)
        self.wake_model = QLineEdit(config.wake.model)
        self.framework = QComboBox()
        self.framework.addItems(["auto", "onnx", "tflite"])
        self.framework.setCurrentText(config.wake.framework)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.01, 1)
        self.threshold.setSingleStep(0.05)
        self.threshold.setValue(config.wake.threshold)
        self.timezone = QLineEdit(config.memory.timezone)
        self.timezone.setPlaceholderText("System timezone, or Asia/Kolkata")
        self.history = QCheckBox("Retain chat history locally")
        self.history.setChecked(config.memory.save_history)
        self.memory = QCheckBox("Enable explicitly saved preferences")
        self.memory.setChecked(config.memory.enabled)
        self.top = QCheckBox("Keep the pet above other windows")
        self.top.setChecked(config.ui.always_on_top)
        self.reduced = QCheckBox("Reduce pet motion")
        self.reduced.setChecked(config.ui.reduced_motion)
        for label, widget in [
            ("Pet name", self.name),
            ("Your name", self.user),
            ("Personality", self.personality),
            ("AI provider", self.provider),
            ("Model ID", self.model),
            ("New API key", self.api_key),
            ("Ollama URL", self.endpoint),
            ("Speech engine", self.backend),
            ("Edge voice", self.voice),
            ("Local voice", self.local_voice),
            ("Piper model path", self.piper_model),
            ("Piper sample rate", self.piper_rate),
            ("Whisper model / local path", self.stt_model),
            ("Wake model / trained path", self.wake_model),
            ("Wake framework", self.framework),
            ("Wake threshold", self.threshold),
            ("Timezone", self.timezone),
            ("Memory", self.memory),
            ("Chat retention", self.history),
            ("Pet", self.top),
            ("Animation", self.reduced),
        ]:
            form.addRow(label, widget)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        note = QLabel(
            "Save applies immediately and stops the current turn. "
            "Choose a model ID from your provider account; Ollama needs a running server "
            "and installed model. Process environment variables take priority. "
            "Retained chats and saved facts are sent as context "
            "to the chosen AI provider. Startup is managed separately with --startup."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        config = replace(
            self.config,
            pet=replace(
                self.config.pet,
                name=self.name.text().strip(),
                user_name=self.user.text().strip(),
                personality=self.personality.toPlainText(),
            ),
            brain=replace(
                self.config.brain,
                provider=self.provider.currentText(),
                model=self.model.text().strip(),
                ollama_base_url=self.endpoint.text().strip(),
            ),
            tts=replace(
                self.config.tts,
                backend=self.backend.currentText(),
                voice=self.voice.text(),
                local_voice=self.local_voice.text(),
                piper_model=self.piper_model.text().strip(),
                piper_sample_rate=self.piper_rate.value(),
            ),
            stt=replace(self.config.stt, model=self.stt_model.currentText().strip()),
            wake=replace(
                self.config.wake,
                model=self.wake_model.text().strip(),
                framework=self.framework.currentText(),
                threshold=self.threshold.value(),
            ),
            memory=replace(
                self.config.memory,
                enabled=self.memory.isChecked(),
                save_history=self.history.isChecked(),
                timezone=self.timezone.text().strip(),
            ),
            ui=replace(
                self.config.ui,
                always_on_top=self.top.isChecked(),
                reduced_motion=self.reduced.isChecked(),
            ),
        )
        try:
            save_settings(config, self.path)
            sync_env_overrides(config, self.env_path)
            save_api_key(self.env_path, config.brain.provider, self.api_key.text().strip())
        except BuddyError as error:
            QMessageBox.warning(self, "Settings could not be saved", str(error))
            return
        self.api_key.clear()
        self.saved_config = config
        self.accept()
