from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton
import sqlite3
import os
import hashlib
import threading
import traceback
from kivy.clock import Clock
from kivy.utils import platform

# ---------------------------------------------------------------------------
# Пути и константы
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".wma"}
ERROR_LOG = "/data/data/org.davyur.ytmus/files/error.log"


# ---------------------------------------------------------------------------
# Получение путей через Android API
# ---------------------------------------------------------------------------
def get_app_dirs():
    if platform != "android":
        home = os.path.expanduser("~")
        return (
            os.path.join(home, ".ytmus", "ytmus.db"),
            os.path.join(home, ".ytmus", "YTmus"),
        )

    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Environment = autoclass("android.os.Environment")
        activity = PythonActivity.mActivity

        internal_dir = activity.getFilesDir().getAbsolutePath()

        # App-specific папка Music (не требует разрешений на запись)
        external_music = activity.getExternalFilesDir(Environment.DIRECTORY_MUSIC)
        external_dir = external_music.getAbsolutePath() if external_music else internal_dir

        dst = os.path.join(external_dir, "YTmus")
        db = os.path.join(internal_dir, "ytmus.db")
        print(f"DB: {db}\nDST: {dst}")
        return db, dst
    except Exception as e:
        print(f"get_app_dirs error: {e}")
        return (
            "/data/data/org.davyur.ytmus/files/ytmus.db",
            "/data/data/org.davyur.ytmus/files/YTmus",
        )


# ---------------------------------------------------------------------------
# Разрешения
# ---------------------------------------------------------------------------
def request_perms():
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
            request_permissions(perms)
    except Exception as e:
        print(f"request_perms error: {e}")


def check_perms_status():
    if platform != "android":
        return {"audio": True, "notif": True}
    try:
        from android.permissions import check_permission, Permission
        return {
            "audio": check_permission(Permission.READ_MEDIA_AUDIO),
            "notif": check_permission(Permission.POST_NOTIFICATIONS),
        }
    except Exception:
        return {"audio": False, "notif": False}


# ---------------------------------------------------------------------------
# Чтение файлов — ДВА способа
# ---------------------------------------------------------------------------
def read_file_by_path(path):
    """Быстрое чтение через обычный open()."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"read_file_by_path error {path}: {e}")
        return None


def read_file_by_uri(uri_obj):
    """Медленное чтение через ContentResolver (fallback)."""
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        BufferedInputStream = autoclass("java.io.BufferedInputStream")
        ByteArrayOutputStream = autoclass("java.io.ByteArrayOutputStream")
        activity = PythonActivity.mActivity
        resolver = activity.getContentResolver()

        is_stream = resolver.openInputStream(uri_obj)
        if is_stream is None:
            return None

        bis = BufferedInputStream(is_stream)
        baos = ByteArrayOutputStream()

        # Побайтовое чтение — медленно, но надёжно в pyjnius
        while True:
            b = bis.read()
            if b == -1:
                break
            baos.write(b)

        bis.close()
        baos.close()
        return bytes(baos.toByteArray())
    except Exception as e:
        print(f"read_file_by_uri error: {e}")
        return None


# ---------------------------------------------------------------------------
# БД
# ---------------------------------------------------------------------------
def init_db(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE,
        title TEXT,
        ext TEXT,
        size INTEGER,
        md5 TEXT,
        source TEXT
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


# ---------------------------------------------------------------------------
# Сканирование через MediaStore
# ---------------------------------------------------------------------------
def scan_via_mediastore():
    """
    Возвращает список кортежей: (readable_path_or_None, uri_obj_or_None, name, ext)
    Приоритет — _data (прямой путь). Fallback — URI.
    """
    if platform != "android":
        return []
    try:
        from jnius import autoclass
        MediaStore = autoclass("android.provider.MediaStore")
        ContentUris = autoclass("android.content.ContentUris")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity

        projection = [
            MediaStore.Audio.Media._ID,
            MediaStore.Audio.Media.DISPLAY_NAME,
            MediaStore.Audio.Media.SIZE,
            MediaStore.Audio.Media.DATA,  # прямой путь к файлу
        ]

        cursor = activity.getContentResolver().query(
            MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
            projection, None, None, None
        )

        files = []
        if cursor:
            print(f"MediaStore вернул {cursor.getCount()} записей")
            while cursor.moveToNext():
                try:
                    file_id = cursor.getLong(0)
                    name = cursor.getString(1)
                    size = cursor.getLong(2)
                    data_path = cursor.getString(3)  # может быть None

                    if not name:
                        continue

                    ext = os.path.splitext(name)[1].lower()
                    if ext not in SUPPORTED_EXTENSIONS:
                        continue

                    # Строим правильный URI через ContentUris
                    uri_obj = ContentUris.withAppendedId(
                        MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
                        file_id
                    )

                    # Проверяем, существует ли прямой путь
                    if data_path and os.path.exists(data_path):
                        files.append((data_path, None, name, ext))
                    else:
                        files.append((None, uri_obj, name, ext))
                except Exception as e:
                    print(f"cursor row error: {e}")
                    continue
            cursor.close()
        return files
    except Exception as e:
        print(f"MediaStore scan error: {e}")
        traceback.print_exc()
        return []


def scan_and_collect(db_path, dst_dir, progress_cb):
    init_db(db_path)

    # Создаём папку и проверяем запись
    os.makedirs(dst_dir, exist_ok=True)
    test_file = os.path.join(dst_dir, ".test_write")
    with open(test_file, "w") as f:
        f.write("ok")
    os.remove(test_file)
    print(f"Папка готова к записи: {dst_dir}")

    # Сканируем
    all_files = scan_via_mediastore()
    progress_cb(("scanned", len(all_files)))

    if not all_files:
        return {"copied": 0, "dupes": 0, "errors": 0}

    # Дедупликация по md5
    seen_hashes = set()
    copied = 0
    skipped_dupes = 0
    errors = 0

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    for data_path, uri_obj, name, ext in all_files:
        # Читаем файл — сначала по пути, потом по URI
        data = None
        if data_path:
            data = read_file_by_path(data_path)
        if data is None and uri_obj is not None:
            data = read_file_by_uri(uri_obj)

        if data is None:
            errors += 1
            continue

        h = hashlib.md5(data).hexdigest()
        size = len(data)

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
            with open(target, "wb") as f:
                f.write(data)
            source = data_path if data_path else str(uri_obj)
            c.execute(
                "INSERT INTO tracks(path, title, ext, size, md5, source) VALUES (?,?,?,?,?,?)",
                (target, os.path.splitext(name)[0], ext, size, h, source)
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
            text: "Найдено: -"
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

        MDLabel:
            id: path_label
            text: "Папка: ..."
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
                text: "Ошибка"
                on_release: app.show_error()
            MDFlatButton:
                text: "Список"
                on_release: app.show_list()
"""


