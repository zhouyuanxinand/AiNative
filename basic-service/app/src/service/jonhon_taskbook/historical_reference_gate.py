"""Detect verified, review-only historical artifacts left in the output body.

Matching a caption or a figure number cannot prove historical pollution. Match
whole table text and merge structure, or the bytes of referenced image parts.
Evidence also used by formal requirements is reported without blocking.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from lxml import etree

from .source_scope import review_reference_source_details


def _text(element):
    return "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()


def _compact(text):
    return re.sub(r"\s+", "", text)


def _table_identity(table):
    """Ignore controlled font/width edits while preserving row/cell boundaries."""
    rows = []
    for row in table.findall(qn("w:tr")):
        cells = []
        for cell in row.findall(qn("w:tc")):
            merges = []
            for name in ("gridSpan", "vMerge", "hMerge"):
                marker = cell.find(f'{qn("w:tcPr")}/{qn("w:" + name)}')
                merges.append(None if marker is None else marker.get(qn("w:val"), "continue"))
            cells.append((_compact(_text(cell)), merges))
        rows.append(cells)
    if not any(cell[0] for row in rows for cell in row):
        return None
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def _image_hashes(document, element):
    hashes = set()
    for node in element.iter():
        for attribute in (qn("r:embed"), qn("r:id")):
            relation = document.part.rels.get(node.get(attribute))
            if (relation is not None and not relation.is_external
                    and relation.reltype.endswith("/image")):
                hashes.add(hashlib.sha256(relation.target_part.blob).hexdigest())
    return hashes


def audit_historical_reference_content(output_path, classification):
    details = review_reference_source_details(classification)
    report = {"policy": "source_verified_exclusive_historical_artifacts",
              "checked_source_ids": [], "unverifiable_sources": [],
              "warnings": [], "violations": []}
    if not details:
        return report
    documents, historical, formal_tables, formal_images = {}, [], set(), set()
    for block in (classification or {}).get("source_blocks", []):
        source_id = str(block.get("id", ""))
        path, index = block.get("source_path"), block.get("body_index")
        try:
            if not path or type(index) is not int or index < 0:
                raise ValueError("source coordinates unavailable")
            path = str(Path(path).resolve())
            if path not in documents:
                documents[path] = Document(path)
            document = documents[path]
            element = document.element.body[index]
            if element.tag != qn("w:tbl" if block.get("type") == "table" else "w:p"):
                raise ValueError("source element type changed")
            if block.get("is_fragment") or block.get("parent_source_id"):
                # A parent containing formal fragments must never become an
                # exclusive historical artifact based on partial text.
                formal_images.update(_image_hashes(document, element))
                continue
            actual_text = _text(element)
            expected_hash = block.get("content_hash")
            actual_hash = hashlib.sha256(
                _compact(actual_text).encode("utf-8") if actual_text else etree.tostring(element)
            ).hexdigest()
            if not expected_hash or expected_hash != actual_hash:
                raise ValueError("source content hash changed or unavailable")
            tables = {_table_identity(table) for table in element.iter(qn("w:tbl"))} - {None}
            images = _image_hashes(document, element)
            if source_id in details:
                historical.append((source_id, tables, images))
                report["checked_source_ids"].append(source_id)
            else:
                formal_tables.update(tables)
                formal_images.update(images)
        except (OSError, ValueError, IndexError, KeyError, PackageNotFoundError):
            if source_id in details:
                report["unverifiable_sources"].append(source_id)

    output = Document(output_path)
    output_tables, output_images = defaultdict(list), defaultdict(list)
    for body_index, element in enumerate(output.element.body):
        for table_index, table in enumerate(element.iter(qn("w:tbl"))):
            fingerprint = _table_identity(table)
            if fingerprint:
                output_tables[fingerprint].append({"output_body_index": body_index, "output_table_index": table_index})
        for fingerprint in _image_hashes(output, element):
            output_images[fingerprint].append({"output_body_index": body_index})
    for source_id, tables, images in historical:
        detail = details[source_id]
        for kind, fingerprints, formal, matches in (
            ("table", tables, formal_tables, output_tables),
            ("image", images, formal_images, output_images),
        ):
            for fingerprint in sorted(fingerprints):
                for coordinates in matches.get(fingerprint, []):
                    finding = {
                        "source_id": source_id, "source_path": detail["source_path"],
                        "source_body_index": detail["body_index"],
                        "artifact_type": kind, "artifact_sha256": fingerprint,
                        **coordinates,
                    }
                    if fingerprint in formal:
                        report["warnings"].append({"code": "SHARED_HISTORICAL_AND_FORMAL_ARTIFACT", **finding})
                    else:
                        report["violations"].append({"code": "HISTORICAL_REFERENCE_IN_BODY", **finding})
    return report
