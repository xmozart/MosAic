"""Principal and the single authorization hook (FUTURE_APPENDIX §1 guard).

v1 is single-user and ``check`` always allows, but every service method takes a
``Principal`` and every API request calls ``check``, so multi-user can be added later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("mosaic.authz")


@dataclass(frozen=True)
class Principal:
    user_id: int
    tenant_id: int | None = None


def check(principal: Principal, action: str, resource: str) -> None:
    """Authorize ``principal`` to perform ``action`` on ``resource``. Always allows in v1."""
    log.debug("authz", extra={"user_id": principal.user_id, "action": action, "resource": resource})
