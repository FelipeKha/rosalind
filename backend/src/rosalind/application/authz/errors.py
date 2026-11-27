"""Access-policy enforcement errors."""

from __future__ import annotations


class AccessPolicyError(Exception):
    """An active policy could not be loaded or validated.

    The request must fail closed; implicit permit-all is only for the case where
    no permit policies exist, never for an evaluation failure.
    """
