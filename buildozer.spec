[app]
title = YTmus
package.name = ytmus
package.domain = org.davyur
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,mp3,wav,ogg,json,txt,ttf
version = 1.1.0
requirements = hostpython3==3.11.9,python3==3.11.9,kivy==2.3.0,kivymd==1.2.0
orientation = portrait
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_AUDIO,POST_NOTIFICATIONS,WAKE_LOCK
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
android.copy_libs = 1
android.debug = 1
android.wakelock = 1
android.window = 1
log_level = 2

[buildozer]
log_level = 2
warn_on_root = 1
