# HL Mando V2 VCU CAN1 패널

`HL_Mando_V2_VCU_CAN1_Monitoring.upp.json`을 유저패널에서 불러옵니다.
메인 창의 BUS1에는 `dbc/BUS1/HL_Mando_V2_VCU_CAN1_Monitoring.sym`을 로드합니다.
탭별 자식 배치 지원을 추가한 현재 소스로 실행해야 합니다. 기존 배포 EXE를 사용한다면 다시 빌드해야 합니다.

- 단일 화면 왼쪽: 도구의 탭 컨테이너 안에 수신 ID별 13개 탭, 전체 80개 신호 표시.
- 수신 범위: 0x130~0x13D. 원본에 정의되지 않은 0x139는 제외.
- 오른쪽: 하나의 송신 그룹에 0x100의 Alive Counter를 제외한 12개 신호를 숫자 입력으로 배치.
- 송신 등록: BUS1, 표준 Classic CAN, 8바이트, SYM 기준 20ms 주기.
- Alive Counter: 도구 없이 등록 패킷의 `signal_counters`에 Upcount, raw 0~15, step 1 설정.
- 초기 데이터는 모두 0. 로드 시 STANDBY, RUN 초기화는 전체 주기 송신 STOP.
- RUN 진입 후 값을 설정하고 START 0x100 시퀀스를 실행하면 주기 송신 시작. STOP 0x100으로 정지.
- 신호 범위·스케일·부호·단위는 SYM을 사용하며, Min/Max가 없으면 비트 표현 범위에서 계산. TX 신호에 없는 ENUM 의미는 추정하지 않고 숫자로 입력.
- 통신 속도와 장치 연결 설정은 패널에 지정하지 않음.

검증: 실제 SYM 파싱, 패킷/도구 검증, 패널 로드, 13개 탭의 자식 배치와 저장 필드 유지 확인. 관련 단위 테스트 8개 통과. 실제 CAN 송수신과 장치 연결은 수행하지 않았습니다. 화면 글꼴·가독성은 실제 앱에서 확인이 필요합니다.

재생성 및 검증은 프로젝트 폴더에서 `../.venv/Scripts/python.exe USER_PANEL/build_mando_panel.py`를 실행합니다.
