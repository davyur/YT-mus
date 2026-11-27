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
RELATIVE_MUSIC_PATH = "Music/YTmus"  # куда пишет MediaStore
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".wma"}

MIME_MAP = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".wav": "audio/x-wav",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
}


# ---------------------------------------------------------------------------
# Разрешения (runtime)
# ---------------------------------------------------------------------------
def request_runtime_permissions():
    """Запрашивает READ_MEDIA_AUDIO + POST_NOTIFICATIONS на Android 13+."""
    if platform != "android":
        return
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        Build = autoclass("android.os.Build")
        PackageManager = autoclass("android.content.pm.PackageManager")

        if Build.VERSION.SDK_INT >= 33:
            perms = [
                "android.permission.READ_MEDIA_AUDIO",
                "android.permission.POST_NOTIFICATIONS",
            ]
        else:
            perms = [
                "android.permission.READ_EXTERNAL_STORAGE",
                "android.permission.WRITE_EXTERNAL_STORAGE",
            ]

        to_request = []
        for p in perms:
            if activity.checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED:
                to_request.append(p)

        if to_request:
            activity.requestPermissions(to_request, 1)
            print(f"Запрошены разрешения: {to_request}")
    except Exception as e:
        print(f"request_permissions error: {e}")


def check_all_files_access():
    """Проверяет MANAGE_EXTERNAL_STORAGE (для fallback-копирования)."""
    if platform != "android":
        return True
    try:
        from jnius import autoclass
        Environment = autoclass("android.os.Environment")
        return Environment.isExternalStorageManager()
    except Exception:
        return False


def open_all_files_settings():
    """Открывает системные настройки 'Управление всем хранилищем'."""
    if platform != "android":
        return
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        Uri = autoclass("android.net.Uri")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity

        intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
        intent.setData(Uri.parse("package:org.davyur.ytmus"))
        activity.startActivity(intent)
    except Exception as e:
        print(f"open_settings error: {e}")


# ---------------------------------------------------------------------------
# MediaStore: копирование файлов
# ---------------------------------------------------------------------------
def copy_via_mediastore(src_path, dst_name):
    """
    Копирует файл в Music/YTmus через MediaStore.
    Работает на Android 10+ без MANAGE_EXTERNAL_STORAGE.
    Возвращает uri (строку) или None при ошибке.
    """
    if platform != "android":
        # На десктопе — просто shutil
        dst_dir = os.path.expanduser("~/Music/YTmus")
        os.makedirs(dst_dir, exist_ok=True)
        target = safe_target(dst_dir, dst_name)
        shutil.copy2(src_path, target)
        return target

    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        MediaStore = autoclass("android.provider.MediaStore")
        ContentValues = autoclass("android.content.ContentValues")

        activity = PythonActivity.mActivity
        resolver = activity.getContentResolver()

        ext = os.path.splitext(dst_name)[1].lower()
        mime = MIME_MAP.get(ext, "audio/*")

        values = ContentValues()
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, dst_name)
        values.put(MediaStore.MediaColumns.MIME_TYPE, mime)
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, RELATIVE_MUSIC_PATH)
        values.put(MediaStore.MediaColumns.IS_PENDING, 1)

        uri = resolver.insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            return None

        # Пишем данные через OutputStream
        with open(src_path, "rb") as f:
            data = f.read()

        os_stream = resolver.openOutputStream(uri)
        if os_stream is None:
            return None

        # pyjnius конвертирует python bytes в Java byte[]
        os_stream.write(data)
        os_stream.flush()
        os_stream.close()

        # Снимаем pending
        values.clear()
        values.put(MediaStore.MediaColumns.IS_PENDING, 0)
        resolver.update(uri, values, None, None)

        return uri.toString()
    except Exception as e:
        print(f"mediastore copy error: {e}")
        return None


def delete_via_mediastore(uri_str):
    """Удаляет файл через MediaStore (для отката при ошибке)."""
    if platform != "android" or not uri_str:
        return
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Uri = autoclass("android.net.Uri")
        activity = PythonActivity.mActivity
        resolver = activity.getContentResolver()
        resolver.delete(Uri.parse(uri_str), None, None)
    except Exception:
        pass


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
    base, ext = os.path.splitext(name)
    candidate = os.path.join(dst_dir, name)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dst_dir, f"{base}({i}){ext}")
        i += 1
    return candidate


