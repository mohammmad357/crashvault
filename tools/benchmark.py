"""End-to-end CLI benchmarks; durable and unsynced writes stay separate."""
import argparse
import csv
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"python"))
from crashvault import Store


def workload(count):
    return "".join(f"PUT\tkey-{i:06d}\tvalue-{i:06d}-"+"x"*48+"\n" for i in range(count))+"STATS\n"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--count",type=int,default=10000)
    parser.add_argument("--sync-count",type=int,default=200)
    parser.add_argument("--samples",type=int,default=5)
    args=parser.parse_args()
    if not 1<=args.count<=1000000 or not 1<=args.sync_count<=10000 or not 1<=args.samples<=100:
        parser.error("count 1..1000000; sync-count 1..10000; samples 1..100")
    programs={"Python":[sys.executable,str(ROOT/"python"/"crashvault.py")],"C":[str(args.binary.resolve())]}
    rows=[]
    with tempfile.TemporaryDirectory() as directory:
        baseline=Path(directory)/"baseline.log"
        with Store(baseline,sync=False) as store:
            for i in range(args.count): store.put(f"key-{i:06d}",f"value-{i:06d}-"+"x"*48)
        for name,count,sync in [("unsynced writes",args.count,False),("synced writes",args.sync_count,True),("replay",args.count,False)]:
            for language,program in programs.items():
                for sample in range(args.samples+1):
                    path=baseline if name=="replay" else Path(directory)/f"{language}-{name}-{sample}.log"
                    commands="STATS\n" if name=="replay" else workload(count)
                    begin=perf_counter()
                    result=subprocess.run(program+[str(path)]+([] if sync else ["--no-sync"]),input=commands,text=True,encoding="ascii",capture_output=True,check=True)
                    elapsed=perf_counter()-begin
                    stats=json.loads(result.stdout.splitlines()[-1])
                    assert stats["keys"]==count and stats["records"]==count and stats["recovered_bytes"]==0
                    if sample:
                        rows.append(dict(workload=name,language=language,sample=sample,operations=count,milliseconds=elapsed*1000,
                                         operations_per_second=count/elapsed,file_bytes=stats["file_bytes"]))
                print(f"Measured {name}: {language}",flush=True)
    with (ROOT/"results"/"raw.csv").open("w",newline="",encoding="utf-8") as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]),lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    metadata=dict(platform=platform.platform(),processor=platform.processor(),python=sys.version,
                  compiler=subprocess.check_output(["gcc","--version"],text=True).splitlines()[0],
                  flags="-std=c11 -D_POSIX_C_SOURCE=200809L -O2 -Wall -Wextra -Wpedantic -Werror",
                  count=args.count,sync_count=args.sync_count,samples=args.samples,
                  timing="End-to-end wall clock: startup, recovery, stdin/stdout protocol and storage calls included",
                  warmup="one unrecorded fresh-file batch per language/workload",value_bytes=61)
    (ROOT/"results"/"environment.json").write_text(json.dumps(metadata,indent=2)+"\n",encoding="utf-8")
    report=["# Measured results","",f"Median of {args.samples} samples after one unrecorded warmup per workload/language. Values are 61 ASCII bytes; keys are 10 bytes.","",
            "| Workload | Language | Operations | Median ms | Median operations/s | Log bytes |","|---|---|---:|---:|---:|---:|"]
    for name in ("unsynced writes","synced writes","replay"):
        for language in programs:
            group=[r for r in rows if (r["workload"],r["language"])==(name,language)]
            report.append(f'| {name} | {language} | {group[0]["operations"]} | {statistics.median(r["milliseconds"] for r in group):.3f} | {statistics.median(r["operations_per_second"] for r in group):.0f} | {group[0]["file_bytes"]} |')
    report += ["","## What these measurements mean","",
               "These measure complete CLI processes: startup, input parsing, log initialization/replay, encoding, checksums, hash indexing, writes, flush/sync calls and JSON output. They are not pure storage or language microbenchmarks. Replay uses an already-created log and benefits from a warm OS page cache.","",
               "Synced writes request fsync (Python/POSIX C) or _commit (Windows C) before each acknowledgment. Unsynced writes flush library buffers but skip that durability request; their throughput cannot be advertised as durable throughput. The modes also use different operation counts, so startup has a larger impact on the small synced batch.","",
               "A sync call's effectiveness depends on the filesystem, storage stack and hardware. The tests exercise process termination and synthetic truncation, not physical power loss. Results are specific to the recorded environment; scheduling and antivirus activity may affect these end-to-end Windows timings.","",
               "For replay, operations/s means log records replayed per second including process overhead, not GET requests/s. All output key/record counts are checked while benchmarking.","",
               "See [raw samples](raw.csv) and [environment metadata](environment.json)."]
    (ROOT/"results"/"RESULTS.md").write_text("\n".join(report)+"\n",encoding="utf-8")


if __name__=="__main__": main()
