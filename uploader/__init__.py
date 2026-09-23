"""Building blocks of ``github_upload.py`` (the Sidar GitHub upload tool).

``github_upload.py`` stays the entrypoint and keeps same-named thin wrappers that
pass their collaborators (``run_command`` and sibling helpers) at call time, so
tests that monkeypatch ``github_upload.*`` keep taking effect.
"""
