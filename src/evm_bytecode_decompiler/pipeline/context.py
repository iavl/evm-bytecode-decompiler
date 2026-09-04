from dataclasses import dataclass, field
from pathlib import Path

from .stages import Stage


@dataclass
class PipelineContext:
    run_dir: Path
    stages: dict[str, dict[str, object]] = field(default_factory=dict)

    def mark(self, stage: Stage, status: str, **details: object) -> None:
        self.stages[stage.value] = {"status": status, **details}
