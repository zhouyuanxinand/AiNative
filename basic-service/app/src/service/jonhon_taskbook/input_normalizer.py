"""Normalize local Word, PDF and scanned inputs while retaining page evidence.

PDF and OCR conversion are deliberately reviewable rather than layout-faithful:
the normalized DOCX carries extracted content, while the manifest preserves each
original page image, text coordinates and OCR confidence. No document is sent to
an external service, and missing local OCR models never trigger a download.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from docx import Document
from PIL import Image, ImageOps

SUPPORTED_INPUT_EXTENSIONS = frozenset({".docx", ".doc", ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"})
_OCR_LOCK = threading.Lock()
_OCR_REVIEW_CONFIDENCE = 0.85
logger = logging.getLogger(__name__)


class InputNormalizationError(ValueError):
    def __init__(self, message: str, *, evidence_path: Path | None = None):
        super().__init__(message)
        self.evidence_path = evidence_path


@dataclass(frozen=True)
class NormalizedInput:
    path: Path
    original_path: Path
    method: str
    warnings: tuple[str, ...]
    requires_review: bool
    evidence_path: Path | None = None


def _hash_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _document_has_text(document) -> bool:
    return any(text.strip() for text in document.element.body.itertext())


def _load_docx(path: Path):
    try:
        document = Document(str(path))
    except Exception as exc:
        raise InputNormalizationError("Word 文件不是可读取的 DOCX 文档，请检查文件是否损坏或加密。") from exc
    if not _document_has_text(document):
        raise InputNormalizationError("Word 文件没有可提取正文；若为图片扫描件，请导出为 PDF 或图片进行本地 OCR。")
    return document


def _save_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _local_model_paths(rapidocr_module) -> tuple[str, str, str]:
    configured = [os.getenv(f"JTB_OCR_{stage}_MODEL", "").strip() for stage in ("DET", "CLS", "REC")]
    if any(configured):
        if not all(configured) or not all(Path(item).is_file() for item in configured):
            raise InputNormalizationError("本地 OCR 模型不完整：须同时配置 DET、CLS、REC 三个现有 ONNX 模型路径。")
        return tuple(str(Path(item).resolve()) for item in configured)
    model_dir = Path(rapidocr_module.__file__).resolve().parent / "models"
    paths = []
    for stage in ("det", "cls", "rec"):
        candidates = [path for path in model_dir.glob("*.onnx") if stage in path.stem.lower().split("_")]
        if len(candidates) != 1:
            raise InputNormalizationError(
                f"本地 OCR 缺少唯一的 {stage} 模型；请安装带模型的 rapidocr，或配置 JTB_OCR_DET_MODEL、JTB_OCR_CLS_MODEL、JTB_OCR_REC_MODEL。不会联网下载模型。"
            )
        paths.append(str(candidates[0]))
    return tuple(paths)


@lru_cache(maxsize=2)
def _build_ocr_engine(model_paths: tuple[str, str, str]):
    from rapidocr import EngineType, RapidOCR

    parameters = {"Global.text_score": 0.0, "Global.log_level": "warning"}
    for stage, model_path in zip(("Det", "Cls", "Rec"), model_paths, strict=True):
        parameters[f"{stage}.model_path"] = model_path
        parameters[f"{stage}.engine_type"] = EngineType.ONNXRUNTIME
    try:
        return RapidOCR(params=parameters)
    except Exception as exc:
        raise InputNormalizationError("本地 OCR 引擎初始化失败，请核查 ONNX Runtime、模型和运行环境。") from exc


def _get_ocr_engine():
    try:
        rapidocr_module = importlib.import_module("rapidocr")
        importlib.import_module("onnxruntime")
    except ImportError as exc:
        raise InputNormalizationError("本地 OCR 不可用：未安装 rapidocr 或 onnxruntime，扫描件不能继续生成。") from exc
    return _build_ocr_engine(_local_model_paths(rapidocr_module))


def _ocr_page(image_path: Path, enabled: bool) -> list[dict]:
    if not enabled:
        raise InputNormalizationError("本地 OCR 已禁用（JTB_INPUT_OCR_ENABLED=0）；请启用后处理扫描件，或上传带文字的 Word/PDF。")
    with _OCR_LOCK:
        engine = _get_ocr_engine()
        try:
            result = engine(str(image_path))
        except Exception as exc:
            raise InputNormalizationError("本地 OCR 识别失败，原页已保留，请核查图片清晰度或引擎配置。") from exc
    texts = result.txts or ()
    scores = result.scores or ()
    boxes = result.boxes
    if len(texts) != len(scores) or (texts and (boxes is None or len(boxes) != len(texts))):
        raise InputNormalizationError("本地 OCR 返回的文本、位置和置信度不一致，不能继续生成。")
    lines = []
    for text, score, box in zip(texts, scores, boxes if boxes is not None else (), strict=True):
        if str(text).strip():
            confidence = float(score)
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise InputNormalizationError("本地 OCR 返回无效置信度，不能继续生成。")
            lines.append({
                "text": str(text),
                "confidence": confidence,
                "low_confidence": confidence < _OCR_REVIEW_CONFIDENCE,
                "bbox": [[float(x), float(y)] for x, y in box],
            })
    return lines


def _is_blank_image(path: Path) -> bool:
    with Image.open(path) as image:
        extrema = image.convert("L").getextrema()
        return extrema[0] >= 250


def _native_pdf_items(page) -> tuple[list[dict], list[dict]]:
    lines = []
    for block in page.get_text("dict", sort=True)["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                lines.append({"text": text, "bbox": list(line["bbox"]), "confidence": None})
    tables = []
    try:
        for table in page.find_tables().tables:
            rows = table.extract()
            if rows and any(str(cell or "").strip() for row in rows for cell in row):
                tables.append({"kind": "table", "bbox": list(table.bbox), "rows": rows})
    except (ValueError, RuntimeError):
        # The page image and every text line remain available when no reliable
        # table reconstruction is available. Review is mandatory in either case.
        tables = []
    items = list(tables)
    for line in lines:
        x0, y0, x1, y1 = line["bbox"]
        x, y = (x0 + x1) / 2, (y0 + y1) / 2
        if not any(table["bbox"][0] <= x <= table["bbox"][2] and table["bbox"][1] <= y <= table["bbox"][3] for table in tables):
            items.append({"kind": "paragraph", **line})
    items.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return lines, items


def _write_page(document, page: dict) -> None:
    if page["page"] > 1:
        document.add_page_break()
    page["docx_paragraph_start"] = len(document.paragraphs)
    for item in page["items"]:
        if item["kind"] == "table":
            rows = item["rows"]
            width = max(len(row) for row in rows)
            table = document.add_table(rows=len(rows), cols=width)
            table.style = "Table Grid"
            for row_index, row in enumerate(rows):
                for column, cell in enumerate(row):
                    table.cell(row_index, column).text = str(cell or "")
        else:
            # Keep source wording intact; page labels live in the evidence
            # manifest instead of being inserted as invented requirement text.
            document.add_paragraph(item["text"])
    page["docx_paragraph_end"] = len(document.paragraphs)


def _read_pdf(source: Path, evidence_dir: Path, manifest: dict, ocr_enabled: bool):
    try:
        pymupdf = importlib.import_module("pymupdf")
    except ImportError as exc:
        raise InputNormalizationError("PDF 解析不可用：未安装 PyMuPDF。") from exc
    try:
        pdf = pymupdf.open(str(source))
    except Exception as exc:
        raise InputNormalizationError("PDF 无法读取，请检查文件是否损坏。") from exc
    with pdf:
        if pdf.needs_pass:
            raise InputNormalizationError("PDF 已加密，请提供可直接读取的副本。")
        for index, page in enumerate(pdf, start=1):
            image_path = evidence_dir / f"page-{index:04d}.png"
            pixmap = page.get_pixmap(dpi=200, colorspace=pymupdf.csRGB, alpha=False)
            pixmap.save(str(image_path))
            record = {"page": index, "image": image_path.name,
                      "image_width": pixmap.width, "image_height": pixmap.height,
                      "pdf_width_points": page.rect.width, "pdf_height_points": page.rect.height}
            manifest["pages"].append(record)
            lines, items = _native_pdf_items(page)
            text = "\n".join(line["text"] for line in lines)
            image_coverage = sum(
                max(0, item["bbox"][2] - item["bbox"][0]) * max(0, item["bbox"][3] - item["bbox"][1])
                for item in page.get_image_info()
            ) / max(1, page.rect.width * page.rect.height)
            if len(re.sub(r"\s+", "", text)) >= 8 and "\ufffd" not in text and image_coverage < 0.5:
                record.update(method="pdf_text", coordinate_system="pdf_points", lines=lines, items=items)
            elif _is_blank_image(image_path):
                record.update(method="blank_page", coordinate_system="image_pixels", lines=[], items=[])
            else:
                record.update(method="pdf_ocr", coordinate_system="image_pixels")
                lines = _ocr_page(image_path, ocr_enabled)
                record.update(lines=lines, items=[{"kind": "paragraph", **line} for line in lines])
            record["text"] = "\n".join(line["text"] for line in record["lines"])
            yield record


def _read_images(source: Path, evidence_dir: Path, manifest: dict, ocr_enabled: bool):
    try:
        image = Image.open(source)
    except Exception as exc:
        raise InputNormalizationError("图片无法读取，请检查格式或文件是否损坏。") from exc
    with image:
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            frame = ImageOps.exif_transpose(image.copy()).convert("RGB")
            image_path = evidence_dir / f"page-{index + 1:04d}.png"
            frame.save(image_path)
            record = {"page": index + 1, "image": image_path.name, "width": frame.width, "height": frame.height,
                      "method": "image_ocr", "coordinate_system": "image_pixels"}
            manifest["pages"].append(record)
            lines = _ocr_page(image_path, ocr_enabled)
            record.update(lines=lines, items=[{"kind": "paragraph", **line} for line in lines], text="\n".join(line["text"] for line in lines))
            yield record


def _create_word_application():
    """Own a separate Word instance without consulting pywin32's gen_py cache."""
    import pythoncom
    from win32com.client import dynamic

    dispatch = pythoncom.CoCreateInstanceEx(
        "Word.Application", None, pythoncom.CLSCTX_LOCAL_SERVER, None, (pythoncom.IID_IDispatch,)
    )[0]
    return dynamic.Dispatch(dispatch, "Word.Application")


