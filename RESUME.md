# Portfolio and resume notes

Suggested wording for this project, which was built with AI assistance. The discussion questions below connect each claim to a design decision or a test you can demonstrate.

## English portfolio description

**CrashVault — append-only key/value storage engine (Python, C11).** Implements a shared binary log format, CRC32 validation, replay-based recovery, and a custom open-addressed hash index in C. Verified interoperability with 2,000 deterministic operations, exhaustive byte-cut recovery on a small history, exhaustive single-bit corruption checks on a small log, and process-kill tests after synced acknowledgments. Includes reproducible end-to-end benchmarks and Linux sanitizer CI.

## Concise resume bullet

Developed CrashVault with AI assistance: interoperable Python/C11 storage engines with a checksummed append log, guarded record framing and restart recovery; validated with 2,000 seeded operations, byte-cut fault injection and post-acknowledgment process termination tests.

Do not call it distributed, fully transactional, production-grade, concurrency-safe or proven against power loss; those features are not implemented or demonstrated. Any performance number should identify workload, sync mode, machine and the end-to-end timing boundary. [The report](results/RESULTS.md) contains the measured values.

## متن فارسی برای معرفی پروژه

توسعهٔ CrashVault با کمک ابزارهای هوش مصنوعی: موتور ذخیره‌سازی کلید–مقدار در Python و C11 با قالب باینری مشترک، لاگ افزایشی، کنترل CRC32، شاخص هش و بازیابی پس از قطع نوشتن؛ اعتبارسنجی با ۲۰۰۰ عملیات دارای بذر ثابت، تزریق قطع بایتی و قطع پردازش پس از دریافت پاسخ موفق.

## Be ready to explain

1. Why append, flush and file sync happen before acknowledgment.
2. Why an incomplete frame is different from a complete frame with a bad CRC.
3. Why length redundancy matters when a damaged length could otherwise look like a truncated record.
4. Why missing acknowledgment can still mean a committed mutation.
5. Why C tombstones cannot simply become empty slots.
6. Why replay scales with history, and what crash-safe compaction would require.
7. Which failure models the tests cover and which remain untested.
