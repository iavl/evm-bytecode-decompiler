import csv
import json
from collections.abc import Iterable
from pathlib import Path

RelationSet = dict[str, list[tuple[str, ...]]]
RELATION_SCHEMA_VERSION = 1

RELATION_COLUMNS: dict[str, int] = {
    "PublicFunction": 2,
    "FunctionEntry": 2,
    "FunctionBlock": 2,
    "Block": 1,
    "BlockPC": 2,
    "BlockSuccessor": 2,
    "ConditionalSuccessor": 3,
    "Statement": 1,
    "StatementBlock": 2,
    "StatementPC": 2,
    "StatementOpcode": 2,
    "StatementOperand": 2,
    "StatementOperandSize": 2,
    "StatementTruncated": 2,
    "Defines": 2,
    "Uses": 2,
    "DataFlow": 2,
    "StorageLoad": 3,
    "StorageStore": 3,
    "Call": 7,
    "CallDetail": 9,
    "Event": 4,
    "EventTopic": 3,
    "Revert": 3,
    "Constant": 2,
}


def _delimiter(path: Path, sample: str) -> str:
    """Datalog commonly emits tab-separated rows with a .csv suffix."""
    if path.suffix in {".tsv", ".facts"} or "\t" in sample:
        return "\t"
    return ","


def parse_relation_file(path: Path) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        sample = handle.read(4096)
        delimiter = _delimiter(path, sample)
        handle.seek(0)
        for row in csv.reader(handle, delimiter=delimiter):
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].lstrip().startswith("#"):
                continue
            rows.append(tuple(cell.strip() for cell in row))
    return rows


def validate_relations(relations: RelationSet, *, require_core: bool = True) -> None:
    """Reject malformed adapter output before it can become semantic evidence."""
    if require_core:
        missing = [name for name in ("Block", "Statement") if name not in relations]
        if missing:
            raise ValueError(f"missing required relations: {', '.join(missing)}")
    for name, rows in relations.items():
        expected = RELATION_COLUMNS.get(name)
        if expected is None:
            continue
        for row in rows:
            if len(row) != expected:
                raise ValueError(f"relation {name} expects {expected} columns, got {len(row)}")
        if len(rows) != len(set(rows)):
            raise ValueError(f"relation {name} contains duplicate rows")
    for name in (
        "BlockPC",
        "StatementBlock",
        "StatementPC",
        "StatementOpcode",
        "StatementOperand",
        "StatementOperandSize",
        "StatementTruncated",
    ):
        by_key: dict[str, str] = {}
        for row in relations.get(name, ()):
            if len(row) < 2:
                continue
            previous = by_key.setdefault(row[0], row[1])
            if previous != row[1]:
                raise ValueError(f"relation {name} has conflicting values for {row[0]}")
    known_blocks = {row[0] for row in relations.get("Block", ()) if row}
    known_statements = {row[0] for row in relations.get("Statement", ()) if row}

    def refs(name: str, indexes: tuple[int, ...], known: set[str]) -> None:
        unknown = sorted(
            {
                row[index]
                for row in relations.get(name, ())
                for index in indexes
                if len(row) > index and row[index] not in known
            }
        )
        if unknown:
            raise ValueError(f"{name} references unknown IDs: {unknown[:5]}")

    refs("BlockPC", (0,), known_blocks)
    refs("BlockSuccessor", (0, 1), known_blocks)
    refs("ConditionalSuccessor", (0, 1, 2), known_blocks)
    refs("FunctionEntry", (1,), known_blocks)
    refs("FunctionBlock", (1,), known_blocks)
    known_functions = {row[1] for row in relations.get("PublicFunction", ()) if len(row) >= 2}
    known_functions.update(row[0] for row in relations.get("FunctionEntry", ()) if row)
    unknown_functions = sorted(
        {
            row[0]
            for row in relations.get("FunctionBlock", ())
            if row and row[0] not in known_functions
        }
    )
    if unknown_functions:
        raise ValueError(f"FunctionBlock references unknown functions: {unknown_functions[:5]}")
    for relation in (
        "StatementBlock",
        "StatementPC",
        "StatementOpcode",
        "StatementOperand",
        "StatementOperandSize",
        "StatementTruncated",
        "Defines",
        "Uses",
        "StorageLoad",
        "StorageStore",
        "Call",
        "CallDetail",
    ):
        refs(relation, (0,), known_statements)
    refs("Event", (1,), known_statements)
    refs("Revert", (1,), known_statements)


def load_relations(directory: Path) -> RelationSet:
    raw: RelationSet = {}
    schema_path = directory / "schema.json"
    if schema_path.is_file():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid relation schema metadata") from exc
        if not isinstance(schema, dict) or schema.get("version") != RELATION_SCHEMA_VERSION:
            raise ValueError("unsupported relation schema version")
    for path in sorted(directory.iterdir()):
        if path.suffix not in {".csv", ".tsv", ".facts"} or not path.is_file():
            continue
        raw[path.stem] = parse_relation_file(path)
    relations = dict(raw)
    for name, rows in raw.items():
        if name.startswith("EBD_"):
            relations[name[4:]] = rows
    validate_relations(relations)
    return relations


def write_relations(directory: Path, relations: RelationSet, suffix: str = ".tsv") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "schema.json").write_text(
        json.dumps({"version": RELATION_SCHEMA_VERSION}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name, rows in sorted(relations.items()):
        path = directory / f"{name}{suffix}"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t" if suffix in {".tsv", ".facts"} else ",")
            for row in sorted(set(rows)):
                writer.writerow(row)


def relation_rows(relations: RelationSet, name: str) -> Iterable[tuple[str, ...]]:
    return relations.get(name, ())
