"""BM25 backend compatibility exports."""

from .. import DocumentStore


class BM25BackendMixin(DocumentStore):
    """Compatibility mixin exposing BM25 capabilities via DocumentStore."""


__all__ = ["BM25BackendMixin"]
