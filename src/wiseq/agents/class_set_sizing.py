"""Class-set sizing for school orders.

WiseQ's public class-set page publishes a sizing table that tells a school
how many headsets to order.  The rule depends on the *use model*, and the
quantity is not simply "number of pupils" -- shared sets need spares,
per-pupil sets need a replacement allowance, and exam sets need a small
buffer.

Source (verified 2026-10-29):
  https://www.wiseq.nl/pages/klassenset-koptelefoons-kopen-school

    Gebruiksmodel                            Aantal
    Gedeelde set per lokaal                  Aantal devices + 2
    Gedeelde set per bouw (roulerend)       Grootste groep + 10%
    Eigen setje per leerling                 Leerlingaantal + 10%
    Alleen digitale toetsen                  Grootste toetsgroep + 3
    Individuele leerlingen met prikkelgevoeligheid   Per leerling

    "Reken op 10 tot 15% uitval per schooljaar bij intensief gedeeld
     gebruik. Kabels knikken, oorkussens slijten, exemplaren verdwijnen."

This is a SIZING rule, not a discount.  The 10-15% is the attrition
allowance for intensively shared headsets and is expressed as a percentage
of the group, while the table's own "+ 10%" rows are expressed as
percentages of the largest group.

Two distinct percentage sources are used here and they must not be
conflated:

  * the table's own buffer (+2, +10%, +3), and
  * the attrition allowance (10-15% per school year for intensive shared
    use).

The attrition allowance is applied to the table result ONLY when the
school declares intensive shared use, and it is reported separately so the
operator can see both numbers.

Everything here is a DETERMINISTIC calculation.  It proposes quantities;
it never prices them (pricing needs the staffel ladder, which is not
public) and it never sends anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from enum import Enum
from typing import Optional

# The attrition allowance WiseQ publishes for intensively shared headsets:
# "Reken op 10 tot 15% uitval per schooljaar bij intensief gedeeld gebruik."
ATTRITION_MIN_PCT = 10.0
ATTRITION_MAX_PCT = 15.0

# The buffer the table itself specifies for each use model.
SHARED_PER_ROOM_EXTRA = 2
EXAM_EXTRA = 3
PER_PUPIL_BUFFER_PCT = 10.0
BUILDING_BUFFER_PCT = 10.0


class UseModel(str, Enum):
    """The use models WiseQ's class-set page distinguishes."""

    SHARED_PER_ROOM = "shared_per_room"
    SHARED_PER_BUILDING = "shared_per_building"
    OWN_PAIR_PER_PUPIL = "own_pair_per_pupil"
    EXAMS_ONLY = "exams_only"
    INDIVIDUAL_SENSITIVE = "individual_sensitive"

    @property
    def label(self) -> str:
        return {
            UseModel.SHARED_PER_ROOM: "Gedeelde set per lokaal",
            UseModel.SHARED_PER_BUILDING: "Gedeelde set per bouw (roulerend)",
            UseModel.OWN_PAIR_PER_PUPIL: "Eigen setje per leerling",
            UseModel.EXAMS_ONLY: "Alleen digitale toetsen",
            UseModel.INDIVIDUAL_SENSITIVE: (
                "Individuele leerlingen met prikkelgevoeligheid"),
        }[self]

    @property
    def is_shared(self) -> bool:
        """Shared use models are the ones that suffer attrition."""
        return self in (UseModel.SHARED_PER_ROOM,
                        UseModel.SHARED_PER_BUILDING)


