"""Reproduce incomplete-tail repair and complete-corruption refusal in Python/C.

Run from the repository root after compiling build/crashvault[.exe].
All data is synthetic and temporary. No user log is modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from crashvault import CorruptionError, Store, encode


def run(binary: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="crashvault-demo-") as temporary:
        folder = Path(temporary)
        original = folder / "original.log"
        with Store(original) as store:
            store.put("alpha", "one")
            store.put("beta", "two")
            store.put("alpha", "updated")
            store.delete("beta")
        clean = original.read_bytes()
        tail = encode(1, "pending", "never-acknowledged")[:13]
        damaged = clean + tail
        py_path, c_path = folder / "python.log", folder / "c.log"
        py_path.write_bytes(damaged)
        c_path.write_bytes(damaged)
        with Store(py_path) as store:
            py_before = store.stats()
            py_values = {key:store.get(key) for key in ("alpha", "beta", "pending")}
            store.put("resumed", "yes")
        command = "STATS\nGET\talpha\nGET\tbeta\nGET\tpending\nPUT\tresumed\tyes\n"
        native = subprocess.run([str(binary), str(c_path)], input=command, text=True,
                                encoding="ascii", capture_output=True, check=True)
        answers = [json.loads(line) for line in native.stdout.splitlines()]
        expected = {"alpha":"updated", "beta":None, "pending":None}
        assert py_values == expected
        assert [line["value"] for line in answers[1:4]] == list(expected.values())
        assert py_before == answers[0]
        assert py_before["recovered_bytes"] == len(tail)
        assert py_before["file_bytes"] == len(clean)
        assert py_before["records"] == 4
        assert py_path.read_bytes() == c_path.read_bytes()
        assert original.read_bytes() == clean

        corrupt = bytearray(clean)
        corrupt[-1] ^= 1
        rejected = []
        for language in ("Python", "C"):
            path = folder / (language + "-corrupt.log")
            path.write_bytes(corrupt)
            if language == "Python":
                try:
                    Store(path)
                except CorruptionError:
                    error = "CorruptionError"
                else:
                    raise AssertionError("Complete corruption was accepted")
            else:
                result = subprocess.run([str(binary), str(path)], input="STATS\n",
                                        text=True, encoding="ascii", capture_output=True)
                assert result.returncode != 0
                error = result.stderr.strip()
            assert path.read_bytes() == corrupt
            rejected.append({"language":language, "error":error, "bytes_unchanged":True})
        return {
            "scenario":"synthetic partial tail, not real power loss",
            "environment":{"python":platform.python_version(), "platform":platform.platform()},
            "sync":True, "clean_bytes":len(clean), "torn_bytes":len(damaged),
            "discarded_incomplete_bytes":len(tail), "recovered":py_before,
            "values":py_values, "after_append_bytes":len(py_path.read_bytes()),
            "python_c_bytes_equal":True, "original_unchanged":True,
            "complete_corruption":rejected, "status":"PASS",
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c-binary", type=Path, default=ROOT / "build" / ("crashvault.exe" if os.name == "nt" else "crashvault"))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = run(args.c_binary.resolve())
    output = json.dumps(report, indent=2)
    if args.json:
        args.json.write_text(output + "\n", encoding="utf-8")
    print(output)
