from pathlib import Path


def test_dockerfile_installs_docker_cli_and_exposes_runtime_port():
    src = Path("Dockerfile").read_text(encoding="utf-8")
    assert "docker.io" in src
    assert "EXPOSE 7860" in src
    assert "PORT=7860" in src


def test_dockerfile_uses_non_root_user_and_creates_runtime_dirs():
    src = Path("Dockerfile").read_text(encoding="utf-8")
    assert "useradd -m -u 10001 sidaruser" in src
    assert "/app/sessions" in src
    assert "/app/chroma_db" in src
    assert "USER sidaruser" in src


def test_dockerfile_has_optional_rag_precache_build_args():
    src = Path("Dockerfile").read_text(encoding="utf-8")
    assert "ARG PRECACHE_RAG_MODEL=false" in src
    assert "ARG RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2" in src
    assert "SentenceTransformer('${RAG_EMBEDDING_MODEL}')" in src