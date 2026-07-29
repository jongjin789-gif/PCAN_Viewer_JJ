import sys
import os
import json
import platform
import ctypes
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from src.main_window import UniversalCANMonitor

# User panel edit-mode password settings (modifiable by code)
USER_PANEL_EDIT_PASSWORD_ENABLED = True
USER_PANEL_EDIT_PASSWORD = "1234"

def get_viewer_mode():
    """PCAN_Viewer_JJ.pk 파일의 최상단에서 viewer_mode_only 값을 읽어옵니다."""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    pk_path = os.path.join(base_dir, "PCAN_Viewer_JJ.pk")
    viewer_only = False
    
    if os.path.exists(pk_path):
        try:
            with open(pk_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and "viewer_mode_only" in data:
                    viewer_only = bool(data["viewer_mode_only"])
        except Exception:
            pass
            
    return viewer_only

if __name__ == '__main__':
    if platform.system() == 'Windows':
        try:
            myappid = 'mycompany.myproduct.subproduct.version'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
            
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
            
    app = QApplication(sys.argv)
    app.setStyle("Fusion") 
    
    viewer_mode = get_viewer_mode()
    window = UniversalCANMonitor(
        viewer_only=viewer_mode,
        user_panel_security={
            "enabled": USER_PANEL_EDIT_PASSWORD_ENABLED,
            "password": USER_PANEL_EDIT_PASSWORD,
        },
    )
    window.show()
    sys.exit(app.exec_())