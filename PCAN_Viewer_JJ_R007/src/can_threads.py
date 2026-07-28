from PyQt5.QtCore import QThread, pyqtSignal
import datetime
import os
import time


class CANReceiverThread(QThread):
    """
    CAN 메시지를 수신하고 cantools를 이용해 디코딩하는 백그라운드 스레드
    """
    error_signal = pyqtSignal(str)
    # bytes 타입의 마샬링(Marshaling) 오류를 막기 위해 object 사용
    raw_msg_signal = pyqtSignal(float, int, object, bool, bool, bool, bool)

    def __init__(self, bus, db_messages):
        super().__init__()
        self.bus = bus
        self.db_messages = db_messages  # {can_id: cantools.Message}
        self.running = False
        self.latest_data = {}  # {signal_name: (value, unit, timestamp)}
        self.latest_msg_stats = {}  # {can_id: {"count": 0, "cycle": 0.0, "last_time": None, "data": b""}}
        
        # 타임스탬프 정규화를 위한 변수
        self._is_first_msg = True
        self._timestamp_offset = 0.0
        self._last_queue_warning_ts = 0.0

    def run(self):
        self.running = True
        while self.running:
            try:
                msg = self.bus.recv(timeout=0.1)
                if msg is None:
                    continue
                
                # --- 타임스탬프 정규화 (Timestamp Normalization) ---
                # 일부 시스템(예: Windows PCAN)에서 드라이버가 제공하는 타임스탬프는 Unix Epoch가 아닌
                # 시스템 부팅 기준일 수 있습니다. 이 로직은 최초 수신 메시지를 기준으로 CAN 타임스탬프와
                # 시스템 시간(time.time())의 오프셋을 계산하여, 모든 타임스탬프를 시스템 시간 기준으로 보정합니다.
                # 이를 통해 Linux(SocketCAN)와 Windows(PCAN) 간의 타임스탬프 기준 차이를 줄여 일관성을 높입니다.
                if self._is_first_msg and msg.timestamp > 0:
                    self._timestamp_offset = time.time() - msg.timestamp
                    self._is_first_msg = False
                
                # 계산된 오프셋을 적용합니다. (첫 메시지 수신 전까지는 오프셋이 0)
                normalized_timestamp = msg.timestamp + self._timestamp_offset
                
                # GUI 렌더링 스레드로 원본 데이터 전송 (완벽한 타입 캐스팅으로 PyQt5 충돌 차단)
                self.raw_msg_signal.emit(
                    float(normalized_timestamp), # 정규화된 타임스탬프 사용
                    int(msg.arbitration_id), 
                    bytes(msg.data), 
                    bool(msg.is_extended_id), 
                    bool(msg.is_error_frame),
                    bool(getattr(msg, 'is_fd', False)),
                    bool(msg.is_rx)
                )
                if msg.is_error_frame:
                    continue
                
                # 모든 수신 메시지 통계(Count, Cycle Time, Data) 업데이트
                can_id = msg.arbitration_id
                now = normalized_timestamp # 정규화된 타임스탬프 사용
                stats = self.latest_msg_stats.get(can_id, {"count": 0, "cycle": 0.0, "last_time": None, "data": b"", "is_fd": False, "direction": 'Rx'})
                stats["count"] += 1
                if stats["last_time"] is not None:
                    stats["cycle"] = (now - stats["last_time"]) * 1000.0
                stats["last_time"] = now
                stats["data"] = msg.data
                stats["is_fd"] = getattr(msg, 'is_fd', False)
                stats["direction"] = 'Rx' if msg.is_rx else 'Tx'
                self.latest_msg_stats[can_id] = stats

                # 수신된 CAN ID가 등록된 DBC/SYM에 존재하는 경우 시그널 디코딩
                if can_id in self.db_messages:
                    db_msg = self.db_messages[can_id]
                    try:
                        # decode_choices=False 설정하여 NamedSignalValue(Enum) 대신 순수 수치값으로 받음
                        decoded_data = db_msg.decode(msg.data, decode_choices=False)
                        
                        # 최신 데이터 딕셔너리 갱신 (Factor, Offset 연산 완료된 값)
                        for sig_name, sig_val in decoded_data.items():
                            signal_def = db_msg.get_signal_by_name(sig_name)
                            unit = signal_def.unit if signal_def.unit else ""
                            self.latest_data[sig_name] = (sig_val, unit, now) # 정규화된 타임스탬프 사용
                    except Exception as e:
                        pass # 데이터 길이 오류 등 예외 처리
            except Exception as e:
                err_text = str(e)
                err_lower = err_text.lower()

                # 드라이버 수신 큐 지연 경고는 복구 가능한 상태이므로 연결을 끊지 않고 수신을 계속합니다.
                if "receive queue was read too late" in err_lower:
                    now = time.monotonic()
                    if now - self._last_queue_warning_ts >= 2.0:
                        self._last_queue_warning_ts = now
                        self.error_signal.emit(f"Rx Warning: {err_text}")
                    continue

                self.error_signal.emit(f"Rx Error: {err_text}")
                break

    def stop(self):
        self.running = False
        self.wait()


