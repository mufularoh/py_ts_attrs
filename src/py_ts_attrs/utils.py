from types import ModuleType
from typing import List
from pathlib import Path
import importlib
import importlib.util
import sys

from contextlib import contextmanager

@contextmanager
def add_to_path(p: Path):
    old_path = sys.path
    sys.path = sys.path[:] 
    sys.path.insert(0, p.resolve().as_posix())
    try:
        yield
    finally:
        sys.path = old_path

def import_modules(files: List[Path], package_root: Path) -> List[ModuleType]:
    ret: List[ModuleType] = []
    with add_to_path(package_root):
        for file in files:
            spec = importlib.util.spec_from_file_location(file.stem, file.resolve().as_posix())
            assert spec is not None
            assert spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            ret.append(module)
    return ret

