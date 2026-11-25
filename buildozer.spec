[app]

; Имя приложения
title = MusicApp
package.name = musicapp
package.domain = org.musicapp

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,mp3,ttf,db

version = 1.1.0

requirements = python3,kivy==2.3.0,kivymd==1.2.0,mutagen,plyer,sdl2,sdl2_ttf,sdl2_image,sdl2_mixer,sqlite3,android,pyjnius

; Ориентация и разрешение
orientation = portrait
fullscreen = 0

android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_AUDIO,WAKE_LOCK
android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True

android.arch = armeabi-v7a, arm64-v8a

; Иконка (положите свои icon.png / icon-*.png в project/icon/)
# android.icon = icon.png

[buildozer]

log_level = 2
warn_on_root = 1