# Dutch and English aliases, so a school email can name the model however
# it likes.  Normalisation is done by the caller before lookup.
_USE_MODEL_ALIASES: dict[str, UseModel] = {
    # shared per room
    "gedeelde set per lokaal": UseModel.SHARED_PER_ROOM,
    "gedeelde set lokaal": UseModel.SHARED_PER_ROOM,
    "per lokaal": UseModel.SHARED_PER_ROOM,
    "shared per room": UseModel.SHARED_PER_ROOM,
    "shared set per classroom": UseModel.SHARED_PER_ROOM,
    # shared per building
    "gedeelde set per bouw": UseModel.SHARED_PER_BUILDING,
    "gedeelde set per bouw roulerend": UseModel.SHARED_PER_BUILDING,
    "per bouw": UseModel.SHARED_PER_BUILDING,
    "roulerend": UseModel.SHARED_PER_BUILDING,
    "shared per building": UseModel.SHARED_PER_BUILDING,
    # own pair per pupil
    "eigen setje per leerling": UseModel.OWN_PAIR_PER_PUPIL,
    "eigen setje": UseModel.OWN_PAIR_PER_PUPIL,
    "eigen koptelefoon per leerling": UseModel.OWN_PAIR_PER_PUPIL,
    "own pair per pupil": UseModel.OWN_PAIR_PER_PUPIL,
    "individual pair per pupil": UseModel.OWN_PAIR_PER_PUPIL,
    # exams only
    "alleen digitale toetsen": UseModel.EXAMS_ONLY,
    "digitale toetsen": UseModel.EXAMS_ONLY,
    "alleen toetsen": UseModel.EXAMS_ONLY,
    "exams only": UseModel.EXAMS_ONLY,
    "digital exams only": UseModel.EXAMS_ONLY,
    # individual / sensitive
    "individuele leerlingen met prikkelgevoeligheid": UseModel.INDIVIDUAL_SENSITIVE,
    "prikkelgevoeligheid": UseModel.INDIVIDUAL_SENSITIVE,
    "prikkelgevoelig": UseModel.INDIVIDUAL_SENSITIVE,
    "individual sensitive": UseModel.INDIVIDUAL_SENSITIVE,
    "sensitive": UseModel.INDIVIDUAL_SENSITIVE,
}


def _normalise(text: str) -> str:
    out = " ".join(text.strip().lower().split())
    return out


def resolve_use_model(text: str) -> Optional[UseModel]:
    """Map free text to a use model, or None when it is not recognisable.

    Longest alias first, so "eigen setje per leerling" wins over
    "eigen setje" and "gedeelde set per bouw" wins over "per bouw".
    """
    if not text:
        return None
    hay = _normalise(text)
    best: Optional[tuple[int, UseModel]] = None
    for alias, model in _USE_MODEL_ALIASES.items():
        if alias in hay:
            if best is None or len(alias) > best[0]:
                best = (len(alias), model)
    return best[1] if best else None


@dataclass
class SizingRequest:
    """Inputs for a class-set sizing calculation.

    pupils:       number of pupils the set is for.
    devices:      number of devices in the room.  Only meaningful for the
                  shared-per-room model, where the table says
                  "Aantal devices + 2".  When not given, the pupil count
                  is used as the base, because a room with N devices
                  generally serves N pupils.
    largest_group:
                  size of the largest group.  Only meaningful for the
                  shared-per-building and own-pair models, where the
                  table says "Grootste groep + 10%" / "Leerlingaantal
                  + 10%".  When not given, the pupil count is used.
    use_model:    the resolved use model.
    intensive_shared_use:
                  whether the school declares intensive shared use.  When
                  true, the published 10-15% attrition allowance is
                  applied on top of the table's own buffer.
    attrition_pct:
                  which end of the published 10-15% range to plan for.
                  Defaults to the conservative end (15).
    """

    pupils: int
    use_model: UseModel
    devices: Optional[int] = None
    largest_group: Optional[int] = None
    intensive_shared_use: bool = False
    attrition_pct: float = ATTRITION_MAX_PCT

    def __post_init__(self) -> None:
        if self.pupils <= 0:
            raise ValueError("pupils must be a positive count")
        if not (ATTRITION_MIN_PCT <= self.attrition_pct <= ATTRITION_MAX_PCT):
            raise ValueError(
                f"attrition_pct must be within the published "
                f"{ATTRITION_MIN_PCT}-{ATTRITION_MAX_PCT}% range")
        if self.use_model is UseModel.SHARED_PER_BUILDING and not self.largest_group:
            # not an error: fall back to pupils, but it is recorded below
            pass

    @property
    def _base(self) -> int:
        """The number the table's own buffer is applied to."""
        if self.use_model is UseModel.SHARED_PER_ROOM:
            return self.devices if self.devices else self.pupils
        if self.use_model is UseModel.SHARED_PER_BUILDING:
            return self.largest_group if self.largest_group else self.pupils
        if self.use_model is UseModel.OWN_PAIR_PER_PUPIL:
            # "Leerlingaantal + 10%" -- the pupil count, not the largest
            # group.  The largest group applies to the rolling-building
            # model only.
            return self.pupils
        if self.use_model is UseModel.EXAMS_ONLY:
            # "Grootste toetsgroep + 3" -- the base is the largest exam
            # group, not the whole school.
            return self.largest_group if self.largest_group else self.pupils
        return self.pupils


