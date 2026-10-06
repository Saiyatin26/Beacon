import sys
import shutil
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from certification.adapters import check_cobol_cics_runtime
avail, diag, details = check_cobol_cics_runtime()
print("COBOL RUNTIME AVAILABLE:", avail)
print("DIAGNOSTICS:", diag)
print("DETAILS:", details)

# Check WSL directly
try:
    res = subprocess.run(["wsl", "-l", "-v"], capture_output=True, text=True, timeout=5)
    print("WSL DISTROS:\n", res.stdout)
except Exception as e:
    print("WSL ERROR:", e)

# Check cobc in wsl
try:
    res = subprocess.run(["wsl", "-d", "Ubuntu", "--", "which", "cobc"], capture_output=True, text=True, timeout=5)
    print("WSL COBC:", res.stdout.strip(), "returncode:", res.returncode)
    if res.returncode == 0:
        v_res = subprocess.run(["wsl", "-d", "Ubuntu", "--", "cobc", "--version"], capture_output=True, text=True, timeout=5)
        print("WSL COBC VERSION:\n", v_res.stdout)
except Exception as e:
    print("WSL COBC ERROR:", e)
