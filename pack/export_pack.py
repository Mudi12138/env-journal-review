"""Build the distributable index pack from the Katana corpus (maintainer tool).

Runs on Katana (see export_pack.pbs). Reads the retrieval index in $ENVTOP_ROOT/retrieval and
the parsed full texts in $ENVTOP_ROOT/fulltext (default ENVTOP_ROOT: /srv/scratch/$USER/envtop),
and writes one self-contained directory plus a tar of it:

  env-journal-index-<version>/
    manifest.json        version, counts, embedding model, tokenizer, sha256 of every file
    corpus.parquet       one row per paper: DOI, title, abstract, journal, year, topic labels,
                         facet labels, has_fulltext
    emb_bge_large.npy    float16, rows aligned with corpus.parquet (bge-large-en-v1.5, CLS,
                         L2-normalised, passages embedded without the query prefix)
    bm25.npz             BM25 weights (scipy CSR), rows aligned with corpus.parquet
    bm25_vocab.json      term -> column
    topic_centroids.npz  mean embedding per subject topic (A1..J3), for picking reviewers
    fulltext.sqlite      docs(doi PRIMARY KEY, chars, text BLOB zlib-compressed UTF-8)

The skill reads this directory locally; nothing at run time depends on Katana.
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.path.expandvars(os.environ.get("ENVTOP_ROOT", "/srv/scratch/$USER/envtop")))
RET = ROOT / "retrieval"
KEEP = ["DOI", "title", "abstract", "journal_std", "journal", "year", "doctype", "category",
        "category_label", "group", "group_name", "research_purpose_label",
        "research_method_label", "environmental_system_label", "research_object",
        "has_abstract", "evidence_strength"]
MODEL = {"name": "BAAI/bge-large-en-v1.5", "revision": "d4aa6901d3a41ba39fb536a557fa166f842b0e09",
         "pooling": "cls", "normalize": True, "max_length": 512,
         "query_prefix": "Represent this sentence for searching relevant passages: "}


def sha256(path, chunk=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v1")
    ap.add_argument("--out", default=str(ROOT / "pack"))
    a = ap.parse_args()
    out = Path(a.out) / f"env-journal-index-{a.version}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    d = pd.read_parquet(RET / "corpus.parquet").reset_index(drop=True)
    paths = d.fulltext_file.fillna("").astype(str)
    has_ft = np.array([bool(p) and (ROOT / p).exists() for p in paths])
    corpus = d[KEEP].copy()
    corpus["has_fulltext"] = has_ft
    corpus.to_parquet(out / "corpus.parquet", index=False)
    print("corpus", corpus.shape, "with full text", int(has_ft.sum()), flush=True)

    emb = np.load(RET / "emb_bge_large.npy")
    assert emb.shape[0] == len(d), (emb.shape, len(d))
    np.save(out / "emb_bge_large.npy", emb.astype(np.float16))
    shutil.copy2(RET / "bm25.npz", out / "bm25.npz")
    shutil.copy2(RET / "bm25_vocab.json", out / "bm25_vocab.json")

    # topic centroids, exactly as reviewer/katana/pick_roles.py computes them
    e32 = emb.astype(np.float32)
    has_text = d.abstract.fillna("").str.len().to_numpy() > 0
    cat = d.category.astype(str).to_numpy()
    codes, labels, vecs = [], [], []
    for code in sorted(set(cat)):
        if code.startswith("Z") or code in ("nan", "None", ""):
            continue
        pos = np.where((cat == code) & has_text)[0]
        v = e32[pos].mean(axis=0)
        codes.append(code)
        labels.append(str(d.category_label.iloc[pos[0]]))
        vecs.append(v / np.linalg.norm(v))
    np.savez(out / "topic_centroids.npz", codes=np.array(codes), labels=np.array(labels),
             vecs=np.stack(vecs).astype(np.float32))
    print("centroids", len(codes), flush=True)

    db = sqlite3.connect(out / "fulltext.sqlite")
    db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"
                     "CREATE TABLE docs(doi TEXT PRIMARY KEY, chars INTEGER, text BLOB);")
    batch, n = [], 0
    for doi, p, ok in zip(d.DOI, paths, has_ft):
        if not ok:
            continue
        text = (ROOT / p).read_text(encoding="utf-8", errors="ignore")
        batch.append((doi.lower(), len(text), zlib.compress(text.encode("utf-8"), 6)))
        if len(batch) == 1000:
            db.executemany("INSERT OR REPLACE INTO docs VALUES (?,?,?)", batch)
            n += len(batch)
            batch = []
            print("fulltext", n, flush=True)
    db.executemany("INSERT OR REPLACE INTO docs VALUES (?,?,?)", batch)
    n += len(batch)
    db.commit()
    db.close()
    print("fulltext total", n, flush=True)

    files = {f.name: {"bytes": f.stat().st_size, "sha256": sha256(f)}
             for f in sorted(out.iterdir())}
    manifest = {
        "name": "env-journal-index", "version": a.version,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "journals": sorted(corpus.journal_std.dropna().unique().tolist()),
        "years": [int(pd.to_numeric(corpus.year, errors="coerce").min()),
                  int(pd.to_numeric(corpus.year, errors="coerce").max())],
        "papers": int(len(corpus)), "with_abstract": int((corpus.abstract.fillna("") != "").sum()),
        "with_fulltext": int(n), "topics": len(codes),
        "embedding": MODEL,
        "bm25": {"k1": 1.5, "b": 0.75, "min_df": 2,
                 "token_regex": r"[a-z0-9][a-z0-9\-\+/\.]*", "lowercase": True,
                 "min_token_len": 2},
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    tar_path = out.parent / f"{out.name}.tar"
    with tarfile.open(tar_path, "w") as t:
        t.add(out, arcname=out.name)
    (out.parent / f"{out.name}.tar.sha256").write_text(f"{sha256(tar_path)}  {tar_path.name}\n")
    print("done", tar_path, tar_path.stat().st_size, flush=True)


if __name__ == "__main__":
    main()
