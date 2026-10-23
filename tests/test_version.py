import re
import tomllib

import discjockey
from discjockey import REPO


def test_one_version_source():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == discjockey.__version__


def test_the_version_is_semantic():
    assert re.fullmatch(r"\d+\.\d+\.\d+", discjockey.__version__)
