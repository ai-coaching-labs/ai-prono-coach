"""Ressources de présentation incluses dans le paquet et la distribution Mac."""

from importlib.resources import files
from functools import lru_cache
import re


def asset_text(name):
    return files("prono").joinpath("assets", name).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def _html_fragments(name):
    """Fragments statiques uniquement ; aucune expression exécutée depuis le HTML."""
    return dict(
        re.findall(
            r"<!-- fragment: ([a-z0-9_]+) -->\n(.*?)\n<!-- /fragment -->",
            asset_text(name),
            re.DOTALL,
        )
    )


def html_fragment(file, name, /, **values):
    """Les appels Python fournissent des valeurs déjà échappées ou du HTML de confiance."""
    return _html_fragments(file)[name].format_map(values)
