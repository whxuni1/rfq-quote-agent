from __future__ import annotations

from typing import Any

import structlog


def get_logger(module: str, **ctx: Any) -> Any:
    """Every log line carries `module`; callers bind goal_id / step_id as they go."""
    return structlog.get_logger().bind(module=module, **ctx)
