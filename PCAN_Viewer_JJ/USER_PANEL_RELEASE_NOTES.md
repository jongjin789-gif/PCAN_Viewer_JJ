# User Panel Release Notes

## 패널 제목 및 하단 상태 표시

- 메인창 **보기 → 유저 패널 제목 변경…**에서 창 제목을 수정합니다. 제목은 패널 파일·패키지·자동 저장/통합 설정에 포함되며, 빈 입력은 `User Panel`로 복원합니다.
- 창 맨 아래 전체 너비의 상태 표시줄(QStatusBar)에 `BUS 1 | BUS 2 | BUS 3` 연결 상태를 왼쪽, `모드 | 송수신 상태`를 오른쪽으로 구획을 나누어 배치했습니다. 상세 오류는 시스템 로그로 확인합니다. 상단의 단축키 설명 나열을 제거했으며 단축키 기능은 유지합니다.

## 미등록 TX 도구가 있는 자동 저장 설정 복원

- TX 패킷 연결이 아직 없는 도구 때문에 프로그램 시작 시 패널 전체 복원이 실패하던 문제를 수정했습니다. 해당 패널은 STANDARD로 복원하고 시스템 로그에 등록/연결 필요 안내를 표시합니다. TX 패킷 연결을 완료하기 전까지 RUN은 차단하며, 잘못된 등록 패킷 데이터에 대한 검증은 유지합니다.

## 유저 패널 아이콘 도구 모음 (소스)

- 모드(EDIT/STANDARD/RUN/Force RUN), 통신 설정, TX 패킷 관리, INIT 설정, TX/RX/그룹·도형 생성 버튼을 한 줄의 아이콘으로 배치했습니다. 마우스를 올리면 기존 기능명을 툴팁으로 표시하며, 현재 모드는 선택 배경으로 구분합니다.
- 메인창·그래프창의 청록색/짙은 파란색 스타일에 맞춘 유저 패널 창 아이콘과 기능별 SVG 아이콘을 추가했습니다. 배포 빌드의 아이콘 리소스 폴더와 Qt SVG 의존성에 포함됩니다.

## 패널 전용 실행 · 통신 설정 · Force RUN · 시스템 로그 (소스)

- 실행 파일 옆 `PCAN_Viewer_JJ.pk`에 `"user_panel_only": true`를 설정하면 메인창을 표시하지 않고 유저 패널만 엽니다. 기본값은 false이며, true일 때 기존 `viewer_mode_only`보다 우선합니다. 창 안에서는 이 플래그를 변경할 수 없습니다. 패널 전용 모드에서 패널을 닫으면 송신·수신 처리와 버스 연결을 정리하고 프로그램을 종료합니다.
- 패널은 STANDARD로 시작합니다. 패널을 여는 것만으로 기존 버스를 연결/해제하지 않으며, 메인창의 실제 연결 상태를 공유합니다. 이전 세션의 통신·DBC·패널 설정 복원과 자동 저장은 유지됩니다. 복원된 메인 TX 패킷은 정지 상태입니다.
- **통신 설정 / DBC**에서 BUS 1·2·3의 장치 검색, 연결/해제, Nominal/Data bitrate, FD ISO 설정과 DBC/SYM 등록/해제를 수행합니다. 연결 중 설정은 잠기고, 실제 변경 전에 패널 송신을 STANDARD로 정지합니다. 창을 여는 것만으로 정지하지 않습니다.
- EDIT 비밀번호와 통신 비밀번호는 `main.py`의 `USER_PANEL_EDIT_PASSWORD`, `USER_PANEL_COMMUNICATION_PASSWORD`로 독립 관리하며 초기값은 각각 `1234`입니다. 통신 설정창을 열 때마다 인증하며, Force RUN도 매번 통신 비밀번호가 필요합니다. 속성창에서 통신 속도 변경 및 DBC 포함 패키지 불러오기에도 통신 인증을 적용합니다.
- 일반 RUN은 INIT의 CMD/RCV 및 START 대상 버스의 연결/Classic·FD 타입을 사전 검사하고 INIT을 처음부터 실행합니다. INIT에서 RCV 등록/응답 비교를 지원하며, 실패·시간 초과·실행 중 연결 해제 시 STANDARD로 복귀하고 일반 송신을 시작하지 않습니다.
- **Force RUN**은 INIT의 CMD·RCV·DEL을 생략하고 START·STOP만 원래 순서대로 적용합니다. 지정되지 않은 패킷은 기존 RUN의 기본 송신 정책을 따릅니다. INIT 성공으로 기록하지 않으며 미연결·Classic/FD 불일치 송신 차단을 유지합니다. Force는 현재 실행에만 적용되고, 이후 일반 RUN에서는 INIT을 다시 실행합니다.
- 패널 하단 **시스템 로그**에 모드/송신 정지, INIT 진행·결과, Force/인증, 통신 상태·오류 및 설정 파일 처리 결과를 표시합니다. 최대 2,000줄, 연속 반복 이벤트 묶음, 높이 조절, 전체 복사·파일 저장·지우기를 지원합니다. 비밀번호는 기록하지 않습니다.
- STANDARD는 유저 패널 송신 정지이며, 일반 모드에서 메인창이 별도로 실행한 TX까지 정지시키지는 않습니다. 실행 파일 배포에는 소스 재빌드가 필요합니다.

