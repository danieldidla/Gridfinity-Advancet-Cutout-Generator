"""Mesh export: STL and 3MF for printing, glTF for the browser preview."""

from __future__ import annotations

import io
import struct
import zipfile
from xml.sax.saxutils import escape

import numpy as np
import trimesh
from manifold3d import Manifold


# Booleans leave a handful of zero-area triangles whose vertices coincide.
# They are harmless in an indexed mesh but make a position-merged one (any STL
# reader, i.e. every slicer) non-manifold, so they are collapsed on the way out.
_MERGE_DIGITS = 5
_SIMPLIFY_TOLERANCE = 1e-5


def to_arrays(solid: Manifold, clean: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (float64) and triangle indices of the solid."""
    if clean:
        solid = solid.simplify(_SIMPLIFY_TOLERANCE)
    mesh = solid.to_mesh64()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    tris = np.asarray(mesh.tri_verts, dtype=np.int64)
    if not clean:
        return verts, tris

    quantised = np.round(verts, _MERGE_DIGITS)
    unique, inverse = np.unique(quantised, axis=0, return_inverse=True)
    remapped = inverse[tris]
    keep = ((remapped[:, 0] != remapped[:, 1])
            & (remapped[:, 1] != remapped[:, 2])
            & (remapped[:, 0] != remapped[:, 2]))
    return unique, remapped[keep]


def to_trimesh(solid: Manifold, clean: bool = True) -> trimesh.Trimesh:
    verts, tris = to_arrays(solid, clean=clean)
    mesh = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    mesh.remove_unreferenced_vertices()
    return mesh


def export_stl(solid: Manifold) -> bytes:
    """Binary STL."""
    verts, tris = to_arrays(solid)
    tri_v = verts[tris]                       # (T, 3, 3)
    normals = np.cross(tri_v[:, 1] - tri_v[:, 0], tri_v[:, 2] - tri_v[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals),
                        where=lengths > 0)

    # Binary STL is a packed array of 50-byte records: 12 floats plus a 2-byte
    # attribute word. Build it as a structured array rather than looping.
    record = np.zeros(len(tris), dtype=np.dtype([
        ("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2"),
    ]))
    record["n"] = normals
    record["v"] = tri_v

    out = io.BytesIO()
    out.write(b"gridfinity cutout generator".ljust(80, b"\0"))
    out.write(struct.pack("<I", len(tris)))
    out.write(record.tobytes())
    return out.getvalue()


def export_3mf(solid: Manifold, name: str = "gridfinity-bin") -> bytes:
    """Minimal but valid 3MF, which slicers prefer over STL (units are explicit)."""
    verts, tris = to_arrays(solid)
    rows = ["".join(
        f'<vertex x="{v[0]:.4f}" y="{v[1]:.4f}" z="{v[2]:.4f}"/>' for v in verts)]
    tri_rows = "".join(
        f'<triangle v1="{t[0]}" v2="{t[1]}" v3="{t[2]}"/>' for t in tris)
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<metadata name="Title">{escape(name)}</metadata>'
        '<resources><object id="1" type="model"><mesh>'
        f'<vertices>{rows[0]}</vertices>'
        f'<triangles>{tri_rows}</triangles>'
        '</mesh></object></resources>'
        '<build><item objectid="1"/></build></model>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rel0" Target="/3D/3dmodel.model" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '</Types>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    return buf.getvalue()


def export_glb(solid: Manifold) -> bytes:
    """Binary glTF for the three.js preview.

    Skips the cleanup pass: the preview is indexed, so slivers are invisible
    there, and this runs on every parameter change.
    """
    mesh = to_trimesh(solid, clean=False)
    scene = trimesh.Scene(mesh)
    return scene.export(file_type="glb")
