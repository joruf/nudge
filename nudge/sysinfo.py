"""Short descriptions of the machine, used for the header and the VM banner."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess

from .paths import IS_LINUX, IS_WINDOWS

# Names systemd-detect-virt reports, mapped to something a human recognises.
VM_LABELS = {
    "vmware": "VMware",
    "oracle": "VirtualBox",
    "microsoft": "Hyper-V",
    "kvm": "KVM/QEMU",
    "qemu": "QEMU",
    "xen": "Xen",
    "parallels": "Parallels",
    "bochs": "Bochs",
    "amazon": "Amazon EC2",
}


def detect_vm() -> str | None:
    """Return a friendly hypervisor name, or None when running on bare metal."""
    if not IS_LINUX or not shutil.which("systemd-detect-virt"):
        return None
    try:
        result = subprocess.run(
            ["systemd-detect-virt"], capture_output=True, text=True, timeout=3, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    if not value or value == "none":
        return None
    return VM_LABELS.get(value, value)


def platform_label() -> str:
    if IS_WINDOWS:
        release = platform.release()
        build = platform.version().split(".")[-1] if platform.version() else ""
        return f"Windows {release}" + (f" · Build {build}" if build else "")
    parts = ["Linux"]
    session = os.environ.get("XDG_SESSION_TYPE")
    if session:
        parts.append(session.upper() if session in ("x11",) else session.capitalize())
    desktop = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION")
    if desktop:
        parts.append(desktop.replace("X-", "").split(":")[0])
    return " · ".join(parts)
