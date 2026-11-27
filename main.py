import os
import sqlite3
import threading
from pathlib import Path

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.label import Label
from kivy.utils import platform

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.toolbar import MDTopAppBar

# === АВТОМАТИЧЕСКОЕ ЛОГИРОВАНИЕ ОШИБОК ===
import sys
import traceback

LOG_DIR = Path.home() / ".music_app"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = str(LOG_DIR / "crash.log")

def log_exception(exc_type, exc_value, exc_traceback):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("=== CRASH LOG ===\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = log_exception
# ==========================================

# ---------------------------------------------------------------------------
# Конфигурация / хранилище
# ---------------------------------------------------------------------------

APP_DIR = Path.home() / ".music_app"
if platform == "android":
    try:
        from jnius import autoclass
        Environment = autoclass("android.os.Environment")
        APP_DIR = Path(Environment.getExternalStorageDirectory().getAbsolutePath()) / "MusicApp"
    except Exception:
        pass
APP_DIR.mkdir(parents=True, exist_ok=True)

DB_FILE = str(APP_DIR / "music_app.db")


def get_music_directory():
    """Каталог с музыкой."""
    # Для теста используем ~/Music или текущую директорию
    fallback = Path.home() / "Music"
    if fallback.exists():
        return str(fallback)
    return str(Path.cwd())


def db():
    con = sqlite3.connect(DB_FILE, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE, title TEXT,
        artist TEXT, album TEXT, genre TEXT, duration REAL DEFAULT 0,
        favorite INTEGER DEFAULT 0)""")
    con.commit()
    con.close()


def scan_music_folder(root_dir):
    """Сканирование папки с музыкой."""
    count = 0
    if os.path.exists(root_dir):
        con = db()
        cur = con.cursor()
        for root, _, files in os.walk(root_dir):
            for file in files:
                if file.lower().endswith(".mp3"):
                    path = os.path.join(root, file)
                    title = os.path.splitext(file)[0]
                    try:
                        cur.execute(
                            "INSERT OR IGNORE INTO tracks(path, title) VALUES (?, ?)",
                            (path, title)
                        )
                        count += 1
                    except Exception as e:
                        print(f"Error adding {path}: {e}")
        con.commit()
        con.close()
    return count


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

class MusicApp(MDApp):
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        
        # Инициализация БД
        init_db()
        
        # UI
        screen = MDScreen()
        layout = MDBoxLayout(orientation="vertical")
        
        layout.add_widget(MDTopAppBar(title="YTmus - Тест БД"))
        
        self.status_label = MDLabel(
            text="Инициализация...",
            halign="center",
            theme_text_color="Primary"
        )
        layout.add_widget(self.status_label)
        
        self.count_label = MDLabel(
            text="Треков найдено: 0",
            halign="center",
            theme_text_color="Secondary"
        )
        layout.add_widget(self.count_label)
        
        screen.add_widget(layout)
        
        # Запуск сканирования через 1 секунду
        Clock.schedule_once(lambda dt: self.start_scan(), 1.0)
        
        return screen
    
    def start_scan(self):
        music_dir = get_music_directory()
        self.status_label.text = f"Сканирование: {music_dir}"
        
        # Сканирование в отдельном потоке
        threading.Thread(target=self._scan_thread, args=(music_dir,), daemon=True).start()
    
    def _scan_thread(self, music_dir):
        count = scan_music_folder(music_dir)
        # Обновление UI в главном потоке
        Clock.schedule_once(lambda dt: self._update_ui(count), 0)
    
    def _update_ui(self, count):
        self.status_label.text = "Сканирование завершено!"
        self.count_label.text = f"Треков найдено: {count}"


if __name__ == "__main__":
    MusicApp().run()
