import json
from collections.abc import Iterable
from typing import Any


def deterministic_metrics(contract: Any) -> dict[str, int]:
    return {
        "functions": len(contract.functions),
        "blocks": sum(len(function.blocks) for function in contract.functions),
        "statements": sum(
            len(block.statements) for function in contract.functions for block in function.blocks
        ),
        "storage_reads": sum(item.access == "read" for item in contract.storage),
        "storage_writes": sum(item.access == "write" for item in contract.storage),
        "external_calls": len(contract.external_calls),
        "events": len(contract.events),
        "reverts": len(contract.reverts),
    }


def regression_failures(results: Iterable[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for item in results:
        if item.get("status") != "ok":
            continue
        metrics = item.get("metrics", {})
        if metrics.get("functions", 0) < 1:
            failures.append(f"{item['name']}: no function recovered")
    return failures


def render_benchmark_report(results: Iterable[dict[str, Any]]) -> str:
    entries = list(results)
    successes = sum(item.get("status") == "ok" for item in entries)
    lines = [
        "# EVM Bytecode Decompiler Benchmark",
        "",
        f"Successful fixtures: `{successes}/{len(entries)}`",
        "",
        "| Fixture | Status | Functions | Storage writes | Calls | Events | Reverts |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in entries:
        metrics = item.get("metrics", {})
        lines.append(
            f"| `{item['name']}` | `{item['status']}` | {metrics.get('functions', 0)} | "
            f"{metrics.get('storage_writes', 0)} | {metrics.get('external_calls', 0)} | "
            f"{metrics.get('events', 0)} | {metrics.get('reverts', 0)} |"
        )
    lines.extend(
        [
            "",
            "Metrics are deterministic structural observations; readability and AI semantics "
            "are not folded into these scores.",
            "",
        ]
    )
    return "\n".join(lines)


def write_results(path: Any, results: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps({"fixtures": results}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
