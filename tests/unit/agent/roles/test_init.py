"""agent/roles/__init__.py için import ve __all__ contract testleri."""

import agent.roles as roles_pkg
from agent.roles import (
    CoderAgent,
    CoverageAgent,
    PoyrazAgent,
    QAAgent,
    ResearcherAgent,
    ReviewerAgent,
)

_EXPECTED_ROLES = {
    "CoderAgent",
    "ResearcherAgent",
    "ReviewerAgent",
    "PoyrazAgent",
    "QAAgent",
    "CoverageAgent",
}


def test_all_role_classes_importable_by_name():
    """Her rol sınıfı doğrudan agent.roles paketinden import edilebilmelidir."""
    assert CoderAgent is not None
    assert ResearcherAgent is not None
    assert ReviewerAgent is not None
    assert PoyrazAgent is not None
    assert QAAgent is not None
    assert CoverageAgent is not None


def test_all_exports_are_classes():
    """__all__ içindeki her isim gerçek bir sınıf (type) olmalıdır."""
    for cls_name in roles_pkg.__all__:
        cls = getattr(roles_pkg, cls_name)
        assert isinstance(cls, type), f"'{cls_name}' bir sınıf (type) olmalı, değil: {type(cls)}"


def test_all_list_contains_exactly_expected_roles():
    """__all__ tam olarak beklenen rol sınıflarını içermelidir — ne eksik ne fazla."""
    assert set(roles_pkg.__all__) == _EXPECTED_ROLES


def test_role_classes_accessible_via_package_attribute():
    """Rol sınıflarına paket niteliği (getattr) ile erişilebilmelidir."""
    for cls_name in _EXPECTED_ROLES:
        cls = getattr(roles_pkg, cls_name, None)
        assert cls is not None, f"'{cls_name}' agent.roles üzerinden erişilemiyor"
        assert isinstance(cls, type)
