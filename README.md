# MusicApp — музыкальный плеер (Kivy + KivyMD)

Android APK / Desktop плеер: сканирование MP3, теги и обложки через mutagen,
плейлисты, избранное, история воспроизведения, мини-плеер с перемоткой.

## Возможности
- 📂 Автоскан папки Music (на Android — через `plyer.storagepath`, на десктопе — `~/Music`)
- 🏷 Чтение ID3-тегов (title/artist/album/genre) и кэширование обложек
- 🔍 Поиск по названию/исполнителю/альбому (`favorites` / `избранное` — только избранное)
- ❤ Избранное с историей
- 📃 Плейлисты: создание, удаление, добавление/удаление треков
- 🕘 История воспроизведения
- ▶ Мини-плеер: play/pause, stop, next/prev, перемотка слайдером, автопереход к следующему треку
- 🔋 `Window.prevent_screensaver` — экран не гаснет во время воспроизведения
- ♻ Список треков на `RecycleView` — быстро прокручивает большие библиотеки на телефоне
- 💾 SQLite (WAL): tracks, playlists, playlist_tracks, play_history, favorites_history

## Запуск на десктопе
```bash
pip install -r requirements.txt
python main.py
```

## Сборка APK (Linux)
```bash
sudo apt install openjdk-17-jdk zip unzip autoconf libtool pkg-config \
    zlib1g-dev libssl-dev cmake
pip install buildozer cython==0.29.36
buildozer android debug        # -> bin/musicapp-1.1.0-debug.apk
buildozer android release      # подписанный релизный APK
```
Конфигурация — в `buildozer.spec` (права: READ_MEDIA_AUDIO, WAKE_LOCK и т.д.).

## Структура
```
main.py          — всё приложение (БД, сканер, экраны, плеер)
buildozer.spec   — конфигурация сборки APK
requirements.txt — зависимости для десктоп-разработки
```

## Лицензия
MIT
