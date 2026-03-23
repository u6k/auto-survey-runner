"""Backward-compatible stage exports.

Historically the pipeline stages lived in this single module.  They are now
split under ``survey_runner.stages`` so each processing step is easier to find
and maintain, while this module keeps the old import path working.
"""

from .stages import (
    STAGE_ORDER,
    collecting_stage,
    extracting_stage,
    integrating_stage,
    planning_stage,
    snapshotting_stage,
    spawning_stage,
    summarizing_stage,
)

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
