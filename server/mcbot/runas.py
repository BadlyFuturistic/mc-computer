"""Run a tool as the service account.

The memory database belongs to mcbot, and SQLite needs write access to the directory
as well as the file. An admin running a tool by hand is therefore refused with a bare
"readonly database", which says nothing about the cause.

Any tool that writes to the database calls ensure_service_user() first. It re-executes
itself through sudo as mcbot, which a sudoers rule permits for a fixed list of tools.
"""
import os
import pwd
import sys

SERVICE_USER = "mcbot"
SERVICE_HOME = "/var/lib/mcbot"


def ensure_service_user() -> None:
    """Re-exec as the service account if we are not already it."""
    try:
        target = pwd.getpwnam(SERVICE_USER).pw_uid
    except KeyError:
        return                                  # no such account; nothing to do
    if os.geteuid() in (target, 0):
        os.environ.setdefault("HOME", SERVICE_HOME)
        return

    script = os.path.abspath(sys.argv[0])
    rc = os.spawnvp(os.P_WAIT, "sudo",
                    ["sudo", "-n", "-u", SERVICE_USER, f"HOME={SERVICE_HOME}",
                     script, *sys.argv[1:]])
    if rc == 0:
        sys.exit(0)
    sys.exit(
        f"could not run as {SERVICE_USER}.\n"
        f"  This tool writes to the assistant's database, which only {SERVICE_USER} "
        f"may change.\n"
        f"  Add this line to /etc/sudoers.d/mcbot:\n"
        f"    {os.environ.get('USER', 'you')} ALL=({SERVICE_USER}) NOPASSWD: SETENV: {script}"
    )
