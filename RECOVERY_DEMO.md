# When is it safe to discard the tail?

A reproducible recovery experiment with the independent Python and C engines.
Run from the repository root after compiling `build/crashvault` (Windows:
`build/crashvault.exe`) using the README instructions:

```sh
python tools/recovery_demo.py --json results/RECOVERY_DEMO.json
```

The script uses disposable files in a temporary directory. It creates four
mutations: PUT alpha=one, PUT beta=two, PUT alpha=updated, DELETE beta.
It copies that valid history and appends just 13 bytes of another PUT frame.
This is **synthetic prefix truncation**, not a physical power-loss experiment.

## Measured result

Recorded on 2026-10-11 with Python 3.13.7, Windows 10 and GCC 15.2;
default file sync remained enabled. The [raw JSON](results/RECOVERY_DEMO.json)
records assertions, environment and outcomes; rerunning replaces that report.

| Stage | Bytes | Meaning |
|---|---:|---|
| Valid four-record history | 115 | alpha=updated; beta absent |
| Copy plus incomplete frame | 128 | 13 uncommitted synthetic bytes |
| Reopen in either language | 115 | Discard exactly the incomplete tail |
| Append resumed=yes | 144 | Continue successfully; both logs byte-identical |

Both engines report four recovered records and one live key. The pending key
is absent. The original valid log remains unchanged throughout the experiment.

The script also flips a CRC bit in a **complete** final record. Python raises
`CorruptionError`; C reports `checksum mismatch`. Both leave the damaged bytes
unchanged. Quietly truncating this complete record would conceal corruption of
a mutation that may already have been acknowledged.

## The engineering decision

Recover only an incomplete final frame. Reject complete invalid records.
The [format](FORMAT.md) combines a redundant length guard with a payload CRC32.
This makes a single-bit length error less likely to be mistaken for a long,
unfinished frame. CRC32 detects accidental corruption; it does not authenticate
records or defend against deliberate checksum rewriting.

An acknowledgement follows append, library flush and a file-sync request.
Losing an acknowledgement does not imply that the write is absent: an
unacknowledged complete record can still replay. The synthetic pending frame
here is incomplete by construction; it is not evidence that every interrupted
write disappears.

## Limits of this evidence

- No real power cut, device reordering or lost interior sectors were simulated.
- The parent directory is not synced when a new filename is created.
- Actual physical persistence depends on the filesystem and storage device.
- Open each log with one process/Store at a time; there is no process locking.
- C storage-call fault injection, compaction and multi-record transactions are
  outside this example. This is an educational engine, not a production claim.

The existing eight-test suite also passed locally, including seeded cross-
language operations, byte cuts, bit flips and termination after a synced ACK.
Run it yourself with `python -m unittest discover -s tests -v`; this local
result does not substitute for the repository's remote CI status.

## فارسی

در این آزمایش، تاریخچهٔ سالم ۱۱۵ بایت است. ۱۳ بایت از یک رکورد ناتمام
به کپی آن اضافه می‌شود؛ هر دو پیاده‌سازی فقط همان انتهای ناتمام را حذف
می‌کنند و با یک نوشتن تازه به ۱۴۴ بایت می‌رسند. فایل‌های نهایی یکسان‌اند.
اما اگر رکورد کامل خراب شود، بازیابی متوقف می‌شود و فایل دست‌نخورده
می‌ماند. این تفاوت مانع پنهان‌شدن خرابی دادهٔ تأییدشده می‌شود.

این آزمون قطع برق واقعی نیست؛ همگام‌سازی پوشه، قفل بین پردازش‌ها و
تضمین رفتار سخت‌افزار در آن وجود ندارد. نوشته با کمک هوش مصنوعی و
بر اساس خروجی اجرای واقعی تهیه شده است.
