---
pretty_name: Environmental journal index (env-journal-review)
language:
- en
license: other
size_categories:
- 10K<n<100K
task_categories:
- text-retrieval
tags:
- environmental-science
- peer-review
- retrieval
- embeddings
configs:
- config_name: corpus
  data_files: corpus.parquet
---

# Environmental journal index

The literature index used by env-journal-review, an agent skill for
AI pre-submission review of environmental science and engineering manuscripts. The skill's
editor and reviewers search this index to judge how new a manuscript is and read the closest
papers in full.

## Contents

40,453 research papers published 2015–2026 in Environmental Science & Technology, Water
Research, Nature Water, Nature Sustainability, Nature Climate Change, Nature Geoscience and One
Earth; 40,111 have an abstract and a parsed full text.

| File | What it holds |
|---|---|
| `corpus.parquet` | DOI, title, abstract, journal, year, one of 60 environmental topic labels, research purpose / method / system facets |
| `emb_bge_large.npy` | `BAAI/bge-large-en-v1.5` embeddings of title + abstract (float16, CLS pooling, L2-normalised), row-aligned with the corpus |
| `bm25.npz`, `bm25_vocab.json` | BM25 index of title + abstract (k1 = 1.5, b = 0.75) |
| `topic_centroids.npz` | centroid embedding of each of the 60 topics, used to pick reviewer roles |
| `fulltext.sqlite` | parsed full texts, table `docs(doi, chars, text)` with zlib-compressed text |
| `manifest.json` | sizes, SHA-256 checksums, embedding and BM25 settings |

## Use

With the skill installed:

```
python env-journal-review/scripts/envreview.py index-download
```

downloads tag `v1` to `~/.envreview/env-journal-index-v1/` and checks every file against the
manifest. The corpus table alone can be read with any Parquet reader.

## Terms

Titles, abstracts and full texts remain the copyright of their publishers. The index is
provided for use with env-journal-review; topic labels, facets, embeddings and the BM25 index
were produced for that project.
