"""Differential, truncation, corruption and acknowledged-process-kill checks."""
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from crashvault import Store, CorruptionError, MAGIC, encode, MAX_KEY, MAX_VALUE


class VaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = Path(os.environ.get("VAULT_C", str(ROOT / "build" / ("crashvault.exe" if os.name == "nt" else "crashvault"))))
        if not cls.binary.exists():
            raise RuntimeError("Compile the C binary first")

    def native(self, path, commands="STATS\n", sync=False, check=True):
        args = [str(self.binary), str(path)] + ([] if sync else ["--no-sync"])
        return subprocess.run(args, input=commands, text=True, encoding="ascii", capture_output=True, check=check)

    def test_randomized_operations_and_cross_language_reopen(self):
        rng = random.Random(357)
        reference = {}; operations = []; expected = []
        for _ in range(2000):
            key = f"key-{rng.randrange(80)}"
            op = rng.choice(("PUT", "PUT", "DEL", "GET"))
            if op == "PUT":
                value = rng.choice(("", 'quotes"and\\slashes', str(rng.randrange(100000))))
                operations.append((op,key,value)); reference[key] = value; expected.append({"ok":True})
            elif op == "DEL":
                operations.append((op,key)); expected.append({"deleted":key in reference}); reference.pop(key,None)
            else:
                operations.append((op,key)); expected.append({"value":reference.get(key)})
        commands = "".join("\t".join(op)+"\n" for op in operations)
        with tempfile.TemporaryDirectory() as directory:
            pyfile, cfile = Path(directory)/"py.log", Path(directory)/"c.log"
            with Store(pyfile,sync=False) as store:
                for op, *args in operations:
                    if op == "PUT": store.put(*args)
                    elif op == "DEL": store.delete(*args)
                    else: store.get(*args)
                self.assertEqual(store.data,reference)
            response = self.native(cfile,commands)
            self.assertEqual([json.loads(line) for line in response.stdout.splitlines()],expected)
            self.assertEqual(pyfile.read_bytes(),cfile.read_bytes())
            with Store(cfile,sync=False) as store:
                self.assertEqual(store.data,reference)
                store.put("from-python","interoperable")
            query = "GET\tfrom-python\nPUT\tfrom-c\talso works\n"
            self.assertEqual(json.loads(self.native(cfile,query).stdout.splitlines()[0]),{"value":"interoperable"})
            with Store(cfile,sync=False) as store:
                self.assertEqual(store.get("from-c"),"also works")

    def test_every_byte_cut_recovers_only_complete_prefix(self):
        operations=[(1,"alpha","one"),(1,"beta","two"),(1,"alpha","updated"),(2,"beta","")]
        frames=[encode(*op) for op in operations]
        full=MAGIC+b"".join(frames)
        boundaries=[]; offset=len(MAGIC); state={}
        for (op,key,value),frame in zip(operations,frames):
            offset+=len(frame)
            if op==1: state[key]=value
            else: state.pop(key,None)
            boundaries.append((offset,dict(state)))
        with tempfile.TemporaryDirectory() as directory:
            for cut in range(len(full)+1):
                expected={}; end=8
                for boundary, data in boundaries:
                    if boundary<=cut: expected=data; end=boundary
                recovered=cut if cut<8 else cut-end
                with self.subTest(cut=cut):
                    pyfile,cfile=Path(directory)/"py.log",Path(directory)/"c.log"
                    pyfile.write_bytes(full[:cut]); cfile.write_bytes(full[:cut])
                    with Store(pyfile,sync=False) as store:
                        self.assertEqual(store.data,expected)
                        self.assertEqual(store.recovered_bytes,recovered)
                        store.put("resumed","yes")
                    response=self.native(cfile,"STATS\nPUT\tresumed\tyes\n")
                    stats=json.loads(response.stdout.splitlines()[0])
                    self.assertEqual(stats["keys"],len(expected))
                    self.assertEqual(stats["recovered_bytes"],recovered)
                    self.assertEqual(pyfile.read_bytes(),cfile.read_bytes())

    def assert_corrupt(self,path,blob):
        path.write_bytes(blob)
        with self.assertRaises(CorruptionError): Store(path,sync=False)
        self.assertNotEqual(self.native(path,check=False).returncode,0)
        self.assertEqual(path.read_bytes(),blob,"corrupt logs must not be rewritten")

    def test_every_single_bit_flip_in_complete_small_log_is_rejected(self):
        full=MAGIC+encode(1,"a","b")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"damaged.log"
            for byte in range(len(full)):
                for bit in range(8):
                    damaged=bytearray(full); damaged[byte]^=1<<bit
                    with self.subTest(byte=byte,bit=bit): self.assert_corrupt(path,damaged)

    def test_malformed_fields_with_valid_checksum(self):
        payloads=[struct.pack("<BHI",3,1,0)+b"k",struct.pack("<BHI",1,0,1)+b"v",
                  struct.pack("<BHI",2,1,1)+b"kv",struct.pack("<BHI",1,2,0)+b"k",
                  struct.pack("<BHI",1,1,1)+b"k\x00"]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"damaged.log"
            for payload in payloads:
                blob=MAGIC+struct.pack("<II",len(payload),len(payload)^0xffffffff)+payload+struct.pack("<I",zlib.crc32(payload))
                self.assert_corrupt(path,blob)

    def test_limits_empty_values_and_protocol_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"limits.log"
            commands="PUT\t"+"k"*MAX_KEY+"\t"+"v"*MAX_VALUE+"\nPUT\tempty\t\nGET\tempty\n"
            out=self.native(path,commands).stdout.splitlines()
            self.assertEqual(json.loads(out[-1]),{"value":""})
            with Store(path,sync=False) as store:
                self.assertEqual(store.get("k"*MAX_KEY),"v"*MAX_VALUE)
                for key,value in [("", "v"),("k"*(MAX_KEY+1),"v"),("k","v"*(MAX_VALUE+1)),("k","\t")]:
                    with self.assertRaises(ValueError): store.put(key,value)
            for command in ["PUT\t\tv\n","PUT\tk\tv\textra\n","GET\n","UNKNOWN\n","PUT\tk\t"+"v"*(MAX_VALUE+1)+"\n"]:
                self.assertNotEqual(self.native(path,command,check=False).returncode,0)

    def test_tombstones_and_hash_collisions(self):
        def bucket(key):
            h=14695981039346656037
            for byte in key.encode(): h=((h^byte)*1099511628211)&0xffffffffffffffff
            return h&63
        keys=[f"collision-{i}" for i in range(5000) if bucket(f"collision-{i}")==0][:30]
        operations=[f"PUT\t{k}\tv\n" for k in keys]+[f"DEL\t{k}\n" for k in keys[::2]]
        operations += [f"GET\t{k}\n" for k in keys]
        with tempfile.TemporaryDirectory() as directory:
            lines=self.native(Path(directory)/"collisions.log","".join(operations)).stdout.splitlines()[-len(keys):]
            self.assertEqual([json.loads(line)["value"] for line in lines],[None if i%2==0 else "v" for i in range(len(keys))])

    def test_acknowledged_writes_survive_process_kill(self):
        # This checks process termination after acknowledgment, not a power failure.
        with tempfile.TemporaryDirectory() as directory:
            for language,args in [("Python",[sys.executable,str(ROOT/"python"/"crashvault.py")]),("C",[str(self.binary)])]:
                path=Path(directory)/(language+".log")
                process=subprocess.Popen(args+[str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="ascii")
                try:
                    process.stdin.write("PUT\tconfirmed\tdurable\n"); process.stdin.flush()
                    self.assertEqual(json.loads(process.stdout.readline()),{"ok":True})
                    process.kill(); process.wait(timeout=10)
                finally:
                    if process.poll() is None: process.kill(); process.wait()
                    process.stdin.close(); process.stdout.close(); process.stderr.close()
                with Store(path) as store: self.assertEqual(store.get("confirmed"),"durable")

    def test_sync_failure_does_not_publish_state_and_poison_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"sync-error.log"
            with Store(path,sync=False) as store:
                store.put("stable","before")
                with patch.object(store,"_flush",side_effect=OSError("injected sync failure")):
                    with self.assertRaises(OSError): store.put("stable","uncertain")
                self.assertEqual(store.get("stable"),"before")
                self.assertTrue(store.failed)
                with self.assertRaises(OSError): store.put("another","blocked")
            # Closing flushes the buffered complete frame: no acknowledgment did not imply absence.
            with Store(path,sync=False) as store:
                self.assertEqual(store.get("stable"),"uncertain")


if __name__=="__main__": unittest.main()
