from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, TypeVar

from .security_config import SecurityPolicyConfig

T = TypeVar("T")


@dataclass(frozen=True)
class BoundaryResult:
    boundary: str
    protected_input_required: bool
    hardware_tee: bool


@contextmanager
def trusted_computation_boundary(
    *,
    protected_input: bool,
    config: SecurityPolicyConfig | None = None,
) -> Iterator[BoundaryResult]:
    """Prototype trust boundary; does not claim hardware-backed confidential computing."""
    config = config or SecurityPolicyConfig()
    if not protected_input:
        raise ValueError("Trusted computation requires protected input")
    yield BoundaryResult(
        boundary=config.prototype_trusted_boundary,
        protected_input_required=True,
        hardware_tee=False,
    )


def execute_protected(operation: Callable[[], T], *, config: SecurityPolicyConfig | None = None) -> tuple[T, BoundaryResult]:
    with trusted_computation_boundary(protected_input=True, config=config) as boundary:
        return operation(), boundary
