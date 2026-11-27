from kivy.lang import Builder
from kivymd.app import MDApp

KV = """
MDScreen:
    MDBoxLayout:
        orientation: "vertical"
        
        MDTopAppBar:
            title: "YTmus"
        
        MDLabel:
            text: "Приложение работает! 🎉"
            halign: "center"
            theme_text_color: "Primary"
        
        MDLabel:
            text: "Версия 1.1.0"
            halign: "center"
            theme_text_color: "Secondary"
        
        MDRaisedButton:
            text: "Нажми меня"
            pos_hint: {"center_x": 0.5}
            on_release: app.on_button()
"""

class MusicApp(MDApp):
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        return Builder.load_string(KV)
    
    def on_button(self):
        print("Кнопка нажата!")

if __name__ == "__main__":
    MusicApp().run()
