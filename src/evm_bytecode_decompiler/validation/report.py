import json
from collections.abc import Iterable

from ..gigahorse.runner import GigahorseResult
from ..inference.abi import InferredABI
from ..inference.storage import StorageLayoutEntry
from ..models.input import NormalizedBytecode
from ..models.ir import ContractIR
from .coverage import ValidationCoverage


def render_report(
    normalized: NormalizedBytecode,
    contract: ContractIR,
    abi: InferredABI,
    storage: Iterable[StorageLayoutEntry],
    coverage: ValidationCoverage,
    gigahorse: GigahorseResult,
) -> str:
    storage_items = list(storage)
    function_names = [item.name for item in abi.functions]
    calls = sorted({call.call_type for call in contract.external_calls})
    statement_count = sum(
        len(block.statements) for item in contract.functions for block in item.blocks
    )
    lines = [
        "# EVM Bytecode Decompiler Decompilation Report",
        "",
        "This output is reconstructed from bytecode and is not verified source code.",
        "",
        "## Input",
        "",
        f"- kind: `{normalized.metadata.kind.value}`",
        f"- target: `{normalized.metadata.target}`",
        f"- SHA-256: `{normalized.metadata.bytecode_sha256}`",
        f"- size: `{normalized.metadata.bytecode_size}` bytes",
        f"- chain: `{normalized.metadata.chain or '<not supplied>'}`",
        f"- block: `{normalized.metadata.block or '<latest>'}`",
        "",
        "## Analysis Environment",
        "",
        f"- backend: `{gigahorse.backend}` ({gigahorse.version})",
        f"- commit: `{gigahorse.commit}`",
        f"- status: `{gigahorse.effective_status}`",
        f"- completeness: `{gigahorse.completeness}`",
        *[f"- warning: {warning}" for warning in gigahorse.warnings],
        "",
        "## Contract Overview",
        "",
        f"- functions: `{len(contract.functions)}`",
        f"- basic blocks: `{sum(len(item.blocks) for item in contract.functions)}`",
        f"- statements: `{statement_count}`",
        "",
        "## Recovered Functions",
        "",
        *[
            f"- `{function.selector or '<fallback>'}` → `{name}`"
            for function, name in zip(contract.functions, function_names)
        ],
        "",
        "## Storage Model",
        "",
        *[
            f"- `{item.name}` ({item.kind}, confidence `{item.confidence:.2f}`)"
            for item in storage_items
        ],
        "- none observed" if not storage_items else "",
        "",
        "## External Calls",
        "",
        *[f"- `{call}`" for call in calls],
        "- none observed" if not calls else "",
        "",
        "## Events and Reverts",
        "",
        f"- events: `{len(contract.events)}`",
        f"- reverts: `{len(contract.reverts)}`",
        "",
        "## Unresolved Semantics",
        "",
        "- Names, types, and operation meanings remain generic unless deterministic evidence "
        "supports them.",
        "- The built-in fallback does not replace full Gigahorse dataflow analysis.",
        "",
        "## Validation Coverage",
        "",
        "```json",
        json.dumps(coverage.model_dump(mode="json"), indent=2),
        "```",
        "",
        f"- analysis completeness: `{coverage.analysis_completeness:.2f}`",
        "- operation coverage: `"
        f"{coverage.operation_coverage if coverage.operation_coverage is not None else 'n/a'}`",
        f"- unresolved statements: `{coverage.unresolved_statements}`",
        f"- unassigned blocks: `{coverage.unassigned_blocks}`",
        "",
        "## Semantic Overlay",
        "",
        "- Deterministic analysis does not call an AI provider.",
        "- Optional agent annotations are stored separately under `agent/` and are not "
        "part of this report.",
        "",
        "## Limitations",
        "",
        "- Solidity-like output is semantic pseudocode and may not compile.",
        "- No source, storage values, transaction traces, or vulnerability classification "
        "are inferred here.",
        "",
    ]
    return "\n".join(lines)
