from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
from kivymd.uix.list import MDList, TwoLineListItem, OneLineAvatarListItem
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.scrollview import ScrollView
from kivy.uix.screenmanager import ScreenManager, Screen
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
# Получение путей
# ---------------------------------------------------------------------------
def get_app_dirs():
    if platform != "android":
        home = os.path.expanduser("~")
        return (
            os.path.join(home, ".ytmus", "ytmus.db"),
            os.path.join(home, ".ytmus", "YTmus"),
            os.path.join(home, ".ytmus", "covers"),
        )

    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Environment = autoclass("android.os.Environment")
        activity = PythonActivity.mActivity

        internal_dir = activity.getFilesDir().getAbsolutePath()
        external_music = activity.getExternalFilesDir(Environment.DIRECTORY_MUSIC)
        external_dir = external_music.getAbsolutePath() if external_music else internal_dir

        dst = os.path.join(external_dir, "YTmus")
        db = os.path.join(internal_dir, "ytmus.db")
        covers = os.path.join(internal_dir, "covers")

        os.makedirs(dst, exist_ok=True)
        os.makedirs(covers, exist_ok=True)

        print(f"DB: {db}\nDST: {dst}\nCOVERS: {covers}")
        return db, dst, covers
    except Exception as e:
        print(f"get_app_dirs error: {e}")
        return (
            "/data/data/org.davyur.ytmus/files/ytmus.db",
            "/data/data/org.davyur.ytmus/files/YTmus",
            "/data/data/org.davyur.ytmus/files/covers",
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
# Парсинг метаданных через mutagen
# ---------------------------------------------------------------------------
def parse_metadata(file_path):
    """
    Извлекает метаданные из аудиофайла.
    Возвращает dict: {title, artist, album, duration, cover_path}
    """
    result = {
        "title": os.path.splitext(os.path.basename(file_path))[0],
        "artist": "Неизвестный исполнитель",
        "album": "Неизвестный альбом",
        "duration": 0,
        "cover_path": "",
    }

    try:
        from mutagen import File as MutagenFile
        from mutagen.mp3 import MP3
        from mutagen.mp4 import MP4
        from mutagen.flac import FLAC
        from mutagen.id3 import ID3, APIC

        audio = MutagenFile(file_path)
        if audio is None:
            return result

        # Длительность (есть у всех форматов)
        if hasattr(audio, "info") and hasattr(audio.info, "length"):
            result["duration"] = int(audio.info.length)

        ext = os.path.splitext(file_path)[1].lower()

        # MP3 с ID3 тегами
        if ext == ".mp3":
            try:
                tags = ID3(file_path)
                if "TIT2" in tags:
                    result["title"] = str(tags["TIT2"].text[0]) if tags["TIT2"].text else result["title"]
                if "TPE1" in tags:
                    result["artist"] = str(tags["TPE1"].text[0]) if tags["TPE1"].text else result["artist"]
                if "TALB" in tags:
                    result["album"] = str(tags["TALB"].text[0]) if tags["TALB"].text else result["album"]

                # Обложка
                for tag in tags.values():
                    if isinstance(tag, APIC):
                        cover_path = save_cover(file_path, tag.data)
                        if cover_path:
                            result["cover_path"] = cover_path
                        break
            except Exception:
                pass

        # M4A / MP4
        elif ext == ".m4a":
            try:
                tags = MP4(file_path)
                if "\xa9nam" in tags:
                    result["title"] = tags["\xa9nam"][0]
                if "\xa9ART" in tags:
                    result["artist"] = tags["\xa9ART"][0]
                if "\xa9alb" in tags:
                    result["album"] = tags["\xa9alb"][0]

                # Обложка
                if "covr" in tags:
                    cover_data = tags["covr"][0]
                    cover_path = save_cover(file_path, bytes(cover_data))
                    if cover_path:
                        result["cover_path"] = cover_path
            except Exception:
                pass

        # FLAC
        elif ext == ".flac":
            try:
                tags = FLAC(file_path)
                if "title" in tags:
                    result["title"] = tags["title"][0]
                if "artist" in tags:
                    result["artist"] = tags["artist"][0]
                if "album" in tags:
                    result["album"] = tags["album"][0]

                # Обложка
                if tags.pictures:
                    cover_data = tags.pictures[0].data
                    cover_path = save_cover(file_path, cover_data)
                    if cover_path:
                        result["cover_path"] = cover_path
            except Exception:
                pass

    except Exception as e:
        print(f"parse_metadata error {file_path}: {e}")

    return result


def save_cover(file_path, cover_data):
    """Сохраняет обложку в папку covers. Возвращает путь или пустую строку."""
    if not cover_data:
        return ""
    try:
        from kivy.utils import platform as plat
        # Определяем папку covers
        if plat == "android":
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            covers_dir = os.path.join(PythonActivity.mActivity.getFilesDir().getAbsolutePath(), "covers")
        else:
            covers_dir = os.path.join(os.path.expanduser("~"), ".ytmus", "covers")

        os.makedirs(covers_dir, exist_ok=True)

        # Уникальное имя по хешу файла
        file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]
        cover_path = os.path.join(covers_dir, f"{file_hash}.jpg")

        if not os.path.exists(cover_path):
            with open(cover_path, "wb") as f:
                f.write(cover_data)

        return cover_path
    except Exception as e:
        print(f"save_cover error: {e}")
        return ""


