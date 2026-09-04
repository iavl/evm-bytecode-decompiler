from pydantic import BaseModel, ConfigDict, Field

from ..gigahorse.parser import disassemble


class SelectorMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: str = Field(pattern=r"^0x[0-9a-f]{8}$")
    destination_pc: int = Field(ge=0)
    dispatcher_pc: int = Field(ge=0)
    function_id: str


def extract_public_selectors(code: bytes) -> list[SelectorMatch]:
    instructions = disassemble(code)
    matches: list[SelectorMatch] = []
    for index, instruction in enumerate(instructions):
        if instruction.opcode != 0x63 or instruction.operand is None:
            continue
        window = instructions[index + 1 : index + 7]
        eq_offset = next(
            (offset for offset, item in enumerate(window) if item.opcode == 0x14),
            None,
        )
        if eq_offset is None:
            continue
        destination = next(
            (item for item in window[eq_offset + 1 :] if item.operand is not None),
            None,
        )
        if destination is None:
            continue
        if not any(item.opcode == 0x57 for item in window[window.index(destination) + 1 :]):
            continue
        destination_pc = destination.operand
        if destination_pc is None:
            continue
        selector = f"0x{instruction.operand:08x}"
        matches.append(
            SelectorMatch(
                selector=selector,
                destination_pc=destination_pc,
                dispatcher_pc=instruction.pc,
                function_id=f"func_{selector}",
            )
        )
    return matches
