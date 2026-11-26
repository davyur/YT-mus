# YTmus — музыкальный плеер (Kivy + KivyMD)

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
- 🌙 Фоновое воспроизведение на Android через службу `service/main.py`
  (`android.service`, `services = myservice:service/main.py` в buildozer.spec):
  музыка играет даже когда приложение свёрнуто. Если служба недоступна —
  автоматический fallback: SoundLoader в UI-процессе + `Window.prevent_screensaver`
  (экран не гаснет, но при сворачивании звук ставится на паузу)
- ♻ Список треков на `RecycleView` — быстро прокручивает большие библиотеки на телефоне
- 💾 SQLite (WAL): tracks, playlists, playlist_tracks, play_history, favorites_history

## Разрешения Android (важно!)
Без этих строк в `buildozer.spec` приложение не получит доступ к файлам
и вылетит на Android 13+:
```ini
requirements = python3,kivy==2.3.0,kivymd==1.2.0,plyer,mutagen,android
android.permissions = READ_EXTERNAL_STORAGE, READ_MEDIA_AUDIO, FOREGROUND_SERVICE, POST_NOTIFICATIONS, WAKE_LOCK
android.api = 33
android.minapi = 21
android.sdk = 33
android.ndk = 25b
android.wakelock = True
services = myservice:service/main.py
orientation = portrait
```
- `READ_MEDIA_AUDIO` — обязательное право на чтение музыки для Android 13+ (API 33)
- `android` в requirements — нужен для `from android import service` (фон)
- `FOREGROUND_SERVICE` + `POST_NOTIFICATIONS` — foreground-уведомление службы (Android 8+/13+)
- `WAKE_LOCK` / `android.wakelock` — CPU не засыпает во время фоновой игры
- `plyer.storagepath.get_external_storage_dir_music()` — правильный путь к `/storage/emulated/0/Music`

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
main.py          — всё приложение (БД, сканер, экраны, плеер + клиент службы)
service/main.py  — фоновая служба воспроизведения для Android (отдельный процесс)
buildozer.spec   — конфигурация сборки APK (права, services, wakelock)
requirements.txt — зависимости для десктоп-разработки
```

## Как работает фон
1. `buildozer.spec`: `services = myservice:service/main.py`, в requirements есть `android`.
2. При старте `MusicApp` запускает службу через `android.service.AndroidService("myservice")`.
3. Все команды play/pause/resume/stop/seek шлются в службу; позиция синхронизируется `ping`-запросом раз в секунду.
4. Если пакет `android` недоступен (десктоп или сборка без него), приложение прозрачно
   переключается на SoundLoader в UI-процессе и `Window.prevent_screensaver = True`.

⚠️ Замечания:
- На Android 12+ при первом запуске система запросит разрешение на музыку
  (`READ_MEDIA_AUDIO`) и уведомления (`POST_NOTIFICATIONS`) — их нужно принять.
- Battery optimization может убивать службу — при желании добавьте в инструкции
  пользователя исключение приложения из оптимизации батареи.

## 🌐 Веб-версия интерфейса (`web/index.html`)
В репозитории есть HTML/CSS/JS прототип, полностью повторяющий интерфейс APK:
тёмная тема KivyMD + палитра BlueGray, вкладки «Библиотека / Плейлисты / Избранное / История»,
строки треков как `TrackRowRV` (72dp), мини-плеер-карточка со слайдером перемотки,
диалоги в стиле `MDDialog`, поиск, избранное, история — всё интерактивно на демо-данных.

Запуск: просто откройте файл в браузере, либо:
```bash
python3 -m http.server 8080 --directory web
# затем http://localhost:8080
```
Это UI-макет без реального звука (воспроизведение эмулируется таймером).

## Лицензия
MIT