## 슬라이더·버튼·토글 멀티 명령 (소스)

- 등록 패킷의 실제 송신 단계에서 버스 연결 및 연결 모드와 패킷의 Classic/FD 일치를 검사합니다. 미연결·타입 불일치·드라이버 송신 오류는 해당 패킷을 차단하며, 멀티 명령의 나머지 정상 채널은 등록 순서와 관계없이 계속 전송합니다. 차단 사유는 패널 상태 영역에 표시합니다.
- 즉시 송신 실패 시 이전 패킷 값을 유지하므로, 연결/설정 복구 후 같은 값을 다시 조작하여 재시도할 수 있습니다. 실패 명령을 자동 재전송하지 않습니다. 주기 송신 오류는 해당 패킷 타이머만 정지합니다.
- EDIT에서 도구를 선택하고 Tool Properties의 **멀티 명령 → 추가**로 명령을 등록합니다. 각 명령에 별도 CAN BUS, 등록 TX 패킷, 신호/비트 및 동작 값을 지정할 수 있습니다.
- 기본 명령과 추가 명령의 체크박스로 활성 여부를 선택한 뒤 **Apply Properties**를 누릅니다. 추가 명령은 수정·삭제할 수 있으며, 설정과 체크 상태는 저장·불러오기·복사·실행 취소에 포함됩니다.
- 슬라이더는 현재 표시 값을 모든 활성 명령에 적용합니다. 범위·Resolution·Home 초기값은 기본 도구 설정을 사용합니다. 버튼은 명령별 누름/해제 값, 토글은 명령별 ON/OFF 값을 적용합니다.
- 같은 패킷의 여러 신호는 모두 반영한 뒤 전송합니다. 기존과 같이 주기 0 패킷은 값 변경 시 전송하고, 주기 패킷은 설정된 송신 주기를 따릅니다. 체크 해제는 도구의 값 적용을 제외하는 설정이며, 등록 패킷의 주기 송신을 정지하거나 기존 값을 초기화하지 않습니다.
- 기존 단일 명령 도구는 기본 명령 활성 상태로 호환됩니다.

## 속성창 편집 업데이트 (소스)

- 생성창은 유지하고 기존 도구 편집은 오른쪽 Tool Properties로 변경. 위치·크기·CAN/DBC·신호·동작 속성 및 시퀀스 상세 편집 지원.
- Ctrl/Shift 다중 선택, 혼합값 표시, 체크한 공통 속성만 일괄 적용. CAN BUS 속도는 연결 해제 상태에서 메인창 설정과 함께 변경.
- DBC 없는 패널 재로드 및 비트 직접 편집 지원. 저장된 Start Bit/Length 보존, DBC 신호 자동 매칭과 Unknown 표시.
- 일반 도구의 Motorola(big-endian) 정수 비트 인코딩/디코딩 추가. 오버랩 검사도 실제 비트 위치를 사용.
- 아래 R008 배포 당시의 little-endian 제한은 이번 소스 업데이트에서 해제됨. 실행 파일은 별도 재빌드 필요.

## R008 업데이트

버전 기준: `build_exe.py`의 `APP_VERSION = "R008"`. 소스 폴더명 `PCAN_Viewer_JJ_R007`은 유지합니다.

### 새 기능

