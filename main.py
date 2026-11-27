import os
import sqlite3
import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.utils import platform

# === ЛОГИРОВАНИЕ ===
import sys
import traceback

def get_app_dir():
    if platform == "android":
        try:
            from jnius import autoclass
            Environment = autoclass("android.os.Environment")
            base = Path(Environment.getExternalStorageDirectory().getAbsolutePath())
        except Exception:
            base = Path("/data/data/org.davyur.ytmus/files")
    else:
        base = Path.home()
    
    app_dir = base / ".music_app"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

APP_DIR = get_app_dir()
LOG_FILE = str(APP_DIR / "crash.log")

def log_exception(exc_type, exc_value, exc_traceback):
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("=== CRASH LOG ===\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = log_exception
# =================

print("=== YTmus START ===")
print(f"Platform: {platform}")
print(f"APP_DIR: {APP_DIR}")

DB_FILE = str(APP_DIR / "music_app.db")


def get_music_directory():
    if platform == "android":
        try:
            from plyer import storagepath
            path = storagepath.get_music_dir()
            if path and os.path.exists(path):
                print(f"Music dir (plyer): {path}")
                return path
        except Exception as e:
            print(f"plyer error: {e}")
        return "/storage/emulated/0/Music"
    fallback = Path.home() / "Music"
    if fallback.exists():
        return str(fallback)
    return str(Path.cwd())


def db():
    con = sqlite3.connect(DB_FILE, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    print("init_db called")
    con = db()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE, title TEXT,
        artist TEXT, album TEXT, genre TEXT, duration REAL DEFAULT 0,
        favorite INTEGER DEFAULT 0)""")
    con.commit()
    con.close()
    print("init_db done")


def scan_music_folder(root_dir):
    print(f"Scanning: {root_dir}")
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
                        print(f"Error: {e}")
        con.commit()
        con.close()
    print(f"Scan done: {count} tracks")
    return count


class MusicApp(App):
    def build(self):
        print("build() called")
        self.title = "YTmus"
        
        init_db()
        
        layout = BoxLayout(orientation="vertical", padding=20, spacing=20)
        
        self.status_label = Label(
            text="YTmus - Тест БД",
            font_size="24sp",
            color=(1, 1, 1, 1)
        )
        layout.add_widget(self.status_label)
        
        self.count_label = Label(
            text="Загрузка...",
            font_size="18sp",
            color=(0.7, 0.7, 0.7, 1)
        )
        layout.add_widget(self.count_label)
        
        print("build() done, scheduling scan")
        Clock.schedule_once(lambda dt: self.start_scan(), 1.0)
        
        return layout
    
    def start_scan(self):
        print("start_scan called")
        music_dir = get_music_directory()
        self.status_label.text = f"Сканирование: {music_dir}"
        threading.Thread(target=self._scan_thread, args=(music_dir,), daemon=True).start()
    
    def _scan_thread(self, music_dir):
        count = scan_music_folder(music_dir)
        Clock.schedule_once(lambda dt: self._update_ui(count), 0)
    
    def _update_ui(self, count):
        print(f"_update_ui: {count}")
        self.status_label.text = "Готово!"
        self.count_label.text = f"Треков найдено: {count}"


if __name__ == "__main__":
    print("Starting MusicApp...")
    MusicApp().run()
