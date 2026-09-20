"""Request/response models and the project document schema."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .gridfinity import spec as S

Point = tuple[float, float]


# --- auth -------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    display_name: str
    is_admin: bool


class ServerInfo(BaseModel):
    app_name: str
    allow_registration: bool
    has_users: bool
    max_upload_mb: int


# --- project document -------------------------------------------------------

class BinSettings(BaseModel):
    """Mirrors ``gridfinity.spec.BinSpec`` with validation and sane bounds."""

    grid_x: int = Field(default=2, ge=1, le=12)
    grid_y: int = Field(default=2, ge=1, le=12)
    height_units: float = Field(default=3.0, ge=1.0, le=30.0)

    wall_thickness: float = Field(default=S.DEFAULT_WALL, ge=0.4, le=6.0)
    floor_thickness: float = Field(default=S.DEFAULT_FLOOR, ge=0.4, le=20.0)
    # This application exists to cut pockets into a block. A hollow bin would
    # swallow any pocket that stops above the cavity floor, so solid is the
    # default and emptying the bin is the deliberate choice.
    solid: bool = True

    stacking_lip: bool = True
    lip_style: Literal["normal", "reduced", "none"] = "reduced"
    lip_top_rim: float = Field(default=0.6, ge=0.0, le=2.0)
    height_includes_lip: bool = False
    lip_support: bool = True

    magnet_holes: bool = False
    magnet_diameter: float = Field(default=S.MAGNET_DIAMETER, ge=2.0, le=15.0)
    magnet_depth: float = Field(default=S.MAGNET_DEPTH, ge=0.5, le=10.0)
    screw_holes: bool = False
    screw_diameter: float = Field(default=S.SCREW_DIAMETER, ge=1.0, le=8.0)
    screw_depth: float = Field(default=S.SCREW_DEPTH, ge=1.0, le=20.0)

    label_tab: bool = False
    label_tab_width: float = Field(default=12.0, ge=4.0, le=40.0)
    label_tab_angle: float = Field(default=36.0, ge=10.0, le=75.0)

    corner_segments: int = Field(default=S.CORNER_SEGMENTS, ge=3, le=48)

    def to_spec(self) -> S.BinSpec:
        return S.BinSpec(**self.model_dump())


class CutoutSource(BaseModel):
    kind: Literal["image", "scan", "manual", "shape"] = "manual"
    id: str | None = None
    label: str = ""


class Cutout(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = Field(default="Cutout", max_length=80)
    enabled: bool = True

    polygon: list[Point] = Field(default_factory=list)
    holes: list[list[Point]] = Field(default_factory=list)

    x: float = 0.0
    y: float = 0.0
    rotation: float = Field(default=0.0, ge=-360.0, le=360.0)

    depth: float = Field(default=10.0, ge=0.2, le=200.0)
    clearance: float = Field(default=0.4, ge=-5.0, le=10.0)
    corner_radius: float = Field(default=0.0, ge=0.0, le=30.0)
    draft_angle: float = Field(default=0.0, ge=0.0, le=45.0)
    bottom_radius: float = Field(default=0.0, ge=0.0, le=20.0)

    through: bool = False
    finger_scoop: bool = False
    finger_scoop_radius: float = Field(default=8.0, ge=1.0, le=40.0)
    finger_notch: bool = False
    finger_notch_diameter: float = Field(default=18.0, ge=2.0, le=80.0)

    mesh_source: str | None = None
    mesh_open_top: bool = True
    mesh_flip_z: bool = True

    source: CutoutSource = Field(default_factory=CutoutSource)

    @field_validator("polygon")
    @classmethod
    def _limit_polygon(cls, value: list[Point]) -> list[Point]:
        if len(value) > 6000:
            raise ValueError("Kontur hat zu viele Punkte")
        return value

    def to_spec(self) -> S.CutoutSpec:
        return S.CutoutSpec(
            polygon=[tuple(p) for p in self.polygon],
            holes=[[tuple(p) for p in h] for h in self.holes],
            x=self.x, y=self.y, rotation=self.rotation,
            depth=self.depth, clearance=self.clearance,
            corner_radius=self.corner_radius, draft_angle=self.draft_angle,
            bottom_radius=self.bottom_radius, through=self.through,
            finger_scoop=self.finger_scoop,
            finger_scoop_radius=self.finger_scoop_radius,
            finger_notch=self.finger_notch,
            finger_notch_diameter=self.finger_notch_diameter,
            mesh_source=self.mesh_source, mesh_open_top=self.mesh_open_top,
            mesh_flip_z=self.mesh_flip_z,
            enabled=self.enabled, name=self.name,
        )


class ViewState(BaseModel):
    """Purely cosmetic editor state, round-tripped so a reload looks the same."""
    model_config = ConfigDict(extra="allow")

    selected_cutout: str | None = None
    camera: dict | None = None
    show_grid: bool = True


class ProjectState(BaseModel):
    bin: BinSettings = Field(default_factory=BinSettings)
    cutouts: list[Cutout] = Field(default_factory=list)
    view: ViewState = Field(default_factory=ViewState)

    @field_validator("cutouts")
    @classmethod
    def _limit_cutouts(cls, value: list[Cutout]) -> list[Cutout]:
        if len(value) > 60:
            raise ValueError("zu viele Cutouts")
        return value


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    revision: int
    created_at: object
    updated_at: object
    thumbnail: str | None = None


class ProjectOut(ProjectSummary):
    state: ProjectState
    images: list["ImageOut"] = Field(default_factory=list)
    scans: list["ScanOut"] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str = Field(default="Neues Projekt", max_length=160)
    state: ProjectState | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    state: ProjectState | None = None
    revision: int | None = None


# --- images -----------------------------------------------------------------

class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    width: int
    height: int
    paper: str
    corners: list | None
    px_per_mm: float
    has_rectified: bool = False
    trace: dict = Field(default_factory=dict)


class RectifyRequest(BaseModel):
    corners: list[Point] = Field(min_length=4, max_length=4)
    paper: Literal["a4", "a5", "a3", "letter"] = "a4"
    px_per_mm: float = Field(default=8.0, ge=2.0, le=20.0)
    size_mm: tuple[float, float] | None = None


class Stroke(BaseModel):
    points: list[tuple[int, int]]
    foreground: bool = True


class TraceRequest(BaseModel):
    rect: tuple[int, int, int, int] | None = None
    strokes: list[Stroke] = Field(default_factory=list)
    brush: int = Field(default=8, ge=1, le=80)
    simplify_mm: float = Field(default=0.25, ge=0.0, le=5.0)
    smooth_mm: float = Field(default=0.0, ge=0.0, le=5.0)
    include_holes: bool = True
    min_hole_area_mm2: float = Field(default=4.0, ge=0.0, le=2000.0)
    keep_largest: bool = True


class TraceResult(BaseModel):
    polygon: list[Point]
    holes: list[list[Point]]
    width_mm: float
    height_mm: float
    area_mm2: float
    mask_preview: str | None = None


# --- scans ------------------------------------------------------------------

class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    status: str
    coverage: dict | None
    dimensions: dict | None
    message: str
    shot_count: int = 0
    has_mesh: bool = False


class ScanCreate(BaseModel):
    name: str = Field(default="3D-Aufnahme", max_length=160)


class ScanSettings(BaseModel):
    voxel_mm: float = Field(default=0.5, ge=0.2, le=3.0)
    max_height_mm: float = Field(default=120.0, ge=10.0, le=250.0)
    extent_mm: float = Field(default=160.0, ge=40.0, le=300.0)
    threshold: int = Field(default=45, ge=5, le=200)
    smooth: float = Field(default=0.8, ge=0.0, le=3.0)
    extend_beyond_board: bool = True


class ShotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    sequence: int
    sharpness: float
    corner_count: int
    azimuth: float | None
    elevation: float | None
    usable: bool


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    status: str
    progress: float
    stage: str
    error: str | None
    result: dict | None


# --- geometry ---------------------------------------------------------------

class BuildRequest(BaseModel):
    bin: BinSettings
    cutouts: list[Cutout] = Field(default_factory=list)


class ModelStats(BaseModel):
    triangles: int
    volume_mm3: float
    width_mm: float
    depth_mm: float
    height_mm: float
    material_cm3: float
    build_ms: float
    warnings: list[str] = Field(default_factory=list)


ProjectOut.model_rebuild()
