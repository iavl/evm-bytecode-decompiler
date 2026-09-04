from enum import StrEnum


class Stage(StrEnum):
    INPUT = "input"
    GIGAHORSE = "gigahorse"
    IR_BUILD = "ir_build"
    DETERMINISTIC_INFERENCE = "deterministic_inference"
    AI_FUNCTION_SEMANTICS = "ai_function_semantics"
    AI_RECONCILIATION = "ai_reconciliation"
    SYNTHESIS = "synthesis"
    VALIDATION = "validation"
    REPORT = "report"
