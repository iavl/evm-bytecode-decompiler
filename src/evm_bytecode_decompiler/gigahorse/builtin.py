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


def _expr_text(value: tuple[str, object]) -> str:
    kind, item = value
    if kind == "constant":
        return str(item)
    if kind == "caller":
        return "msg.sender"
    if kind == "calldata":
        return f"calldata({item})"
    return str(item)


def _storage_expressions(
    block: BytecodeBlock,
) -> tuple[dict[int, str], dict[int, str], dict[int, tuple[str, ...]]]:
    """Recover only stack/memory shapes with unambiguous local evidence."""
    stack: list[tuple[str, object]] = []
    memory: dict[int, tuple[str, object]] = {}
    result: dict[int, str] = {}
    values: dict[int, str] = {}
    calls: dict[int, tuple[str, ...]] = {}

    def pop() -> tuple[str, object]:
        return stack.pop() if stack else ("unknown", "unknown")

    def constant(value: tuple[str, object]) -> int | None:
        return int(value[1]) if value[0] == "constant" and isinstance(value[1], int) else None

    for instruction in block.instructions:
        if instruction.opcode == 0x5F:
            stack.append(("constant", 0))
        elif instruction.operand is not None and instruction.opcode >= 0x60:
            stack.append(("constant", instruction.operand))
        elif instruction.opcode == 0x33:
            stack.append(("caller", "msg.sender"))
        elif instruction.opcode == 0x35:
            stack.append(("calldata", _expr_text(pop())))
        elif 0x80 <= instruction.opcode <= 0x8F:
            index = instruction.opcode - 0x80
            stack.append(stack[-1 - index] if len(stack) > index else ("unknown", "unknown"))
        elif 0x90 <= instruction.opcode <= 0x9F:
            index = instruction.opcode - 0x8F
            if len(stack) > index:
                stack[-1], stack[-1 - index] = stack[-1 - index], stack[-1]
        elif instruction.opcode == 0x50:
            pop()
        elif instruction.opcode == 0x52:
            offset = constant(pop())
            value = pop()
            if offset is not None:
                memory[offset] = value
        elif instruction.opcode == 0x20:
            offset = constant(pop())
            size = constant(pop())
            words = (
                [memory.get(offset + index * 32) for index in range(2)]
                if offset is not None
                else []
            )
            if size == 64 and len(words) == 2 and all(words):
                key = words[0]
                base = words[1]
                if key is not None and base is not None:
                    base_slot = constant(base)
                    if base_slot is not None:
                        if key[0] == "mapping":
                            # A nested hash needs provenance for both keys;
                            # keep it symbolic until the stack model can prove it.
                            stack.append(("unknown", "sha3"))
                        else:
                            stack.append(("mapping", f"mapping:{base_slot}:{_expr_text(key)}"))
                    else:
                        stack.append(("unknown", "sha3"))
                else:
                    stack.append(("unknown", "sha3"))
            else:
                stack.append(("unknown", "sha3"))
        elif instruction.opcode == 0x54:
            slot = pop()
            if slot[0] == "constant":
                result[instruction.pc] = f"fixed:{slot[1]}"
            elif slot[0] == "mapping":
                result[instruction.pc] = str(slot[1])
            else:
                result[instruction.pc] = "symbolic:sload"
            stack.append(("sload", f"sload@{instruction.pc:04x}"))
        elif instruction.opcode == 0x55:
            slot = pop()
            value = pop()
            if slot[0] == "constant":
                result[instruction.pc] = f"fixed:{slot[1]}"
            elif slot[0] == "mapping":
                result[instruction.pc] = str(slot[1])
            else:
                result[instruction.pc] = "symbolic:sstore"
            values[instruction.pc] = _expr_text(value)
        elif instruction.opcode in {0xF0, 0xF1, 0xF2, 0xF4, 0xF5, 0xFA, 0xFF}:
            arity = {
                0xF0: 3,
                0xF1: 7,
                0xF2: 7,
                0xF4: 6,
                0xF5: 4,
                0xFA: 6,
                0xFF: 1,
            }[instruction.opcode]
            args = [_expr_text(pop()) for _ in range(arity)][::-1]
            calls[instruction.pc] = tuple(args)
            if instruction.opcode != 0xFF:
                stack.append(("unknown", f"result@{instruction.pc:04x}"))
    return result, values, calls


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
        "ConditionalSuccessor": [],
        "Statement": [],
        "StatementBlock": [],
        "StatementPC": [],
        "StatementOpcode": [],
        "StatementOperand": [],
        "StatementOperandSize": [],
        "StatementTruncated": [],
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
        "CallDetail": [],
        "Event": [],
        "EventTopic": [],
        "Revert": [],
    }
    for block in blocks:
        if block.instructions and block.instructions[-1].opcode == 0x57:
            if len(block.successors) == 2:
                relations["ConditionalSuccessor"].append(
                    (block.id, block.successors[0], block.successors[1])
                )
        stack_facts, storage_values, call_details = _storage_expressions(block)
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
            if instruction.opcode >= 0x60 and instruction.opcode <= 0x7F:
                relations["StatementOperandSize"].append((statement, str(instruction.operand_size)))
            if instruction.truncated:
                relations["StatementTruncated"].append((statement, "true"))
            if instruction.operand is not None or instruction.opcode in {0x35, 0x54}:
                relations["Defines"].append((statement, variable))
            if instruction.opcode == 0x54:
                slot = stack_facts.get(instruction.pc, "symbolic:sload")
                relations["StorageLoad"].append((statement, slot, variable))
            elif instruction.opcode == 0x55:
                value = storage_values.get(instruction.pc, "unknown")
                slot = stack_facts.get(instruction.pc, "symbolic:sstore")
                relations["StorageStore"].append((statement, slot, value))
            elif instruction.opcode in {0xF0, 0xF1, 0xF2, 0xF4, 0xF5, 0xFA, 0xFF}:
                call_type = {
                    0xF0: "create",
                    0xF1: "call",
                    0xF2: "callcode",
                    0xF4: "delegatecall",
                    0xF5: "create2",
                    0xFA: "staticcall",
                    0xFF: "selfdestruct",
                }[instruction.opcode]
                args = call_details.get(instruction.pc, ())
                padded = list(args) + ["unknown"] * (7 - len(args))
                target = padded[1] if instruction.opcode in {0xF1, 0xF2, 0xF4, 0xFA} else "unknown"
                value = (
                    padded[2]
                    if instruction.opcode in {0xF1, 0xF2}
                    else (padded[0] if instruction.opcode in {0xF0, 0xF5} else "unknown")
                )
                input_expr = (
                    f"range:{padded[3]}:{padded[4]}"
                    if instruction.opcode in {0xF1, 0xF2, 0xF4, 0xFA}
                    else f"range:{padded[1]}:{padded[2]}"
                    if instruction.opcode in {0xF0, 0xF5}
                    else "unknown"
                )
                output_expr = (
                    f"range:{padded[5]}:{padded[6]}"
                    if instruction.opcode in {0xF1, 0xF2, 0xF4, 0xFA}
                    else "unknown"
                )
                relations["Call"].append(
                    (statement, call_type, target, value, input_expr, output_expr, variable)
                )
                if instruction.opcode == 0xFF:
                    detail: tuple[str, ...] = (
                        "unknown",
                        "unknown",
                        "unknown",
                        "unknown",
                        "unknown",
                        "unknown",
                        "unknown",
                        padded[0],
                    )
                elif instruction.opcode in {0xF0, 0xF5}:
                    detail = (
                        "unknown",
                        "unknown",
                        padded[0],
                        padded[1],
                        padded[2],
                        "unknown",
                        "unknown",
                        padded[3] if instruction.opcode == 0xF5 else "unknown",
                    )
                else:
                    detail = tuple(padded[:7]) + ("unknown",)
                relations["CallDetail"].append((statement, *detail))
            elif 0xA0 <= instruction.opcode <= 0xA4:
                event_id = f"E_{instruction.pc:04x}"
                topic_count = instruction.opcode - 0xA0
                relations["Event"].append(
                    (
                        event_id,
                        statement,
                        str(topic_count),
                        "unknown",
                    )
                )
            elif instruction.opcode in {0xFD, 0xFE}:
                kind = "revert" if instruction.opcode == 0xFD else "invalid"
                relations["Revert"].append((f"R_{instruction.pc:04x}", statement, kind))
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
                "status": "partial",
                "backend": "builtin-fallback",
                "version": "builtin-evm-lifter-1",
                "commit": "builtin",
                "completeness": "partial",
                "bytecode_sha256": sha256,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
