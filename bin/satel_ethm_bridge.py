#!/usr/bin/env python3
import json
import os
import select
import signal
import socket
import sys
import time
from datetime import datetime

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except Exception:
    Cipher = None
    algorithms = None
    modes = None

PLUGIN = "satel_ethm"
DEFAULT_CONFIG = f"/opt/loxberry/data/system/{PLUGIN}/config.json"
LEGACY_CONFIGS = [
    f"/opt/loxberry/data/plugins/{PLUGIN}/config.json",
    f"/opt/loxberry/config/plugins/{PLUGIN}/config.json",
]
DEFAULT_LOG = f"/opt/loxberry/log/plugins/{PLUGIN}/satel_ethm_bridge.log"
VERSION = "0.23.0"

RUNNING = True
RUNTIME_STATE = {}
RUNTIME_LAST_WRITE = 0
RUNTIME_EVENT_LIMIT = 80


def handle_signal(signum, frame):
    global RUNNING
    RUNNING = False


def plugin_path(kind, filename):
    env_name = {
        "config": "LBPCONFIG",
        "log": "LBPLOG",
    }.get(kind)
    base = os.environ.get(env_name, "") if env_name else ""
    if base:
        return os.path.join(base, filename)
    if kind == "config":
        return DEFAULT_CONFIG
    if kind == "log":
        return DEFAULT_LOG
    raise ValueError(kind)


