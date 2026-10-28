"""New taskbook families keep their own historical failure evidence."""
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from jonhon_taskbook import failure_database as database_module
from jonhon_taskbook.failure_database import FailureDatabase
from jonhon_taskbook.failure_mode_matcher import match_failure_modes_with_audit
from src.controller import failure_database_controller as controller


NEW_PRODUCTS = {
    "optical_connector": "光连接器",
    "printed_board_assembly": "印制板组件",
    "optical_cable_assembly": "光缆组件",
    "liquid_cooling_connector": "液冷产品-液冷连接器",
    "chassis": "机箱",
    "mounting_plate": "安装板",
    "optical_distribution_box": "光布线箱",
    "mounting_frame": "安装架",
    "equipment_cabinet": "设备柜",
    "display_console": "显控台",
}
OLD_PRODUCTS = {
    "filter_connector": "滤波连接器",
    "cable_assembly": "线缆组件",
    "high_speed_backplane": "高速连接器-高速背板连接器",
    "liquid_cooling_chassis": "液冷产品-液冷机箱、冷板",
    "liquid_cooling_pipeline": "液冷产品-液冷管路",
}


def seed_workbook(tmp_path, names):
    path = tmp_path / "failures.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(["数据所属产品的产品名称", "所属型号", "故障描述", "故障原因", "设计改进措施"])
    for name in names:
        sheet.append([name, "TEST-01", "历史失效", "来源原因", "来源措施"])
    book.save(path)
    book.close()
    return path


def write_catalog(path, products):
    path.write_text(yaml.safe_dump({"product_types": {
        key: {"label": label} for key, label in products.items()
    }}, allow_unicode=True), encoding="utf-8")


@pytest.mark.parametrize("label,source_name,expected", [
    ("光连接器", "光纤连接器-光无源连接器-插芯", True),
    ("光纤连接器", "光连接器-插芯", True),
    ("印制板组件", "印制板组件-焊点", True),
    ("机箱", "机箱-紧固件", True),
    ("安装板", "安装板-紧固件", True),
    ("光布线箱", "光布线箱-箱体", True),
    ("安装架", "安装架-支撑件", True),
    ("设备柜", "设备柜-柜门", True),
    ("显控台", "显控台-面板", True),
    ("光缆组件", "光缆组件-光纤", True),
    ("机箱", "液冷产品-液冷机箱、冷板-紧固件", False),
    ("机箱", "电子设备-其他设备-机箱", False),
    ("安装板", "滤波连接器-滤波连接器-安装板", False),
    ("机箱", "光布线箱-箱体", False),
    ("机箱", "安装板-紧固件", False),
    ("安装板", "机箱-框架", False),
    ("光布线箱", "机箱-框架", False),
    ("机箱", "互连设备-设备机柜-机箱、机柜附件-紧固件", False),
    ("设备柜", "互连设备-设备机柜-机箱、机柜插件-印制板", False),
    ("印制板组件", "高速连接器-高速背板连接器-印制板", False),
    ("光缆组件", "线缆组件-线束装联件-导线", False),
    ("线缆组件", "光缆组件-光纤", False),
    ("光连接器", "光缆组件-光纤连接器", False),
    ("光缆组件", "光连接器-光缆组件", False),
    ("液冷产品-液冷连接器", "液冷产品-液冷连接器-密封件", True),
    ("液冷产品-液冷连接器", "液冷产品-液冷管路-液冷连接器", False),
    ("液冷产品-液冷连接器", "液冷产品-液冷机箱、冷板-接头", False),
    ("液冷产品-液冷连接器", "流体连接器-密封件", False),
    ("液冷产品-液冷管路", "液冷产品-液冷连接器-管路", False),
])
def test_source_product_paths_preserve_type_and_component_boundaries(tmp_path, label, source_name, expected):
    records, audit = match_failure_modes_with_audit(label, "TEST", seed_workbook(tmp_path, [source_name]))
    assert bool(records) is expected
    assert audit["rejected_counts"]["product_mismatch"] == (0 if expected else 1)


