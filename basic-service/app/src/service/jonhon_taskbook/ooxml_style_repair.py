"""Repair specific schema defects retained in controlled Word templates.

Style child order and CT_OnOffOnly values follow the Open XML SDK schema:
https://github.com/dotnet/Open-XML-SDK/blob/main/data/schemas/
schemas_openxmlformats_org_wordprocessingml_2006_main.json
"""

from __future__ import annotations

from lxml import etree


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_STYLE_ORDER = {
    _W + name: index for index, name in enumerate((
        "name aliases basedOn next link autoRedefine hidden uiPriority "
        "semiHidden unhideWhenUsed qFormat locked personal personalCompose "
        "personalReply rsid pPr rPr tblPr trPr tcPr tblStylePr"
    ).split())
}
_ON_OFF_ONLY_TAGS = {_W + "noWrap", _W + "tblHeader"}
_ON_OFF_ONLY_VALUES = {"0": "off", "false": "off", "1": "on", "true": "on"}


def normalize_template_styles(root: etree._Element) -> dict[str, int]:
    """Normalize proven defects while retaining unknown markup for diagnosis.

    Only known direct children of style definitions are reordered. A tblStyle
    inside a style definition is illegal; remove it only when its reference is
    self-referential or already expressed by the style's single basedOn value.
    Real document tables and unresolved style references are left untouched.
    """
    stats = {
        "ooxml_style_order_normalized": 0,
        "ooxml_redundant_style_references_removed": 0,
        "ooxml_on_off_only_values_normalized": 0,
    }
    for style in root.iter(_W + "style"):
        children = list(style)
        positions = [i for i, child in enumerate(children) if child.tag in _STYLE_ORDER]
        ordered = sorted((children[i] for i in positions), key=lambda c: _STYLE_ORDER[c.tag])
        if any(children[i] is not child for i, child in zip(positions, ordered)):
            for i, child in zip(positions, ordered):
                children[i] = child
            style[:] = children
            stats["ooxml_style_order_normalized"] += 1

        if style.get(_W + "type") != "table":
            continue
        own_id = style.get(_W + "styleId")
        parents = style.findall(_W + "basedOn")
        parent_id = parents[0].get(_W + "val") if len(parents) == 1 else None
        redundant_ids = {value for value in (own_id, parent_id) if value}
        for properties in style.findall(_W + "tblPr"):
            for reference in properties.findall(_W + "tblStyle"):
                if reference.get(_W + "val") in redundant_ids:
                    properties.remove(reference)
                    stats["ooxml_redundant_style_references_removed"] += 1

    # Unlike ordinary CT_OnOff booleans, these two elements accept on/off only.
    # Omission, already-valid on/off, unknown values and foreign flags survive.
    for element in root.iter():
        if element.tag in _ON_OFF_ONLY_TAGS:
            value = element.get(_W + "val")
            if value in _ON_OFF_ONLY_VALUES:
                element.set(_W + "val", _ON_OFF_ONLY_VALUES[value])
                stats["ooxml_on_off_only_values_normalized"] += 1
    return stats
