import os
from pathlib import Path

project_path = "/projects/WareLogisticcBYS"
INDEX_SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".cs"}
EXCLUDE_DIRS = {"node_modules", "bin", "obj", "dist", ".next", "__pycache__", ".venv", "venv", "migrations"}

path_obj = Path(project_path)
print(f"Path: {path_obj}")
print(f"Exists: {path_obj.exists()}")

files = [
    str(path)
    for path in path_obj.rglob("*")
    if path.suffix in INDEX_SOURCE_EXTENSIONS
    and ".git" not in path.parts
    and not EXCLUDE_DIRS.intersection(path.parts)
]

print(f"Total files found: {len(files)}")
if len(files) > 0:
    print(f"Sample: {files[0]}")
else:
    # Let's see why it's empty
    all_files = list(path_obj.rglob("*"))
    print(f"Total rglob('*') count: {len(all_files)}")
    if all_files:
        print(f"Sample rglob: {all_files[0]} | suffix: {all_files[0].suffix} | parts: {all_files[0].parts}")
