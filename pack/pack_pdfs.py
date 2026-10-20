"""Maintainer tool: pack the PDFs of indexed papers into zip volumes for `envreview lit pdfs`.

  python pack/pack_pdfs.py --src "<folder of PDFs named by DOI suffix>" --out "<output folder>" [--dry-run]

Keeps only PDFs whose name (the part of the DOI after the first "/") is a paper in the index,
takes the largest copy when a name repeats, skips files under 1 KB, and writes:

  <out>/<CODE>_<years>[_partN].zip   stored (PDFs do not compress); inside: <CODE>/<year>/<name>.pdf
  <out>/pdf_manifest.csv             doi, journal, year, file, bytes, volume
  <out>/README.txt                   how to unpack and link the PDFs

Volumes are cut by journal and year at about --max-gb each (a year larger than that is split
into parts). A finished volume is skipped on a rerun. Zip entries carry CRC-32 checksums, so
damage in transfer shows up when unpacking.
"""
import argparse
import csv
import os
import sys
import zipfile
from pathlib import Path

import pandas as pd

CODES = {"Environmental Science & Technology": "EST", "Nature Climate Change": "NCC",
         "Nature Geoscience": "NGEO", "Nature Sustainability": "NSUS", "Nature Water": "NW",
         "One Earth": "OE", "Water Research": "WR"}

README = """PDFs for the env-journal-review literature search
=================================================

{n} PDFs of papers in the index, in {v} zip files ({gb:.0f} GB). Water Research and One Earth
papers came from the publisher as XML, so they have full text in the index but no PDF here.

1. Unpack every zip under one folder, e.g. D:\\env-journal-pdfs (Windows: right-click >
   Extract All, or 7-Zip). Any layout of subfolders is fine; the tool searches them all.
2. Link the folder once:
     python <skill folder>\\scripts\\envreview.py lit pdfs --dir "D:\\env-journal-pdfs"
   It should report about {n} linked PDFs. Search results then show each paper's PDF.

pdf_manifest.csv lists every file with its DOI, journal, year, size and zip volume.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--index", default=str(Path.home() / ".envreview" / "env-journal-index-v1"))
    ap.add_argument("--max-gb", type=float, default=10.0)
    ap.add_argument("--dry-run", action="store_true", help="print the volumes only")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cap = a.max_gb * 1e9

    c = pd.read_parquet(Path(a.index) / "corpus.parquet", columns=["DOI", "journal_std", "year"])
    meta = {d.lower().split("/", 1)[1]: (d, j, int(y)) for d, j, y in zip(c.DOI, c.journal_std, c.year)}
    best = {}
    for root, _, names in os.walk(src):
        for name in names:
            stem = name[:-4].lower() if name.lower().endswith(".pdf") else None
            if stem in meta:
                p = Path(root) / name
                size = p.stat().st_size
                if size >= 1000 and (stem not in best or size > best[stem][1]):
                    best[stem] = (p, size)
    rows = sorted(((list(CODES).index(meta[s][1]), meta[s][2], meta[s][0], s, p, size)
                   for s, (p, size) in best.items()))
    print(f"{len(rows)} PDFs, {sum(r[5] for r in rows) / 1e9:.1f} GB", flush=True)

    # cut volumes: per journal, consecutive years, about `cap` bytes each
    volumes, cur = [], []
    for r in rows:
        if cur and (r[0] != cur[0][0] or sum(x[5] for x in cur) + r[5] > cap):
            volumes.append(cur)
            cur = []
        cur.append(r)
    if cur:
        volumes.append(cur)
    # EST1_2015-2017, EST2_2017-2019, ... (numbered when a journal needs several volumes)
    per_journal = {}
    for v in volumes:
        per_journal[v[0][0]] = per_journal.get(v[0][0], 0) + 1
    names, k = [], {}
    for v in volumes:
        j = v[0][0]
        k[j] = k.get(j, 0) + 1
        y0, y1 = v[0][1], v[-1][1]
        num = str(k[j]) if per_journal[j] > 1 else ""
        names.append(f"{CODES[list(CODES)[j]]}{num}_{y0}" + ("" if y0 == y1 else f"-{y1}"))

    if a.dry_run:
        for name, v in zip(names, volumes):
            print(f"  {name}.zip  {len(v):5d} PDFs  {sum(x[5] for x in v) / 1e9:5.1f} GB")
        return

    manifest = []
    for name, v in zip(names, volumes):
        zpath, done = out / f"{name}.zip", out / f"{name}.zip.done"
        for _, year, doi, stem, p, size in v:
            code = CODES[list(CODES)[v[0][0]]]
            manifest.append({"doi": doi, "journal": list(CODES)[v[0][0]], "year": year,
                             "file": f"{code}/{year}/{stem}.pdf", "bytes": size, "volume": f"{name}.zip"})
        if done.exists():
            print(f"{name}.zip already done", flush=True)
            continue
        with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for k, (_, year, doi, stem, p, size) in enumerate(v, 1):
                z.write(p, manifest[-len(v) + k - 1]["file"])
        done.write_text(str(len(v)), encoding="utf-8")
        print(f"{name}.zip: {len(v)} PDFs, {sum(x[5] for x in v) / 1e9:.1f} GB", flush=True)

    with open(out / "pdf_manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0]))
        w.writeheader()
        w.writerows(manifest)
    (out / "README.txt").write_text(README.format(n=len(manifest), v=len(volumes),
                                                  gb=sum(m["bytes"] for m in manifest) / 1e9),
                                    encoding="utf-8")
    print(f"done: {len(volumes)} volumes in {out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
