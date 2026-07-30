# Universal CAN Monitor (PCAN_Viewer_JJ_R007)

**Universal CAN Monitor**는 Python 및 PyQt5 기반으로 제작된 크로스 플랫폼 CAN 통신 모니터링 및 분석 도구입니다. Windows의 PCAN과 Linux의 SocketCAN 환경을 모두 완벽하게 지원하며, 데이터베이스(.dbc, .sym) 연동을 통한 실시간 시그널 디코딩 및 시계열 그래프 기능을 제공합니다.

---

## ✨ 주요 기능 (Features)

- **크로스 플랫폼 지원**: Windows(PEAK-System PCAN) 및 Linux(SocketCAN / vcan) 환경에서 동일한 UI 및 기능 제공.
- **멀티 채널 모니터링**: 최대 3개의 CAN 버스 채널을 동시에 연결하고 모니터링 가능.
- **CAN FD 지원**: Classic CAN 뿐만 아니라 CAN FD(Flexible Data-rate) 통신 및 ISO/Non-ISO, Data Bitrate 설정 지원.
- **CAN 송신 (Tx) 및 패킷 관리**: 송신 패킷을 생성하여 CAN/FD 프레임 전송 가능. DBC 심볼과 연동하여 물리 값을 입력하면 자동으로 Raw Data(HEX) 연산 처리. Cycle Time 지원, 단축키(스페이스바 단발 전송, Ctrl+C/V 복사 붙여넣기, Delete 삭제) 지원, `.xmt` 파일 저장/불러오기 지원.
- **자동 상태 저장 및 복구**: 프로그램 사용 중 연결한 CAN 하드웨어/속도, 등록된 데이터베이스 목록, 송신부 패킷 리스트가 `PCAN_Viewer_JJ.pk` 파일에 자동 저장되며 프로그램 재시작 시 이전 작업 상태를 완벽하게 복구 및 자동 연결.
- **데이터베이스(DBC/SYM) 연동**: `.dbc` 파일 및 PEAK `.sym` 파일(v5.0, v6.0)을 불러와 Raw CAN 데이터를 물리 값(Physical Value)으로 실시간 자동 변환. 메시지(부모) 체크박스를 통해 하위 시그널 일괄 선택/해제 기능 지원.
- **실시간 그래프 렌더링**: pyqtgraph를 활용하여 트리에서 체크된 여러 시그널을 하나의 통합된 그래프에서 모니터링. **범례 순서 드래그 앤 드롭 변경, 선 색상 및 스타일 커스터마이징** 등 강화된 편집 기능 제공.
- **데이터 로깅 (Record)**: 실시간으로 수신되는 메시지를 `.trc` (Trace) 파일 포맷으로 저장 기능 제공.
- **TRC 로그 뷰어 (Log Viewer)**: 저장된 `.trc` 로그 파일을 오프라인에서 불러와 DBC/SYM 파일을 기준으로 재해석(Parsing)하여 분석할 수 있는 내장 뷰어 제공.
- **독립 뷰어 모드 (Log Viewer Mode)**: `PCAN_Viewer_JJ.pk` 설정 파일의 `"viewer_mode_only"` 값을 `true`로 변경하여 하드웨어 연결 및 송신(Tx) 기능이 숨겨진 뷰어 전용 UI로 전환할 수 있습니다. (뷰어 모드 시 기존 패킷/설정 데이터 덮어쓰기 보호)
- **타이틀 바 버전 표시**: 실행 파일명 또는 빌드 스크립트를 인식하여 타이틀 바에 현재 프로그램의 버전(예: `R006`)이 자동으로 표시됩니다.

---

## ⚙️ 시스템 요구 사항 및 설치 (Installation)

이 프로젝트는 **Python 3.8 이상** 환경에서 구동됩니다.

### 🪟 Windows 환경
1. **사전 준비**: PEAK-System PCAN 드라이버가 설치되어 있어야 합니다. (PCAN-USB 등 연결 필요)
2. **의존성 패키지 자동 설치**: 프로젝트 폴더 내의 `install_windows.bat` 파일을 **관리자 권한으로 실행**합니다.
   - 자동으로 `venv_win` 가상환경이 생성되고 필요한 파이썬 패키지들이 한 번에 설치됩니다.

### 🐧 Linux (Ubuntu/Debian) 환경
소스 코드를 직접 실행하기 위한 개발 환경 설정 가이드입니다.

1. **의존성 설치 스크립트 실행 (최초 1회)**
   - 프로젝트 폴더에서 아래 스크립트를 실행하면, 개발에 필요한 시스템 패키지와 Python 라이브러리가 자동으로 설치되고 `venv_linux` 가상환경이 생성됩니다.
```bash
# 스크립트에 실행 권한을 부여하고 실행합니다.
chmod +x install_linux.sh
./install_linux.sh
```
*참고: 위 스크립트는 PCAN 드라이버 자체를 설치하지 않습니다. 실제 하드웨어(can0) 외에 가상 CAN(vcan0) 테스트도 가능합니다.*

---

## 🚀 사용법 (Usage)

