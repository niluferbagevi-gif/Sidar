from pathlib import Path


def test_host_sandbox_installer_exists_and_is_executable():
    script = Path('scripts/install_host_sandbox.sh')
    assert script.exists()
    assert script.stat().st_mode & 0o111


def test_host_sandbox_installer_contains_core_steps():
    script = Path('scripts/install_host_sandbox.sh').read_text(encoding='utf-8')
    assert '--mode gvisor|kata|both' in script
    assert 'install_gvisor' in script
    assert 'install_kata' in script
    assert '/etc/docker/daemon.json' in script
    assert 'default-runtime' in script
    assert 'docker run --rm --runtime=runsc hello-world' in script
    assert 'docker run --rm --runtime=kata-runtime hello-world' in script