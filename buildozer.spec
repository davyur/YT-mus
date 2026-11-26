[app]

# Название приложения (отображается в лаунчере)
title = YTmus

# Имя пакета (влияет на имя APK-файла)
package.name = ytmus

# Домен пакета (должен быть валидным Java-идентификатором)
package.domain = org.davyur

# Исходный код приложения
source.dir = .

# Исходные файлы (по умолчанию все .py)
source.include_exts = py,png,jpg,kv,atlas,mp3,wav,ogg,json,txt,ttf

# Версия приложения
version = 1.1.0

# Версия кода (увеличивайте при каждом обновлении)
version.regex = __version__ = '(.*)'
version.filename = %(source.dir)s/main.py

# Требования (Python + библиотеки)
requirements = hostpython3==3.11.9,python3==3.11.9,kivy==2.3.0,kivymd==1.2.0,mutagen,plyer,pyjnius

# Ориентация экрана
orientation = portrait

# Поддержка портретной ориентации
osx.python_version = 3
osx.kivy_version = 2.3.0

# Разрешения Android
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_AUDIO,FOREGROUND_SERVICE,POST_NOTIFICATIONS,WAKE_LOCK,FOREGROUND_SERVICE_MEDIA_PLAYBACK

# Минимальная версия Android API
android.minapi = 21

# Целевая версия Android API
android.api = 33

# Версия NDK
android.ndk = 25b

# Версии build-tools (фикс зависания aidl)
android.sdk_build_tools = 33.0.2

# Архитектура (только arm64-v8a для скорости)
android.archs = arm64-v8a

# Отключаем предупреждение о root
warn_on_root = 0

# Кастомный AndroidManifest (решает OnBackInvokedCallback)
android.manifest = AndroidManifest.tmpl.xml

# Точка входа приложения
android.entrypoint = org.kivy.android.PythonActivity

# Тема приложения
android.apptheme = @android:style/Theme.NoTitleBar

# Полноэкранный режим
fullscreen = 0

# Иконка приложения (PNG 512x512)
icon.filename = icon.png

# Пресплаш (заставка при загрузке)
# presplash.filename = %(source.dir)s/presplash.png

# Сервис (ЗАКОММЕНТИРОВАНО для теста — раскомментируйте после проверки)
# services = myservice:service/main.py

# Включить AndroidX
android.enable_androidx = 1

# Копировать библиотеки
android.copy_libs = 1

# Режим отладки
android.debug = 1

# Уровень логирования (2 = подробный, 1 = обычный)
log_level = 2

# Wake lock (не давать экрану гаснуть)
android.wakelock = 1

# Окно приложения
android.window = 1

[buildozer]

# Уровень логирования сборщика
log_level = 2

# Предупреждение при запуске от root
warn_on_root = 1
