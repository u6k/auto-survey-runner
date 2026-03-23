"""Stage-oriented pipeline implementation.

Each stage is placed in its own module so readers can map the runtime stage
names directly to the code that implements them.
"""

from .collecting import collecting_stage
from .extracting import extracting_stage
from .integrating import integrating_stage
from .planning import planning_stage
from .snapshotting import snapshotting_stage
from .spawning import spawning_stage
from .summarizing import summarizing_stage

STAGE_ORDER = ["planning", "collecting", "extracting", "summarizing", "spawning", "integrating", "snapshotting", "done"]

__all__ = [
    "STAGE_ORDER",
    "planning_stage",
    "collecting_stage",
    "extracting_stage",
    "summarizing_stage",
    "spawning_stage",
    "integrating_stage",
    "snapshotting_stage",
]
