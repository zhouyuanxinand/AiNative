from src.service.rd_platform.catalog import default_nodes, get_catalog


def test_catalog_preview_uses_the_same_default_plan_as_pulled_workpackages():
    catalog = get_catalog()
    for definition in catalog["workpackage_definitions"]:
        assert definition["nodes"] == default_nodes(definition["id"])
        assert [node["action_id"] for node in definition["nodes"]] == definition["required_actions"]


def test_modifying_a_catalog_preview_cannot_change_later_plans():
    catalog = get_catalog()
    catalog["workpackage_definitions"][0]["nodes"][1]["depends_on"].clear()
    catalog["workpackage_definitions"][0]["required_actions"].clear()
    assert get_catalog()["workpackage_definitions"][0]["nodes"] == default_nodes("taskbook")
    assert get_catalog()["workpackage_definitions"][0]["required_actions"]
