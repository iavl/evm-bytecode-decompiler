from enum import StrEnum


class Stage(StrEnum):
    INPUT = "input"
    GIGAHORSE = "gigahorse"
    IR_BUILD = "ir_build"
    DETERMINISTIC_INFERENCE = "deterministic_inference"
    VALIDATION = "validation"
    REPORT = "report"
