"""Gridfinity dimensional specification.

All values in millimetres. Kept in one place so a user with a differently
calibrated printer can adjust them without hunting through the builders.

The base profile is the canonical Gridfinity foot, described bottom-up as
three stages. Each stage is (rise, inward_inset): the inset is how far the
cross-section is pulled in, relative to the full ``BIN_SIZE`` footprint, at
the *bottom* of that stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Grid -------------------------------------------------------------------

GRID_PITCH = 42.0          # centre-to-centre spacing of grid cells
BIN_CLEARANCE = 0.5        # total clearance, i.e. 0.25 mm per side
BIN_SIZE = GRID_PITCH - BIN_CLEARANCE   # 41.5 mm outer footprint of one cell
HEIGHT_UNIT = 7.0          # one "u" of bin height

# --- Base foot profile ------------------------------------------------------
# bottom -> top: 0.8 chamfer, 1.8 vertical, 2.15 chamfer. Total rise 4.75 mm,
# total inset 2.95 mm, so the foot's bottom face measures 41.5 - 5.9 = 35.6 mm.
BASE_STAGES: tuple[tuple[float, float], ...] = (
    (0.8, 2.95),   # 45 deg chamfer, from inset 2.95 up to inset 2.15
    (1.8, 2.15),   # vertical
    (2.15, 2.15),  # 45 deg chamfer, from inset 2.15 up to inset 0.0
)
BASE_HEIGHT = sum(rise for rise, _ in BASE_STAGES)   # 4.75
BASE_MAX_INSET = BASE_STAGES[0][1]                   # 2.95

OUTER_RADIUS = 4.0         # corner radius at the full 41.5 mm footprint

# --- Stacking lip -----------------------------------------------------------
# The lip cavity is the base profile mirrored, so an upper bin's foot drops in.
# It is 4.4 mm rather than the base's 4.75 mm: the foot registers on the 45 deg
# chamfers and must not bottom out, and a full-height mirror would taper the rim
# to nothing. What is left at the very top is a 0.1 mm knife edge, which is what
# the stock profile gives you; ``lip_top_rim`` trades a little seating depth for
# a rim that actually prints.
LIP_HEIGHT = 4.4
LIP_CLEARANCE = 0.25       # per side, between a seated foot and the lip
LIP_STAGES: tuple[tuple[float, float], ...] = (
    (0.8, 2.95),
    (1.8, 2.15),
    (1.8, 2.15),
)
LIP_TOP_INSET = 0.35       # inset remaining at the top of the lip cavity

# --- Walls / floor ----------------------------------------------------------
DEFAULT_WALL = 1.2
DEFAULT_FLOOR = 1.4        # solid material above the top of the base foot

# --- Magnets & screws -------------------------------------------------------
MAGNET_DIAMETER = 6.5
MAGNET_DEPTH = 2.4
SCREW_DIAMETER = 3.0
SCREW_DEPTH = 6.0
# offset of a hole centre from the grid cell centre, along X and Y
HOLE_OFFSET = 13.0

# --- Rendering quality ------------------------------------------------------
CORNER_SEGMENTS = 12       # polyline segments per 90 deg corner arc


@dataclass(slots=True)
class BinSpec:
    """Everything the bin builder needs, in one serialisable object."""

    grid_x: int = 1
    grid_y: int = 1
    height_units: float = 3.0

    # shell
    wall_thickness: float = DEFAULT_WALL
    floor_thickness: float = DEFAULT_FLOOR
    solid: bool = False              # skip the cavity entirely; cutouts only

    # top rim
    stacking_lip: bool = True
    lip_style: str = "reduced"       # normal | reduced | none
    lip_top_rim: float = 0.6         # flat rim left at the top edge (reduced)
    height_includes_lip: bool = False
    lip_support: bool = True   # 45 deg chamfer under the lip seat

    # underside
    magnet_holes: bool = False
    magnet_diameter: float = MAGNET_DIAMETER
    magnet_depth: float = MAGNET_DEPTH
    screw_holes: bool = False
    screw_diameter: float = SCREW_DIAMETER
    screw_depth: float = SCREW_DEPTH

    # label tab along the +Y edge
    label_tab: bool = False
    label_tab_width: float = 12.0
    label_tab_angle: float = 36.0

    # fidelity
    corner_segments: int = CORNER_SEGMENTS

    # overrides for a non-standard grid
    grid_pitch: float = GRID_PITCH
    bin_clearance: float = BIN_CLEARANCE

    @property
    def cell_size(self) -> float:
        return self.grid_pitch - self.bin_clearance

    @property
    def outer_width(self) -> float:
        return self.grid_x * self.grid_pitch - self.bin_clearance

    @property
    def outer_depth(self) -> float:
        return self.grid_y * self.grid_pitch - self.bin_clearance

    @property
    def lip_height(self) -> float:
        if not self.stacking_lip or self.lip_style == "none":
            return 0.0
        return LIP_HEIGHT

    @property
    def body_top(self) -> float:
        """Z of the rim that cutouts are measured down from.

        Height units define the *stacking pitch*: a stacked bin's foot rests at
        ``height_units * 7`` above this bin's own foot. The lip therefore adds
        on top of that by default, making a lone 3u bin 21 + 4.4 mm tall. Set
        ``height_includes_lip`` to instead keep the overall height at 7u and
        give up that much interior depth.
        """
        pitch = self.height_units * HEIGHT_UNIT
        return pitch - self.lip_height if self.height_includes_lip else pitch

    @property
    def total_height(self) -> float:
        """Overall exterior height, lip included."""
        return self.body_top + self.lip_height

    @property
    def usable_top_z(self) -> float:
        return self.body_top

    @property
    def inner_floor_z(self) -> float:
        return BASE_HEIGHT + self.floor_thickness


@dataclass(slots=True)
class CutoutSpec:
    """One pocket in the bin."""

    polygon: list[tuple[float, float]] = field(default_factory=list)
    holes: list[list[tuple[float, float]]] = field(default_factory=list)

    # placement, in bin-local millimetres measured from the bin's centre
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0            # degrees, counter-clockwise

    depth: float = 10.0
    clearance: float = 0.4           # uniform in-plane offset
    corner_radius: float = 0.0       # plan-view rounding
    draft_angle: float = 0.0         # degrees; widens the pocket towards the top
    bottom_radius: float = 0.0       # rounding where walls meet the pocket floor

    through: bool = False            # cut all the way through the floor
    finger_scoop: bool = False       # ramp on the +Y side for lifting the part
    finger_scoop_radius: float = 8.0
    finger_notch: bool = False       # semicircular notch in the pocket wall
    finger_notch_diameter: float = 18.0

    # a captured 3D scan used instead of the extruded polygon
    mesh_source: str | None = None   # storage key of a scan mesh
    mesh_open_top: bool = True       # sweep the scan upwards to kill undercuts
    mesh_flip_z: bool = True         # the scan was taken with the object upside down

    enabled: bool = True
    name: str = "Cutout"
