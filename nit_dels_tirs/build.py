#!/usr/bin/env python3
"""Build the "La Nit dels Tirs" poster from an accumulated shot dataset.

Reads template.html plus a data file (both in this folder) and writes the
finished, self-contained HTML page.

The data file is a flat list of [x, y, made] triples, one per shot:
  x, y  -- shot location as percentages, same convention as the FCBQ shot
           map export (x: 0-100 across the court width; y: distance from
           the basket, smaller = closer to the hoop).
  made  -- 1 if the shot went in, 0 otherwise.

There are two datasets in this folder -- see README.md:
  data.json                   -- last season, closed, never updated.
  data_temporada_actual.json  -- this season, grows matchday by matchday.

Usage:
    python3 build.py [output.html] [--data FILENAME]

To add a new matchday's shots first, see append_shots.py.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).parent

args = sys.argv[1:]
data_name = "data.json"
if "--data" in args:
    i = args.index("--data")
    data_name = args[i + 1]
    del args[i:i + 2]
out_path = pathlib.Path(args[0]) if args else HERE / "nit_dels_tirs.html"

template = (HERE / "template.html").read_text(encoding="utf-8")
data = (HERE / data_name).read_text(encoding="utf-8").strip()

out_path.write_text(template.replace("__SHOTS_DATA__", data), encoding="utf-8")
print(f"wrote {out_path} from {data_name} ({len(data.encode('utf-8'))} bytes of shot data)")
