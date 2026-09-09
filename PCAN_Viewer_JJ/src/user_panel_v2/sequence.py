"""DBC-independent sequence execution and panel control."""
import copy
import time
from datetime import datetime

import can
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QTextCursor, QTextCharFormat
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QTextEdit, QAction
from src.crc_utils import calculate_crc16_ccitt_false


def format_can_id(packet):
    can_id = int(packet['id'])
    width = 8 if packet.get('is_extended_id', can_id > 0x7FF) else 3
    return f"0x{can_id:0{width}X}"


def validate_steps(steps):
    if not steps:
        raise ValueError("Sequence has no steps.")
    for index, step in enumerate(steps, 1):
        kind = step.get("kind")
        if kind == "DEL":
            if not 0 <= int(step.get("delay_ms", -1)) <= 600000:
                raise ValueError(f"Step {index}: invalid delay.")
            continue
        if kind not in ("CMD", "RCV") or not step.get("packet"):
            raise ValueError(f"Step {index}: configure a packet.")
        p = step["packet"]
        n = int(p["length"])
        if not 0 <= int(p["id"]) <= (0x1FFFFFFF if p.get("is_extended_id", p["id"] > 0x7FF) else 0x7FF):
            raise ValueError(f"Step {index}: invalid CAN ID.")
        if n not in (list(range(9)) + ([12, 16, 20, 24, 32, 48, 64] if p.get("is_fd") else [])):
            raise ValueError(f"Step {index}: invalid packet length.")
        if len(p["data"]) != n or any(not 0 <= int(b) <= 255 for b in p["data"]):
            raise ValueError(f"Step {index}: invalid data.")
        if p.get("is_brs") and not p.get("is_fd"):
            raise ValueError("BRS requires FD.")
        if kind == "RCV":
            mask = step.get("mask", [])
            if len(mask) != n or not any(mask) or any(not 0 <= int(b) <= 255 for b in mask):
                raise ValueError(f"Step {index}: select at least one comparison bit.")
            if not 1 <= int(step.get("timeout_ms", 0)) <= 600000:
                raise ValueError(f"Step {index}: invalid timeout.")
        else:
            if not 1 <= int(step.get("repeat", 1)) <= 10000 or not 0 <= int(p.get("cycle", 0)) <= 600000:
                raise ValueError(f"Step {index}: invalid repeat/cycle.")
            if p.get("crc_type") not in (None, "N/A", "Hyundai_CRC"):
                raise ValueError("Unsupported CRC type.")
            if p.get("crc_type") == "Hyundai_CRC" and (n < 3 or p["id"] + 0xF800 > 65535):
                raise ValueError("Hyundai CRC requires at least 3 bytes and a compatible ID.")


