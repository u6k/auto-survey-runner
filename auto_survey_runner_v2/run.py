"""CLI entrypoint for auto_survey_runner_v2."""

from __future__ import annotations

import argparse
from pathlib import Path

from survey_runner.config import load_config
from survey_runner.orchestrator import Orchestrator


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(description="Run the auto survey runner v2 pipeline.")
    parser.add_argument("command", choices=["init", "run", "status"], help="Command to execute.")
    parser.add_argument("--config", required=True, help="Path to YAML config.")
    parser.add_argument("--steps", type=int, default=None, help="Max number of tasks to advance in this invocation.")
    return parser


def main() -> int:
    """CLI main function."""
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(Path(args.config))
    orchestrator = Orchestrator(config)

    if args.command == "init":
        orchestrator.init_workspace()
        print("Initialized workspace.")
        return 0
    if args.command == "run":
        orchestrator.run(steps=args.steps)
        print("Run completed.")
        return 0

    status = orchestrator.status()
    print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
