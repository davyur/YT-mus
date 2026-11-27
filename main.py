from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton
import sqlite3
import os
import hashlib
import threading
from kivy.clock import Clock
from kivy.utils import platform

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
DB_PATH_INTERNAL = "/data/data/org.davyur.ytmus/files/ytmus.db"
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".wma"}


# ---------------------------------------------------------------------------
# Получение путей через Android API (самый надёжный способ)
# ---------------------------------------------------------------------------
def get_app_dirs():
    """
    Возвращает (db_path, music_dst_dir).
    Использует Android API для получения правильных путей.
    """
    if platform != "android":
        # Десктоп
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

        # 1. Внутреннее хранилище (всегда работает, приватное)
        internal_dir = activity.getFilesDir().getAbsolutePath()

        # 2. Внешнее app-specific хранилище (видимо в файловом менеджере)
        #    DIRECTORY_MUSIC = "Music"
        external_music = activity.getExternalFilesDir(
            Environment.DIRECTORY_MUSIC
        )
        external_dir = external_music.getAbsolutePath() if external_music else None

        # 3. Fallback: корень app-specific
        external_root = activity.getExternalFilesDir(None)
        external_root_dir = external_root.getAbsolutePath() if external_root else None

        print(f"internal: {internal_dir}")
        print(f"external_music: {external_dir}")
        print(f"external_root: {external_root_dir}")

        # Выбираем: внешняя Music папка > внешняя корень > внутренняя
        if external_dir:
            dst = os.path.join(external_dir, "YTmus")
        elif external_root_dir:
            dst = os.path.join(external_root_dir, "YTmus")
        else:
            dst = os.path.join(internal_dir, "YTmus")

        db = os.path.join(internal_dir, "ytmus.db")
        return db, dst

    except Exception as e:
        print(f"get_app_dirs error: {e}")
        import traceback
        traceback.print_exc()
        # Fallback
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
            print(f"Запрашиваем: {perms}")
            request_permissions(perms)
    except Exception as e:
        print(f"request_perms error: {e}")


def check_perms_status():
    if platform != "android":
        return {"audio": True, "notif": True, "manage": True}
    try:
        from android.permissions import check_permission, Permission
        from jnius import autoclass
        Environment = autoclass("android.os.Environment")
        return {
            "audio": check_permission(Permission.READ_MEDIA_AUDIO),
            "notif": check_permission(Permission.POST_NOTIFICATIONS),
            "manage": Environment.isExternalStorageManager(),
        }
    except Exception as e:
        print(f"check_perms error: {e}")
        return {"audio": False, "notif": False, "manage": False}


def open_manage_storage_settings():
    """Открывает настройки 'Управление всем хранилищем'."""
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
# Утилиты
# ---------------------------------------------------------------------------
def file_hash_from_uri(uri_str):
    """Считает MD5 файла по URI."""
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Uri = autoclass("android.net.Uri")
        activity = PythonActivity.mActivity
        resolver = activity.getContentResolver()

        uri = Uri.parse(uri_str)
        is_stream = resolver.openInputStream(uri)
        if is_stream is None:
            return None, None

        h = hashlib.md5()
        buf = bytes(65536)
        size = 0
        while True:
            n = is_stream.read(buf)
            if n <= 0:
                break
            chunk = buf[:n]
            h.update(chunk)
            size += len(chunk)
        is_stream.close()
        return h.hexdigest(), size
    except Exception as e:
        print(f"hash error: {e}")
        return None, None


def read_file_from_uri(uri_str):
    """Читает файл по URI в bytes."""
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
        print(f"read error: {e}")
        return None


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
        orig_uri TEXT
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
# Сканирование
# ---------------------------------------------------------------------------
def scan_via_mediastore():
    if platform != "android":
        return []
    try:
        from jnius import autoclass
        MediaStore = autoclass("android.provider.MediaStore")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity

        projection = [
            MediaStore.Audio.Media._ID,
            MediaStore.Audio.Media.DISPLAY_NAME,
            MediaStore.Audio.Media.SIZE,
        ]

        cursor = activity.getContentResolver().query(
            MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
            projection, None, None, None
        )

        files = []
        if cursor:
            count = cursor.getCount()
            print(f"MediaStore вернул {count} записей")
            while cursor.moveToNext():
                try:
                    id_idx = cursor.getColumnIndex(MediaStore.Audio.Media._ID)
                    name_idx = cursor.getColumnIndex(MediaStore.Audio.Media.DISPLAY_NAME)

                    file_id = cursor.getLong(id_idx)
                    name = cursor.getString(name_idx)

                    if not name:
                        continue

                    ext = os.path.splitext(name)[1].lower()
                    if ext not in SUPPORTED_EXTENSIONS:
                        continue

                    uri = f"content://media/external/audio/media/{file_id}"
                    files.append((uri, name, ext))
                except Exception as e:
                    print(f"cursor row error: {e}")
                    continue
            cursor.close()
        return files
    except Exception as e:
        print(f"MediaStore scan error: {e}")
        import traceback
        traceback.print_exc()
        return []


