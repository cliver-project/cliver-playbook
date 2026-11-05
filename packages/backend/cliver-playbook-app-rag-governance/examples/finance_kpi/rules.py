"""Intent rules for the finance KPI reference scenario.

These are the rules a project owner would confirm in the rule review
screen. They are versioned data: the demo seeds them into the rule store
and evaluates the golden set against the same values. Priorities are the
routing decision — a 90-day aging question mentions "应收" too, so the
specific intent must outrank the general overview.
"""

from __future__ import annotations

from typing import Any

from cliver_playbook.app.rag_governance.rules.schema import IntentRule


def _rule(
    intent: str,
    *,
    description: str,
    keywords: list[str],
    priority: int,
    strategy: str = "retrieval",
    tools: list[str] | None = None,
    scope: dict[str, Any] | None = None,
    refusal: str | None = None,
    top_k: int = 20,
    rerank_top_k: int = 10,
) -> IntentRule:
    payload: dict[str, Any] = {
        "intent": intent,
        "description": description,
        "priority": priority,
        "classifier": {
            "kind": "keyword-regex",
            "config": {"keywords": keywords, "threshold": 0.5},
        },
        "scope": scope or {},
        "retrieval": {
            "mode": "sparse",
            "top_k": top_k,
            "rerank_top_k": rerank_top_k,
        },
        "strategy": strategy,
        "tools": tools or [],
        "snapshot_fallback": False,
        "refusal": {"message": refusal} if refusal else None,
    }
    return IntentRule.model_validate(payload)


_POLICY_DOC_TYPES = ["policy", "metric_definition", "report"]

FINANCE_RULES: tuple[IntentRule, ...] = (
    _rule(
        "out_of_scope",
        description="Write or ERP mutation requests; the governed query surface is read-only.",
        keywords=["核销", "修改凭证", "删除", "审核", "反审核", "作废", "冲销"],
        priority=200,
        strategy="none",
        refusal=(
            "该问题涉及 ERP 写操作或超出财务指标问答范围；治理查询仅提供只读数据，"
            "无法执行核销、修改、审核或作废。"
        ),
    ),
    _rule(
        "receivables_aging",
        description="Receivables aging and the 90+ warning.",
        keywords=["应收 90 天", "90 天", "90天", "账龄", "逾期", "预警", "应收占比"],
        priority=160,
        strategy="agentic",
        tools=["finance_receivables_aging"],
        scope={"field": "doc_type", "op": "in", "value": ["policy"]},
    ),
    _rule(
        "budget_variance",
        description="Budget attainment and its explanation.",
        keywords=["预算", "达成", "差异", "差在哪里", "预算执行"],
        priority=150,
        strategy="tools",
        tools=["finance_kpi_snapshot"],
    ),
    _rule(
        "financial_overview",
        description="One-screen operating analysis for the latest closed period.",
        keywords=[
            "经营情况",
            "本月经营",
            "一屏",
            "营收",
            "毛利",
            "净利",
            "应收",
            "应付",
            "流动资金",
            "资产负债率",
        ],
        priority=140,
        strategy="agentic",
        tools=["finance_kpi_snapshot", "finance_receivables_aging"],
    ),
    _rule(
        "policy_question",
        description="Accounting policy, metric definition and report questions.",
        keywords=["口径", "收入确认", "坏账", "计提", "制度", "政策", "薪酬", "披露"],
        priority=100,
        scope={"field": "doc_type", "op": "in", "value": _POLICY_DOC_TYPES},
    ),
    _rule(
        "fallback",
        description="No rule recognized the question; refuse instead of guessing.",
        keywords=[],
        priority=0,
        strategy="none",
        refusal="该问题不在当前知识库与只读工具范围内，无法给出可靠答案。",
    ),
)
