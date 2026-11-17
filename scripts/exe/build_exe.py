"""Build the single-file executable with PyInstaller and print its size and SHA-256.

Run with a Python that has the package and its extras installed, plus PyInstaller:
    pip install ".[js,rust]" pyinstaller
    python scripts/exe/build_exe.py [out_dir]

The executable is the CLI (scripts/exe/launcher.py) with the Python runtime,
the package data files and tree-sitter (JavaScript/TypeScript, Rust) inside.
`slop_detector.auth` is left out: it needs PyJWT, which no install extra provides.

ASCII-only (cp949 safety).
"""

import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "slop-detector"


def main(argv):
    out = Path(argv[0]) if argv else HERE / "dist"
    work = out / "build"
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--name", NAME,
        "--collect-data", "slop_detector",
        "--collect-submodules", "slop_detector",
        "--exclude-module", "slop_detector.auth",
        "--distpath", str(out), "--workpath", str(work), "--specpath", str(work),
        str(HERE / "launcher.py"),
    ]
    subprocess.run(cmd, check=True)
    exe = next(out.glob(NAME + "*"))
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    print(f"{exe}  {exe.stat().st_size} bytes  sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
