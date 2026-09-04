import asyncio
import json
from pathlib import Path

import pytest

from evm_bytecode_decompiler.ai.provider import OpenAICompatibleProvider, ProviderUsage
from evm_bytecode_decompiler.ai.schemas import (
    ContractSemanticReconciliation,
    FunctionSemanticAnnotation,
    PseudoFunction,
    PseudoStatement,
    ReviewResult,
)
from evm_bytecode_decompiler.ai.semantic_pass import run_function_semantics
from evm_bytecode_decompiler.cache.store import CacheStore
from evm_bytecode_decompiler.gigahorse.builtin import build_builtin_relations
from evm_bytecode_decompiler.inference.abi import infer_abi
from evm_bytecode_decompiler.inference.storage import infer_storage_layout
from evm_bytecode_decompiler.ir.builder import build_contract_ir
from evm_bytecode_decompiler.models.evidence import EvidenceSource
from evm_bytecode_decompiler.validation.hallucination import validate_pseudo_function

FIXTURE = Path(__file__).parent / "fixtures" / "erc20" / "runtime.hex"


def fixture_contract():
    code = bytes.fromhex(FIXTURE.read_text(encoding="ascii").strip())
    return build_contract_ir(
        build_builtin_relations(code),
        bytecode_sha256="a" * 64,
        bytecode_size=len(code),
        evidence_source=EvidenceSource.BYTECODE,
    )


class FakeProvider:
    provider_name = "fake"
    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0
        self.usage = ProviderUsage(self.provider_name, self.model)

    async def generate_structured(self, *, schema, **kwargs):
        self.calls += 1
        payload = json.loads(kwargs["prompt"])
        if schema is FunctionSemanticAnnotation:
            function_id = payload["function"]["id"]
            return FunctionSemanticAnnotation(function_id=function_id)
        if schema is ContractSemanticReconciliation:
            return ContractSemanticReconciliation()
        if schema is PseudoFunction:
            function = payload["function_ir"]
            body = [
                PseudoStatement(
                    kind="storage_write",
                    target="storage[unknown]",
                    value="unknown",
                    evidence_refs=[item["id"]],
                )
                for item in function["storage_writes"]
            ]
            body.extend(
                PseudoStatement(
                    kind=call["call_type"]
                    if call["call_type"] in {"call", "delegatecall", "staticcall"}
                    else "unknown",
                    call_type=call["call_type"],
                    evidence_refs=[call["id"]],
                )
                for call in function["external_calls"]
            )
            body.extend(
                PseudoStatement(kind="event", evidence_refs=[item["id"]])
                for item in function["events"]
            )
            body.extend(
                PseudoStatement(kind="revert", evidence_refs=[item["id"]])
                for item in function["reverts"]
            )
            return PseudoFunction(
                function_id=function["id"],
                selector=function["selector"],
                name="annotated",
                body=body,
            )
        if schema is ReviewResult:
            return ReviewResult()
        raise AssertionError(f"unexpected schema: {schema}")


def test_openai_compatible_provider_returns_structured_model_and_usage() -> None:
    requests: list[object] = []

    def transport(request, timeout: float) -> bytes:
        requests.append(request)
        return json.dumps(
            {
                "choices": [
                    {"message": {"content": '{"function_id":"f","summary":"known"}'}},
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }
        ).encode()

    provider = OpenAICompatibleProvider(
        api_key="secret",
        model="test-model",
        transport=transport,
    )
    result = asyncio.run(
        provider.generate_structured(
            system="system",
            prompt="prompt",
            schema=FunctionSemanticAnnotation,
        )
    )

    assert result.function_id == "f"
    assert provider.usage.input_tokens == 11
    assert provider.usage.output_tokens == 7
    assert requests[0].get_header("Authorization") == "Bearer secret"


def test_function_semantics_cache_and_evidence_validation(tmp_path: Path) -> None:
    contract = fixture_contract()
    provider = FakeProvider()
    cache = CacheStore(tmp_path / "cache")
    first = asyncio.run(
        run_function_semantics(
            [contract.functions[0]],
            provider=provider,
            abi_by_id={item.function_id: item for item in infer_abi(contract).functions},
            storage=infer_storage_layout(contract),
            cache=cache,
        )
    )
    second = asyncio.run(
        run_function_semantics(
            [contract.functions[0]],
            provider=provider,
            cache=cache,
        )
    )

    assert set(first.annotations) == {contract.functions[0].id}
    assert set(second.annotations) == {contract.functions[0].id}
    assert provider.calls == 1
    assert second.cache_hits == 1


def test_pseudocode_validation_rejects_missing_deterministic_operations() -> None:
    function = fixture_contract().functions[0]
    pseudo = PseudoFunction(function_id=function.id, selector=function.selector, name="transfer")
    review = validate_pseudo_function(function, pseudo)
    assert review.severity == "fail"
    assert review.missing_storage_writes

    valid = PseudoFunction(
        function_id=function.id,
        selector=function.selector,
        name="transfer",
        body=[
            PseudoStatement(
                kind="storage_write",
                target="storage_0",
                value="v_001a",
                evidence_refs=[function.storage_writes[0].id],
            )
        ],
    )
    assert validate_pseudo_function(function, valid).severity == "pass"


def test_invalid_provider_json_is_retried_only_within_limit() -> None:
    attempts = 0

    def transport(request, timeout: float) -> bytes:
        nonlocal attempts
        attempts += 1
        return b"{}"

    provider = OpenAICompatibleProvider(
        api_key="secret",
        model="test-model",
        retries=2,
        transport=transport,
    )
    with pytest.raises(Exception):
        asyncio.run(
            provider.generate_structured(
                system="system",
                prompt="prompt",
                schema=FunctionSemanticAnnotation,
            )
        )
    assert attempts == 3


def test_ai_pipeline_keeps_structured_output_and_report(tmp_path: Path) -> None:
    from evm_bytecode_decompiler.config import AIConfig, AppConfig, OutputConfig
    from evm_bytecode_decompiler.pipeline.decompile import decompile

    provider = FakeProvider()
    config = AppConfig(
        ai=AIConfig(cache_dir=tmp_path / "cache"),
        output=OutputConfig(root=tmp_path / "runs"),
    )
    result = decompile(
        str(FIXTURE),
        output_dir=tmp_path / "run",
        config=config,
        provider=provider,
        use_ai=True,
    )

    output = (result.run_dir / "output" / "decompiled.sol").read_text(encoding="utf-8")
    assert "function annotated" in output
    assert (result.run_dir / "semantics" / "synthesis.json").is_file()
    assert result.coverage.functions == 1.0
