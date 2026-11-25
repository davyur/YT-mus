"""
Music Player — Kivy/KivyMD APK (Android) + Desktop
Улучшенная версия исходного прототипа:
  - исправлены баги (MDList не импортировался, дублирование bind-кнопок,
    утечки Sound, сканер не обновлял UI)
  - поиск по библиотеке, избранное, плейлисты, история воспроизведения
  - мини-плеер со слайдером перемотки, play/pause/stop, next/prev
  - блокировка сна экрана во время воспроизведения (Window.softinput / prevent_screensaver)
  - сборка APK через Buildozer (buildozer.spec в репозитории)
"""

import os
import sqlite3
import threading
from pathlib import Path

from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.utils import platform

from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDIconButton, MDFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.dialog import MDDialog
from kivymd.uix.slider import MDSlider
from kivymd.uix.list import MDList, TwoLineListItem, OneLineListItem

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
CACHE_DIR = str(APP_DIR / "cache_covers")
os.makedirs(CACHE_DIR, exist_ok=True)


def get_music_directory():
    """Каталог с музыкой: Android storagepath -> ~/Music -> каталог приложения."""
    try:
        from plyer import storagepath
        path = storagepath.get_external_storage_dir_music()
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
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
        cover_path TEXT, favorite INTEGER DEFAULT 0)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS playlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS playlist_tracks (
        playlist_id INTEGER, track_id INTEGER, UNIQUE(playlist_id, track_id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS play_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, track_id INTEGER,
        played_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS favorites_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, track_id INTEGER,
        favorited_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Сканер медиатеки
# ---------------------------------------------------------------------------

def parse_mp3(file_path):
    title = os.path.splitext(os.path.basename(file_path))[0]
    artist, album, genre, duration, cover_path = "Unknown", "Unknown", "Unknown", 0, ""
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, APIC
        audio = MP3(file_path)
        duration = int(audio.info.length)
        tags = ID3(file_path)
        if "TIT2" in tags: title = str(tags["TIT2"])
        if "TPE1" in tags: artist = str(tags["TPE1"])
        if "TALB" in tags: album = str(tags["TALB"])
        if "TCON" in tags: genre = str(tags["TCON"])
        for tag in tags.values():
            if isinstance(tag, APIC):
                cache_name = os.path.join(CACHE_DIR, f"{abs(hash(file_path))}.jpg")
                if not os.path.exists(cache_name):
                    with open(cache_name, "wb") as f:
                        f.write(tag.data)
                cover_path = cache_name
                break
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
    return {"path": file_path, "title": title, "artist": artist, "album": album,
            "genre": genre, "duration": duration, "cover_path": cover_path}


def scan_music_folder(root_dir, on_done=None):
    """Потоковое bulk-сканирование. on_done вызывается по завершении."""
    count = 0
    if os.path.exists(root_dir):
        con = db()
        cur = con.cursor()
        tracks_data = []
        for root, _, files in os.walk(root_dir):
            for file in files:
                if file.lower().endswith(".mp3"):
                    path = os.path.join(root, file)
                    t = parse_mp3(path)
                    tracks_data.append((
                        t["path"], t["title"], t["artist"], t["album"],
                        t["genre"], t["duration"], t["cover_path"]
                    ))
        if tracks_data:
            cur.executemany("""
                INSERT OR IGNORE INTO tracks(path, title, artist, album, genre, duration, cover_path, favorite)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """, tracks_data)
            con.commit()
            count = len(tracks_data)
        con.close()
    if on_done:
        Clock.schedule_once(lambda dt: on_done(count), 0)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

SELECT_COLS = ("SELECT id, path, title, artist, album, genre, duration, cover_path, favorite FROM tracks")


def load_all_tracks(where="", params=()):
    con = db()
    cur = con.cursor()
    q = SELECT_COLS
    if where:
        q += " WHERE " + where
    q += " ORDER BY title COLLATE NOCASE"
    cur.execute(q, params)
    rows = cur.fetchall()
    con.close()
    return rows


def load_playlists(sort_mode="name_asc"):
    con = db()
    cur = con.cursor()
    if sort_mode == "name_desc":
        q = "SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE DESC"
    elif sort_mode == "created_desc":
        q = "SELECT id, name FROM playlists ORDER BY id DESC"
    else:
        q = "SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE ASC"
    cur.execute(q)
    rows = cur.fetchall()
    con.close()
    return rows


def create_playlist(name):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO playlists(name) VALUES(?)", (name,))
    pid = cur.lastrowid
    con.commit()
    con.close()
    return pid


def delete_playlist(playlist_id):
    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (playlist_id,))
    cur.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
    con.commit()
    con.close()


def add_track_to_playlist(playlist_id, track_id):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO playlist_tracks(playlist_id, track_id) VALUES (?, ?)",
                (playlist_id, track_id))
    con.commit()
    con.close()


