"""Single-process append-only key/value store with durable acknowledgments."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import sys
import zlib

MAGIC = b"CVLT\x01\x00\x00\x00"
MAX_KEY, MAX_VALUE = 1024, 65536
MAX_PAYLOAD = 7 + MAX_KEY + MAX_VALUE


class CorruptionError(ValueError):
    """A complete record is invalid; never silently discard it."""


def validate(text: str, maximum: int, empty: bool = True) -> bytes:
    if not isinstance(text, str):
        raise ValueError("keys and values must be strings")
    if len(text) > maximum or (not empty and not text):
        raise ValueError("field length outside supported range")
    if any(not 32 <= ord(char) <= 126 for char in text):
        raise ValueError("fields must contain printable ASCII only")
    return text.encode("ascii")


def encode(operation: int, key: str, value: str = "") -> bytes:
    key_bytes = validate(key, MAX_KEY, False)
    value_bytes = validate(value, MAX_VALUE)
    payload = struct.pack("<BHI", operation, len(key_bytes), len(value_bytes)) + key_bytes + value_bytes
    return struct.pack("<II", len(payload), len(payload) ^ 0xFFFFFFFF) + payload + struct.pack("<I", zlib.crc32(payload))


class Store:
    """Exclusive ownership of a log is required; there is no process locking."""
    def __init__(self, path: str | Path, *, sync: bool = True):
        self.path = Path(path)
        self.sync = sync
        self.data: dict[str, str] = {}
        self.records = 0
        self.recovered_bytes = 0
        self.failed = False
        try:
            self.file = self.path.open("r+b")
        except FileNotFoundError:
            self.file = self.path.open("x+b")
        try:
            self._recover()
        except BaseException:
            self.file.close()
            raise

    def _flush(self) -> None:
        self.file.flush()
        if self.sync:
            os.fsync(self.file.fileno())

    def _recover(self) -> None:
        self.file.seek(0, 2)
        original_size = self.file.tell()
        if original_size > 2147483647:
            raise ValueError("log exceeds supported 2 GiB limit")
        self.file.seek(0)
        header = self.file.read(len(MAGIC))
        if len(header) < len(MAGIC):
            if not MAGIC.startswith(header):
                raise CorruptionError("invalid partial file header")
            self.recovered_bytes = len(header)
            self.file.seek(0)
            self.file.truncate()
            self.file.write(MAGIC)
            self._flush()
            return
        if header != MAGIC:
            raise CorruptionError("invalid file header or unsupported version")
        good_end = len(MAGIC)
        while True:
            frame_header = self.file.read(8)
            if not frame_header:
                break
            if len(frame_header) < 8:
                break
            length, complement = struct.unpack("<II", frame_header)
            if complement != length ^ 0xFFFFFFFF or not 8 <= length <= MAX_PAYLOAD:
                raise CorruptionError("invalid frame length")
            frame = self.file.read(length + 4)
            if len(frame) < length + 4:
                break
            payload, checksum = frame[:-4], frame[-4:]
            if zlib.crc32(payload) != struct.unpack("<I", checksum)[0]:
                raise CorruptionError("checksum mismatch")
            operation, key_length, value_length = struct.unpack("<BHI", payload[:7])
            if (operation not in (1, 2) or not 1 <= key_length <= MAX_KEY
                    or value_length > MAX_VALUE or 7 + key_length + value_length != length
                    or (operation == 2 and value_length)):
                raise CorruptionError("invalid record fields")
            try:
                key = payload[7:7+key_length].decode("ascii")
                value = payload[7+key_length:].decode("ascii")
                validate(key, MAX_KEY, False)
                validate(value, MAX_VALUE)
            except (UnicodeError, ValueError) as error:
                raise CorruptionError("invalid record text") from error
            if operation == 1:
                self.data[key] = value
            else:
                self.data.pop(key, None)
            self.records += 1
            good_end += 8 + length + 4
        self.recovered_bytes = original_size - good_end
        if self.recovered_bytes:
            self.file.seek(good_end)
            self.file.truncate()
            self._flush()
        self.file.seek(0, 2)

    def _append(self, record: bytes) -> None:
        if self.failed or self.file.closed:
            raise OSError("store is closed or failed; reopen before using it")
        if self.file.tell() + len(record) > 2147483647:
            raise ValueError("log exceeds supported 2 GiB limit")
        try:
            if self.file.write(record) != len(record):
                raise OSError("short write")
            self._flush()
        except BaseException:
            self.failed = True
            raise
        self.records += 1

    def put(self, key: str, value: str) -> None:
        self._append(encode(1, key, value))
        self.data[key] = value

    def get(self, key: str) -> str | None:
        validate(key, MAX_KEY, False)
        return self.data.get(key)

    def delete(self, key: str) -> bool:
        record = encode(2, key)
        existed = key in self.data
        self._append(record)
        self.data.pop(key, None)
        return existed

    def stats(self) -> dict:
        return {"keys": len(self.data), "records": self.records,
                "recovered_bytes": self.recovered_bytes, "file_bytes": self.file.tell()}

    def close(self) -> None:
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--no-sync", action="store_true", help="unsafe benchmark mode: skip fsync")
    args = parser.parse_args()
    # The CLI protocol is ASCII and works identically on Windows and Linux.
    sys.stdin.reconfigure(encoding="ascii")
    sys.stdout.reconfigure(encoding="ascii")
    try:
        with Store(args.file, sync=not args.no_sync) as store:
            for raw in sys.stdin:
                fields = raw.rstrip("\r\n").split("\t")
                if fields[0] == "PUT" and len(fields) == 3:
                    store.put(fields[1], fields[2]); result = {"ok": True}
                elif fields[0] == "GET" and len(fields) == 2:
                    result = {"value": store.get(fields[1])}
                elif fields[0] == "DEL" and len(fields) == 2:
                    result = {"deleted": store.delete(fields[1])}
                elif fields == ["STATS"]:
                    result = store.stats()
                else:
                    raise ValueError("expected PUT<tab>key<tab>value, GET<tab>key, DEL<tab>key or STATS")
                print(json.dumps(result), flush=True)
    except (OSError, ValueError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