def test_seed_import_uses_same_boundaries_and_retains_unconfirmed_names(tmp_path):
    names = [
        "光纤连接器-光无源连接器-插芯",
        "液冷产品-液冷机箱、冷板-紧固件",
        "机箱-紧固件",
        "电子设备-其他设备-机箱",
        "互连设备-设备机柜-机箱、机柜附件-紧固件",
        "高速连接器-高速背板连接器-印制板",
        "印制板组件-焊点",
        "光布线箱-箱体",
        "线缆组件-导线",
        "光缆组件-光纤",
        "液冷产品-液冷连接器-密封件",
        "液冷产品-液冷管路-接头",
    ]
    catalog = tmp_path / "catalog.yaml"
    write_catalog(catalog, {**OLD_PRODUCTS, **NEW_PRODUCTS})
    store = FailureDatabase(tmp_path / "failures.sqlite3", seed_path=seed_workbook(tmp_path, names), catalog_path=catalog)
    assert [store.get(index)["product_type"] for index in range(1, len(names) + 1)] == [
        "optical_connector", "liquid_cooling_chassis", "chassis", "", "",
        "high_speed_backplane", "printed_board_assembly", "optical_distribution_box",
        "cable_assembly", "optical_cable_assembly", "liquid_cooling_connector", "liquid_cooling_pipeline",
    ]


def test_new_catalog_types_are_editable_and_generate_separate_failure_evidence(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yaml"
    write_catalog(catalog, {**OLD_PRODUCTS, **NEW_PRODUCTS})
    store = FailureDatabase(tmp_path / "failures.sqlite3", seed_path=seed_workbook(tmp_path, []), catalog_path=catalog)
    monkeypatch.setattr(controller, "get_failure_database", lambda: store)
    monkeypatch.setattr(database_module, "get_failure_database", lambda: store)
    application = FastAPI()
    application.include_router(controller.router)
    with TestClient(application) as client:
        options = client.get("/api/failures/options").json()["products"]
        assert {(row["id"], row["label"]) for row in options} >= set(NEW_PRODUCTS.items())
        for key, label in NEW_PRODUCTS.items():
            fields = {
                "product_type": key, "product_name": "已人工确认归属的产品",
                "product_series": "TEST", "product_model": "TEST-01", "failure_location": "部件",
                "failure_mode": f"{label}的故障", "failure_analysis": "记录原因", "improvement": "改进经验",
            }
            response = client.post("/api/failures", json=fields)
            assert response.status_code == 200, response.text
        for key, label in NEW_PRODUCTS.items():
            rows, _ = match_failure_modes_with_audit(label, "TEST")
            assert len(rows) == 1
            assert rows[0]["failure_mode"] == f"{label}的故障"
            response = client.get("/api/failures", params={"product_type": key})
            assert response.status_code == 200 and response.json()["total"] == 1
            row = response.json()["items"][0]
            fields = {field: row[field] for field in database_module.FIELDS}
            response = client.put(f"/api/failures/{row['id']}", json={
                **fields, "improvement": "修订后的经验", "expected_version": row["version"],
            })
            assert response.status_code == 200, response.text
            assert match_failure_modes_with_audit(label, "TEST")[0][0]["reliability_design_method"] == "修订后的经验"
            response = client.delete(f"/api/failures/{row['id']}?expected_version=2")
            assert response.status_code == 200, response.text
            assert match_failure_modes_with_audit(label, "TEST")[0] == []


def test_added_catalog_recognizes_old_optical_evidence_without_rewriting_records(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yaml"
    write_catalog(catalog, OLD_PRODUCTS)
    seed = seed_workbook(tmp_path, ["光纤连接器-光无源连接器-插芯"])
    store = FailureDatabase(tmp_path / "failures.sqlite3", seed_path=seed, catalog_path=catalog)
    before = store.snapshot()
    assert before[0][0]["product_type"] == ""
    write_catalog(catalog, {**OLD_PRODUCTS, **NEW_PRODUCTS})
    restarted = FailureDatabase(store.path, seed_path=seed, catalog_path=catalog)
    monkeypatch.setattr(database_module, "get_failure_database", lambda: restarted)
    rows, audit = match_failure_modes_with_audit("光连接器", "TEST")
    assert len(rows) == 1 and audit["accepted_count"] == 1
    assert restarted.snapshot() == before


@pytest.mark.parametrize("label", ["光缆组件", "液冷产品-液冷连接器"])
def test_new_template_families_do_not_infer_unconfirmed_series_aliases(tmp_path, label):
    seed = seed_workbook(tmp_path, [])
    from openpyxl import load_workbook
    book = load_workbook(seed)
    book.active.append([f"{label}-连接部位", "J599/20", "不得借用的历史故障", "原因", "措施"])
    book.active.append([f"{label}-连接部位", "J599L-01", "本系列历史故障", "本系列原因", "本系列措施"])
    book.save(seed)
    book.close()
    records, audit = match_failure_modes_with_audit(label, "J599L", seed)
    assert [record["failure_mode"] for record in records] == ["本系列历史故障"]
    assert audit["rejected_counts"]["series_mismatch"] == 1
