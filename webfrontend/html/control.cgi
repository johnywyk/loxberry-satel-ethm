#!/usr/bin/env python3
import cgi
import html
import json
import os
import secrets
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except Exception:
    Cipher = None
    algorithms = None
    modes = None

PLUGIN = "satel_ethm"
CONFIG_FILE = Path(os.environ.get("SATEL_ETHM_CONFIG", f"/opt/loxberry/data/system/{PLUGIN}/config.json"))
LEGACY_CONFIG_FILES = [
    Path(f"/opt/loxberry/data/plugins/{PLUGIN}/config.json"),
    Path(f"/opt/loxberry/config/plugins/{PLUGIN}/config.json"),
]
LOG_FILE = Path(f"/opt/loxberry/log/plugins/{PLUGIN}/satel_ethm_control.log")
VERSION = "0.24.0"
CONTROL_QUEUE_DIR = CONFIG_FILE.parent / "control_queue"

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


def log(message):
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


def fail(message, status="400 Bad Request"):
    print(f"Status: {status}")
    print("Content-Type: text/plain; charset=utf-8")
    print()
    print(f"ERROR {message}")
    log(f"ERROR {message}")
    return 1


def ok(message):
    print("Content-Type: text/plain; charset=utf-8")
    print()
    print(message)
    log(message.replace("\n", " | "))
    return 0


def write_json_atomic(path, payload):
    tmp_path = Path(f"{path}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
        fh.write("\n")
    tmp_path.replace(path)


def load_config():
    source_file = CONFIG_FILE
    if not source_file.exists():
        for legacy_file in LEGACY_CONFIG_FILES:
            if legacy_file.exists():
                source_file = legacy_file
                break
    with source_file.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def request_ip():
    return (
        os.environ.get("REMOTE_ADDR")
        or os.environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or ""
    )


def split_ip_list(value):
    normalized = str(value or "").replace(",", " ").replace(";", " ")
    return [item.strip() for item in normalized.split() if item.strip()]


def control_ip_allowed(config, remote_ip):
    allowed = split_ip_list(config.get("allowed_control_ips", ""))
    return not allowed or remote_ip in allowed


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


def config_bool(config, key, default=False):
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "tak")
    return bool(value)


def create_encryption_handler(config):
    if not config_bool(config, "ethm_encryption_enabled", False):
        return None
    key = str(config.get("ethm_integration_key", "")).strip()
    if not key:
        return None
    return EncryptedCommunicationHandler(key)


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
        frame = find_complete_frame(buffer)
        if frame:
            return [frame], buffer[buffer.find(frame) + len(frame):]
        return [], buffer
    frames = []
    while len(buffer) >= 1:
        data_len = buffer[0]
        if len(buffer) < data_len + 1:
            break
        pdu = buffer[1:data_len + 1]
        frames.append(trim_frame_padding(crypto.extract_data_from_pdu(pdu)))
        buffer = buffer[data_len + 1:]
    return frames, buffer


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


def find_complete_frame(buffer):
    start = buffer.find(b"\xFE\xFE")
    if start < 0:
        return None
    end = buffer.find(b"\xFE\x0D", start + 2)
    if end < 0:
        return None
    return buffer[start:end + 2]


def query_ethm(config, frame):
    host = config["ethm_host"]
    port = int(config.get("ethm_port", 7094))
    timeout = float(config.get("ethm_timeout", 2.0))
    crypto = create_encryption_handler(config)
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(prepare_transport_frame(frame, crypto))
        deadline = time.time() + timeout
        buffer = b""
        while time.time() < deadline:
            chunk = sock.recv(1024)
            if not chunk:
                break
            buffer += chunk
            frames, buffer = extract_transport_frames(buffer, crypto)
            if frames:
                return frames[0]
    raise TimeoutError("no response from ETHM")


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


def get_int(form, name, default=None):
    value = form.getfirst(name, default)
    if value is None or value == "":
        raise ValueError(f"missing parameter: {name}")
    return int(value)


def configured_partition_numbers(config):
    numbers = []
    for partition in config.get("control_partitions", []):
        try:
            number = int(partition.get("number", 0))
        except Exception:
            continue
        if partition.get("enabled", True) and 1 <= number <= 32:
            numbers.append(number)
    if not numbers:
        try:
            mask = int(config.get("partition_mask", 1))
        except Exception:
            mask = 1
        numbers = [number for number in range(1, 33) if mask & (1 << (number - 1))]
    if not numbers:
        numbers = [int(config.get("default_control_partition", 1))]
    return sorted(set(numbers))


def partition_numbers_from_form(config, form):
    raw_mask = str(form.getfirst("partition_mask", "")).strip()
    if raw_mask:
        mask = int(raw_mask, 0)
        numbers = [number for number in range(1, 33) if mask & (1 << (number - 1))]
        if not numbers:
            raise ValueError("partition_mask does not select any partition")
        return numbers

    raw = str(form.getfirst("partitions", "")).strip()
    if not raw:
        raw = str(form.getfirst("partition", "")).strip()
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


def result_from_response(response):
    body = unescape_frame(response)
    if len(body) < 3:
        return None, None
    cmd = body[0]
    data = body[1:-2]
    if cmd == 0xEF and data:
        return data[0], RESULT_TEXT.get(data[0], f"unknown result 0x{data[0]:02X}")
    return None, f"response command 0x{cmd:02X}"


