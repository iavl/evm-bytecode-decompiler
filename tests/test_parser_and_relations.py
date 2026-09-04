from pathlib import Path

from evm_bytecode_decompiler.gigahorse.builtin import build_builtin_relations
from evm_bytecode_decompiler.gigahorse.parser import disassemble
from evm_bytecode_decompiler.gigahorse.relations import load_relations, write_relations

FIXTURE = Path(__file__).parent / "fixtures" / "erc20" / "runtime.hex"


def code() -> bytes:
    return bytes.fromhex(FIXTURE.read_text(encoding="ascii").strip())


def test_disassembler_keeps_exact_push_operands() -> None:
    instructions = disassemble(bytes.fromhex("63a9059cbb6001"))
    assert [(item.name, item.operand) for item in instructions] == [
        ("PUSH4", 0xA9059CBB),
        ("PUSH1", 1),
    ]


def test_builtin_relations_cover_fixture_facts(tmp_path: Path) -> None:
    relations = build_builtin_relations(code())
    assert ("0xa9059cbb", "func_0xa9059cbb") in relations["PublicFunction"]
    assert ("0xdd62ed3e", "func_0xdd62ed3e") in relations["PublicFunction"]
    assert relations["StorageLoad"]
    assert relations["StorageStore"]
    assert any(row[1] == "call" for row in relations["Call"])
    assert relations["Event"] and relations["Revert"]

    write_relations(tmp_path, relations)
    loaded = load_relations(tmp_path)
    assert {name: sorted(rows) for name, rows in loaded.items()} == {
        name: sorted(rows) for name, rows in relations.items()
    }


def test_builtin_lifter_recovers_a_fixed_mapping_shape() -> None:
    mapping_access = bytes.fromhex("602a6000526003602052604060002054")
    relations = build_builtin_relations(mapping_access)

    assert relations["StorageLoad"][0][1] == "mapping:3:42"
