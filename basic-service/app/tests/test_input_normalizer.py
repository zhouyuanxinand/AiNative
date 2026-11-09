"""Real PDF and local OCR regressions for development-logic C6 input formats."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from docx import Document
from jonhon_taskbook import input_normalizer
from jonhon_taskbook.input_normalizer import InputNormalizationError, normalize_input
from PIL import Image, ImageDraw, ImageFont


def _source_image(path: Path) -> Path:
    image = Image.new("RGB", (1800, 550), "white")
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    if not font_path.is_file():
        font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font = ImageFont.truetype(str(font_path), 54)
    draw = ImageDraw.Draw(image)
    draw.text((70, 70), "Contact resistance <= 5 mOhm", fill="black", font=font)
    draw.text((70, 180), "Rated current 10 A", fill="black", font=font)
    draw.text((70, 290), "Mechanical life >= 500 cycles", fill="black", font=font)
    image.save(path)
    return path


def _manifest(result):
    return json.loads(result.evidence_path.read_text(encoding="utf-8"))


def _docx_text(path):
    document = Document(path)
    return "\n".join([p.text for p in document.paragraphs] + [cell.text for table in document.tables for row in table.rows for cell in row.cells])


def test_existing_docx_is_validated_without_rewriting_original(tmp_path):
    path = tmp_path / "original.docx"
    document = Document()
    document.add_paragraph("接触电阻≤5mΩ")
    document.save(path)
    original = path.read_bytes()
    result = normalize_input(path, tmp_path / "normalized")
    assert result.path == path.resolve()
    assert result.method == "docx_passthrough"
    assert result.requires_review is False
    assert path.read_bytes() == original


def test_real_text_pdf_preserves_pages_and_source_hash(tmp_path):
    path = tmp_path / "two-pages.pdf"
    with pymupdf.open() as pdf:
        for text in ("Contact resistance <= 5 mOhm", "Rated current 10 A"):
            pdf.new_page().insert_text((72, 100), text, fontsize=16)
        pdf.save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = normalize_input(path, tmp_path / "normalized", ocr_enabled=False)
    evidence = _manifest(result)
    assert result.method == "pdf_text"
    assert result.requires_review is True
    assert [page["page"] for page in evidence["pages"]] == [1, 2]
    assert all((result.evidence_path.parent / page["image"]).is_file() for page in evidence["pages"])
    assert all(line["confidence"] is None for page in evidence["pages"] for line in page["lines"])
    assert evidence["source_sha256"] == digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "Contact resistance <= 5 mOhm" in _docx_text(result.path)
    assert "Rated current 10 A" in _docx_text(result.path)


def test_real_pdf_ruled_table_is_reconstructed_without_duplicate_cell_text(tmp_path):
    path = tmp_path / "table.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        for x in (60, 240, 420):
            page.draw_line((x, 100), (x, 220))
        for y in (100, 140, 180, 220):
            page.draw_line((60, y), (420, y))
        for row, values in enumerate((("Indicator", "Value"), ("Contact resistance", "5 mOhm"), ("Rated current", "10 A"))):
            for column, value in enumerate(values):
                page.insert_text((70 + column * 180, 125 + row * 40), value, fontsize=11)
        pdf.save(path)
    result = normalize_input(path, tmp_path / "normalized", ocr_enabled=False)
    document = Document(result.path)
    assert len(document.tables) == 1
    assert document.tables[0].cell(1, 1).text == "5 mOhm"
    assert "Contact resistance" not in "\n".join(p.text for p in document.paragraphs)


def test_actual_local_ocr_reads_image_and_records_line_confidence(tmp_path, monkeypatch):
    import requests

    def no_network(*args, **kwargs):
        raise AssertionError("本地 OCR 不应发起任何网络请求")

    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    source = _source_image(tmp_path / "scan.png")
    result = normalize_input(source, tmp_path / "normalized", ocr_enabled=True)
    evidence = _manifest(result)
    assert result.method == "image_ocr"
    assert result.requires_review is True
    assert "contact resistance" in _docx_text(result.path).lower()
    assert "rated current" in _docx_text(result.path).lower()
    assert all(0 <= line["confidence"] <= 1 and len(line["bbox"]) == 4 for line in evidence["pages"][0]["lines"])


def test_actual_local_ocr_reads_scanned_pdf_page(tmp_path):
    scan = _source_image(tmp_path / "scan.png")
    path = tmp_path / "scanned.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=900, height=275)
        page.insert_image(page.rect, filename=str(scan))
        pdf.save(path)
    result = normalize_input(path, tmp_path / "normalized", ocr_enabled=True)
    assert result.method == "pdf_ocr"
    assert "rated current" in _docx_text(result.path).lower()
    assert _manifest(result)["pages"][0]["coordinate_system"] == "image_pixels"


def test_native_page_plus_scan_uses_per_page_methods(tmp_path):
    scan = _source_image(tmp_path / "scan.png")
    path = tmp_path / "mixed.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 100), "Product technical requirements", fontsize=16)
        page = pdf.new_page(width=900, height=275)
        page.insert_image(page.rect, filename=str(scan))
        pdf.save(path)
    result = normalize_input(path, tmp_path / "normalized", ocr_enabled=True)
    assert result.method == "pdf_mixed"
    assert [page["method"] for page in _manifest(result)["pages"]] == ["pdf_text", "pdf_ocr"]


def test_disabled_ocr_does_not_succeed_with_an_empty_document(tmp_path):
    scan = _source_image(tmp_path / "scan.png")
    with pytest.raises(InputNormalizationError, match="OCR 已禁用") as error:
        normalize_input(scan, tmp_path / "normalized", ocr_enabled=False)
    evidence = json.loads(error.value.evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert (error.value.evidence_path.parent / evidence["pages"][0]["image"]).is_file()


def test_missing_ocr_engine_is_an_explicit_failure_with_source_page(tmp_path, monkeypatch):
    scan = _source_image(tmp_path / "scan.png")

    def unavailable():
        raise InputNormalizationError("本地 OCR 不可用：未安装 rapidocr")

    monkeypatch.setattr(input_normalizer, "_get_ocr_engine", unavailable)
    with pytest.raises(InputNormalizationError, match="本地 OCR 不可用") as error:
        normalize_input(scan, tmp_path / "normalized", ocr_enabled=True)
    assert error.value.evidence_path.is_file()


def test_low_confidence_text_is_preserved_for_review_not_silently_discarded(tmp_path, monkeypatch):
    scan = _source_image(tmp_path / "scan.png")
    result = SimpleNamespace(txts=("Rated current 10 A",), scores=(0.42,), boxes=(((1, 1), (100, 1), (100, 20), (1, 20)),))
    monkeypatch.setattr(input_normalizer, "_get_ocr_engine", lambda: lambda path: result)
    normalized = normalize_input(scan, tmp_path / "normalized", ocr_enabled=True)
    assert normalized.requires_review is True
    assert "Rated current 10 A" in _docx_text(normalized.path)
    assert any("置信度" in warning for warning in normalized.warnings)
    assert _manifest(normalized)["pages"][0]["lines"][0]["confidence"] == 0.42


def test_blank_pdf_is_a_failure_not_successful_empty_extraction(tmp_path):
    path = tmp_path / "blank.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(path)
    with pytest.raises(InputNormalizationError, match="未提取到可用正文") as error:
        normalize_input(path, tmp_path / "normalized", ocr_enabled=False)
    assert json.loads(error.value.evidence_path.read_text(encoding="utf-8"))["status"] == "failed"


def test_blank_docx_is_rejected(tmp_path):
    path = tmp_path / "blank.docx"
    Document().save(path)
    with pytest.raises(InputNormalizationError, match="没有可提取正文"):
        normalize_input(path, tmp_path / "normalized")


def test_password_protected_pdf_is_rejected(tmp_path):
    path = tmp_path / "encrypted.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Secret example")
        pdf.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    with pytest.raises(InputNormalizationError, match="PDF 已加密"):
        normalize_input(path, tmp_path / "normalized")


def test_unsupported_format_is_rejected(tmp_path):
    path = tmp_path / "input.txt"
    path.write_text("Rated current 10 A", encoding="utf-8")
    with pytest.raises(InputNormalizationError, match="不支持该输入格式"):
        normalize_input(path, tmp_path / "normalized")


def test_missing_local_models_never_start_engine_or_download(tmp_path):
    module = SimpleNamespace(__file__=str(tmp_path / "rapidocr" / "__init__.py"))
    with pytest.raises(InputNormalizationError, match="不会联网下载模型"):
        input_normalizer._local_model_paths(module)


def test_actual_local_ocr_reads_chinese_requirement(tmp_path):
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if not font_path.is_file():
        pytest.skip("真实中文 OCR 测试需要中文字体")
    source = tmp_path / "中文扫描.png"
    image = Image.new("RGB", (1600, 420), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 52)
    draw.text((60, 50), "接触电阻 最大值 5 毫欧", fill="black", font=font)
    draw.text((60, 170), "额定电流 10 安培", fill="black", font=font)
    image.save(source)
    normalized = normalize_input(source, tmp_path / "normalized", ocr_enabled=True)
    text = _docx_text(normalized.path)
    assert "接触电阻" in text
    assert "额定电流" in text
    assert normalized.requires_review is True


@pytest.mark.skipif(os.name != "nt", reason="真实旧 DOC 转换测试需要 Windows Microsoft Word")
@pytest.mark.parametrize("broken_dispatch_cache", [False, True], ids=["normal-cache", "broken-dispatch-cache"])
def test_actual_word_converts_legacy_doc_read_only(tmp_path, monkeypatch, broken_dispatch_cache):
    import pythoncom
    from pywintypes import com_error
    from win32com.client import gencache

    source_docx = tmp_path / "original.docx"
    source = tmp_path / "legacy.doc"
    document = Document()
    document.add_paragraph("接触电阻≤5mΩ")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "额定电流"
    table.cell(0, 1).text = "10A"
    document.save(source_docx)
    pythoncom.CoInitialize()
    word = opened = None
    try:
        try:
            word = input_normalizer._create_word_application()
        except com_error:
            pytest.skip("本机未安装可用 Microsoft Word")
        word.Visible = False
        word.DisplayAlerts = 0
        word.AutomationSecurity = 3
        opened = input_normalizer._open_word_document(word, source_docx.resolve())
        opened.SaveAs2(str(source.resolve()), FileFormat=0)
    finally:
        if opened is not None:
            opened.Close(False)
        if word is not None:
            word.Quit()
        import gc
        opened = word = None
        gc.collect()
        pythoncom.CoUninitialize()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if broken_dispatch_cache:
        def unusable_generated_cache(*args, **kwargs):
            raise AttributeError("CLSIDToClassMap")
        monkeypatch.setattr(gencache, "GetClassForCLSID", unusable_generated_cache)
    normalized = normalize_input(source, tmp_path / "normalized")
    assert normalized.method == "word_com"
    assert "接触电阻≤5mΩ" in _docx_text(normalized.path)
    assert Document(normalized.path).tables[0].cell(0, 1).text == "10A"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_ocr_environment_disable_is_honored(tmp_path, monkeypatch):
    source = _source_image(tmp_path / "scan.png")
    monkeypatch.setenv("JTB_INPUT_OCR_ENABLED", "0")
    with pytest.raises(InputNormalizationError, match="OCR 已禁用"):
        normalize_input(source, tmp_path / "normalized")