@dataclass
class SizingResult:
    use_model: UseModel
    base_quantity: int
    table_quantity: int
    attrition_quantity: int = 0
    total_quantity: int = 0
    attrition_pct: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "use_model": self.use_model.value,
            "use_model_label": self.use_model.label,
            "base_quantity": self.base_quantity,
            "table_quantity": self.table_quantity,
            "attrition_quantity": self.attrition_quantity,
            "total_quantity": self.total_quantity,
            "attrition_pct": self.attrition_pct,
            "notes": list(self.notes),
        }


def _round_up(value: Fraction) -> int:
    """Ceil a Fraction.

    Float arithmetic is wrong here: 100 * 1.10 is 110.00000000000001 in
    binary floating point, and math.ceil would turn that into 111
    spares for a 100-pupil class.  Exact rational arithmetic gives 110.
    """
    return -((-value.numerator) // value.denominator)


def _pct_of(base: int, pct: float) -> int:
    """base increased by pct%, rounded up, computed exactly."""
    return _round_up(Fraction(base) * Fraction(pct).limit_denominator(1000)
                     / Fraction(100))


def size_class_set(request: SizingRequest) -> SizingResult:
    """Apply WiseQ's published sizing table.

    Returns the table quantity and, separately, the attrition allowance
    so the operator can see how much of the order is a spare allowance
    rather than a pupil-facing device.
    """
    base = request._base
    notes: list[str] = []

    # --- does the published attrition allowance apply? ----------------
    #
    # This is decided FIRST, because when it applies it REPLACES the
    # table's own buffer.  Computing the table first and then replacing
    # the buffer would leave the "+2" or "+10%" in the total.
    use_attrition = (request.intensive_shared_use
                     and request.use_model.is_shared)
    if request.intensive_shared_use and not request.use_model.is_shared:
        notes.append(
            "Intensive shared use was declared, but the published attrition "
            "allowance applies to intensively SHARED headsets. This use "
            "model is not shared, so no attrition was applied.")

    if use_attrition:
        attrition_pct = request.attrition_pct
        attrition_qty = _pct_of(base, attrition_pct)
        table_qty = base + attrition_qty
        notes.append(
            f"Intensive shared use declared: the published attrition "
            f"allowance of {attrition_pct:g}% per school year replaces the "
            f"table's own buffer (not added on top of it). "
            f"WiseQ publishes {ATTRITION_MIN_PCT:g}-{ATTRITION_MAX_PCT:g}% "
            f"for intensively shared headsets.")
    else:
        attrition_pct = 0.0
        attrition_qty = 0

    # --- the table's own buffer -------------------------------------
    if not use_attrition and request.use_model is UseModel.SHARED_PER_ROOM:
        table_qty = base + SHARED_PER_ROOM_EXTRA
        notes.append(
            f"Gedeelde set per lokaal: {base} devices + "
            f"{SHARED_PER_ROOM_EXTRA} spare")
        if not request.devices:
            notes.append(
                "Device count not given; the pupil count was used as the "
                "base. Confirm the real device count before ordering.")
    elif not use_attrition and request.use_model is UseModel.SHARED_PER_BUILDING:
        table_qty = base + _pct_of(base, BUILDING_BUFFER_PCT)
        notes.append(
            f"Gedeelde set per bouw: largest group {base} + "
            f"{BUILDING_BUFFER_PCT:g}% buffer")
        if not request.largest_group:
            notes.append(
                "Largest group not given; the pupil count was used as the "
                "base. Confirm the real group sizes before ordering.")
    elif not use_attrition and request.use_model is UseModel.OWN_PAIR_PER_PUPIL:
        table_qty = base + _pct_of(base, PER_PUPIL_BUFFER_PCT)
        notes.append(
            f"Eigen setje per leerling: {base} pupils + "
            f"{PER_PUPIL_BUFFER_PCT:g}% buffer")
    elif not use_attrition and request.use_model is UseModel.EXAMS_ONLY:
        table_qty = base + EXAM_EXTRA
        notes.append(
            f"Alleen digitale toetsen: largest exam group {base} + "
            f"{EXAM_EXTRA}")
        if not request.largest_group:
            notes.append(
                "Largest exam group not given; the pupil count was used as "
                "the base. Confirm the real exam-group size before "
                "ordering.")
    elif not use_attrition:  # INDIVIDUAL_SENSITIVE
        table_qty = base
        notes.append(
            "Individuele leerlingen met prikkelgevoeligheid: one per pupil, "
            "no buffer published")

    # The attrition allowance was applied above (before the table
    # computation) so that it could REPLACE the table's own buffer
    # rather than being stacked on top of it.  Stacking would order
    # roughly 25% spares for a model whose published guidance is 10-15%,
    # and would present a school with a number WiseQ does not publish.

    # When the attrition allowance applied, table_qty ALREADY includes it,
    # so the total is table_qty.  Otherwise the total is the table
    # quantity plus nothing.
    total = table_qty
    return SizingResult(
        use_model=request.use_model,
        base_quantity=base,
        table_quantity=table_qty,
        attrition_quantity=attrition_qty,
        total_quantity=total,
        attrition_pct=attrition_pct,
        notes=notes,
    )


def suggest_models_for_pupils(pupils: int, age_group: str = "") -> list[str]:
    """Which headset models fit which age group.

    From the same page:
      Groep 1 t/m 3 (4-7 jaar)   -> WiseQ Junior (wired, hufterproof)
      Groep 4 t/m 8 (7-12 jaar)  -> WiseQ One (wired, flexible, mic) +
                                    wired earphones for per-pupil sets
      Voortgezet onderwijs        -> WiseQ One zwart-blauw, or adult
                                    headphones for older pupils
    """
    groups = {
        "groep 1": ["WiseQ Junior (bedraad, hufterproof)"],
        "groep 1 t/m 3": ["WiseQ Junior (bedraad, hufterproof)"],
        "groep 4": ["WiseQ One (bedraad, flexibel, met microfoon)"],
        "groep 4 t/m 8": ["WiseQ One (bedraad, flexibel, met microfoon)",
                          "Bedrade oordopjes (bij eigen setje per leerling)"],
        "voortgezet": ["WiseQ One zwart-blauw",
                        "Koptelefoons voor volwassenen (oudere leerlingen)"],
    }
    key = _normalise(age_group)
    for alias, models in groups.items():
        if alias in key:
            return list(models)
    if "4-7" in key or "4 - 7" in key:
        return list(groups["groep 1"])
    if "7-12" in key or "7 - 12" in key:
        return list(groups["groep 4 t/m 8"])
    return []
