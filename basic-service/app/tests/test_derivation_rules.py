from concurrent.futures import ThreadPoolExecutor

import pytest

from jonhon_taskbook.derivation_rules import DerivationRuleRegistry


def create(registry, key="create"):
    return registry.create(actor="verified_designer", target={"product_type": "target_product", "domain": "military"},
                           operations=[{"operation": "add_after", "anchor_slot": "slot-1", "new_title": "专业方法"}],
                           asset_bindings={"profile_sha256": "a" * 64, "mapping_sha256": "b" * 64},
                           reason="固定目标适用范围", idempotency_key=key)


def test_rule_approval_and_publication_are_separate_server_facts(tmp_path):
    registry = DerivationRuleRegistry(tmp_path)
    draft = create(registry)
    assert draft["status"] == "draft" and "approval" not in draft
    assert create(registry) == draft
    with pytest.raises(ValueError, match="审核"):
        registry.publish(draft["id"], expected_digest=draft["digest"], actor="publisher", idempotency_key="badpublish")
    approved = registry.review(draft["id"], expected_digest=draft["digest"], actor="verified_reviewer", approved=True,
                               reason="目标资料及差异已复核", idempotency_key="review")
    assert approved["approval"]["actor"] == "verified_reviewer"
    published = registry.publish(draft["id"], expected_digest=approved["digest"], actor="verified_publisher", idempotency_key="publish")
    assert published["status"] == "published"
    assert DerivationRuleRegistry(tmp_path).get(draft["id"]) == published


def test_rule_cas_and_idempotency_reject_different_write(tmp_path):
    registry = DerivationRuleRegistry(tmp_path)
    draft = create(registry)
    approved = registry.review(draft["id"], expected_digest=draft["digest"], actor="reviewer", approved=True, reason="ok", idempotency_key="review")
    with pytest.raises(ValueError, match="冲突"):
        registry.review(draft["id"], expected_digest=draft["digest"], actor="other", approved=False, reason="reject", idempotency_key="review")
    with pytest.raises(ValueError, match="版本冲突"):
        registry.publish(draft["id"], expected_digest=draft["digest"], actor="publisher", idempotency_key="publish")
    assert registry.get(draft["id"]) == approved


def test_two_reviews_have_exactly_one_cas_winner(tmp_path):
    registry = DerivationRuleRegistry(tmp_path)
    draft = create(registry)
    def review(index):
        try:
            return registry.review(draft["id"], expected_digest=draft["digest"], actor=str(index), approved=True, reason="ok", idempotency_key=str(index))
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(review, [1, 2]))
    assert sum(r is not None for r in results) == 1