def _open_word_document(word, source: Path):
    """Open read-only; even dynamic Documents.Open otherwise uses gen_py for its return value."""
    import pythoncom
    import winerror
    from win32com.client import VARIANT, dynamic

    documents = word.Documents._oleobj_
    # IDispatch.Invoke needs an explicit missing-argument VARIANT. pythoncom.Missing
    # only works with typed invocation. Word's first 12 Open arguments end at Visible.
    missing = VARIANT(pythoncom.VT_ERROR, winerror.DISP_E_PARAMNOTFOUND)
    document = documents.Invoke(
        documents.GetIDsOfNames("Open"), 0, pythoncom.DISPATCH_METHOD, True,
        str(source), False, True, False,  # FileName, ConfirmConversions, ReadOnly, AddToRecentFiles
        missing, missing, missing, missing, missing, missing, missing, False,  # Visible
    )
    return dynamic.Dispatch(document, "Word.Document") if document is not None else None


def _convert_legacy_doc(source: Path, destination: Path) -> str:
    word_error = None
    if os.name == "nt":
        word = opened = None
        pythoncom = None
        update_links = None
        staging = None
        com_initialized = False
        try:
            import pythoncom

            # Word COM does not reliably support the long paths used by scoped
            # RD assets. Keep both Office-facing paths short and copy the final
            # bytes back with Python, which supports those destination paths.
            staging = tempfile.TemporaryDirectory(prefix="jtb-doc-")
            short_source = Path(staging.name) / "input.doc"
            short_destination = Path(staging.name) / "output.docx"
            shutil.copy2(source, short_source)
            pythoncom.CoInitialize()
            com_initialized = True
            word = _create_word_application()
            word.Visible = False
            word.DisplayAlerts = 0
            word.AutomationSecurity = 3
            update_links = word.Options.UpdateLinksAtOpen
            word.Options.UpdateLinksAtOpen = False
            opened = _open_word_document(word, short_source)
            if opened is None:
                raise InputNormalizationError("Word 未返回已打开的旧版 DOC 文档。")
            opened.SaveAs2(str(short_destination), FileFormat=16)
            if not short_destination.is_file():
                raise InputNormalizationError("Word 未输出转换后的 DOCX。")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(short_destination, destination)
            return "word_com"
        except Exception as exc:
            logger.exception("Word COM 旧版 DOC 转换失败，将检查本地 LibreOffice。")
            word_error = exc.with_traceback(None)
        finally:
            if opened is not None:
                try:
                    opened.Close(False)
                except Exception:
                    logger.warning("旧版 DOC 转换结束时关闭 Word 文档失败。", exc_info=True)
            if word is not None:
                if update_links is not None:
                    try:
                        word.Options.UpdateLinksAtOpen = update_links
                    except Exception:
                        logger.warning("旧版 DOC 转换结束时恢复 Word 选项失败。", exc_info=True)
                try:
                    word.Quit()
                except Exception:
                    logger.warning("旧版 DOC 转换结束时退出 Word 失败。", exc_info=True)
            if com_initialized:
                try:
                    # Dynamic COM methods can form reference cycles. Release the
                    # proxies while this thread's COM apartment still exists.
                    import gc
                    opened = word = None
                    gc.collect()
                    pythoncom.CoUninitialize()
                finally:
                    if staging is not None:
                        staging.cleanup()
            elif staging is not None:
                staging.cleanup()
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        profile = destination.parent / "libreoffice-profile"
        try:
            subprocess.run(
                [executable, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "docx",
                 "--outdir", str(destination.parent), str(source)],
                check=True, timeout=120, capture_output=True, creationflags=flags,
            )
            converted = destination.parent / f"{source.stem}.docx"
            if not converted.is_file():
                raise InputNormalizationError("LibreOffice 未输出转换后的 DOCX。")
            if converted != destination:
                converted.replace(destination)
            return "libreoffice"
        except (OSError, subprocess.SubprocessError) as exc:
            raise InputNormalizationError("旧版 DOC 转换失败，请另存为 DOCX 后上传。") from exc
    if word_error is not None and not isinstance(word_error, ImportError):
        raise InputNormalizationError(
            "本地 Word 转换组件调用失败，且未找到可用的 LibreOffice。请检查 Office 转换服务，或将原文件另存为 DOCX 后上传。"
        ) from word_error
    raise InputNormalizationError("旧版 DOC 转换不可用：需本机安装 Microsoft Word 或 LibreOffice；也可先另存为 DOCX。") from word_error


