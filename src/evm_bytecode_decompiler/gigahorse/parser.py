from dataclasses import dataclass

OPCODES = {
    0x00: "STOP",
    0x01: "ADD",
    0x02: "MUL",
    0x03: "SUB",
    0x04: "DIV",
    0x06: "MOD",
    0x10: "LT",
    0x11: "GT",
    0x14: "EQ",
    0x15: "ISZERO",
    0x16: "AND",
    0x17: "OR",
    0x19: "NOT",
    0x20: "SHA3",
    0x30: "ADDRESS",
    0x33: "CALLER",
    0x34: "CALLVALUE",
    0x35: "CALLDATALOAD",
    0x36: "CALLDATASIZE",
    0x37: "CALLDATACOPY",
    0x39: "CODECOPY",
    0x3D: "RETURNDATASIZE",
    0x3E: "RETURNDATACOPY",
    0x50: "POP",
    0x51: "MLOAD",
    0x52: "MSTORE",
    0x53: "MSTORE8",
    0x54: "SLOAD",
    0x55: "SSTORE",
    0x56: "JUMP",
    0x57: "JUMPI",
    0x5B: "JUMPDEST",
    0x5F: "PUSH0",
    0x80: "DUP1",
    0x90: "SWAP1",
    0xA0: "LOG0",
    0xA1: "LOG1",
    0xA2: "LOG2",
    0xA3: "LOG3",
    0xA4: "LOG4",
    0xF0: "CREATE",
    0xF1: "CALL",
    0xF2: "CALLCODE",
    0xF3: "RETURN",
    0xF4: "DELEGATECALL",
    0xF5: "CREATE2",
    0xFA: "STATICCALL",
    0xFD: "REVERT",
    0xFE: "INVALID",
    0xFF: "SELFDESTRUCT",
}


@dataclass(frozen=True)
class Instruction:
    pc: int
    opcode: int
    name: str
    operand: int | None = None
    operand_size: int = 0


@dataclass(frozen=True)
class BytecodeBlock:
    id: str
    pc: int
    instructions: tuple[Instruction, ...]
    successors: tuple[str, ...]


def disassemble(code: bytes) -> list[Instruction]:
    instructions: list[Instruction] = []
    pc = 0
    while pc < len(code):
        opcode = code[pc]
        name = OPCODES.get(opcode, f"OP_{opcode:02x}")
        if 0x60 <= opcode <= 0x7F:
            size = opcode - 0x5F
            raw = code[pc + 1 : pc + 1 + size]
            operand = int.from_bytes(raw, "big") if raw else None
            instructions.append(Instruction(pc, opcode, f"PUSH{size}", operand, len(raw)))
            pc += 1 + size
        elif opcode == 0x5F:
            instructions.append(Instruction(pc, opcode, name, 0, 0))
            pc += 1
        else:
            instructions.append(Instruction(pc, opcode, name))
            pc += 1
    return instructions


def block_id(pc: int) -> str:
    return f"B_{pc:04x}"


def build_blocks(instructions: list[Instruction]) -> list[BytecodeBlock]:
    if not instructions:
        return []
    starts = {instructions[0].pc}
    pc_to_index = {instruction.pc: index for index, instruction in enumerate(instructions)}
    terminators = {0x00, 0x56, 0x57, 0xF3, 0xFD, 0xFE, 0xFF}
    for index, instruction in enumerate(instructions):
        if instruction.opcode == 0x5B:
            starts.add(instruction.pc)
        if instruction.opcode in terminators and index + 1 < len(instructions):
            starts.add(instructions[index + 1].pc)
    ordered = sorted(starts)
    blocks: list[BytecodeBlock] = []
    for start_index, start_pc in enumerate(ordered):
        end_pc = ordered[start_index + 1] if start_index + 1 < len(ordered) else None
        first = pc_to_index[start_pc]
        selected = tuple(
            instruction
            for instruction in instructions[first:]
            if end_pc is None or instruction.pc < end_pc
        )
        blocks.append(BytecodeBlock(block_id(start_pc), start_pc, selected, ()))
    by_pc = {block.pc: block for block in blocks}
    block_pcs = [block.pc for block in blocks]
    completed: list[BytecodeBlock] = []
    for block in blocks:
        last = block.instructions[-1]
        next_pc = next((pc for pc in block_pcs if pc > block.pc), None)
        next_block = by_pc.get(next_pc) if next_pc is not None else None
        destinations: list[str] = []
        if last.opcode in {0x56, 0x57}:
            for instruction in reversed(block.instructions[:-1]):
                if instruction.operand is not None and instruction.opcode >= 0x60:
                    destination = by_pc.get(instruction.operand)
                    if destination:
                        destinations.append(destination.id)
                    break
        if last.opcode == 0x57 and next_block:
            destinations.append(next_block.id)
        elif last.opcode not in terminators and next_block:
            destinations.append(next_block.id)
        unique_destinations = tuple(dict.fromkeys(destinations))
        completed.append(BytecodeBlock(block.id, block.pc, block.instructions, unique_destinations))
    return completed
