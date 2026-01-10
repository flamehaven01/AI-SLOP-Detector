import glob
import os
import sys

from slop_detector import SlopDetector


def scan_project(root_dir):
    print(f"[*] Starting Slop Scan for: {root_dir}")
    detector = SlopDetector()

    python_files = glob.glob(os.path.join(root_dir, "**", "*.py"), recursive=True)
    python_files = [f for f in python_files if "venv" not in f and "site-packages" not in f]

    print(f"[*] Found {len(python_files)} Python files.")

    slop_count = 0
    warning_count = 0

    print(f"{'='*80}")
    print(f"{'FILE':<50} | {'LDR':<5} | {'ICR':<5} | {'DDC':<5} | {'STATUS'}")
    print(f"{'-'*80}")

    for file_path in python_files:
        try:
            result = detector.analyze_file(file_path)

            # v2.x API
            ldr = result.ldr.ldr_score
            inflation = result.inflation.inflation_score
            ddc = result.ddc.usage_ratio
            status = result.status.value
            deficit = result.deficit_score

            rel_path = os.path.relpath(file_path, root_dir)

            # Formatting
            ldr_str = f"{ldr:.2f}"
            if ldr < 0.30:
                ldr_str = f"!!{ldr_str}"

            inflation_str = f"{inflation:.2f}" if inflation != float('inf') else "INF"
            if inflation > 1.0:
                inflation_str = f"!!{inflation_str}"

            ddc_str = f"{ddc:.2f}"
            if ddc < 0.50:
                ddc_str = f"!!{ddc_str}"

            # ASCII-safe markers
            if status == "critical_deficit":
                marker = "[-]"
                slop_count += 1
            elif status in ("suspicious", "inflated_signal", "dependency_noise"):
                marker = "[!]"
                warning_count += 1
            else:
                marker = "[+]"

            if status != "clean":
                print(f"{marker} {rel_path[:48]:<50} | {ldr_str:<5} | {inflation_str:<5} | {ddc_str:<5} | {status.upper()}")

        except SyntaxError as e:
            print(f"[ERR] {os.path.basename(file_path)}: Syntax error - {e}")
        except Exception as e:
            print(f"[ERR] Failed to scan {file_path}: {e}")

    print(f"{'='*80}")
    print("Scan Complete.")
    print(f"Total Files: {len(python_files)}")
    print(f"Critical Slop: {slop_count}")
    print(f"Warnings: {warning_count}")

    if slop_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_scan.py <project_path>")
        sys.exit(1)

    scan_project(sys.argv[1])
