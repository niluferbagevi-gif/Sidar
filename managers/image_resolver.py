from __future__ import annotations


def canonical_project_image_alias(
    image: str, *, legacy_prefixes: dict[str, str]
) -> str | None:
    """Convert legacy Sidar image names to canonical repository tags."""
    candidate = image.strip()
    if not candidate:
        return None
    repository, _separator, tag = candidate.partition(":")
    canonical_repository = legacy_prefixes.get(repository)
    if canonical_repository is None:
        return None
    return f"{canonical_repository}:{tag or 'latest'}"


def is_gpu_project_image(image: str) -> bool:
    """Return True when docker image targets Sidar GPU runtime images."""
    repository = image.strip().split(":", 1)[0].lower()
    return repository.startswith("sidar-gpu")
