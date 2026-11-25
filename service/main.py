"""
Фоновая служба воспроизведения (Android, python-for-android service).

Запускается из основного приложения так:

    from android import service   # пакет `android`, requirement "android" в buildozer.spec
    self._svc = service.AndroidService("myservice")
    self._svc.start(on_task_start=on_started)

Служба работает в отдельном Python-процессе, поэтому SoundLoader в ней
продолжает играть даже когда UI-приложение свёрнуто ("Домой") или экран погас
(при наличии WAKE_LOCK и FOREGROUND_SERVICE).

Протокол сообщений (dict):
    {"cmd": "play",  "path": <mp3>, "track_id": <int>}
    {"cmd": "pause"} / {"cmd": "resume"} / {"cmd": "stop"}
    {"cmd": "seek",  "pos": <сек>}
    {"cmd": "ping"} -> ответ {"state": ..., "pos": ..., "duration": ...}

ВАЖНО (Android 8+): чтобы ОС не убивала службу, она должна быть foreground.
Пакет `android` (python-for-android) поднимает foreground-уведомление для служб,
объявленных в buildozer.spec (`services = myservice:service/main.py`).
Разрешение FOREGROUND_SERVICE добавлено в buildozer.spec.
"""

import os
import json

DB_FILE = os.environ.get("MUSICAPP_DB", "music_app.db")


def _log(msg):
    try:
        print("[myservice]", msg, flush=True)
    except Exception:
        pass


class MusicService:
    """Минимальный плеер-движок для фонового процесса."""

    def __init__(self):
        self.sound = None
        self.track_id = None
        self.duration = 0
        self.state = "stop"  # stop | play | pause
        self._paused_pos = 0

    # ---- API службы -----------------------------------------------------
    def on_start(self):
        _log("started")

    def on_stop(self):
        self.stop()

    def on_message(self, message):
        """Вызывается из mainloop при получении сообщения от UI-приложения."""
        try:
            if isinstance(message, str):
                message = json.loads(message)
            cmd = message.get("cmd")
            if cmd == "play":
                return self.play(message.get("path"), message.get("track_id"))
            if cmd == "pause":
                return self.pause()
            if cmd == "resume":
                return self.resume()
            if cmd == "stop":
                return self.stop()
            if cmd == "seek":
                return self.seek(float(message.get("pos", 0)))
            if cmd == "ping":
                return self.status()
        except Exception as e:
            _log(f"message error: {e}")
        return {"error": "unknown command"}

    # ---- Плеер ----------------------------------------------------------
    def play(self, path, track_id=None):
        self.stop()
        if not path or not os.path.exists(path):
            return {"error": "file not found"}
        from kivy.core.audio import SoundLoader  # импорт внутри процесса службы
        self.sound = SoundLoader.load(path)
        if not self.sound:
            return {"error": "cannot load"}
        self.track_id = track_id
        self.sound.bind(on_stop=self._on_sound_stop)
        self.sound.play()
        self.state = "play"
        self._log(f"playing {os.path.basename(path)}")
        return self.status()

    def pause(self):
        if self.sound and self.state == "play":
            self._paused_pos = self.get_pos()
            self.sound.stop()  # SDL sound без нативного pause -> stop + запоминание позиции
            self.state = "pause"
        return self.status()

    def resume(self):
        if self.sound and self.state == "pause":
            self.sound.play()
            try:
                self.sound.seek(self._paused_pos)
            except Exception:
                pass
            self.state = "play"
        return self.status()

    def stop(self):
        if self.sound:
            try:
                self.sound.unbind(on_stop=self._on_sound_stop)
                self.sound.stop()
                self.sound.unload()
            except Exception:
                pass
            self.sound = None
        self.state = "stop"
        self.track_id = None
        return self.status()

    def seek(self, pos):
        if self.sound:
            try:
                self.sound.seek(pos)
            except Exception:
                pass
        return self.status()

    def get_pos(self):
        try:
            return self.sound.get_pos() or 0
        except Exception:
            return 0

    def status(self):
        return {"state": self.state, "pos": self.get_pos(),
                "track_id": self.track_id, "duration": self.duration}

    def _on_sound_stop(self, *_):
        # трек доиграл естественно — авто-next можно реализовать,
        # читая очередь из общей SQLite БД (DB_FILE)
        self.state = "stop"


# --- Точка входа p4a service (загружается android.service.AndroidService) ---
try:
    from android import service as _service

    class _P4AService(_service.AndroidServiceToken):
        def on_start(self, *args):
            self.player = MusicService()
            self.player.on_start()

        def on_message(self, message):
            return self.player.on_message(message)

        def on_stop(self):
            self.player.on_stop()

except ImportError:
    # Desktop/тест: просто инстанцируем движок
    _P4AService = MusicService
