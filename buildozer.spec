[app]
title = YTmus
package.name = ytmus
package.domain = org.davyur
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,mp3,m4a,flac,wav,ogg,aac,wma,json,txt,ttf
version = 1.1.0
requirements = hostpython3==3.11.9,python3==3.11.9,kivy==2.3.0,kivymd==1.2.0,pyjnius
orientation = portrait
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_AUDIO,POST_NOTIFICATIONS,WAKE_LOCK,FOREGROUND_SERVICE,FOREGROUND_SERVICE_MEDIA_PLAYBACK,USE_FULL_SCREEN_INTENT,MANAGE_EXTERNAL_STORAGE
android.minapi = 21
android.api = 33
android.ndk = 25b
android.sdk_build_tools = 33.0.2
android.archs = arm64-v8a
warn_on_root = 0
icon.filename = icon.png
android.manifest = AndroidManifest.tmpl.xml
fullscreen = 0
android.enable_androidx = 1

[buildozer]
log_level = 2
warn_on_root = 1
