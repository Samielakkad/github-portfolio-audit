"""Evidence-based GitHub portfolio audits."""

from .audit import audit_portfolio
from .client import GitHubClient

__version__ = "0.1.1"
__all__ = ["GitHubClient", "audit_portfolio", "__version__"]
