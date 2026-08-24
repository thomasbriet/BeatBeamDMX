"""Pure upstreamprojectie naar het bestaande Show Interpreter-inputcontract."""

from dataclasses import dataclass
from typing import Optional

from show_interpreter_input import ShowInterpreterInput


@dataclass(frozen=True)
class ShowInterpreterEffectiveContext:
    """Reeds upstream-gevalideerde, effectieve actuele context zonder state."""

    source_is_valid: bool
    section_bucket: str
    energy_modifier: float


def project_show_interpreter_input(
    source: Optional[ShowInterpreterEffectiveContext],
) -> Optional[ShowInterpreterInput]:
    """Projecteer uitsluitend een expliciet geldige bron naar canonical input."""
    if source is None or source.source_is_valid is not True:
        return None
    return ShowInterpreterInput(
        section_bucket=source.section_bucket,
        energy_modifier=source.energy_modifier,
    )