def output_is_on(config, output_number):
    response = query_ethm(config, satel_frame(0x17))
    body = unescape_frame(response)
    data = body[1:-2]
    index = output_number - 1
    if index // 8 >= len(data):
        return False
    return bool(data[index // 8] & (1 << (index % 8)))


def build_command(config, form):
    action = form.getfirst("action", "").strip().lower()
    code = user_code_bytes(config.get("satel_user_code", ""))

    if action in ("arm", "force_arm"):
        partitions = partition_numbers_from_form(config, form)
        mode = max(0, min(3, get_int(form, "mode", 0)))
        cmd = (0xA0 if action == "force_arm" else 0x80) + mode
        return cmd, code + bitmask_bytes(partitions, 4), f"{action} partitions={format_partition_numbers(partitions)} mode={mode}"

    if action == "disarm":
        partitions = partition_numbers_from_form(config, form)
        return 0x84, code + bitmask_bytes(partitions, 4), f"disarm partitions={format_partition_numbers(partitions)}"

    if action == "clear_alarm":
        partitions = partition_numbers_from_form(config, form)
        return 0x85, code + bitmask_bytes(partitions, 4), f"clear_alarm partitions={format_partition_numbers(partitions)}"

    if action == "clear_trouble":
        return 0x8B, code, "clear_trouble"

    if action in ("output_on", "output_off", "output_toggle"):
        output = get_int(form, "output")
        if action == "output_toggle":
            action = "output_off" if output_is_on(config, output) else "output_on"
        cmd = 0x88 if action == "output_on" else 0x89
        return cmd, code + bitmask_bytes([output], 16), f"{action} output={output}"

    if action in ("zone_bypass", "zone_unbypass"):
        zone = get_int(form, "zone")
        cmd = 0x86 if action == "zone_bypass" else 0x87
        return cmd, code + bitmask_bytes([zone], 16), f"{action} zone={zone}"

    if action == "open_door":
        output = get_int(form, "output")
        expander = get_int(form, "expander", 1)
        data = code + bitmask_bytes([output], 16) + bitmask_bytes([expander], 8)
        return 0x8A, data, f"open_door output={output} expander={expander}"

    raise ValueError(f"unsupported action: {action}")


def enqueue_control_request(config, form):
    CONTROL_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    request_id = secrets.token_hex(12)
    request_path = CONTROL_QUEUE_DIR / f"{request_id}.request.json"
    response_path = CONTROL_QUEUE_DIR / f"{request_id}.response.json"
    params = {}
    for key in ("action", "partition", "partitions", "partition_mask", "mode", "output", "zone", "expander"):
        value = form.getfirst(key)
        if value is not None:
            params[key] = value

    write_json_atomic(
        request_path,
        {
            "created": time.time(),
            "params": params,
            "source": "control.cgi",
        },
    )

    confirm_timeout = 0.0
    if str(config.get("control_confirm_blocking", False)).lower() not in ("0", "false", "no", "off", "nie"):
        try:
            confirm_timeout = float(config.get("control_confirm_timeout", 20.0))
        except Exception:
            confirm_timeout = 20.0
    deadline = time.time() + max(4.0, float(config.get("ethm_timeout", 2.0)) + confirm_timeout + 5.0)
    while time.time() < deadline:
        if response_path.exists():
            try:
                with response_path.open("r", encoding="utf-8") as fh:
                    response = json.load(fh)
            finally:
                try:
                    response_path.unlink()
                except Exception:
                    pass
            return response
        time.sleep(0.1)

    try:
        request_path.unlink()
    except Exception:
        pass
    raise TimeoutError("control queue timeout")


def main():
    form = cgi.FieldStorage()
    try:
        config = load_config()
    except Exception as exc:
        return fail(f"cannot load config: {exc}", "500 Internal Server Error")

    remote_ip = request_ip()
    if not control_ip_allowed(config, remote_ip):
        log(f"REJECT forbidden ip={remote_ip} action={form.getfirst('action', '')}")
        return fail("forbidden source ip", "403 Forbidden")

    token = str(config.get("control_token", ""))
    if token and form.getfirst("token", "") != token:
        log(f"REJECT bad token ip={remote_ip} action={form.getfirst('action', '')}")
        return fail("bad token", "403 Forbidden")

    try:
        queued_response = enqueue_control_request(config, form)
        message = queued_response.get("message", "")
        if queued_response.get("ok"):
            return ok(f"OK {message}")
        return fail(message or "control failed", "500 Internal Server Error")
    except Exception as queue_exc:
        log(f"queue fallback: {queue_exc}")

    try:
        cmd, data, description = build_command(config, form)
        frame = satel_frame(cmd, data)
        response = query_ethm(config, frame)
        result_code, result_text = result_from_response(response)
        response_hex = response.hex(" ").upper()
        if result_code in (0x00, 0xFF, None):
            return ok(f"OK {description}\nresult={result_text}\nresponse={response_hex}")
        return fail(f"{description}; result={result_text}; response={response_hex}", "500 Internal Server Error")
    except Exception as exc:
        return fail(html.escape(str(exc)), "500 Internal Server Error")


if __name__ == "__main__":
    sys.exit(main())
