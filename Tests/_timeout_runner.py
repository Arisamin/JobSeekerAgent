import os
import subprocess
import sys
import time


def main() -> int:
    hard_timeout_seconds = int(os.environ.get("PYTEST_HARD_TIMEOUT", "120"))
    faulthandler_timeout_seconds = int(os.environ.get("PYTEST_FAULTHANDLER_TIMEOUT", "20"))
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["Tests/"]

    cmd = [
        r".venv/Scripts/python.exe",
        "-m",
        "pytest",
        *targets,
        "-vv",
        "-s",
        "-o",
        f"faulthandler_timeout={faulthandler_timeout_seconds}",
    ]

    print("RUN:", " ".join(cmd), flush=True)
    print(
        f"Timeout policy: hard={hard_timeout_seconds}s, faulthandler={faulthandler_timeout_seconds}s",
        flush=True,
    )

    start = time.time()
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    try:
        output, _ = process.communicate(timeout=hard_timeout_seconds)
        print(output)
        print(f"EXIT={process.returncode} ELAPSED={time.time() - start:.1f}s")
        return int(process.returncode or 0)
    except subprocess.TimeoutExpired:
        print(
            f"\nHARD TIMEOUT REACHED ({hard_timeout_seconds}s). Terminating pytest...",
            flush=True,
        )
        process.terminate()
        try:
            output, _ = process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
        print(output)
        print(f"EXIT=124 ELAPSED={time.time() - start:.1f}s")
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
