import os
import sys
import glob
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
    print(f"{'FILE':<50} | {'LDR':<5} | {'HYPE':<5} | {'GHOSTS'}")
    print(f"{'-'*80}")
    
    for file_path in python_files:
        try:
            result = detector.analyze_file(file_path)
            
            if result.get("status") == "error":
                print(f"[ERR] {os.path.basename(file_path)}: {result.get('msg')}")
                continue
                
            ldr = result['density_score']
            hype = result['hype_score']
            ghosts = len(result['ghost_imports'])
            is_slop = result['is_slop']
            
            rel_path = os.path.relpath(file_path, root_dir)
            
            # Formatting
            ldr_str = f"{ldr:.2f}"
            if ldr < 0.15: ldr_str = f"!!{ldr_str}"
            
            hype_str = f"{hype:.2f}"
            if hype > 3.0: hype_str = f"!!{hype_str}"
            
            ghost_str = str(ghosts)
            if ghosts > 0: ghost_str = f"({ghosts}) {','.join(result['ghost_imports'][:3])}"
            
            if is_slop:
                print(f"❌ {rel_path[:48]:<50} | {ldr_str:<5} | {hype_str:<5} | {ghost_str}")
                slop_count += 1
            elif ghosts > 0 or ldr < 0.3:
                print(f"⚠️ {rel_path[:48]:<50} | {ldr_str:<5} | {hype_str:<5} | {ghost_str}")
                warning_count += 1
            else:
                # Optional: Don't print clean files to reduce noise, or print with checkmark
                # print(f"✅ {rel_path[:48]:<50} | {ldr_str:<5} | {hype_str:<5} | {ghost_str}")
                pass

        except Exception as e:
            print(f"[ERR] Failed to scan {file_path}: {e}")

    print(f"{'='*80}")
    print(f"Scan Complete.")
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