1. **프로그램 실행**:
   - Windows: 터미널에서 `venv_win\Scripts\activate` 입력 후 `python main.py` 실행
   - Linux (가상 CAN): 터미널에서 `source venv_linux/bin/activate && python3 main.py` 실행
   - Linux (실제 CAN): `ip link` 등 하드웨어 제어를 위해 root 권한이 필요합니다. `sudo`로 실행해야 합니다. 아래의 **권장 방식**을 사용하세요.

     - **권장 방식 (가장 안정적)**:
       - `sudo`는 보안상의 이유로 현재 사용자의 가상환경을 무시하고 시스템 기본 Python으로 스크립트를 실행하는 경우가 많습니다. 이로 인해 가상환경에 설치된 라이브러리(`cantools` 등)를 찾지 못하는 `ModuleNotFoundError`가 발생합니다.
       - 이를 해결하는 가장 확실한 방법은 아래와 같이 **가상환경 내부의 파이썬 실행 파일을 명시적으로 지정**하여 `sudo`로 실행하는 것입니다.
       - ```bash
         sudo ./venv_linux/bin/python3 main.py
         ```

     - **대안 (시스템 설정에 따라 실패할 수 있음)**:
       - `sudo -E` 옵션은 현재 사용자의 환경 변수(`PATH`, `VIRTUAL_ENV` 등)를 유지하면서 명령을 실행하려고 시도합니다.
       - `source venv_linux/bin/activate && sudo -E python3 main.py`
       - **주의**: 이 방식은 시스템의 `/etc/sudoers` 설정(특히 `secure_path`)에 따라 `PATH`가 초기화되어 실패할 수 있으므로 권장 방식만큼 신뢰성이 높지 않습니다.

2. **상세 사용법**:
   - 프로그램의 모든 기능에 대한 자세한 설명은 **MANUAL.md (사용자 매뉴얼)** 파일을 참고하세요.
   - User Panel 인수 점검은 **USER_PANEL_ACCEPTANCE_CHECKLIST.md**를 참고하세요.
   - User Panel 변경 요약은 **USER_PANEL_RELEASE_NOTES.md**를 참고하세요.

3. **채널 연결 (Connection)**:
   - 상단의 **Connection Control** 패널에서 사용하려는 Bus의 채널과 통신 속도(Baudrate)를 선택합니다.
   - CAN FD 채널인 경우 FD 체크박스 및 Data Baudrate 옵션이 활성화됩니다.
   - **Open** 버튼을 클릭하여 통신을 시작합니다.

4. **데이터베이스 파일 적용**:
   - **Database Files** 패널에서 **Load DBC/SYM** 버튼을 클릭하여 해당 Bus에 맞는 DB 파일을 로드합니다.
   - DB 파일이 로드되면, 수신되는 CAN Raw ID가 트리에서 메시지 이름 및 하위 시그널로 묶여 표시됩니다.

5. **송신 (Write) 패킷 생성 및 전송**:
   - 메인 창 하단의 패널에서 **패킷 생성하기**를 눌러 전송할 데이터를 기입합니다. DB 심볼을 선택하면 하위 항목에 값을 바로 기입할 수 있습니다.
   - 생성된 패킷을 선택하고 **스페이스바**를 누르면 1회 전송되며, **Start** 버튼을 누르면 설정된 Cycle Time에 맞춰 주기적으로 전송됩니다.
   - 여러 패킷을 선택해 단축키로 지우거나(`Delete`) 복사(`Ctrl+C` / `Ctrl+V`)할 수 있습니다.
   - `PCAN-Explorer`, `PCAN-View`에서 생성한 `.xmt` 송신 목록 파일을 불러오거나 현재 목록을 저장할 수 있습니다.

6. **실시간 그래프 뷰어**:
   - 모니터링 트리 하위의 Signal 체크박스를 클릭하여 활성화합니다.
   - **[선택된 항목 실시간 그래프 보기]** 버튼을 클릭하여 시계열 데이터의 변화를 확인합니다.

7. **데이터 기록 및 로그 확인**:
   - **Record** 버튼을 눌러 모니터링 중인 데이터를 `.trc` 파일로 기록합니다.
   - 기록이 완료된 후 **Open TRC Log Viewer** 버튼을 눌러 기록된 데이터를 분석할 수 있습니다.

---

## 🛠️ 배포 및 빌드 (Build Executable)

이 프로그램은 `PyInstaller`를 이용해 파이썬이 설치되지 않은 환경에서도 실행 가능한 단일 독립 실행 파일(.exe, 로컬 바이너리)로 빌드할 수 있습니다.

1. 터미널(또는 명령 프롬프트)에서 운영체제에 맞는 가상환경을 활성화한 후 빌드 스크립트를 실행합니다.
   
   **Windows**:
   ```cmd
   venv_win\Scripts\activate
   python build_exe.py
   ```
   
   **Linux**:
   ```bash
   source venv_linux/bin/activate
   python build_exe.py
   ```
2. 빌드가 성공적으로 완료되면 프로젝트 폴더 내 `dist` 디렉토리 하위에 플랫폼별 배포 폴더가 생성됩니다.
   - Windows: `dist/PCAN_Viewer_JJ_R007_win/PCAN_Viewer_JJ_R007_win.exe`
   - Linux: `dist/PCAN_Viewer_JJ_R007_linux/PCAN_Viewer_JJ_R007_linux` (리눅스용 README 파일 포함)

*(빌드 스크립트는 PCANBasic.dll 및 아이콘 파일 등 필요 리소스들을 실행 파일 내부에 자동으로 함께 패키징하도록 설계되어 있습니다.)*