import csv
from collections.abc import Iterable
from pathlib import Path

RelationSet = dict[str, list[tuple[str, ...]]]

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
    "Defines": 2,
    "Uses": 2,
    "DataFlow": 2,
    "StorageLoad": 3,
    "StorageStore": 3,
    "Call": 7,
    "Event": 4,
    "Revert": 3,
    "Constant": 2,
}


def parse_relation_file(path: Path) -> list[tuple[str, ...]]:
    delimiter = "\t" if path.suffix in {".tsv", ".facts"} else ","
    rows: list[tuple[str, ...]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter=delimiter):
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].lstrip().startswith("#"):
                continue
            rows.append(tuple(cell.strip() for cell in row))
    return rows


def load_relations(directory: Path) -> RelationSet:
    relations: RelationSet = {}
    for path in sorted(directory.iterdir()):
        if path.suffix not in {".csv", ".tsv", ".facts"} or not path.is_file():
            continue
        relations[path.stem] = parse_relation_file(path)
    return relations


def write_relations(directory: Path, relations: RelationSet, suffix: str = ".tsv") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, rows in sorted(relations.items()):
        path = directory / f"{name}{suffix}"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t" if suffix in {".tsv", ".facts"} else ",")
            for row in sorted(set(rows)):
                writer.writerow(row)


def relation_rows(relations: RelationSet, name: str) -> Iterable[tuple[str, ...]]:
    return relations.get(name, ())
