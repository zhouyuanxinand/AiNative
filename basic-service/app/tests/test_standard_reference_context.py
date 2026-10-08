"""Reference-list labels and structural context, without promoting test prose."""
import pytest

from jonhon_taskbook import standard_references as references


@pytest.mark.parametrize(("text", "expected"), [
    ("通用基础标准：GB/T 11313.1-2013《射频连接器 第1部分：总规范 一般要求和试验方法》",
     "GB/T 11313.1-2013《射频连接器 第1部分：总规范 一般要求和试验方法》"),
    ("产品专用标准：GB/T 11313.15-2018《射频连接器 第15部分：SMA型射频同轴连接器》",
     "GB/T 11313.15-2018《射频连接器 第15部分：SMA型射频同轴连接器》"),
    ("滤波测试标准：GB/T 5095.2307-2021《电子设备用机电元件 基本试验规程及测量方法 第23-7部分：屏蔽和滤波试验》",
     "GB/T 5095.2307-2021《电子设备用机电元件 基本试验规程及测量方法 第23-7部分：屏蔽和滤波试验》"),
    ("可靠性试验标准：GJB 360B《电子及电气元件试验方法》",
     "GJB 360B《电子及电气元件试验方法》"),
])
def test_explicit_reference_label_preserves_original_code_and_title(text, expected):
    assert references.extract_standard_references(text) == [expected]


@pytest.mark.parametrize("heading", ["1.3 执行标准", "规范性引用文件", "第三章 适用的法律法规要求", "二、引用标准："])
def test_only_explicit_reference_headings_activate_context(heading):
    assert references.is_reference_heading(heading)


@pytest.mark.parametrize("heading", ["材料试验", "电气性能", "试验方法", "按执行标准进行检测", "执行标准：GB/T 11313 产品应通过检验"])
def test_technical_headings_and_sentences_do_not_activate_reference_context(heading):
    assert not references.is_reference_heading(heading)


def test_reference_context_allows_short_descriptive_list_label():
    text = "通用基础 GB/T 11313.1-2013《射频连接器总规范》"
    assert references.extract_standard_references(text) == []
    assert references.extract_standard_references(text, reference_context=True) == [
        "GB/T 11313.1-2013《射频连接器总规范》"
    ]


@pytest.mark.parametrize("reference_context", [False, True])
@pytest.mark.parametrize("text", [
    "按GB/T 5095.2307-2021进行滤波测试，衰减应满足要求。",
    "试验方法：按GJB 360B开展振动试验。",
    "按适用标准GB/T 11313进行检测，阻抗为50Ω。",
])
def test_test_instructions_are_not_reference_rows(text, reference_context):
    assert references.extract_standard_references(text, reference_context=reference_context) == []


def test_numbered_multi_standard_list_still_splits_exact_entries():
    assert references.extract_standard_references(
        "1.3 适用标准：GB/T 11313《射频同轴连接器通用规范》、GJB 6815《军用射频连接器通用规范》。"
    ) == ["GB/T 11313《射频同轴连接器通用规范》", "GJB 6815《军用射频连接器通用规范》"]
