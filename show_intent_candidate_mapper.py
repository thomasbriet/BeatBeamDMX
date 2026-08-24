"""Pure v0-mapping van beschikbare interpreterinput naar een intent-candidate."""

from show_intent import ShowIntent
from show_interpreter_input import ShowInterpreterInput
from typing import Optional


def map_show_intent_candidate(source: Optional[ShowInterpreterInput]) -> Optional[ShowIntent]:
    """Geef None door of maak een nieuwe intent met exact de canonical invoer."""
    if source is None:
        return None
    return ShowIntent(
        section_bucket=source.section_bucket,
        energy_modifier=source.energy_modifier,
    )
