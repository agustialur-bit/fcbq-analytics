#!/usr/bin/env python3
"""Build the "La Nit dels Tirs" poster from the accumulated season data.

Reads template.html and data.json (both in this folder) and writes the
finished, self-contained HTML page.

data.json is a flat list of [x, y, made] triples, one per shot:
  x, y  -- shot location as percentages, same convention as the FCBQ shot
           map export (x: 0-100 across the court width; y: distance from
           the basket, smaller = closer to the hoop).
  made  -- 1 if the shot went in, 0 otherwise.

Usage:
    python3 build.py [output.html]

To add a new matchday's shots first, see append_shots.py.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
template = (HERE / "template.html").read_text(encoding="utf-8")
data = (HERE / "data.json").read_text(encoding="utf-8").strip()

out_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "nit_dels_tirs.html"
out_path.write_text(template.replace("__SHOTS_DATA__", data), encoding="utf-8")
print(f"wrote {out_path} ({len(data.encode('utf-8'))} bytes of shot data)")
