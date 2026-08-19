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
    
    # Windows에서 절전 모드 진입으로 인한 성능 저하 방지
    if platform.system() == 'Windows':
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_DISPLAY_REQUIRED = 0x00000002
        try:
            # 시스템이 절전 모드로 전환되거나 디스플레이가 꺼지는 것을 방지
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
        except Exception as e:
            print(f"[Warning] Could not prevent system sleep: {e}")

    exit_code = 1
    try:
        viewer_mode = get_viewer_mode()
        window = UniversalCANMonitor(
            viewer_only=viewer_mode,
            user_panel_security={
                "enabled": USER_PANEL_EDIT_PASSWORD_ENABLED,
                "password": USER_PANEL_EDIT_PASSWORD,
            },
        )
        window.show()
        exit_code = app.exec_()
    finally:
        # 프로그램 종료 시, 시스템 절전 방지 설정을 원래대로 복원
        if platform.system() == 'Windows':
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception as e:
                print(f"[Warning] Could not restore system sleep settings: {e}")

    sys.exit(exit_code)