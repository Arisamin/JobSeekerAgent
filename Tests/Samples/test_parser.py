import subprocess
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    script_path = project_root / "test_parser.py"
    command = [sys.executable, str(script_path), "Tests/Samples/positive_match.txt", "--expect-match", "auto"]
    result = subprocess.run(command, cwd=str(project_root), check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())