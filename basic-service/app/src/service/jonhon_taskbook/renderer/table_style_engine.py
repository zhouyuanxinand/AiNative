"""Deterministic table styling for generated taskbook content.

The engine deliberately contains presentation policy only.  Product names,
chapter numbers, indicator meanings and routing rules stay in profiles/rule
packs; this module only makes the already selected table cells visually
consistent with the controlled output style.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"

DEFAULT_FONT = "仿宋_GB2312"
DEFAULT_SIZE_HALF_POINTS = 21  # 10.5pt
THICK_BORDER_SIZE = 12  # OOXML eighth-points: 1.5pt
THIN_BORDER_SIZE = 4  # OOXML eighth-points: 0.5pt

# Widths are presentation defaults, not business rules.  Existing template
# geometry is preserved unless a caller explicitly supplies widths.
DEFAULT_WIDTHS = {
    "indicator": (1200, 2200, 2200, 2200, 1838),
    "failure": (1800, 1800, 2300, 1800, 1938),
}


def fit_widths(
    widths: tuple[int, ...],
    available_width: int,
) -> tuple[int, ...]:
    """Scale a logical column vector to exactly fit the live page width.

    Width ratios are presentation policy; the absolute width belongs to the
    current customer template because its page size and margins may change.
    """

    values = tuple(max(1, int(value)) for value in widths)
    target = int(available_width)
    if not values or target < len(values):
        return values
    source_total = sum(values)
    scaled = [max(1, value * target // source_total) for value in values]
    delta = target - sum(scaled)
    if delta:
        scaled[-1] += delta
    return tuple(scaled)


def _table_xml(table):
    return getattr(table, "_tbl", table)


def _iter_cells(table_xml) -> Iterable:
    yield from table_xml.findall(f".//{_W}tc")


def _iter_runs(cell) -> Iterable:
    yield from cell.findall(f".//{_W}r")


def _iter_paragraphs(cell) -> Iterable:
    yield from cell.findall(f".//{_W}p")


def _ensure_child(parent, tag: str):
    child = parent.find(tag)
    if child is None:
        child = OxmlElement(tag.replace(_W, "w:"))
        parent.append(child)
    return child


def _set_run_font(run, font_name: str, size_half_points: int) -> None:
    rpr = run.find(f"{_W}rPr")
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        run.insert(0, rpr)
    fonts = rpr.find(f"{_W}rFonts")
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(f"{{{W}}}{key}", font_name)
    for tag in ("sz", "szCs"):
        node = rpr.find(f"{_W}{tag}")
        if node is None:
            node = OxmlElement(f"w:{tag}")
            rpr.append(node)
        node.set(f"{{{W}}}val", str(size_half_points))
    # Customer templates may attach an italic paragraph/character style to
    # table cells.  Font name and size alone do not override that inheritance,
    # so the generated controlled tables must explicitly opt out of italics.
    for tag in ("i", "iCs"):
        node = rpr.find(f"{_W}{tag}")
        if node is None:
            node = OxmlElement(f"w:{tag}")
            rpr.append(node)
        node.set(f"{{{W}}}val", "0")


def _normalize_paragraph_spacing(paragraph) -> None:
    """Remove template-specific spacing from controlled table cells.

    The customer's Word templates can attach different paragraph styles to
    neighbouring rows.  Explicit OOXML values keep generated tables visually
    stable without depending on a product, chapter number, or template style
    name.
    """

    ppr = paragraph.find(f"{_W}pPr")
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        paragraph.insert(0, ppr)
    spacing = ppr.find(f"{_W}spacing")
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        ppr.append(spacing)
    spacing.set(f"{_W}before", "0")
    spacing.set(f"{_W}after", "0")
    spacing.set(f"{_W}line", "0")
    spacing.set(f"{_W}lineRule", "atLeast")


def _set_cell_width(cell, width: int) -> None:
    tc_pr = cell.find(f"{_W}tcPr")
    if tc_pr is None:
        tc_pr = OxmlElement("w:tcPr")
        cell.insert(0, tc_pr)
    tcw = tc_pr.find(f"{_W}tcW")
    if tcw is None:
        tcw = OxmlElement("w:tcW")
        tc_pr.append(tcw)
    tcw.set(f"{{{W}}}type", "dxa")
    tcw.set(f"{{{W}}}w", str(width))


def _set_fixed_layout(table_xml) -> None:
    tbl_pr = table_xml.find(f"{_W}tblPr")
    if tbl_pr is None:
        tbl_pr = OxmlElement("w:tblPr")
        table_xml.insert(0, tbl_pr)
    layout = tbl_pr.find(f"{_W}tblLayout")
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(f"{{{W}}}type", "fixed")
    jc = tbl_pr.find(f"{_W}jc")
    if jc is None:
        jc = OxmlElement("w:jc")
        tbl_pr.append(jc)
    jc.set(f"{{{W}}}val", "center")


def normalize_table_width(
    table,
    target_width: int,
    *,
    alignment: str = "left",
    indent: int = 0,
) -> tuple[int, ...]:
    """Fit an existing table to one exact width without changing its ratios.

    Word resolves ``tblW``, ``tblGrid`` and each row's ``tcW`` together.  A
    template can therefore render narrower than its grid when percentage cell
    widths survive alongside a DXA grid.  This helper rewrites the complete
    geometry contract while preserving merged cells and the template's column
    proportions.
    """

    table_xml = _table_xml(table)
    grid = table_xml.find(f"{_W}tblGrid")
    if grid is None:
        return ()
    source_widths: list[int] = []
    for column in grid.findall(f"{_W}gridCol"):
        try:
            width = int(column.get(f"{_W}w", "0"))
        except (TypeError, ValueError):
            return ()
        if width <= 0:
            return ()
        source_widths.append(width)
    if not source_widths or int(target_width) <= 0:
        return ()

    fitted = fit_widths(tuple(source_widths), int(target_width))
    _set_fixed_layout(table_xml)
    _set_table_grid(table_xml, fitted)
    _set_row_widths(table_xml, fitted)

    tbl_pr = table_xml.find(f"{_W}tblPr")
    if tbl_pr is None:
        return fitted
    jc = tbl_pr.find(f"{_W}jc")
    if jc is None:
        jc = OxmlElement("w:jc")
        tbl_pr.append(jc)
    jc.set(f"{_W}val", alignment)
    tbl_ind = tbl_pr.find(f"{_W}tblInd")
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(f"{_W}type", "dxa")
    tbl_ind.set(f"{_W}w", str(int(indent)))
    # Some legacy templates store alignment on every row.  Those row-level
    # values override tblPr/jc in Word, so normalize both layers.
    for row in table_xml.findall(f"{_W}tr"):
        tr_pr = row.find(f"{_W}trPr")
        if tr_pr is None:
            tr_pr = OxmlElement("w:trPr")
            row.insert(0, tr_pr)
        row_jc = tr_pr.find(f"{_W}jc")
        if row_jc is None:
            row_jc = OxmlElement("w:jc")
            tr_pr.append(row_jc)
        row_jc.set(f"{_W}val", alignment)
    return fitted


def _available_page_width(table_xml) -> int | None:
    """Read usable width from the live template instead of a fixed chapter."""

    root = table_xml.getroottree().getroot()
    for section in root.findall(f".//{_W}sectPr"):
        page = section.find(f"{_W}pgSz")
        margin = section.find(f"{_W}pgMar")
        if page is None or margin is None:
            continue
        try:
            width = int(page.get(f"{_W}w"))
            left = int(margin.get(f"{_W}left", "0"))
            right = int(margin.get(f"{_W}right", "0"))
        except (TypeError, ValueError):
            continue
        usable = width - left - right
        if usable > 0:
            return usable
    return None


def _dominant_dxa_table_width(table_xml) -> int | None:
    """Pick a stable table width from existing dxa table widths in the document."""

    root = table_xml.getroottree().getroot()
    values: list[int] = []
    for tbl_w in root.findall(f".//{_W}tblPr/{_W}tblW"):
        if tbl_w.get(f"{{{W}}}type") != "dxa":
            continue
        try:
            width = int(tbl_w.get(f"{{{W}}}w", "0"))
        except (TypeError, ValueError):
            continue
        if width > 0:
            values.append(width)
    if not values:
        return None
    counts = Counter(values)
    top = max(counts.values())
    # Prefer the narrower width when frequencies tie to avoid layout overflow.
    return min(width for width, freq in counts.items() if freq == top)


def _set_table_grid(table_xml, widths: tuple[int, ...]) -> None:
    grid = table_xml.find(f"{_W}tblGrid")
    if grid is None:
        grid = OxmlElement("w:tblGrid")
        table_xml.insert(1 if table_xml.find(f"{_W}tblPr") is not None else 0, grid)
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        column = OxmlElement("w:gridCol")
        column.set(f"{_W}w", str(width))
        grid.append(column)

    tbl_pr = table_xml.find(f"{_W}tblPr")
    if tbl_pr is not None:
        table_width = tbl_pr.find(f"{_W}tblW")
        if table_width is None:
            table_width = OxmlElement("w:tblW")
            tbl_pr.insert(0, table_width)
        table_width.set(f"{_W}type", "dxa")
        table_width.set(f"{_W}w", str(sum(widths)))


def _grid_span(cell) -> int:
    span = cell.find(f"./{_W}tcPr/{_W}gridSpan")
    if span is None:
        return 1
    try:
        return max(1, int(span.get(f"{_W}val", "1")))
    except ValueError:
        return 1


def _set_row_widths(table_xml, widths: tuple[int, ...]) -> None:
    for row in table_xml.findall(f"{_W}tr"):
        cursor = 0
        cells = row.findall(f"{_W}tc")
        for cell in cells:
            span = _grid_span(cell)
            end = min(len(widths), cursor + span)
            if cursor >= len(widths) or end <= cursor:
                break
            _set_cell_width(cell, sum(widths[cursor:end]))
            cursor = end


def _normalize_row_flow(table_xml) -> None:
    """Keep one repeatable header and let all body rows grow across pages."""

    for index, row in enumerate(table_xml.findall(f"{_W}tr")):
        tr_pr = row.find(f"{_W}trPr")
        if tr_pr is None:
            tr_pr = OxmlElement("w:trPr")
            row.insert(0, tr_pr)
        for tag in ("tblHeader", "trHeight"):
            for node in list(tr_pr.findall(f"{_W}{tag}")):
                tr_pr.remove(node)
        if index == 0:
            header = OxmlElement("w:tblHeader")
            header.set(f"{_W}val", "true")
            tr_pr.append(header)
        else:
            for node in list(tr_pr.findall(f"{_W}cantSplit")):
                tr_pr.remove(node)


def _set_cell_border(cell, side: str, size: int) -> None:
    """Write one explicit cell border so Word cannot inherit a wrong weight."""

    tc_pr = cell.find(f"{_W}tcPr")
    if tc_pr is None:
        tc_pr = OxmlElement("w:tcPr")
        cell.insert(0, tc_pr)
    borders = tc_pr.find(f"{_W}tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    border = borders.find(f"{_W}{side}")
    if border is None:
        border = OxmlElement(f"w:{side}")
        borders.append(border)
    border.set(f"{_W}val", "single")
    border.set(f"{_W}sz", str(int(size)))
    border.set(f"{_W}space", "0")
    border.set(f"{_W}color", "000000")


def _set_table_border(table_xml, side: str, size: int) -> None:
    """Keep table-level borders aligned with the explicit cell contract."""

    tbl_pr = table_xml.find(f"{_W}tblPr")
    if tbl_pr is None:
        tbl_pr = OxmlElement("w:tblPr")
        table_xml.insert(0, tbl_pr)
    borders = tbl_pr.find(f"{_W}tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    border = borders.find(f"{_W}{side}")
    if border is None:
        border = OxmlElement(f"w:{side}")
        borders.append(border)
    border.set(f"{_W}val", "single")
    border.set(f"{_W}sz", str(int(size)))
    border.set(f"{_W}space", "0")
    border.set(f"{_W}color", "000000")


def normalize_table_borders(
    table,
    *,
    header_rows: int = 1,
    thick_size: int = THICK_BORDER_SIZE,
    thin_size: int = THIN_BORDER_SIZE,
) -> None:
    """Apply thick frame/header borders and thin body grid lines.

    This operates on the live template structure.  It contains no product,
    model or chapter assumptions, so the same renderer covers every controlled
    indicator and failure-mode table.
    """

    table_xml = _table_xml(table)
    rows = table_xml.findall(f"{_W}tr")
    if not rows:
        return
    for side, size in {
        "top": thick_size,
        "left": thick_size,
        "bottom": thick_size,
        "right": thick_size,
        "insideH": thin_size,
        "insideV": thin_size,
    }.items():
        _set_table_border(table_xml, side, size)
    last_row = len(rows) - 1
    for row_index, row in enumerate(rows):
        cells = row.findall(f"{_W}tc")
        if not cells:
            continue
        is_header = row_index < max(0, int(header_rows))
        for cell_index, cell in enumerate(cells):
            if is_header:
                sizes = {
                    "top": thick_size,
                    "left": thick_size if cell_index == 0 else thin_size,
                    "bottom": thick_size,
                    "right": thick_size if cell_index == len(cells) - 1 else thin_size,
                }
            else:
                sizes = {
                    "top": thin_size,
                    "left": thick_size if cell_index == 0 else thin_size,
                    "bottom": thick_size if row_index == last_row else thin_size,
                    "right": thick_size if cell_index == len(cells) - 1 else thin_size,
                }
            for side, size in sizes.items():
                _set_cell_border(cell, side, size)


def apply_table_style(
    table,
    table_kind: str = "generic",
    *,
    font_name: str = DEFAULT_FONT,
    size_half_points: int = DEFAULT_SIZE_HALF_POINTS,
    widths: tuple[int, ...] | None = None,
) -> None:
    """Apply deterministic presentation styling to a python-docx table/XML.

    ``widths`` is optional.  If omitted, a default is applied only when the
    table has the matching logical column count; otherwise its template grid
    is preserved.  This avoids making chapter- or product-specific assumptions.
    """

    table_xml = _table_xml(table)
    _set_fixed_layout(table_xml)
    cells = list(_iter_cells(table_xml))
    width_values = tuple(int(value) for value in widths) if widths else None
    if width_values is None:
        default_widths = DEFAULT_WIDTHS.get(table_kind)
        rows = table_xml.findall(f"{_W}tr")
        first_row = rows[0] if rows else None
        logical_columns = sum(
            _grid_span(cell)
            for cell in (first_row.findall(f"{_W}tc") if first_row is not None else [])
        )
        # A controlled customer template is the column authority.  A default
        # vector is safe only when it describes that exact live structure.
        if default_widths and len(default_widths) == logical_columns:
            width_values = default_widths
    if width_values:
        available = _dominant_dxa_table_width(table_xml) or _available_page_width(table_xml)
        if available:
            width_values = fit_widths(width_values, available)
        _set_table_grid(table_xml, width_values)
        _set_row_widths(table_xml, width_values)
        _normalize_row_flow(table_xml)
    if table_kind in {"indicator", "failure"}:
        normalize_table_borders(table_xml)
    for cell in cells:
        for paragraph in _iter_paragraphs(cell):
            _normalize_paragraph_spacing(paragraph)
        for run in _iter_runs(cell):
            _set_run_font(run, font_name, size_half_points)