# ---------------------------------------------------------------------------
# Сканирование
# ---------------------------------------------------------------------------
def scan_via_os_walk():
    if platform != "android":
        return []

    music_dir = "/storage/emulated/0/Music"
    if not os.path.exists(music_dir):
        print(f"Папка {music_dir} не существует")
        return []

    print(f"Сканируем {music_dir}...")
    files = []

    for root, dirs, filenames in os.walk(music_dir):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                full_path = os.path.join(root, filename)
                files.append((full_path, filename, ext))

    print(f"os.walk нашёл {len(files)} файлов")
    return files


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------
def read_file(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"read error {path}: {e}")
        return None


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE,
        title TEXT,
        artist TEXT,
        album TEXT,
        ext TEXT,
        size INTEGER,
        duration INTEGER,
        md5 TEXT,
        cover_path TEXT,
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
# Основная функция сканирования
# ---------------------------------------------------------------------------
def scan_and_collect(db_path, dst_dir, covers_dir, progress_cb):
    init_db(db_path)

    os.makedirs(dst_dir, exist_ok=True)
    os.makedirs(covers_dir, exist_ok=True)
    print(f"Папка назначения: {dst_dir}")

    # 1. Сканируем
    all_files = scan_via_os_walk()
    progress_cb(("scanned", len(all_files), "total"))

    if not all_files:
        return {"copied": 0, "dupes": 0, "errors": 0}

    # 2. Дедупликация и копирование с парсингом метаданных
    seen_hashes = set()
    copied = 0
    skipped_dupes = 0
    errors = 0
    total = len(all_files)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    for idx, (full_path, name, ext) in enumerate(all_files, 1):
        # Прогресс парсинга
        progress_cb(("parsing", idx, total))

        # Читаем файл
        data = read_file(full_path)
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

        # Парсим метаданные
        meta = parse_metadata(full_path)

        # Копируем файл
        target = safe_target(dst_dir, name)
        try:
            with open(target, "wb") as f:
                f.write(data)

            c.execute(
                """INSERT INTO tracks(path, title, artist, album, ext, size, duration, md5, cover_path, source) 
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    target,
                    meta["title"],
                    meta["artist"],
                    meta["album"],
                    ext,
                    size,
                    meta["duration"],
                    h,
                    meta["cover_path"],
                    full_path,
                )
            )
            copied += 1
            progress_cb(("copied", copied, total))
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
ScreenManager:
    MainScreen:
    ListScreen:

<MainScreen>:
    name: "main"
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

<ListScreen>:
    name: "list"
    MDBoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            title: "Библиотека"
            left_action_items: [["arrow-left", lambda x: app.root.current = "main"]]

        ScrollView:
            MDList:
                id: tracks_list
"""


class MainScreen(Screen):
    pass


class ListScreen(Screen):
    pass


class MusicApp(MDApp):
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        self.db_path, self.dst_dir, self.covers_dir = get_app_dirs()
        init_db(self.db_path)
        return Builder.load_string(KV)

    def on_start(self):
        Clock.schedule_once(lambda dt: request_perms(), 0.5)
        Clock.schedule_once(lambda dt: self.update_perms_label(), 1.5)
        Clock.schedule_once(
            lambda dt: setattr(self.root.get_screen("main").ids.path_label, "text",
                               f"Папка: {self.dst_dir}"), 2.0
        )

    def update_perms_label(self):
        status = check_perms_status()
        audio = "OK" if status.get("audio") else "НЕТ"
        notif = "OK" if status.get("notif") else "НЕТ"
        self.root.get_screen("main").ids.perms_label.text = f"Аудио: {audio} | Увед: {notif}"

    def start_scan(self):
        main_screen = self.root.get_screen("main")
        main_screen.ids.status_label.text = "Сканирование..."
        main_screen.ids.found_label.text = "Найдено: ..."
        main_screen.ids.copied_label.text = "Скопировано: ..."
        main_screen.ids.dupes_label.text = "Дубликатов: ..."

        def progress(args):
            kind, n, total = args
            def upd(_):
                if kind == "scanned":
                    main_screen.ids.found_label.text = f"Найдено: {n}"
                elif kind == "parsing":
                    main_screen.ids.status_label.text = f"Обработка: {n}/{total}"
                elif kind == "copied":
                    main_screen.ids.copied_label.text = f"Скопировано: {n}/{total}"
            Clock.schedule_once(upd, 0)

        def worker():
            try:
                stats = scan_and_collect(self.db_path, self.dst_dir, self.covers_dir, progress)
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
        main_screen = self.root.get_screen("main")
        main_screen.ids.status_label.text = "Готово!"
        main_screen.ids.dupes_label.text = (
            f"Дубликатов: {stats['dupes']}, ошибок: {stats['errors']}"
        )

    def _fail(self, err):
        main_screen = self.root.get_screen("main")
        main_screen.ids.status_label.text = "ОШИБКА! Нажми 'Ошибка'"
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
        """Показывает список треков с метаданными."""
        list_screen = self.root.get_screen("list")
        tracks_list = list_screen.ids.tracks_list
        tracks_list.clear_widgets()

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT title, artist, album, duration, cover_path FROM tracks ORDER BY title")
        rows = c.fetchall()
        conn.close()

        if not rows:
            tracks_list.add_widget(OneLineAvatarListItem(text="База пуста"))
        else:
            for title, artist, album, duration, cover_path in rows:
                # Форматируем длительность
                if duration > 0:
                    mins = duration // 60
                    secs = duration % 60
                    duration_str = f"{mins}:{secs:02d}"
                else:
                    duration_str = "??:??"

                item = TwoLineListItem(
                    text=title,
                    secondary_text=f"{artist} • {album} • {duration_str}"
                )
                tracks_list.add_widget(item)

        self.root.current = "list"


if __name__ == "__main__":
    MusicApp().run()
