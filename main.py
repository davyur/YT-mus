from kivy.lang import Builder
from kivymd.app import MDApp
import sqlite3
from pathlib import Path

KV = """
MDScreen:
    MDBoxLayout:
        orientation: "vertical"
        
        MDTopAppBar:
            title: "YTmus - Тест БД"
        
        MDLabel:
            id: status_label
            text: "Инициализация..."
            halign: "center"
            theme_text_color: "Primary"
        
        MDLabel:
            id: db_label
            text: "БД: проверка..."
            halign: "center"
            theme_text_color: "Secondary"
        
        MDRaisedButton:
            text: "Создать БД"
            pos_hint: {"center_x": 0.5}
            on_release: app.create_db()
"""

class MusicApp(MDApp):
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        return Builder.load_string(KV)
    
    def create_db(self):
        try:
            # Простой путь для теста
            db_path = "/data/data/org.davyur.ytmus/files/test.db"
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("""CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                title TEXT
            )""")
            cursor.execute("INSERT INTO tracks (title) VALUES ('Тестовый трек')")
            conn.commit()
            
            # Проверяем
            cursor.execute("SELECT COUNT(*) FROM tracks")
            count = cursor.fetchone()[0]
            conn.close()
            
            self.root.ids.status_label.text = "БД создана!"
            self.root.ids.db_label.text = f"Треков в БД: {count}"
        except Exception as e:
            self.root.ids.status_label.text = "Ошибка!"
            self.root.ids.db_label.text = str(e)

if __name__ == "__main__":
    MusicApp().run()