def scan_and_collect(db_path, dst_dir, progress_cb):
    init_db(db_path)

    # Создаём папку назначения
    try:
        os.makedirs(dst_dir, exist_ok=True)
        print(f"Папка создана: {dst_dir}")
    except Exception as e:
        raise RuntimeError(f"Не удалось создать папку {dst_dir}: {e}")

    # Проверка записи
    test_file = os.path.join(dst_dir, ".test_write")
    try:
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        print("Запись в папку работает")
    except Exception as e:
        raise RuntimeError(f"Нет прав на запись в {dst_dir}: {e}")

    # Сканируем
    all_files = scan_via_mediastore()
    progress_cb(("scanned", len(all_files)))

    if not all_files:
        return {"copied": 0, "dupes": 0, "errors": 0}

    # Группируем по размеру
    by_size = {}
    for uri, name, ext in all_files:
        by_size.setdefault(ext, []).append((uri, name))

    seen_hashes = set()
    copied = 0
    skipped_dupes = 0
    errors = 0

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    for ext, group in by_size.items():
        for uri, name in group:
            data = read_file_from_uri(uri)
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
                c.execute(
                    "INSERT INTO tracks(path, title, ext, size, md5, orig_uri) VALUES (?,?,?,?,?,?)",
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
            text: "Путь: ..."
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
        self.db_path, self.dst_dir = get_app_dirs()
        init_db(self.db_path)
        return Builder.load_string(KV)

    def on_start(self):
        Clock.schedule_once(lambda dt: request_perms(), 0.5)
        Clock.schedule_once(lambda dt: self.update_perms_label(), 1.5)
        # Показываем путь куда будем копировать
        Clock.schedule_once(lambda dt: self.root.ids.path_label.setter("text")(
            self.root.ids.path_label, f"Папка: {self.dst_dir}"
        ), 2.0)

    def update_perms_label(self):
        status = check_perms_status()
        audio = "OK" if status.get("audio") else "НЕТ"
        notif = "OK" if status.get("notif") else "НЕТ"
        manage = "OK" if status.get("manage") else "нет"
        self.root.ids.perms_label.text = (
            f"Аудио: {audio} | Увед: {notif} | Все файлы: {manage}"
        )

    def check_perms(self):
        self.update_perms_label()
        request_perms()
        # Показываем диалог с предложением дать полный доступ
        self._show_manage_dialog()

    def _show_manage_dialog(self):
        if getattr(self, "_perm_dialog", None):
            self._perm_dialog.dismiss()
        self._perm_dialog = MDDialog(
            title="Доступ к файлам",
            text=(
                "Для копирования музыки в общую папку Music/YTmus нужно "
                "разрешение 'Управление всем хранилищем'.\n\n"
                "Без этого файлы будут копироваться в приватную папку приложения "
                "(Android/data/org.davyur.ytmus/files/YTmus/)."
            ),
            buttons=[
                MDFlatButton(
                    text="ОК",
                    on_release=lambda _: self._perm_dialog.dismiss()
                ),
                MDRaisedButton(
                    text="Открыть настройки",
                    on_release=lambda _: (
                        open_manage_storage_settings(),
                        self._perm_dialog.dismiss()
                    )
                ),
            ],
        )
        self._perm_dialog.open()

    def start_scan(self):
        self.root.ids.status_label.text = "Проверка папки..."
        self.root.ids.found_label.text = "Найдено: ..."
        self.root.ids.copied_label.text = "Скопировано: ..."

        # Сначала проверяем запись
        try:
            os.makedirs(self.dst_dir, exist_ok=True)
            test = os.path.join(self.dst_dir, ".test")
            with open(test, "w") as f:
                f.write("ok")
            os.remove(test)
        except Exception as e:
            self.root.ids.status_label.text = f"НЕТ ЗАПИСИ: {e}"
            self._show_manage_dialog()
            return

        self.root.ids.status_label.text = "Сканирование..."

        def progress(kind, n):
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
        self.root.ids.status_label.text = f"ОШИБКА: {str(e)[:150]}"

    def show_list(self):
        conn = sqlite3.connect(self.db_path)
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
