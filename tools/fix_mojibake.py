"""Repair UTF-8 text that was read as Windows-1252 and re-saved.

Symptom: emoji render as `ðŸŽ™ï¸`, ellipses as `â€¦`, in the browser and in the
editor. Cause: a tool in the export/import round trip read the UTF-8 bytes using
the Windows ANSI codepage (PowerShell 5.1's default for `Get-Content` /
`Set-Content`) and wrote them back out as UTF-8, so every non-ASCII byte became
its own character.

Windows-1252 leaves five byte values undefined (0x81 0x8D 0x8F 0x90 0x9D). The
Windows API passes those through unchanged, so the inverse mapping has to as
well -- Python's strict `cp1252` codec refuses them, which is why a plain
`s.encode("cp1252")` fails on any file containing an emoji.

Usage (from the repo root):

    python scripts/pr5/fix_mojibake.py --check          # report only
    python scripts/pr5/fix_mojibake.py --write          # repair in place

Idempotent: a clean file round-trips to itself and is left untouched.
"""
import argparse
import io
import sys

# Bytes Windows-1252 does not define; the Windows API round-trips them as the
# matching U+0080-U+009F code point.
_PASSTHROUGH = {0x81, 0x8D, 0x8F, 0x90, 0x9D}

TARGETS = [
    # Not just the frontend: .gitignore was mojibaked by the same import bug and
    # went unnoticed because it wasn't listed here.
    ".gitignore",
    "app/static/index.html",
    "app/static/js/app.js",
    "app/static/js/audio-recorder.js",
    "app/static/js/audio-player.js",
    "app/static/js/pcm-player-processor.js",
    "app/static/js/pcm-recorder-processor.js",
    "app/static/css/style.css",
]


def to_ansi_bytes(text: str) -> bytes | None:
    """Reverse of 'read these UTF-8 bytes as Windows-1252'. None if impossible."""
    out = bytearray()
    for ch in text:
        cp = ord(ch)
        if cp < 0x80:
            out.append(cp)
        elif cp in _PASSTHROUGH:
            out.append(cp)
        else:
            try:
                out.extend(ch.encode("cp1252"))
            except UnicodeEncodeError:
                # A genuine non-ASCII character that never came from mojibake.
                return None
    return bytes(out)


def repair(text: str) -> str | None:
    """Return the repaired text, or None if this file needs no repair."""
    raw = to_ansi_bytes(text)
    if raw is None:
        return None
    try:
        fixed = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return fixed if fixed != text else None


def main() -> int:
    # The Windows console is cp1252 by default and cannot print the emoji this
    # script exists to restore -- printing a sample would raise before writing
    # anything. Force UTF-8 out, degrading unprintable glyphs rather than dying.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - older interpreters / redirected stdout
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="repair in place")
    ap.add_argument("--check", action="store_true", help="report only (default)")
    ap.add_argument("paths", nargs="*", default=None)
    args = ap.parse_args()

    paths = args.paths or TARGETS
    changed = 0

    for p in paths:
        try:
            text = io.open(p, encoding="utf-8").read()
        except FileNotFoundError:
            print(f"skip   {p}  (not found)")
            continue
        except UnicodeDecodeError:
            print(f"SKIP   {p}  (not valid UTF-8 -- inspect by hand)")
            continue

        fixed = repair(text)
        if fixed is None:
            print(f"clean  {p}")
            continue

        changed += 1
        samples = [
            (a.strip()[:64], b.strip()[:64])
            for a, b in zip(text.splitlines(), fixed.splitlines())
            if a != b
        ][:3]
        print(f"REPAIR {p}  ({sum(1 for a, b in zip(text.splitlines(), fixed.splitlines()) if a != b)} lines)")
        for a, b in samples:
            print(f"         - {a}")
            print(f"         + {b}")

        if args.write:
            # newline="" so existing line endings survive untouched.
            with io.open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(fixed)

    if not changed:
        print("\nNothing to repair.")
    elif args.write:
        print(f"\nRepaired {changed} file(s). Hard-reload the browser (Ctrl+F5).")
    else:
        print(f"\n{changed} file(s) need repair. Re-run with --write to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
