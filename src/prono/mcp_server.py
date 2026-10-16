"""MCP stdio : exclusivement lecture locale. Aucun outil de placement ou d'écriture."""

from .workspace import Workspace
from .analysis import fixtures, analyze, backtest
from .journal import summary


def run(root):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ValueError(
            "Installer l'option MCP : python -m pip install -e '.[mcp]'."
        ) from None
    ws = Workspace(root)
    mcp = FastMCP("ai-prono-coach")

    @mcp.tool()
    def list_fixtures() -> list:
        """Lire les matchs et les cotes locales, avec leurs sources et dates."""
        return fixtures(ws)

    @mcp.tool()
    def analyze_match(event_id: str) -> dict:
        """Calculer une analyse pré-match sans écrire ni recommander une mise réelle."""
        return analyze(ws, event_id)

    @mcp.tool()
    def paper_summary() -> dict:
        """Lire les statistiques agrégées du journal fictif."""
        return summary(ws)

    @mcp.tool()
    def model_evaluation() -> dict:
        """Évaluer chronologiquement le modèle, sans simuler de rentabilité."""
        result = backtest(ws)
        result.pop("predictions")
        return result

    mcp.run(transport="stdio")
