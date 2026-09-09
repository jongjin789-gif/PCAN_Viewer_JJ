# User Panel Release Notes

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
