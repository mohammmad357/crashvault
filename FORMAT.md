# CrashVault file format v1

All integers are unsigned and little-endian. Bytes are identical across Python and C; no native C structs are written to disk.

## File header

Eight bytes: `43 56 4c 54 01 00 00 00` (`CVLT`, version 1, three zero bytes).

## Each mutation frame

| Offset within frame | Size | Field |
|---:|---:|---|
| 0 | 4 | Payload length L |
| 4 | 4 | L XOR `0xffffffff` |
| 8 | 1 | Operation: 1 = PUT, 2 = DELETE |
| 9 | 2 | Key length K |
| 11 | 4 | Value length V |
| 15 | K | Printable ASCII key bytes |
| 15 + K | V | Printable ASCII value bytes |
| 8 + L | 4 | IEEE CRC32 of the L-byte payload |

`L = 7 + K + V`. Frame size is `12 + L = 19 + K + V`. Key length is 1..1024, value length 0..65,536; DELETE requires V = 0. CRC32 uses the reflected IEEE polynomial `0xedb88320`, initial state `0xffffffff` and final XOR `0xffffffff`, matching `zlib.crc32`. The length guard covers the two header length words by redundancy; the CRC covers payload bytes only. Neither provides authenticity.

## Invariants

Replay maintains the state of every complete valid mutation seen so far. A PUT replaces a value; DELETE removes it if present. There are no multi-record transactions or sequence numbers. GET/STATS never append mutation frames.

A frame is applied only after its complete header, payload, checksum and fields have been validated. Incomplete bytes at EOF are repairable only at the final frame. A complete invalid header/record stops recovery. Repairs truncate to the last complete valid boundary, then flush and, in default mode, request file sync.

A partial file magic is repairable only if it is a prefix of the expected eight bytes. A file with the correct header and no frames is an empty store. The maximum supported file size is 2,147,483,647 bytes.

This design handles synthetic prefix truncation. It does not recover arbitrary lost interior sectors, authenticate data, make a single frame an atomic hardware write, or detect deliberate coordinated changes to payload and checksum. The parent directory is not synced by v1.
