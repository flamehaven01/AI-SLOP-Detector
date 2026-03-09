import fnmatch
import glob
import os
import sys
from pathlib import Path

from slop_detector import SlopDetector

_HEADER = f"{'FILE':<50} | {'LDR':<5} | {'ICR':<5} | {'DDC':<5} | STATUS"
_SEP = "=" * 80
_DASH = "-" * 80


# ------------------------------------------------------------------
# File collection
# ------------------------------------------------------------------

def _matches_ignore(rel_path: str, patterns) -> bool:
    rel = rel_path.replace("\\", "/").lstrip("./")
    for pattern in patterns:
        pat = str(pattern).replace("\\", "/").lstrip("./")
        if fnmatch.fnmatch(rel, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
            return True
        if Path(rel).match(pat):
            return True
    return False


def _collect_python_files(root_dir: str, ignore_patterns) -> list:
    """Glob all .py files under root_dir, applying ignore patterns and venv exclusion."""
    all_files = glob.glob(os.path.join(root_dir, "**", "*.py"), recursive=True)
    result = []
    for file_path in all_files:
        rel = os.path.relpath(file_path, root_dir)
        if _matches_ignore(rel, ignore_patterns):
            continue
        if "venv" in file_path or "site-packages" in file_path:
            continue
        result.append(file_path)
    return result


# ------------------------------------------------------------------
# Per-file analysis + display
# ------------------------------------------------------------------

def _format_metric(value: float, threshold: float, fmt: str = ".2f") -> str:
    """Format a metric value, prefixing '!!' when below threshold."""
    s = format(value, fmt)
    return f"!!{s}" if value < threshold else s


def _analyze_file(file_path: str, root_dir: str, detector: SlopDetector):
    """
    Analyze one file and return (marker, row_str) or raise on failure.
    marker: 'slop' | 'warning' | 'clean'
    row_str: formatted table row (None when file is clean)
    """
    result = detector.analyze_file(file_path)
    ldr = result.ldr.ldr_score
    inflation = result.inflation.inflation_score
    ddc = result.ddc.usage_ratio
    status = result.status.value

    if status == "critical_deficit":
        marker = "slop"
    elif status in ("suspicious", "inflated_signal", "dependency_noise"):
        marker = "warning"
    else:
        return "clean", None

    ldr_str = _format_metric(ldr, 0.30)
    inflation_str = (
        format(inflation, ".2f") if inflation != float("inf") else "INF"
    )
    if inflation > 1.0:
        inflation_str = f"!!{inflation_str}"
    ddc_str = _format_metric(ddc, 0.50)

    prefix = "[-]" if marker == "slop" else "[!]"
    rel = os.path.relpath(file_path, root_dir)
    row = (
        f"{prefix} {rel[:48]:<50} | {ldr_str:<5} | {inflation_str:<5} | {ddc_str:<5} | {status.upper()}"
    )
    return marker, row


# ------------------------------------------------------------------
# Summary + exit
# ------------------------------------------------------------------

def _print_summary(total: int, slop_count: int, warning_count: int) -> None:
    print(_SEP)
    print("Scan Complete.")
    print(f"Total Files: {total}")
    print(f"Critical Slop: {slop_count}")
    print(f"Warnings: {warning_count}")


def _exit_on_slop(slop_count: int) -> None:
    if slop_count > 0:
        sys.exit(1)


# ------------------------------------------------------------------
# Orchestrator
# ------------------------------------------------------------------

def scan_project(root_dir: str) -> None:
    print(f"[*] Starting Slop Scan for: {root_dir}")
    detector = SlopDetector()
    python_files = _collect_python_files(root_dir, detector.config.get_ignore_patterns())
    print(f"[*] Found {len(python_files)} Python files.")

    print(_SEP)
    print(_HEADER)
    print(_DASH)

    slop_count = 0
    warning_count = 0

    for file_path in python_files:
        try:
            marker, row = _analyze_file(file_path, root_dir, detector)
            if marker == "slop":
                slop_count += 1
                print(row)
            elif marker == "warning":
                warning_count += 1
                print(row)
        except SyntaxError as e:
            print(f"[ERR] {os.path.basename(file_path)}: Syntax error - {e}")
        except Exception as e:
            print(f"[ERR] Failed to scan {file_path}: {e}")

    _print_summary(len(python_files), slop_count, warning_count)
    _exit_on_slop(slop_count)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_scan.py <project_path>")
        sys.exit(1)
    scan_project(sys.argv[1])
