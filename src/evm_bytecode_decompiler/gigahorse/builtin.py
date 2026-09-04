import json
from pathlib import Path

from .parser import BytecodeBlock, Instruction, block_id, build_blocks, disassemble
from .relations import RelationSet, write_relations


def _hex(value: int) -> str:
    return f"0x{value:x}"


def _selectors(instructions: list[Instruction]) -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for index, instruction in enumerate(instructions):
        if instruction.opcode != 0x63 or instruction.operand is None:
            continue
        window = instructions[index + 1 : index + 7]
        eq_index = next((offset for offset, item in enumerate(window) if item.opcode == 0x14), None)
        if eq_index is None:
            continue
        push = next((item for item in window[eq_index + 1 :] if item.operand is not None), None)
        if push is None:
            continue
        after_push = window[window.index(push) + 1 :]
        if not any(item.opcode == 0x57 for item in after_push):
            continue
        selector = f"0x{instruction.operand:08x}"
        function = f"func_{selector}"
        destination = push.operand
        if destination is None:
            continue
        found.append((selector, function, destination))
    return found


def _reachable(entry: str, by_id: dict[str, BytecodeBlock]) -> set[str]:
    seen: set[str] = set()
    todo = [entry]
    while todo:
        current = todo.pop()
        if current in seen or current not in by_id:
            continue
        seen.add(current)
        todo.extend(by_id[current].successors)
    return seen


def _stack_expressions(block: BytecodeBlock) -> dict[int, str]:
    """Keep only nearby PUSH facts; full stack recovery belongs to Gigahorse."""
    pushes: list[Instruction] = []
    result: dict[int, str] = {}
    for instruction in block.instructions:
        if instruction.operand is not None and instruction.opcode >= 0x60:
            pushes.append(instruction)
        elif instruction.opcode in {0x54, 0x55}:
            slot = pushes[-1].operand if pushes else None
            result[instruction.pc] = f"fixed:{slot}" if slot is not None else "symbolic:sload"
        elif instruction.opcode == 0x20:
            result[instruction.pc] = "mapping:unknown"
    return result


def build_builtin_relations(code: bytes) -> RelationSet:
    instructions = disassemble(code)
    blocks = build_blocks(instructions)
    by_id = {block.id: block for block in blocks}
    selectors = _selectors(instructions)
    relations: RelationSet = {
        "Block": [(block.id,) for block in blocks],
        "BlockPC": [(block.id, str(block.pc)) for block in blocks],
        "BlockSuccessor": [
            (block.id, successor) for block in blocks for successor in block.successors
        ],
        "Statement": [],
        "StatementBlock": [],
        "StatementPC": [],
        "StatementOpcode": [],
        "StatementOperand": [],
        "Constant": [],
        "FunctionBlock": [],
        "FunctionEntry": [],
        "PublicFunction": [(selector, function) for selector, function, _ in selectors],
        "Defines": [],
        "Uses": [],
        "DataFlow": [],
        "StorageLoad": [],
        "StorageStore": [],
        "Call": [],
        "Event": [],
        "Revert": [],
    }
    for block in blocks:
        previous_variable: str | None = None
        stack_facts = _stack_expressions(block)
        for instruction in block.instructions:
            statement = f"S_{instruction.pc:04x}"
            variable = f"v_{instruction.pc:04x}"
            relations["Statement"].append((statement,))
            relations["StatementBlock"].append((statement, block.id))
            relations["StatementPC"].append((statement, str(instruction.pc)))
            relations["StatementOpcode"].append((statement, instruction.name))
            if instruction.operand is not None:
                relations["StatementOperand"].append((statement, str(instruction.operand)))
                relations["Constant"].append((statement, str(instruction.operand)))
            if previous_variable:
                relations["Uses"].append((statement, previous_variable))
                relations["DataFlow"].append((previous_variable, variable))
            if instruction.operand is not None or instruction.opcode in {0x35, 0x54}:
                relations["Defines"].append((statement, variable))
                previous_variable = variable
            if instruction.opcode == 0x54:
                slot = stack_facts.get(instruction.pc, "symbolic:sload")
                relations["StorageLoad"].append((statement, slot, variable))
            elif instruction.opcode == 0x55:
                value = previous_variable or "unknown"
                slot = stack_facts.get(instruction.pc, "symbolic:sstore")
                relations["StorageStore"].append((statement, slot, value))
            elif instruction.opcode in {0xf0, 0xf1, 0xf2, 0xf4, 0xf5, 0xfa, 0xff}:
                call_type = {
                    0xf0: "create",
                    0xf1: "call",
                    0xf2: "callcode",
                    0xf4: "delegatecall",
                    0xf5: "create2",
                    0xfa: "staticcall",
                    0xff: "selfdestruct",
                }[instruction.opcode]
                relations["Call"].append(
                    (statement, call_type, "unknown", "unknown", "unknown", "unknown", variable)
                )
            elif 0xa0 <= instruction.opcode <= 0xa4:
                relations["Event"].append(
                    (
                        f"E_{instruction.pc:04x}",
                        statement,
                        str(instruction.opcode - 0xa0),
                        "unknown",
                    )
                )
            elif instruction.opcode in {0xfd, 0xfe}:
                kind = "revert" if instruction.opcode == 0xfd else "invalid"
                relations["Revert"].append(
                    (f"R_{instruction.pc:04x}", statement, kind)
                )
    function_entries: list[tuple[str, ...]] = [
        (function, block_id(destination)) for _, function, destination in selectors
    ]
    relations["FunctionEntry"] = function_entries
    if function_entries:
        for function, entry in function_entries:
            for member_block_id in sorted(_reachable(entry, by_id)):
                relations["FunctionBlock"].append((function, member_block_id))
    else:
        relations["FunctionEntry"] = [("fallback", blocks[0].id)] if blocks else []
        relations["FunctionBlock"] = [("fallback", block.id) for block in blocks]
    return relations


def write_builtin_workspace(code: bytes, output_dir: Path, *, sha256: str) -> None:
    facts_dir = output_dir / "facts"
    relations = build_builtin_relations(code)
    write_relations(facts_dir, relations)
    (output_dir / "results.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "backend": "builtin-fallback",
                "version": "builtin-evm-lifter-1",
                "commit": "builtin",
                "bytecode_sha256": sha256,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
