#!/usr/bin/env python3
"""Build OpenStax Introductory Statistics 2e .fapack for Field Atlas."""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from tools.packs.build_practical_skills_pack import add_attribution
from tools.packs.build_prealgebra_pack import line_chunks
from tools.packs.stream_pack import build_pack_streaming


def verify_pack_crossplatform(pack: Path) -> dict:
    with zipfile.ZipFile(pack) as archive:
        names = archive.namelist()
        assert "manifest.json" in names and "content.sqlite" in names, f"{pack}: missing entries {names}"
        assert "ATTRIBUTION.txt" in names, f"{pack}: missing ATTRIBUTION.txt"
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["type"] == "KNOWLEDGE" and manifest["schemaVersion"] == 1, pack
        for artifact in manifest["artifacts"]:
            blob = archive.read(artifact["path"])
            assert len(blob) == artifact["bytes"], f"{pack}:{artifact['path']} byte count"
            assert hashlib.sha256(blob).hexdigest() == artifact["sha256"], f"{pack}:{artifact['path']} sha256"
        sqlite_bytes = archive.read("content.sqlite")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / f"verify-{pack.name}.sqlite"
        db_path.write_bytes(sqlite_bytes)
        db = sqlite3.connect(db_path)
        try:
            assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            chunks = db.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
            assert chunks > 0
            sample_hits = {}
            for q in ["central limit theorem", "hypothesis testing p-value", "chi-square distribution", "linear regression correlation"]:
                terms = " ".join(f'"{w}"' for w in q.split())
                rows = db.execute(
                    "SELECT title, bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 2",
                    (terms,),
                ).fetchall()
                sample_hits[q] = [r[0] for r in rows]
        finally:
            db.close()
    return {
        "pack": str(pack), "bytes": pack.stat().st_size, "chunks": chunks,
        "title": manifest["title"], "license": manifest["license"], "sample_hits": sample_hits,
    }

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CORPUS = HERE / "intro_stats" / "corpus.jsonl"
ATTRIBUTION = HERE / "intro_stats" / "ATTRIBUTION.txt"
PACK_ID = "openstax-introductory-statistics"
TITLE = "Mathematics: Introductory statistics"
LICENSE_ID = "CC-BY-4.0"
SOURCE_URLS = ["https://openstax.org/details/books/introductory-statistics-2e"]


def build(corpus: Path, out: Path, version: str) -> dict:
    found = hashlib.sha256(corpus.read_bytes()).hexdigest()
    artifacts = build_pack_streaming(
        corpus, out, PACK_ID, version, TITLE, LICENSE_ID, SOURCE_URLS,
        fts_tokenizer="porter unicode61", chunker=line_chunks,
    )
    add_attribution(artifacts, ATTRIBUTION.read_text(encoding="utf-8"))
    shutil.copyfile(ATTRIBUTION, artifacts.pack.parent / "ATTRIBUTION.txt")
    summary = verify_pack_crossplatform(artifacts.pack)
    data = artifacts.pack.read_bytes()
    manifest = json.loads(artifacts.manifest.read_bytes())
    return {
        "pack": str(artifacts.pack),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "installedBytes": sum(a["bytes"] for a in manifest["artifacts"]),
        "corpusSha256": found,
        "verified": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "intro-stats-pack")
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args()
    print(json.dumps(build(args.corpus, args.out, args.version), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
