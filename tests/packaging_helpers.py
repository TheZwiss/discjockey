"""Loads the build scripts in packaging/. They are plain scripts, not a package: a `packaging` package would shadow
the PyPI `packaging` that pytest and PyInstaller import."""
import importlib.util
import sys

from discjockey import REPO

PACKAGING = REPO / "packaging"


def load(name: str):
    if str(PACKAGING) not in sys.path:
        sys.path.insert(0, str(PACKAGING))  # the scripts import each other (sign_app imports machos)
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PACKAGING / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