def remove_track_from_playlist(playlist_id, track_id):
    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM playlist_tracks WHERE playlist_id=? AND track_id=?",
                (playlist_id, track_id))
    con.commit()
    con.close()


def load_playlist_tracks(playlist_id):
    con = db()
    cur = con.cursor()
    cur.execute("""SELECT t.id, t.path, t.title, t.artist, t.album, t.genre, t.duration, t.cover_path, t.favorite
        FROM playlist_tracks pt JOIN tracks t ON t.id = pt.track_id
        WHERE pt.playlist_id=? ORDER BY t.title COLLATE NOCASE""", (playlist_id,))
    rows = cur.fetchall()
    con.close()
    return rows


def update_track_meta(track_id, title, artist, album, genre):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE tracks SET title=?, artist=?, album=?, genre=? WHERE id=?",
                (title, artist, album, genre, track_id))
    con.commit()
    con.close()


def toggle_favorite(track_id):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT favorite FROM tracks WHERE id=?", (track_id,))
    row = cur.fetchone()
    new_value = 0 if row and row[0] else 1
    cur.execute("UPDATE tracks SET favorite=? WHERE id=?", (new_value, track_id))
    if new_value == 1:
        cur.execute("INSERT INTO favorites_history(track_id) VALUES(?)", (track_id,))
    con.commit()
    con.close()
    return new_value


def log_play(track_id):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO play_history(track_id) VALUES(?)", (track_id,))
    con.commit()
    con.close()


def search_tracks(text):
    q = text.strip().lower()
    if not q:
        return load_all_tracks()
    if q in ("favorites", "избранное"):
        return load_all_tracks("favorite=1")
    like = f"%{q}%"
    return load_all_tracks(
        "lower(title) LIKE ? OR lower(artist) LIKE ? OR lower(album) LIKE ?",
        (like, like, like))


# ---------------------------------------------------------------------------
# UI: строка трека для RecycleView
# ---------------------------------------------------------------------------

class SelectableRecycleBoxLayout(FocusBehavior, LayoutSelectionBehavior, RecycleBoxLayout):
    pass


class TrackRowRV(MDBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(72),
                         padding=dp(6), spacing=dp(6), **kwargs)
        self.title_label = Label(halign="left", valign="middle", markup=True)
        self.sub_label = Label(halign="left", valign="middle", font_size="12sp",
                               color=(0.7, 0.7, 0.7, 1))
        col = MDBoxLayout(orientation="vertical")
        col.add_widget(self.title_label)
        col.add_widget(self.sub_label)
        self.add_widget(col)

        # Привязки один раз при создании, данные читаем из self.* в колбэках —
        # так RecycleView-переиспользование виджетов не приводит к дублям bind.
        self.btn_fav = MDIconButton(icon="heart-outline")
        self.btn_fav.bind(on_release=self.on_fav)
        self.btn_more = MDIconButton(icon="dots-vertical")
        self.btn_more.bind(on_release=self.on_more)
        self.btn_play = MDIconButton(icon="play")
        self.btn_play.bind(on_release=self.on_play)
        self.add_widget(self.btn_fav)
        self.add_widget(self.btn_more)
        self.add_widget(self.btn_play)

        self.track_id = None
        self.path = None
        self.app_ref = None

    def refresh_view_attrs(self, rv, index, data):
        super().refresh_view_attrs(rv, index, data)
        self.track_id = data['id']
        self.path = data['path']
        if self.track_id is None:  # пустая строка-заглушка
            self.title_label.text = "Нет треков"
            self.sub_label.text = ""
            self.btn_fav.icon = "heart-outline"
            return
        self.title_label.text = data['title']
        self.sub_label.text = f"{data['artist']} • {data['album']}"
        self.btn_fav.icon = "heart" if data['favorite'] else "heart-outline"

    def on_play(self, *_):
        if self.app_ref and self.track_id is not None:
            self.app_ref.play_track_by_id(self.track_id)

    def on_fav(self, *_):
        if self.track_id is None:
            return
        toggle_favorite(self.track_id)
        if self.app_ref:
            self.app_ref.refresh_all()

    def on_more(self, *_):
        if self.app_ref and self.track_id is not None:
            self.app_ref.open_track_menu(self.track_id, self.btn_more)


