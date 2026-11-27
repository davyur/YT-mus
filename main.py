from kivy.lang import Builder
from kivymd.app import MDApp
import sqlite3
import os
from kivy.clock import Clock

KV = """
MDScreen:
    MDBoxLayout:
        orientation: "vertical"
        
        MDTopAppBar:
            title: "YTmus - Сканер"
        
        MDLabel:
            id: status_label
            text: "Готов к сканированию"
            halign: "center"
            theme_text_color: "Primary"
        
        MDLabel:
            id: count_label
            text: "Треков найдено: 0"
            halign: "center"
            theme_text_color: "Secondary"
        
        MDLabel:
            id: path_label
            text: "Путь: ..."
            halign: "center"
            theme_text_color: "Hint"
            font_style: "Caption"
        
        MDRaisedButton:
            text: "Сканировать Music"
            pos_hint: {"center_x": 0.5}
            on_release: app.start_scan()
"""

class MusicApp(MDApp):
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        return Builder.load_string(KV)
    
    def start_scan(self):
        # Стандартный путь к музыке на Android
        music_dir = "/storage/emulated/0/Music"
        self.root.ids.path_label.text = f"Путь: {music_dir}"
        self.root.ids.status_label.text = "Сканирование..."
        
        # Запускаем сканирование
        count = self.scan_folder(music_dir)
        
        self.root.ids.status_label.text = "Готово!"
        self.root.ids.count_label.text = f"Треков найдено: {count}"
    
    def scan_folder(self, root_dir):
        count = 0
        if not os.path.exists(root_dir):
            return 0
        
        # Подключаемся к БД
        db_path = "/data/data/org.davyur.ytmus/files/test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            path TEXT UNIQUE,
            title TEXT
        )""")
        
        # Сканируем
        for folder, _, files in os.walk(root_dir):
            for file in files:
                if file.lower().endswith(".mp3"):
                    full_path = os.path.join(folder, file)
                    title = os.path.splitext(file)[0]
                    try:
                        cursor.execute(
                            "INSERT OR IGNORE INTO tracks (path, title) VALUES (?, ?)",
                            (full_path, title)
                        )
                        count += 1
                    except Exception as e:
                        print(f"Error: {e}")
        
        conn.commit()
        
        # Считаем всего треков в БД
        cursor.execute("SELECT COUNT(*) FROM tracks")
        total = cursor.fetchone()[0]
        conn.close()
        
        self.root.ids.count_label.text = f"Новых: {count}, Всего в БД: {total}"
        return count

if __name__ == "__main__":
    MusicApp().run()
