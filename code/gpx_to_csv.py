#!/usr/bin/env python3
"""Convert all Strava GPX activity files into a single combined CSV of trackpoints."""

import csv
import gzip
import sys
import time as _time
from pathlib import Path
from xml.etree import ElementTree as ET

ACTIVITIES_DIR = Path("data/export_YOUR_ID/activities")
OUT_TRKPTS = Path("data/activities_trackpoints.csv")
OUT_SUMMARY = Path("data/activities_gpx_summary.csv")

NS = {
    "gpx": "http://www.topografix.com/GPX/1/1",
    "tpx": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1",
    "tpx2": "http://www.garmin.com/xmlschemas/TrackPointExtension/v2",
}


def open_gpx(path: Path):
    if path.suffixes[-2:] == [".gpx", ".gz"]:
        return gzip.open(path, "rb")
    return open(path, "rb")


def text(node, tag, ns="gpx"):
    if node is None:
        return ""
    el = node.find(f"{ns}:{tag}", NS)
    return el.text if el is not None and el.text is not None else ""


def find_ext(trkpt, tag):
    # Search both v1 and v2 TrackPointExtension namespaces.
    for ns in ("tpx", "tpx2"):
        el = trkpt.find(f"gpx:extensions/{ns}:TrackPointExtension/{ns}:{tag}", NS)
        if el is not None and el.text is not None:
            return el.text
    return ""


def main():
    files = sorted(
        list(ACTIVITIES_DIR.glob("*.gpx")) + list(ACTIVITIES_DIR.glob("*.gpx.gz"))
    )
    print(f"Found {len(files)} GPX files", file=sys.stderr)

    summary_rows = []
    total_pts = 0
    t0 = _time.time()

    with open(OUT_TRKPTS, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "activity_id", "track_name", "track_type",
            "time", "lat", "lon", "ele_m",
            "hr_bpm", "cad_rpm", "temp_c", "power_w",
        ])

        for i, path in enumerate(files, 1):
            # activity id = filename without all suffixes
            activity_id = path.name.split(".", 1)[0]
            try:
                with open_gpx(path) as fh:
                    tree = ET.parse(fh)
            except ET.ParseError as e:
                print(f"  parse error {path.name}: {e}", file=sys.stderr)
                continue

            root = tree.getroot()
            file_pts = 0
            for trk in root.findall("gpx:trk", NS):
                name = text(trk, "name")
                ttype = text(trk, "type")
                for seg in trk.findall("gpx:trkseg", NS):
                    for pt in seg.findall("gpx:trkpt", NS):
                        lat = pt.get("lat", "")
                        lon = pt.get("lon", "")
                        ele = text(pt, "ele")
                        when = text(pt, "time")
                        hr = find_ext(pt, "hr")
                        cad = find_ext(pt, "cad")
                        temp = find_ext(pt, "atemp")
                        power = find_ext(pt, "power")
                        w.writerow([
                            activity_id, name, ttype,
                            when, lat, lon, ele,
                            hr, cad, temp, power,
                        ])
                        file_pts += 1

                summary_rows.append({
                    "activity_id": activity_id,
                    "track_name": name,
                    "track_type": ttype,
                    "trackpoints": file_pts,
                    "source_file": path.name,
                })

            total_pts += file_pts
            if i % 50 == 0 or i == len(files):
                dt = _time.time() - t0
                print(
                    f"  [{i}/{len(files)}] {path.name}  pts_so_far={total_pts:,}  "
                    f"elapsed={dt:.1f}s",
                    file=sys.stderr,
                )

    with open(OUT_SUMMARY, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["activity_id", "track_name", "track_type", "trackpoints", "source_file"]
        )
        w.writeheader()
        w.writerows(summary_rows)

    print(f"Done. {total_pts:,} trackpoints from {len(files)} files in {_time.time()-t0:.1f}s",
          file=sys.stderr)
    print(f"  trackpoints -> {OUT_TRKPTS}", file=sys.stderr)
    print(f"  summary     -> {OUT_SUMMARY}", file=sys.stderr)


if __name__ == "__main__":
    main()
