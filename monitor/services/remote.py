"""Remote host helpers: SSH targets and read-only host probes over SSH.

Credentials are never stored in the repo or the database. The collector uses
the default key(s) in the container's ~/.ssh (mounted read-only by Compose) and
only trusts host keys already present in ~/.ssh/known_hosts.
"""

from __future__ import annotations

import paramiko
from django.conf import settings

PROBE_SCRIPT = """\
set -e
echo LOADAVG; cat /proc/loadavg
echo UPTIME; cut -d' ' -f1 /proc/uptime
echo MEMINFO; grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
echo CPU1; head -1 /proc/stat
sleep 1
echo CPU2; head -1 /proc/stat
echo NET; cat /proc/net/dev
echo DISK; df -P -B1 / | tail -1
echo NPROC; nproc
"""

SSH_TIMEOUT_SECONDS = 5
PROBE_TIMEOUT_SECONDS = 20


class RemoteProbeError(RuntimeError):
    """Raised when a remote host cannot be reached or probed."""


def remote_ssh_target(name: str) -> str | None:
    """SSH target (user@host) for a configured remote host, else None (local)."""
    return settings.REMOTE_HOSTS.get(name)


def docker_ssh_url(target: str) -> str:
    return f"ssh://{target}"


def run_probe(target: str, script: str = PROBE_SCRIPT) -> str:
    """Run a shell script on the remote host over SSH and return its stdout."""
    user, _, hostname = target.rpartition("@")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(
            hostname=hostname,
            username=user or None,
            timeout=SSH_TIMEOUT_SECONDS,
            banner_timeout=SSH_TIMEOUT_SECONDS,
            auth_timeout=SSH_TIMEOUT_SECONDS,
            look_for_keys=True,
            allow_agent=False,
        )
        stdin, stdout, stderr = client.exec_command(
            "sh -s",
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        stdin.write(script)
        stdin.channel.shutdown_write()
        output = stdout.read().decode(errors="replace")
        status = stdout.channel.recv_exit_status()
        if status != 0:
            detail = stderr.read().decode(errors="replace").strip()[:200]
            raise RemoteProbeError(f"probe exited {status}: {detail}")
        return output
    except (paramiko.SSHException, OSError) as exc:
        raise RemoteProbeError(str(exc) or exc.__class__.__name__) from exc
    finally:
        client.close()
