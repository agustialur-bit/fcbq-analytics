#!/usr/bin/env python3
"""Append one matchday's shots to the current-season dataset.

Takes a JSON file with the new shots -- either a flat list of [x, y, made]
triples, or the raw {"x":.., "y":.., "fet":true/false} objects the FCBQ
shot-map export uses -- and appends them to data_temporada_actual.json in
this folder (this season; see README.md -- data.json is last season and
is not meant to grow any further, pass --data data.json to target it
explicitly if that's really what's needed).

Usage:
    python3 append_shots.py new_matchday.json [--data FILENAME]
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent


def normalize(shot):
    if isinstance(shot, dict):
        return [shot["x"], shot["y"], 1 if shot.get("fet") else 0]
    x, y, made = shot
    return [x, y, 1 if made else 0]


def main():
    args = sys.argv[1:]
    data_name = "data_temporada_actual.json"
    if "--data" in args:
        i = args.index("--data")
        data_name = args[i + 1]
        del args[i:i + 2]

    if len(args) != 1:
        print(__doc__)
        sys.exit(1)

    data_path = HERE / data_name
    new_shots = json.loads(pathlib.Path(args[0]).read_text(encoding="utf-8"))
    new_shots = [normalize(s) for s in new_shots]

    current = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else []
    current.extend(new_shots)
    data_path.write_text(json.dumps(current, separators=(",", ":")), encoding="utf-8")

    made = sum(s[2] for s in new_shots)
    total_made = sum(s[2] for s in current)
    print(f"added {len(new_shots)} shots ({made} made) to {data_name} -> total: {len(current)} shots ({total_made} made)")


if __name__ == "__main__":
    main()
