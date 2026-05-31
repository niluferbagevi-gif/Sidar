from managers.image_resolver import canonical_project_image_alias, is_gpu_project_image


def test_canonical_project_image_alias_handles_empty_unknown_and_default_tag() -> None:
    prefixes = {"legacy-sidar": "sidar"}

    assert canonical_project_image_alias("   ", legacy_prefixes=prefixes) is None
    assert canonical_project_image_alias("external:latest", legacy_prefixes=prefixes) is None
    assert (
        canonical_project_image_alias(" legacy-sidar ", legacy_prefixes=prefixes) == "sidar:latest"
    )
    assert (
        canonical_project_image_alias("legacy-sidar:dev", legacy_prefixes=prefixes) == "sidar:dev"
    )


def test_is_gpu_project_image_normalizes_repository_name() -> None:
    assert is_gpu_project_image(" SIDAR-GPU:latest ") is True
    assert is_gpu_project_image("sidar:latest") is False
