from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton
import sqlite3
import os
import shutil
import hashlib
import threading
from kivy.clock import Clock
from kivy.utils import platform

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
DB_PATH = "/data/data/org.davyur.ytmus/files/ytmus.db"
# App-specific папка — НЕ требует разрешений на запись!
APP_SPECIFIC_DIR = "/storage/emulated/0/Android/data/org.davyur.ytmus/files/YTmus"
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".wma"}


# ---------------------------------------------------------------------------
# Разрешения (правильный способ через android.permissions)
# ---------------------------------------------------------------------------
def request_perms():
    """Запрашивает разрешения через python-for-android API."""
    if platform != "android":
        return
    try:
        from android.permissions import request_permissions, Permission, check_permission
        perms = []
        if not check_permission(Permission.READ_MEDIA_AUDIO):
            perms.append(Permission.READ_MEDIA_AUDIO)
        if not check_permission(Permission.POST_NOTIFICATIONS):
            perms.append(Permission.POST_NOTIFICATIONS)
        if perms:
            print(f"Запрашиваем разрешения: {perms}")
            request_permissions(perms)
    except ImportError:
        print("android.permissions не доступен")
    except Exception as e:
        print(f"request_perms error: {e}")


def check_perms_status():
    """Проверяет статус разрешений."""
    if platform != "android":
        return {"audio": True, "notif": True}
    try:
        from android.permissions import check_permission, Permission
        return {
            "audio": check_permission(Permission.READ_MEDIA_AUDIO),
            "notif": check_permission(Permission.POST_NOTIFICATIONS),
        }
    except Exception as e:
        print(f"check_perms error: {e}")
        return {"audio": False, "notif": False}


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------
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
    except Exception as e:
        print(f"hash error {path}: {e}")
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
    base, ext = os.path.splitext(name)
    candidate = os.path.join(dst_dir, name)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dst_dir, f"{base}({i}){ext}")
        i += 1
    return candidate


def ensure_dst():
    """Создаёт app-specific папку (не требует разрешений)."""
    try:
        os.makedirs(APP_SPECIFIC_DIR, exist_ok=True)
        test = os.path.join(APP_SPECIFIC_DIR, ".writetest")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return APP_SPECIFIC_DIR
    except Exception as e:
        print(f"ensure_dst error: {e}")
        return None


# ---------------------------------------------------------------------------
# Сканирование через MediaStore
# ---------------------------------------------------------------------------
def scan_via_mediastore():
    """Сканирует все аудиофайлы через MediaStore."""
    if platform != "android":
        return []
    try:
        from jnius import autoclass
        MediaStore = autoclass("android.provider.MediaStore")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity

        # Используем правильные колонки
        projection = [
            MediaStore.Audio.Media._ID,
            MediaStore.Audio.Media.DISPLAY_NAME,
            MediaStore.Audio.Media.SIZE,
        ]

        cursor = activity.getContentResolver().query(
            MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
            projection,
            None, None, None
        )

        files = []
        if cursor:
            count = cursor.getCount()
            print(f"MediaStore вернул {count} записей")
            while cursor.moveToNext():
                try:
                    id_idx = cursor.getColumnIndex(MediaStore.Audio.Media._ID)
                    name_idx = cursor.getColumnIndex(MediaStore.Audio.Media.DISPLAY_NAME)
                    size_idx = cursor.getColumnIndex(MediaStore.Audio.Media.SIZE)

                    file_id = cursor.getLong(id_idx)
                    name = cursor.getString(name_idx)
                    size = cursor.getLong(size_idx)

                    if not name:
                        continue

                    ext = os.path.splitext(name)[1].lower()
                    if ext not in SUPPORTED_EXTENSIONS:
                        continue

                    # Строим URI для файла
                    uri = f"content://media/external/audio/media/{file_id}"
                    files.append((uri, name, size, ext))
                except Exception as e:
                    print(f"cursor error: {e}")
                    continue
            cursor.close()
        return files
    except Exception as e:
        print(f"MediaStore scan error: {e}")
        import traceback
        traceback.print_exc()
        return []


def read_file_from_uri(uri_str):
    """Читает файл через ContentResolver по URI."""
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Uri = autoclass("android.net.Uri")
        activity = PythonActivity.mActivity
        resolver = activity.getContentResolver()

        uri = Uri.parse(uri_str)
        is_stream = resolver.openInputStream(uri)
        if is_stream is None:
            return None

        # Читаем через буфер
        data = bytearray()
        buf = bytes(65536)
        while True:
            n = is_stream.read(buf)
            if n <= 0:
                break
            data.extend(buf[:n])
        is_stream.close()
        return bytes(data)
    except Exception as e:
        print(f"read uri error: {e}")
        return None


