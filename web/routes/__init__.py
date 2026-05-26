"""Route modules for Sidar web API."""

from typing import Any

from fastapi import APIRouter


class LegacyExportRouter(APIRouter):
    """APIRouter with typed legacy export registry for compatibility hooks."""

    legacy_exports: dict[str, Any]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.legacy_exports = {}
