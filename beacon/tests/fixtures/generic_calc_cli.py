#!/usr/bin/env python3
"""Domain-neutral CLI fixture script for testing ProcessAdapter and CliAdapter."""

import argparse
import json
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="Generic calculation CLI fixture")
    parser.add_argument("--x", type=float, default=None, help="Operand X")
    parser.add_argument("--y", type=float, default=None, help="Operand Y")
    parser.add_argument("--operation", type=str, default="multiply", choices=["multiply", "add", "error", "sleep", "huge_output"])
    parser.add_argument("--sleep_seconds", type=float, default=0.0, help="Simulate latency")
    parser.add_argument("--json_in", type=str, default=None, help="JSON input payload")

    args = parser.parse_args()

    # Read from json_in if provided
    x = args.x
    y = args.y
    op = args.operation

    if args.json_in:
        data = json.loads(args.json_in)
        x = data.get("x", x)
        y = data.get("y", y)
        op = data.get("operation", op)

    # Handle sleep for timeout testing
    if op == "sleep" or args.sleep_seconds > 0:
        sleep_dur = args.sleep_seconds if args.sleep_seconds > 0 else 5.0
        time.sleep(sleep_dur)

    # Handle deliberate failure
    if op == "error":
        sys.stderr.write("Simulated CLI fatal error occurred\n")
        sys.exit(2)

    # Handle oversized output
    if op == "huge_output":
        huge_str = "A" * 2_000_000
        print(json.dumps({"huge_data": huge_str}))
        sys.exit(0)

    # Default arithmetic operations
    if x is None or y is None:
        sys.stderr.write("Missing required operands x and y\n")
        sys.exit(1)

    if op == "multiply":
        result = x * y
    elif op == "add":
        result = x + y
    else:
        result = 0.0

    output = {
        "status": "success",
        "operation": op,
        "x": x,
        "y": y,
        "result": result,
    }
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
