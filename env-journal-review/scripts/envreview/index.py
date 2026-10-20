"""Local access to the index pack: search, full text by DOI, and reviewer-role selection.

Ported from the original pipeline's retrieval and reviewer-role tools. Three retrieval paths
are fused by reciprocal-rank fusion:
  emb     one ranking per natural-language query (bge-large-en-v1.5, query prefix applied)
  bm25    lexical ranking over title + abstract
  phrase  exact substring match over title + abstract, newest first; a phrase matching more
          papers than one path keeps (per_path) is skipped as too common
Filters (publication years, journals, excluded DOIs) are applied before ranking. `similar`
ranks papers by cosine similarity of their stored title+abstract embeddings to one paper's.
"""
from __future__ import annotations

import json
import re
import sqlite3
import zlib
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

RRF_K = 60
TOKEN = re.compile(r"[a-z0-9][a-z0-9\-\+/\.]*")
STOP = set("""a an the and or of in on for to with by from as at is are was were be been being
this that these those we our it its their they he she which who whom what when where how why
not no non can could may might will would should must have has had do does did than then thus
here there about into over under between among during after before within without via using use
used using study studies paper article results result show shows shown suggest suggests
however moreover furthermore also both each other others such more most less least high low
significant significantly different differences increase decrease""".split())


def tokenize(s: str) -> list[str]:
    return [t for t in TOKEN.findall(s.lower()) if t not in STOP and len(t) > 1]


