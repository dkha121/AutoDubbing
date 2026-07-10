"""Video preview widget using Qt Multimedia.

Degrades gracefully: if QtMultimedia is unavailable, shows a placeholder label
so the rest of the app still works.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    _HAS_MULTIMEDIA = True
except ImportError:  # pragma: no cover - optional module
    _HAS_MULTIMEDIA = False


class VideoPreviewWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._path: str | None = None

        if not _HAS_MULTIMEDIA:
            self._fallback = QLabel("Video preview unavailable\n(install PySide6 multimedia)")
            self._fallback.setAlignment(Qt.AlignCenter)
            layout.addWidget(self._fallback)
            return

        self.video = QVideoWidget()
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setVideoOutput(self.video)
        self.player.setAudioOutput(self.audio)
        layout.addWidget(self.video, 1)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        self.position = QSlider(Qt.Horizontal)
        self.position.sliderMoved.connect(self._seek)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.position, 1)
        layout.addLayout(controls)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)

    def load(self, path: str) -> None:
        self._path = path
        if not _HAS_MULTIMEDIA:
            self._fallback.setText(f"Loaded:\n{Path(path).name}")
            return
        from PySide6.QtCore import QUrl
        self.player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))

    def toggle_play(self) -> None:
        if not _HAS_MULTIMEDIA:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_btn.setText("Play")
        else:
            self.player.play()
            self.play_btn.setText("Pause")

    def seek_seconds(self, seconds: float) -> None:
        if _HAS_MULTIMEDIA:
            self.player.setPosition(int(seconds * 1000))

    def _seek(self, value: int) -> None:
        self.player.setPosition(value)

    def _on_position(self, pos: int) -> None:
        self.position.setValue(pos)

    def _on_duration(self, dur: int) -> None:
        self.position.setRange(0, dur)