def copy_file_to_dst(src_uri, dst_name, dst_dir):
    """Копирует файл из MediaStore в app-specific папку."""
    try:
        data = read_file_from_uri(src_uri)
        if data is None:
            return False

        target = safe_target(dst_dir, dst_name)
        with open(target, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"copy error: {e}")
        return False


def scan_and_collect(dst_dir, progress_cb):
    init_db()

    # 1. Сканируем
    all_files = scan_via_mediastore()
    progress_cb(("scanned", len(all_files)))

    if not all_files:
        return {"copied": 0, "dupes": 0, "errors": 0}

    # 2. Группируем по размеру
    by_size = {}
    for uri, name, size, ext in all_files:
        by_size.setdefault(size, []).append((uri, name, ext))

    # 3. Дедупликация и копирование
    seen_hashes = set()
    copied = 0
    skipped_dupes = 0
    errors = 0

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for size, group in by_size.items():
        for uri, name, ext in group:
            # Читаем данные для хеша
            data = read_file_from_uri(uri)
            if data is None:
                errors += 1
                continue

            h = hashlib.md5(data).hexdigest()

            if h in seen_hashes:
                skipped_dupes += 1
                continue
            seen_hashes.add(h)

            c.execute("SELECT 1 FROM tracks WHERE md5=?", (h,))
            if c.fetchone():
                skipped_dupes += 1
                continue

            # Сохраняем в dst_dir
            target = safe_target(dst_dir, name)
            try:
                with open(target, "wb") as f:
                    f.write(data)
                c.execute(
                    "INSERT INTO tracks(path, title, ext, size, md5, orig_path) VALUES (?,?,?,?,?,?)",
                    (target, os.path.splitext(name)[0], ext, size, h, uri)
                )
                copied += 1
                progress_cb(("copied", copied))
            except Exception as e:
                print(f"save error: {e}")
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
            text: "Дубликатов: -"
            halign: "center"
            theme_text_color: "Hint"

        MDLabel:
            id: perms_label
            text: "Права: ..."
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
                text: "Права"
                on_release: app.check_perms()
            MDFlatButton:
                text: "Список"
                on_release: app.show_list()
"""


class MusicApp(MDApp):
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        init_db()
        return Builder.load_string(KV)

    def on_start(self):
        # Запрашиваем разрешения через 0.5 сек после старта
        Clock.schedule_once(lambda dt: request_perms(), 0.5)
        Clock.schedule_once(lambda dt: self.update_perms_label(), 1.5)

    def update_perms_label(self):
        status = check_perms_status()
        audio = "OK" if status.get("audio") else "НЕТ"
        notif = "OK" if status.get("notif") else "НЕТ"
        self.root.ids.perms_label.text = f"Аудио: {audio} | Уведомления: {notif}"

    def check_perms(self):
        self.update_perms_label()
        # Повторно запрашиваем если нет
        request_perms()

    def start_scan(self):
        dst = ensure_dst()
        if dst is None:
            self.root.ids.status_label.text = "НЕТ ПРАВ на запись!"
            return

        self.root.ids.status_label.text = "Сканирование..."
        self.root.ids.found_label.text = "Найдено: ..."
        self.root.ids.copied_label.text = "Скопировано: ..."

        def progress(kind, n):
            def upd(_):
                if kind == "scanned":
                    self.root.ids.found_label.text = f"Найдено: {n}"
                elif kind == "copied":
                    self.root.ids.copied_label.text = f"Скопировано: {n}"
            Clock.schedule_once(upd, 0)

        def worker():
            try:
                stats = scan_and_collect(dst, progress)
                Clock.schedule_once(lambda dt: self._done(stats), 0)
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                print(err)
                Clock.schedule_once(lambda dt: self._fail(err), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, stats):
        self.root.ids.status_label.text = "Готово!"
        self.root.ids.dupes_label.text = (
            f"Дубликатов: {stats['dupes']}, ошибок: {stats['errors']}"
        )

    def _fail(self, e):
        self.root.ids.status_label.text = f"ОШИБКА: {str(e)[:100]}"

    def show_list(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT title, ext FROM tracks ORDER BY title LIMIT 10")
        rows = c.fetchall()
        conn.close()
        items = [f"{r[0]}{r[1]}" for r in rows]
        self.root.ids.status_label.text = (
            "Треки: " + ", ".join(items) if items else "База пуста"
        )


if __name__ == "__main__":
    MusicApp().run()
