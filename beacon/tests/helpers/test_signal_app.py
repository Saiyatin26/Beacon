"""BEACON V2 — Signal-Only Persistent Test Application.

Reads line-delimited input from stdin. Does NOT recognize or process any exit command.
Optionally logs every raw line received on stdin to the file path passed in sys.argv[1].
Terminates only via EOF or OS signal (SIGTERM/taskkill).
"""
import json
import os
import sys


def main():
    pid = os.getpid()
    log_file = sys.argv[1] if len(sys.argv) > 1 else None

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        if log_file:
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

        try:
            req = json.loads(line)
        except Exception:
            req = {"raw": line}

        resp = {
            "received": req,
            "pid": pid,
            "status": "PROCESSED",
        }
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
