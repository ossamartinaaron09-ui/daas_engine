"""FastAPI delivery application package for DaaS MVP."""

from daas.api.main import app, create_app, get_db

__all__ = ["app", "create_app", "get_db"]
