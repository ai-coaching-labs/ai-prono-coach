"""Installation locale sans écrasement de configuration personnalisée."""

import argparse
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def write_if_absent(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"Conservé : {path}")
        return
    path.write_text(content, encoding="utf-8")


def install_mcp(workspace, python):
    """Actualiser uniquement la configuration standard générée, avec sauvegarde."""
    from prono.workspace import atomic_write

    path = workspace / ".mcp.json"
    entry = {
        "command": str(python),
        "args": ["-m", "prono.cli", "--workspace", str(workspace), "mcp"],
    }
    if not path.exists():
        write_if_absent(path, json.dumps({"mcpServers": {"prono": entry}}, indent=2) + "\n")
        return
    original = path.read_text(encoding="utf-8")
    try:
        config = json.loads(original)
        previous = config["mcpServers"]["prono"]
        command = Path(previous["command"])
        managed = (
            set(previous) == {"command", "args"}
            and previous["args"] == entry["args"]
            and command.parts[-3:] == (".venv", "bin", "python")
            and (command.parent.parent.parent / "src/prono/cli.py").is_file()
        )
    except (ValueError, KeyError, TypeError):
        managed = False
    if not managed:
        print(f"Configuration MCP personnalisée conservée : {path}")
        return
    if previous == entry:
        return
    backup = path.with_name(".mcp.json.before-engine-update")
    if backup.exists():
        index = 1
        while backup.with_name(backup.name + f".{index}").exists():
            index += 1
        backup = backup.with_name(backup.name + f".{index}")
    atomic_write(backup, original)
    config["mcpServers"]["prono"] = entry
    atomic_write(path, json.dumps(config, indent=2) + "\n")
    print(f"Moteur MCP actualisé : {path} (sauvegarde : {backup})")


def install_ide(workspace, ide, python):
    from prono.workspace import Workspace

    instructions = (ROOT / "AGENTS.md").read_text()
    enabled = Workspace(workspace).config["agents"]["enabled"]
    agents = [a for a in (ROOT / "agents").glob("*.md") if a.stem in enabled]
    skills = list((ROOT / "skills").glob("*/SKILL.md"))
    if ide in ("claude", "copilot", "opencode"):
        prefix = {"claude": ".claude", "copilot": ".github", "opencode": ".opencode"}[
            ide
        ]
        for agent in agents:
            body = agent.read_text()
            meta = f'---\nname: {agent.stem}\ndescription: "Spécialiste {agent.stem} AI Prono Coach"\n'
            if ide == "opencode":
                meta += "mode: subagent\n"
            write_if_absent(
                workspace
                / prefix
                / "agents"
                / (agent.stem + (".agent.md" if ide == "copilot" else ".md")),
                meta + "---\n\n" + body,
            )
        for skill in skills:
            write_if_absent(
                workspace / prefix / "skills" / skill.parent.name / "SKILL.md",
                skill.read_text(),
            )
    if ide == "claude":
        write_if_absent(workspace / "CLAUDE.md", instructions)
        install_mcp(workspace, python)
    elif ide == "copilot":
        write_if_absent(workspace / ".github/copilot-instructions.md", instructions)
    elif ide == "gemini":
        write_if_absent(workspace / "GEMINI.md", instructions)
        for skill in skills:
            body = skill.read_text().split("---", 2)[-1].strip()
            write_if_absent(
                workspace / ".gemini/commands" / (skill.parent.name + ".toml"),
                "description = "
                + json.dumps(skill.parent.name)
                + "\nprompt = "
                + json.dumps(body, ensure_ascii=False)
                + "\n",
            )
    elif ide == "cursor":
        write_if_absent(
            workspace / ".cursor/rules/prono.mdc",
            "---\nalwaysApply: true\n---\n\n" + instructions,
        )
    elif ide == "windsurf":
        write_if_absent(workspace / ".windsurfrules", instructions)
    # OpenCode/Copilot : MCP via configuration manuelle documentée, sans modifier leurs fichiers globaux.


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--ide",
        choices=[
            "all",
            "claude",
            "copilot",
            "opencode",
            "gemini",
            "cursor",
            "windsurf",
        ],
        default="all",
    )
    p.add_argument("--workspace", type=Path, default=ROOT)
    p.add_argument(
        "--mcp", action="store_true", help="Installer le SDK MCP optionnel depuis PyPI"
    )
    p.add_argument("--demo", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11+ requis.")
    target = a.workspace.resolve()
    if a.dry_run:
        print(
            json.dumps(
                {
                    "engine": str(ROOT),
                    "workspace": str(target),
                    "ide": a.ide,
                    "mcp": a.mcp,
                    "demo": a.demo,
                },
                indent=2,
            )
        )
        return
    # Installer en venv le moteur ; les configurations sont déployées seulement dans le workspace.
    env = ROOT / ".venv"
    if not env.exists():
        venv.create(env, with_pip=True)
    python = env / "bin/python"
    # Le moteur sans dépendance est importé via un .pth, y compris hors du dépôt.
    site = subprocess.check_output(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        text=True,
    ).strip()
    Path(site, "ai_prono_coach.pth").write_text(str(ROOT / "src") + "\n")
    if a.mcp:
        subprocess.run([str(python), "-m", "pip", "install", "mcp==1.30.0"], check=True)
    target.mkdir(parents=True, exist_ok=True)
    for folder in ("agents", "skills", "templates", "config", "docs"):
        for source in (ROOT / folder).rglob("*"):
            if source.is_file() and not any(
                part.startswith(".") or part == "__pycache__"
                for part in source.relative_to(ROOT / folder).parts
            ):
                if source.name == "workspace.user.toml":
                    continue
                destination = target / source.relative_to(ROOT)
                if source.resolve() != destination.resolve():
                    write_if_absent(destination, source.read_text())
    if ROOT != target:
        write_if_absent(target / "AGENTS.md", (ROOT / "AGENTS.md").read_text())
    for ide in (
        ["claude", "copilot", "opencode", "gemini", "cursor", "windsurf"]
        if a.ide == "all"
        else [a.ide]
    ):
        install_ide(target, ide, python)
    subprocess.run(
        [str(python), "-m", "prono.cli", "--workspace", str(target), "init"], check=True
    )
    if a.demo:
        subprocess.run(
            [str(python), "-m", "prono.cli", "--workspace", str(target), "demo"],
            check=True,
        )
    print(
        f"Prêt. Depuis {target}, lancer votre assistant de code.\nCLI : {python} -m prono.cli --workspace {target} fixtures"
    )
    if not a.mcp:
        print(
            "MCP non installé ; commandes terminal disponibles. Ajouter --mcp pour activer le serveur MCP."
        )


if __name__ == "__main__":
    main()
