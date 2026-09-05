import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from evm_bytecode_decompiler.agent.artifacts import render_agent
from evm_bytecode_decompiler.agent.context import build_contract_context, build_function_context
from evm_bytecode_decompiler.agent.validation import apply_proposal, validate_proposal
from evm_bytecode_decompiler.cli import app
from evm_bytecode_decompiler.config import AppConfig, GigahorseConfig, OutputConfig
from evm_bytecode_decompiler.errors import AnnotationError
from evm_bytecode_decompiler.models.annotations import AnnotationProposal, FunctionAnnotation
from evm_bytecode_decompiler.pipeline.artifacts import read_manifest
from evm_bytecode_decompiler.pipeline.decompile import decompile

FIXTURE = Path(__file__).parent / "fixtures" / "erc20" / "runtime.hex"


def _run(tmp_path: Path) -> Path:
    result = decompile(
        str(FIXTURE),
        output_dir=tmp_path / "run",
        config=AppConfig(
            gigahorse=GigahorseConfig(backend="builtin"),
            output=OutputConfig(root=tmp_path),
        ),
    )
    return result.run_dir


def _proposal(run_dir: Path, *, annotation: FunctionAnnotation | None = None) -> AnnotationProposal:
    manifest = read_manifest(run_dir)
    function_id = next(
        iter(json.loads((run_dir / "ir" / "contract.json").read_text())["functions"])
    )["id"]
    # The canonical function model is easier to use for a stable evidence reference.
    contract = json.loads((run_dir / "ir" / "contract.json").read_text())
    function = next(item for item in contract["functions"] if item["id"] == function_id)
    evidence = function["blocks"][0]["statements"][0]["id"]
    value = annotation or FunctionAnnotation(
        summary="evidence-backed summary", evidence_refs=[evidence]
    )
    return AnnotationProposal(
        run_fingerprint=str(manifest["fingerprint"]),
        functions={function_id: value},
    )


def test_deterministic_fingerprint_ignores_openai_environment(tmp_path: Path, monkeypatch) -> None:
    config = AppConfig(
        gigahorse=GigahorseConfig(backend="builtin"),
        output=OutputConfig(root=tmp_path),
    )
    first = decompile(str(FIXTURE), output_dir=tmp_path / "first", config=config)
    monkeypatch.setenv("OPENAI_API_KEY", "different-secret")
    monkeypatch.setenv("OPENAI_MODEL", "different-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid")
    second = decompile(str(FIXTURE), output_dir=tmp_path / "second", config=config)
    assert (
        read_manifest(first.run_dir)["fingerprint"] == read_manifest(second.run_dir)["fingerprint"]
    )


def test_context_exposes_partial_builtin_backend(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    context = build_contract_context(run_dir)
    assert context["backend"]["name"] == "builtin"
    assert context["backend"]["completeness"] == "partial"
    assert context["truncated"] is False
    function_context = build_function_context(run_dir, "0xa9059cbb", max_statements=1)
    assert function_context["scope"] == "function"
    assert function_context["function"]["selector"] == "0xa9059cbb"


def test_annotation_validation_rejects_identity_and_evidence_errors(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    valid = _proposal(run_dir)
    assert validate_proposal(run_dir, valid) == valid

    unknown_function = valid.model_copy(
        update={"functions": {"missing": valid.functions[next(iter(valid.functions))]}}
    )
    with pytest.raises(AnnotationError, match="unknown function"):
        validate_proposal(run_dir, unknown_function)

    function_id = next(iter(valid.functions))
    bad_selector = valid.model_copy(
        update={
            "functions": {
                function_id: valid.functions[function_id].model_copy(
                    update={"selector": "0xdeadbeef"}
                )
            }
        }
    )
    with pytest.raises(AnnotationError, match="selector"):
        validate_proposal(run_dir, bad_selector)

    bad_evidence = valid.model_copy(
        update={
            "functions": {
                function_id: valid.functions[function_id].model_copy(
                    update={"evidence_refs": ["missing"]}
                )
            }
        }
    )
    with pytest.raises(AnnotationError, match="evidence"):
        validate_proposal(run_dir, bad_evidence)

    wrong_run = valid.model_copy(update={"run_fingerprint": "0" * 64})
    with pytest.raises(AnnotationError, match="run_fingerprint"):
        validate_proposal(run_dir, wrong_run)

    extra = valid.model_dump(mode="json")
    extra["unexpected"] = True
    with pytest.raises(AnnotationError, match="invalid annotation"):
        validate_proposal(run_dir, extra)

    invalid_confidence = valid.model_dump(mode="json")
    invalid_confidence["functions"][function_id]["name_confidence"] = 2
    with pytest.raises(AnnotationError, match="invalid annotation"):
        validate_proposal(run_dir, invalid_confidence)


def test_apply_and_render_keep_canonical_artifacts_immutable(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    manifest = read_manifest(run_dir)
    before = {
        relative: hashlib.sha256((run_dir / relative).read_bytes()).hexdigest()
        for relative in manifest["artifacts"]
    }
    proposal = _proposal(run_dir)
    apply_proposal(run_dir, proposal)
    output, report = render_agent(run_dir)
    assert output.is_file() and report.is_file()
    after = {
        relative: hashlib.sha256((run_dir / relative).read_bytes()).hexdigest()
        for relative in manifest["artifacts"]
    }
    assert before == after
    assert (run_dir / "agent" / "annotations.json").is_file()
    assert "RECONSTRUCTED / UNVERIFIED" in output.read_text(encoding="utf-8")


def test_cli_agent_round_trip(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(run_dir).model_dump(mode="json")), encoding="utf-8"
    )
    runner = CliRunner()
    validated = runner.invoke(app, ["agent", "validate", str(run_dir), str(proposal_path)])
    applied = runner.invoke(app, ["agent", "apply", str(run_dir), str(proposal_path)])
    rendered = runner.invoke(app, ["agent", "render", str(run_dir)])
    assert validated.exit_code == applied.exit_code == rendered.exit_code == 0
    assert (run_dir / "agent" / "decompiled.annotated.sol").is_file()
