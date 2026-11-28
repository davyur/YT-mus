from kivy.lang import Builder
from kivy.factory import Factory
from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDIconButton
from kivymd.uix.boxlayout import MDBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.core.audio import SoundLoader
from kivy.clock import Clock
from kivy.utils import platform
from kivy.metrics import dp
from kivy.uix.label import Label
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

                if "