- CMD/RCV/DEL 시퀀스 도구: 단계 삽입·삭제·순서 변경, 명령어/응답 이름, 실행/정지/처음부터 재실행.
- 메인 패킷 생성창을 재사용한 Classic/FD·BRS·CRC·주기 설정 및 반복 횟수 지원.
- DBC 없이 CMD HEX/비트 수정, RCV `X/0/1` 마스크 수정. 같은 ID의 여러 신호를 하나의 응답 조건으로 비교.
- 시퀀스를 패널 Save에 포함. 상태별 버튼 색상, 진행/오류/전체 완료 색상 로그와 로그 지우기.
- 로그 형식: `[시간] 현재순번/전체개수 종류 BUS CAN_ID 이름 · 상태`. 패킷 바이트는 출력하지 않음. Standard ID는 3자리, Extended는 8자리.
- 일반 패널 도구에도 Classic/FD 및 BRS 설정 추가. 8바이트 이하 FD 송신 지원.
- 슬라이더 Resolution에 따른 표시 자릿수, Initial Value 및 왼쪽 Home 버튼.
- 로그 뷰어 Extended 필터(최대 0x1FFFFFFF), 필터 결과만 재전송, LOG 탭 Save로 원본 행 추출 및 메시지 번호 재부여.
- 전체 UI 기본 글꼴 Consolas 적용.

### 수정 및 동작 변경

- 버튼/토글의 DBC 선택값이 설정창 종료 후 기본 1/0으로 저장되던 오류 수정.
- 같은 신호의 토글은 상호 해제하며 자동 해제 시 OFF 값은 송신하지 않음.
- 격자 최소 32×32 유지, 작은 창에서는 스크롤, 큰 창에서는 격자·도구 확대.
- 일반 도구 최소 Row Span 3 → 2. Home 버튼은 왼쪽에서 슬라이더와 값 표시의 두 행을 차지.
- 패널 닫기·모드 변경 시 패널의 모든 송신 및 시퀀스 대기를 중지. 자동 재개하지 않음.

### 검증 및 배포

- Python 3.13 환경의 자동 테스트 16개 통과. 실제 CAN 장비 검증 및 R008 바이너리 검증은 별도 수행 필요.
- `python build_exe.py` 실행 후 Windows는 `dist/PCAN_Viewer_JJ_R008_win/PCAN_Viewer_JJ_R008_win.exe` 사용.
- Linux는 `dist/PCAN_Viewer_JJ_R008_linux/PCAN_Viewer_JJ_R008_linux` 사용.
- 일반 패널 fallback 인코딩의 little-endian 제한은 유지. 시퀀스는 저장된 바이트/마스크로 실행.

---

## R007 이전 기록

## Version Scope
- Project: PCAN_Viewer_JJ_R007
- Area: User Panel (v2 modular architecture)
- Date: 2026-07-30

## What Was Added
- Mode state machine: EDIT / STANDBY / RUN.
- Edit mode password gate integration from main configuration.
- TX/RX tool split creation flow.
- Group/Tab parent-child composition.
- Shape tools and draw mode (rect/line).
- Drag move + bottom-right drag resize.
- Numeric geometry editor (row/col/row_span/col_span).
- Z-order controls (front/back/forward/backward).
- TX overlap diagnostics with list highlighting and conflict focus navigation.
- Per-frame TX staging/flush policy and cycle mode support.
- Package persistence: .pjjupkg with panel JSON + DB bundle.
- CAN-free RX simulator (manual apply + auto simulation).

## Behavior Changes
- TX emission path now stages values by frame and flushes with policy-aware timers.
- Widgets using same frame can operate together without immediate overwrite.
- Edit operations are restricted by mode and optional password policy.

## Compatibility
- Existing import path compatibility preserved through wrapper module.
- Existing main window DB handling remains compatible with package load replacement flow.

## Operational Notes
- Use STANDBY for validation without TX output.
- Use RUN for full TX/RX runtime.
- Run overlap check after adding/editing any TX mapping.

## Known Limitations
- Fallback bit-packing path currently supports little-endian only.
- Big-endian fallback encoding is not yet implemented.
- Final acceptance with real CAN hardware is still required.

## Recommended Validation Path
1. Execute USER_PANEL_ACCEPTANCE_CHECKLIST.md.
2. Record results in USER_PANEL_TEST_REPORT_TEMPLATE.md.
3. Confirm no critical FAIL/BLOCKED before release.
