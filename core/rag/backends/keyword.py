"""Keyword backend compatibility exports."""

from .. import DocumentStore


class KeywordBackendMixin(DocumentStore):
    """Compatibility mixin exposing keyword capabilities via DocumentStore."""


__all__ = ["KeywordBackendMixin"]