class LogParserThread(QThread):
    """TRC 로그 파일을 비동기로 파싱하고 DBC 포맷에 맞게 디코딩하는 백그라운드 스레드"""
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(object, object, object) # signal_data, found_msgs, raw_log_lines
    error_signal = pyqtSignal(str)

    def __init__(self, file_path, db_messages):
        super().__init__()
        self.file_path = file_path
        self.db_messages = db_messages
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        signal_data = {} # {(bus_num, can_id): {signal_name: (times[], values[])}}
        found_msgs = set()
        raw_log_lines = []
        try:
            base_time = 0.0
            fallback_base_time = 0.0
            last_offset_ms = 0.0

            try:
                fallback_base_time = os.path.getmtime(self.file_path)
            except Exception:
                fallback_base_time = datetime.datetime.now().timestamp()

            total_lines = 0
            with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for _ in f:
                    total_lines += 1
                    if self._is_cancelled:
                        return

            if total_lines <= 0:
                if not self._is_cancelled:
                    self.progress_signal.emit(100)
                    self.finished_signal.emit(signal_data, found_msgs, raw_log_lines)
                return

            with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f, start=1):
                    if self._is_cancelled:
                        break
                    
                    if i % 200 == 0:
                        self.progress_signal.emit(int(i * 100 / total_lines))

                    if line.startswith(';$STARTTIME='):
                        try:
                            ole_date = float(line.split('=')[1])
                            base_date = datetime.datetime(1899, 12, 30)
                            start_dt = base_date + datetime.timedelta(days=ole_date)
                            base_time = start_dt.timestamp()
                        except Exception:
                            pass
                        continue

                    line = line.strip()
                    if not line or line.startswith(';'):
                        continue

                    tokens = line.split()
                    
                    try:
                        if base_time == 0.0:
                            base_time = fallback_base_time

                        offset_ms = max(0.0, float(tokens[1]))
                        if raw_log_lines and offset_ms < last_offset_ms:
                            offset_ms = last_offset_ms
                        last_offset_ms = offset_ms
                        ts = base_time + (offset_ms / 1000.0)
                        
                        # Identify format and parse
                        # Format 1: PCAN-Explorer (e.g., "1) 1.004 1 100h Rx d 8 ...")
                        if len(tokens) > 6 and tokens[2].isdigit() and tokens[4] in ('Rx', 'Tx'):
                            bus_num = int(tokens[2])
                            can_id = int(tokens[3].rstrip('h'), 16)
                            dlc = int(tokens[6])
                            data = bytes.fromhex("".join(t.rstrip('h') for t in tokens[7:7+dlc]))
                            # Infer FD from DLC or BRS flag
                            msg_type = 'FD' if dlc > 8 or (len(tokens) > 7+dlc and 'BRS' in tokens[7+dlc:]) else 'DT'

                        # Format 2 & 4: PCAN-Explorer 7, PCAN-View 5, or this app's own format
                        # - PE7 / App's: "1 0.276 FB 1 0035 Rx - 13 ..."
                        # - PV5:         "1 0.276 FB   0035 Rx 32 ..."
                        elif len(tokens) > 5 and tokens[2] in ('DT', 'FD', 'ED', 'RTR', 'FB', 'FE', 'FBE', 'BR', 'EB'):
                            msg_type = tokens[2]
                            # Distinguish formats by checking for a bus number (single digit at tokens[3])
                            if len(tokens) > 7 and tokens[3].isdigit() and len(tokens[3]) == 1 and tokens[5] in ('Rx', 'Tx'): # Format with bus number
                                bus_num = int(tokens[3])
                                can_id = int(tokens[4].rstrip('h'), 16)
                                dlc = int(tokens[7])
                                data = bytes.fromhex("".join(tokens[8:8+dlc]))
                            elif tokens[4] in ('Rx', 'Tx'): # Format without bus number
                                bus_num = 1
                                can_id = int(tokens[3].rstrip('h'), 16)
                                dlc = int(tokens[5])
                                data = bytes.fromhex("".join(tokens[6:6+dlc]))
                            else:
                                continue

                        # Format 3: PCAN-View (e.g., "1) 123.4 Rx 0100 8 00 ...")
                        elif len(tokens) > 4 and tokens[2] in ('Rx', 'Tx'):
                            bus_num = 1
                            can_id = int(tokens[3].rstrip('h'), 16)
                            dlc = int(tokens[4])
                            data = bytes.fromhex("".join(tokens[5:5+dlc]))
                            msg_type = 'FD' if dlc > 8 else 'DT'
                        else:
                            continue
                        
                        log_line_data = {"timestamp": ts, "offset_ms": offset_ms, "type": msg_type, "bus": bus_num, "can_id": can_id, "dlc": dlc, "data": data}
                        raw_log_lines.append(log_line_data)

                        if bus_num in self.db_messages and can_id in self.db_messages[bus_num]:
                            found_msgs.add((bus_num, can_id))
                            db_msg = self.db_messages[bus_num][can_id]
                            try:
                                decoded = db_msg.decode(data, decode_choices=False)
                                key = (bus_num, can_id)
                                if key not in signal_data: signal_data[key] = {}
                                for sig_name, val in decoded.items():
                                    if not isinstance(val, (int, float)): continue
                                    if sig_name not in signal_data[key]: signal_data[key][sig_name] = ([], [])
                                    signal_data[key][sig_name][0].append(ts)
                                    signal_data[key][sig_name][1].append(float(val))
                            except Exception: pass
                    except (ValueError, IndexError):
                        continue

            if not self._is_cancelled:
                self.progress_signal.emit(100)
                self.finished_signal.emit(signal_data, found_msgs, raw_log_lines)
        except Exception as e:
            self.error_signal.emit(str(e))