class SequenceControl(QWidget):
    COLORS = {"ready": "#245A81", "run": "#00695C", "receive": "#F2B544",
              "delay": "#6A4594", "stop": "#59636E", "done": "#237541", "error": "#B3261E"}
    def __init__(self, owner, cfg):
        super().__init__()
        self.owner, self.cfg = owner, cfg
        self.running = False
        self.index = -1
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._tick)
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(100)
        self.watchdog.timeout.connect(self._check_connection)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton()
        self.button.clicked.connect(self.toggle)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("background:white; color:black;")
        self.log.document().setMaximumBlockCount(2000)
        clear = QAction("로그 지우기", self.log)
        clear.triggered.connect(self.log.clear)
        self.log.addAction(clear)
        from PyQt5.QtCore import Qt
        self.log.setContextMenuPolicy(Qt.ActionsContextMenu)
        layout.addWidget(self.button)
        layout.addWidget(self.log, 1)
        self._state("ready", "실행")

    def _state(self, state, label):
        self.button.setText(f"{self.cfg.get('title', 'Sequence')} · {label}")
        color = "black" if state == "receive" else "white"
        self.button.setStyleSheet(f"background:{self.COLORS[state]}; color:{color}; padding:4px;")

    def write(self, message, color="black"):
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(f"[{stamp}] {message}", fmt)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def step_log(self, status):
        step = self.steps[self.index]
        p = step.get('packet', {})
        bus = f"BUS_{p['bus']}" if p else "-"
        can_id = format_can_id(p) if p else "-"
        name = step.get('name', '').strip() or "이름 없음"
        return f"{self.index + 1}/{len(self.steps)} {step['kind']} {bus} {can_id} {name} · {status}"

    def stop(self, reason="사용자 정지"):
        was_running = self.running
        self.running = False
        self.timer.stop()
        self.watchdog.stop()
        if was_running:
            self.write(reason)
            self._state("stop", "정지됨 · 재실행")

    def fail(self, message):
        self.stop("실행 중단")
        self.write(message, "#B3261E")
        self._state("error", "오류 · 재실행")

    def _check_connection(self):
        if not self.running:
            return
        if self.owner.mode != "run" or not self.owner.isVisible():
            self.stop("패널 상태 변경")
        elif any(self.owner.main_window.buses.get(bus) is None for bus in self.required_buses):
            self.fail("CAN 연결 해제")

    def toggle(self):
        if self.running:
            self.stop()
            return
        if self.owner.mode != "run":
            return
        try:
            self.steps = copy.deepcopy(self.cfg.get("binding", {}).get("sequence_steps", []))
            validate_steps(self.steps)
            main = self.owner.main_window
            self.required_buses = {s["packet"]["bus"] for s in self.steps if s["kind"] != "DEL"}
            for s in self.steps:
                if s["kind"] == "DEL":
                    continue
                p = s["packet"]
                if main.buses.get(p["bus"]) is None:
                    raise ValueError(f"Bus {p['bus']} is not connected.")
                if p.get("is_fd") and not main.bus_capabilities[p["bus"]].get("is_fd"):
                    raise ValueError(f"Bus {p['bus']} requires FD mode.")
        except Exception as exc:
            self.fail(str(exc))
            return
        self.running = True
        self.index = -1
        self.started = time.time()
        self.last_receive = "수신 없음"
        self.write("--- 시퀀스 시작 ---")
        self.watchdog.start()
        self._next()

    def _next(self):
        if not self.running:
            return
        previous = self.steps[self.index]["kind"] if self.index >= 0 else None
        self.index += 1
        if self.index == len(self.steps):
            self.running = False
            self.watchdog.stop()
            self.write("전체 과정 완료", "#237541")
            self._state("done", "완료 · 재실행")
            return
        step = self.steps[self.index]
        kind = step["kind"]
        if kind == "CMD":
            self._state("run", "실행 중 · 정지")
            self.remaining = int(step.get("repeat", 1))
            self.response_floor = time.time()
            self.pending_match = False
            self.last_receive = "수신 없음"
            self._send()
        elif kind == "DEL":
            self.write(self.step_log(f"{step['delay_ms']} ms 대기"))
            self._state("delay", "지연 중 · 정지")
            self.timer.start(int(step["delay_ms"]))
        else:
            self._state("receive", "응답 대기 · 정지")
            if previous != "CMD":
                self.response_floor = time.time()
                self.pending_match = False
                self.last_receive = "수신 없음"
            self.write(self.step_log(f"응답 대기 / 제한 {step['timeout_ms']} ms"))
            self.deadline = time.time() + step['timeout_ms'] / 1000.0
            if self.pending_match:
                self.write(self.step_log("응답 조건 일치"))
                self.timer.start(0)
                self.matched = True
            else:
                self.matched = False
                self.timer.start(int(step["timeout_ms"]))

    def _send(self):
        try:
            p = self.steps[self.index]["packet"]
            payload = bytes(p["data"])
            if p.get("crc_type") == "Hyundai_CRC":
                alive = p.get("alive_counter", 0)
                p["alive_counter"] = (alive + 1) % 256
                body = bytes([alive]) + payload[3:]
                crc = calculate_crc16_ccitt_false(body + (0xF800 + p["id"]).to_bytes(2, "little"))
                payload = crc.to_bytes(2, "little") + body
            msg = can.Message(arbitration_id=p["id"], data=payload,
                              is_extended_id=p.get("is_extended_id", p["id"] > 0x7FF),
                              is_fd=p.get("is_fd", False), bitrate_switch=p.get("is_brs", False), check=True)
            self.owner.main_window.buses[p["bus"]].send(msg)
            self.owner.main_window.record_tx_activity(p["bus"], p["id"], payload, msg.is_fd)
            self.write(self.step_log("송신 완료"))
            self.remaining -= 1
            self.timer.start(int(p.get("cycle", 0)) if self.remaining else 0)
        except Exception as exc:
            self.fail(self.step_log(f"송신 실패: {exc}"))

    def _tick(self):
        if not self.running:
            return
        kind = self.steps[self.index]["kind"]
        if kind == "CMD" and self.remaining:
            self._send()
        elif kind == "RCV" and not self.matched:
            self.fail(self.step_log("RCV 타임아웃"))
        else:
            self._next()

    def receive(self, ts, bus, can_id, data, extended, fd, brs=False):
        if not self.running or ts < max(self.started, getattr(self, "response_floor", self.started)):
            return
        idx = self.index
        if self.steps[idx]["kind"] == "CMD":
            idx += 1
        if idx >= len(self.steps) or self.steps[idx]["kind"] != "RCV":
            return
        if idx == self.index and ts > self.deadline:
            return
        s = self.steps[idx]
        p = s["packet"]
        if (bus, can_id, extended, fd, brs) != (p["bus"], p["id"], p.get("is_extended_id", p["id"] > 0x7FF), p.get("is_fd", False), p.get("is_brs", False)):
            return
        self.last_receive = bytes(data).hex(" ").upper()
        if len(data) != p["length"] or not all((a & m) == (b & m) for a, b, m in zip(data, p["data"], s["mask"])):
            return
        self.pending_match = True
        if idx == self.index and not self.matched:
            self.matched = True
            self.write(self.step_log("응답 조건 일치"))
            self.timer.start(0)
