from kivy.lang import Builder
from kivymd.app import MDApp
import sqlite3
import os
import shutil
import hashlib
import threading
from kivy.clock import Clock

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
DB_PATH = "/data/data/org.davyur.ytmus/files/ytmus.db"
MUSIC_SRC = "/storage/emulated/0/Music"
MUSIC_DST = "/storage/emulated/0/YTmus"
MUSIC_DST_FALLBACK = "/storage/emulated/0/Android/data/org.davyur.ytmus/files/YTmus"

# Поддерживаемые форматы (все в нижнем регистре)
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".wma"}


def ensure_dst():
    for p in (MUSIC_DST, MUSIC_DST_FALLBACK):
        try:
            os.makedirs(p, exist_ok=True)
            test = os.path.join(p, ".writetest")
            with open(test, "w") as f:
                f.write("ok")
            os.remove(test)
            return p
        except Exception:
            continue
    return None


def file_hash(path, chunk=1024 * 1024):
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except Exception:
        return None


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE,
        title TEXT,
        ext TEXT,
        size INTEGER,
        md5 TEXT,
        orig_path TEXT
    )""")
    conn.commit()
    conn.close()


def safe_target(dst_dir, name):
    """Возвращает путь с суффиксом (1), (2)... если имя занято."""
    base, ext = os.path.splitext(name)
    candidate = os.path.join(dst_dir, name)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dst_dir, f"{base}({i}){ext}")
        i += 1
    return candidate


def scan_and_collect(dst_dir, progress_cb):
    init_db()

    # 1. Собираем все аудиофайлы рекурсивно
    all_files = []
    for root, dirs, files in os.walk(MUSIC_SRC):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                full = os.path.join(root, f)
                try:
                    size = os.path.getsize(full)
                except Exception:
                    continue
                all_files.append((full, f, size, ext))

    progress_cb(("scanned", len(all_files)))

    # 2. Группируем по размеру
    by_size = {}
    for path, name, size, ext in all_files:
        by_size.setdefault(size, []).append((path, name, ext))

    # 3. Дедупликация по md5
    seen_hashes = set()
    copied = 0
    skipped_dupes = 0
    errors = 0

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for size, group in by_size.items():
        for path, name, ext in group:
            h = file_hash(path)
            if h is None:
                errors += 1
                continue

            if h in seen_hashes:
                skipped_dupes += 1
                continue
            seen_hashes.add(h)

            c.execute("SELECT 1 FROM tracks WHERE md5=?", (h,))
            if c.fetchone():
                skipped_dupes += 1
                continue

            target = safe_target(dst_dir, name)
            try:
                shutil.copy2(path, target)
                c.execute(
                    "INSERT INTO tracks(path, title, ext, size, md5, orig_path) VALUES (?,?,?,?,?,?)",
                    (target, os.path.splitext(name)[0], ext, size, h, path)
                )
                copied += 1
                progress_cb(("copied", copied))
            except Exception:
                errors += 1

    conn.commit()
    conn.close()
    return {"copied": copied, "dupes": skipped_dupes, "errors": errors}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
KV = """
MDScreen:
    MDBoxLayout:
        orientation: "vertical"
        padding: dp(8)
        spacing: dp(8)

        MDTopAppBar:
            title: "YTmus - Сканер"

        MDLabel:
            id: status_label
            text: "Готов"
            halign: "center"
            theme_text_color: "Primary"

        MDLabel:
            id: found_label
            text: "Найдено файлов: -"
            halign: "center"
            theme_text_color: "Secondary"

        MDLabel:
            id: copied_label
            text: "Скопировано: -"
            halign: "center"
            theme_text_color: "Secondary"

        MDLabel:
            id: dupes_label
            text: "Дубликатов пропущено: -"
            halign: "center"
            theme_text_color: "Hint"

        MDLabel:
            id: formats_label
            text: "Форматы: mp3, m4a, flac, wav, ogg, aac, wma"
            halign: "center"
            theme_text_color: "Hint"
            font_style: "Caption"

        MDLabel:
            id: dst_label
            text: "Папка: -"
            halign: "center"
            theme_text_color: "Hint"
            font_style: "Caption"

        MDBoxLayout:
            orientation: "horizontal"
            spacing: dp(8)
            MDRaisedButton:
                text: "Сканировать"
                on_release: app.start_scan()
            MDFlatButton:
                text: "Показать список"
                on_release: app.show_list()
"""


class MusicApp(MDApp):
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        init_db()
        return Builder.load_string(KV)

    def start_scan(self):
        dst = ensure_dst()
        if dst is None:
            self.root.ids.status_label.text = "НЕТ ПРАВ на создание папки!"
            return
        self.root.ids.dst_label.text = f"Папка: {dst}"
        self.root.ids.status_label.text = "Сканирование..."
        self.root.ids.found_label.text = "Найдено файлов: ..."
        self.root.ids.copied_label.text = "Скопировано: ..."

        def progress(kind, n):
            def upd(_):
                if kind == "scanned":
                    self.root.ids.found_label.text = f"Найдено файлов: {n}"
                elif kind == "copied":
                    self.root.ids.copied_label.text = f"Скопировано: {n}"
            Clock.schedule_once(upd, 0)

        def worker():
            try:
                stats = scan_and_collect(dst, progress)
                Clock.schedule_once(lambda dt: self._done(stats), 0)
            except Exception as e:
                Clock.schedule_once(lambda dt: self._fail(e), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, stats):
        self.root.ids.status_label.text = "Готово!"
        self.root.ids.dupes_label.text = (
            f"Дубликатов пропущено: {stats['dupes']}, ошибок: {stats['errors']}"
        )

    def _fail(self, e):
        self.root.ids.status_label.text = f"ОШИБКА: {e}"

    def show_list(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT title, ext FROM tracks ORDER BY title LIMIT 10")
        rows = c.fetchall()
        conn.close()
        items = [f"{r[0]}{r[1]}" for r in rows]
        self.root.ids.status_label.text = "Треки: " + ", ".join(items)


if __name__ == "__main__":
    MusicApp().run()
