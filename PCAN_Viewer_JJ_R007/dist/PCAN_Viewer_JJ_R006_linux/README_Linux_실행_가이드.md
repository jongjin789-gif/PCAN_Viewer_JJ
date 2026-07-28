# PCAN Viewer JJ - 리눅스 환경 실행 가이드

이 프로그램은 파이썬 가상환경(venv)이나 추가 라이브러리 설치 없이 바로 실행 가능한 독립 바이너리 파일입니다.
단, 리눅스의 디스플레이(GUI) 출력 및 SocketCAN 제어를 위해 타겟 PC에 최소한의 OS 필수 패키지가 설치되어 있어야 합니다.

## 🛠️ 1. 필수 시스템 패키지 설치 (최초 1회)
프로그램을 실행할 리눅스 PC(Ubuntu/Debian 기준)의 터미널을 열고 아래 명령어를 복사하여 실행해 주세요.

```bash
sudo apt-get update
sudo apt-get install -y can-utils iproute2     libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0     libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-xfixes0     libxkbcommon-x11-0 libqt5x11extras5 fonts-nanum libopengl0
```

## 🚀 2. 실행 방법
```bash
chmod +x PCAN_Viewer_JJ_R006_linux
./PCAN_Viewer_JJ_R006_linux
```

## ⚠️ 3. (중요) 실제 CAN 하드웨어 사용 시
실제 CAN 장비(예: `can0`)에 연결하려면 `ip link` 명령어를 실행하기 위한 root 권한이 필요할 수 있습니다.
프로그램 내부에서 권한이 없을 경우 안내 메시지가 표시되지만, 처음부터 권한을 부여하여 실행하는 것이 더 편리할 수 있습니다.

```bash
sudo ./PCAN_Viewer_JJ_R006_linux
```
