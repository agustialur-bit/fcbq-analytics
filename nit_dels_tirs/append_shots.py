#!/usr/bin/env python3
"""Append one matchday's shots to data.json (the running season total).

Takes a JSON file with the new shots -- either a flat list of [x, y, made]
triples, or the raw {"x":.., "y":.., "fet":true/false} objects the FCBQ
shot-map export uses -- and appends them to data.json in this folder.

Usage:
    python3 append_shots.py new_matchday.json
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
data_path = HERE / "data.json"


def normalize(shot):
    if isinstance(shot, dict):
        return [shot["x"], shot["y"], 1 if shot.get("fet") else 0]
    x, y, made = shot
    return [x, y, 1 if made else 0]


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    new_shots = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    new_shots = [normalize(s) for s in new_shots]

    current = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else []
    current.extend(new_shots)
    data_path.write_text(json.dumps(current, separators=(",", ":")), encoding="utf-8")

    made = sum(s[2] for s in new_shots)
    total_made = sum(s[2] for s in current)
    print(f"added {len(new_shots)} shots ({made} made) -> season total: {len(current)} shots ({total_made} made)")


if __name__ == "__main__":
    main()
