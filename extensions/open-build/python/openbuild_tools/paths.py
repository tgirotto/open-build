#---------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for license information.
#---------------------------------------------------------------------------------------------
"""Workspace path checks for tool arguments."""

from __future__ import annotations

import os
from pathlib import Path


class WorkspacePathError(Exception):
    """A tool argument resolved outside the workspace."""


def workspace_from_env() -> Path:
    raw = os.environ.get("OPENBUILD_WORKSPACE", "").strip()
    if not raw:
        raise RuntimeError("OPENBUILD_WORKSPACE is not set")
    return Path(raw)


def resolve_workspace_path(workspace: Path, user_path: str) -> Path:
    """Resolve a user path and reject anything outside the workspace."""
    if not isinstance(user_path, str) or not user_path.strip():
        raise WorkspacePathError("path is required")
    candidate = Path(user_path)
    root = workspace.resolve()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise WorkspacePathError("path escapes the workspace")
    return resolved


def relative_path(workspace: Path, path: Path) -> str:
    return path.resolve().relative_to(workspace.resolve()).as_posix()
