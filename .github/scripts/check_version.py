"""Check version declarations and an optional release tag without importing the engine."""
import argparse
import ast
import os
from pathlib import Path
import re
import tomllib


def project_version(root: Path, tag: str | None = None) -> str:
    with (root / "pyproject.toml").open("rb") as source:
        version = tomllib.load(source)["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("La version doit être stable et au format X.Y.Z.")
    module = ast.parse((root / "src/prono/__init__.py").read_text())
    versions = [ast.literal_eval(node.value) for node in module.body
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)]
    if versions != [version]:
        raise ValueError("pyproject.toml et prono.__version__ doivent porter la même version.")
    if tag is not None and tag != "v" + version:
        raise ValueError(f"Le tag doit être v{version}, reçu : {tag!r}.")
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME")
                        if os.environ.get("GITHUB_REF_TYPE") == "tag" else None)
    args = parser.parse_args()
    try:
        print(project_version(Path(__file__).resolve().parents[2], args.tag))
    except (ValueError, KeyError) as error:
        parser.exit(1, f"Version invalide : {error}\n")
