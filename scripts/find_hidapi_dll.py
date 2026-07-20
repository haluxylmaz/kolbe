# Find hidapi.dll on this machine (run from the project root):
#   .\.venv\Scripts\python.exe scripts\find_hidapi_dll.py

import os
import sys
from pathlib import Path

sp = Path(sys.prefix) / "Lib" / "site-packages"
names = ("hidapi.dll", "libhidapi-0.dll")
found = []
for root, _dirs, files in os.walk(sp):
    for name in files:
        if name.lower() in names or (name.lower().startswith("hidapi") and name.lower().endswith(".dll")):
            found.append(Path(root, name).resolve())

print(f"site-packages: {sp}")
if not found:
    print("NO hidapi.dll found under site-packages")
    sys.exit(1)

for path in found:
    print(path)
print()
print("Use this in the .spec binaries list:")
print(f"  binaries=[(r'{found[0]}', '.')],")
