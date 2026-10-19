"""Maintainer tool: upload an unpacked index pack to Hugging Face and tag it.

  python pack/upload_hf.py --pack ~/.envreview/env-journal-index-v1            # private repo
  python pack/upload_hf.py --pack ... --public                                 # make it public

Uses the token stored by `huggingface-cli login` (or HF_TOKEN). The tag is the manifest's
version, which is what `envreview.py index-download` asks for.
"""
import argparse
import json
from pathlib import Path

from huggingface_hub import HfApi

ap = argparse.ArgumentParser()
ap.add_argument("--pack", required=True, help="folder holding manifest.json and the pack files")
ap.add_argument("--repo", default="Mudi12137/env-journal-index")
ap.add_argument("--public", action="store_true", help="make the dataset public (default private)")
a = ap.parse_args()

pack = Path(a.pack).expanduser()
manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
files = ["manifest.json", *manifest["files"]]
missing = [f for f in files if not (pack / f).exists()]
if missing:
    raise SystemExit(f"missing in {pack}: {missing}")

api = HfApi()
api.create_repo(a.repo, repo_type="dataset", private=not a.public, exist_ok=True)
api.update_repo_settings(a.repo, repo_type="dataset", private=not a.public)
api.upload_file(path_or_fileobj=str(Path(__file__).with_name("dataset_card.md")),
                path_in_repo="README.md", repo_id=a.repo, repo_type="dataset",
                commit_message="Dataset card")
commit = api.upload_folder(folder_path=str(pack), repo_id=a.repo, repo_type="dataset",
                           allow_patterns=files,
                           commit_message=f"{manifest['name']} {manifest['version']}")
tag = manifest["version"]
if tag in {t.name for t in api.list_repo_refs(a.repo, repo_type="dataset").tags}:
    api.delete_tag(a.repo, repo_type="dataset", tag=tag)
api.create_tag(a.repo, repo_type="dataset", tag=tag, revision=commit.oid)
print(json.dumps({"repo": a.repo, "private": not a.public, "tag": tag, "commit": commit.oid,
                  "files": files}, indent=1))