class TrackRecycleView(RecycleView):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        self.viewclass = TrackRowRV
        self.rv_box = SelectableRecycleBoxLayout(
            default_size=(None, dp(72)),
            default_size_hint=(1, None),
            key_location='pos',
            size_hint_y=None,
            orientation="vertical")
        self.rv_box.bind(minimum_height=self.rv_box.setter('height'))
        self.add_widget(self.rv_box)

    def add_widget(self, widget, *args, **kwargs):
        if isinstance(widget, SelectableRecycleBoxLayout):
            self._layout_manager = widget
        super().add_widget(widget, *args, **kwargs)

    def fill(self, tracks):
        data = []
        y = 0
        for t in tracks:
            data.append({
                'id': t[0], 'path': t[1], 'title': t[2], 'artist': t[3],
                'album': t[4], 'favorite': t[8],
                'pos': (0, y), 'size': (Window.width, dp(72)),
            })
            y -= dp(72)
        # Пустая запись принудительно очищает старые view'ы RecycleView
        self.data = [{"id": None, "path": "", "title": "", "artist": "",
                      "album": "", "favorite": 0}] + data if not data else data


# ---------------------------------------------------------------------------
# Экраны
# ---------------------------------------------------------------------------

class LibraryScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = None
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(MDTopAppBar(title="Библиотека"))
        top = MDBoxLayout(size_hint_y=None, height=dp(64), padding=dp(8), spacing=dp(8))
        self.search = MDTextField(hint_text="Поиск...", size_hint_y=None, height=dp(48))
        self.search.bind(text=self.on_search)
        top.add_widget(self.search)
        btn_rescan = MDIconButton(icon="folder-refresh", on_release=self.rescan)
        top.add_widget(btn_rescan)
        root.add_widget(top)

        self.rv = TrackRecycleView(None)
        root.add_widget(self.rv)
        self.add_widget(root)

    def bind_app(self, app):
        self.app_ref = app
        self.rv.app_ref = app

    def rescan(self, *_):
        if self.app_ref:
            self.app_ref.start_scan()

    def on_search(self, *_):
        if self.app_ref:
            self.rv.fill(search_tracks(self.search.text))


class PlaylistsScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = None
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(MDTopAppBar(title="Плейлисты"))
        top = MDBoxLayout(size_hint_y=None, height=dp(56), spacing=dp(6), padding=dp(6))
        self.name_input = MDTextField(hint_text="Название")
        top.add_widget(self.name_input)
        top.add_widget(MDRaisedButton(text="Создать", on_release=self.create_playlist))
        root.add_widget(top)

        scroll = ScrollView()
        self.list = MDList()
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        self.add_widget(root)

    def bind_app(self, app):
        self.app_ref = app

    def create_playlist(self, *_):
        name = self.name_input.text.strip()
        if name:
            create_playlist(name)
            self.name_input.text = ""
            self.refresh()

    def refresh(self):
        self.list.clear_widgets()
        for pid, name in load_playlists():
            item = TwoLineListItem(text=name, secondary_text="Открыть")
            item.bind(on_release=lambda _, p=pid, n=name: self.app_ref.open_playlist_view(p, n))
            self.list.add_widget(item)


class PlaylistViewScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = None
        self.playlist_id = None
        self.playlist_title = ""
        root = MDBoxLayout(orientation="vertical")
        self.toolbar = MDTopAppBar(title="Плейлист")
        self.toolbar.right_action_items = [
            ("delete-outline", lambda _: self.app_ref.confirm_delete_playlist()),
            ("arrow-left", lambda _: self.app_ref.sm.current != "library" and setattr(self.app_ref.sm, "current", "playlists")),
        ]
        root.add_widget(self.toolbar)
        scroll = ScrollView()
        self.list = MDList()
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        self.add_widget(root)

    def bind_app(self, app):
        self.app_ref = app

    def load(self, playlist_id, title):
        self.playlist_id = playlist_id
        self.playlist_title = title
        self.toolbar.title = title
        self.refresh()

    def refresh(self):
        self.list.clear_widgets()
        if self.playlist_id is None:
            return
        for track in load_playlist_tracks(self.playlist_id):
            row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(60),
                              padding=dp(6), spacing=dp(4))
            lbl = Label(text=f"[b]{track[2]}[/b]\n{track[3]}", markup=True,
                        halign="left", valign="middle")
            lbl.bind(size=lbl.setter('text_size'))
            row.add_widget(lbl)
            btn_play = MDIconButton(icon="play")
            tid = track[0]
            btn_play.bind(on_release=lambda _, i=tid: self.app_ref.play_track_by_id(i))
            row.add_widget(btn_play)
            btn_rem = MDIconButton(icon="minus-box")
            btn_rem.bind(on_release=lambda _, i=tid: self.remove_track(i))
            row.add_widget(btn_rem)
            self.list.add_widget(row)

    def remove_track(self, track_id):
        remove_track_from_playlist(self.playlist_id, track_id)
        self.refresh()


class HistoryScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = None
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(MDTopAppBar(title="История"))
        scroll = ScrollView()
        self.list = MDList()
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        self.add_widget(root)

    def bind_app(self, app):
        self.app_ref = app

    def refresh(self):
        self.list.clear_widgets()
        con = db()
        cur = con.cursor()
        cur.execute("""SELECT DISTINCT t.id, t.title, t.artist, ph.played_at
                       FROM play_history ph JOIN tracks t ON t.id = ph.track_id
                       ORDER BY ph.id DESC LIMIT 100""")
        rows = cur.fetchall()
        con.close()
        for tid, title, artist, when in rows:
            item = TwoLineListItem(text=title, secondary_text=f"{artist} • {when}")
            item.bind(on_release=lambda _, i=tid: self.app_ref.play_track_by_id(i))
            self.list.add_widget(item)


class FavoritesScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = None
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(MDTopAppBar(title="Избранное"))
        self.rv = TrackRecycleView(None)
        root.add_widget(self.rv)
        self.add_widget(root)

    def bind_app(self, app):
        self.app_ref = app
        self.rv.app_ref = app


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

class PlayerState:
    def __init__(self):
        self.sound = None
        self.current_track_id = None
        self.current_duration = 0
        self.queue = []          # список track_id текущего контекста
        self.queue_index = -1
        self.paused = False


