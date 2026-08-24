"""Puur, immutable v0-inputcontract voor een toekomstige Show Interpreter."""

from dataclasses import dataclass

from show_intent import normalize_energy_modifier, normalize_section_bucket


@dataclass(frozen=True)
class ShowInterpreterInput:
    """Volledig gevalideerde actuele v0-muzikale context zonder state of uitvoering."""

    section_bucket: str
    energy_modifier: float

    def __post_init__(self):
        # De reeds overeengekomen v0-normalisatie blijft in één pure bron.
        object.__setattr__(self, "section_bucket", normalize_section_bucket(self.section_bucket))
        object.__setattr__(self, "energy_modifier", normalize_energy_modifier(self.energy_modifier))
