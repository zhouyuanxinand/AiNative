"""Local governed difference rules. Approval and publication are server facts."""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .template_derivation import digest
from .template_outline_editor import ALLOWED_OPERATIONS, _clean_title


class DerivationRuleRegistry:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "derivation_rules.sqlite3"
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS receipts(key TEXT PRIMARY KEY, request_digest TEXT NOT NULL, body TEXT NOT NULL)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _actor(actor):
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("规则治理需要服务器验证的操作者")
        return actor.strip()

    def _write(self, request, key, apply):
        if not isinstance(key, str) or not key.strip():
            raise ValueError("规则写入必须提供幂等键")
        fingerprint = digest(request)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT request_digest,body FROM receipts WHERE key=?", (key,)).fetchone()
            if previous:
                if previous[0] != fingerprint:
                    raise ValueError("规则幂等键冲突")
                return json.loads(previous[1])
            rule = apply(db)
            rule["digest"] = digest({k: v for k, v in rule.items() if k != "digest"})
            encoded = json.dumps(rule, ensure_ascii=False)
            db.execute("INSERT OR REPLACE INTO rules(id,body) VALUES(?,?)", (rule["id"], encoded))
            db.execute("INSERT INTO receipts VALUES(?,?,?)", (key, fingerprint, encoded))
            return rule

    def create(self, *, actor, target, operations, asset_bindings, reason, idempotency_key):
        actor = self._actor(actor)
        if not isinstance(target, dict) or set(target) != {"product_type", "domain"} or not all(isinstance(v, str) and v.strip() for v in target.values()):
            raise ValueError("差异规则必须固定唯一目标产品及领域")
        if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
            raise ValueError("差异规则缺少结构操作")
        allowed = {"operation", "target_slot", "anchor_slot", "new_title", "reason"}
        normalized = []
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) - allowed or operation.get("operation") not in ALLOWED_OPERATIONS:
                raise ValueError("差异规则含不支持的操作或字段")
            if any(not isinstance(v, str) for v in operation.values()):
                raise ValueError("章节差异操作属性必须为文本")
            action = operation["operation"]
            item = {"operation": action, "reason": operation.get("reason", "")[:160]}
            for key, required in (("target_slot", action in {"rename", "delete"} or action.startswith("move_")),
                                   ("anchor_slot", action.startswith(("add_", "move_")))):
                if required:
                    if not operation.get(key, "").strip():
                        raise ValueError("差异操作缺少目标或锚点章节")
                    item[key] = operation[key].strip()
            if action == "rename" or action.startswith("add_"):
                title = _clean_title(operation.get("new_title", ""))
                if not title or len(title) > 80:
                    raise ValueError("差异操作的目标标题无效")
                item["new_title"] = title
            normalized.append(item)
        operations = normalized
        if not isinstance(asset_bindings, dict) or set(asset_bindings) != {"profile_sha256", "mapping_sha256"} or any(not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v) for v in asset_bindings.values()):
            raise ValueError("规则必须固定目标 Profile 和 mapping 摘要")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError("差异规则缺少适用依据")
        request = {"action": "create", "actor": actor, "target": target, "operations": operations,
                   "asset_bindings": asset_bindings, "reason": reason}
        def apply(db):
            return {"id": uuid.uuid4().hex, "version": 1, "status": "draft", "applicability": deepcopy(target),
                    "operations": deepcopy(operations), "asset_bindings": deepcopy(asset_bindings), "reason": reason,
                    "created_by": actor, "created_at": datetime.now(timezone.utc).isoformat()}
        return self._write(request, idempotency_key, apply)

    def get(self, rule_id):
        with self._connect() as db:
            row = db.execute("SELECT body FROM rules WHERE id=?", (rule_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("差异规则不存在")
        return json.loads(row[0])

    def list(self):
        with self._connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM rules ORDER BY id")]

    def _transition(self, rule_id, *, expected_digest, actor, action, idempotency_key, reason=None, approved=None):
        actor = self._actor(actor)
        request = {"rule_id": rule_id, "expected_digest": expected_digest, "actor": actor, "action": action,
                   "reason": reason, "approved": approved}
        def apply(db):
            row = db.execute("SELECT body FROM rules WHERE id=?", (rule_id,)).fetchone()
            if row is None:
                raise FileNotFoundError("差异规则不存在")
            rule = json.loads(row[0])
            if not expected_digest or rule["digest"] != expected_digest:
                raise ValueError("规则版本冲突")
            if action == "review":
                if rule["status"] not in {"draft", "rejected"} or not str(reason or "").strip() or not isinstance(approved, bool):
                    raise ValueError("规则当前状态或审核意见无效")
                rule["status"] = "approved" if approved else "rejected"
                rule["approval"] = {"actor": actor, "reason": reason, "approved": approved, "at": datetime.now(timezone.utc).isoformat()}
            else:
                if rule["status"] != "approved":
                    raise ValueError("规则必须独立审核后才能发布")
                rule["status"] = "published"
                rule["publication"] = {"actor": actor, "at": datetime.now(timezone.utc).isoformat()}
            return rule
        return self._write(request, idempotency_key, apply)

    def review(self, rule_id, *, expected_digest, actor, approved, reason, idempotency_key):
        return self._transition(rule_id, expected_digest=expected_digest, actor=actor, action="review",
                                approved=approved, reason=reason, idempotency_key=idempotency_key)

    def publish(self, rule_id, *, expected_digest, actor, idempotency_key):
        return self._transition(rule_id, expected_digest=expected_digest, actor=actor, action="publish", idempotency_key=idempotency_key)