class MusicApp(MDApp):
    def build(self):
        init_db()
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        self.state = PlayerState()

        self.sm = ScreenManager()
        self.library = LibraryScreen(name="library")
        self.playlists = PlaylistsScreen(name="playlists")
        self.playlist_view = PlaylistViewScreen(name="playlist_view")
        self.favorites = FavoritesScreen(name="favorites")
        self.history = HistoryScreen(name="history")

        for screen in (self.library, self.playlists, self.playlist_view,
                       self.favorites, self.history):
            screen.bind_app(self)
            self.sm.add_widget(screen)

        root = MDBoxLayout(orientation="vertical")
        root.add_widget(self.build_topbar())
        root.add_widget(self.sm)
        root.add_widget(self.build_miniplayer())

        Clock.schedule_once(lambda dt: self.start_scan(), 0.5)
        Clock.schedule_once(lambda dt: self.refresh_all(), 1)
        Clock.schedule_interval(self.update_progress, 1)

        return root

    # ---------------- навигация ----------------
    def build_topbar(self):
        bar = MDBoxLayout(size_hint_y=None, height=dp(56), padding=dp(6), spacing=dp(6))
        for text, screen in (("Библиотека", "library"), ("Плейлисты", "playlists"),
                             ("Избранное", "favorites"), ("История", "history")):
            bar.add_widget(MDFlatButton(text=text,
                                       on_release=lambda _, s=screen: self.goto(s)))
        return bar

    def goto(self, screen):
        if screen == "history":
            self.history.refresh()
        self.sm.current = screen

    # ---------------- мини-плеер ----------------
    def build_miniplayer(self):
        card = MDCard(size_hint_y=None, height=dp(130), padding=dp(8),
                      radius=[18, 18, 0, 0], elevation=6)
        box = MDBoxLayout(orientation="vertical", spacing=dp(2))
        self.now_label = Label(text="Не играет", size_hint_y=None, height=dp(24),
                               halign="left")
        self.now_label.bind(size=self.now_label.setter('text_size'))
        self.progress = MDSlider(min=0, max=100, value=0, size_hint_y=None, height=dp(36))
        self.progress.bind(on_touch_up=self.on_seek)
        self.time_label = Label(text="0:00 / 0:00", halign="right",
                                size_hint_y=None, height=dp(18))
        controls = MDBoxLayout(size_hint_y=None, height=dp(48),
                               adaptive_width=True, pos_hint={'center_x': .5})
        controls.add_widget(MDIconButton(icon="skip-previous", on_release=self.prev_track))
        self.btn_toggle = MDIconButton(icon="play", on_release=self.toggle_play)
        controls.add_widget(self.btn_toggle)
        controls.add_widget(MDIconButton(icon="skip-next", on_release=self.next_track))
        controls.add_widget(MDIconButton(icon="stop", on_release=self.stop_track))
        box.add_widget(self.now_label)
        box.add_widget(self.progress)
        box.add_widget(self.time_label)
        box.add_widget(controls)
        card.add_widget(box)
        return card

    # ---------------- сканирование / обновление ----------------
    def start_scan(self):
        music_dir = get_music_directory()
        threading.Thread(target=scan_music_folder,
                         args=(music_dir, self.on_scan_done), daemon=True).start()

    def on_scan_done(self, count):
        self.refresh_all()

    def refresh_all(self):
        self.library.rv.fill(load_all_tracks())
        self.favorites.rv.fill(load_all_tracks("favorite=1"))
        self.playlists.refresh()
        if self.playlist_view.playlist_id is not None:
            self.playlist_view.refresh()

    # ---------------- воспроизведение ----------------
    def track_row(self, track_id):
        return load_all_tracks("id=?", (track_id,))

    def play_track_by_id(self, track_id, queue=None):
        rows = self.track_row(track_id)
        if not rows:
            return
        t = rows[0]
        if self.state.sound:
            try:
                self.state.sound.stop()
                self.state.sound.unload()
            except Exception:
                pass
            self.state.sound = None

        self.state.sound = SoundLoader.load(t[1])
        self.state.current_track_id = track_id
        self.state.current_duration = int(t[6] or 0)
        self.state.paused = False
        if queue is not None:
            self.state.queue = list(queue)
            if track_id in self.state.queue:
                self.state.queue_index = self.state.queue.index(track_id)

        if self.state.sound:
            self.state.sound.play()
            self.now_label.text = f"{t[2]} — {t[3]}"
            self.btn_toggle.icon = "pause"
            Window.prevent_screensaver = True
            log_play(track_id)
        else:
            self.now_label.text = f"Не удалось открыть: {t[2]}"

    def play_current(self):
        if self.state.sound and self.state.sound.state != "play":
            self.state.sound.play()
            self.state.paused = False
            self.btn_toggle.icon = "pause"
            Window.prevent_screensaver = True

    def toggle_play(self, *_):
        if not self.state.sound:
            if self.state.queue:
                self.play_track_by_id(self.state.queue[0], self.state.queue)
            return
        if self.state.sound.state == "play":
            self.state.sound.stop()
            self.state.paused = True
            self.btn_toggle.icon = "play"
        else:
            self.play_current()

    def next_track(self, *_):
        if self.state.queue and self.state.queue_index >= 0:
            i = min(self.state.queue_index + 1, len(self.state.queue) - 1)
            self.play_track_by_id(self.state.queue[i], self.state.queue)

    def prev_track(self, *_):
        if self.state.queue and self.state.queue_index > 0:
            self.play_track_by_id(self.state.queue[self.state.queue_index - 1],
                                  self.state.queue)

    def stop_track(self, *_):
        if self.state.sound:
            self.state.sound.stop()
            self.state.sound.unload()
            self.state.sound = None
        self.state.paused = False
        self.now_label.text = "Не играет"
        self.btn_toggle.icon = "play"
        self.progress.value = 0
        Window.prevent_screensaver = False

    def on_seek(self, instance, touch):
        if not self.state.sound or self.state.current_duration <= 0:
            return
        try:
            if self.progress.collide_point(*touch.pos):
                frac = (touch.x - self.progress.x) / max(self.progress.width, 1)
                frac = max(0.0, min(1.0, frac))
                self.state.sound.seek(frac * self.state.current_duration)
        except Exception:
            pass

    def update_progress(self, *_):
        if self.state.sound and self.state.current_duration > 0 \
                and self.state.sound.state == "play":
            try:
                pos = self.state.sound.get_pos() or 0
                self.progress.max = self.state.current_duration
                self.progress.value = min(pos, self.state.current_duration)
                self.time_label.text = (f"{int(pos // 60)}:{int(pos % 60):02d} / "
                                        f"{int(self.state.current_duration // 60)}:"
                                        f"{int(self.state.current_duration % 60):02d}")
                if pos >= self.state.current_duration - 0.5:
                    self.next_track()
            except Exception:
                pass

    # ---------------- меню трека (добавить в плейлист и т.д.) ----------------
    def open_track_menu(self, track_id, anchor):
        items = [("Играть", lambda: self.play_from_context(track_id)),
                 ("В избранное", lambda: self.fav_and_refresh(track_id))]
        for pid, name in load_playlists():
            items.append((f"+ «{name}»",
                          lambda p=pid, t=track_id: (add_track_to_playlist(p, t),
                                                     self.playlists.refresh())))
        content = MDList()
        for text, cb in items:
            li = OneLineListItem(text=text)
            li.bind(on_release=lambda _, c=cb: (c(), self.close_menu()))
            content.add_widget(li)
        self._menu_dialog = MDDialog(title="Трек", content_radius_vertical=10,
                                     items=[], text_button_right="Закрыть",
                                     on_press_dismiss=True)
        # Простой вариант: MDDialog со списком элементов
        self._menu_dialog = MDDialog(title="Трек", type="simple", items=[
            OneLineListItem(text=text, on_release=lambda _, c=cb: (c(), self.close_menu()))
            for text, cb in items])
        self._menu_dialog.open()

    def close_menu(self):
        if getattr(self, "_menu_dialog", None):
            self._menu_dialog.dismiss()

    def fav_and_refresh(self, track_id):
        toggle_favorite(track_id)
        self.refresh_all()

    def play_from_context(self, track_id):
        ids = [d['id'] for d in self.library.rv.data] or [track_id]
        self.play_track_by_id(track_id, ids)

    # ---------------- удаление плейлиста ----------------
    def confirm_delete_playlist(self):
        pid = self.playlist_view.playlist_id
        if pid is None:
            return
        def do_delete(*_):
            delete_playlist(pid)
            self._del_dialog.dismiss()
            self.sm.current = "playlists"
            self.refresh_all()
        self._del_dialog = MDDialog(
            title="Удалить плейлист?",
            text=f"«{self.playlist_view.playlist_title}» будет удалён.",
            buttons=[MDFlatButton(text="Отмена",
                                  on_release=lambda _: self._del_dialog.dismiss()),
                     MDRaisedButton(text="Удалить", on_release=do_delete)])
        self._del_dialog.open()

    def on_stop(self):
        self.stop_track()


if __name__ == "__main__":
    MusicApp().run()