class LocalIndex:
    def __init__(self, root: Path):
        import pandas as pd
        import scipy.sparse as sp

        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.d = pd.read_parquet(self.root / "corpus.parquet")
        # fp16 on disk, fp32 in memory (~166 MB): converting per query would dominate latency
        self.emb = np.load(self.root / "emb_bge_large.npy").astype(np.float32)
        self.bm = sp.load_npz(self.root / "bm25.npz")
        self.vocab = json.loads((self.root / "bm25_vocab.json").read_text(encoding="utf-8"))
        self.year = pd.to_numeric(self.d.year, errors="coerce").fillna(9999).to_numpy()
        self.doi = self.d.DOI.str.lower().to_numpy()
        self.low = (self.d.title.fillna("") + " " + self.d.abstract.fillna("")).str.lower().to_numpy()
        self._tok = self._model = None
        self.skipped_phrases = []

    # ---- encoder ---------------------------------------------------------------
    def encode(self, texts: list[str], query: bool) -> np.ndarray:
        import torch
        from transformers import AutoModel, AutoTokenizer

        cfg = self.manifest["embedding"]
        if self._tok is None:
            self._tok = AutoTokenizer.from_pretrained(cfg["name"], revision=cfg["revision"])
            self._model = AutoModel.from_pretrained(cfg["name"], revision=cfg["revision"]).eval()
            if torch.cuda.is_available():
                self._model = self._model.cuda()
        prefix = cfg["query_prefix"] if query else ""
        b = self._tok([prefix + t for t in texts], padding=True, truncation=True,
                      max_length=cfg["max_length"], return_tensors="pt")
        b = {k: v.to(self._model.device) for k, v in b.items()}
        with torch.no_grad():
            h = self._model(**b).last_hidden_state[:, 0]
            h = torch.nn.functional.normalize(h, p=2, dim=1)
        return h.cpu().numpy().astype(np.float32)

    # ---- retrieval -------------------------------------------------------------
    def _mask(self, before=None, exclude=(), after=None, journals=()):
        mask = np.ones(len(self.d), bool)
        if before:
            mask &= self.year <= int(before)
        if after:
            mask &= self.year >= int(after)
        if journals:
            mask &= self.d.journal_std.isin(list(journals)).to_numpy()
        ex = {x.lower().strip() for x in exclude}
        if ex:
            mask &= ~np.isin(self.doi, list(ex))
        return mask

    @staticmethod
    def _top(scores, mask, n):
        s = np.where(mask, scores, -np.inf)
        n = min(n, int(mask.sum()))
        if n <= 0:
            return np.array([], dtype=int)
        idx = np.argpartition(-s, n - 1)[:n]
        idx = idx[np.argsort(-s[idx])]
        return idx[np.isfinite(s[idx])]

    def search(self, queries, phrases=(), before=None, exclude=(), topk=30, per_path=300,
               after=None, journals=()):
        mask = self._mask(before, exclude, after, journals)
        contrib, scores = defaultdict(list), defaultdict(float)

        def add(idx, label):
            for r, i in enumerate(idx):
                contrib[i].append((label, r + 1))
                scores[i] += 1.0 / (RRF_K + r + 1)

        queries = list(queries or [])
        self.skipped_phrases = []            # (phrase, hits) too common to rank; read by the CLI
        if queries:
            qv = self.encode(queries, query=True)
            for qi in range(len(queries)):
                add(self._top(self.emb @ qv[qi], mask, per_path), f"emb:q{qi + 1}")
            for qi, q in enumerate(queries):
                cols = [self.vocab[t] for t in set(tokenize(q)) if t in self.vocab]
                if cols:
                    s = np.asarray(self.bm[:, cols].sum(axis=1)).ravel()
                    idx = self._top(s, mask & (s > 0), per_path)
                    add(idx, f"bm25:q{qi + 1}")
        for p in phrases or []:
            p = p.lower().strip()
            if not p:
                continue
            hit = np.fromiter((p in t for t in self.low), bool, len(self.low)) & mask
            idx = np.where(hit)[0]
            if len(idx) > per_path:
                # "wastewater treatment" matches ~3,000 papers: not an exact-term signal, and
                # which of them survive the cut would depend only on row order
                self.skipped_phrases.append((p, len(idx)))
                continue
            order = np.lexsort((self.doi[idx], -self.year[idx]))    # newest first, then DOI
            add(idx[order], f'phrase:"{p}"')

        order = sorted(scores, key=lambda i: -scores[i])[:topk]
        return [self.record(i, why_retrieved="; ".join(
                    f"{a}#{b}" for a, b in sorted(contrib[i], key=lambda x: x[1])),
                    rrf=round(scores[i], 5)) for i in order]

    def record(self, i, **extra):
        r = self.d.iloc[i]
        # field names follow the editor's evidence packs (category, facets, why_retrieved)
        out = {"doi": r.DOI, "year": int(r.year) if str(r.year).isdigit() else r.year,
               "journal": r.journal_std, "title": r.title,
               "category": f"{r.category} {r.category_label}",
               "facets": f"{r.research_purpose_label or ''} | {r.research_method_label or ''} | "
                         f"{r.environmental_system_label or ''}",
               "abstract": r.abstract or "", "has_fulltext": bool(r.has_fulltext)}
        out.update(extra)
        return out

    def row(self, doi):
        """Row number of a DOI in the corpus, or None."""
        i = np.where(self.doi == doi.lower().strip())[0]
        return int(i[0]) if len(i) else None

    def similar(self, doi, topk=20, before=None, after=None, journals=()):
        """Papers whose title+abstract embedding is closest to this paper's (cosine; the
        vectors are L2-normalised, so a dot product). No model is loaded."""
        i = self.row(doi)
        if i is None:
            return None
        mask = self._mask(before, exclude=[doi], after=after, journals=journals)
        sims = self.emb @ self.emb[i]
        return [self.record(int(j), similarity=round(float(sims[j]), 4))
                for j in self._top(sims, mask, topk)]

    # ---- full text -------------------------------------------------------------
    def fulltext(self, dois, max_chars=60000):
        db = sqlite3.connect(f"file:{self.root / 'fulltext.sqlite'}?mode=ro", uri=True)
        out = []
        try:
            for doi in dois:
                row = db.execute("SELECT chars, text FROM docs WHERE doi = ?",
                                 (doi.lower().strip(),)).fetchone()
                if not row:
                    out.append({"doi": doi, "found": False})
                    continue
                text = zlib.decompress(row[1]).decode("utf-8")
                i = np.where(self.doi == doi.lower().strip())[0]
                meta = self.record(int(i[0])) if len(i) else {"doi": doi}
                meta.pop("abstract", None)
                out.append({**meta, "found": True, "chars": row[0], "truncated": row[0] > max_chars,
                            "text": text[:max_chars]})
        finally:
            db.close()
        return out

    # ---- reviewer roles --------------------------------------------------------
    def roles(self, title, abstract, exclude=(), n_roles=3, n_neighbours=30):
        """The n closest of the 60 subject topics (embedding vs topic centroids) and the
        manuscript's main methods, voted by its nearest published neighbours."""
        z = np.load(self.root / "topic_centroids.npz", allow_pickle=True)
        codes, labels, cvecs = [str(c) for c in z["codes"]], [str(x) for x in z["labels"]], z["vecs"]
        v = self.encode([f"{title}. {abstract}"], query=False)[0]   # passage vs passage
        sims = cvecs @ v
        order = np.argsort(-sims)
        topics = [{"code": codes[i], "label": labels[i], "sim": round(float(sims[i]), 4)}
                  for i in order[:5]]
        s = np.where(self._mask(exclude=exclude), self.emb @ v, -np.inf)
        nn = np.argsort(-s)[:n_neighbours]
        meth, cats = defaultdict(float), Counter()
        for i in nn:
            r = self.d.iloc[i]
            cats[f"{r.category} {r.category_label}"] += 1
            for t in str(r.research_method_label or "").split(";"):
                if t.strip():
                    meth[t.strip().replace(", domain unspecified", "")] += float(s[i])
        return {"roles": topics[:n_roles], "topics": topics,
                "methods": [t for t, _ in sorted(meth.items(), key=lambda x: -x[1])[:4]],
                "neighbour_topics": cats.most_common(6)}