def log(message):
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
    try:
        os.makedirs(os.path.dirname(plugin_path("log", "")), exist_ok=True)
        with open(plugin_path("log", "satel_ethm_bridge.log"), "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass
    print(line, end="", flush=True)


def debug_log(config, message):
    if cfg_bool(config, "debug_logging", False):
        log(message)


def load_config():
    config_file = os.environ.get("SATEL_ETHM_CONFIG", DEFAULT_CONFIG)
    if not os.path.exists(config_file):
        for legacy_config in LEGACY_CONFIGS:
            if os.path.exists(legacy_config):
                config_file = legacy_config
                break
    with open(config_file, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cfg_float(config, key, default):
    try:
        return float(config.get(key, default))
    except Exception:
        return float(default)


def cfg_bool(config, key, default):
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "tak")
    return bool(value)


def config_file_path():
    return os.environ.get("SATEL_ETHM_CONFIG", DEFAULT_CONFIG)


def runtime_file_path():
    return os.path.join(os.path.dirname(config_file_path()), "runtime.json")


def write_runtime_state(force=False):
    global RUNTIME_LAST_WRITE
    now = time.time()
    if not force and now - RUNTIME_LAST_WRITE < 1.0:
        return
    RUNTIME_LAST_WRITE = now
    try:
        path = runtime_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(RUNTIME_STATE, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        pass


def update_runtime_state(values, force=False):
    RUNTIME_STATE.update(values)
    RUNTIME_STATE["updated_ts"] = int(time.time())
    RUNTIME_STATE["updated_iso"] = datetime.now().isoformat(timespec="seconds")
    write_runtime_state(force)


def runtime_event(kind, title, detail="", **fields):
    event = {
        "ts": int(time.time()),
        "iso": datetime.now().isoformat(timespec="seconds"),
        "kind": str(kind),
        "title": str(title),
        "detail": str(detail),
    }
    event.update(fields)
    return event


def runtime_events_with(event):
    events = list(RUNTIME_STATE.get("events", []))
    events.append(event)
    return events[-RUNTIME_EVENT_LIMIT:]


def add_runtime_event(kind, title, detail="", **fields):
    update_runtime_state(
        {"events": runtime_events_with(runtime_event(kind, title, detail, **fields))},
        force=True,
    )


def hex_to_bytes(value):
    cleaned = value.replace("\\x", " ").replace(",", " ").replace("-", " ")
    parts = [part for part in cleaned.split() if part]
    return bytes(int(part, 16) for part in parts)


def crc16(data):
    crc = 0x147A
    for byte in data:
        crc = ((crc << 1) | (crc >> 15)) & 0xFFFF
        crc ^= 0xFFFF
        crc = (crc + (crc >> 8) + byte) & 0xFFFF
    return crc


def escape_body(data):
    escaped = bytearray()
    for byte in data:
        escaped.append(byte)
        if byte == 0xFE:
            escaped.append(0xF0)
    return bytes(escaped)


def satel_frame(cmd, data=b""):
    body = bytes([cmd]) + bytes(data)
    crc = crc16(body)
    full = body + bytes([(crc >> 8) & 0xFF, crc & 0xFF])
    return b"\xFE\xFE" + escape_body(full) + b"\xFE\x0D"


class SatelEncryption:
    BLOCK_LENGTH = 16

    def __init__(self, integration_key):
        if Cipher is None:
            raise RuntimeError("Python module cryptography is required for ETHM integration encryption")
        self.cipher = Cipher(algorithms.AES(self.integration_key_to_encryption_key(integration_key)), modes.ECB())

    @classmethod
    def integration_key_to_encryption_key(cls, integration_key):
        key_bytes = bytes(str(integration_key), "ascii", errors="ignore")
        key = [0] * 24
        for index in range(12):
            key[index] = key[index + 12] = key_bytes[index] if len(key_bytes) > index else 0x20
        return bytes(key)

    @classmethod
    def blocks(cls, message):
        return [message[index:index + cls.BLOCK_LENGTH] for index in range(0, len(message), cls.BLOCK_LENGTH)]

    def encrypt(self, data):
        if len(data) < self.BLOCK_LENGTH:
            data += b"\x00" * (self.BLOCK_LENGTH - len(data))
        encrypted = []
        encryptor = self.cipher.encryptor()
        cv = list(encryptor.update(bytes([0] * self.BLOCK_LENGTH)))
        for block in self.blocks(data):
            part = list(block)
            if len(block) == self.BLOCK_LENGTH:
                part = [a ^ b for a, b in zip(part, cv)]
                part = list(encryptor.update(bytes(part)))
                cv = list(part)
            else:
                cv = list(encryptor.update(bytes(cv)))
                part = [a ^ b for a, b in zip(part, cv)]
            encrypted += part
        return bytes(encrypted)

    def decrypt(self, data):
        decrypted = []
        decryptor = self.cipher.decryptor()
        encryptor = self.cipher.encryptor()
        cv = list(encryptor.update(bytes([0] * self.BLOCK_LENGTH)))
        for block in self.blocks(data):
            temp = list(block)
            part = list(block)
            if len(block) == self.BLOCK_LENGTH:
                part = list(decryptor.update(bytes(part)))
                part = [a ^ b for a, b in zip(part, cv)]
                cv = list(temp)
            else:
                cv = list(encryptor.update(bytes(cv)))
                part = [a ^ b for a, b in zip(part, cv)]
            decrypted += part
        return bytes(decrypted)


class EncryptedCommunicationHandler:
    next_id_s = 0

    def __init__(self, integration_key):
        self._rolling_counter = 0
        self._id_s = EncryptedCommunicationHandler.next_id_s
        EncryptedCommunicationHandler.next_id_s = (EncryptedCommunicationHandler.next_id_s + 1) & 0xFF
        self._id_r = 0
        self._satel_encryption = SatelEncryption(integration_key)

    def _prepare_header(self):
        header = (
            os.urandom(2)
            + self._rolling_counter.to_bytes(2, "big")
            + self._id_s.to_bytes(1, "big")
            + self._id_r.to_bytes(1, "big")
        )
        self._rolling_counter = (self._rolling_counter + 1) & 0xFFFF
        self._id_s = header[4]
        return header

    def prepare_pdu(self, message):
        return self._satel_encryption.encrypt(self._prepare_header() + message)

    def extract_data_from_pdu(self, pdu):
        decrypted = self._satel_encryption.decrypt(pdu)
        header = decrypted[:6]
        data = decrypted[6:]
        self._id_r = header[4]
        if (self._id_s & 0xFF) != decrypted[5]:
            raise RuntimeError("Incorrect encrypted ETHM communication id; check integration key")
        return bytes(data)


def ethm_encryption_enabled(config):
    return cfg_bool(config, "ethm_encryption_enabled", False) and bool(str(config.get("ethm_integration_key", "")).strip())


def create_encryption_handler(config):
    if not ethm_encryption_enabled(config):
        return None
    return EncryptedCommunicationHandler(str(config.get("ethm_integration_key", "")).strip())


def prepare_transport_frame(frame, crypto=None):
    if not crypto:
        return frame
    pdu = crypto.prepare_pdu(frame)
    if len(pdu) > 255:
        raise ValueError("Encrypted ETHM PDU too long")
    return len(pdu).to_bytes(1, "big") + pdu


def trim_frame_padding(frame):
    end = frame.find(b"\xfe\x0d")
    if end >= 0:
        return frame[:end + 2]
    return frame


def extract_transport_frames(buffer, crypto=None):
    if not crypto:
        return extract_satel_frames(buffer)
    frames = []
    while len(buffer) >= 1:
        data_len = buffer[0]
        if len(buffer) < data_len + 1:
            break
        pdu = buffer[1:data_len + 1]
        frames.append(trim_frame_padding(crypto.extract_data_from_pdu(pdu)))
        buffer = buffer[data_len + 1:]
    return frames, buffer


def ascii_hex(value):
    return " ".join(f"{byte:02X}" for byte in value.encode("ascii", errors="ignore"))


def bcd_hex(value):
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) % 2:
        digits += "F"
    return " ".join(digits[index:index + 2] for index in range(0, len(digits), 2))


def expand_command_template(command_hex, config):
    code = str(config.get("satel_user_code", ""))
    return (
        command_hex
        .replace("{USER_CODE_ASCII}", ascii_hex(code))
        .replace("{USER_CODE_BCD}", bcd_hex(code))
    )


def command_code(frame):
    if len(frame) < 3 or frame[0:2] != b"\xfe\xfe":
        raise ValueError("SATEL command must start with FE FE")
    return frame[2]


def find_response_frame(buffer, cmd):
    marker = b"\xfe\xfe" + bytes([cmd])
    start = buffer.find(marker)
    if start < 0:
        return None
    end = buffer.find(b"\xfe\x0d", start + 3)
    if end < 0:
        return None
    return buffer[start:end + 2]


def pop_response_frame(buffer, cmd):
    marker = b"\xfe\xfe" + bytes([cmd])
    start = buffer.find(marker)
    if start < 0:
        return None, buffer
    end = buffer.find(b"\xfe\x0d", start + 3)
    if end < 0:
        return None, buffer
    response = buffer[start:end + 2]
    remaining = buffer[:start] + buffer[end + 2:]
    return response, remaining


def extract_satel_frames(buffer):
    frames = []
    while True:
        start = buffer.find(b"\xfe\xfe")
        if start < 0:
            return frames, b""
        if start:
            buffer = buffer[start:]
        end = buffer.find(b"\xfe\x0d", 3)
        if end < 0:
            return frames, buffer
        frames.append(buffer[:end + 2])
        buffer = buffer[end + 2:]


def query_ethm(host, port, timeout, frame, crypto=None):
    cmd = command_code(frame)
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(prepare_transport_frame(frame, crypto))
        deadline = time.time() + timeout
        buffer = b""
        decrypted = b""
        while time.time() < deadline:
            chunk = sock.recv(1024)
            if not chunk:
                break
            buffer += chunk
            frames, buffer = extract_transport_frames(buffer, crypto)
            decrypted += b"".join(frames)
            response = find_response_frame(decrypted, cmd)
            if response:
                return response
    raise TimeoutError(f"No SATEL response for command 0x{cmd:02X}")


def query_ethm_socket(sock, buffer, timeout, frame):
    cmd = command_code(frame)
    sock.sendall(frame)
    deadline = time.time() + timeout
    while time.time() < deadline:
        response, buffer = pop_response_frame(buffer, cmd)
        if response:
            return response, buffer
        remaining = max(0.0, deadline - time.time())
        ready, _, _ = select.select([sock], [], [], remaining)
        if not ready:
            break
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("ETHM connection closed")
        buffer += chunk
    raise TimeoutError(f"No SATEL response for command 0x{cmd:02X}")


def query_ethm_expected(host, port, timeout, frame, expected_cmd, crypto=None):
    sent_cmd = command_code(frame)
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(prepare_transport_frame(frame, crypto))
        deadline = time.time() + timeout
        buffer = b""
        decrypted = b""
        while time.time() < deadline:
            chunk = sock.recv(1024)
            if not chunk:
                break
            buffer += chunk
            frames, buffer = extract_transport_frames(buffer, crypto)
            decrypted += b"".join(frames)
            response = find_response_frame(decrypted, expected_cmd)
            if response:
                return response
    raise TimeoutError(f"No SATEL response 0x{expected_cmd:02X} for command 0x{sent_cmd:02X}")


def query_ethm_socket_expected(sock, buffer, timeout, frame, expected_cmd):
    sent_cmd = command_code(frame)
    sock.sendall(frame)
    deadline = time.time() + timeout
    while time.time() < deadline:
        response, buffer = pop_response_frame(buffer, expected_cmd)
        if response:
            return response, buffer
        remaining = max(0.0, deadline - time.time())
        ready, _, _ = select.select([sock], [], [], remaining)
        if not ready:
            break
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("ETHM connection closed")
        buffer += chunk
    raise TimeoutError(f"No SATEL response 0x{expected_cmd:02X} for command 0x{sent_cmd:02X}")


def query_frame(config, frame, transport=None):
    timeout = float(config.get("ethm_timeout", 2.0))
    cmd = command_code(frame)
    crypto = create_encryption_handler(config)
    if transport and transport.get("sock") is not None and crypto is None:
        response, buffer = query_ethm_socket(transport["sock"], transport.get("buffer", b""), timeout, frame)
        transport["buffer"] = buffer
        update_runtime_state({
            "last_ethm_ts": int(time.time()),
            "last_ethm_iso": datetime.now().isoformat(timespec="seconds"),
            "last_ethm_cmd": f"0x{cmd:02X}",
            "last_ethm_response": response.hex(" ").upper(),
            "last_ethm_transport": "push-socket",
        })
        return response
    ethm_host = config["ethm_host"]
    ethm_port = int(config.get("ethm_port", 7094))
    response = query_ethm(ethm_host, ethm_port, timeout, frame, crypto)
    update_runtime_state({
        "last_ethm_ts": int(time.time()),
        "last_ethm_iso": datetime.now().isoformat(timespec="seconds"),
        "last_ethm_cmd": f"0x{cmd:02X}",
        "last_ethm_response": response.hex(" ").upper(),
        "last_ethm_transport": "new-socket-encrypted" if crypto else "new-socket",
    })
    return response


def query_expected_frame(config, frame, expected_cmd, transport=None):
    timeout = float(config.get("ethm_timeout", 2.0))
    sent_cmd = command_code(frame)
    crypto = create_encryption_handler(config)
    if transport and transport.get("sock") is not None and crypto is None:
        response, buffer = query_ethm_socket_expected(
            transport["sock"], transport.get("buffer", b""), timeout, frame, expected_cmd
        )
        transport["buffer"] = buffer
        update_runtime_state({
            "last_ethm_ts": int(time.time()),
            "last_ethm_iso": datetime.now().isoformat(timespec="seconds"),
            "last_ethm_cmd": f"0x{sent_cmd:02X}",
            "last_ethm_expected": f"0x{expected_cmd:02X}",
            "last_ethm_response": response.hex(" ").upper(),
            "last_ethm_transport": "push-socket",
        })
        return response
    ethm_host = config["ethm_host"]
    ethm_port = int(config.get("ethm_port", 7094))
    response = query_ethm_expected(ethm_host, ethm_port, timeout, frame, expected_cmd, crypto)
    update_runtime_state({
        "last_ethm_ts": int(time.time()),
        "last_ethm_iso": datetime.now().isoformat(timespec="seconds"),
        "last_ethm_cmd": f"0x{sent_cmd:02X}",
        "last_ethm_expected": f"0x{expected_cmd:02X}",
        "last_ethm_response": response.hex(" ").upper(),
        "last_ethm_transport": "new-socket-encrypted" if crypto else "new-socket",
    })
    return response


def open_push_socket(config):
    host = config["ethm_host"]
    port = int(config.get("ethm_port", 7094))
    timeout = float(config.get("ethm_timeout", 2.0))
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.setblocking(False)
    return sock


def read_push_frames(sock, buffer, crypto=None):
    ready, _, _ = select.select([sock], [], [], 0)
    if not ready:
        return [], buffer
    while True:
        try:
            chunk = sock.recv(4096)
        except BlockingIOError:
            break
        if not chunk:
            raise ConnectionError("ETHM push connection closed")
        buffer += chunk
        ready, _, _ = select.select([sock], [], [], 0)
        if not ready:
            break
    return extract_transport_frames(buffer, crypto)


def close_socket(sock):
    if not sock:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass


def mask_from_response(response):
    if len(response) < 7:
        raise ValueError("SATEL response too short")
    data = response[3:-4]
    if not data:
        return 0, []
    mask = 0
    for index, byte in enumerate(data[:4]):
        mask |= byte << (index * 8)
    return mask, list(data)


def data_from_response(response):
    if len(response) < 7:
        raise ValueError("SATEL response too short")
    return list(response[3:-4])


RESULT_TEXT = {
    0x00: "ok",
    0x01: "requesting user code not found",
    0x02: "no access",
    0x03: "selected user does not exist",
    0x04: "selected user already exists",
    0x05: "wrong code or code already exists",
    0x06: "telephone code already exists",
    0x07: "changed code is the same",
    0x08: "other error",
    0x11: "can not arm, but can use force arm",
    0x12: "can not arm",
    0xFF: "command accepted, will be processed",
}


def unescape_frame(frame):
    if not frame.startswith(b"\xFE\xFE") or not frame.endswith(b"\xFE\x0D"):
        raise ValueError("invalid frame markers")
    raw = frame[2:-2]
    result = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte == 0xFE and index + 1 < len(raw) and raw[index + 1] == 0xF0:
            result.append(0xFE)
            index += 2
        else:
            result.append(byte)
            index += 1
    return bytes(result)


def control_result_from_response(response):
    body = unescape_frame(response)
    if len(body) < 3:
        return None, None
    cmd = body[0]
    data = body[1:-2]
    if cmd == 0xEF and data:
        return data[0], RESULT_TEXT.get(data[0], f"unknown result 0x{data[0]:02X}")
    return None, f"response command 0x{cmd:02X}"


def user_code_bytes(code):
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    if not digits:
        raise ValueError("missing SATEL user code")
    if len(digits) > 16:
        raise ValueError("SATEL user code/prefix too long")
    if len(digits) % 2:
        digits += "F"
    result = bytearray()
    for index in range(0, len(digits), 2):
        result.append(int(digits[index:index + 2], 16))
    while len(result) < 8:
        result.append(0xFF)
    return bytes(result[:8])


def bitmask_bytes(numbers, length):
    result = bytearray(length)
    for number in numbers:
        if number < 1 or number > length * 8:
            raise ValueError(f"number out of range: {number}")
        index = number - 1
        result[index // 8] |= 1 << (index % 8)
    return bytes(result)


def request_int(params, name, default=None):
    value = params.get(name, default)
    if value is None or value == "":
        raise ValueError(f"missing parameter: {name}")
    return int(value)


def configured_partition_numbers(config):
    numbers = [int(partition["number"]) for partition in configured_partitions(config)]
    if numbers:
        return sorted(set(numbers))
    return [int(config.get("default_control_partition", 1))]


def partition_numbers_from_params(config, params):
    raw_mask = str(params.get("partition_mask", "")).strip()
    if raw_mask:
        mask = int(raw_mask, 0)
        numbers = [number for number in range(1, 33) if mask & (1 << (number - 1))]
        if not numbers:
            raise ValueError("partition_mask does not select any partition")
        return numbers

    raw = str(params.get("partitions", "")).strip()
    if not raw:
        raw = str(params.get("partition", "")).strip()
    if not raw:
        raw = str(config.get("default_control_partition", 1))

    if raw.lower() in ("all", "wszystko", "*"):
        return configured_partition_numbers(config)

    numbers = []
    for token in raw.replace(";", ",").replace(" ", ",").split(","):
        token = token.strip()
        if not token:
            continue
        number = int(token, 0)
        if number < 1 or number > 32:
            raise ValueError(f"partition out of range: {number}")
        numbers.append(number)
    if not numbers:
        raise ValueError("missing partition selection")
    return sorted(set(numbers))


def format_partition_numbers(numbers):
    return ",".join(str(number) for number in numbers)


def output_is_on(config, output_number, transport=None):
    response = query_frame(config, satel_frame(0x17), transport)
    data = data_from_response(response)
    return bool(bit_value(data, output_number))


def build_control_command(config, params, transport=None):
    action = str(params.get("action", "")).strip().lower()
    code = user_code_bytes(config.get("satel_user_code", ""))

    if action in ("arm", "force_arm"):
        partitions = partition_numbers_from_params(config, params)
        mode = max(0, min(3, request_int(params, "mode", 0)))
        cmd = (0xA0 if action == "force_arm" else 0x80) + mode
        params["_confirm_kind"] = "arm"
        params["_confirm_partitions"] = partitions
        return cmd, code + bitmask_bytes(partitions, 4), f"{action} partitions={format_partition_numbers(partitions)} mode={mode}"

    if action == "disarm":
        partitions = partition_numbers_from_params(config, params)
        params["_confirm_kind"] = "disarm"
        params["_confirm_partitions"] = partitions
        return 0x84, code + bitmask_bytes(partitions, 4), f"disarm partitions={format_partition_numbers(partitions)}"

    if action == "clear_alarm":
        partitions = partition_numbers_from_params(config, params)
        params["_confirm_kind"] = "clear_alarm"
        params["_confirm_partitions"] = partitions
        return 0x85, code + bitmask_bytes(partitions, 4), f"clear_alarm partitions={format_partition_numbers(partitions)}"

    if action == "clear_trouble":
        return 0x8B, code, "clear_trouble"

    if action in ("output_on", "output_off", "output_toggle"):
        output = request_int(params, "output")
        if action == "output_toggle":
            action = "output_off" if output_is_on(config, output, transport) else "output_on"
            params["_resolved_action"] = action
        cmd = 0x88 if action == "output_on" else 0x89
        params["_confirm_kind"] = "output"
        params["_confirm_output"] = output
        params["_confirm_value"] = 1 if action == "output_on" else 0
        return cmd, code + bitmask_bytes([output], 16), f"{action} output={output}"

    if action in ("zone_bypass", "zone_unbypass"):
        zone = request_int(params, "zone")
        cmd = 0x86 if action == "zone_bypass" else 0x87
        params["_confirm_kind"] = "zone_bypass"
        params["_confirm_zone"] = zone
        params["_confirm_value"] = 1 if action == "zone_bypass" else 0
        return cmd, code + bitmask_bytes([zone], 16), f"{action} zone={zone}"

    if action == "open_door":
        output = request_int(params, "output")
        expander = request_int(params, "expander", 1)
        data = code + bitmask_bytes([output], 16) + bitmask_bytes([expander], 8)
        return 0x8A, data, f"open_door output={output} expander={expander}"

    raise ValueError(f"unsupported action: {action}")


def control_queue_dir():
    return os.path.join(os.path.dirname(config_file_path()), "control_queue")


def queue_control_request(params, source="bridge"):
    queue_dir = control_queue_dir()
    os.makedirs(queue_dir, exist_ok=True)
    request_id = f"{int(time.time() * 1000)}-{os.getpid()}-{len(os.listdir(queue_dir))}"
    request_path = os.path.join(queue_dir, f"{request_id}.request.json")
    write_json_atomic(
        request_path,
        {
            "created": time.time(),
            "params": params,
            "source": source,
        },
    )
    return request_id


CONTROL_ACTION_CODES = {
    "arm": 1,
    "force_arm": 2,
    "disarm": 3,
    "clear_alarm": 4,
    "clear_trouble": 5,
    "output_on": 6,
    "output_off": 7,
    "output_toggle": 8,
    "zone_bypass": 9,
    "zone_unbypass": 10,
    "open_door": 11,
}


def control_feedback_payload(
    params,
    success,
    result_code=None,
    pending=0,
    accepted=None,
    confirmed=0,
    timeout=0,
):
    action = str(params.get("action", "")).strip().lower()
    if result_code is None:
        result_code = 999
    if accepted is None:
        accepted = success
    return {
        "SATEL_CONTROL_OK": 1 if success else 0,
        "SATEL_CONTROL_ERROR": 0 if (success or pending) else 1,
        "SATEL_CONTROL_PENDING": 1 if pending else 0,
        "SATEL_CONTROL_ACCEPTED": 1 if accepted else 0,
        "SATEL_CONTROL_CONFIRMED": 1 if confirmed else 0,
        "SATEL_CONTROL_TIMEOUT": 1 if timeout else 0,
        "SATEL_CONTROL_LAST_CODE": int(result_code),
        "SATEL_CONTROL_LAST_ACTION": CONTROL_ACTION_CODES.get(action, 0),
        "SATEL_CONTROL_SEQ": int(time.time() * 1000) % 1000000000,
    }


def partition_bit(partition):
    return 1 << (int(partition) - 1)


def confirmation_partitions(config, params):
    raw = params.get("_confirm_partitions")
    if isinstance(raw, list):
        numbers = [int(number) for number in raw]
    elif raw:
        numbers = [int(token) for token in str(raw).replace(";", ",").split(",") if token.strip()]
    elif params.get("_confirm_partition"):
        numbers = [int(params.get("_confirm_partition"))]
    else:
        numbers = [int(config.get("default_control_partition", 1))]
    return sorted(set(numbers))


def read_command_mask(config, command_name, transport=None):
    command_hex = config.get("commands", {}).get(command_name)
    if not command_hex:
        return 0
    frame = hex_to_bytes(expand_command_template(command_hex, config))
    response = query_frame(config, frame, transport)
    mask, _data = mask_from_response(response)
    return mask


def read_output_value(config, output_number, transport=None):
    command_hex = str(config.get("output_status_command", "")).strip()
    frame = hex_to_bytes(expand_command_template(command_hex, config)) if command_hex else satel_frame(0x17)
    response = query_frame(config, frame, transport)
    data = data_from_response(response)
    return bit_value(data, int(output_number))


def read_zone_bypass_value(config, zone_number, transport=None):
    command_hex = config.get("zone_bypass_status_command", "FE FE 06 D7 E8 FE 0D")
    frame = hex_to_bytes(expand_command_template(command_hex, config))
    response = query_frame(config, frame, transport)
    data = data_from_response(response)
    return bit_value(data, int(zone_number))


def control_confirmation_state(config, params, transport=None):
    kind = params.get("_confirm_kind")
    if not kind:
        return None, "no confirmation rule"

    if kind == "arm":
        partitions = confirmation_partitions(config, params)
        armed_mask = read_command_mask(config, "armed", transport)
        exit_long_mask = read_command_mask(config, "exit_time", transport)
        exit_short_mask = read_command_mask(config, "exit_time_short", transport)
        waiting = []
        for partition in partitions:
            bit = partition_bit(partition)
            if not ((armed_mask | exit_long_mask | exit_short_mask) & bit):
                waiting.append(partition)
        if not waiting:
            return True, f"confirmed arm partitions={format_partition_numbers(partitions)}"
        return False, f"waiting arm partitions={format_partition_numbers(waiting)}"

    if kind == "disarm":
        partitions = confirmation_partitions(config, params)
        active_mask = (
            read_command_mask(config, "armed", transport)
            | read_command_mask(config, "exit_time", transport)
            | read_command_mask(config, "exit_time_short", transport)
        )
        waiting = [partition for partition in partitions if active_mask & partition_bit(partition)]
        if not waiting:
            return True, f"confirmed disarm partitions={format_partition_numbers(partitions)}"
        return False, f"waiting disarm partitions={format_partition_numbers(waiting)}"

    if kind == "clear_alarm":
        partitions = confirmation_partitions(config, params)
        alarm_mask = read_command_mask(config, "alarm", transport)
        waiting = [partition for partition in partitions if alarm_mask & partition_bit(partition)]
        if not waiting:
            return True, f"confirmed clear_alarm partitions={format_partition_numbers(partitions)}"
        return False, f"waiting clear_alarm partitions={format_partition_numbers(waiting)}"

    if kind == "output":
        output = int(params.get("_confirm_output", 0))
        expected = int(params.get("_confirm_value", 0))
        value = read_output_value(config, output, transport)
        if value == expected:
            return True, f"confirmed output={output} value={value}"
        return False, f"waiting output={output} value={value} expected={expected}"

    if kind == "zone_bypass":
        zone = int(params.get("_confirm_zone", 0))
        expected = int(params.get("_confirm_value", 0))
        value = read_zone_bypass_value(config, zone, transport)
        if value == expected:
            return True, f"confirmed zone_bypass zone={zone} value={value}"
        return False, f"waiting zone_bypass zone={zone} value={value} expected={expected}"

    return None, f"no confirmation rule for {kind}"


def wait_control_confirmation(config, params, transport=None):
    if not cfg_bool(config, "control_confirm_enabled", True):
        return None, "confirmation disabled"
    timeout = cfg_float(config, "control_confirm_timeout", 20.0)
    interval = cfg_float(config, "control_confirm_interval", 0.5)
    deadline = time.time() + max(0.0, timeout)
    last_message = "not checked"
    while time.time() <= deadline:
        confirmed, message = control_confirmation_state(config, params, transport)
        last_message = message
        if confirmed is None:
            return None, message
        if confirmed:
            return True, message
        time.sleep(max(0.1, interval))
    return False, last_message


def write_json_atomic(path, payload):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp_path, path)


def test_statuses_message(config, transport=None):
    lines = ["Test statusów OK"]
    for name, command in config.get("commands", {}).items():
        frame = hex_to_bytes(expand_command_template(command, config))
        response = query_frame(config, frame, transport)
        mask, _data = mask_from_response(response)
        lines.append(f"{name}: {response.hex(' ').upper()} mask={mask}")
    return "\n".join(lines)


def test_zones_message(config, transport=None):
    tests = [
        ("violation", config.get("zone_status_command", "FE FE 00 D7 E2 FE 0D")),
        ("bypass", config.get("zone_bypass_status_command", "FE FE 06 D7 E8 FE 0D")),
        ("tamper", config.get("zone_tamper_status_command", "FE FE 01 D7 E3 FE 0D")),
        ("alarm", config.get("zone_alarm_status_command", "FE FE 02 D7 E4 FE 0D")),
        ("alarm_memory", config.get("zone_alarm_memory_status_command", "FE FE 04 D7 E6 FE 0D")),
    ]
    lines = ["Test wejść OK"]
    for name, command in tests:
        frame = hex_to_bytes(expand_command_template(command, config))
        response = query_frame(config, frame, transport)
        mask, _data = mask_from_response(response)
        lines.append(f"{name}: {response.hex(' ').upper()} mask={mask}")
    return "\n".join(lines)


def test_udp_message(config):
    payload, sent = udp_send(config["loxone_host"], int(config["loxone_udp_port"]), "SATEL_TEST", 1)
    return f"Test UDP OK\nsent {payload} to {config['loxone_host']}:{config['loxone_udp_port']} bytes={sent}"


def process_test_request(config, request, transport=None):
    test_name = str(request.get("test", "")).strip()
    if test_name == "ethm":
        command = config.get("commands", {}).get("armed", "FE FE 0A D7 EC FE 0D")
        frame = hex_to_bytes(expand_command_template(command, config))
        response = query_frame(config, frame, transport)
        mask, _data = mask_from_response(response)
        return "Test ETHM OK\n" + f"armed response: {response.hex(' ').upper()}\nmask={mask}"
    if test_name == "statuses":
        return test_statuses_message(config, transport)
    if test_name == "zones":
        return test_zones_message(config, transport)
    if test_name == "udp":
        return test_udp_message(config)
    raise ValueError(f"unsupported test: {test_name}")


def process_control_requests(config, transport=None):
    queue_dir = control_queue_dir()
    os.makedirs(queue_dir, exist_ok=True)
    processed = 0
    for filename in sorted(os.listdir(queue_dir)):
        if not filename.endswith(".request.json"):
            continue
        request_path = os.path.join(queue_dir, filename)
        request_id = filename[:-len(".request.json")]
        response_path = os.path.join(queue_dir, f"{request_id}.response.json")
        if os.path.exists(response_path):
            continue
        request = {}
        params = {}
        try:
            with open(request_path, "r", encoding="utf-8") as fh:
                request = json.load(fh)
            if request.get("kind") == "test":
                message = process_test_request(config, request, transport)
                write_json_atomic(response_path, {"ok": True, "message": message})
                log(f"test: OK {request.get('test', '')}")
                try:
                    os.unlink(request_path)
                except Exception:
                    pass
                processed += 1
                continue
            params = request.get("params", {})
            try:
                send_status(config, control_feedback_payload(params, False, 0, pending=1, accepted=False))
            except Exception as feedback_exc:
                log(f"control_feedback: ERROR {feedback_exc}")
            cmd, data, description = build_control_command(config, params, transport)
            frame = satel_frame(cmd, data)
            response = query_expected_frame(config, frame, 0xEF, transport)
            result_code, result_text = control_result_from_response(response)
            response_hex = response.hex(" ").upper()
            accepted = result_code in (0x00, 0xFF, None)
            confirmed = None
            confirmation_text = "accepted; status refresh will confirm asynchronously" if accepted else "not checked"
            timed_out = False
            success = accepted
            if accepted and cfg_bool(config, "control_confirm_blocking", False):
                confirmed, confirmation_text = wait_control_confirmation(config, params, transport)
                if confirmed is False:
                    success = False
                    timed_out = True
                elif confirmed is True:
                    success = True
                else:
                    success = accepted
            message = (
                f"{description}; result={result_text}; confirmation={confirmation_text}; "
                f"response={response_hex}"
            )
            try:
                send_status(
                    config,
                    control_feedback_payload(
                        params,
                        success,
                        result_code,
                        pending=0,
                        accepted=accepted,
                        confirmed=confirmed is True,
                        timeout=timed_out,
                    ),
                )
            except Exception as feedback_exc:
                log(f"control_feedback: ERROR {feedback_exc}")
            write_json_atomic(
                response_path,
                {
                    "ok": success,
                    "message": message,
                    "result_code": result_code,
                    "result_text": result_text,
                    "accepted": accepted,
                    "confirmed": confirmed,
                    "confirmation": confirmation_text,
                    "response": response_hex,
                },
            )
            update_runtime_state(
                {
                    "last_control_ts": int(time.time()),
                    "last_control_iso": datetime.now().isoformat(timespec="seconds"),
                    "last_control_ok": 1 if success else 0,
                    "last_control_action": str(params.get("action", "")),
                    "last_control_description": description,
                    "last_control_result_code": result_code if result_code is not None else "",
                    "last_control_result_text": result_text or "",
                    "last_control_confirmation": confirmation_text,
                    "last_control_response": response_hex,
                    "events": runtime_events_with(runtime_event(
                        "control",
                        "Sterowanie OK" if success else "Sterowanie ERROR",
                        message,
                        action=str(params.get("action", "")),
                        result=str(result_text or ""),
                    )),
                },
                force=True,
            )
            log(f"control: {'OK' if success else 'ERROR'} {message}")
        except Exception as exc:
            if request.get("kind") != "test":
                try:
                    send_status(config, control_feedback_payload(params, False, 999))
                except Exception:
                    pass
            write_json_atomic(response_path, {"ok": False, "message": str(exc)})
            update_runtime_state(
                {
                    "last_control_ts": int(time.time()),
                    "last_control_iso": datetime.now().isoformat(timespec="seconds"),
                    "last_control_ok": 0,
                    "last_control_action": str(params.get("action", "")),
                    "last_control_error": str(exc),
                    "events": runtime_events_with(runtime_event(
                        "control",
                        "Sterowanie ERROR",
                        str(exc),
                        action=str(params.get("action", "")),
                    )),
                },
                force=True,
            )
            log(f"control: ERROR {exc}")
        try:
            os.unlink(request_path)
        except Exception:
            pass
        processed += 1
    return processed


def zone_violated(data, zone_number):
    if zone_number < 1:
        return 0
    index = zone_number - 1
    byte_index = index // 8
    bit_index = index % 8
    if byte_index >= len(data):
        return 0
    return 1 if (data[byte_index] & (1 << bit_index)) else 0


def bit_value(data, number):
    if number < 1:
        return 0
    index = number - 1
    byte_index = index // 8
    bit_index = index % 8
    if byte_index >= len(data):
        return 0
    return 1 if (data[byte_index] & (1 << bit_index)) else 0


def configured_partitions(config):
    partitions = []
    for partition in config.get("control_partitions", []):
        try:
            number = int(partition.get("number", 0))
        except Exception:
            continue
        if partition.get("enabled", True) and 1 <= number <= 32:
            partitions.append({"number": number, "name": partition.get("name", "")})
    if not partitions:
        mask = int(config.get("partition_mask", 1))
        for number in range(1, 33):
            if mask & partition_bit(number):
                partitions.append({"number": number, "name": f"Partycja {number}"})
    return partitions


def add_partition_payload(config, payload, masks):
    if not cfg_bool(config, "send_partition_details", True):
        return
    for partition in configured_partitions(config):
        number = int(partition["number"])
        bit = partition_bit(number)
        prefix = f"SATEL_PARTITION_{number:03d}"
        armed = 1 if (masks.get("armed", 0) & bit) else 0
        alarm = 1 if (masks.get("alarm", 0) & bit) else 0
        fire_alarm = 1 if (masks.get("fire_alarm", 0) & bit) else 0
        alarm_memory = 1 if (masks.get("alarm_memory", 0) & bit) else 0
        entry_time = 1 if (masks.get("entry_time", 0) & bit) else 0
        exit_long = 1 if (masks.get("exit_time", 0) & bit) else 0
        exit_short = 1 if (masks.get("exit_time_short", 0) & bit) else 0
        exit_time = 1 if (exit_long or exit_short) else 0
        payload[f"{prefix}_ARMED"] = armed
        payload[f"{prefix}_ALARM"] = alarm
        payload[f"{prefix}_FIRE_ALARM"] = fire_alarm
        payload[f"{prefix}_ALARM_MEMORY"] = alarm_memory
        payload[f"{prefix}_ENTRY_TIME"] = entry_time
        payload[f"{prefix}_EXIT_TIME"] = exit_time
        payload[f"{prefix}_EXIT_TIME_LONG"] = exit_long
        payload[f"{prefix}_EXIT_TIME_SHORT"] = exit_short
        payload[f"{prefix}_DISARMED"] = 1 if not armed and not exit_time else 0


def udp_send(host, port, key, value):
    payload = f"{key}={value}".encode("ascii", errors="ignore")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        sent = udp.sendto(payload, (host, int(port)))
    return payload.decode("ascii"), sent


def mqtt_enabled(config):
    return cfg_bool(config, "mqtt_enabled", False)


def mqtt_base_topic(config):
    base = str(config.get("mqtt_base_topic", "satel")).strip().strip("/")
    return base or "satel"


def mqtt_encode_remaining_length(length):
    encoded = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length > 0:
            byte |= 0x80
        encoded.append(byte)
        if length == 0:
            break
    return bytes(encoded)


def mqtt_string(value):
    data = str(value).encode("utf-8")
    return len(data).to_bytes(2, "big") + data


def mqtt_packet(packet_type, payload):
    return bytes([packet_type]) + mqtt_encode_remaining_length(len(payload)) + payload


def mqtt_read_packet(sock, timeout=3.0):
    sock.settimeout(timeout)
    fixed = sock.recv(1)
    if not fixed:
        raise ConnectionError("MQTT connection closed")
    multiplier = 1
    remaining = 0
    while True:
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("MQTT connection closed while reading remaining length")
        value = byte[0]
        remaining += (value & 127) * multiplier
        if not (value & 128):
            break
        multiplier *= 128
        if multiplier > 128 * 128 * 128:
            raise ValueError("MQTT remaining length malformed")
    payload = bytearray()
    while len(payload) < remaining:
        chunk = sock.recv(remaining - len(payload))
        if not chunk:
            raise ConnectionError("MQTT connection closed while reading payload")
        payload.extend(chunk)
    return fixed[0], bytes(payload)


def mqtt_connect(config, client_suffix="pub"):
    host = str(config.get("mqtt_host", "localhost")).strip() or "localhost"
    port = int(config.get("mqtt_port", 1883))
    timeout = cfg_float(config, "mqtt_timeout", 3.0)
    keepalive = int(cfg_float(config, "mqtt_keepalive", 60.0))
    username = str(config.get("mqtt_username", "")).strip()
    password = str(config.get("mqtt_password", "")).strip()
    base_client_id = str(config.get("mqtt_client_id", "")).strip()
    if base_client_id:
        client_id = f"{base_client_id}-{client_suffix}"
    else:
        client_id = f"satel-ethm-{client_suffix}-{os.getpid()}"

    flags = 0x02
    payload = mqtt_string(client_id)
    if username:
        flags |= 0x80
        payload += mqtt_string(username)
    if password:
        flags |= 0x40
        payload += mqtt_string(password)

    variable_header = mqtt_string("MQTT") + bytes([4, flags]) + keepalive.to_bytes(2, "big")
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.sendall(mqtt_packet(0x10, variable_header + payload))
    packet_type, response = mqtt_read_packet(sock, timeout)
    if packet_type != 0x20 or len(response) < 2 or response[1] != 0:
        close_socket(sock)
        code = response[1] if len(response) > 1 else "?"
        raise RuntimeError(f"MQTT CONNACK failed: {code}")
    return sock


def mqtt_disconnect(sock):
    if sock is None:
        return
    try:
        sock.sendall(b"\xE0\x00")
    except Exception:
        pass
    close_socket(sock)


def mqtt_publish_socket(sock, topic, value, retain=False):
    payload = mqtt_string(topic) + str(value).encode("utf-8")
    sock.sendall(mqtt_packet(0x31 if retain else 0x30, payload))


def mqtt_key_topic(config, key):
    base = mqtt_base_topic(config)
    key = str(key)
    lower = key.lower()
    if lower.startswith("satel_"):
        lower = lower[len("satel_"):]
    parts = lower.split("_")
    if len(parts) >= 2 and parts[0] == "zone" and parts[1].isdigit():
        suffix = "_".join(parts[2:]) if len(parts) > 2 else "violated"
        return f"{base}/zone/{parts[1]}/{suffix}"
    if len(parts) >= 2 and parts[0] == "partition" and parts[1].isdigit():
        suffix = "_".join(parts[2:]) if len(parts) > 2 else "state"
        return f"{base}/partition/{parts[1]}/{suffix}"
    if len(parts) >= 2 and parts[0] == "output" and parts[1].isdigit():
        suffix = "_".join(parts[2:]) if len(parts) > 2 else "state"
        return f"{base}/output/{parts[1]}/{suffix}"
    if len(parts) >= 2 and parts[0] == "temp" and parts[1].isdigit():
        suffix = "_".join(parts[2:]) if len(parts) > 2 else "value"
        return f"{base}/temperature/{parts[1]}/{suffix}"
    if lower.startswith("trouble_"):
        return f"{base}/trouble/{lower[len('trouble_'):]}"
    if lower.startswith("control_"):
        return f"{base}/control/status/{lower[len('control_'):]}"
    if lower.startswith("push_"):
        return f"{base}/push/{lower[len('push_'):]}"
    if lower.startswith("watchdog_"):
        return f"{base}/watchdog/{lower[len('watchdog_'):]}"
    if lower.startswith("diag_"):
        return f"{base}/diagnostic/{lower[len('diag_'):]}"
    if lower.startswith("ready_"):
        return f"{base}/ready/{lower[len('ready_'):]}"
    return f"{base}/status/{lower}"


def mqtt_publish_values(config, values):
    if not mqtt_enabled(config) or not values:
        return
    retain = cfg_bool(config, "mqtt_retain", True)
    publish_raw = cfg_bool(config, "mqtt_publish_raw", False)
    base = mqtt_base_topic(config)
    sock = None
    try:
        sock = mqtt_connect(config, "pub")
        for key, value in values.items():
            mqtt_publish_socket(sock, mqtt_key_topic(config, key), value, retain)
            if publish_raw:
                mqtt_publish_socket(sock, f"{base}/raw/{key}", value, retain)
        update_runtime_state({
            "mqtt_last_publish_ts": int(time.time()),
            "mqtt_last_publish_iso": datetime.now().isoformat(timespec="seconds"),
            "mqtt_last_publish_count": len(values),
            "mqtt_last_publish_keys": ",".join(list(values.keys())[:20]),
            "mqtt_connected": 1,
            "mqtt_last_error": "",
        })
    except Exception as exc:
        log(f"mqtt: publish ERROR: {exc}")
        update_runtime_state({
            "mqtt_connected": 0,
            "mqtt_last_error": str(exc),
            "mqtt_last_error_iso": datetime.now().isoformat(timespec="seconds"),
        }, force=True)
    finally:
        mqtt_disconnect(sock)


def mqtt_subscribe(sock, topic, packet_id=1):
    payload = int(packet_id).to_bytes(2, "big") + mqtt_string(topic) + b"\x00"
    sock.sendall(mqtt_packet(0x82, payload))
    packet_type, response = mqtt_read_packet(sock, 3.0)
    if packet_type != 0x90 or len(response) < 3:
        raise RuntimeError("MQTT SUBACK missing")
    return packet_id + 1


def mqtt_ping(sock):
    sock.sendall(b"\xC0\x00")


def mqtt_decode_buffer(buffer):
    packets = []
    offset = 0
    while offset < len(buffer):
        if len(buffer) - offset < 2:
            break
        packet_type = buffer[offset]
        index = offset + 1
        multiplier = 1
        remaining = 0
        while True:
            if index >= len(buffer):
                return packets, buffer[offset:]
            byte = buffer[index]
            index += 1
            remaining += (byte & 127) * multiplier
            if not (byte & 128):
                break
            multiplier *= 128
            if multiplier > 128 * 128 * 128:
                raise ValueError("MQTT remaining length malformed")
        end = index + remaining
        if end > len(buffer):
            break
        packets.append((packet_type, buffer[index:end]))
        offset = end
    return packets, buffer[offset:]


def mqtt_poll(sock, buffer):
    messages = []
    ready, _, _ = select.select([sock], [], [], 0)
    if ready:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("MQTT control connection closed")
        buffer += chunk
    packets, buffer = mqtt_decode_buffer(buffer)
    for packet_type, payload in packets:
        kind = packet_type >> 4
        if kind != 3 or len(payload) < 2:
            continue
        topic_len = int.from_bytes(payload[:2], "big")
        if len(payload) < 2 + topic_len:
            continue
        topic = payload[2:2 + topic_len].decode("utf-8", errors="replace")
        message = payload[2 + topic_len:].decode("utf-8", errors="replace")
        messages.append((topic, message))
    return messages, buffer


def mqtt_bool_payload(payload):
    value = str(payload).strip().lower()
    return value in ("1", "true", "on", "yes", "tak")


def mqtt_json_payload(payload):
    text = str(payload).strip()
    if not text:
        return {}
    if text.startswith("{"):
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    return {"value": text}


def mqtt_control_params(config, topic, payload):
    base = mqtt_base_topic(config)
    topic = str(topic).strip("/")
    prefix = f"{base}/control/"
    if not topic.startswith(prefix):
        return None
    tail = topic[len(prefix):].strip("/")
    parts = [part for part in tail.split("/") if part]
    data = mqtt_json_payload(payload)
    if not parts:
        return None

    action = parts[0].lower()
    if action in ("arm", "force_arm", "disarm", "clear_alarm"):
        params = {"action": action}
        params.update({key: value for key, value in data.items() if key in ("partition", "partitions", "partition_mask", "mode")})
        if "partition" not in params and "partitions" not in params and "partition_mask" not in params:
            raw_value = str(data.get("value", "")).strip()
            if raw_value:
                params["partitions" if raw_value.lower() in ("all", "wszystko", "*") or "," in raw_value else "partition"] = raw_value
        return params
    if action == "clear_trouble":
        return {"action": "clear_trouble"}
    if action == "output" and len(parts) >= 3:
        output = int(parts[1])
        command = parts[2].lower()
        if command == "set":
            return {"action": "output_on" if mqtt_bool_payload(data.get("value", payload)) else "output_off", "output": output}
        if command == "toggle":
            return {"action": "output_toggle", "output": output}
    if action == "zone" and len(parts) >= 3:
        zone = int(parts[1])
        command = parts[2].lower()
        if command in ("bypass", "block"):
            return {"action": "zone_bypass" if mqtt_bool_payload(data.get("value", payload)) else "zone_unbypass", "zone": zone}
    return None


def mqtt_connect_control(config):
    sock = mqtt_connect(config, "ctl")
    base = mqtt_base_topic(config)
    packet_id = mqtt_subscribe(sock, f"{base}/control/#", 1)
    update_runtime_state({
        "mqtt_control_connected": 1,
        "mqtt_control_topic": f"{base}/control/#",
        "mqtt_control_packet_id": packet_id,
        "mqtt_control_last_error": "",
    }, force=True)
    return sock, b"", packet_id


def mqtt_process_control_messages(config, messages):
    queued = 0
    for topic, payload in messages:
        try:
            params = mqtt_control_params(config, topic, payload)
            if not params:
                continue
            request_id = queue_control_request(params, source=f"mqtt:{topic}")
            queued += 1
            log(f"mqtt_control: queued {params} request={request_id}")
            update_runtime_state({
                "mqtt_control_last_ts": int(time.time()),
                "mqtt_control_last_iso": datetime.now().isoformat(timespec="seconds"),
                "mqtt_control_last_topic": topic,
                "mqtt_control_last_payload": payload,
                "mqtt_control_last_params": params,
                "events": runtime_events_with(runtime_event(
                    "mqtt",
                    "MQTT sterowanie",
                    f"{topic} -> {params}",
                )),
            }, force=True)
        except Exception as exc:
            log(f"mqtt_control: message ERROR topic={topic}: {exc}")
            update_runtime_state({
                "mqtt_control_last_error": str(exc),
                "mqtt_control_last_error_iso": datetime.now().isoformat(timespec="seconds"),
            }, force=True)
    return queued


def send_status(config, values):
    host = config["loxone_host"]
    port = int(config["loxone_udp_port"])
    last_payload = ""
    for key, value in values.items():
        payload, sent = udp_send(host, port, key, value)
        last_payload = payload
        log(f"udp: sent {payload} to {host}:{port} bytes={sent}")
    if values:
        last_values = dict(RUNTIME_STATE.get("last_values", {}))
        for key, value in values.items():
            last_values[str(key)] = value
        update_runtime_state({
            "last_udp_ts": int(time.time()),
            "last_udp_iso": datetime.now().isoformat(timespec="seconds"),
            "last_udp_target": f"{host}:{port}",
            "last_udp_payload": last_payload,
            "last_udp_count": len(values),
            "last_udp_keys": ",".join(list(values.keys())[:20]),
            "last_values": last_values,
            "events": runtime_events_with(runtime_event(
                "udp",
                "UDP do Loxone",
                f"{len(values)} wartosci -> {host}:{port}",
                keys=",".join(list(values.keys())[:20]),
                payload=last_payload,
            )),
        })
        mqtt_publish_values(config, values)


def read_core_statuses(config, transport=None):
    wanted_mask = int(config.get("partition_mask", 1))
    commands = config["commands"]

    results = {}
    masks = {}
    data_by_name = {}
    errors = {}

    for name, command_hex in commands.items():
        try:
            frame = hex_to_bytes(expand_command_template(command_hex, config))
            response = query_frame(config, frame, transport)
            mask, data = mask_from_response(response)
            masks[name] = mask
            data_by_name[name] = data
            if name in ("armed", "alarm", "fire_alarm", "alarm_memory", "entry_time", "exit_time", "exit_time_short"):
                results[name] = 1 if (mask & wanted_mask) else 0
            elif name == "trouble":
                results[name] = 1 if any(data) else 0
            else:
                results[name] = 1 if mask else 0
            debug_log(config, f"{name}: response={response.hex(' ').upper()} mask={mask} value={results[name]}")
        except Exception as exc:
            errors[name] = str(exc)
            log(f"{name}: ERROR: {exc}")

    payload = {"SATEL_ONLINE": 1 if results else 0}
    if "armed" in results:
        payload["SATEL_ARMED"] = results["armed"]
    if "alarm" in results:
        payload["SATEL_ALARM"] = results["alarm"]
    if "fire_alarm" in results:
        payload["SATEL_FIRE_ALARM"] = results["fire_alarm"]
    if "alarm_memory" in results:
        payload["SATEL_ALARM_MEMORY"] = results["alarm_memory"]
    if "trouble" in results:
        payload["SATEL_TROUBLE"] = results["trouble"]
        if cfg_bool(config, "send_trouble_details", True) and "trouble" in masks:
            payload.update(trouble_detail_payload(data_by_name.get("trouble", [])))
    if "entry_time" in results:
        payload["SATEL_ENTRY_TIME"] = results["entry_time"]
    exit_time = 0
    exit_time_known = False
    if "exit_time" in results:
        payload["SATEL_EXIT_TIME_LONG"] = results["exit_time"]
        exit_time = exit_time or results["exit_time"]
        exit_time_known = True
    if "exit_time_short" in results:
        payload["SATEL_EXIT_TIME_SHORT"] = results["exit_time_short"]
        exit_time = exit_time or results["exit_time_short"]
        exit_time_known = True
    if exit_time_known:
        payload["SATEL_EXIT_TIME"] = 1 if exit_time else 0
    add_partition_payload(config, payload, masks)
    if config.get("send_masks", True):
        if "armed" in masks:
            payload["SATEL_ARMED_MASK"] = masks["armed"]
        if "alarm" in masks:
            payload["SATEL_ALARM_MASK"] = masks["alarm"]
        if "fire_alarm" in masks:
            payload["SATEL_FIRE_ALARM_MASK"] = masks["fire_alarm"]
        if "alarm_memory" in masks:
            payload["SATEL_ALARM_MEMORY_MASK"] = masks["alarm_memory"]
        if "trouble" in masks:
            payload["SATEL_TROUBLE_MASK"] = masks["trouble"]
        if "entry_time" in masks:
            payload["SATEL_ENTRY_TIME_MASK"] = masks["entry_time"]
        if "exit_time" in masks:
            payload["SATEL_EXIT_TIME_LONG_MASK"] = masks["exit_time"]
        if "exit_time_short" in masks:
            payload["SATEL_EXIT_TIME_SHORT_MASK"] = masks["exit_time_short"]
    if errors:
        payload["SATEL_ERROR"] = 1
    else:
        payload["SATEL_ERROR"] = 0
    return payload


def trouble_detail_payload(data):
    payload = {}
    if not data:
        return payload
    payload["SATEL_TROUBLE_TECH_ZONE"] = 1 if any(data[0:16]) else 0
    payload["SATEL_TROUBLE_EXPANDER_AC"] = 1 if any(data[16:24]) else 0
    payload["SATEL_TROUBLE_EXPANDER_BATT"] = 1 if any(data[24:32]) else 0
    payload["SATEL_TROUBLE_EXPANDER_NO_BATT"] = 1 if any(data[32:40]) else 0
    sys1 = data[40] if len(data) > 40 else 0
    sys2 = data[41] if len(data) > 41 else 0
    sys3 = data[42] if len(data) > 42 else 0
    payload["SATEL_TROUBLE_OUT"] = 1 if (sys1 & 0x0F) else 0
    payload["SATEL_TROUBLE_KPD_POWER"] = 1 if (sys1 & 0x10) else 0
    payload["SATEL_TROUBLE_EXP_POWER"] = 1 if (sys1 & 0x20) else 0
    payload["SATEL_TROUBLE_BATTERY"] = 1 if (sys1 & 0x40) else 0
    payload["SATEL_TROUBLE_AC"] = 1 if (sys1 & 0x80) else 0
    payload["SATEL_TROUBLE_DIALER"] = 1 if (sys2 & 0x07) else 0
    payload["SATEL_TROUBLE_RTC"] = 1 if (sys2 & 0x08) else 0
    payload["SATEL_TROUBLE_DTR"] = 1 if (sys2 & 0x10) else 0
    payload["SATEL_TROUBLE_NO_BATTERY"] = 1 if (sys2 & 0x20) else 0
    payload["SATEL_TROUBLE_MODEM"] = 1 if (sys2 & 0xC0) else 0
    payload["SATEL_TROUBLE_PHONE_LINE"] = 1 if (sys3 & 0x07) else 0
    payload["SATEL_TROUBLE_MONITORING"] = 1 if (sys3 & 0x18) else 0
    payload["SATEL_TROUBLE_MEMORY"] = 1 if (sys3 & 0xE0) else 0
    return payload


def configured_zones(config):
    zones = []
    for zone in config.get("zones", []):
        try:
            number = int(zone.get("number", 0))
        except Exception:
            continue
        try:
            partition = int(zone.get("partition", 0) or 0)
        except Exception:
            partition = 0
        if partition < 1 or partition > 32:
            partition = 0
        if zone.get("enabled", True) and number > 0:
            zones.append({"number": number, "name": zone.get("name", ""), "partition": partition})
    return zones


def add_partition_zone_payload(config, payload, zones):
    if not cfg_bool(config, "send_partition_details", True):
        return
    partitions = {int(partition["number"]) for partition in configured_partitions(config)}
    for zone in zones:
        partition = int(zone.get("partition", 0) or 0)
        if partition:
            partitions.add(partition)
    for partition in sorted(partitions):
        prefix = f"SATEL_PARTITION_{partition:03d}"
        mapped_zones = [zone for zone in zones if int(zone.get("partition", 0) or 0) == partition]
        if not mapped_zones:
            continue
        zone_any = 0
        bypass_any = 0
        tamper_any = 0
        alarm_any = 0
        alarm_memory_any = 0
        for zone in mapped_zones:
            number = int(zone.get("number", 0))
            zone_any = zone_any or int(payload.get(f"SATEL_ZONE_{number:03d}", 0))
            bypass_any = bypass_any or int(payload.get(f"SATEL_ZONE_{number:03d}_BYPASS", 0))
            tamper_any = tamper_any or int(payload.get(f"SATEL_ZONE_{number:03d}_TAMPER", 0))
            alarm_any = alarm_any or int(payload.get(f"SATEL_ZONE_{number:03d}_ALARM", 0))
            alarm_memory_any = alarm_memory_any or int(payload.get(f"SATEL_ZONE_{number:03d}_ALARM_MEMORY", 0))
        payload[f"{prefix}_ZONE_ANY"] = 1 if zone_any else 0
        payload[f"{prefix}_ZONE_BYPASS_ANY"] = 1 if bypass_any else 0
        payload[f"{prefix}_ZONE_TAMPER_ANY"] = 1 if tamper_any else 0
        payload[f"{prefix}_ZONE_ALARM_ANY"] = 1 if alarm_any else 0
        payload[f"{prefix}_ZONE_ALARM_MEMORY_ANY"] = 1 if alarm_memory_any else 0
        payload[f"{prefix}_READY_ZONES_OK"] = 0 if zone_any else 1
        payload[f"{prefix}_READY_TAMPER_OK"] = 0 if tamper_any else 1


def configured_outputs(config):
    outputs = []
    for output in config.get("control_outputs", []):
        try:
            number = int(output.get("number", 0))
        except Exception:
            continue
        if output.get("enabled", True) and number > 0:
            outputs.append({"number": number, "name": output.get("name", "")})
    return outputs


def configured_temperature_zones(config):
    zones = []
    for zone in config.get("temperature_zones", []):
        try:
            number = int(zone.get("number", 0))
        except Exception:
            continue
        if zone.get("enabled", True) and number > 0:
            zones.append({"number": number, "name": zone.get("name", "")})
    return zones


def read_zone_statuses(config, transport=None):
    zones = configured_zones(config)
    payload = {}

    if not cfg_bool(config, "poll_zones", False) or not zones:
        return payload

    try:
        command_hex = config.get("zone_status_command", "FE FE 00 D7 E2 FE 0D")
        frame = hex_to_bytes(expand_command_template(command_hex, config))
        response = query_frame(config, frame, transport)
        zone_data = data_from_response(response)
        zone_any = 0
        for zone in zones:
            number = int(zone.get("number", 0))
            value = zone_violated(zone_data, number)
            zone_any = zone_any or value
            payload[f"SATEL_ZONE_{number:03d}"] = value
        payload["SATEL_ZONE_ANY"] = 1 if zone_any else 0
        payload["SATEL_READY_ZONES_OK"] = 0 if zone_any else 1
        debug_log(config, f"zones: response={response.hex(' ').upper()} count={len(zones)} any={payload['SATEL_ZONE_ANY']}")

        if cfg_bool(config, "poll_zone_bypass", True):
            command_hex = config.get("zone_bypass_status_command", "FE FE 06 D7 E8 FE 0D")
            frame = hex_to_bytes(expand_command_template(command_hex, config))
            response = query_frame(config, frame, transport)
            bypass_data = data_from_response(response)
            bypass_any = 0
            for zone in zones:
                number = int(zone.get("number", 0))
                value = zone_violated(bypass_data, number)
                bypass_any = bypass_any or value
                payload[f"SATEL_ZONE_{number:03d}_BYPASS"] = value
            payload["SATEL_ZONE_BYPASS_ANY"] = 1 if bypass_any else 0
            debug_log(config, f"zones_bypass: response={response.hex(' ').upper()} count={len(zones)} any={payload['SATEL_ZONE_BYPASS_ANY']}")

        if cfg_bool(config, "poll_zone_diagnostics", True):
            diagnostics = [
                ("TAMPER", "zone_tamper_status_command", "FE FE 01 D7 E3 FE 0D"),
                ("ALARM", "zone_alarm_status_command", "FE FE 02 D7 E4 FE 0D"),
                ("ALARM_MEMORY", "zone_alarm_memory_status_command", "FE FE 04 D7 E6 FE 0D"),
            ]
            for suffix, config_key, default_command in diagnostics:
                command_hex = config.get(config_key, default_command)
                frame = hex_to_bytes(expand_command_template(command_hex, config))
                response = query_frame(config, frame, transport)
                diagnostic_data = data_from_response(response)
                diagnostic_any = 0
                for zone in zones:
                    number = int(zone.get("number", 0))
                    value = zone_violated(diagnostic_data, number)
                    diagnostic_any = diagnostic_any or value
                    payload[f"SATEL_ZONE_{number:03d}_{suffix}"] = value
                any_key = f"SATEL_ZONE_{suffix}_ANY"
                payload[any_key] = 1 if diagnostic_any else 0
                if suffix == "TAMPER":
                    payload["SATEL_READY_TAMPER_OK"] = 0 if diagnostic_any else 1
                debug_log(
                    config,
                    f"zones_{suffix.lower()}: response={response.hex(' ').upper()} count={len(zones)} any={payload[any_key]}"
                )
        add_partition_zone_payload(config, payload, zones)
    except Exception as exc:
        payload["SATEL_ERROR"] = 1
        log(f"zones: ERROR: {exc}")

    return payload


def add_ready_status(config, status_payload, zone_payload):
    if not cfg_bool(config, "send_ready_inferred", True):
        return status_payload, zone_payload
    zone_ok = zone_payload.get("SATEL_READY_ZONES_OK", 1 if "SATEL_ZONE_ANY" not in zone_payload else 0)
    tamper_ok = zone_payload.get("SATEL_READY_TAMPER_OK", 1)
    trouble_ok = 0 if status_payload.get("SATEL_TROUBLE", 0) else 1
    alarm_ok = 0 if status_payload.get("SATEL_ALARM", 0) else 1
    ready = 1 if zone_ok and tamper_ok and trouble_ok and alarm_ok else 0
    status_payload["SATEL_READY_INFERRED"] = ready
    status_payload["SATEL_READY_ZONES_OK"] = zone_ok
    status_payload["SATEL_READY_TAMPER_OK"] = tamper_ok
    status_payload["SATEL_READY_TROUBLE_OK"] = trouble_ok
    status_payload["SATEL_READY_ALARM_OK"] = alarm_ok
    for partition in configured_partitions(config):
        number = int(partition["number"])
        prefix = f"SATEL_PARTITION_{number:03d}"
        armed = status_payload.get(f"SATEL_PARTITION_{number:03d}_ARMED", 0)
        exit_time = status_payload.get(f"SATEL_PARTITION_{number:03d}_EXIT_TIME", 0)
        alarm = status_payload.get(f"SATEL_PARTITION_{number:03d}_ALARM", 0)
        partition_zone_ok = zone_payload.get(f"{prefix}_READY_ZONES_OK", zone_ok)
        partition_tamper_ok = zone_payload.get(f"{prefix}_READY_TAMPER_OK", tamper_ok)
        partition_alarm_ok = 0 if alarm else 1
        partition_ready = 1 if partition_zone_ok and partition_tamper_ok and trouble_ok and partition_alarm_ok and not armed and not exit_time else 0
        status_payload[f"{prefix}_READY_INFERRED"] = partition_ready
        status_payload[f"{prefix}_READY_ZONES_OK"] = partition_zone_ok
        status_payload[f"{prefix}_READY_TAMPER_OK"] = partition_tamper_ok
        status_payload[f"{prefix}_READY_TROUBLE_OK"] = trouble_ok
        status_payload[f"{prefix}_READY_ALARM_OK"] = partition_alarm_ok
    return status_payload, zone_payload


def read_output_statuses(config, transport=None):
    outputs = configured_outputs(config)
    payload = {}

    if not cfg_bool(config, "poll_outputs", True) or not outputs:
        return payload

    try:
        command_hex = str(config.get("output_status_command", "")).strip()
        frame = hex_to_bytes(expand_command_template(command_hex, config)) if command_hex else satel_frame(0x17)
        response = query_frame(config, frame, transport)
        output_data = data_from_response(response)
        output_any = 0
        for output in outputs:
            number = int(output.get("number", 0))
            value = bit_value(output_data, number)
            output_any = output_any or value
            payload[f"SATEL_OUTPUT_{number:03d}"] = value
        payload["SATEL_OUTPUT_ANY"] = 1 if output_any else 0
        debug_log(config, f"outputs: response={response.hex(' ').upper()} count={len(outputs)} any={payload['SATEL_OUTPUT_ANY']}")
    except Exception as exc:
        payload["SATEL_ERROR"] = 1
        log(f"outputs: ERROR: {exc}")

    return payload


def temperature_from_data(data):
    if len(data) < 3:
        return None
    raw = (int(data[1]) << 8) | int(data[2])
    if raw == 0xFFFF:
        return None
    return (raw - 110) / 2.0


def read_temperature_statuses(config, transport=None):
    zones = configured_temperature_zones(config)
    payload = {}

    if not cfg_bool(config, "poll_temperatures", False) or not zones:
        return payload

    for zone in zones:
        number = int(zone.get("number", 0))
        try:
            zone_byte = 0 if number == 256 else number
            if transport and transport.get("sock") is not None:
                previous_timeout = config.get("ethm_timeout", 2.0)
                config["ethm_timeout"] = max(float(previous_timeout), float(config.get("temperature_timeout", 5.0)))
                try:
                    response = query_frame(config, satel_frame(0x7D, bytes([zone_byte])), transport)
                finally:
                    config["ethm_timeout"] = previous_timeout
            else:
                ethm_host = config["ethm_host"]
                ethm_port = int(config.get("ethm_port", 7094))
                timeout = max(float(config.get("ethm_timeout", 2.0)), float(config.get("temperature_timeout", 5.0)))
                response = query_ethm(
                    ethm_host,
                    ethm_port,
                    timeout,
                    satel_frame(0x7D, bytes([zone_byte])),
                    create_encryption_handler(config),
                )
            data = data_from_response(response)
            temperature = temperature_from_data(data)
            if temperature is None:
                debug_log(config, f"temperature: zone={number} response={response.hex(' ').upper()} value=unknown")
                continue
            payload[f"SATEL_TEMP_{number:03d}"] = f"{temperature:.1f}"
            if cfg_bool(config, "send_temperature_raw", False):
                payload[f"SATEL_TEMP_{number:03d}_RAW"] = (int(data[1]) << 8) | int(data[2])
            debug_log(config, f"temperature: zone={number} response={response.hex(' ').upper()} value={temperature:.1f}")
        except Exception as exc:
            payload["SATEL_ERROR"] = 1
            log(f"temperature: zone={number} ERROR: {exc}")

    return payload


def apply_zone_hold(payload, held_until, hold_seconds, now):
    if hold_seconds <= 0:
        return payload

    held = dict(payload)
    zone_any = 0
    for key, value in list(held.items()):
        if not key.startswith("SATEL_ZONE_") or key == "SATEL_ZONE_ANY":
            continue
        if key == "SATEL_ZONE_BYPASS_ANY" or key.endswith("_BYPASS"):
            continue
        suffix = key[len("SATEL_ZONE_"):]
        if not (len(suffix) == 3 and suffix.isdigit()):
            continue
        if value:
            held_until[key] = now + hold_seconds
        elif now < held_until.get(key, 0):
            held[key] = 1
        if held[key]:
            zone_any = 1

    if "SATEL_ZONE_ANY" in held:
        held["SATEL_ZONE_ANY"] = zone_any
    return held


def filter_changed_payload(payload, last_payload, full_refresh_due):
    if full_refresh_due:
        return dict(payload)
    changed = {}
    for key, value in payload.items():
        if last_payload.get(key) != value:
            changed[key] = value
    return changed


def send_changed_payload(config, payload, last_payload):
    payload_to_send = filter_changed_payload(payload, last_payload, False)
    if payload_to_send:
        send_status(config, payload_to_send)
    last_payload.update(payload)


def main():
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    log(f"SATEL ETHM Bridge {VERSION} started config_file={config_file_path()}")

    started_at = time.time()
    update_runtime_state(
        {
            "service_state": "running",
            "service_version": VERSION,
            "service_started_ts": int(started_at),
            "service_started_iso": datetime.now().isoformat(timespec="seconds"),
            "config_file": config_file_path(),
        },
        force=True,
    )
    last_error_sent = 0
    last_status_ok_at = 0
    last_push_frame_at = 0
    next_status_poll = 0
    next_zone_poll = 0
    next_output_poll = 0
    next_temperature_poll = 0
    last_status_full_refresh = 0
    last_zone_full_refresh = 0
    last_output_full_refresh = 0
    last_status_payload = {}
    last_zone_payload = {}
    last_output_payload = {}
    last_push_payload = {}
    held_until = {}
    push_sock = None
    push_buffer = b""
    push_crypto = None
    next_push_reconnect = 0
    push_reconnects = 0
    last_push_trigger = 0
    last_push_enabled = None
    last_push_endpoint = None
    mqtt_control_sock = None
    mqtt_control_buffer = b""
    mqtt_control_packet_id = 1
    mqtt_control_reconnects = 0
    mqtt_control_last_ping = 0
    next_mqtt_control_reconnect = 0
    last_mqtt_control_enabled = None
    last_mqtt_control_endpoint = None
    while RUNNING:
        sleep_for = 0.2
        try:
            config = load_config()
            now = time.time()
            status_interval = cfg_float(config, "status_poll_interval", config.get("poll_interval", 5.0))
            status_full_refresh_interval = cfg_float(config, "status_full_refresh_interval", 30.0)
            zone_interval = cfg_float(config, "zones_poll_interval", 1.0)
            output_interval = cfg_float(config, "outputs_poll_interval", 2.0)
            temperature_interval = cfg_float(config, "temperature_poll_interval", 60.0)
            full_refresh_interval = cfg_float(config, "zones_full_refresh_interval", 30.0)
            output_full_refresh_interval = cfg_float(config, "outputs_full_refresh_interval", 30.0)
            hold_seconds = cfg_float(config, "zone_hold_seconds", 0.0)
            send_status_on_change = cfg_bool(config, "status_send_on_change", True)
            send_zones_on_change = cfg_bool(config, "zones_send_on_change", True)
            send_outputs_on_change = cfg_bool(config, "outputs_send_on_change", True)
            push_enabled = cfg_bool(config, "push_enabled", True)
            push_reconnect_interval = cfg_float(config, "push_reconnect_interval", 10.0)
            push_debounce_seconds = cfg_float(config, "push_debounce_seconds", 0.3)
            watchdog_status_max_age = cfg_float(config, "watchdog_status_max_age", 30.0)
            watchdog_push_max_age = cfg_float(config, "watchdog_push_max_age", 300.0)
            mqtt_control_enabled = mqtt_enabled(config) and cfg_bool(config, "mqtt_control_enabled", False)
            mqtt_reconnect_interval = cfg_float(config, "mqtt_reconnect_interval", 10.0)
            mqtt_keepalive = cfg_float(config, "mqtt_keepalive", 60.0)
            push_endpoint = (
                str(config.get("ethm_host", "")),
                int(config.get("ethm_port", 7094)),
                ethm_encryption_enabled(config),
                str(config.get("ethm_integration_key", "")).strip() if ethm_encryption_enabled(config) else "",
            )
            mqtt_control_endpoint = (
                str(config.get("mqtt_host", "localhost")).strip(),
                int(config.get("mqtt_port", 1883)),
                mqtt_base_topic(config),
                str(config.get("mqtt_username", "")).strip(),
                bool(str(config.get("mqtt_password", "")).strip()),
            )

            if push_enabled != last_push_enabled or push_endpoint != last_push_endpoint:
                if push_sock is not None:
                    close_socket(push_sock)
                    push_sock = None
                    push_crypto = None
                push_buffer = b""
                next_push_reconnect = 0
                last_push_trigger = 0
                next_status_poll = 0
                next_zone_poll = 0
                next_output_poll = 0
                if push_enabled:
                    log(
                        f"push: enabled endpoint={push_endpoint[0]}:{push_endpoint[1]} "
                        f"encrypted={1 if push_endpoint[2] else 0}"
                    )
                else:
                    log("push: disabled")
                last_push_enabled = push_enabled
                last_push_endpoint = push_endpoint

            if push_enabled:
                if push_sock is None and now >= next_push_reconnect:
                    try:
                        push_sock = open_push_socket(config)
                        push_crypto = create_encryption_handler(config)
                        push_buffer = b""
                        log("push: connected to ETHM")
                        update_runtime_state(
                            {
                                "push_connected": 1,
                                "push_reconnects": push_reconnects,
                                "push_status_iso": datetime.now().isoformat(timespec="seconds"),
                                "events": runtime_events_with(runtime_event(
                                    "push",
                                    "Push polaczony",
                                    f"{push_endpoint[0]}:{push_endpoint[1]}",
                                )),
                            },
                            force=True,
                        )
                        send_changed_payload(
                            config,
                            {
                                "SATEL_PUSH_CONNECTED": 1,
                                "SATEL_PUSH_RECONNECTS": push_reconnects,
                            },
                            last_push_payload,
                        )
                        next_status_poll = 0
                        next_zone_poll = 0
                        next_output_poll = 0
                    except Exception as exc:
                        push_reconnects += 1
                        log(f"push: connect ERROR: {exc}")
                        update_runtime_state(
                            {
                                "push_connected": 0,
                                "push_reconnects": push_reconnects,
                                "push_last_error": str(exc),
                                "push_status_iso": datetime.now().isoformat(timespec="seconds"),
                                "events": runtime_events_with(runtime_event(
                                    "push",
                                    "Push ERROR",
                                    str(exc),
                                )),
                            },
                            force=True,
                        )
                        send_changed_payload(
                            config,
                            {
                                "SATEL_PUSH_CONNECTED": 0,
                                "SATEL_PUSH_RECONNECTS": push_reconnects,
                            },
                            last_push_payload,
                        )
                        next_push_reconnect = now + max(1.0, push_reconnect_interval)

                if push_sock is not None:
                    try:
                        frames, push_buffer = read_push_frames(push_sock, push_buffer, push_crypto)
                        if frames:
                            last_push_frame_at = now
                            update_runtime_state(
                                {
                                    "last_push_ts": int(now),
                                    "last_push_iso": datetime.now().isoformat(timespec="seconds"),
                                    "last_push_count": len(frames),
                                    "last_push_frame": frames[-1].hex(" ").upper(),
                                    "push_connected": 1,
                                    "push_reconnects": push_reconnects,
                                    "events": runtime_events_with(runtime_event(
                                        "push",
                                        "Ramka push",
                                        f"{len(frames)} ramka/ramki",
                                        frame=frames[-1].hex(" ").upper(),
                                    )),
                                },
                                force=True,
                            )
                            debug_log(config, f"push: received {len(frames)} frame(s)")
                            for frame in frames[:5]:
                                debug_log(config, f"push: frame={frame.hex(' ').upper()}")
                            if now - last_push_trigger >= max(0.0, push_debounce_seconds):
                                last_push_trigger = now
                                next_status_poll = 0
                                next_zone_poll = 0
                                next_output_poll = 0
                    except Exception as exc:
                        close_socket(push_sock)
                        push_sock = None
                        push_crypto = None
                        push_buffer = b""
                        push_reconnects += 1
                        log(f"push: disconnected: {exc}")
                        update_runtime_state(
                            {
                                "push_connected": 0,
                                "push_reconnects": push_reconnects,
                                "push_last_error": str(exc),
                                "push_status_iso": datetime.now().isoformat(timespec="seconds"),
                                "events": runtime_events_with(runtime_event(
                                    "push",
                                    "Push rozlaczony",
                                    str(exc),
                                )),
                            },
                            force=True,
                        )
                        send_changed_payload(
                            config,
                            {
                                "SATEL_PUSH_CONNECTED": 0,
                                "SATEL_PUSH_RECONNECTS": push_reconnects,
                            },
                            last_push_payload,
                        )
                        next_push_reconnect = now + max(1.0, push_reconnect_interval)
            else:
                if push_sock is not None:
                    close_socket(push_sock)
                    push_sock = None
                    push_crypto = None
                    push_buffer = b""
                send_changed_payload(
                    config,
                    {
                        "SATEL_PUSH_CONNECTED": 0,
                        "SATEL_PUSH_RECONNECTS": push_reconnects,
                    },
                    last_push_payload,
                )
                update_runtime_state({
                    "push_connected": 0,
                    "push_reconnects": push_reconnects,
                    "push_status_iso": datetime.now().isoformat(timespec="seconds"),
                })

            if mqtt_control_enabled != last_mqtt_control_enabled or mqtt_control_endpoint != last_mqtt_control_endpoint:
                mqtt_disconnect(mqtt_control_sock)
                mqtt_control_sock = None
                mqtt_control_buffer = b""
                next_mqtt_control_reconnect = 0
                mqtt_control_last_ping = 0
                if mqtt_control_enabled:
                    log(
                        "mqtt_control: enabled "
                        f"broker={mqtt_control_endpoint[0]}:{mqtt_control_endpoint[1]} "
                        f"topic={mqtt_control_endpoint[2]}/control/#"
                    )
                else:
                    log("mqtt_control: disabled")
                    update_runtime_state({"mqtt_control_connected": 0})
                last_mqtt_control_enabled = mqtt_control_enabled
                last_mqtt_control_endpoint = mqtt_control_endpoint

            if mqtt_control_enabled:
                if mqtt_control_sock is None and now >= next_mqtt_control_reconnect:
                    try:
                        mqtt_control_sock, mqtt_control_buffer, mqtt_control_packet_id = mqtt_connect_control(config)
                        mqtt_control_last_ping = now
                        log("mqtt_control: connected")
                    except Exception as exc:
                        mqtt_control_reconnects += 1
                        log(f"mqtt_control: connect ERROR: {exc}")
                        update_runtime_state({
                            "mqtt_control_connected": 0,
                            "mqtt_control_reconnects": mqtt_control_reconnects,
                            "mqtt_control_last_error": str(exc),
                            "mqtt_control_last_error_iso": datetime.now().isoformat(timespec="seconds"),
                        }, force=True)
                        next_mqtt_control_reconnect = now + max(1.0, mqtt_reconnect_interval)
                if mqtt_control_sock is not None:
                    try:
                        messages, mqtt_control_buffer = mqtt_poll(mqtt_control_sock, mqtt_control_buffer)
                        if messages:
                            mqtt_process_control_messages(config, messages)
                        if now - mqtt_control_last_ping >= max(10.0, mqtt_keepalive / 2.0):
                            mqtt_ping(mqtt_control_sock)
                            mqtt_control_last_ping = now
                    except Exception as exc:
                        log(f"mqtt_control: disconnected: {exc}")
                        mqtt_disconnect(mqtt_control_sock)
                        mqtt_control_sock = None
                        mqtt_control_buffer = b""
                        mqtt_control_reconnects += 1
                        update_runtime_state({
                            "mqtt_control_connected": 0,
                            "mqtt_control_reconnects": mqtt_control_reconnects,
                            "mqtt_control_last_error": str(exc),
                            "mqtt_control_last_error_iso": datetime.now().isoformat(timespec="seconds"),
                        }, force=True)
                        next_mqtt_control_reconnect = now + max(1.0, mqtt_reconnect_interval)
            else:
                if mqtt_control_sock is not None:
                    mqtt_disconnect(mqtt_control_sock)
                    mqtt_control_sock = None
                    mqtt_control_buffer = b""
                update_runtime_state({"mqtt_control_connected": 0})

            control_transport = {"sock": push_sock, "buffer": push_buffer} if push_sock is not None and push_crypto is None else None
            control_count = process_control_requests(config, control_transport)
            if control_transport is not None:
                push_buffer = control_transport.get("buffer", b"")
            if control_count:
                next_status_poll = 0
                next_zone_poll = 0
                next_output_poll = 0

            if now >= next_status_poll:
                debug_log(
                    config,
                    "config: "
                    f"config_file={config_file_path()} "
                    f"ethm={config.get('ethm_host')}:{config.get('ethm_port', 7094)} "
                    f"loxone_udp={config.get('loxone_host')}:{config.get('loxone_udp_port')} "
                    f"status_interval={status_interval}s zones_interval={zone_interval}s "
                    f"outputs_interval={output_interval}s temperature_interval={temperature_interval}s"
                )
                transport = {"sock": push_sock, "buffer": push_buffer} if push_sock is not None and push_crypto is None else None
                payload = read_core_statuses(config, transport)
                if payload.get("SATEL_ONLINE"):
                    last_status_ok_at = now
                payload, _ready_zone_payload = add_ready_status(config, payload, last_zone_payload)
                if transport is not None:
                    push_buffer = transport.get("buffer", b"")
                status_full_refresh_due = status_full_refresh_interval > 0 and now - last_status_full_refresh >= status_full_refresh_interval
                if cfg_bool(config, "send_diagnostics", True) and status_full_refresh_due:
                    status_age = int(now - last_status_ok_at) if last_status_ok_at else 999999
                    push_age = int(now - last_push_frame_at) if last_push_frame_at else 999999
                    status_ok = 1 if status_age <= watchdog_status_max_age else 0
                    push_ok = 1
                    if push_enabled:
                        push_ok = 1 if (push_sock is not None and push_age <= watchdog_push_max_age) else 0
                    watchdog_ok = 1 if (status_ok and push_ok) else 0
                    payload["SATEL_DIAG_UPTIME"] = int(now - started_at)
                    payload["SATEL_DIAG_LAST_STATUS_OK_AGE"] = status_age
                    payload["SATEL_DIAG_LAST_PUSH_AGE"] = push_age
                    payload["SATEL_DIAG_CONFIG_RELOAD_TS"] = int(now)
                    payload["SATEL_WATCHDOG_OK"] = watchdog_ok
                    payload["SATEL_WATCHDOG_STATUS_OK"] = status_ok
                    payload["SATEL_WATCHDOG_PUSH_OK"] = push_ok
                    payload["SATEL_WATCHDOG_STATUS_MAX_AGE"] = int(watchdog_status_max_age)
                    payload["SATEL_WATCHDOG_PUSH_MAX_AGE"] = int(watchdog_push_max_age)
                if send_status_on_change:
                    payload_to_send = filter_changed_payload(payload, last_status_payload, status_full_refresh_due)
                else:
                    payload_to_send = dict(payload)
                if payload_to_send:
                    send_status(config, payload_to_send)
                last_status_payload.update(payload)
                push_payload = {
                    "SATEL_PUSH_CONNECTED": 1 if push_sock is not None else 0,
                    "SATEL_PUSH_RECONNECTS": push_reconnects,
                }
                push_payload_to_send = filter_changed_payload(push_payload, last_push_payload, status_full_refresh_due)
                if push_payload_to_send:
                    send_status(config, push_payload_to_send)
                last_push_payload.update(push_payload)
                if status_full_refresh_due:
                    last_status_full_refresh = now
                next_status_poll = now + max(0.5, status_interval)

            zones_enabled = cfg_bool(config, "poll_zones", False) and bool(configured_zones(config))
            outputs_enabled = cfg_bool(config, "poll_outputs", True) and bool(configured_outputs(config))
            temperatures_enabled = cfg_bool(config, "poll_temperatures", False) and bool(configured_temperature_zones(config))

            if zones_enabled and now >= next_zone_poll:
                transport = {"sock": push_sock, "buffer": push_buffer} if push_sock is not None and push_crypto is None else None
                zone_payload = read_zone_statuses(config, transport)
                if transport is not None:
                    push_buffer = transport.get("buffer", b"")
                zone_payload = apply_zone_hold(zone_payload, held_until, hold_seconds, now)
                ready_status_payload, zone_payload = add_ready_status(config, dict(last_status_payload), zone_payload)
                ready_payload = {
                    key: value for key, value in ready_status_payload.items()
                    if key.startswith("SATEL_READY_")
                    or (key.startswith("SATEL_PARTITION_") and "_READY_" in key)
                }
                ready_payload_to_send = filter_changed_payload(ready_payload, last_status_payload, False)
                if ready_payload_to_send:
                    send_status(config, ready_payload_to_send)
                    last_status_payload.update(ready_payload)
                full_refresh_due = full_refresh_interval > 0 and now - last_zone_full_refresh >= full_refresh_interval
                if send_zones_on_change:
                    payload_to_send = filter_changed_payload(zone_payload, last_zone_payload, full_refresh_due)
                else:
                    payload_to_send = dict(zone_payload)
                if payload_to_send:
                    send_status(config, payload_to_send)
                last_zone_payload.update(zone_payload)
                if full_refresh_due:
                    last_zone_full_refresh = now
                next_zone_poll = now + max(0.2, zone_interval)

            if outputs_enabled and now >= next_output_poll:
                transport = {"sock": push_sock, "buffer": push_buffer} if push_sock is not None and push_crypto is None else None
                output_payload = read_output_statuses(config, transport)
                if transport is not None:
                    push_buffer = transport.get("buffer", b"")
                output_full_refresh_due = output_full_refresh_interval > 0 and now - last_output_full_refresh >= output_full_refresh_interval
                if send_outputs_on_change:
                    payload_to_send = filter_changed_payload(output_payload, last_output_payload, output_full_refresh_due)
                else:
                    payload_to_send = dict(output_payload)
                if payload_to_send:
                    send_status(config, payload_to_send)
                last_output_payload.update(output_payload)
                if output_full_refresh_due:
                    last_output_full_refresh = now
                next_output_poll = now + max(0.5, output_interval)

            if temperatures_enabled and now >= next_temperature_poll:
                transport = {"sock": push_sock, "buffer": push_buffer} if push_sock is not None and push_crypto is None else None
                temperature_payload = read_temperature_statuses(config, transport)
                if transport is not None:
                    push_buffer = transport.get("buffer", b"")
                if temperature_payload:
                    send_status(config, temperature_payload)
                next_temperature_poll = now + max(10.0, temperature_interval)

            next_times = [next_status_poll]
            if push_enabled:
                next_times.append(next_push_reconnect if push_sock is None else now + 0.2)
            if zones_enabled:
                next_times.append(next_zone_poll)
            if outputs_enabled:
                next_times.append(next_output_poll)
            if temperatures_enabled:
                next_times.append(next_temperature_poll)
            if mqtt_control_enabled:
                next_times.append(next_mqtt_control_reconnect if mqtt_control_sock is None else now + 0.2)
            sleep_for = min(max(0.05, min(next_times) - time.time()), 0.2)
        except Exception as exc:
            log(f"ERROR: {exc}")
            add_runtime_event("error", "Blad petli glownej", str(exc))
            try:
                config = load_config()
                now = time.time()
                if now - last_error_sent > 10:
                    send_status(config, {"SATEL_ONLINE": 0})
                    last_error_sent = now
            except Exception:
                pass
            sleep_for = 1.0
        time.sleep(sleep_for)

    close_socket(push_sock)
    mqtt_disconnect(mqtt_control_sock)
    update_runtime_state(
        {
            "service_state": "stopped",
            "service_stopped_ts": int(time.time()),
            "service_stopped_iso": datetime.now().isoformat(timespec="seconds"),
        },
        force=True,
    )
    log("SATEL ETHM Bridge stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
