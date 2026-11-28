from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
from kivymd.uix.list import TwoLineListItem
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivymd.uix.boxlayout import MDBoxLayout
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.core.audio import SoundLoader
from kivy.clock import Clock
from kivy.utils import platform
from kivy.metrics import dp
from kivy.uix.label import Label
from kivy.uix.image import Image
import sqlite3
import os
import hashlib
import threading
import traceback
import random

# ---------------------------------------------------------------------------
# Пути и константы
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".wma"}
ERROR_LOG = "/data/data/org.davyur.ytmus/files/error.log"

REPEAT_OFF = 0
REPEAT_ALL = 1
REPEAT_ONE = 2
SHUFFLE = 3


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
# Парсинг метаданных
# ---------------------------------------------------------------------------
def parse_metadata(file_path):
    result = {
        "title": os.path.splitext(os.path.basename(file_path))[0],
        "artist": "Неизвестный исполнитель",
        "album": "Неизвестный альбом",
        "duration": 0,
        "cover_path": "",
    }

    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(file_path)
        if audio is None:
            return result

        if hasattr(audio, "info") and hasattr(audio.info, "length"):
            result["duration"] = int(audio.info.length)

        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".mp3":
            try:
                from mutagen.id3 import ID3, APIC
                tags = ID3(file_path)
                if "TIT2" in tags:
                    result["title"] = str(tags["TIT2"].text[0]) if tags["TIT2"].text else result["title"]
                if "TPE1" in tags:
                    result["artist"] = str(tags["TPE1"].text[0]) if tags["TPE1"].text else result["artist"]
                if "TALB" in tags:
                    result["album"] = str(tags["TALB"].text[0]) if tags["TALB"].text else result["album"]

                for tag in tags.values():
                    if isinstance(tag, APIC):
                        cover_path = save_cover(file_path, tag.data)
                        if cover_path:
                            result["cover_path"] = cover_path
                        break
            except Exception:
                pass

        elif ext == ".m4a":
            try:
                from mutagen.mp4 import MP4
                tags = MP4(file_path)
                if "\xa9nam" in tags:
                    result["title"] = tags["\xa9nam"][0]
                if "\xa9ART" in tags:
                    result["artist"] = tags["\xa9ART"][0]
                if "\xa9alb" in tags:
                    result["album"] = tags["\xa9alb"][0]

                if "covr" in tags:
                    cover_data = tags["covr"][0]
                    cover_path = save_cover(file_path, bytes(cover_data))
                    if cover_path:
                        result["cover_path"] = cover_path
            except Exception:
                pass

        elif ext == ".flac":
            try:
                from mutagen.flac import FLAC
                tags = FLAC(file_path)
                if "title" in tags:
                    result["title"] = tags["title"][0]
                if "artist" in tags:
                    result["artist"] = tags["artist"][0]
                if "album" in tags:
                    result["album"] = tags["album"][0]

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
    if not cover_data:
        return ""
    try:
        if platform == "android":
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            covers_dir = os.path.join(PythonActivity.mActivity.getFilesDir().getAbsolutePath(), "covers")
        else:
            covers_dir = os.path.join(os.path.expanduser("~"), ".ytmus", "covers")

        os.makedirs(covers_dir, exist_ok=True)

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
        return []

    files = []
    for root, dirs, filenames in os.walk(music_dir):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                full_path = os.path.join(root, filename)
                files.append((full_path, filename, ext))

    return files


