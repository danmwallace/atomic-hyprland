"""Resolve secret references in a registry server's env when the server starts.

A value is either a plain string or a reference, so files never hold secrets:
  {"keyring": {"service": S, "account": A}}  -> secret-tool lookup service S account A
  {"credential": N}  -> systemd-creds --user decrypt <config>/atomic-hyprland/credentials/N.cred -
"""
import subprocess

from . import paths


class SecretError(Exception):
    """A secret reference that could not be resolved; the message names the variable."""


def _lookup(name: str, ref: dict) -> str:
    if "keyring" in ref:
        attrs = ref["keyring"]
        argv = ["secret-tool", "lookup"]
        for key, value in attrs.items():
            argv += [str(key), str(value)]
    elif "credential" in ref:
        cred = paths.config_dir() / "credentials" / f"{ref['credential']}.cred"
        argv = ["systemd-creds", "--user", "decrypt", str(cred), "-"]
    else:
        raise SecretError(f"{name}: unknown secret reference {sorted(ref)}")
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SecretError(f"{name}: {exc}") from exc
    if out.returncode != 0 or not out.stdout:
        raise SecretError(f"{name}: lookup failed ({argv[0]} exit {out.returncode})")
    return out.stdout


def resolve_env(env: dict) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for name, value in env.items():
        resolved[name] = _lookup(name, value) if isinstance(value, dict) else str(value)
    return resolved
