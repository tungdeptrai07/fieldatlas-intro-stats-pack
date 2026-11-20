#!/usr/bin/env python3
"""Extract OpenStax *Introductory Statistics 2e* corpus (CC BY 4.0 commit)."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from extract_openstax_prealgebra import (  # noqa: E402
    CNXML,
    COLLXML,
    MDML,
    _flat,
    _local,
    kebab,
    module_to_text,
)

BOOK_URL = "https://openstax.org/books/introductory-statistics-2e"
LICENSE_ID = "CC-BY-4.0"
EXCLUDED_CLASSES = {"preface", "introduction"}
INCLUDED_APPENDICES = {
    "m47891": "Appendix — Mathematical Phrases, Symbols, and Formulas",
    "m47875": "Appendix — Tables",
}


def parse_book(osbooks: Path):
    coll = ET.parse(osbooks / "collections" / "introductory-statistics-2e.collection.xml")
    root = coll.getroot()

    def module_info(mid: str):
        path = osbooks / "modules" / mid / "index.cnxml"
        doc = ET.parse(path).getroot()
        cls = doc.get("class") or ""
        title_el = doc.find(f"{{{CNXML}}}title")
        title = _flat(title_el) if title_el is not None else mid
        content = doc.find(f"{{{CNXML}}}content")
        return cls, title, content, doc

    chapters = []
    top_modules = []
    content_el = root.find(f"{{{COLLXML}}}content")
    for node in content_el:
        if _local(node) == "module":
            mid = node.get("document")
            cls, title, _, _ = module_info(mid)
            top_modules.append((mid, cls, title))
        elif _local(node) == "subcollection":
            title_el = node.find(f"{{{MDML}}}title")
            ch_title = _flat(title_el)
            mods = []
            inner = node.find(f"{{{COLLXML}}}content")
            for m in inner.iter(f"{{{COLLXML}}}module"):
                mid = m.get("document")
                cls, title, _, _ = module_info(mid)
                mods.append((mid, cls, title))
            chapters.append((ch_title, mods))
    return chapters, top_modules, module_info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--osbooks", type=Path, required=True,
                    help="checkout of openstax/osbooks-introductory-statistics-bundle")
    ap.add_argument("--out", type=Path, default=HERE / "intro_stats" / "corpus.jsonl")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    try:
        commit = subprocess.run(
            ["git", "-C", str(args.osbooks), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        commit = "unknown"
    print(f"osbooks commit: {commit}", file=sys.stderr)

    chapters, top_modules, module_info = parse_book(args.osbooks)
    all_titles = {mid: title for mid, _, title in top_modules}
    for _, mods in chapters:
        for mid, _, title in mods:
            all_titles[mid] = title

    def make_resolver(doc_root):
        by_id = {el.get("id"): el for el in doc_root.iter() if el.get("id")}
        labels = {"figure": "Figure", "table": "Table", "example": "Example",
                  "exercise": "Exercise"}

        def resolve(link_el):
            target_doc = link_el.get("document")
            if target_doc and target_doc in all_titles:
                return all_titles[target_doc]
            target = by_id.get(link_el.get("target-id") or "")
            if target is None:
                return ""
            tag = _local(target)
            if tag == "section":
                t = target.find(f"{{{CNXML}}}title")
                return _flat(t) if t is not None else ""
            return labels.get(tag, "")

        return resolve

    rows = []
    for ch_no, (ch_title, mods) in enumerate(chapters, start=1):
        sec_no = 0
        for mid, cls, title in mods:
            if cls in EXCLUDED_CLASSES:
                continue
            sec_no += 1
            _, _, content, doc_root = module_info(mid)
            text = module_to_text(content, resolve_link=make_resolver(doc_root))
            glossary = doc_root.find(f"{{{CNXML}}}glossary")
            if glossary is not None:
                terms = module_to_text(glossary, resolve_link=make_resolver(doc_root))
                if terms:
                    text += "\n\nGlossary\n" + terms
            slug = f"{ch_no}-{sec_no}-{kebab(title)}"
            rows.append({
                "document_id": f"openstax-intro-stats-{mid}",
                "title": f"{ch_title} \u2014 {title}",
                "source": f"{BOOK_URL}/pages/{slug}",
                "license": LICENSE_ID,
                "text": text,
            })

    for mid, cls, title in top_modules:
        if mid not in INCLUDED_APPENDICES:
            continue
        _, _, content, doc_root = module_info(mid)
        text = module_to_text(content, resolve_link=make_resolver(doc_root))
        rows.append({
            "document_id": f"openstax-intro-stats-{mid}",
            "title": INCLUDED_APPENDICES[mid],
            "source": f"{BOOK_URL}/pages/{kebab(title)}",
            "license": LICENSE_ID,
            "text": text,
        })

    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    args.out.write_text(payload, encoding="utf-8")
    print(json.dumps({
        "commit": commit,
        "rows": len(rows),
        "bytes": len(payload.encode("utf-8")),
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }, indent=2))


if __name__ == "__main__":
    main()
