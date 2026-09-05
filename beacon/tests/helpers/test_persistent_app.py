"""BEACON V2 — Deterministic Persistent Test Application.

Line-delimited JSON over stdin/stdout.
Exposes process PID and sequence counter in every response.
Exits cleanly when EOF is received or when command is 'exit'.
"""
import json
import os
import sys


def main():
    pid = os.getpid()
    count = 0

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as err:
            sys.stdout.write(json.dumps({"error": str(err), "pid": pid}) + "\n")
            sys.stdout.flush()
            continue

        if isinstance(req, dict) and req.get("command") == "exit":
            break

        count += 1
        resp = {
            "echo": req.get("data", req) if isinstance(req, dict) else req,
            "pid": pid,
            "count": count,
            "status": "PROCESSED",
        }
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
