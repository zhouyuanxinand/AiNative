"""从技术要求封面抽取：产品名称、使用单位、研制单位、密级等。"""
import re
import zipfile
from typing import Any, Dict

from lxml import etree

from .config import W
from .docx_io import get_para_text


def extract_cover_metadata(tech_path: str) -> Dict[str, str]:
    meta = {
        "product_name": "",
        "customer_unit": "",
        "developer_unit": "中航光电科技股份有限公司",
        "security_level": "",
        "doc_date": "",
    }
    with zipfile.ZipFile(tech_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))

    paras = [get_para_text(p).strip() for p in root.findall(f".//{{{W}}}p")]
    paras = [p for p in paras if p]

    for i, text in enumerate(paras[:30]):
        if re.match(r"^密级", text) and i + 1 < len(paras):
            meta["security_level"] = paras[i + 1].strip()
        if re.match(r"^名\s*称", text):
            rest = re.sub(r"^名\s*称[：:]\s*", "", text).strip()
            if rest:
                meta["product_name"] = rest
            elif i + 1 < len(paras):
                meta["product_name"] = paras[i + 1].strip()
        if "使用单位" in text:
            rest = re.sub(r".*使用单位[^：:]*[：:]\s*", "", text).strip()
            if rest:
                meta["customer_unit"] = rest
            elif i + 1 < len(paras) and "研制单位" not in paras[i + 1]:
                meta["customer_unit"] = paras[i + 1].strip()
        if "研制单位" in text:
            rest = re.sub(r".*研制单位[^：:]*[：:]\s*", "", text).strip()
            if rest:
                meta["developer_unit"] = rest
            elif i + 1 < len(paras):
                meta["developer_unit"] = paras[i + 1].strip()

    return meta
