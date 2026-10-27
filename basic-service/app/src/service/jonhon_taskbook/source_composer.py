"""Import source-document styles without binding them to template-local IDs.

docxcompose still handles package parts and media.  Style and numbering IDs,
however, belong to a document: a converted DOC's Normal style can have the same
ID as the taskbook's figure caption.  Import the complete dependency graph and
rewrite each reference separately before the copied XML enters the template.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import sys

from docx.enum.style import WD_STYLE_TYPE
from docx.opc.oxml import serialize_part_xml
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn

try:
    from docxcompose.composer import Composer
except ModuleNotFoundError:
    _vendored = Path(__file__).resolve().parents[1] / "third_party_sources" / "docxcompose"
    if not (_vendored / "docxcompose" / "composer.py").is_file():
        raise
    sys.path.insert(0, str(_vendored))
    from docxcompose.composer import Composer


class SourceDocumentComposer(Composer):
    """Keep source styles and list definitions isolated from the template."""

    def __init__(self, doc, preserve_styles=True):
        super().__init__(doc, preserve_styles=preserve_styles)
        self._source_states = {}
        self._vml_identifiers = None

    def _create_style_id_mapping(self, doc):
        super()._create_style_id_mapping(doc)
        self._bind_source(doc)

    def _bind_source(self, doc):
        # Callers copy individual blocks, resetting relationship mappings before
        # each block.  Lists and styles must retain their document-level mapping
        # so lists continue and source IDs cannot refer to another source's data.
        state = self._source_states.setdefault(doc.part, {
            "styles": {}, "numbers": {}, "abstract_numbers": {},
        })
        self._source_style_ids = state["styles"]
        self.num_id_mapping = state["numbers"]
        self.anum_id_mapping = state["abstract_numbers"]

    def _import_style(self, doc, source_id):
        if source_id in self._source_style_ids:
            return self._source_style_ids[source_id]
        source_style = doc.styles.element.get_by_id(source_id)
        if source_style is None:
            return None

        styles = self.doc.styles.element
        destination_id = source_id
        suffix = 1
        while styles.get_by_id(destination_id) is not None:
            destination_id = f"{source_id}_source{suffix}"
            suffix += 1
        copied = deepcopy(source_style)
        copied.set(qn("w:styleId"), destination_id)
        # A source default is now an explicitly referenced style.  It must not
        # become a second default and change untouched controlled-template text.
        copied.attrib.pop(qn("w:default"), None)
        name = copied.find(qn("w:name"))
        if name is not None:
            original_name = name.get(qn("w:val"), source_id)
            names = {node.get(qn("w:val")) for node in styles.findall("./" + qn("w:style") + "/" + qn("w:name"))}
            new_name, suffix = original_name, 1
            while new_name in names:
                new_name = f"{original_name} (source {suffix})"
                suffix += 1
            name.set(qn("w:val"), new_name)

        # Reserve before traversing: paragraph/character linked styles commonly
        # refer back to each other, and next may refer to the current style.
        self._source_style_ids[source_id] = destination_id
        styles.append(copied)
        for tag in ("basedOn", "next", "link"):
            for reference in list(copied.findall(qn("w:" + tag))):
                mapped = self._import_style(doc, reference.get(qn("w:val")))
                if mapped is None:
                    copied.remove(reference)
                else:
                    reference.set(qn("w:val"), mapped)
        self.add_numberings(doc, copied)
        return destination_id

    def add_styles(self, doc, element):
        self._bind_source(doc)
        # An absent pStyle/tblStyle means the SOURCE default, not the target's
        # default.  In particular, template body indents can consume most of a
        # narrow table cell if a source default is left implicit.
        for tag, properties, reference_tag, kind in (
            ("p", "pPr", "pStyle", WD_STYLE_TYPE.PARAGRAPH),
            ("tbl", "tblPr", "tblStyle", WD_STYLE_TYPE.TABLE),
        ):
            default = doc.styles.default(kind)
            if default is None:
                continue
            for node in element.iter(qn("w:" + tag)):
                props = node.find(qn("w:" + properties))
                if props is None:
                    props = OxmlElement("w:" + properties)
                    node.insert(0, props)
                if props.find(qn("w:" + reference_tag)) is None:
                    reference = OxmlElement("w:" + reference_tag)
                    reference.set(qn("w:val"), default.style_id)
                    props.insert(0, reference)
        # Snapshot the refs before any changes.  Rewriting the entire block once
        # per style would turn paragraph, character and table styles into the
        # final style in the block, causing wrong list labels and cell layout.
        style_tags = {qn("w:tblStyle"), qn("w:pStyle"), qn("w:rStyle")}
        references = [node for node in element.iter() if node.tag in style_tags]
        for reference in references:
            mapped = self._import_style(doc, reference.get(qn("w:val")))
            if mapped is None:
                reference.getparent().remove(reference)
            else:
                reference.set(qn("w:val"), mapped)

    def add_numberings(self, doc, element):
        self._bind_source(doc)
        references = list(element.iter(qn("w:numId")))
        source_ids = [int(reference.get(qn("w:val"))) for reference in references]
        for source_id in dict.fromkeys(source_ids):
            if source_id == 0 or source_id in self.num_id_mapping:
                continue
            # Upstream allocates IDs once per invocation.  Import one numId at a
            # time so two lists in one table cannot receive the same destination
            # ID.  Use a separate node to avoid rewriting an already-mapped ref.
            holder = OxmlElement("w:p")
            num_id = OxmlElement("w:numId")
            num_id.set(qn("w:val"), str(source_id))
            holder.append(num_id)
            previous_abstract_ids = set(self.anum_id_mapping.values())
            super().add_numberings(doc, holder)
            imported_abstract_ids = set(self.anum_id_mapping.values()) - previous_abstract_ids
            for abstract_id in imported_abstract_ids:
                abstracts = self.numbering_part().element.xpath(
                    f'./w:abstractNum[@w:abstractNumId="{abstract_id}"]'
                )
                for abstract in abstracts:
                    style_tags = {qn("w:pStyle"), qn("w:numStyleLink"), qn("w:styleLink")}
                    for reference in [node for node in abstract.iter() if node.tag in style_tags]:
                        mapped = self._import_style(doc, reference.get(qn("w:val")))
                        if mapped is None:
                            reference.getparent().remove(reference)
                        else:
                            reference.set(qn("w:val"), mapped)
        for reference, source_id in zip(references, source_ids):
            reference.set(qn("w:val"), str(self.num_id_mapping.get(source_id, source_id)))

    def add_footnotes(self, doc, element):
        references = list(element.iter(qn("w:footnoteReference")))
        if not references:
            return
        super().add_footnotes(doc, element)
        # Upstream copies note XML verbatim.  Importing styles from a temporary
        # source-part tree later does not rewrite those target-note references.
        part = self.footnote_part()
        notes = parse_xml(part.blob)
        copied_ids = {reference.get(qn("w:id")) for reference in references}
        for note in notes:
            if note.get(qn("w:id")) in copied_ids:
                self.add_styles(doc, note)
                self.add_numberings(doc, note)
        part._blob = serialize_part_xml(notes)

    def add_shapes(self, doc, element):
        super().add_shapes(doc, element)
        self._unique_vml_shape_ids(element)

    def _unique_vml_shape_ids(self, element):
        shape_tag = "{urn:schemas-microsoft-com:vml}shape"
        spid = "{urn:schemas-microsoft-com:office:office}spid"
        shapes = list(element.iter(shape_tag))
        if not shapes:
            return
        if self._vml_identifiers is None:
            self._vml_identifiers = set()
            for part in self.pkg.parts:
                root = getattr(part, "element", None)
                if root is not None:
                    for shape in root.iter(shape_tag):
                        self._vml_identifiers.update(
                            value for value in (shape.get("id"), shape.get(spid)) if value
                        )
        used = self._vml_identifiers
        definitions = [(shape, attribute, shape.get(attribute))
                       for shape in shapes for attribute in ("id", spid)
                       if shape.get(attribute)]
        # Do not allocate another source shape's original ID while resolving a
        # collision; OLE objects and controls refer to these identifiers locally.
        reserved = used | {value for _, _, value in definitions}
        mapping = {}
        for _, _, original in definitions:
            if original in mapping:
                continue
            candidate = original
            if candidate in used:
                numeric = re.fullmatch(r"(_x0000_[is])(\d+)", original)
                suffix = int(numeric[2]) + 1 if numeric else 1
                while True:
                    candidate = f"{numeric[1]}{suffix}" if numeric else f"{original}_source{suffix}"
                    if candidate not in reserved:
                        break
                    suffix += 1
            mapping[original] = candidate
            used.add(candidate)
            reserved.add(candidate)
        for shape, attribute, original in definitions:
            shape.set(attribute, mapping[original])
        for node in element.iter():
            for attribute, value in list(node.attrib.items()):
                local_name = attribute.rsplit("}", 1)[-1]
                if local_name in {"ShapeID", "shapeid", "idref"} and value in mapping:
                    node.set(attribute, mapping[value])
                elif local_name == "href" and value.startswith("#") and value[1:] in mapping:
                    node.set(attribute, "#" + mapping[value[1:]])
