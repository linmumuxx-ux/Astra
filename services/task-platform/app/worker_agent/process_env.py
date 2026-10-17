"""Environment handed to processes the Worker Agent starts.

The Agent's own token and Gateway address stay in the Agent process. A model
shell tool inherits the OpenCode process environment, so that process must not
see Worker or Gateway credentials.
"""

from __future__ import annotations

import os

_EXACT = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "TZ",
        "TMPDIR",
        "TMP",
        "TEMP",
        "SHELL",
    }
)
_PREFIXES = ("LC_", "XDG_", "SSL_CERT_")


def child_environ(source: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ if source is None else source
    return {
        key: value
        for key, value in env.items()
        if key in _EXACT or key.startswith(_PREFIXES)
    }
