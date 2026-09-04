def confidence_class(score: float) -> str:
    if score >= 0.95:
        return "deterministic"
    if score >= 0.80:
        return "strongly supported"
    if score >= 0.60:
        return "plausible"
    if score >= 0.40:
        return "weak inference"
    return "unresolved"


def readable_name(name: str, confidence: float, neutral: str) -> str:
    return name if confidence >= 0.60 else neutral
