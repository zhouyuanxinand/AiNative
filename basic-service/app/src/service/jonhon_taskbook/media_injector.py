"""DOCX 图片媒体补注入；只处理 OOXML 关系，不参与章节定位。"""
from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from pathlib import PurePosixPath

from lxml import etree


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
CONTENT_TYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
MIME_BY_EXTENSION = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "emf": "image/x-emf",
    "wmf": "image/x-wmf",
    "svg": "image/svg+xml",
}


def _media_path(target: str) -> str:
    normalized = str(PurePosixPath("word") / target) if not target.startswith("word/") else target
    return str(PurePosixPath(normalized))


def inject_media(source_docx: str, target_docx: str) -> int:
    """补齐目标 DOCX 已引用但尚未注册的源图片关系和媒体文件。"""
    with zipfile.ZipFile(source_docx, "r") as source_zip:
        source_media = {
            name: source_zip.read(name)
            for name in source_zip.namelist()
            if name.startswith("word/media/")
        }
        source_relationships: dict[str, str] = {}
        relationship_name = "word/_rels/document.xml.rels"
        if relationship_name in source_zip.namelist():
            source_root = etree.fromstring(source_zip.read(relationship_name))
            for relationship in source_root:
                if "image" not in relationship.get("Type", ""):
                    continue
                relationship_id = relationship.get("Id", "")
                target = relationship.get("Target", "")
                if relationship_id and target:
                    source_relationships[relationship_id] = _media_path(target)

    if not source_media:
        return 0

    with zipfile.ZipFile(target_docx, "r") as target_zip:
        names = set(target_zip.namelist())
        document_xml = target_zip.read("word/document.xml")
        relationships_xml = (
            target_zip.read("word/_rels/document.xml.rels")
            if "word/_rels/document.xml.rels" in names
            else b""
        )

    relationships_root = (
        etree.fromstring(relationships_xml)
        if relationships_xml
        else etree.Element(f"{{{REL_NS}}}Relationships")
    )
    relationship_by_id = {
        relationship.get("Id", ""): relationship
        for relationship in relationships_root
        if relationship.get("Id")
    }
    used_ids = set(re.findall(rb'r:embed="(rId\d+)"', document_xml))
    used_ids |= set(re.findall(rb'r:id="(rId\d+)"', document_xml))
    used_ids = {value.decode("ascii") for value in used_ids}

    additions: dict[str, bytes] = {}
    changed_relationships = False
    for relationship_id in sorted(used_ids):
        existing = relationship_by_id.get(relationship_id)
        if existing is not None:
            existing_target = _media_path(existing.get("Target", ""))
            if existing_target in names:
                continue
        source_path = source_relationships.get(relationship_id)
        if not source_path or source_path not in source_media:
            continue

        destination = source_path
        if destination in names:
            source_hash = hashlib.sha256(source_media[source_path]).hexdigest()
            with zipfile.ZipFile(target_docx, "r") as target_zip:
                target_hash = hashlib.sha256(target_zip.read(destination)).hexdigest()
            if source_hash != target_hash:
                stem = str(PurePosixPath(destination).with_suffix(""))
                suffix = PurePosixPath(destination).suffix
                serial = 1
                while f"{stem}_source_{serial}{suffix}" in (names | set(additions)):
                    serial += 1
                destination = f"{stem}_source_{serial}{suffix}"

        additions[destination] = source_media[source_path]
        target_value = destination.replace("word/", "", 1)
        if existing is None:
            existing = etree.SubElement(
                relationships_root, f"{{{REL_NS}}}Relationship"
            )
            existing.set("Id", relationship_id)
            relationship_by_id[relationship_id] = existing
        existing.set("Type", IMAGE_REL_TYPE)
        existing.set("Target", target_value)
        changed_relationships = True

    # 未被正文直接引用的媒体也按内容去重保留，便于后续图片关系修复审计。
    existing_hashes: set[str] = set()
    with zipfile.ZipFile(target_docx, "r") as target_zip:
        for name in names:
            if name.startswith("word/media/"):
                existing_hashes.add(hashlib.sha256(target_zip.read(name)).hexdigest())
    for source_path, data in source_media.items():
        digest = hashlib.sha256(data).hexdigest()
        if digest in existing_hashes or digest in {
            hashlib.sha256(value).hexdigest() for value in additions.values()
        }:
            continue
        destination = source_path
        serial = 1
        while destination in names or destination in additions:
            path = PurePosixPath(source_path)
            destination = str(path.with_name(f"{path.stem}_source_{serial}{path.suffix}"))
            serial += 1
        additions[destination] = data

    if not additions and not changed_relationships:
        return 0

    new_relationships_xml = etree.tostring(
        relationships_root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )
    temporary = target_docx + ".media.tmp"
    with zipfile.ZipFile(target_docx, "r") as source_zip, zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED
    ) as output_zip:
        content_types = etree.fromstring(source_zip.read("[Content_Types].xml"))
        existing_extensions = {
            item.get("Extension", "").lower()
            for item in content_types.findall(f"{{{CONTENT_TYPE_NS}}}Default")
        }
        for media_name in additions:
            extension = PurePosixPath(media_name).suffix.lstrip(".").lower()
            mime = MIME_BY_EXTENSION.get(extension)
            if mime and extension not in existing_extensions:
                item = etree.SubElement(
                    content_types, f"{{{CONTENT_TYPE_NS}}}Default"
                )
                item.set("Extension", extension)
                item.set("ContentType", mime)
                existing_extensions.add(extension)
        new_content_types = etree.tostring(
            content_types,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )

        for item in source_zip.infolist():
            if item.filename == "[Content_Types].xml":
                output_zip.writestr(item, new_content_types)
            elif item.filename == "word/_rels/document.xml.rels":
                output_zip.writestr(item, new_relationships_xml)
            else:
                output_zip.writestr(item, source_zip.read(item.filename))
        if "word/_rels/document.xml.rels" not in names:
            output_zip.writestr("word/_rels/document.xml.rels", new_relationships_xml)
        for media_name, data in additions.items():
            if media_name not in names:
                output_zip.writestr(media_name, data)
    shutil.move(temporary, target_docx)
    return len(additions)