def scan_via_mediastore():
    """Сканирует все аудиофайлы через MediaStore."""
    if platform != "android":
        return []
    try:
        from jnius import autoclass
        MediaStore = autoclass("android.provider.MediaStore")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity

        cursor = activity.getContentResolver().query(
            MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
            None, None, None, None
        )
        files = []
        if cursor:
            while cursor.moveToNext():
                path_idx = cursor.getColumnIndex(MediaStore.Audio.Media.DATA)
                title_idx = cursor.getColumnIndex(MediaStore.Audio.Media.DISPLAY_NAME)
                size_idx = cursor.getColumnIndex(MediaStore.Audio.Media.SIZE)
                path = cursor.getString(path_idx)
                title = cursor.getString(title_idx)
                size = cursor.getLong(size_idx)
                if path and title:
                    ext = os.path.splitext(path)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        # Не копируем файлы, которые уже в YTmus
                        if RELATIVE_MUSIC_PATH not in path:
                            files.append((path, title, size, ext))
            cursor.close()
        return files
    except Exception as e:
        print(f"MediaStore scan error: {e}")
        return []


def scan_and_collect(progress_cb):
    init_db()
    all_files = scan_via_mediastore()
    progress_cb(("scanned", len(all_files)))
    if not all_files:
        return {"copied": 0, "dupes": 0, "errors": 0}

    by_size = {}
    for path, name, size, ext in all_files:
        by_size.setdefault(size, []).append((path, name, ext))

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

            uri = copy_via_mediastore(path, name)
            if uri is None:
                errors += 1
                continue

            c.execute(
                "INSERT INTO tracks(path, title, ext, size, md5, orig_path) VALUES (?,?,?,?,?,?)",
                (uri, os.path.splitext(name)[0], ext, size, h, path)
            )
            copied += 1
            progress_cb(("copied", copied))

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
            text: "Права: проверка..."
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
        # Запрашиваем разрешения при старте
        Clock.schedule_once(lambda dt: request_runtime_permissions(), 0.5)
        Clock.schedule_once(lambda dt: self._update_perms_label(), 1.5)

    def _update_perms_label(self):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            PackageManager = autoclass("android.content.pm.PackageManager")
            activity = PythonActivity.mActivity
            audio_ok = activity.checkSelfPermission(
                "android.permission.READ_MEDIA_AUDIO"
            ) == PackageManager.PERMISSION_GRANTED
            notif_ok = activity.checkSelfPermission(
                "android.permission.POST_NOTIFICATIONS"
            ) == PackageManager.PERMISSION_GRANTED
            all_files = check_all_files_access()
            status = []
            status.append("Аудио: " + ("OK" if audio_ok else "НЕТ"))
            status.append("Уведомления: " + ("OK" if notif_ok else "НЕТ"))
            status.append("Все файлы: " + ("OK" if all_files else "нет (не нужно)"))
            self.root.ids.perms_label.text = " | ".join(status)
        except Exception as e:
            self.root.ids.perms_label.text = f"Ошибка проверки: {e}"

    def check_perms(self):
        self._update_perms_label()

    def start_scan(self):
        self.root.ids.status_label.text = "Сканирование через MediaStore..."
        self.root.ids.found_label.text = "Найдено: ..."
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
                stats = scan_and_collect(progress)
                Clock.schedule_once(lambda dt: self._done(stats), 0)
            except Exception as e:
                Clock.schedule_once(lambda dt: self._fail(e), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, stats):
        if stats["copied"] == 0 and stats["errors"] > 0:
            self.root.ids.status_label.text = "Нет прав на запись!"
            self._show_perm_dialog()
        else:
            self.root.ids.status_label.text = "Готово!"
        self.root.ids.dupes_label.text = (
            f"Дубликатов: {stats['dupes']}, ошибок: {stats['errors']}"
        )

    def _fail(self, e):
        self.root.ids.status_label.text = f"ОШИБКА: {e}"

    def _show_perm_dialog(self):
        if getattr(self, "_perm_dialog", None):
            self._perm_dialog.dismiss()
        self._perm_dialog = MDDialog(
            title="Нет прав на запись",
            text=(
                "MediaStore не смог создать файлы в Music/YTmus.\n\n"
                "Варианты:\n"
                "1. Дать разрешение 'Управление всем хранилищем'\n"
                "2. Проверить, что приложение имеет доступ к аудио"
            ),
            buttons=[
                MDFlatButton(
                    text="Отмена",
                    on_release=lambda _: self._perm_dialog.dismiss()
                ),
                MDRaisedButton(
                    text="Открыть настройки",
                    on_release=lambda _: (open_all_files_settings(), self._perm_dialog.dismiss())
                ),
            ],
        )
        self._perm_dialog.open()

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
