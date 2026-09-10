"""One-command CLI for the thin OpenHands Gateway wrapper."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .harness import REASONING_OPTIONS, run
from .telemetry import collect


def main() -> int:
    """Run OpenHands and collect telemetry in one command."""
    parser = argparse.ArgumentParser(description="Run OpenHands through the HackerRank API Gateway")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--instruction-file", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", choices=REASONING_OPTIONS, default="medium")
    parser.add_argument("--output", type=Path, default=Path("run-output"))
    parser.add_argument("--gateway-base-url")
    parser.add_argument("--env-file", type=Path, help="optional Gateway .env file; defaults to .env in the current directory")
    parser.add_argument("--redact", action="store_true", help="redact likely credentials from output artifacts")
    argv = sys.argv[1:]
    if argv and argv[0] == "run":
        argv = argv[1:]
    args = parser.parse_args(argv)

    result = run(args.workspace, args.instruction_file, args.model, args.reasoning, args.output, args.gateway_base_url, args.env_file, args.redact)
    collect(
        result.events_path,
        args.output / "telemetry.json",
        model=args.model if "/" in args.model else f"openai/{args.model}",
        reasoning=args.reasoning,
        started_at=result.started_at,
        completed_at=result.completed_at,
        status=result.status,
        exit_code=result.exit_code,
        error=result.error,
        gateway_responses_path=args.output / "gateway_responses.jsonl",
        redact_output=args.redact,
    )
    print(f"Telemetry: {args.output / 'telemetry.json'}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
