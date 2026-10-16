"""Verify the bundled engine and public resources without extracting the archive."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import plistlib
import tarfile

from check_version import project_version


def verify_app(root: Path, app: Path) -> None:
    version = project_version(root)
    with (app / "Contents/Info.plist").open("rb") as source:
        info = plistlib.load(source)
    archive = app / "Contents/Resources/engine.tar.gz"
    if info["CFBundleShortVersionString"] != version:
        raise ValueError("La version de l’application diffère du projet.")
    if info["PronoEngineBuild"] != hashlib.sha256(archive.read_bytes()).hexdigest():
        raise ValueError("L’empreinte du moteur ne correspond pas au bundle.")
    allowed = {"src", "scripts", "agents", "skills", "templates", "docs", "config",
               "AGENTS.md", "README.md", "LICENSE", "install.sh", "pyproject.toml"}
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            path = PurePosixPath(member.name)
            if not path.parts:
                continue
            if path.is_absolute() or ".." in path.parts or path.parts[0] not in allowed:
                raise ValueError(f"Chemin inattendu dans le moteur : {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"Lien inattendu dans le moteur : {member.name}")
            if path.parts[0] == "config" and path.parts != ("config",) and path.as_posix() != "config/workspace.toml":
                raise ValueError(f"Configuration privée dans le moteur : {member.name}")
        resources = [root / "AGENTS.md", root / "README.md", root / "LICENSE", root / "pyproject.toml",
                     root / "config/workspace.toml", root / "agents/coach.md",
                     *sorted((root / "src/prono").glob("*.py")),
                     *sorted((root / "src/prono/assets").glob("*"))]
        for source in resources:
            if not source.is_file():
                continue
            name = source.relative_to(root).as_posix()
            with bundle.extractfile("./" + name) as packaged:
                if packaged.read() != source.read_bytes():
                    raise ValueError(f"Ressource absente ou différente : {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    verify_app(Path(__file__).resolve().parents[2], args.app)
    print("Version, empreinte, contenu et ressources du moteur vérifiés.")