def read_file(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
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


def scan_and_collect(db_path, dst_dir, covers_dir, progress_cb):
    init_db(db_path)
    os.makedirs(dst_dir, exist_ok=True)
    os.makedirs(covers_dir, exist_ok=True)

    all_files = scan_via_os_walk()
    progress_cb(("scanned", len(all_files), "total"))

    if not all_files:
        return {"copied": 0, "dupes": 0, "errors": 0}

    seen_hashes = set()
    copied = 0
    skipped_dupes = 0
    errors = 0
    total = len(all_files)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    for idx, (full_path, name, ext) in enumerate(all_files, 1):
        progress_cb(("parsing", idx, total))

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

        meta = parse_metadata(full_path)

        target = safe_target(dst_dir, name)
        try:
            with open(target, "wb") as f:
                f.write(data)

            c.execute(
                """INSERT INTO tracks(path, title, artist, album, ext, size, duration, md5, cover_path, source) 
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (target, meta["title"], meta["artist"], meta["album"], ext, size,
                 meta["duration"], h, meta["cover_path"], full_path)
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
# ОПТИМИЗАЦИЯ: RecycleView для списка треков
# ---------------------------------------------------------------------------
class SelectableRecycleBoxLayout(FocusBehavior, LayoutSelectionBehavior, RecycleBoxLayout):
    """Добавляет выделение и навигацию с клавиатуры."""
    pass


class TrackRow(MDBoxLayout):
    """Один элемент списка — переиспользуется RecycleView."""
    
    def __init__(self, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(64),
            padding=dp(8),
            spacing=dp(8),
            **kwargs
        )
        # Обложка (заглушка)
        self.cover = Image(
            size_hint=(None, None),
            size=(dp(48), dp(48)),
            allow_stretch=True,
            keep_ratio=True,
        )
        self.cover.color = (0.3, 0.3, 0.3, 1)  # серый фон
        self.add_widget(self.cover)

        # Текст
        text_box = MDBoxLayout(orientation="vertical", spacing=dp(2))
        self.title_label = Label(
            halign="left",
            valign="middle",
            font_size="14sp",
            color=(1, 1, 1, 1),
        )
        self.subtitle_label = Label(
            halign="left",
            valign="middle",
            font_size="11sp",
            color=(0.7, 0.7, 0.7, 1),
        )
        text_box.add_widget(self.title_label)
        text_box.add_widget(self.subtitle_label)
        self.add_widget(text_box)

        # Длительность справа
        self.duration_label = Label(
            halign="right",
            valign="middle",
            font_size="12sp",
            color=(0.6, 0.6, 0.6, 1),
            size_hint_x=None,
            width=dp(50),
        )
        self.add_widget(self.duration_label)

        # Данные трека (заполняются через refresh_view_attrs)
        self.track_id = None
        self.app_ref = None

    def refresh_view_attrs(self, rv, index, data):
        """Вызывается RecycleView при переиспользовании виджета."""
        super().refresh_view_attrs(rv, index, data)
        self.track_id = data.get('track_id')
        self.title_label.text = data.get('title', '')
        self.subtitle_label.text = data.get('subtitle', '')
        self.duration_label.text = data.get('duration', '')

        # Загрузка обложки
        cover_path = data.get('cover_path', '')
        if cover_path and os.path.exists(cover_path):
            self.cover.source = cover_path
            self.cover.color = (1, 1, 1, 1)
        else:
            self.cover.source = ''
            self.cover.color = (0.3, 0.3, 0.3, 1)

    def on_touch_down(self, touch):
        """Обработка нажатия на строку."""
        if self.collide_point(*touch.pos) and self.track_id is not None:
            if self.app_ref:
                self.app_ref.play_track(self.track_id)
            return True
        return super().on_touch_down(touch)


class OptimizedTrackList(RecycleView):
    """Быстрый список треков с виртуализацией."""
    
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        self.viewclass = TrackRow
        self.data = []
        
        self.layout = SelectableRecycleBoxLayout(
            default_size=(None, dp(64)),
            default_size_hint=(1, None),
            size_hint_y=None,
            orientation='vertical',
            multiselect=False,
            touch_multiselect=False,
        )
        self.layout.bind(minimum_height=self.layout.setter('height'))
        self.add_widget(self.layout)

    def load_tracks(self, tracks_data):
        """Загружает данные треков в RecycleView."""
        self.data = []
        for track_id, title, artist, album, duration, cover_path in tracks_data:
            if duration > 0:
                mins = duration // 60
                secs = duration % 60
                duration_str = f"{mins}:{secs:02d}"
            else:
                duration_str = "--:--"

            self.data.append({
                'track_id': track_id,
                'title': title,
                'subtitle': f"{artist} • {album}",
                'duration': duration_str,
                'cover_path': cover_path or '',
            })


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
            left_action_items: [["arrow-left", lambda x: app.go_main()]]
            right_action_items: [["refresh", lambda x: app.refresh_list()]]

        # Быстрый RecycleView вместо MDList
        OptimizedTrackList:
            id: track_list

        # Мини-плеер внизу
        MDCard:
            size_hint_y: None
            height: dp(140)
            padding: dp(8)
            radius: [dp(16), dp(16), 0, 0]
            elevation: 8

            MDBoxLayout:
                orientation: "vertical"
                spacing: dp(4)

                MDLabel:
                    id: now_playing_label
                    text: "Не играет"
                    halign: "center"
                    theme_text_color: "Primary"
                    font_style: "Caption"

                MDSlider:
                    id: progress_slider
                    min: 0
                    max: 100
                    value: 0
                    size_hint_y: None
                    height: dp(30)

                MDBoxLayout:
                    orientation: "horizontal"
                    spacing: dp(8)
                    adaptive_width: True
                    pos_hint: {"center_x": 0.5}

                    MDIconButton:
                        icon: "skip-previous"
                        on_release: app.prev_track()

                    MDIconButton:
                        id: play_pause_btn
                        icon: "play"
                        on_release: app.toggle_play_pause()

                    MDIconButton:
                        icon: "skip-next"
                        on_release: app.next_track()

                    MDIconButton:
                        icon: "stop"
                        on_release: app.stop_track()

                    MDIconButton:
                        id: mode_btn
                        icon: "repeat-off"
                        on_release: app.cycle_mode()
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

        # Состояние плеера
        self.sound = None
        self.current_track_id = None
        self.current_track_path = None
        self.track_queue = []
        self.queue_index = -1
        self.is_playing = False
        self.play_mode = REPEAT_OFF

        # Регистрируем кастомный виджет RecycleView
        Builder.load_string(KV)

        # Запуск обновления прогресса
        Clock.schedule_interval(self.update_progress, 1.0)

        return Builder.load_string(KV)

    def on_start(self):
        Clock.schedule_once(lambda dt: request_perms(), 0.5)
        Clock.schedule_once(lambda dt: self.update_perms_label(), 1.5)
        Clock.schedule_once(
            lambda dt: setattr(self.root.get_screen("main").ids.path_label, "text",
                               f"Папка: {self.dst_dir}"), 2.0
        )

    def go_main(self):
        self.root.current = "main"

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
                MDFlatButton(text="Закрыть", on_release=lambda _: self._err_dialog.dismiss()),
            ],
        )
        self._err_dialog.open()

    def show_list(self):
        """Быстрая загрузка списка через RecycleView."""
        list_screen = self.root.get_screen("list")
        track_list = list_screen.ids.track_list
        
        # Устанавливаем ссылку на приложение для обработки нажатий
        track_list.app_ref = self

        # Загружаем данные из БД в отдельном потоке (если много треков)
        def load_from_db():
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT id, title, artist, album, duration, cover_path FROM tracks ORDER BY title")
            rows = c.fetchall()
            conn.close()
            return rows

        def update_ui(rows):
            self.track_queue = [row[0] for row in rows]
            track_list.load_tracks(rows)
            self.update_mode_icon()

        # Для небольшого количества треков — сразу, для большого — в потоке
        if len(self.track_queue) > 100:
            threading.Thread(target=lambda: Clock.schedule_once(
                lambda dt: update_ui(load_from_db()), 0
            ), daemon=True).start()
        else:
            rows = load_from_db()
            update_ui(rows)

        self.root.current = "list"

    def refresh_list(self):
        """Обновить список (кнопка refresh в toolbar)."""
        self.show_list()

    # ---------------------------------------------------------------------------
    # Воспроизведение
    # ---------------------------------------------------------------------------
    def play_track(self, track_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT path, title, artist FROM tracks WHERE id=?", (track_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return

        path, title, artist = row

        if self.sound:
            self.sound.stop()
            self.sound.unload()

        self.sound = SoundLoader.load(path)
        if self.sound is None:
            print(f"Failed to load: {path}")
            return

        self.current_track_id = track_id
        self.current_track_path = path
        
        if track_id in self.track_queue:
            self.queue_index = self.track_queue.index(track_id)
        
        self.sound.play()
        self.is_playing = True

        list_screen = self.root.get_screen("list")
        list_screen.ids.now_playing_label.text = f"♪ {title} — {artist}"
        list_screen.ids.play_pause_btn.icon = "pause"

        if self.sound.length > 0:
            list_screen.ids.progress_slider.max = self.sound.length

    def toggle_play_pause(self):
        if not self.sound:
            return

        if self.is_playing:
            self.sound.pause()
            self.is_playing = False
            self.root.get_screen("list").ids.play_pause_btn.icon = "play"
        else:
            self.sound.play()
            self.is_playing = True
            self.root.get_screen("list").ids.play_pause_btn.icon = "pause"

    def stop_track(self):
        if self.sound:
            self.sound.stop()
            self.sound.unload()
            self.sound = None

        self.is_playing = False
        self.current_track_id = None

        list_screen = self.root.get_screen("list")
        list_screen.ids.now_playing_label.text = "Не играет"
        list_screen.ids.play_pause_btn.icon = "play"
        list_screen.ids.progress_slider.value = 0

    def next_track(self):
        if not self.track_queue:
            return

        if self.play_mode == REPEAT_ONE:
            if self.current_track_id:
                self.play_track(self.current_track_id)
            return

        if self.play_mode == SHUFFLE:
            if len(self.track_queue) > 1:
                next_id = random.choice(self.track_queue)
                while next_id == self.current_track_id and len(self.track_queue) > 1:
                    next_id = random.choice(self.track_queue)
                self.play_track(next_id)
            return

        if self.queue_index < 0:
            self.queue_index = 0
        elif self.queue_index < len(self.track_queue) - 1:
            self.queue_index += 1
        elif self.play_mode == REPEAT_ALL:
            self.queue_index = 0
        else:
            self.stop_track()
            return

        self.play_track(self.track_queue[self.queue_index])

    def prev_track(self):
        if not self.track_queue or self.queue_index <= 0:
            return
        self.queue_index -= 1
        self.play_track(self.track_queue[self.queue_index])

    def cycle_mode(self):
        self.play_mode = (self.play_mode + 1) % 4
        self.update_mode_icon()

    def update_mode_icon(self):
        list_screen = self.root.get_screen("list")
        mode_icons = {
            REPEAT_OFF: "repeat-off",
            REPEAT_ALL: "repeat",
            REPEAT_ONE: "repeat-once",
            SHUFFLE: "shuffle",
        }
        list_screen.ids.mode_btn.icon = mode_icons.get(self.play_mode, "repeat-off")

    def update_progress(self, dt):
        if self.sound and self.is_playing:
            list_screen = self.root.get_screen("list")
            current_pos = self.sound.get_pos()
            list_screen.ids.progress_slider.value = current_pos

            if current_pos >= self.sound.length - 0.5:
                self.next_track()


if __name__ == "__main__":
    MusicApp().run()
