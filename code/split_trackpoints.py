#!/usr/bin/env python3
"""Split activities_trackpoints.csv into <40MB chunks; never split mid-activity."""

from pathlib import Path

SRC = Path("data/activities_trackpoints.csv")
OUT_DIR = Path("data/activities_trackpoints_parts")
MAX_BYTES = 38 * 1024 * 1024  # 38 MB target ceiling, well under 40

OUT_DIR.mkdir(exist_ok=True)
for old in OUT_DIR.glob("activities_trackpoints_part*.csv"):
    old.unlink()


def open_part(idx):
    p = OUT_DIR / f"activities_trackpoints_part{idx:02d}.csv"
    f = open(p, "wb")
    f.write(header)
    return p, f, len(header)


with open(SRC, "rb") as src:
    header = src.readline()

    part_idx = 1
    path, out, size = open_part(part_idx)
    current_activity = None
    pending_buf = b""           # rows for the activity currently being written
    pending_activity = None

    def flush_pending(out, size):
        global pending_buf, pending_activity
        if pending_buf:
            out.write(pending_buf)
            size += len(pending_buf)
            pending_buf = b""
            pending_activity = None
        return size

    for line in src:
        # activity_id is the first comma-separated field
        comma = line.find(b",")
        aid = line[:comma] if comma != -1 else line.rstrip()

        if aid != pending_activity:
            # boundary between activities — safe to consider rolling over.
            # Decide BEFORE flushing so the pending activity lands in the new
            # part rather than blowing past the cap on this one.
            if pending_buf and size + len(pending_buf) > MAX_BYTES:
                out.close()
                print(f"  wrote {path.name}  {size/1024/1024:.1f} MB")
                part_idx += 1
                path, out, size = open_part(part_idx)
            size = flush_pending(out, size)
            pending_activity = aid

        pending_buf += line

        # safety: if a single activity's buffer alone exceeds the cap, flush it
        # to avoid unbounded memory and just let that part exceed the target.
        if len(pending_buf) >= MAX_BYTES:
            size = flush_pending(out, size)

    size = flush_pending(out, size)
    out.close()
    print(f"  wrote {path.name}  {size/1024/1024:.1f} MB")

print(f"\nSplit into {part_idx} files in {OUT_DIR}")
