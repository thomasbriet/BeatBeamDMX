"""Pure intent-continuity foundation voor Auto Show v0."""

from dataclasses import dataclass
import math
import numbers


# Dit zijn exact de output-buckets van beatbeam_app.phrase_bucket().  De module
# herhaalt ze bewust lokaal, omdat importeren van de runtime-monoliet hier geen
# veilige, side-effectvrije afhankelijkheid zou zijn.
SECTION_BUCKETS = frozenset({
    "intro", "verse", "build", "chorus", "drop", "down", "break", "outro", "unknown",
})
NEUTRAL_SECTION_BUCKET = "unknown"

# Bestaande begrensde modifier-semantiek: [-0.08, +0.08], met 0.0 als veilige
# uitkomst voor een onbruikbare invoer.
MINIMUM_ENERGY_MODIFIER = -0.08
MAXIMUM_ENERGY_MODIFIER = 0.08
NEUTRAL_ENERGY_MODIFIER = 0.0


def normalize_section_bucket(value):
    """Behoud de bestaande fail-closed bucketuitkomst voor ongeldige waarden."""
    if not isinstance(value, str):
        return NEUTRAL_SECTION_BUCKET
    bucket = value.strip().lower()
    return bucket if bucket in SECTION_BUCKETS else NEUTRAL_SECTION_BUCKET


def normalize_energy_modifier(value):
    """Pas de bestaande begrenzing toe; onbruikbare waarden worden neutraal."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return NEUTRAL_ENERGY_MODIFIER
    modifier = float(value)
    if not math.isfinite(modifier):
        return NEUTRAL_ENERGY_MODIFIER
    return max(MINIMUM_ENERGY_MODIFIER, min(MAXIMUM_ENERGY_MODIFIER, modifier))


@dataclass(frozen=True)
class ShowIntent:
    """Volledig gevalideerde v0-visual-intent, zonder uitvoering."""

    section_bucket: str
    energy_modifier: float

    def __post_init__(self):
        object.__setattr__(self, "section_bucket", normalize_section_bucket(self.section_bucket))
        object.__setattr__(self, "energy_modifier", normalize_energy_modifier(self.energy_modifier))


def neutral_show_intent():
    """Geef uitsluitend voor het ontbreken van eerdere state de veilige startstate."""
    return ShowIntent(NEUTRAL_SECTION_BUCKET, NEUTRAL_ENERGY_MODIFIER)


def resolve_show_intent(previous, candidate):
    """Behoud previous bij None; een expliciete candidate vervangt volledig."""
    if candidate is not None:
        if not isinstance(candidate, ShowIntent):
            raise TypeError("candidate must be a ShowIntent or None")
        return candidate
    if previous is not None:
        if not isinstance(previous, ShowIntent):
            raise TypeError("previous must be a ShowIntent or None")
        return previous
    return neutral_show_intent()
