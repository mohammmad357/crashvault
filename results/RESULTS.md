# Measured results

Median of 5 samples after one unrecorded warmup per workload/language. Values are 61 ASCII bytes; keys are 10 bytes.

| Workload | Language | Operations | Median ms | Median operations/s | Log bytes |
|---|---|---:|---:|---:|---:|
| unsynced writes | Python | 10000 | 844.526 | 11841 | 900008 |
| unsynced writes | C | 10000 | 125.968 | 79385 | 900008 |
| synced writes | Python | 200 | 461.685 | 433 | 18008 |
| synced writes | C | 200 | 339.451 | 589 | 18008 |
| replay | Python | 10000 | 301.504 | 33167 | 900008 |
| replay | C | 10000 | 17.441 | 573371 | 900008 |

## What these measurements mean

These measure complete CLI processes: startup, input parsing, log initialization/replay, encoding, checksums, hash indexing, writes, flush/sync calls and JSON output. They are not pure storage or language microbenchmarks. Replay uses an already-created log and benefits from a warm OS page cache.

Synced writes request fsync (Python/POSIX C) or _commit (Windows C) before each acknowledgment. Unsynced writes flush library buffers but skip that durability request; their throughput cannot be advertised as durable throughput. The modes also use different operation counts, so startup has a larger impact on the small synced batch.

A sync call's effectiveness depends on the filesystem, storage stack and hardware. The tests exercise process termination and synthetic truncation, not physical power loss. Results are specific to the recorded environment; scheduling and antivirus activity may affect these end-to-end Windows timings.

For replay, operations/s means log records replayed per second including process overhead, not GET requests/s. All output key/record counts are checked while benchmarking.

See [raw samples](raw.csv) and [environment metadata](environment.json).
