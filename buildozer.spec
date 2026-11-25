[app]

; Имя приложения
title = MusicApp
package.name = musicapp
package.domain = org.musicapp

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,mp3,ttf,db
source.include_paths = .,service

version = 1.1.0

; android — ОБЯЗАТЕЛЕН: даёт доступ к android.service (фоновая служба плеера)
requirements = python3,kivy==2.3.0,kivymd==1.2.0,mutagen,plyer,sdl2,sdl2_ttf,sdl2_image,sdl2_mixer,sqlite3,android,pyjnius

; Фоновая служба воспроизведения: service/main.py работает в отдельном процессе,
; музыка играет даже когда приложение свёрнуто (SoundLoader в UI-процессе не умеет фон)
services = myservice:service/main.py

; Ориентация и разрешение
orientation = portrait
fullscreen = 0

; READ_MEDIA_AUDIO обязателен для Android 13+ (API 33), WAKE_LOCK — для фонового звука
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_AUDIO,FOREGROUND_SERVICE,POST_NOTIFICATIONS,WAKE_LOCK
android.api = 33
android.minapi = 21
android.sdk = 33
android.ndk = 25b
android.accept_sdk_license = True

; Блокировка сна CPU/экрана во время работы службы
android.wakelock = True

android.arch = armeabi-v7a, arm64-v8a

; Иконка (положите свои icon.png / icon-*.png в project/icon/)
# android.icon = icon.png

[buildozer]

log_level = 2
warn_on_root = 1
