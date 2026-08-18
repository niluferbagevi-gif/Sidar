"""Regression test for the installer's tty_notice()/read-prompt ordering fix.

A code review flagged that install_sidar.sh writes interactive-installer
prompts through two different channels: regular stdout/stderr (echo/info/
warn) flows through the async log-capture pipe set up by
`exec > >(mask_install_log_stream | tee -i >(sed ...)) 2>&1` (install_sidar.sh),
while each `read -r -p "..." 2>/dev/tty` call bypasses that pipe entirely and
writes its prompt straight to the controlling terminal (so the prompt stays
visible even when stdout/stderr are independently redirected to a file).

Two independent channels racing to the same terminal is fine as long as the
async one is always faster — but it is not: on slow-fork platforms (WSL2 is
the reviewer's specific example) the log-capture pipeline can lag enough for
the read's prompt to become visible before an immediately-preceding
`echo`/`info` line explaining what the prompt is asking for. See the
tests/shell/*.bats coverage for the individual call sites; this test proves
the underlying mechanism (tty_notice() sharing read's own /dev/tty channel)
actually removes the race, using a real pty and an artificially slow-starting
log pipe reader to model a WSL2-style fork delay deterministically.
"""

from __future__ import annotations

import os
import pty
import select
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Stands in for the real `mask_install_log_stream | tee -i >(sed ...)`
# pipeline's fork/startup latency on a slow-fork platform.
_SLOW_PIPE_READER = "sleep 0.3 && cat"

_COMMON_SETUP = f"""
cd {REPO_ROOT}
export SIDAR_INSTALL_TEST_MODE=1
source ./install_sidar.sh >/dev/null 2>&1
exec > >({_SLOW_PIPE_READER}) 2>&1
"""


def _run_under_pty(
    script: str, feed: bytes, feed_after: float = 0.15, timeout: float = 2.0
) -> bytes:
    """Run `script` under a real pty and return everything written to it."""
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - child process, replaced by exec
        os.execvp("bash", ["bash", "-c", script])

    start = time.time()
    chunks: list[bytes] = []
    fed = False
    try:
        while time.time() - start < timeout:
            ready, _, _ = select.select([fd], [], [], 0.02)
            if fd in ready:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
            if not fed and time.time() - start > feed_after:
                try:
                    os.write(fd, feed)
                except OSError:
                    pass
                fed = True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
    return b"".join(chunks)


@pytest.mark.skipif(
    not (REPO_ROOT / "install_sidar.sh").is_file(), reason="install_sidar.sh not found"
)
def test_tty_notice_keeps_context_ordered_before_the_prompt_it_explains() -> None:
    """The fixed pattern: tty_notice() shares read's own /dev/tty channel."""
    script = _COMMON_SETUP + 'tty_notice "MENU-TEXT"\nread -r -p "PROMPT: " x 2>/dev/tty\n'
    output = _run_under_pty(script, b"answer\n")

    prompt_index = output.find(b"PROMPT:")
    menu_index = output.find(b"MENU-TEXT")

    assert prompt_index != -1, "prompt never appeared on the pty"
    assert menu_index != -1, "tty_notice() output never appeared on the pty"
    assert menu_index < prompt_index, (
        "tty_notice() output must appear before the prompt that follows it "
        f"(menu_index={menu_index}, prompt_index={prompt_index})"
    )


def test_plain_echo_before_the_same_prompt_can_lose_the_ordering_race() -> None:
    """Characterizes the bug tty_notice() fixes.

    Without tty_notice(), the context line goes through the (here,
    artificially delayed) async log pipe while `read -r -p ... 2>/dev/tty`
    bypasses it — so the prompt can become visible with its explanatory line
    nowhere to be seen yet. This is the failure mode the review comment
    described for WSL2; it is intentionally reproduced here (not asserted
    as desired behavior) to prove the fixed test above is exercising a real
    mechanism rather than a tautology.
    """
    script = _COMMON_SETUP + 'echo "MENU-TEXT"\nread -r -p "PROMPT: " x 2>/dev/tty\n'
    output = _run_under_pty(script, b"answer\n")

    prompt_index = output.find(b"PROMPT:")
    menu_index = output.find(b"MENU-TEXT")

    assert prompt_index != -1, "prompt never appeared on the pty"
    # The whole point: under the old plain-echo pattern, the prompt can win
    # the race against its own explanatory text (menu_index is -1, i.e. not
    # observed yet, or arrives after the prompt).
    assert menu_index == -1 or menu_index > prompt_index


# Every interactive `read -r ... -p "..." 2>/dev/tty` call site whose
# immediately-preceding context line(s) need the same synchronous /dev/tty
# channel to stay correctly ordered. Each entry is (file, marker-that-must-
# precede-the-read-in-the-file). This is a text-level regression lock: it
# does not re-run the pty proof above per call site, it just prevents someone
# from reintroducing the plain echo/info + `read ... 2>/dev/tty` pattern at
# one of these locations without noticing.
_GUARDED_PROMPT_SITES = (
    (
        "scripts/install_modules/utils/python_env.sh",
        "} &> /dev/tty",
        '-p "Seçim [1-7, varsayılan 2]: " profile_choice 2>/dev/tty',
    ),
    (
        "scripts/install_modules/phases/03_system.sh",
        "tty_notice \"Lütfen Docker Desktop'ı manuel başlatın",
        '-p "Docker hazır olduktan sonra [ENTER] tuşuna basın..." 2>/dev/tty',
    ),
    (
        "scripts/install_modules/phases/03_system.sh",
        'tty_notice "Yukarıdaki 1-4 numaralı adımları tamamladıktan sonra devam edin."',
        '-p "Entegrasyonu tamamladıktan sonra devam etmek için [ENTER] tuşuna basın..." 2>/dev/tty',
    ),
    (
        "scripts/install_modules/phases/06_services.sh",
        "tty_notice \"Lütfen Docker Desktop'ı açın/yeniden başlatın",
        '-p "Devam etmek için [ENTER] tuşuna basın..." 2>/dev/tty',
    ),
    (
        "scripts/install_modules/phases/08_env.sh",
        "} &> /dev/tty",
        '-p "Seçiminiz (1 veya 2, varsayılan=1): " env_choice 2>/dev/tty',
    ),
    (
        "scripts/install_modules/phases/11_post_install.sh",
        "} &> /dev/tty",
        '-p "Seçim [1/2, varsayılan=1]: " runtime_answer 2>/dev/tty',
    ),
)


@pytest.mark.parametrize(
    "relative_path,marker,read_line",
    _GUARDED_PROMPT_SITES,
    ids=[f"{path}:{marker[:24]}" for path, marker, _ in _GUARDED_PROMPT_SITES],
)
def test_interactive_prompt_sites_route_their_context_through_dev_tty(
    relative_path: str, marker: str, read_line: str
) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    assert read_line in text, f"expected read call not found in {relative_path}"
    marker_index = text.index(marker)
    read_index = text.index(read_line)
    assert marker_index < read_index, (
        f"{relative_path}: the /dev/tty-routed context ({marker!r}) must appear "
        "before the read it explains, not after"
    )
    # And the marker must actually be the line immediately feeding into that
    # read (no unrelated code sneaking back onto the async pipe in between).
    between = text[marker_index:read_index]
    assert between.count("\n") <= 6, (
        f"{relative_path}: unexpectedly large gap between the tty-routed context "
        "and the read it's meant to precede — verify nothing async crept back in"
    )