def normalize_input(path: str | Path, output_dir: str | Path, *, ocr_enabled: bool | None = None) -> NormalizedInput:
    """Return a readable DOCX and a local, immutable-source evidence trail.

    Every PDF/image result requires source-page review, regardless of OCR score.
    Unreadable/empty documents fail with an evidence manifest when available.
    Existing DOCX files are validated and passed through without rewriting.
    """
    source = Path(path).resolve()
    if not source.is_file():
        raise InputNormalizationError("输入文件不存在或不是普通文件。")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_INPUT_EXTENSIONS:
        raise InputNormalizationError("不支持该输入格式；请使用 DOCX、DOC、PDF 或 PNG/JPEG/TIFF/BMP/WebP 图片。")
    if suffix == ".docx":
        _load_docx(source)
        return NormalizedInput(source, source, "docx_passthrough", (), False)

    digest = _hash_file(source)
    evidence_dir = Path(output_dir).resolve() / f"{source.stem}-{digest[:12]}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / "source-evidence.json"
    destination = evidence_dir / "normalized.docx"
    manifest = {"schema_version": 1, "original_path": str(source), "source_sha256": digest,
                "normalized_path": str(destination), "requires_review": True, "status": "normalizing", "pages": []}
    enabled = ocr_enabled if ocr_enabled is not None else os.getenv("JTB_INPUT_OCR_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    warnings = []
    try:
        if suffix == ".doc":
            method = _convert_legacy_doc(source, destination)
            _load_docx(destination)
            warnings.append("旧版 DOC 已本地转换，请核对原文与转换文档的表格、编号及公式。")
        else:
            document = Document()
            document.core_properties.comments = f"原始文件：{source.name}；逐页依据：{evidence_path.name}"
            reader = _read_pdf if suffix == ".pdf" else _read_images
            for page in reader(source, evidence_dir, manifest, enabled):
                _write_page(document, page)
                if not page["text"].strip():
                    warnings.append(f"原文第 {page['page']} 页没有识别出文字，请核对原页图片。")
                low_confidence_count = sum(bool(line.get("low_confidence")) for line in page["lines"])
                if low_confidence_count:
                    warnings.append(f"原文第 {page['page']} 页有 {low_confidence_count} 行 OCR 置信度低于 {_OCR_REVIEW_CONFIDENCE}，须逐项核对。")
                _save_manifest(evidence_path, manifest)
            if not _document_has_text(document):
                raise InputNormalizationError("未提取到可用正文；原页已保留，不能将空白识别结果用于生成。")
            document.save(destination)
            methods = {page["method"] for page in manifest["pages"] if page["method"] != "blank_page"}
            method = next(iter(methods)) if len(methods) == 1 else "pdf_mixed"
            warnings.append("PDF/扫描件已转换为可编辑文字，原页图片及逐行依据已保留；须核对表格关系、编号、公式和识别结果后再用于正式生成。")
        if _hash_file(source) != digest:
            raise InputNormalizationError("转换期间原文件发生变化，请使用稳定副本重新导入。")
        manifest.update(status="needs_review", method=method, warnings=warnings)
        _save_manifest(evidence_path, manifest)
        return NormalizedInput(destination, source, method, tuple(warnings), True, evidence_path)
    except Exception as exc:
        manifest.update(status="failed", error=str(exc), warnings=warnings)
        _save_manifest(evidence_path, manifest)
        if isinstance(exc, InputNormalizationError):
            exc.evidence_path = evidence_path
            raise
        raise InputNormalizationError("输入文档转换失败，详细依据已保留。", evidence_path=evidence_path) from exc