class MusicApp(MDApp):
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        self.db_path, self.dst_dir = get_app_dirs()
        init_db(self.db_path)
        return Builder.load_string(KV)

    def on_start(self):
        Clock.schedule_once(lambda dt: request_perms(), 0.5)
        Clock.schedule_once(lambda dt: self.update_perms_label(), 1.5)
        Clock.schedule_once(
            lambda dt: setattr(self.root.ids.path_label, "text",
                               f"Папка: {self.dst_dir}"), 2.0
        )

    def update_perms_label(self):
        status = check_perms_status()
        audio = "OK" if status.get("audio") else "НЕТ"
        notif = "OK" if status.get("notif") else "НЕТ"
        self.root.ids.perms_label.text = f"Аудио: {audio} | Увед: {notif}"

    def start_scan(self):
        self.root.ids.status_label.text = "Сканирование..."
        self.root.ids.found_label.text = "Найдено: ..."
        self.root.ids.copied_label.text = "Скопировано: ..."

        # ИСПРАВЛЕНО: progress принимает кортеж одним аргументом
        def progress(args):
            kind, n = args
            def upd(_):
                if kind == "scanned":
                    self.root.ids.found_label.text = f"Найдено: {n}"
                elif kind == "copied":
                    self.root.ids.copied_label.text = f"Скопировано: {n}"
            Clock.schedule_once(upd, 0)

        def worker():
            try:
                stats = scan_and_collect(self.db_path, self.dst_dir, progress)
                Clock.schedule_once(lambda dt: self._done(stats), 0)
            except Exception:
                err = traceback.format_exc()
                try:
                    with open(ERROR_LOG, "w", encoding="utf-8") as f:
                        f.write(err)
                except Exception:
                    pass
                print(err)
                Clock.schedule_once(lambda dt: self._fail(err), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, stats):
        self.root.ids.status_label.text = (
            f"Готово! Скопировано: {stats['copied']}, "
            f"дубликатов: {stats['dupes']}, ошибок: {stats['errors']}"
        )

    def _fail(self, err):
        self.root.ids.status_label.text = "ОШИБКА! Нажми 'Ошибка'"
        self._last_error = err

    def show_error(self):
        err = getattr(self, "_last_error", None)
        if not err:
            try:
                with open(ERROR_LOG, "r", encoding="utf-8") as f:
                    err = f.read()
            except Exception:
                err = "Ошибок нет"

        if getattr(self, "_err_dialog", None):
            self._err_dialog.dismiss()
        self._err_dialog = MDDialog(
            title="Трассировка ошибки",
            text=err[-1500:],
            buttons=[
                MDFlatButton(
                    text="Закрыть",
                    on_release=lambda _: self._err_dialog.dismiss()
                ),
            ],
        )
        self._err_dialog.open()

    def show_list(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT title, ext FROM tracks ORDER BY title LIMIT 15")
        rows = c.fetchall()
        conn.close()
        items = [f"{r[0]}{r[1]}" for r in rows]
        self.root.ids.status_label.text = (
            "Треки: " + " | ".join(items) if items else "База пуста"
        )


if __name__ == "__main__":
    MusicApp().run()
