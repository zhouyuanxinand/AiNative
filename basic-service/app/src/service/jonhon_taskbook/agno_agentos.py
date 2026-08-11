from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

def create_agentos_app(root: str | Path, *, model: Any | None = None):
    """Create optional AgentOS tools around the existing controlled pipeline."""
    if model is None:
        raise ValueError('A company-approved AGNO model must be supplied explicitly; default models are disabled.')
    try:
        from agno.agent import Agent
        from agno.os import AgentOS
        from agno.team import Team
    except ImportError as exc:
        raise RuntimeError('Optional AGNO integration requires the company-approved agno package.') from exc
    project_root = Path(root).resolve()
    pipeline = project_root / 'pipeline.py'
    def _existing_file(value: str, label: str) -> Path:
        path = Path(value).resolve()
        if not path.is_file():
            raise ValueError(f'{label} does not exist: {path}')
        return path
    def inspect_delivery_contract() -> dict[str, Any]:
        return {
            'entrypoint': str(pipeline),
            'body_generation': 'prohibited',
            'routing': 'copy_exact_only',
            'required_equivalence_inputs': ['baseline_docx', 'baseline_evidence_json'],
        }
    def validate_equivalence_inputs(
        tech: str, spec: str, template: str, profile: str, category_mapping: str,
        baseline_docx: str, baseline_evidence_json: str,
    ) -> dict[str, str]:
        files = {
            'tech': _existing_file(tech, 'tech'), 'spec': _existing_file(spec, 'spec'),
            'template': _existing_file(template, 'template'), 'profile': _existing_file(profile, 'profile'),
            'category_mapping': _existing_file(category_mapping, 'category_mapping'),
            'baseline_docx': _existing_file(baseline_docx, 'baseline_docx'),
            'baseline_evidence_json': _existing_file(baseline_evidence_json, 'baseline_evidence_json'),
        }
        return {name: str(path) for name, path in files.items()}
    def run_equivalence_checked_pipeline(
        tech: str, spec: str, template: str, output: str, profile: str, category_mapping: str,
        baseline_docx: str, baseline_evidence_json: str, product_type: str, product_label: str,
        product_domain: str, development_process: str = '全新', product_series: str = '',
        organization_scope: str = 'non_central_research', cover_phase: str = '',
    ) -> dict[str, Any]:
        values = validate_equivalence_inputs(tech, spec, template, profile, category_mapping, baseline_docx, baseline_evidence_json)
        output_path = Path(output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(pipeline), '--tech', values['tech'], '--spec', values['spec'],
            '--tpl', values['template'], '--out', str(output_path), '--profile', values['profile'],
            '--category-mapping', values['category_mapping'], '--baseline', values['baseline_docx'],
            '--baseline-json', values['baseline_evidence_json'], '--fail-on-regression',
            '--product-type', product_type, '--product-label', product_label, '--product-domain', product_domain,
            '--development-process', development_process, '--product-series', product_series,
            '--organization-scope', organization_scope]
        if cover_phase:
            command.extend(['--cover-phase', cover_phase])
        completed = subprocess.run(command, cwd=project_root, capture_output=True)
        regression_path = output_path.with_suffix('.regression.json')
        delivery_path = output_path.with_suffix('.delivery_gate.json')
        def read_json(path: Path) -> dict[str, Any]:
            try:
                return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            except (OSError, json.JSONDecodeError):
                return {}
        regression = read_json(regression_path)
        delivery = read_json(delivery_path)
        return {
            'exit_code': completed.returncode, 'output': str(output_path),
            'regression_report': str(regression_path), 'regression_passed': regression.get('passed') is True,
            'delivery_gate': str(delivery_path), 'delivery_approved': delivery.get('approved_for_delivery') is True,
            'approved': completed.returncode == 0 and regression.get('passed') is True and delivery.get('approved_for_delivery') is True,
        }
    agent = Agent(
        name='受控任务书回归代理', model=model, telemetry=False,
        tools=[inspect_delivery_contract, validate_equivalence_inputs, run_equivalence_checked_pipeline],
        instructions=['只调用受控工具。不得生成、改写或总结任务书正文。缺少任一基线输入时不得执行。'],
    )
    team = Team(
        name='研制任务书受控交付 Team', model=model, telemetry=False, members=[agent],
        tools=[inspect_delivery_contract, validate_equivalence_inputs, run_equivalence_checked_pipeline],
        instructions=['仅在等效性回归和交付门禁均通过时返回 approved=true。'],
    )
    return AgentOS(name='研制任务书 AgentOS', teams=[team], telemetry=False).get_app()
