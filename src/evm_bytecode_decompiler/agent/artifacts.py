import json
from pathlib import Path

from ..errors import AnnotationError
from ..models.annotations import AnnotationProposal
from ..pipeline.artifacts import (
    artifact_hash,
    load_abi,
    load_contract,
    load_storage,
    validate_manifest,
)
from ..synthesis.pseudocode import render_contract
from .validation import validate_proposal


def load_applied(run_dir: Path) -> AnnotationProposal:
    run_manifest = validate_manifest(run_dir)
    agent_dir = run_dir / "agent"
    annotations_path = agent_dir / "annotations.json"
    manifest_path = agent_dir / "manifest.json"
    if not annotations_path.is_file() or not manifest_path.is_file():
        raise AnnotationError("no validated agent overlay is present")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        proposal = json.loads(annotations_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnnotationError(f"invalid agent artifact: {exc}") from exc
    if not isinstance(manifest, dict):
        raise AnnotationError("agent manifest must be an object")
    if manifest.get("schema_version") != 1:
        raise AnnotationError("unsupported agent manifest version")
    if manifest.get("deterministic_run_fingerprint") != run_manifest.get("fingerprint"):
        raise AnnotationError("agent overlay belongs to a different deterministic run")
    if manifest.get("annotations_sha256") != artifact_hash(annotations_path):
        raise AnnotationError("agent annotation hash mismatch")
    return validate_proposal(run_dir, proposal)


def render_agent(run_dir: Path) -> tuple[Path, Path]:
    proposal = load_applied(run_dir)
    contract = load_contract(run_dir)
    abi = load_abi(run_dir)
    storage = load_storage(run_dir)
    render_labels = dict(proposal.storage_labels)
    for entry in storage:
        label = proposal.storage_labels.get(entry.id)
        if label:
            render_labels.update({evidence: label for evidence in entry.evidence})
    render_annotations = {}
    for function_id, annotation in proposal.functions.items():
        labels = dict(annotation.storage_labels)
        for entry in storage:
            label = labels.get(entry.id)
            if label:
                labels.update({evidence: label for evidence in entry.evidence})
        render_annotations[function_id] = annotation.model_copy(update={"storage_labels": labels})
    agent_dir = run_dir / "agent"
    output_path = agent_dir / "decompiled.annotated.sol"
    output_path.write_text(
        render_contract(
            contract,
            abi,
            storage,
            annotations=render_annotations,
            contract_annotation=proposal.contract,
            storage_labels=render_labels,
            annotated=True,
        ),
        encoding="utf-8",
    )
    manifest = validate_manifest(run_dir)
    backend = manifest.get("backend", {})
    backend_name = backend.get("name", "unknown") if isinstance(backend, dict) else "unknown"
    completeness = (
        backend.get("completeness", "unknown") if isinstance(backend, dict) else "unknown"
    )
    lines = [
        "# Agent Semantic Report",
        "",
        "This is an evidence-grounded semantic overlay over reconstructed, unverified pseudocode.",
        "It is not recovered Solidity source.",
        "",
        f"- deterministic run fingerprint: `{manifest.get('fingerprint')}`",
        f"- analysis backend: `{backend_name}`",
        f"- analysis completeness: `{completeness}`",
        f"- annotated functions: `{len(proposal.functions)}`",
        "",
        "## Contract Semantics",
        "",
        proposal.contract.summary or "No contract-wide summary was supplied.",
        "",
    ]
    if proposal.contract.uncertainties:
        lines.extend(
            [
                "## Uncertainties",
                "",
                *[f"- {item}" for item in proposal.contract.uncertainties],
                "",
            ]
        )
    lines.extend(
        [
            "## Trust Boundary",
            "",
            "Canonical IR, deterministic operations, calls, storage accesses, constants, "
            "and control flow remain unchanged.",
            "Agent names, labels, summaries, and patterns are advisory and evidence-bound.",
            "",
        ]
    )
    report_path = agent_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path, report_path
