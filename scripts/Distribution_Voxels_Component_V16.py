#! python3
"""
Distribution Voxels Component  V16
==================================
Rhino 8 / CPython 3

CONCEPT
-------
Reads a voxel field organised by Rhino colour layers (Red, Yellow, Green, Blue …).
Each layer = one architectural program zone.
Distributes architectural elements across the field using six condition modes:

  ROOM        - agentic space-making: solid slabs top/bottom, window treatment on sides
  FACADE      - orient a source element to every exterior face (Object-Orient logic)
  STRUCTURE   - parametric columns / beams at voxel corners and edges
  ORNAMENT    - attractor-based rotation / scale / spiral on exterior faces
  CIRCULATION - parametric stair geometry in vertical voxel stacks
  SKYWALK     - elevated adaptive circulation: sweep profiles along curves with attractor response

INSPIRED BY
-----------
  Grasshopper Object_Orient_Component_Selection.gh
  Core transform: Transform.PlaneToPlane (source plane → target plane)
  Skywalk concept: parametric elevation + adaptive profiles responding to attractor points
"""

import math
import traceback
from collections import deque

import Rhino
import Rhino.Geometry as rg
import Rhino.DocObjects as rd
import rhinoscriptsyntax as rs
import scriptcontext as sc
import System
import System.Drawing as sd
import Eto.Drawing as edrawing
import Eto.Forms as eforms


# ==============================================================================
#  CONFIGURATION
# ==============================================================================

DEFAULTS = {
    "room_wwr":      50,     # window-to-wall ratio %
    "room_slab_t":  0.2,     # slab thickness (Rhino doc units, e.g. 0.2 m)
    "facade_offset":  0,     # push-out offset mm
    "facade_every_n": 1,
    "struct_size":    8,     # column/beam profile size (% of voxel size)
    "orn_min":        0,
    "orn_max":       90,
    "stair_width":  800,
    "stair_rise":   175,
    "stair_run":    280,
    "stair_rot_x":    0,
}

FACE_DIRS = {
    "+X": rg.Vector3d( 1,  0,  0),
    "-X": rg.Vector3d(-1,  0,  0),
    "+Y": rg.Vector3d( 0,  1,  0),
    "-Y": rg.Vector3d( 0, -1,  0),
    "+Z": rg.Vector3d( 0,  0,  1),
    "-Z": rg.Vector3d( 0,  0, -1),
}
FACE_TO_OFFSET = {
    "+X": ( 1,  0,  0), "-X": (-1,  0,  0),
    "+Y": ( 0,  1,  0), "-Y": ( 0, -1,  0),
    "+Z": ( 0,  0,  1), "-Z": ( 0,  0, -1),
}
ALL_FACES  = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
SIDE_FACES = ["+X", "-X", "+Y", "-Y"]

PLACE_AT_OPTIONS = [
    "All voxels",
    "Boundary only",
    "Perimeter",
    u"Grid 2\u00d72",
    u"Grid 3\u00d73",
    "Vertical stacks",
    "Random Cluster Groups",
    # V7 architectural voxel filters
    "Z-gradient",
    "Checkerboard XY",
    "Checkerboard 3D",
    "Attractor gradient",
    # V7 solar integration (reads sc.sticky["voxelgen_solar_tiers"] from bake)
    "Solar high zones",      # CritHigh + High tiers only
    "Solar exposed zones",   # CritHigh + High + Med tiers
    "Solar shade zones",     # Low + Shade tiers only (cool/protected areas)
]

OUTPUT_LAYERS = {
    "Room":        ("VOXELGEN_Room",        sd.Color.FromArgb(135, 206, 235)),
    "Facade":      ("VOXELGEN_Facade",      sd.Color.FromArgb(255, 180,  40)),
    "Structure":       ("VOXELGEN_Structure",       sd.Color.FromArgb(112, 128, 144)),
    "Structure_Joint": ("VOXELGEN_Structure_Joint", sd.Color.FromArgb(180, 160, 100)),
    "Ornament":    ("VOXELGEN_Ornament",    sd.Color.FromArgb(148,   0, 211)),
    "Circulation": ("VOXELGEN_Circulation", sd.Color.FromArgb( 50, 205,  50)),
    "Discrete":           ("VOXELGEN_Discrete",           sd.Color.FromArgb(220,  80,  50)),
    "Discrete_A":         ("VOXELGEN_Discrete_A",         sd.Color.FromArgb(220, 100,  60)),
    "Discrete_B":         ("VOXELGEN_Discrete_B",         sd.Color.FromArgb(180,  60, 180)),
    "Discrete_C":         ("VOXELGEN_Discrete_C",         sd.Color.FromArgb( 60, 160, 220)),
    "Discrete_D":         ("VOXELGEN_Discrete_D",         sd.Color.FromArgb(220, 200,  60)),
    "Discrete_E":         ("VOXELGEN_Discrete_E",         sd.Color.FromArgb( 80, 200, 120)),
    "Discrete_F":         ("VOXELGEN_Discrete_F",         sd.Color.FromArgb(180, 100, 220)),
    # Climate Adaptive response layers
    "Discrete_ClimHot":     ("VOXELGEN_Discrete_ClimHot",     sd.Color.FromArgb(230,  60,  40)),
    "Discrete_ClimWarm":    ("VOXELGEN_Discrete_ClimWarm",    sd.Color.FromArgb(240, 140,  30)),
    "Discrete_ClimMid":     ("VOXELGEN_Discrete_ClimMid",     sd.Color.FromArgb(180, 180,  40)),
    "Discrete_ClimPassive": ("VOXELGEN_Discrete_ClimPassive", sd.Color.FromArgb( 60, 180, 100)),
    "Discrete_ClimWind":    ("VOXELGEN_Discrete_ClimWind",    sd.Color.FromArgb( 60, 140, 220)),
    # Skywalk adaptive circulation layers
    "Skywalk_Paths":  ("VOXELGEN_Skywalk_Paths",  sd.Color.FromArgb(100, 200, 100)),
    "Skywalk_Nodes":  ("VOXELGEN_Skywalk_Nodes",  sd.Color.FromArgb(150, 255, 100)),
    # Room Cluster shell layer
    "Cluster_Shell":  ("VOXELGEN_Cluster_Shell",  sd.Color.FromArgb(255, 165,   0)),
    # Solar Voxel Analysis layers (5-tier heatmap + chart)
    "Solar_5_CritHigh": ("VOXELGEN_Solar_CritHigh", sd.Color.FromArgb(220,  40,  40)),
    "Solar_4_High":     ("VOXELGEN_Solar_High",     sd.Color.FromArgb(240, 140,  30)),
    "Solar_3_Med":      ("VOXELGEN_Solar_Med",      sd.Color.FromArgb(240, 220,  50)),
    "Solar_2_Low":      ("VOXELGEN_Solar_Low",      sd.Color.FromArgb( 60, 180, 220)),
    "Solar_1_Shade":    ("VOXELGEN_Solar_Shade",    sd.Color.FromArgb( 30,  60, 130)),
    "Solar_Chart":      ("VOXELGEN_Solar_Chart",    sd.Color.FromArgb(200, 200, 200)),
}


# ==============================================================================
#  VOXEL DATA MODEL
# ==============================================================================

class Voxel:
    __slots__ = ('brep_id', 'center', 'grid_ijk', 'layer', 'size',
                 'neighbors', 'face_types', 'brep')

    def __init__(self, brep_id, center, grid_ijk, layer, size, brep=None):
        self.brep_id    = brep_id
        self.center     = center
        self.grid_ijk   = grid_ijk
        self.layer      = layer
        self.size       = size
        self.brep       = brep
        self.neighbors  = {}  # face_dir -> Voxel or None
        self.face_types = {}  # face_dir -> str


class SuperVoxel:
    """
    Virtual voxel representing a merged group of W×D×H real voxels.
    Has the same interface as Voxel so apply_discrete_mode works unchanged.
    Used by Low Resolution (Bay) mode.
    """
    __slots__ = ('center', 'grid_ijk', 'layer_name', 'layer', 'size',
                 'neighbors', 'face_types', 'face_half', 'face_sizes',
                 'brep_id', 'brep')

    def __init__(self, center, grid_ijk, layer_name, base_size,
                 face_types, neighbors, face_half, face_sizes):
        self.center     = center
        self.grid_ijk   = grid_ijk
        self.layer_name = layer_name
        self.layer      = layer_name      # alias used by some code paths
        self.size       = base_size       # kept for fallback; face_sizes used for scaling
        self.neighbors  = neighbors       # face_dir -> SuperVoxel or None
        self.face_types = face_types      # face_dir -> str
        self.face_half  = face_half       # face_dir -> float (half-extent for plane origin)
        self.face_sizes = face_sizes      # face_dir -> float (face characteristic size)
        self.brep_id    = None
        self.brep       = None


# ==============================================================================
#  CORE ENGINE
# ==============================================================================

def load_voxels_from_ids(guids):
    """
    Build voxel dict from an explicit list of Rhino object GUIDs (user-selected).
    Returns (voxels_dict {grid_ijk: Voxel}, voxel_size, skipped_count).
    """
    candidates = []
    skipped    = 0
    accepted_types = (rd.ObjectType.Brep, rd.ObjectType.Extrusion,
                      rd.ObjectType.Mesh, rd.ObjectType.SubD)
    for guid in guids:
        obj = sc.doc.Objects.FindId(guid)
        if not obj or obj.IsDeleted:
            skipped += 1
            continue
        if obj.ObjectType not in accepted_types:
            skipped += 1
            continue
        layer_name = sc.doc.Layers[obj.Attributes.LayerIndex].FullPath
        geo = obj.Geometry
        # Use raw geometry bounding box — no solid check, accepts open meshes/BREPs
        bb = geo.GetBoundingBox(True)
        if not bb.IsValid:
            skipped += 1
            continue
        sx  = bb.Max.X - bb.Min.X
        sy  = bb.Max.Y - bb.Min.Y
        sz  = bb.Max.Z - bb.Min.Z
        avg = (sx + sy + sz) / 3.0
        if avg < 1e-6:
            skipped += 1
            continue
        candidates.append((obj.Id, bb.Center, layer_name, avg))

    if not candidates:
        return {}, 0.0, skipped

    sizes      = sorted(c[3] for c in candidates)
    voxel_size = sizes[len(sizes) // 2]

    voxels_dict = {}
    for brep_id, center, layer_name, size in candidates:
        i = int(round(center.X / voxel_size))
        j = int(round(center.Y / voxel_size))
        k = int(round(center.Z / voxel_size))
        v = Voxel(brep_id, center, (i, j, k), layer_name, voxel_size)
        voxels_dict[(i, j, k)] = v

    return voxels_dict, voxel_size, skipped


def scan_voxel_field(target_layers=None):
    """
    (Legacy) Scan document for closed BREPs on the specified layers.
    Returns (voxels_dict {grid_ijk: Voxel}, voxel_size).
    """
    candidates = []
    accepted_types = (rd.ObjectType.Brep, rd.ObjectType.Extrusion,
                      rd.ObjectType.Mesh, rd.ObjectType.SubD)
    for obj in sc.doc.Objects:
        if obj.IsDeleted:
            continue
        if obj.ObjectType not in accepted_types:
            continue
        layer_name = sc.doc.Layers[obj.Attributes.LayerIndex].FullPath
        if target_layers and not any(t in layer_name for t in target_layers):
            continue
        geo = obj.Geometry
        # Convert to Brep for uniform handling
        if isinstance(geo, rg.Extrusion):
            brep = geo.ToBrep()
        elif isinstance(geo, rg.Mesh):
            brep = rg.Brep.CreateFromMesh(geo, True)
        elif isinstance(geo, rg.SubD):
            brep = geo.ToBrep(rg.SubDToBrepOptions())
        else:
            brep = obj.BrepGeometry
        if brep is None or not brep.IsSolid:
            continue
        bb = brep.GetBoundingBox(True)
        if not bb.IsValid:
            continue
        sx = bb.Max.X - bb.Min.X
        sy = bb.Max.Y - bb.Min.Y
        sz = bb.Max.Z - bb.Min.Z
        avg = (sx + sy + sz) / 3.0
        if avg < 1e-6:
            continue
        candidates.append((obj.Id, bb.Center, layer_name, avg, brep))

    if not candidates:
        return {}, 0.0

    sizes = sorted(c[3] for c in candidates)
    voxel_size = sizes[len(sizes) // 2]

    voxels_dict = {}
    for brep_id, center, layer_name, size, brep in candidates:
        i = int(round(center.X / voxel_size))
        j = int(round(center.Y / voxel_size))
        k = int(round(center.Z / voxel_size))
        v = Voxel(brep_id, center, (i, j, k), layer_name, voxel_size, brep)
        voxels_dict[(i, j, k)] = v

    return voxels_dict, voxel_size


def compute_adjacency(voxels_dict):
    """Classify every voxel face: interior / exterior / inter_program / top / bottom."""
    for (i, j, k), vox in voxels_dict.items():
        for face_dir, (di, dj, dk) in FACE_TO_OFFSET.items():
            nb = voxels_dict.get((i + di, j + dj, k + dk))
            vox.neighbors[face_dir] = nb
            if nb is None:
                if face_dir == "+Z":
                    vox.face_types[face_dir] = "top"
                elif face_dir == "-Z":
                    vox.face_types[face_dir] = "bottom"
                else:
                    vox.face_types[face_dir] = "exterior"
            elif nb.layer == vox.layer:
                vox.face_types[face_dir] = "interior"
            else:
                if face_dir == "+Z":
                    vox.face_types[face_dir] = "top"
                elif face_dir == "-Z":
                    vox.face_types[face_dir] = "bottom"
                else:
                    vox.face_types[face_dir] = "inter_program"


def orient_component(source_geo, source_plane, target_plane):
    """
    Object Orient equivalent (GH Object Orient component in Python).
    Transforms source_geo from source_plane coordinate space to target_plane.
    """
    xform = rg.Transform.PlaneToPlane(source_plane, target_plane)
    result = source_geo.Duplicate()
    result.Transform(xform)
    return result


def _get_vox_face_size(vox, face_dir):
    """Return the characteristic face size for scale_to_fit.
    For regular Voxels this is vox.size.
    For SuperVoxels it is the face-direction-specific max(width, height)."""
    if hasattr(vox, 'face_sizes'):
        return vox.face_sizes.get(face_dir, vox.size)
    return vox.size


def get_face_plane(vox, face_dir):
    """
    Outward-facing plane at the centre of the given voxel face.
    Coordinate frame is always RIGHT-HANDED with ZAxis = outward normal.
      Vertical faces  : X = ZAxis × normal  (rightward looking out)
                        Y = normal × X       (world-up on face)
      Horizontal faces: X = world XAxis
                        Y = normal × X       (consistent Y for top/bottom)
    SuperVoxels store a face_half dict with per-direction extents.
    """
    # SuperVoxel uses per-direction half-extents; regular Voxel uses size/2
    if hasattr(vox, 'face_half'):
        half = vox.face_half[face_dir]
    else:
        half = vox.size / 2.0
    normal = FACE_DIRS[face_dir]
    origin = rg.Point3d(
        vox.center.X + normal.X * half,
        vox.center.Y + normal.Y * half,
        vox.center.Z + normal.Z * half,
    )
    if abs(normal.Z) < 0.99:
        # Vertical face — X is the "rightward" direction when looking outward
        x_axis = rg.Vector3d.CrossProduct(rg.Vector3d.ZAxis, normal)
    else:
        # Horizontal face — align to world X
        x_axis = rg.Vector3d.XAxis
    x_axis.Unitize()
    # Y = normal × X  →  ensures right-hand rule: Z = X × Y = normal  ✓
    y_axis = rg.Vector3d.CrossProduct(normal, x_axis)
    y_axis.Unitize()
    return rg.Plane(origin, x_axis, y_axis)


def flood_fill_cluster(start_vox, voxels_dict):
    """BFS flood-fill: collect all voxels connected to start_vox on the same layer."""
    visited = set()
    queue   = deque([start_vox.grid_ijk])
    while queue:
        ijk = queue.popleft()
        if ijk in visited:
            continue
        visited.add(ijk)
        vox = voxels_dict[ijk]
        for face_dir in ALL_FACES:
            nb = vox.neighbors.get(face_dir)
            if nb and nb.layer == vox.layer and nb.grid_ijk not in visited:
                queue.append(nb.grid_ijk)
    return [voxels_dict[ijk] for ijk in visited]


def ensure_output_layer(mode_name):
    layer_name, color = OUTPUT_LAYERS[mode_name]
    if not rs.IsLayer(layer_name):
        rs.AddLayer(layer_name, color)
    return layer_name


def clear_output_layer(mode_name):
    layer_name, _ = OUTPUT_LAYERS[mode_name]
    if rs.IsLayer(layer_name):
        rs.LayerLocked(layer_name, False)
        objs = rs.ObjectsByLayer(layer_name)
        if objs:
            rs.DeleteObjects(objs)


def _add_brep(brep, layer_name):
    attrs = rd.ObjectAttributes()
    idx   = sc.doc.Layers.FindByFullPath(layer_name, -1)
    if idx >= 0:
        attrs.LayerIndex = idx
    return sc.doc.Objects.AddBrep(brep, attrs)   # returns GUID


def _target_voxels(voxels_dict, target_layers):
    return [v for v in voxels_dict.values()
            if any(t in v.layer for t in target_layers)]


def _peel_shells(voxels, depth):
    """
    Return all voxels within `depth` shells of the outer surface.
    Shell 1 = outermost exposed ring. Shell 2 = that ring + the next layer
    inward. Iteratively peels layers like an onion.
    """
    if depth <= 0:
        return []
    vox_map   = {v.grid_ijk: v for v in voxels}
    remaining = set(vox_map.keys())
    result    = set()

    for _ in range(depth):
        layer = set()
        for ijk in remaining:
            # Exposed if any of the 6 neighbour slots is either outside the
            # full field OR has already been peeled away.
            for di, dj, dk in FACE_TO_OFFSET.values():
                nb = (ijk[0]+di, ijk[1]+dj, ijk[2]+dk)
                if nb not in remaining:          # exposed face
                    layer.add(ijk)
                    break
        if not layer:
            break                               # no more shells to peel
        result   |= layer
        remaining -= layer

    return [vox_map[ijk] for ijk in result]


def _filter_by_place_at(voxels, place_at, shell_depth=1,
                         rand_seed=42,
                         attractor_pt=None, attr_radius=20.0,
                         attr_min=0.0, attr_max=1.0):
    """
    Filter a voxel list by spatial strategy.
    shell_depth applies only to "Boundary only".
    "Random Cluster Groups" returns all voxels — splitting is done separately.
    V7 additions: Z-gradient, Checkerboard XY/3D, Attractor gradient.
    """
    if not voxels:
        return []

    if place_at == "Z-gradient":
        import random as _random
        rng  = _random.Random(rand_seed)
        zs   = [v.center.Z for v in voxels]
        z_lo = min(zs); z_hi = max(zs)
        span = (z_hi - z_lo) or 1.0
        result = []
        for v in voxels:
            t = (v.center.Z - z_lo) / span   # 0 = base, 1 = top
            p = 1.0 - t                       # base=100%, top=0%
            if rng.random() < p:
                result.append(v)
        return result if result else list(voxels)

    elif place_at == "Checkerboard XY":
        return [v for v in voxels if (v.grid_ijk[0] + v.grid_ijk[1]) % 2 == 0]

    elif place_at == "Checkerboard 3D":
        return [v for v in voxels if sum(v.grid_ijk) % 2 == 0]

    elif place_at == "Attractor gradient":
        import random as _random
        rng = _random.Random(rand_seed)
        if attractor_pt is None:
            return list(voxels)   # no point picked → fall back to All
        result = []
        for v in voxels:
            d = v.center.DistanceTo(attractor_pt)
            # Linear falloff: max at d=0, min at d=attr_radius
            p = attr_max - (attr_max - attr_min) * min(d / max(attr_radius, 1e-6), 1.0)
            if rng.random() < p:
                result.append(v)
        return result if result else list(voxels)

    elif place_at == "Boundary only":
        depth = max(1, int(shell_depth))
        xs = [v.center.X for v in voxels]
        ys = [v.center.Y for v in voxels]
        zs = [v.center.Z for v in voxels]
        vsize = voxels[0].size
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        zmin, zmax = min(zs), max(zs)
        # depth=1 → margin=0.5*vsize → outermost ring only
        # depth=2 → margin=1.5*vsize → 2 rings deep, etc.
        margin = (depth - 0.5) * vsize
        result = [v for v in voxels if
                  (v.center.X - xmin) <= margin or (xmax - v.center.X) <= margin or
                  (v.center.Y - ymin) <= margin or (ymax - v.center.Y) <= margin or
                  (v.center.Z - zmin) <= margin or (zmax - v.center.Z) <= margin]
        return result if result else list(voxels)

    elif place_at == "Perimeter":
        # Only voxels with at least one lateral (side) face exposed to exterior.
        return [v for v in voxels
                if any(v.face_types.get(fd) in ("exterior", "inter_program")
                       for fd in SIDE_FACES)]

    elif u"2\u00d72" in place_at:          # "Grid 2×2"
        # Normalise to local grid so pattern always starts at first voxel.
        i_min = min(v.grid_ijk[0] for v in voxels)
        j_min = min(v.grid_ijk[1] for v in voxels)
        return [v for v in voxels
                if (v.grid_ijk[0] - i_min) % 2 == 0
                and (v.grid_ijk[1] - j_min) % 2 == 0]

    elif u"3\u00d73" in place_at:          # "Grid 3×3"
        i_min = min(v.grid_ijk[0] for v in voxels)
        j_min = min(v.grid_ijk[1] for v in voxels)
        return [v for v in voxels
                if (v.grid_ijk[0] - i_min) % 3 == 0
                and (v.grid_ijk[1] - j_min) % 3 == 0]

    elif place_at == "Vertical stacks":
        # Return only the BASE voxel (lowest k) of each XY column that has
        # 2+ voxels stacked.  Avoids selecting every voxel in a solid block.
        from collections import defaultdict
        cols = defaultdict(list)
        for v in voxels:
            cols[(v.grid_ijk[0], v.grid_ijk[1])].append(v)
        result = []
        for col_voxels in cols.values():
            if len(col_voxels) >= 2:
                result.append(min(col_voxels, key=lambda v: v.grid_ijk[2]))
        return result

    # ── V7 Solar integration: reads baked tier map from sc.sticky ────────────
    elif place_at in ("Solar high zones", "Solar exposed zones", "Solar shade zones"):
        tier_map = sc.sticky.get("voxelgen_solar_tiers", {})
        if not tier_map:
            print(">>> Solar zones filter: no baked data in sc.sticky['voxelgen_solar_tiers']."
                  "  Run 'Bake Solar Voxels' first.  Falling back to All voxels.")
            return list(voxels)
        if place_at == "Solar high zones":
            allowed = {"Solar_5_CritHigh", "Solar_4_High"}
        elif place_at == "Solar exposed zones":
            allowed = {"Solar_5_CritHigh", "Solar_4_High", "Solar_3_Med"}
        else:  # Solar shade zones
            allowed = {"Solar_2_Low", "Solar_1_Shade"}
        result = [v for v in voxels if tier_map.get(v.grid_ijk, "Solar_1_Shade") in allowed]
        return result if result else list(voxels)

    else:                                   # "All voxels" or "Random Cluster Groups"
        return list(voxels)


# ── Climate zone definitions (mirrors Climate_Comfort_Agent_V2 logic) ─────────
CLIMATE_ZONES = ["hot_stagnant", "overheated", "marginal", "passive", "tunnel"]

# Default per-zone behavior rules: shell_depth, place_at, resolution_place_at, element_label
CLIMATE_RULES_DEFAULT = {
    "hot_stagnant": {"depth": 3, "place_at": "Boundary only", "element": "A"},
    "overheated":   {"depth": 2, "place_at": "Boundary only", "element": "A"},
    "marginal":     {"depth": 1, "place_at": "Boundary only", "element": "B"},
    "passive":      {"depth": 1, "place_at": u"Grid 3\u00d73",  "element": "B"},
    "tunnel":       {"depth": 1, "place_at": "Boundary only", "element": "C"},
}

CLIMATE_ZONE_LAYERS = {
    "hot_stagnant": "Discrete_ClimHot",
    "overheated":   "Discrete_ClimWarm",
    "marginal":     "Discrete_ClimMid",
    "passive":      "Discrete_ClimPassive",
    "tunnel":       "Discrete_ClimWind",
}


def _classify_voxels_by_climate(voxels):
    """
    Classify voxels into 5 climate zones by matching each voxel's XYZ centre
    to the nearest cell in sc.sticky["comfort_data"] (written automatically by
    Climate_Comfort_Agent_V2 after agents complete).

    comfort_data schema: {(ix,iy,iz): {"pos":(x,y,z), "zone":str,
                          "thermal":float, "daylight":float,
                          "airflow":float, "combined":float}}

    Returns dict  {zone_name: [Voxel, ...]}
    Falls back to all-voxels-as-marginal if no data in sc.sticky.
    """
    import scriptcontext as sc

    zones = {z: [] for z in CLIMATE_ZONES}

    raw = sc.sticky.get("comfort_data", {})
    if not raw:
        # No climate data available — default everything to marginal
        zones["marginal"] = list(voxels)
        return zones

    # Build flat lookup: list of (x, y, z, zone, thermal/100, airflow/100)
    cells_xyz = []
    for cell in raw.values():
        pos  = cell["pos"]
        zone = cell["zone"]
        # Recover solar (0-1) and vent (0-1) from stored 0-100 scores
        solar = max(0.0, min(1.0, 1.0 - cell["thermal"] / 100.0))
        vent  = max(0.0, min(1.0, cell["airflow"] / 100.0))
        cells_xyz.append((pos[0], pos[1], pos[2], solar, vent))

    # Classify each voxel by nearest comfort cell (positional match)
    for v in voxels:
        cx, cy, cz = v.center.X, v.center.Y, v.center.Z
        best_d2 = 1e18
        best_solar, best_vent = 0.5, 0.5
        for (px, py, pz, s, a) in cells_xyz:
            d2 = (px - cx)**2 + (py - cy)**2 + (pz - cz)**2
            if d2 < best_d2:
                best_d2 = d2
                best_solar, best_vent = s, a
        _assign_voxel_to_zone(v, best_solar, best_vent, zones)

    return zones


def _assign_voxel_to_zone(vox, solar, vent, zones):
    """Apply Climate_Comfort_Agent_V2 zone thresholds."""
    if vent > 0.85:
        zones["tunnel"].append(vox)
    else:
        comfort = vent * 0.6 + (1.0 - solar) * 0.4
        if comfort > 0.65:
            zones["passive"].append(vox)
        elif solar > 0.7 and vent < 0.3:
            zones["hot_stagnant"].append(vox)
        elif solar > 0.7:
            zones["overheated"].append(vox)
        else:
            zones["marginal"].append(vox)


def _classify_voxel_clusters(voxels_dict):
    """Connected-component BFS: groups spatially-adjacent voxels into clusters.

    Two voxels are in the same cluster if they share a face (6-connected grid
    neighbours).  Isolated blobs — voxels with a gap between them — become
    separate clusters.

    Args:
        voxels_dict: {grid_ijk: Voxel}

    Returns:
        {cluster_id (int): [grid_ijk, ...]}
    """
    from collections import deque
    OFFSETS = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]
    visited  = set()
    clusters = {}
    cid      = 0
    for ijk in voxels_dict:
        if ijk in visited:
            continue
        group = []
        q     = deque([ijk])
        visited.add(ijk)
        while q:
            ci, cj, ck = q.popleft()
            group.append((ci, cj, ck))
            for di, dj, dk in OFFSETS:
                nb = (ci + di, cj + dj, ck + dk)
                if nb not in visited and nb in voxels_dict:
                    visited.add(nb)
                    q.append(nb)
        clusters[cid] = group
        cid += 1
    return clusters


def _get_cluster_shell(cluster_ijk_list, voxels_dict, shell_depth=1):
    """Return {ijk: Voxel} for the outer shell_depth rings of one cluster.

    Uses a bounding-box distance approach identical to the existing
    'Boundary only' filter so it works correctly with round()-based grid_ijk.

    depth=1 → outermost ring only.
    depth=3 → 3 voxels deep from each face of the cluster's bounding box.
    Falls back to the entire cluster if the shell would be empty.
    """
    if not cluster_ijk_list:
        return {}
    voxels = [voxels_dict[ijk] for ijk in cluster_ijk_list if ijk in voxels_dict]
    if not voxels:
        return {}
    xs    = [v.center.X for v in voxels]
    ys    = [v.center.Y for v in voxels]
    zs    = [v.center.Z for v in voxels]
    vsize = voxels[0].size
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)
    margin = (shell_depth - 0.5) * vsize
    shell  = {}
    for v in voxels:
        if (v.center.X - xmin <= margin or xmax - v.center.X <= margin or
                v.center.Y - ymin <= margin or ymax - v.center.Y <= margin or
                v.center.Z - zmin <= margin or zmax - v.center.Z <= margin):
            shell[v.grid_ijk] = v
    return shell if shell else {ijk: voxels_dict[ijk]
                                for ijk in cluster_ijk_list if ijk in voxels_dict}


def _voronoi_cluster_bfs(voxels_dict, n_clusters, seed=0):
    """Partition ALL voxels into n_clusters rooms via floor-band constrained BFS.

    Mirrors the Program Classifier V6 approach:
      1. Divide the k (floor) range into N equal bands.
      2. Plant one seed per band from eligible voxels in that band.
      3. Multi-source BFS, each seed expanding only within its floor band
         (±1 floor tolerance at transitions).
      4. Flood-fill any unclaimed gaps from claimed neighbours.
      5. Band-midpoint fallback for any voxels still unclaimed.

    This gives horizontal slab-like clusters (matching Program Classifier
    zone shapes) rather than spherical blobs — cleaner boundary detection.

    Args:
        voxels_dict : {grid_ijk: Voxel}
        n_clusters  : number of floor-band zones
        seed        : random seed for reproducibility

    Returns:
        {grid_ijk: cluster_id (int)}  — every voxel assigned to one cluster
    """
    import random as _r
    from collections import deque
    import math as _math

    if not voxels_dict:
        return {}

    n_clusters = max(1, min(n_clusters, len(voxels_dict)))
    rng        = _r.Random(seed)
    OFFSETS    = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]

    # ── Floor range ────────────────────────────────────────────────────────────
    all_k   = [ijk[2] for ijk in voxels_dict]
    k_min   = min(all_k)
    k_max   = max(all_k)
    k_span  = max(k_max - k_min, 0)
    band_h  = (k_span + 1) / n_clusters          # float band height

    remaining   = set(voxels_dict.keys())
    cluster_map = {}                              # ijk → cluster_id

    # ── Seed one voxel per band + initialise per-band BFS queues ─────────────
    q            = deque()                        # (ijk, cid, klo, khi)
    band_ranges  = {}                             # cid → (klo, khi)

    for cid in range(n_clusters):
        klo = k_min + int(_math.floor(cid       * band_h))
        khi = k_min + int(_math.ceil ((cid + 1) * band_h)) - 1

        eligible = [ijk for ijk in remaining if klo <= ijk[2] <= khi]
        if not eligible:                          # widen ±1 if band is empty
            eligible = [ijk for ijk in remaining if klo - 1 <= ijk[2] <= khi + 1]
        if not eligible:
            eligible = list(remaining)
        if not eligible:
            continue

        s = rng.choice(eligible)
        cluster_map[s] = cid
        remaining.discard(s)
        band_ranges[cid] = (klo, khi)
        q.append((s, cid, klo, khi))

    # ── Multi-source BFS (all seeds interleaved — fair expansion) ─────────────
    while q:
        ijk, cid, klo, khi = q.popleft()
        i, j, k = ijk
        for di, dj, dk in OFFSETS:
            nb = (i + di, j + dj, k + dk)
            if nb in remaining and klo - 1 <= nb[2] <= khi + 1:
                cluster_map[nb] = cid
                remaining.discard(nb)
                q.append((nb, cid, klo, khi))

    # ── Flood-fill: close gaps between bands ──────────────────────────────────
    fill_q = deque()
    for ijk in list(cluster_map.keys()):
        i, j, k = ijk
        for di, dj, dk in OFFSETS:
            nb = (i + di, j + dj, k + dk)
            if nb in remaining:
                fill_q.append((nb, cluster_map[ijk]))

    while fill_q:
        ijk, cid = fill_q.popleft()
        if ijk not in remaining:
            continue
        cluster_map[ijk] = cid
        remaining.discard(ijk)
        i, j, k = ijk
        for di, dj, dk in OFFSETS:
            nb = (i + di, j + dj, k + dk)
            if nb in remaining:
                fill_q.append((nb, cid))

    # ── Band-midpoint fallback for any still-unclaimed voxels ─────────────────
    for ijk in remaining:
        k   = ijk[2]
        cid = min(range(n_clusters),
                  key=lambda c: abs(k - (k_min + (c + 0.5) * band_h)))
        cluster_map[ijk] = cid

    return cluster_map


def _get_voronoi_boundary(cluster_map, voxels_dict, ring_depth=1):
    """Find boundary voxels at cluster interfaces, then expand inward per cluster.

    Mirrors Program Classifier V6 boundary logic:
      - A voxel is on the boundary if it has at least one 6-connected
        neighbour that IS in the field but belongs to a DIFFERENT cluster.
      - Field-exterior faces are intentionally EXCLUDED — they would mark
        every voxel in a thin/hollow field as boundary ("all voxels" bug).
      - For ring_depth > 1, expand N-1 more layers INWARD within the same
        cluster, giving a controllable thick wall at each zone interface.

    Args:
        cluster_map : {ijk: cluster_id}  from _voronoi_cluster_bfs
        voxels_dict : {ijk: Voxel}
        ring_depth  : int ≥ 1

    Returns:
        {cluster_id: {ijk: Voxel}}  — boundary voxels per cluster
    """
    OFFSETS = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]

    # Step 1 — voxels touching a DIFFERENT cluster (cluster-interface only)
    # nb must be IN the field (nb in cluster_map) AND a different cluster.
    # This exactly matches how Program Classifier V6 separates programs.
    boundary_set = set()
    for ijk, cid in cluster_map.items():
        i, j, k = ijk
        for di, dj, dk in OFFSETS:
            nb = (i + di, j + dj, k + dk)
            nb_cid = cluster_map.get(nb)
            if nb_cid is not None and nb_cid != cid:
                boundary_set.add(ijk)
                break

    # Step 2 — expand inward ring_depth-1 more layers within same cluster
    current_layer = set(boundary_set)
    visited       = set(boundary_set)
    for _ in range(ring_depth - 1):
        next_layer = set()
        for ijk in current_layer:
            cid  = cluster_map[ijk]
            i, j, k = ijk
            for di, dj, dk in OFFSETS:
                nb = (i + di, j + dj, k + dk)
                if (nb in cluster_map and
                        cluster_map[nb] == cid and
                        nb not in visited):
                    next_layer.add(nb)
                    visited.add(nb)
        current_layer = next_layer
        boundary_set |= next_layer

    # Group by cluster_id
    result = {}
    for ijk in boundary_set:
        cid = cluster_map.get(ijk)
        if cid is None:
            continue
        if cid not in result:
            result[cid] = {}
        if ijk in voxels_dict:
            result[cid][ijk] = voxels_dict[ijk]

    return result


def _split_3_clusters(voxels, seed=0):
    """
    Split voxels into 3 spatially coherent groups via 3-seed Voronoi.
    Returns [group_A, group_B, group_C].  Each group is a list of Voxel.
    """
    import random
    n = len(voxels)
    if n < 3:
        return [voxels, [], []]
    rng   = random.Random(seed)
    seeds = rng.sample(voxels, 3)
    pts   = [(s.center.X, s.center.Y, s.center.Z) for s in seeds]
    groups = [[], [], []]
    for vox in voxels:
        cx, cy, cz = vox.center.X, vox.center.Y, vox.center.Z
        best = min(range(3),
                   key=lambda i: (cx - pts[i][0])**2 +
                                 (cy - pts[i][1])**2 +
                                 (cz - pts[i][2])**2)
        groups[best].append(vox)
    return groups


def _split_6_clusters(voxels, seed=0):
    """
    V16 — Split voxels into 6 spatially coherent groups via 6-seed Voronoi.
    Returns [group_A, group_B, group_C, group_D, group_E, group_F].
    Used by the Discrete tab when 6 inputs are supported.
    """
    import random
    n = len(voxels)
    if n == 0:
        return [[] for _ in range(6)]
    k     = min(6, n)
    rng   = random.Random(seed)
    seeds = rng.sample(list(voxels), k)
    pts   = [(s.center.X, s.center.Y, s.center.Z) for s in seeds]
    groups = [[] for _ in range(6)]
    for vox in voxels:
        cx, cy, cz = vox.center.X, vox.center.Y, vox.center.Z
        best = min(range(k),
                   key=lambda i: (cx - pts[i][0])**2 +
                                 (cy - pts[i][1])**2 +
                                 (cz - pts[i][2])**2)
        groups[best].append(vox)
    return groups


def _split_n_clusters(voxels, n, seed=0):
    """
    Partition voxels into n spatially coherent groups via n-seed Voronoi.
    Returns {grid_ijk: cluster_id}.  Used by the circulation-gap feature.
    """
    import random
    m = len(voxels)
    if m == 0:
        return {}
    n = max(1, min(int(n), m))
    rng   = random.Random(seed)
    seeds = rng.sample(list(voxels), n)
    pts   = [(s.center.X, s.center.Y, s.center.Z) for s in seeds]
    lk = {}
    for vox in voxels:
        cx, cy, cz = vox.center.X, vox.center.Y, vox.center.Z
        best = min(range(n),
                   key=lambda i: (cx - pts[i][0])**2 +
                                 (cy - pts[i][1])**2 +
                                 (cz - pts[i][2])**2)
        lk[vox.grid_ijk] = best
    return lk


def _erode_circulation(voxels, cluster_lk, gap):
    """
    Remove voxels lying within `gap` voxels (Manhattan, X/Y only — never Z) of a
    voxel belonging to a DIFFERENT cluster.  This carves empty circulation
    corridors between adjacent clusters while leaving vertical stacks intact.
    """
    g = max(1, int(gap))
    occupied = {v.grid_ijk: v for v in voxels}
    kept = []
    for v in voxels:
        ci, cj, ck = v.grid_ijk
        my_cid = cluster_lk.get(v.grid_ijk)
        border = False
        for di in range(-g, g + 1):
            for dj in range(-g, g + 1):
                if di == 0 and dj == 0:
                    continue
                if abs(di) + abs(dj) > g:        # Manhattan radius
                    continue
                nb_ijk = (ci + di, cj + dj, ck)  # same Z level only
                if nb_ijk in occupied and cluster_lk.get(nb_ijk) != my_cid:
                    border = True
                    break
            if border:
                break
        if not border:
            kept.append(v)
    return kept


# ==============================================================================
#  ROOM MODE  —  Multi-Voxel Room Distribution
# ==============================================================================
#
#  Five distribution strategies (all return  {grid_ijk: room_id}):
#
#  1. Single Voxel    — 1:1 (original behaviour)
#  2. Random Clusters — BFS random growth, controlled min/max voxel count
#  3. Grid Rooms      — regular NxM grouping in plan  (3 size variants)
#  4. Voronoi         — Voronoi diagram from random seeds → organic zones
#  5. Linear Bands    — corridor-like strips along X or Y
# ==============================================================================

def _distribute_single(voxels):
    """One room per voxel."""
    return {v.grid_ijk: i for i, v in enumerate(voxels)}


def _distribute_random_clusters(voxels, min_sz, max_sz, seed):
    """
    Greedy BFS growth from random seeds.
    Each room grows until it hits max_sz or runs out of neighbours.
    Randomised by `seed` — same seed = same layout every run.
    """
    import random
    rng        = random.Random(seed)
    unassigned = {v.grid_ijk: v for v in voxels}
    room_map   = {}
    room_id    = 0

    while unassigned:
        # Pick a random unassigned voxel as seed
        seed_ijk = rng.choice(list(unassigned.keys()))
        target   = rng.randint(min_sz, max_sz)
        room     = [unassigned.pop(seed_ijk)]
        frontier = []
        for nb in room[0].neighbors.values():
            if nb and nb.grid_ijk in unassigned:
                frontier.append(nb)

        while len(room) < target and frontier:
            pick = rng.choice(frontier)
            frontier.remove(pick)
            if pick.grid_ijk not in unassigned:
                continue
            room.append(unassigned.pop(pick.grid_ijk))
            for nb in pick.neighbors.values():
                if nb and nb.grid_ijk in unassigned and nb not in frontier:
                    frontier.append(nb)

        for vox in room:
            room_map[vox.grid_ijk] = room_id
        room_id += 1

    return room_map


def _distribute_grid(voxels, gw, gh):
    """
    Group voxels into regular gw × gh plan-grid rooms.
    Each floor level is independent (k stays separate).
    """
    room_map = {}
    for vox in voxels:
        i, j, k = vox.grid_ijk
        room_map[vox.grid_ijk] = (i // gw, j // gh, k)
    return room_map


def _distribute_voronoi(voxels, num_seeds, seed):
    """
    Place `num_seeds` random seed-voxels; assign every other voxel to the
    nearest seed (Euclidean in 3-D).  Produces irregular organic rooms.
    """
    import random
    rng    = random.Random(seed)
    n      = max(2, min(num_seeds, len(voxels)))
    seeds  = rng.sample(voxels, n)
    s_pts  = [(s.center.X, s.center.Y, s.center.Z) for s in seeds]
    room_map = {}
    for vox in voxels:
        cx, cy, cz = vox.center.X, vox.center.Y, vox.center.Z
        best = min(range(n),
                   key=lambda idx: (cx - s_pts[idx][0])**2 +
                                   (cy - s_pts[idx][1])**2 +
                                   (cz - s_pts[idx][2])**2)
        room_map[vox.grid_ijk] = best
    return room_map


def _distribute_linear_bands(voxels, axis, band_w):
    """
    Strip rooms running along `axis` ('X' or 'Y').
    band_w = width of each strip in voxel units.
    Each floor level is independent.
    """
    room_map = {}
    for vox in voxels:
        i, j, k = vox.grid_ijk
        band_id  = (j // band_w, k) if axis == "X" else (i // band_w, k)
        room_map[vox.grid_ijk] = band_id
    return room_map


def _distribute_rooms(voxels, dist_type, min_sz, max_sz, rand_seed):
    """
    Dispatcher — returns {grid_ijk: room_id}.
    dist_type: "Single Voxel" | "Random Clusters" |
               "Grid 2×2" | "Grid 2×3" | "Grid 3×3" |
               "Voronoi" | "Bands X" | "Bands Y"
    """
    if dist_type == "Random Clusters":
        return _distribute_random_clusters(voxels, min_sz, max_sz, rand_seed)
    elif dist_type == "Grid 2\u00d72":
        return _distribute_grid(voxels, 2, 2)
    elif dist_type == "Grid 2\u00d73":
        return _distribute_grid(voxels, 2, 3)
    elif dist_type == "Grid 3\u00d73":
        return _distribute_grid(voxels, 3, 3)
    elif dist_type == "Voronoi":
        return _distribute_voronoi(voxels, max_sz, rand_seed)   # max_sz = num seeds
    elif dist_type == "Bands X":
        return _distribute_linear_bands(voxels, "X", max(1, min_sz))
    elif dist_type == "Bands Y":
        return _distribute_linear_bands(voxels, "Y", max(1, min_sz))
    else:  # "Single Voxel"
        return _distribute_single(voxels)

def _face_slab(vox, face_dir, thickness):
    """Thin solid slab on a voxel face (floor / ceiling / party wall)."""
    half   = vox.size / 2.0
    normal = FACE_DIRS[face_dir]
    fc     = rg.Point3d(
        vox.center.X + normal.X * half,
        vox.center.Y + normal.Y * half,
        vox.center.Z + normal.Z * half,
    )
    if abs(normal.Z) > 0.9:               # horizontal slab
        origin = rg.Point3d(fc.X - half, fc.Y - half, fc.Z)
        box = rg.Box(
            rg.Plane(origin, rg.Vector3d.XAxis, rg.Vector3d.YAxis),
            rg.Interval(0, vox.size),
            rg.Interval(0, vox.size),
            rg.Interval(0, thickness if normal.Z > 0 else -thickness),
        )
    else:                                  # vertical wall slab
        x_ax = rg.Vector3d.CrossProduct(normal, rg.Vector3d.ZAxis)
        x_ax.Unitize()
        origin = rg.Point3d(
            fc.X - x_ax.X * half - normal.X * thickness * 0.5,
            fc.Y - x_ax.Y * half - normal.Y * thickness * 0.5,
            vox.center.Z - half,
        )
        box = rg.Box(
            rg.Plane(origin, x_ax, rg.Vector3d.ZAxis),
            rg.Interval(0, vox.size),
            rg.Interval(0, vox.size),
            rg.Interval(0, thickness),
        )
    return box.ToBrep() if box.IsValid else None


def _window_frame(vox, face_dir, wwr):
    """
    Planar frame surface (wall with rectangular void) on a voxel face.
    wwr = window-to-wall ratio  0.0 – 1.0.
    """
    half   = vox.size / 2.0
    normal = FACE_DIRS[face_dir]
    fc     = rg.Point3d(
        vox.center.X + normal.X * half,
        vox.center.Y + normal.Y * half,
        vox.center.Z + normal.Z * half,
    )
    if abs(normal.Z) < 0.99:
        x_ax = rg.Vector3d.CrossProduct(normal, rg.Vector3d.ZAxis)
    else:
        x_ax = rg.Vector3d.XAxis
    x_ax.Unitize()
    y_ax = rg.Vector3d.CrossProduct(x_ax, normal)
    y_ax.Unitize()

    oh = half * 0.98     # outer half-size (slight inset)
    wh = oh * math.sqrt(max(0.01, min(wwr, 0.99)))  # window half-size

    def _rect(h):
        pts = [
            fc + x_ax * (-h) + y_ax * (-h),
            fc + x_ax * ( h) + y_ax * (-h),
            fc + x_ax * ( h) + y_ax * ( h),
            fc + x_ax * (-h) + y_ax * ( h),
        ]
        return rg.PolylineCurve([pts[0], pts[1], pts[2], pts[3], pts[0]])

    outer = _rect(oh)
    inner = _rect(wh)
    tol   = sc.doc.ModelAbsoluteTolerance
    breps = rg.Brep.CreatePlanarBreps([outer, inner], tol)
    if breps and len(breps) > 0:
        return breps[0]
    return None


def apply_room_mode(voxels_dict, target_layers, wwr, side_treatment, slab_t,
                    dist_type="Single Voxel", min_sz=1, max_sz=4, rand_seed=42,
                    place_at="All voxels"):
    """
    Multi-voxel room distribution logic.

    dist_type   : see _distribute_rooms()
    min_sz      : min voxels per room  (Random Clusters) / band width (Bands)
    max_sz      : max voxels per room  (Random Clusters) / num seeds  (Voronoi)
    rand_seed   : random seed for reproducible layouts

    Face rules (after room assignment):
      same room, any direction → open void
      different room (any)    → party wall slab
      no neighbour / exterior → exterior treatment (window/solid/open)
      top / bottom            → floor/ceiling slab  (always)
    """
    layer_name = ensure_output_layer("Room")
    wwr_ratio  = wwr / 100.0
    n_items    = 0
    all_guids  = []

    # ── 1. Gather all target voxels ───────────────────────────────────────────
    raw_vox    = _target_voxels(voxels_dict, target_layers)
    target_vox = _filter_by_place_at(raw_vox, place_at)
    if not target_vox:
        return 0, 0

    target_set = {v.grid_ijk for v in target_vox}   # fast membership check

    # ── 2. Distribute into rooms ──────────────────────────────────────────────
    room_map   = _distribute_rooms(target_vox, dist_type, min_sz, max_sz, rand_seed)
    n_rooms    = len(set(room_map.values()))

    # ── 3. Generate geometry per face ─────────────────────────────────────────
    for vox in target_vox:
        my_room = room_map.get(vox.grid_ijk)

        for face_dir in ALL_FACES:
            nb    = vox.neighbors.get(face_dir)
            ftype = vox.face_types.get(face_dir, "exterior")

            # ── Floor / Ceiling: always solid slab ───────────────────────────
            if ftype in ("top", "bottom"):
                b = _face_slab(vox, face_dir, slab_t)
                if b:
                    g = _add_brep(b, layer_name)
                    if g: all_guids.append(g)
                    n_items += 1
                continue

            # ── Side faces ───────────────────────────────────────────────────
            if face_dir not in SIDE_FACES:
                continue

            nb_in_target = nb and nb.grid_ijk in target_set
            same_room    = nb_in_target and room_map.get(nb.grid_ijk) == my_room

            if same_room:
                # Within the same room → void (open space)
                continue

            elif nb_in_target and not same_room:
                # Adjacent room or different program zone → party wall
                b = _face_slab(vox, face_dir, slab_t)
                if b:
                    g = _add_brep(b, layer_name)
                    if g: all_guids.append(g)
                    n_items += 1

            else:
                # Exterior face (no target neighbour)
                if side_treatment == "Window Frame":
                    b = _window_frame(vox, face_dir, wwr_ratio)
                    if b:
                        g = _add_brep(b, layer_name)
                        if g: all_guids.append(g)
                        n_items += 1
                elif side_treatment == "Solid":
                    b = _face_slab(vox, face_dir, slab_t)
                    if b:
                        g = _add_brep(b, layer_name)
                        if g: all_guids.append(g)
                        n_items += 1
                # "Open" → nothing

    import time as _time
    _group_objects(all_guids, "VOXELGEN_Room_{}".format(int(_time.time())))
    return n_items, n_rooms


# ==============================================================================
#  FACADE MODE  —  Object-Orient Distribution
# ==============================================================================

def _combined_bb(geos):
    """Union bounding box of a list of geometries."""
    bb = rg.BoundingBox.Empty
    for g in geos:
        bb = rg.BoundingBox.Union(bb, g.GetBoundingBox(True))
    return bb


def _orient_geos(geos, src_plane, target_plane):
    """Duplicate and transform a list of geometries from src_plane to target_plane."""
    xform = rg.Transform.PlaneToPlane(src_plane, target_plane)
    results = []
    for g in geos:
        dup = g.Duplicate()
        dup.Transform(xform)
        results.append(dup)
    return results


def _add_geos(geos, layer_name):
    """Add a list of geometries to a layer. Returns list of added GUIDs."""
    attrs = rd.ObjectAttributes()
    idx   = sc.doc.Layers.FindByFullPath(layer_name, -1)
    if idx >= 0:
        attrs.LayerIndex = idx
    added = []
    for g in geos:
        guid = None
        if isinstance(g, rg.Brep):
            guid = sc.doc.Objects.AddBrep(g, attrs)
        elif isinstance(g, rg.Mesh):
            guid = sc.doc.Objects.AddMesh(g, attrs)
        else:
            try:
                guid = sc.doc.Objects.Add(g, attrs)
            except Exception:
                pass
        if guid is not None and guid != System.Guid.Empty:
            added.append(guid)
    return added


def _group_objects(guids, group_name):
    """Add guids to a new named group. Returns group name."""
    valid = [g for g in guids if g != System.Guid.Empty]
    if not valid:
        return None
    gidx = sc.doc.Groups.Add(group_name)
    sc.doc.Groups.AddToGroup(gidx, valid)
    return group_name


def _facade_core(voxels, source_geos, face_filter, offset_dist, every_n,
                 scale_to_fit, layer_name):
    """Inner loop for facade placement — returns (count, guid_list)."""
    src_bb     = _combined_bb(source_geos)
    src_origin = rg.Point3d(src_bb.Center.X, src_bb.Center.Y, src_bb.Min.Z)
    src_plane  = rg.Plane(src_origin, rg.Vector3d.ZAxis)
    src_face_w = src_bb.Max.X - src_bb.Min.X
    src_face_h = src_bb.Max.Y - src_bb.Min.Y
    src_size   = max(src_face_w, src_face_h, 1e-6)

    face_idx  = 0
    count     = 0
    guids     = []

    for vox in voxels:
        for face_dir in ALL_FACES:
            ftype = vox.face_types.get(face_dir, "exterior")
            if ftype not in ("exterior", "top", "bottom", "inter_program"):
                continue
            if ftype == "interior":
                continue

            if face_filter == "Sides only"     and face_dir in ("+Z", "-Z"):
                continue
            if face_filter == "Top/Bottom only" and face_dir in SIDE_FACES:
                continue
            if face_filter == "N/S only"        and face_dir not in ("+Y", "-Y"):
                continue
            if face_filter == "E/W only"        and face_dir not in ("+X", "-X"):
                continue

            if every_n > 1 and (face_idx % every_n) != 0:
                face_idx += 1
                continue
            face_idx += 1

            target_plane = get_face_plane(vox, face_dir)

            if offset_dist:
                normal = FACE_DIRS[face_dir]
                target_plane.Origin = rg.Point3d(
                    target_plane.Origin.X + normal.X * offset_dist,
                    target_plane.Origin.Y + normal.Y * offset_dist,
                    target_plane.Origin.Z + normal.Z * offset_dist,
                )

            oriented_geos = _orient_geos(source_geos, src_plane, target_plane)

            if scale_to_fit and src_size > 1e-6:
                sf    = vox.size / src_size
                xform = rg.Transform.Scale(target_plane.Origin, sf)
                for g in oriented_geos:
                    g.Transform(xform)

            guids.extend(_add_geos(oriented_geos, layer_name))
            count += 1

    return count, guids


def apply_facade_mode(voxels_dict, target_layers, source_geos,
                      face_filter, offset_dist, every_n, scale_to_fit,
                      place_at="All voxels",
                      src_geos_b=None, src_geos_c=None, cluster_seed=0):
    """Orient source elements to exterior faces using PlaneToPlane transform.
    place_at        : any PLACE_AT_OPTIONS value including "Random Cluster Groups"
    src_geos_b/c    : optional alternate source geometries for clusters B and C
    """
    layer_name = ensure_output_layer("Facade")
    raw_vox    = _target_voxels(voxels_dict, target_layers)
    count      = 0
    all_guids  = []

    if place_at == "Random Cluster Groups":
        clusters = _split_3_clusters(raw_vox, seed=cluster_seed)
        geos_abc = [
            source_geos,
            src_geos_b if src_geos_b else source_geos,
            src_geos_c if src_geos_c else source_geos,
        ]
        for cluster_voxels, cluster_geos in zip(clusters, geos_abc):
            if not cluster_voxels or not cluster_geos:
                continue
            n, guids = _facade_core(cluster_voxels, cluster_geos,
                                    face_filter, offset_dist, every_n,
                                    scale_to_fit, layer_name)
            count    += n
            all_guids.extend(guids)
    else:
        voxels = _filter_by_place_at(raw_vox, place_at)
        count, all_guids = _facade_core(voxels, source_geos,
                                        face_filter, offset_dist, every_n,
                                        scale_to_fit, layer_name)

    import time as _time
    _group_objects(all_guids, "VOXELGEN_Facade_{}".format(int(_time.time())))
    return count


# ==============================================================================
#  DISCRETE MODE  —  Combinatorial Distribution (Retsin / Discrete Economies)
# ==============================================================================

def _find_chains_3(voxels_set, voxels_dict):
    """Return list of (vox_a, vox_b, vox_c, face_dir) for collinear triples."""
    seen   = set()
    chains = []
    voxels_set_keys = {v.grid_ijk for v in voxels_set}
    for vox in voxels_set:
        for fd, (di, dj, dk) in FACE_TO_OFFSET.items():
            i, j, k = vox.grid_ijk
            ijk_b = (i + di,     j + dj,     k + dk)
            ijk_c = (i + 2*di,  j + 2*dj,  k + 2*dk)
            if ijk_b not in voxels_dict or ijk_c not in voxels_dict:
                continue
            if ijk_b not in voxels_set_keys or ijk_c not in voxels_set_keys:
                continue
            key = tuple(sorted([vox.grid_ijk, ijk_b, ijk_c]))
            if key in seen:
                continue
            seen.add(key)
            chains.append((vox, voxels_dict[ijk_b], voxels_dict[ijk_c], fd))
    return chains


def _find_chains_n(n, voxels_set, voxels_dict):
    """
    V7: Return list of [Voxel, ...] chains of exactly n collinear adjacent voxels.
    Works for any n ≥ 2.  For n=2 returns pairs (same as span-2 bridge).
    Deduplicates so each chain is counted once regardless of which end we start from.
    """
    if n < 2:
        return []
    vox_keys = {v.grid_ijk for v in voxels_set}
    seen, chains = set(), []
    for vox in voxels_set:
        ci, cj, ck = vox.grid_ijk
        for fd, (di, dj, dk) in FACE_TO_OFFSET.items():
            # Build the full chain of n ijks starting from vox in direction fd
            chain_ijks = [(ci + di*s, cj + dj*s, ck + dk*s) for s in range(n)]
            # All cells must be in the voxels_dict AND the vox filter set
            if not all(ijk in voxels_dict and ijk in vox_keys for ijk in chain_ijks):
                continue
            # Dedup: canonical key is the sorted tuple of all ijks
            key = tuple(sorted(chain_ijks))
            if key in seen:
                continue
            seen.add(key)
            chains.append([voxels_dict[ijk] for ijk in chain_ijks])
    return chains


def _build_bridge_plane(vox_a, vox_b, face_dir):
    """Plane centred between two adjacent voxels, ZAxis = span direction."""
    mid     = rg.Point3d(
        (vox_a.center.X + vox_b.center.X) * 0.5,
        (vox_a.center.Y + vox_b.center.Y) * 0.5,
        (vox_a.center.Z + vox_b.center.Z) * 0.5,
    )
    span_v  = FACE_DIRS[face_dir]
    if abs(span_v.Z) < 0.99:
        x_ax = rg.Vector3d.CrossProduct(rg.Vector3d.ZAxis, span_v)
    else:
        x_ax = rg.Vector3d.XAxis
    x_ax.Unitize()
    y_ax = rg.Vector3d.CrossProduct(span_v, x_ax)
    y_ax.Unitize()
    return rg.Plane(mid, x_ax, y_ax)


def _apply_interlocking_joints(placed_guids, tolerance=0.001):
    """
    Detect overlapping placed Breps and cut half-lap interlocking joints.
    For each pair whose bounding boxes intersect, the boolean intersection
    volume is subtracted from BOTH elements — creating a mutual notch.
    Non-Brep geometry (Mesh, etc.) is skipped gracefully.
    Returns the number of joints cut.
    """
    # Collect all breps + bounding boxes from doc
    items = []
    for guid in placed_guids:
        obj = sc.doc.Objects.FindId(guid)
        if obj is None or obj.IsDeleted:
            continue
        geo = obj.Geometry
        if not isinstance(geo, rg.Brep):
            continue
        bb = geo.GetBoundingBox(True)
        if bb.IsValid:
            items.append([geo, guid, bb])   # list so we can update geo after Replace

    joints_cut = 0
    replaced   = {}   # guid → updated brep (avoid using stale refs)

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            gi, guid_i, bb_i = items[i]
            gj, guid_j, bb_j = items[j]

            # Use most-recent brep if already modified
            brep_i = replaced.get(guid_i, gi)
            brep_j = replaced.get(guid_j, gj)

            # Fast bbox rejection
            expand = tolerance * 2
            if (bb_i.Min.X > bb_j.Max.X + expand or bb_i.Max.X < bb_j.Min.X - expand or
                bb_i.Min.Y > bb_j.Max.Y + expand or bb_i.Max.Y < bb_j.Min.Y - expand or
                bb_i.Min.Z > bb_j.Max.Z + expand or bb_i.Max.Z < bb_j.Min.Z - expand):
                continue

            try:
                # Compute intersection volume
                int_list = rg.Brep.CreateBooleanIntersection(
                    [brep_i], [brep_j], tolerance)
                if not int_list:
                    continue
                int_brep = int_list[0]
                if not int_brep.IsValid:
                    continue

                # Subtract intersection from each element → mutual notch
                cut_i = rg.Brep.CreateBooleanDifference(
                    [brep_i], [int_brep], tolerance)
                cut_j = rg.Brep.CreateBooleanDifference(
                    [brep_j], [int_brep], tolerance)

                if cut_i and cut_i[0].IsValid:
                    sc.doc.Objects.Replace(guid_i, cut_i[0])
                    replaced[guid_i] = cut_i[0]
                    # Update bbox for further pair tests
                    items[i][2] = cut_i[0].GetBoundingBox(True)
                    joints_cut += 1

                if cut_j and cut_j[0].IsValid:
                    sc.doc.Objects.Replace(guid_j, cut_j[0])
                    replaced[guid_j] = cut_j[0]
                    items[j][2] = cut_j[0].GetBoundingBox(True)
                    joints_cut += 1

            except Exception as _ex:
                print(">>> Joint cut failed: {}".format(_ex))

    return joints_cut


# ==============================================================================
#  SOLAR VOXEL ANALYSIS  —  EPW + Ray Shadow Casting (Option 3)
# ==============================================================================

def _parse_epw(epw_path):
    """
    Parse an EnergyPlus EPW weather file.
    Returns (lat_deg, lon_deg, tz_offset, hourly_rows) where:
      hourly_rows = list of dicts {month, day, hour, ghi, dni, dhi}
    """
    rows = []
    lat = lon = tz = 0.0
    try:
        with open(epw_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        # Line 1: LOCATION header
        loc_parts = lines[0].split(",")
        lat = float(loc_parts[6])
        lon = float(loc_parts[7])
        tz  = float(loc_parts[8])
        # Data starts at line 9 (index 8)
        for line in lines[8:]:
            parts = line.strip().split(",")
            if len(parts) < 22:
                continue
            try:
                month = int(parts[1])
                day   = int(parts[2])
                hour  = int(parts[3])   # 1–24 in EPW
                ghi   = max(0.0, float(parts[13]))   # Global Horiz Radiation Wh/m²
                dni   = max(0.0, float(parts[14]))   # Direct Normal Radiation Wh/m²
                dhi   = max(0.0, float(parts[15]))   # Diffuse Horiz Radiation Wh/m²
                rows.append({"month": month, "day": day, "hour": hour,
                             "ghi": ghi, "dni": dni, "dhi": dhi})
            except (ValueError, IndexError):
                continue
    except Exception as ex:
        print(">>> _parse_epw error: {}".format(ex))
    return lat, lon, tz, rows


def _day_of_year(month, day):
    """Return 1-based day-of-year."""
    _MONTH_DAYS = [31,28,31,30,31,30,31,31,30,31,30,31]
    return sum(_MONTH_DAYS[:month - 1]) + day


def _sun_position(lat_deg, month, day, hour_epw):
    """
    Compute sun altitude and azimuth for given location and time.
    hour_epw: 1–24 (EPW convention, represents end of hour)
    Returns (alt_deg, az_deg) where az is from North clockwise (0=N, 90=E, 180=S, 270=W)
    Returns None if sun is below horizon.
    """
    import math as _m
    solar_hour = hour_epw - 0.5          # midpoint of the EPW hour
    lat_r = _m.radians(lat_deg)
    doy   = _day_of_year(month, day)
    # Solar declination
    dec_r = _m.radians(23.45 * _m.sin(_m.radians(360.0 / 365.0 * (284 + doy))))
    # Hour angle (negative morning, 0 noon, positive afternoon)
    ha_r  = _m.radians(15.0 * (solar_hour - 12.0))
    # Solar altitude
    sin_alt = (_m.sin(lat_r) * _m.sin(dec_r)
               + _m.cos(lat_r) * _m.cos(dec_r) * _m.cos(ha_r))
    if sin_alt <= 0.0:
        return None
    alt_r   = _m.asin(max(-1.0, min(1.0, sin_alt)))
    cos_alt = _m.cos(alt_r)
    # Solar azimuth (measured from South for standard formula)
    if cos_alt < 1e-9:
        return _m.degrees(alt_r), 180.0
    cos_az  = (_m.sin(dec_r) - _m.sin(lat_r) * sin_alt) / (_m.cos(lat_r) * cos_alt)
    cos_az  = max(-1.0, min(1.0, cos_az))
    az_from_south = _m.degrees(_m.acos(cos_az))
    # Convert to azimuth from North (0=N, 90=E, 180=S, 270=W)
    if solar_hour > 12.0:
        az_north = 180.0 + az_from_south   # afternoon → west
    else:
        az_north = 180.0 - az_from_south   # morning → east
    return _m.degrees(alt_r), az_north % 360.0


def _sun_vec_from_alt_az(alt_deg, az_deg):
    """
    Convert solar altitude + azimuth (from North, clockwise) to a Rhino unit vector.
    Assumes Rhino: +X = East, +Y = North, +Z = Up.
    """
    import math as _m
    alt_r = _m.radians(alt_deg)
    az_r  = _m.radians(az_deg)
    return rg.Vector3d(
        _m.sin(az_r) * _m.cos(alt_r),   # East (+X)
        _m.cos(az_r) * _m.cos(alt_r),   # North (+Y)
        _m.sin(alt_r)                    # Up (+Z)
    )


def _shadow_march(ijk, sun_step, voxels_dict, max_steps=60):
    """
    March a ray from ijk in the direction of sun_step (tuple of float grid offsets).
    Returns True if another voxel is encountered before max_steps (= face is in shadow).
    sun_step: (di_f, dj_f, dk_f) — unit sun direction in fractional grid coords.
    """
    di, dj, dk = sun_step
    ci, cj, ck = ijk
    for t in range(1, max_steps + 1):
        ni = int(round(ci + di * t))
        nj = int(round(cj + dj * t))
        nk = int(round(ck + dk * t))
        test_ijk = (ni, nj, nk)
        if test_ijk == ijk:
            continue
        if test_ijk in voxels_dict:
            return True
    return False


def _bake_solar_voxels(voxels_dict, epw_path,
                        use_occlusion=True, key_hours_only=False,
                        thresh_crit=600.0, thresh_high=400.0,
                        thresh_med=200.0,  thresh_low=50.0):
    """
    Compute per-voxel annual solar radiation (kWh/m²/year) using EPW data.
    With use_occlusion=True: casts shadow rays between voxels for each sun position.
    Returns {ijk: tier_str} where tier_str is one of:
      'Solar_5_CritHigh', 'Solar_4_High', 'Solar_3_Med', 'Solar_2_Low', 'Solar_1_Shade'
    Also returns hourly_sun_data list for solar chart drawing.
    """
    import math as _m

    lat, lon, tz, hourly_rows = _parse_epw(epw_path)

    # ── Build list of unique daytime sun positions + accumulated DNI ──────────
    # Group hourly rows by rounded sun direction (5° az, 5° alt bins) for speed.
    from collections import defaultdict
    sun_buckets = defaultdict(float)   # (az_bin, alt_bin) → total DNI (Wh/m²)
    sun_positions = {}                 # (az_bin, alt_bin) → (alt_deg, az_deg)

    # For chart: store individual sun path points
    sun_path_pts = []   # list of {month, day, hour, alt, az, dni, ghi}

    if key_hours_only:
        # Use 8 representative months × 6 hours = 48 sun positions (fast preview)
        rep_months = [1, 2, 4, 6, 8, 10, 11, 12]
        rep_hours  = [7, 9, 11, 13, 15, 17]
        rep_day    = 15   # middle of month
        epw_map    = {}   # (month, day, hour) → row
        for r in hourly_rows:
            if r["month"] in rep_months and r["day"] == rep_day and r["hour"] in rep_hours:
                epw_map[(r["month"], r["day"], r["hour"])] = r
        for mo in rep_months:
            for hr in rep_hours:
                row = epw_map.get((mo, rep_day, hr))
                if row is None: continue
                pos = _sun_position(lat, mo, rep_day, hr)
                if pos is None: continue
                alt_d, az_d = pos
                if alt_d <= 0: continue
                az_b  = int(round(az_d  / 5.0)) * 5
                alt_b = int(round(alt_d / 5.0)) * 5
                sun_buckets[(az_b, alt_b)] += row["dni"] * (8760 / 48.0)
                sun_positions[(az_b, alt_b)] = (alt_d, az_d)
                sun_path_pts.append({"month": mo, "day": rep_day, "hour": hr,
                                     "alt": alt_d, "az": az_d,
                                     "dni": row["dni"], "ghi": row["ghi"]})
    else:
        for row in hourly_rows:
            if row["dni"] < 1.0: continue   # skip night / overcast
            pos = _sun_position(lat, row["month"], row["day"], row["hour"])
            if pos is None: continue
            alt_d, az_d = pos
            if alt_d <= 2.0: continue   # below effective horizon
            az_b  = int(round(az_d  / 5.0)) * 5
            alt_b = int(round(alt_d / 5.0)) * 5
            sun_buckets[(az_b, alt_b)] += row["dni"]   # Wh/m²
            sun_positions[(az_b, alt_b)] = (alt_d, az_d)
            sun_path_pts.append({"month": row["month"], "day": row["day"],
                                 "hour": row["hour"],
                                 "alt": alt_d, "az": az_d,
                                 "dni": row["dni"], "ghi": row["ghi"]})

    print(">>> Solar: {} unique sun positions from EPW, lat={:.2f}°".format(
        len(sun_buckets), lat))

    # ── Accumulate radiation per voxel face ───────────────────────────────────
    vox_list = list(voxels_dict.values())
    if not vox_list:
        return {}, sun_path_pts

    vox_size = vox_list[0].size
    # Per-voxel radiation accumulator: max face radiation (W×h/m²)
    vox_rad   = {ijk: 0.0 for ijk in voxels_dict}

    FACE_NORMALS = {
        "+X": (1,0,0), "-X": (-1,0,0),
        "+Y": (0,1,0), "-Y": (0,-1,0),
        "+Z": (0,0,1), "-Z": (0,0,-1),
    }

    total_pos = len(sun_buckets)
    for idx, ((az_b, alt_b), total_dni) in enumerate(sun_buckets.items()):
        alt_d, az_d = sun_positions[(az_b, alt_b)]
        sv   = _sun_vec_from_alt_az(alt_d, az_d)
        # Sun direction in fractional grid units (1 unit = 1 voxel)
        sun_step = (sv.X, sv.Y, sv.Z)   # already normalized world-unit
        total_dni_kwh = total_dni / 1000.0   # Wh → kWh

        for ijk, vox in voxels_dict.items():
            # Shadow check
            in_shadow = False
            if use_occlusion:
                in_shadow = _shadow_march(ijk, sun_step, voxels_dict)
            if in_shadow:
                continue
            # Best face contribution: max dot product across all 6 faces
            best_dot = 0.0
            for fd, (nx, ny, nz) in FACE_NORMALS.items():
                dot = nx * sv.X + ny * sv.Y + nz * sv.Z
                if dot > best_dot:
                    best_dot = dot
            # Accumulate: radiation (kWh/m²) × face exposure
            vox_rad[ijk] += total_dni_kwh * best_dot

        if (idx + 1) % 50 == 0:
            print(">>> Solar progress: {}/{} sun positions".format(idx+1, total_pos))

    # ── Classify into 5 tiers ─────────────────────────────────────────────────
    result = {}
    for ijk, rad in vox_rad.items():
        if   rad >= thresh_crit: tier = "Solar_5_CritHigh"
        elif rad >= thresh_high: tier = "Solar_4_High"
        elif rad >= thresh_med:  tier = "Solar_3_Med"
        elif rad >= thresh_low:  tier = "Solar_2_Low"
        else:                    tier = "Solar_1_Shade"
        result[ijk] = tier

    tier_counts = {}
    for t in result.values():
        tier_counts[t] = tier_counts.get(t, 0) + 1
    print(">>> Solar tiers: {}".format(tier_counts))

    return result, sun_path_pts


def _draw_solar_chart(lat_deg, sun_path_pts, chart_origin, chart_radius=10.0,
                      vox_shade_freq=None):
    """
    Draw a stereographic sun path diagram in Rhino world space.
    chart_origin : rg.Point3d — centre of chart in Rhino
    chart_radius : float — radius in Rhino model units
    vox_shade_freq : dict {(az_b, alt_b): fraction_shadowed} for shading overlay
    Returns list of Rhino GUIDs added to VOXELGEN_Solar_Chart layer.
    """
    import math as _m

    chart_layer = ensure_output_layer("Solar_Chart")
    guids = []

    ox, oy, oz = chart_origin.X, chart_origin.Y, chart_origin.Z

    def _polar_to_xy(alt_d, az_d):
        """Convert altitude+azimuth to 2D chart coordinates (flat polar)."""
        r = chart_radius * (1.0 - alt_d / 90.0)   # r=radius at horizon, 0 at zenith
        az_r = _m.radians(az_d)
        return ox + r * _m.sin(az_r), oy + r * _m.cos(az_r)

    def _add_curve(pts2d, layer):
        pts3d = [rg.Point3d(x, y, oz) for x, y in pts2d]
        if len(pts3d) < 2: return None
        crv = rg.Polyline(pts3d).ToNurbsCurve()
        guid = sc.doc.Objects.AddCurve(crv)
        if guid:
            obj = sc.doc.Objects.FindId(guid)
            if obj:
                attr = obj.Attributes.Duplicate()
                attr.LayerIndex = sc.doc.Layers.FindName(layer).Index
                sc.doc.Objects.ModifyAttributes(obj, attr, True)
            guids.append(guid)
        return guid

    # ── Altitude rings ────────────────────────────────────────────────────────
    for alt in [10, 20, 30, 40, 50, 60, 70, 80]:
        r = chart_radius * (1.0 - alt / 90.0)
        pts = []
        for az_step in range(0, 361, 5):
            az_r = _m.radians(az_step)
            pts.append((ox + r * _m.sin(az_r), oy + r * _m.cos(az_r)))
        pts.append(pts[0])  # close
        _add_curve(pts, chart_layer)

    # Horizon outer circle
    pts = []
    for az_step in range(0, 361, 5):
        az_r = _m.radians(az_step)
        pts.append((ox + chart_radius * _m.sin(az_r), oy + chart_radius * _m.cos(az_r)))
    pts.append(pts[0])
    _add_curve(pts, chart_layer)

    # ── Azimuth lines ─────────────────────────────────────────────────────────
    for az in range(0, 360, 30):
        az_r = _m.radians(az)
        x0 = ox + chart_radius * 0.05 * _m.sin(az_r)
        y0 = oy + chart_radius * 0.05 * _m.cos(az_r)
        x1 = ox + chart_radius * _m.sin(az_r)
        y1 = oy + chart_radius * _m.cos(az_r)
        _add_curve([(x0, y0), (x1, y1)], chart_layer)

    # ── Compass labels ────────────────────────────────────────────────────────
    compass = {0: "N", 90: "E", 180: "S", 270: "W",
               45: "NE", 135: "SE", 225: "SW", 315: "NW"}
    for az_d, label in compass.items():
        r = chart_radius * 1.12
        az_r = _m.radians(az_d)
        pt = rg.Point3d(ox + r * _m.sin(az_r), oy + r * _m.cos(az_r), oz)
        g = sc.doc.Objects.AddTextDot(label, pt)
        if g:
            obj = sc.doc.Objects.FindId(g)
            if obj:
                attr = obj.Attributes.Duplicate()
                attr.LayerIndex = sc.doc.Layers.FindName(chart_layer).Index
                sc.doc.Objects.ModifyAttributes(obj, attr, True)
            guids.append(g)

    # Altitude labels
    for alt in [30, 60]:
        px, py = _polar_to_xy(alt, 0)   # label at North direction
        pt = rg.Point3d(px - chart_radius * 0.05, py, oz)
        label = "{}°".format(alt)
        g = sc.doc.Objects.AddTextDot(label, pt)
        if g:
            obj = sc.doc.Objects.FindId(g)
            if obj:
                attr = obj.Attributes.Duplicate()
                attr.LayerIndex = sc.doc.Layers.FindName(chart_layer).Index
                sc.doc.Objects.ModifyAttributes(obj, attr, True)
            guids.append(g)

    # ── Sun path curves for 3 key days ────────────────────────────────────────
    key_days = [
        (1,  21, "Jan 21 (Summer-SH)"),    # Southern Hemisphere summer
        (6,  21, "Jun 21 (Winter-SH)"),    # Southern Hemisphere winter
        (3,  21, "Mar 21 (Equinox)"),
    ]
    for month, day, label in key_days:
        path_pts = []
        for hr in range(4, 22):
            pos = _sun_position(lat_deg, month, day, hr)
            if pos is None: continue
            alt_d, az_d = pos
            if alt_d <= 0: continue
            x, y = _polar_to_xy(alt_d, az_d)
            path_pts.append((x, y))
        if len(path_pts) >= 2:
            _add_curve(path_pts, chart_layer)

    # ── Individual sun position dots (coloured by DNI) ────────────────────────
    # Gather unique sun positions with max DNI
    dot_map = {}   # (month, day, hour) key → first occurrence
    for pt in sun_path_pts:
        k = (pt["month"], pt["day"], pt["hour"])
        if k not in dot_map:
            dot_map[k] = pt

    for k, pt in list(dot_map.items())[:2000]:   # cap for performance
        alt_d = pt["alt"]; az_d = pt["az"]; dni = pt["dni"]
        if alt_d <= 0: continue
        x, y = _polar_to_xy(alt_d, az_d)
        rhino_pt = rg.Point3d(x, y, oz)
        # Label: DNI value rounded
        lbl = "{:.0f}".format(dni) if dni > 0 else ""
        g = sc.doc.Objects.AddTextDot(lbl, rhino_pt)
        if g:
            obj = sc.doc.Objects.FindId(g)
            if obj:
                attr = obj.Attributes.Duplicate()
                # Color by DNI: red (high) → blue (low)
                t = min(dni / 900.0, 1.0)
                r_col = int(220 * t)
                b_col = int(180 * (1.0 - t))
                attr.ObjectColor = sd.Color.FromArgb(r_col, 80, b_col)
                attr.ColorSource = rd.ObjectColorSource.ColorFromObject
                attr.LayerIndex  = sc.doc.Layers.FindName(chart_layer).Index
                sc.doc.Objects.ModifyAttributes(obj, attr, True)
            guids.append(g)

    # ── Shading frequency overlay ─────────────────────────────────────────────
    if vox_shade_freq:
        for (az_b, alt_b), frac_shaded in vox_shade_freq.items():
            if alt_b <= 0: continue
            x, y = _polar_to_xy(float(alt_b), float(az_b))
            rhino_pt = rg.Point3d(x, y, oz + 0.05)
            lbl = "{:.0f}%".format(frac_shaded * 100)
            g = sc.doc.Objects.AddTextDot(lbl, rhino_pt)
            if g:
                obj = sc.doc.Objects.FindId(g)
                if obj:
                    attr = obj.Attributes.Duplicate()
                    # Blue = heavily shaded, white = unshaded
                    shade_c = int(200 * frac_shaded)
                    attr.ObjectColor = sd.Color.FromArgb(
                        200 - shade_c, 200 - shade_c, 200)
                    attr.ColorSource = rd.ObjectColorSource.ColorFromObject
                    attr.LayerIndex  = sc.doc.Layers.FindName(chart_layer).Index
                    sc.doc.Objects.ModifyAttributes(obj, attr, True)
                guids.append(g)

    # ── Title + legend ────────────────────────────────────────────────────────
    title_pt = rg.Point3d(ox, oy + chart_radius * 1.35, oz)
    g = sc.doc.Objects.AddTextDot(
        u"Solar Radiation  (lat {:.1f}\u00b0)".format(lat_deg), title_pt)
    if g:
        obj = sc.doc.Objects.FindId(g)
        if obj:
            attr = obj.Attributes.Duplicate()
            attr.LayerIndex = sc.doc.Layers.FindName(chart_layer).Index
            sc.doc.Objects.ModifyAttributes(obj, attr, True)
        guids.append(g)

    legend_items = [
        (u"\u25A0 CritHigh \u2265600 kWh/m\u00b2/yr",  sd.Color.FromArgb(220, 40, 40)),
        (u"\u25A0 High 400-600",                         sd.Color.FromArgb(240,140, 30)),
        (u"\u25A0 Medium 200-400",                       sd.Color.FromArgb(240,220, 50)),
        (u"\u25A0 Low 50-200",                           sd.Color.FromArgb( 60,180,220)),
        (u"\u25A0 Shade <50",                            sd.Color.FromArgb( 30, 60,130)),
    ]
    for li, (text, color) in enumerate(legend_items):
        lpt = rg.Point3d(ox + chart_radius * 1.25, oy + chart_radius * (0.8 - li * 0.35), oz)
        g = sc.doc.Objects.AddTextDot(text, lpt)
        if g:
            obj = sc.doc.Objects.FindId(g)
            if obj:
                attr = obj.Attributes.Duplicate()
                attr.ObjectColor = color
                attr.ColorSource = rd.ObjectColorSource.ColorFromObject
                attr.LayerIndex  = sc.doc.Layers.FindName(chart_layer).Index
                sc.doc.Objects.ModifyAttributes(obj, attr, True)
            guids.append(g)

    sc.doc.Views.Redraw()
    return guids


# ==============================================================================
#  LOW RESOLUTION (BAY) SUPER-VOXEL BUILDER
# ==============================================================================

def _build_super_voxels(voxels, voxels_dict, group_x, group_y, group_z=1):
    """
    Merge real voxels into SuperVoxel units for Low Resolution (Bay) mode.

    group_x, group_y, group_z : bay size in i, j, k grid steps (1–16).
        group_z=1 → no vertical grouping (one super-voxel per k level).
        group_z>1 → group group_z k-levels into one super-voxel.

    Incomplete bays at field edges are skipped (clean grid only).
    Returns list of SuperVoxel objects.
    """
    if not voxels:
        return []

    vs      = voxels[0].size
    vox_set = {v.grid_ijk: v for v in voxels}

    # ── Collect grid extent ────────────────────────────────────────────────────
    all_i = [ijk[0] for ijk in vox_set]
    all_j = [ijk[1] for ijk in vox_set]
    all_k = [ijk[2] for ijk in vox_set]
    i_min, j_min, k_min = min(all_i), min(all_j), min(all_k)
    i_max, j_max, k_max = max(all_i), max(all_j), max(all_k)

    group_z = max(1, int(group_z))

    super_voxels = []
    sv_lk        = {}    # (i0, j0, k0) → SuperVoxel

    # ── Unified stride scan: X, Y, Z ─────────────────────────────────────────
    for i0 in range(i_min, i_max + 1, group_x):
        for j0 in range(j_min, j_max + 1, group_y):
            for k0 in range(k_min, k_max + 1, group_z):
                k_lo = k0
                k_hi = k0 + group_z - 1

                # All (i,j,k) cells in this bay
                group_ijks = [
                    (i0 + di, j0 + dj, k0 + dk)
                    for di in range(group_x)
                    for dj in range(group_y)
                    for dk in range(group_z)
                ]
                # V14: include partial bays at field edges — use whatever voxels
                # are present.  Previously incomplete bays were silently skipped,
                # causing edge groups to produce no element even though real
                # voxels existed there.
                member_voxels = [vox_set[ijk] for ijk in group_ijks if ijk in vox_set]
                if not member_voxels:
                    continue   # truly empty cell — nothing to place

                # For partial bays compute effective extents from present members
                # so the placed element scales to the actual occupied footprint,
                # not the full nominal bay size.
                if len(member_voxels) < len(group_ijks):
                    p_i = set(ijk[0] for ijk in group_ijks if ijk in vox_set)
                    p_j = set(ijk[1] for ijk in group_ijks if ijk in vox_set)
                    p_k = set(ijk[2] for ijk in group_ijks if ijk in vox_set)
                    eff_gx = len(p_i)
                    eff_gy = len(p_j)
                    eff_nk = len(p_k)
                else:
                    eff_gx, eff_gy, eff_nk = group_x, group_y, group_z

                k_hi_eff = k_lo + eff_nk - 1
                n_k      = eff_nk

                sv = _make_super_voxel(
                    member_voxels, i0, j0, k_lo, k_hi_eff,
                    eff_gx, eff_gy, n_k, vs, vox_set)
                key = (i0, j0, k0)
                super_voxels.append(sv)
                sv_lk[key] = sv

    # ── Wire neighbors between super-voxels ───────────────────────────────────
    for (i0, j0, k0), sv in sv_lk.items():
        sv.neighbors["+X"] = sv_lk.get((i0 + group_x, j0,          k0))
        sv.neighbors["-X"] = sv_lk.get((i0 - group_x, j0,          k0))
        sv.neighbors["+Y"] = sv_lk.get((i0,           j0 + group_y, k0))
        sv.neighbors["-Y"] = sv_lk.get((i0,           j0 - group_y, k0))
        sv.neighbors["+Z"] = sv_lk.get((i0,           j0,           k0 + group_z))
        sv.neighbors["-Z"] = sv_lk.get((i0,           j0,           k0 - group_z))
        # Mark faces interior where a super-voxel neighbor exists
        for fd in ALL_FACES:
            if sv.neighbors.get(fd) is not None:
                sv.face_types[fd] = "interior"

    return super_voxels


def _make_super_voxel(member_voxels, i0, j0, k_lo, k_hi,
                      gx, gy, n_k, vs, vox_set):
    """Helper: build one SuperVoxel from a list of constituent Voxels."""
    cx = sum(v.center.X for v in member_voxels) / len(member_voxels)
    cy = sum(v.center.Y for v in member_voxels) / len(member_voxels)
    cz = sum(v.center.Z for v in member_voxels) / len(member_voxels)
    center = rg.Point3d(cx, cy, cz)

    # Representative layer from the first member
    layer_name = getattr(member_voxels[0], 'layer_name',
                         getattr(member_voxels[0], 'layer', ''))

    # face half-extents (distance from center to each face boundary)
    hx = gx * vs / 2.0     # half-extent in X (±X faces)
    hy = gy * vs / 2.0     # half-extent in Y (±Y faces)
    hz = n_k * vs / 2.0    # half-extent in Z (±Z faces)

    face_half = {
        "+X": hx, "-X": hx,
        "+Y": hy, "-Y": hy,
        "+Z": hz, "-Z": hz,
    }

    # face characteristic sizes: max(face_width, face_height)
    # ±X face: width=gy*vs (Y direction), height=nk*vs (Z direction)
    # ±Y face: width=gx*vs, height=nk*vs
    # ±Z face: width=gx*vs, height=gy*vs
    face_sizes = {
        "+X": max(gy, n_k) * vs, "-X": max(gy, n_k) * vs,
        "+Y": max(gx, n_k) * vs, "-Y": max(gx, n_k) * vs,
        "+Z": max(gx, gy)  * vs, "-Z": max(gx, gy)  * vs,
    }

    # Initial face_types: all exterior.
    # Faces that have a super-voxel neighbor will be overwritten to "interior"
    # during neighbor wiring in _build_super_voxels (after all SVs are created).
    # Z faces: also check whether real voxels exist directly above / below this
    # bay's footprint — if so, the Z face is blocked (interior) even though no
    # super-voxel neighbor exists at that position.
    face_types = {fd: "exterior" for fd in ALL_FACES}
    top_covered = any((i0 + di, j0 + dj, k_hi + 1) in vox_set
                      for di in range(gx) for dj in range(gy))
    bot_covered = any((i0 + di, j0 + dj, k_lo - 1) in vox_set
                      for di in range(gx) for dj in range(gy))
    if top_covered:
        face_types["+Z"] = "interior"
    if bot_covered:
        face_types["-Z"] = "interior"

    return SuperVoxel(
        center     = center,
        grid_ijk   = (i0, j0, k_lo),
        layer_name = layer_name,
        base_size  = vs,
        face_types = face_types,
        neighbors  = {fd: None for fd in ALL_FACES},
        face_half  = face_half,
        face_sizes = face_sizes,
    )


def apply_discrete_mode(
        voxels_dict, target_layers,
        src_geos_a,
        src_geos_b,        # None → falls back to A
        src_geos_c,        # None → falls back to resolved B
        assignment_rule,   # "By Z-level"|"By adjacency"|"By cluster"|"Random mix"
        span,              # int ≥ 1
        placement,         # "Exterior faces"|"Wall"|"Top edges"|"All exposed"|...
        orientation,       # "Face-normal"|"Rotated sequence"|"Edge-aligned"
        scale_to_fit,
        place_at,          # from PLACE_AT_OPTIONS
        cluster_seed, rand_seed,
        interlocking=False,
        constrain_to_field=False, field_margin=0.5,
        orient_strength=0.7,
        invert_place_at=False,
        shell_depth=1,
        _output_layer_override=None,
        # V7 new params
        invert_placement=False,
        sun_az=180.0, sun_alt=45.0, sun_thresh=60.0,
        attractor_pt=None,
        attr_radius=20.0, attr_min=0.0, attr_max=1.0,
        # V8 new params
        cluster_target="All",          # "All"|"A/B/C/D/E/F only" (V16)
        cluster_faces="All exposed",   # "All exposed"|"Wall cluster"|...
        cluster_invert=False,          # True → invert which faces cluster places on
        forced_label=None,             # "A".."F" — set by Sub-Placement sentinel (V16)
        place_inside=False,            # True → flip face normal inward (element inside voxel)
        # Resolution params (mutually exclusive — only one active)
        hi_res=1,                      # High-res: subdivide each face into hi_res×hi_res cells
        lo_res_x=1,                    # Low-res (Bay): group lo_res_x voxels in X per bay
        lo_res_y=1,                    # Low-res (Bay): group lo_res_y voxels in Y per bay
        lo_res_z=1,                    # Low-res (Bay): group lo_res_z voxels in Z per bay
        # V12 — Density threshold
        density_thresh_active=False,   # bool: randomly skip voxels to create empty space
        density_thresh=1.0,            # float 0–1: fraction of voxels that receive elements (1=all)
        # V13 — Circulation gap
        circulation_active=False,      # bool: erode clusters in X/Y to leave circulation gaps
        circ_rooms=6,                  # int: number of Voronoi clusters (rooms) to partition into
        circ_gap=1,                    # int: gap width in voxels (X/Y Manhattan radius)
        # V16 — Three additional element slots (A-F total).  Fallback chain:
        # D→C, E→D, F→E so the function still runs with only Element A loaded.
        src_geos_d=None,
        src_geos_e=None,
        src_geos_f=None):
    """
    Combinatorial discrete distribution.
    Three element types (A, B, C) are assigned per voxel by a rule, then
    oriented to face planes (span 1), bridge midpoints (span 2), or
    long-span chains (span ≥ 3).
    V7: Wall placement, Random placement, arbitrary span, invert_placement,
        Corner expression, Solar shield, Threshold, Z-gradient, Checkerboard,
        Attractor gradient.
    """
    import random as _random
    import time   as _time

    ensure_output_layer("Discrete")   # parent layer

    # ── Guard: require at least Element A ─────────────────────────────────────
    if not src_geos_a:
        return 0

    # ── Resolve element fallbacks (B-F optional — fall back chain) ───────────
    # This allows the function to run with only Element A loaded.
    # V16: A → B → C → D → E → F, each falls back to the prior resolved geom.
    src_b = src_geos_b if src_geos_b else src_geos_a
    src_c = src_geos_c if src_geos_c else src_b
    src_d = src_geos_d if src_geos_d else src_c
    src_e = src_geos_e if src_geos_e else src_d
    src_f = src_geos_f if src_geos_f else src_e

    # ── Per-element source reference frames ───────────────────────────────────
    def _src_refs(geos):
        bb  = _combined_bb(geos)
        dx  = max(bb.Max.X - bb.Min.X, 1e-6)
        dy  = max(bb.Max.Y - bb.Min.Y, 1e-6)
        dz  = max(bb.Max.Z - bb.Min.Z, 1e-6)

        if dz <= dx and dz <= dy:
            # Thinnest in Z (flat slab / cube) — depth = Z, face normal = world Z (legacy)
            depth  = dz
            size   = max(dx, dy)
            origin = rg.Point3d(bb.Center.X, bb.Center.Y, bb.Min.Z)
            plane  = rg.Plane(origin, rg.Vector3d.XAxis, rg.Vector3d.YAxis)
            # ZAxis = X × Y = (0,0,1) ✓
        elif dy <= dx:
            # Thinnest in Y — element face in XZ plane, depth = Y, face normal = world Y
            depth  = dy
            size   = max(dx, dz)
            origin = rg.Point3d(bb.Center.X, bb.Min.Y, bb.Center.Z)
            plane  = rg.Plane(origin,
                              rg.Vector3d(-1.0, 0.0, 0.0),
                              rg.Vector3d( 0.0, 0.0, 1.0))
            # ZAxis = (-1,0,0) × (0,0,1) = (0,1,0) = world Y ✓
        else:
            # Thinnest in X — element face in YZ plane, depth = X, face normal = world X
            depth  = dx
            size   = max(dy, dz)
            origin = rg.Point3d(bb.Min.X, bb.Center.Y, bb.Center.Z)
            plane  = rg.Plane(origin,
                              rg.Vector3d(0.0, 1.0, 0.0),
                              rg.Vector3d(0.0, 0.0, 1.0))
            # ZAxis = (0,1,0) × (0,0,1) = (1,0,0) = world X ✓
        return plane, depth, size

    src_refs = {
        "A": _src_refs(src_geos_a),
        "B": _src_refs(src_b),
        "C": _src_refs(src_c),
        "D": _src_refs(src_d),
        "E": _src_refs(src_e),
        "F": _src_refs(src_f),
    }

    # Per-label output layers — only create sub-layers for explicitly loaded elements.
    # Fallback labels route to the same layer as their source element.
    if _output_layer_override:
        _ov = ensure_output_layer(_output_layer_override)
        _lbl_layer = {"A": _ov, "B": _ov, "C": _ov, "D": _ov, "E": _ov, "F": _ov}
    else:
        layer_a = ensure_output_layer("Discrete_A")
        layer_b = ensure_output_layer("Discrete_B") if src_geos_b else layer_a
        layer_c = ensure_output_layer("Discrete_C") if src_geos_c else layer_b
        layer_d = ensure_output_layer("Discrete_D") if src_geos_d else layer_c
        layer_e = ensure_output_layer("Discrete_E") if src_geos_e else layer_d
        layer_f = ensure_output_layer("Discrete_F") if src_geos_f else layer_e
        _lbl_layer = {"A": layer_a, "B": layer_b, "C": layer_c,
                      "D": layer_d, "E": layer_e, "F": layer_f}

    # ── Voxel pool ────────────────────────────────────────────────────────────
    # When target_layers is None (climate mode passes a pre-filtered zone dict),
    # use all voxels in the dict directly.
    if target_layers is None:
        all_vox = list(voxels_dict.values())
    else:
        all_vox = _target_voxels(voxels_dict, target_layers)
    voxels  = _filter_by_place_at(all_vox, place_at, shell_depth=shell_depth,
                                   rand_seed=rand_seed,
                                   attractor_pt=attractor_pt,
                                   attr_radius=attr_radius,
                                   attr_min=attr_min, attr_max=attr_max)
    if invert_place_at:
        kept_set = {id(v) for v in voxels}
        voxels   = [v for v in all_vox if id(v) not in kept_set]

    # ── V12: Density threshold — randomly drop voxels to create empty space ────
    # density_thresh=1.0 → keep all voxels (full fill, no empty space).
    # density_thresh=0.7 → keep ~70% of voxels; 30% are randomly left empty.
    # density_thresh=0.0 → keep no voxels (all empty).
    # Seeded via (rand_seed + 99) so it is reproducible and independent of the
    # Random placement RNG (rand_seed + 0/1/2 used by those paths).
    if density_thresh_active and density_thresh < 1.0:
        import random as _rng_density_mod
        _rng_d = _rng_density_mod.Random(rand_seed + 99)
        voxels = [v for v in voxels if _rng_d.random() < max(0.0, density_thresh)]

    # ── V13: Circulation gap — erode clusters in X/Y to leave empty corridors ──
    # Partition the surviving voxels into N Voronoi clusters (rooms), then drop
    # voxels lying within `circ_gap` of a different cluster (X/Y only, not Z).
    _voxels_before_circ = voxels   # V15: keep full set for cluster-invert gap detection
    if circulation_active and circ_gap >= 1 and len(voxels) > 1:
        _circ_lk = _split_n_clusters(voxels, circ_rooms, cluster_seed)
        voxels   = _erode_circulation(voxels, _circ_lk, circ_gap)
        if not voxels:
            return 0   # gap consumed everything — nothing left to place

    # ── Low Resolution (Bay) mode: replace voxels with super-voxels ──────────
    # Build super-voxels AFTER place_at filter so bays only form from voxels
    # that passed the filter.  hi_res and lo_res are mutually exclusive (user
    # choice) — if lo_res is active we skip the hi_res grid loop later.
    _lo_res_active = (lo_res_x > 1 or lo_res_y > 1 or lo_res_z > 1)
    if _lo_res_active:
        voxels = _build_super_voxels(
            voxels, voxels_dict, lo_res_x, lo_res_y, lo_res_z)
        if not voxels:
            return 0   # no complete bays found

    # Effective hi_res: disabled when lo_res is active
    _hi_res = 1 if _lo_res_active else max(1, int(hi_res))

    # ── Field bounding box (used if constrain_to_field or Solar shield) ─────────
    # Solar shield always constrains — elements on face-normals can overshoot the
    # field boundary if not checked.
    _force_constrain = (placement == "Solar shield")
    _field_bb = None
    if (constrain_to_field or _force_constrain) and all_vox:
        _vox_size_ref = all_vox[0].size
        _margin_dist  = field_margin * _vox_size_ref
        xs = [v.center.X for v in all_vox]
        ys = [v.center.Y for v in all_vox]
        zs = [v.center.Z for v in all_vox]
        _hs = _vox_size_ref * 0.5
        _field_bb = rg.BoundingBox(
            min(xs) - _hs - _margin_dist, min(ys) - _hs - _margin_dist,
            min(zs) - _hs - _margin_dist,
            max(xs) + _hs + _margin_dist, max(ys) + _hs + _margin_dist,
            max(zs) + _hs + _margin_dist)

    # ── Field centroid (for directional orientation modes) ────────────────────
    if all_vox:
        _cx = sum(v.center.X for v in all_vox) / len(all_vox)
        _cy = sum(v.center.Y for v in all_vox) / len(all_vox)
        _cz = sum(v.center.Z for v in all_vox) / len(all_vox)
        _field_centroid = rg.Point3d(_cx, _cy, _cz)
        _max_hdist = max(
            math.sqrt((v.center.X - _cx)**2 + (v.center.Y - _cy)**2)
            for v in all_vox) or 1.0
        _kmin = min(v.grid_ijk[2] for v in all_vox)
        _kmax = max(v.grid_ijk[2] for v in all_vox)
        _krange = max(_kmax - _kmin, 1)
    else:
        _field_centroid = rg.Point3d.Origin
        _max_hdist = 1.0
        _kmin = _krange = 1

    # ── Build assignment lookup (get_type: vox → (src_geos, label)) ──────────
    # V16: 6 labels A-F. By Z-level → 6 bands. By adjacency → 6 categories
    # (most-exposed → A … fully interior → F). By cluster → 6-zone Voronoi.
    # Random mix → uniform over 6 labels.
    _ALL_GEOS  = [src_geos_a, src_b, src_c, src_d, src_e, src_f]
    _ALL_LBLS  = ["A", "B", "C", "D", "E", "F"]
    _PAIRS_AF  = list(zip(_ALL_GEOS, _ALL_LBLS))

    def _make_get_type():
        # V8/V16 sentinel — Sub-Placement mode: every voxel returns forced label's element.
        if assignment_rule == "__sub_fixed__" and forced_label in _ALL_LBLS:
            _geos_lk = dict(zip(_ALL_LBLS, _ALL_GEOS))
            _lbl     = forced_label
            _geos    = _geos_lk[_lbl]
            def gt(vox):
                return (_geos, _lbl)
            return gt
        if assignment_rule == "By Z-level":
            k_vals  = [v.grid_ijk[2] for v in all_vox]
            k_min   = min(k_vals) if k_vals else 0
            k_range = max(max(k_vals) - k_min, 1) if k_vals else 1
            def gt(vox):
                t = (vox.grid_ijk[2] - k_min) / k_range
                idx = min(5, int(t * 6))   # 6 equal Z bands
                return (_ALL_GEOS[idx], _ALL_LBLS[idx])
            return gt

        elif assignment_rule == "By adjacency":
            # 4 side-faces possible → 0..4 exposure. Map to 6 bins.
            # n=4 → A, 3 → B, 2 → C, 1 → D, 0 → E, (F reserved as fallback).
            _ADJ_MAP = {4: 0, 3: 1, 2: 2, 1: 3, 0: 4}
            def gt(vox):
                n = sum(1 for fd in SIDE_FACES
                        if vox.face_types.get(fd) == "exterior")
                idx = _ADJ_MAP.get(n, 5)
                return (_ALL_GEOS[idx], _ALL_LBLS[idx])
            return gt

        elif assignment_rule == "By cluster":
            groups = _split_6_clusters(all_vox, cluster_seed)
            lk = {}
            for (geos, lbl), grp in zip(_PAIRS_AF, groups):
                for v in grp:
                    lk[v.grid_ijk] = (geos, lbl)
            def gt(vox):
                return lk.get(vox.grid_ijk, (src_geos_a, "A"))
            return gt

        else:  # "Random mix"
            rng = _random.Random(rand_seed)
            lk  = {v.grid_ijk: rng.choice(_PAIRS_AF) for v in all_vox}
            def gt(vox):
                return lk.get(vox.grid_ijk, (src_geos_a, "A"))
            return gt

    get_type = _make_get_type()

    # ── Orientation helper ────────────────────────────────────────────────────
    def _apply_orient(tgt, vox_or_midpt, idx):
        """Apply orientation modifier in-place on tgt plane. Returns tgt."""
        if orientation == "Rotated sequence":
            tgt.Rotate(math.radians(90.0 * (idx % 4)), tgt.ZAxis)

        elif orientation == "Edge-aligned":
            tgt.Rotate(math.pi / 2.0, tgt.ZAxis)

        elif orientation in ("Centrifugal", "Shard outward", "Vortex"):
            # Resolve position
            if isinstance(vox_or_midpt, rg.Point3d):
                pt = vox_or_midpt
                k  = None
            else:
                pt = vox_or_midpt.center
                k  = vox_or_midpt.grid_ijk[2]

            fn = tgt.ZAxis  # face normal as baseline

            if orientation == "Centrifugal":
                # Lean radially away from field centroid (horizontal)
                lean = rg.Vector3d(pt.X - _field_centroid.X,
                                   pt.Y - _field_centroid.Y, 0)

            elif orientation == "Shard outward":
                # Radial outward + upward tilt scaled by height and distance
                hdist = math.sqrt((pt.X - _field_centroid.X)**2 +
                                  (pt.Y - _field_centroid.Y)**2)
                dist_t = hdist / _max_hdist
                ht = ((k - _kmin) / _krange) if k is not None else 0.5
                lean = rg.Vector3d(
                    pt.X - _field_centroid.X,
                    pt.Y - _field_centroid.Y,
                    (dist_t * 0.6 + ht * 0.8) * _max_hdist * 0.5,
                )

            else:  # "Vortex"
                # Tangential direction (90° CCW around Z) — swirling effect
                dx = pt.X - _field_centroid.X
                dy = pt.Y - _field_centroid.Y
                lean = rg.Vector3d(-dy, dx, 0)

            if lean.Length > 1e-6:
                lean.Unitize()
                # Blend face-normal with lean direction by orient_strength
                bx = fn.X * (1.0 - orient_strength) + lean.X * orient_strength
                by = fn.Y * (1.0 - orient_strength) + lean.Y * orient_strength
                bz = fn.Z * (1.0 - orient_strength) + lean.Z * orient_strength
                blended = rg.Vector3d(bx, by, bz)
                if blended.Length > 1e-6:
                    blended.Unitize()
                    # Rotate tgt plane from fn toward blended
                    rot_axis = rg.Vector3d.CrossProduct(fn, blended)
                    if rot_axis.Length > 1e-10:
                        rot_axis.Unitize()
                        dot = max(-1.0, min(1.0, fn.X*blended.X +
                                            fn.Y*blended.Y + fn.Z*blended.Z))
                        angle = math.acos(dot)
                        tgt.Rotate(angle, rot_axis)
        return tgt

    # ── Tracking ──────────────────────────────────────────────────────────────
    # V16 — 6 element buckets A-F
    guids_by_lbl = {"A": [], "B": [], "C": [], "D": [], "E": [], "F": []}
    face_idx = 0

    def _record(new_guids, lbl):
        bucket = guids_by_lbl.get(lbl)
        if bucket is None:
            guids_by_lbl["A"].extend(new_guids)
        else:
            bucket.extend(new_guids)

    def _orient_and_add(source_geos, lbl, tgt_plane, vox_size, span_n=1,
                        scale_xyz=None):
        """Orient, scale, add using per-label source reference frame.
        scale_xyz: optional (sx, sy, sz) tuple for non-uniform scaling
                   used by Low Resolution center-placement path.
        """
        sp, s_depth, s_size = src_refs[lbl]
        oriented = _orient_geos(source_geos, sp, tgt_plane)
        if scale_xyz is not None:
            # Non-uniform scale: lo-res bay-fill path always scales to bay volume,
            # independent of the "Scale to fit voxel size" checkbox.
            sx, sy, sz = scale_xyz
            if s_size > 1e-6 and s_depth > 1e-6:
                xf = rg.Transform.Scale(tgt_plane, sx, sy, sz)
                for g in oriented: g.Transform(xf)
        elif scale_to_fit:
            if span_n == 1:
                sf    = vox_size / s_size
                xform = rg.Transform.Scale(tgt_plane.Origin, sf)
                for g in oriented: g.Transform(xform)
            else:
                xf = rg.Transform.Scale(
                    tgt_plane,
                    vox_size / s_size,
                    vox_size / s_size,
                    span_n * vox_size / s_depth,
                )
                for g in oriented: g.Transform(xf)
        # Field constraint — check actual geometry bbox centre, not just placement origin.
        # tgt_plane.Origin is always on a voxel face (inside field), so we must
        # test where the geometry actually ends up after orient + scale.
        if _field_bb is not None and oriented:
            geo_min = rg.Point3d( 1e15,  1e15,  1e15)
            geo_max = rg.Point3d(-1e15, -1e15, -1e15)
            for g in oriented:
                bb = g.GetBoundingBox(True)
                if bb.IsValid:
                    geo_min.X = min(geo_min.X, bb.Min.X)
                    geo_min.Y = min(geo_min.Y, bb.Min.Y)
                    geo_min.Z = min(geo_min.Z, bb.Min.Z)
                    geo_max.X = max(geo_max.X, bb.Max.X)
                    geo_max.Y = max(geo_max.Y, bb.Max.Y)
                    geo_max.Z = max(geo_max.Z, bb.Max.Z)
            geo_centre = rg.Point3d(
                (geo_min.X + geo_max.X) * 0.5,
                (geo_min.Y + geo_max.Y) * 0.5,
                (geo_min.Z + geo_max.Z) * 0.5,
            )
            if not _field_bb.Contains(geo_centre):
                return []
        return _add_geos(oriented, _lbl_layer[lbl])

    # ── V7 pre-computation: solar vector + random face set ────────────────────
    # Solar shield: convert azimuth+altitude to a unit world vector
    _sun_vec = None
    if placement == "Solar shield":
        az_r  = math.radians(sun_az)
        alt_r = math.radians(sun_alt)
        _sun_vec = rg.Vector3d(
            math.sin(az_r) * math.cos(alt_r),
            math.cos(az_r) * math.cos(alt_r),
            math.sin(alt_r))

    # V8 — Cluster placement: pre-compute voxel→cluster_id lookup via Voronoi split
    _cluster_lk   = None
    _target_cid   = None
    _cluster_room = None   # V15: None|"wall"|"no_facade"|"only_facade"
    if placement == "Cluster":
        _grps = _split_6_clusters(voxels, cluster_seed)   # V16: 6-zone split
        _cluster_lk = {}
        for cid, grp in enumerate(_grps):
            for v in grp:
                _cluster_lk[v.grid_ijk] = cid
        _target_cid = {"A only": 0, "B only": 1, "C only": 2,
                       "D only": 3, "E only": 4, "F only": 5}.get(cluster_target, None)
        if   cluster_faces == "Wall cluster":               _cluster_room = "wall"
        elif cluster_faces == "Wall cluster - no facade":   _cluster_room = "no_facade"
        elif cluster_faces == "Wall cluster - only facade": _cluster_room = "only_facade"
        elif cluster_faces == "Floor cluster":              _cluster_room = "floor"
        elif cluster_faces == "Ceiling cluster":            _cluster_room = "ceiling"

    # V15 — Cluster invert: build the gap-voxel list from voxels removed by
    # circulation erosion.  _cluster_lk only covers surviving voxels, so the
    # gap voxels are exactly those in _voxels_before_circ but not in voxels.
    _gap_voxels = None
    if placement == "Cluster" and cluster_invert:
        _surviving_ijks = {v.grid_ijk for v in voxels}
        _gap_voxels = [v for v in _voxels_before_circ
                       if v.grid_ijk not in _surviving_ijks]
        # When no circulation gap exists, the gap zone is voxels NOT in the
        # target cluster — those are already in `voxels` and handled by the
        # am_in_tgt check inside _check_placement (no swap needed).
        if _gap_voxels:
            voxels = _gap_voxels   # iterate over gap voxels for inverted mode

    # Random placement: pre-compute which (ijk, face_dir) pairs are included
    _random_face_set = None
    if placement == "Random":
        import random as _rng_mod
        rng0 = _rng_mod.Random(rand_seed)
        _random_face_set = set()
        for _v in voxels:
            for _fd in ALL_FACES:
                _ft = _v.face_types.get(_fd, "exterior")
                if _ft != "interior" and rng0.random() < 0.5:
                    _random_face_set.add((_v.grid_ijk, _fd))

    # Helper: evaluate whether (vox, face_dir, ftype) passes the placement filter
    # Returns True = include this face. Used for span-1 and the invert logic.
    def _check_placement(face_dir, ftype, vox, _seen_joints):
        """Returns (include: bool, consumed_from_seen: bool)"""
        if placement == "Exterior faces":
            return ftype not in ("interior",), False
        if placement == "Wall":
            # V12 fix: vertical shared faces ONLY (side neighbours). Skip +Z/-Z so
            # vertically-stacked voxels do not create horizontal floor/ceiling walls.
            if face_dir not in SIDE_FACES: return False, False
            nb  = vox.neighbors.get(face_dir)
            if nb is None: return False, False
            key = tuple(sorted([vox.grid_ijk, nb.grid_ijk]))
            if key in _seen_joints: return False, True   # already placed
            _seen_joints.add(key)
            return True, True
        if placement == "Top edges":
            return face_dir == "+Z" and ftype in ("top", "exterior"), False
        if placement == "All exposed":
            return ftype != "interior", False
        if placement == "Ceiling":
            return face_dir == "+Z", False
        if placement == "Floor":
            return face_dir == "-Z", False
        if placement == "Facade sides":
            # V8: true exterior facades only (no program dividers).
            # Element is placed OUTSIDE the voxel via get_face_plane's outward ZAxis.
            return (face_dir in SIDE_FACES and ftype == "exterior"), False
        if placement == "Facade sides+dividers":
            # V7 legacy behaviour preserved: include inter-program divider faces.
            return (face_dir in SIDE_FACES
                    and ftype in ("exterior", "inter_program")), False
        if placement == "Corner expression":
            exposed = sum(1 for fd in SIDE_FACES
                          if vox.face_types.get(fd, "exterior") != "interior")
            if exposed < 3: return False, False
            return ftype != "interior", False
        if placement == "Solar shield":
            if _sun_vec is None: return False, False
            fn  = FACE_DIRS[face_dir]   # already rg.Vector3d
            dot = fn.X * _sun_vec.X + fn.Y * _sun_vec.Y + fn.Z * _sun_vec.Z
            return dot >= math.cos(math.radians(sun_thresh)), False
        if placement == "Threshold":
            nb = vox.neighbors.get(face_dir)
            if nb is None: return False, False
            vox_layer = getattr(vox, "layer_name", "")
            nb_layer  = getattr(nb,  "layer_name", "")
            if vox_layer == nb_layer: return False, False
            key = tuple(sorted([vox.grid_ijk, nb.grid_ijk]))
            if key in _seen_joints: return False, True
            _seen_joints.add(key)
            return True, True
        if placement == "Cluster":
            # V8/V15 Voronoi-cluster placement
            if _cluster_lk is None: return False, False
            my_cid = _cluster_lk.get(vox.grid_ijk)

            # Helper: is a cluster-id in the selected target?
            def _in_tgt(cid):
                if cid is None: return False
                return _target_cid is None or cid == _target_cid

            am_in_tgt = _in_tgt(my_cid)

            if cluster_invert:
                # ── INVERTED MODE ────────────────────────────────────────────
                # Work on the voxels the normal cluster SKIPPED (the gap zone).
                # Apply the same _cluster_room face logic relative to the gap:
                #   INTERIOR = gap voxel facing another gap voxel      → skip
                #   DIVIDER  = gap voxel facing a cluster voxel        → boundary
                #   FACADE   = gap voxel at field edge (no neighbour)  → outer
                # No dedup needed: cluster voxels return False at am_in_tgt.
                if am_in_tgt: return False, False
                if _cluster_room in ("wall", "no_facade", "only_facade"):
                    if face_dir not in SIDE_FACES: return False, False
                    nb = vox.neighbors.get(face_dir)
                    if nb is None:
                        if _cluster_room == "no_facade": return False, False
                        return True, False
                    if not _in_tgt(_cluster_lk.get(nb.grid_ijk)):
                        return False, False                         # gap→gap: INTERIOR
                    if _cluster_room == "only_facade": return False, False
                    return True, False                              # gap→cluster: DIVIDER
                elif _cluster_room in ("floor", "ceiling"):
                    _fd_tgt = "-Z" if _cluster_room == "floor" else "+Z"
                    if face_dir != _fd_tgt: return False, False
                    nb = vox.neighbors.get(face_dir)
                    if nb is None: return True, False               # FACADE (field edge)
                    if not _in_tgt(_cluster_lk.get(nb.grid_ijk)):
                        return False, False                         # gap→gap: INTERIOR
                    return True, False                              # gap→cluster: DIVIDER
                else:
                    # "All exposed" inverted
                    nb = vox.neighbors.get(face_dir)
                    if nb is not None and not _in_tgt(_cluster_lk.get(nb.grid_ijk)):
                        return False, False
                    return True, False

            # ── NORMAL MODE ──────────────────────────────────────────────────
            if not am_in_tgt: return False, False
            if _cluster_room in ("wall", "no_facade", "only_facade"):
                # Wall-cluster family — side faces only.
                if face_dir not in SIDE_FACES: return False, False
                nb = vox.neighbors.get(face_dir)
                if nb is None:
                    if _cluster_room == "no_facade": return False, False
                    return True, False                              # FACADE
                nb_cid = _cluster_lk.get(nb.grid_ijk)
                if nb_cid == my_cid: return False, False           # INTERIOR
                if _cluster_room == "only_facade": return False, False
                key = tuple(sorted([vox.grid_ijk, nb.grid_ijk]))   # DIVIDER
                if key in _seen_joints: return False, True
                _seen_joints.add(key)
                return True, True
            elif _cluster_room in ("floor", "ceiling"):
                # Floor / Ceiling cluster — single horizontal face per zone.
                #   FACADE   = field edge (no neighbour above/below)
                #   DIVIDER  = neighbour in different cluster zone (threshold)
                #   INTERIOR = neighbour in same cluster zone  → skip
                _fd_tgt = "-Z" if _cluster_room == "floor" else "+Z"
                if face_dir != _fd_tgt: return False, False
                nb = vox.neighbors.get(face_dir)
                if nb is None: return True, False                   # FACADE
                nb_cid = _cluster_lk.get(nb.grid_ijk)
                if nb_cid == my_cid: return False, False            # INTERIOR
                key = tuple(sorted([vox.grid_ijk, nb.grid_ijk]))    # DIVIDER
                if key in _seen_joints: return False, True
                _seen_joints.add(key)
                return True, True
            # "All exposed" — every face not interior to the same cluster zone
            nb = vox.neighbors.get(face_dir)
            if nb is not None and _cluster_lk.get(nb.grid_ijk) == my_cid:
                return False, False                                 # same zone → interior
            return True, False
        if placement == "Random":
            if _random_face_set is None: return True, False
            return (vox.grid_ijk, face_dir) in _random_face_set, False
        if placement == "Replace voxel":
            # One element placed per voxel at its centre — dedup handled in outer loop
            return True, False
        # Default: include everything
        return True, False

    # ── Span 1: face-based (regular + hi-res) and bay-center (lo-res) ───────────
    if span == 1:
        seen_joints  = set()
        placed_lo_res = set()   # tracks super-voxel keys already placed (lo-res only)

        for vox in voxels:
            src_geos, lbl = get_type(vox)
            for face_dir in ALL_FACES:
                ftype = vox.face_types.get(face_dir, "exterior")

                # Evaluate placement filter via helper
                include, _ = _check_placement(face_dir, ftype, vox, seen_joints)

                # Apply face-level invert (V7)
                if invert_placement:
                    include = not include

                if not include:
                    continue

                # ── LOW RESOLUTION + REPLACE VOXEL: bay-center volume fill ───────
                # "Replace voxel" in lo-res mode fills the entire bay volume with ONE
                # element, non-uniformly scaled to fit the bay bounding box exactly.
                # All other placements (Wall, Exterior, Facade, etc.) fall through to
                # the regular face-plane code below — get_face_plane() and
                # _get_vox_face_size() already handle SuperVoxels via face_half /
                # face_sizes, so no special case is needed for lo-res face placement.
                if _lo_res_active and placement == "Replace voxel":
                    if vox.grid_ijk not in placed_lo_res:
                        placed_lo_res.add(vox.grid_ijk)
                        sp, s_depth, s_size = src_refs[lbl]
                        sv_hx = vox.face_half.get("+X", vox.size / 2)
                        sv_hy = vox.face_half.get("+Y", vox.size / 2)
                        sv_hz = vox.face_half.get("+Z", vox.size / 2)
                        tgt_ctr = rg.Plane(
                            rg.Point3d(vox.center.X,
                                       vox.center.Y,
                                       vox.center.Z - sv_hz),
                            rg.Vector3d.XAxis, rg.Vector3d.YAxis)
                        new_g = _orient_and_add(
                            src_geos, lbl, tgt_ctr, vox.size, span_n=1,
                            scale_xyz=((2 * sv_hx) / s_size,
                                       (2 * sv_hy) / s_size,
                                       (2 * sv_hz) / s_depth))
                        _record(new_g, lbl)
                    continue

                # ── REPLACE VOXEL path ────────────────────────────────────────
                # One element per voxel, centred inside the voxel volume.
                # Origin at voxel bottom-centre so _src_refs base maps to vox bottom.
                # scale_to_fit ON → element stretched to fill voxel cube exactly.
                if placement == "Replace voxel":
                    if vox.grid_ijk not in placed_lo_res:
                        placed_lo_res.add(vox.grid_ijk)
                        sp, s_depth, s_size = src_refs[lbl]
                        half = vox.size / 2.0
                        tgt_ctr = rg.Plane(
                            rg.Point3d(vox.center.X,
                                       vox.center.Y,
                                       vox.center.Z - half),
                            rg.Vector3d.XAxis, rg.Vector3d.YAxis)
                        if scale_to_fit:
                            new_g = _orient_and_add(
                                src_geos, lbl, tgt_ctr, vox.size, span_n=1,
                                scale_xyz=(vox.size / s_size,
                                           vox.size / s_size,
                                           vox.size / s_depth))
                        else:
                            new_g = _orient_and_add(
                                src_geos, lbl, tgt_ctr, vox.size, span_n=1)
                        _record(new_g, lbl)
                    continue

                # ── REGULAR + HI-RES path ──────────────────────────────────────
                # Cluster (wall/side faces): flip inward so elements face INTO the room.
                # Floor cluster (-Z) and Ceiling cluster (+Z): face upward/downward
                # into the zone naturally — no flip needed.
                _is_floor_ceil_cluster = (
                    placement == "Cluster" and
                    _cluster_room in ("floor", "ceiling"))
                flip_inward = (placement == "Ceiling" and face_dir == "+Z") or \
                              (placement == "Floor"   and face_dir == "-Z") or \
                              (placement == "Cluster" and not _is_floor_ceil_cluster)
                # When inverted: Ceiling inverted = Floor inward on -Z, etc.
                if invert_placement:
                    flip_inward = (placement == "Floor"   and face_dir == "+Z") or \
                                  (placement == "Ceiling" and face_dir == "-Z")

                tgt = get_face_plane(vox, face_dir)

                # Wall: the element must be CENTRED on the shared interface.
                # get_face_plane puts origin at the interface surface, so the element
                # base is at the interface and extends fully into the neighbour voxel.
                # Fix: shift the origin backward by exactly half the scaled element
                # depth, so the element is symmetric about the interface.
                #
                #   scaled_depth = s_depth * (vox_size / s_size)  [scale_to_fit ON]
                #   scaled_depth = s_depth                         [scale_to_fit OFF]
                #   half_depth   = scaled_depth / 2
                #
                # After shift: element bottom = interface - half_depth (inside vox)
                #              element top    = interface + half_depth (inside neighbour)
                #              element CENTRE = shared interface  ✓
                if placement == "Wall":
                    sp, s_depth, s_size = src_refs[lbl]
                    _face_sz_wall = _get_vox_face_size(vox, face_dir)
                    if scale_to_fit:
                        half_depth = s_depth * _face_sz_wall / s_size * 0.5
                    else:
                        half_depth = s_depth * 0.5
                    norm = FACE_DIRS[face_dir]
                    orig = tgt.Origin
                    tgt  = rg.Plane(
                        rg.Point3d(orig.X - norm.X * half_depth,
                                   orig.Y - norm.Y * half_depth,
                                   orig.Z - norm.Z * half_depth),
                        tgt.XAxis, tgt.YAxis)

                if flip_inward:
                    tgt.Rotate(math.pi, tgt.XAxis)

                # place_inside: flip ZAxis inward so element projects into the voxel
                # rather than outward from the face surface.
                if place_inside:
                    tgt.Rotate(math.pi, tgt.XAxis)

                # Face characteristic size (SuperVoxel uses face-specific value)
                face_sz = _get_vox_face_size(vox, face_dir)

                if _lo_res_active:
                    # ── LOW RESOLUTION: tile across the bay boundary face ────────
                    # A bay face spans several voxel faces (e.g. 2×2×2 → 2×2 cells).
                    # Place ONE element per voxel cell so the whole bay boundary is
                    # covered, instead of a single element at the bay centroid.
                    # Each cell keeps the element's native size (or scales to ONE
                    # voxel when "Scale to fit voxel size" is checked).
                    _vs = vox.size
                    _gx = max(1, int(round(2 * vox.face_half.get("+X", _vs / 2.0) / _vs)))
                    _gy = max(1, int(round(2 * vox.face_half.get("+Y", _vs / 2.0) / _vs)))
                    _gz = max(1, int(round(2 * vox.face_half.get("+Z", _vs / 2.0) / _vs)))
                    if face_dir in ("+X", "-X"):
                        _n_u, _n_v = _gy, _gz
                    elif face_dir in ("+Y", "-Y"):
                        _n_u, _n_v = _gx, _gz
                    else:                       # +Z / -Z
                        _n_u, _n_v = _gx, _gy
                    for _r in range(_n_v):
                        for _c in range(_n_u):
                            _ou = (_c - (_n_u - 1) / 2.0) * _vs
                            _ov = (_r - (_n_v - 1) / 2.0) * _vs
                            _sub_orig = rg.Point3d(
                                tgt.Origin.X + tgt.XAxis.X * _ou + tgt.YAxis.X * _ov,
                                tgt.Origin.Y + tgt.XAxis.Y * _ou + tgt.YAxis.Y * _ov,
                                tgt.Origin.Z + tgt.XAxis.Z * _ou + tgt.YAxis.Z * _ov)
                            _sub_tgt = rg.Plane(_sub_orig, tgt.XAxis, tgt.YAxis)
                            _sub_tgt = _apply_orient(_sub_tgt, vox, face_idx)
                            face_idx += 1
                            new_g = _orient_and_add(
                                src_geos, lbl, _sub_tgt, _vs, span_n=1)
                            _record(new_g, lbl)
                elif _hi_res <= 1:
                    # ── Normal path: 1 element per face ──────────────────────
                    # The element keeps its native input size; scaling happens
                    # only when "Scale to fit voxel size" is checked (handled
                    # inside _orient_and_add).
                    tgt = _apply_orient(tgt, vox, face_idx)
                    face_idx += 1
                    new_g = _orient_and_add(src_geos, lbl, tgt, face_sz, span_n=1)
                    _record(new_g, lbl)
                else:
                    # ── High Resolution: subdivide face into _hi_res × _hi_res cells.
                    # Each cell is placed ON the face surface, projecting INWARD so
                    # geometry stays within field bounds.
                    #
                    # Key: the inward ZAxis is baked into sub_tgt BEFORE _apply_orient.
                    # Plane(origin, XAxis, -YAxis) → ZAxis = XAxis × (-YAxis) = -tgt.ZAxis ✓
                    # This ensures _apply_orient rotates around the inward normal
                    # consistently for all cells (no per-cell axis inconsistency).
                    #
                    # Sub-cell positions use the original outward tgt.XAxis/tgt.YAxis
                    # so the N×N grid is laid out correctly on the face regardless of flip.
                    cell_sz = face_sz / _hi_res
                    n = _hi_res
                    # Pre-compute negated YAxis once for the inward plane
                    _neg_y = rg.Vector3d(-tgt.YAxis.X, -tgt.YAxis.Y, -tgt.YAxis.Z)
                    for row in range(n):
                        for col in range(n):
                            # Sub-cell centre offset from face centre (in original face XY)
                            ox = (col - (n - 1) / 2.0) * cell_sz
                            oy = (row - (n - 1) / 2.0) * cell_sz
                            sub_orig = rg.Point3d(
                                tgt.Origin.X + tgt.XAxis.X*ox + tgt.YAxis.X*oy,
                                tgt.Origin.Y + tgt.XAxis.Y*ox + tgt.YAxis.Y*oy,
                                tgt.Origin.Z + tgt.XAxis.Z*ox + tgt.YAxis.Z*oy,
                            )
                            # Build sub_tgt: inward ZAxis unless place_inside already flipped
                            if not place_inside:
                                sub_tgt = rg.Plane(sub_orig, tgt.XAxis, _neg_y)
                            else:
                                sub_tgt = rg.Plane(sub_orig, tgt.XAxis, tgt.YAxis)
                            sub_tgt = _apply_orient(sub_tgt, vox, face_idx)
                            face_idx += 1
                            new_g = _orient_and_add(
                                src_geos, lbl, sub_tgt, cell_sz, span_n=1)
                            _record(new_g, lbl)

    # ── Span 2: bridge between adjacent voxel pairs ───────────────────────────
    elif span == 2:
        import random as _rng_mod2
        seen_bridge = set()
        _rng_span2 = _rng_mod2.Random(rand_seed + 1) if placement == "Random" else None
        for vox in voxels:
            src_geos, lbl = get_type(vox)
            for face_dir in ALL_FACES:
                nb = vox.neighbors.get(face_dir)
                if nb is None: continue
                key = tuple(sorted([vox.grid_ijk, nb.grid_ijk]))
                if key in seen_bridge: continue

                # Random filter for span-2
                if placement == "Random":
                    include = (_rng_span2.random() < 0.5)
                    if invert_placement: include = not include
                    if not include:
                        seen_bridge.add(key)
                        continue
                elif invert_placement:
                    # For span-2 invert: skip pairs where BOTH faces would be excluded
                    # (simple: 50% random flip when inverted for non-Random modes)
                    pass  # invert is meaningful for span-1; for span-2 just place all

                seen_bridge.add(key)

                tgt = _build_bridge_plane(vox, nb, face_dir)
                mid = rg.Point3d((vox.center.X+nb.center.X)*0.5,
                                 (vox.center.Y+nb.center.Y)*0.5,
                                 (vox.center.Z+nb.center.Z)*0.5)
                tgt = _apply_orient(tgt, mid, face_idx)
                face_idx += 1

                new_g = _orient_and_add(src_geos, lbl, tgt, vox.size, span_n=2)
                _record(new_g, lbl)

    # ── Span ≥ 3: collinear chains of N voxels ────────────────────────────────
    elif span >= 3:
        chains = _find_chains_n(span, voxels, voxels_dict)
        if not chains:
            print(">>> Discrete: No {}-voxel chains found — try 'All voxels' in Place at.".format(span))

        # Random filter for span-N chains
        if placement == "Random":
            import random as _rng_mod3
            rng3 = _rng_mod3.Random(rand_seed + 2)
            if invert_placement:
                chains = [c for c in chains if rng3.random() >= 0.5]
            else:
                chains = [c for c in chains if rng3.random() < 0.5]

        for chain_voxels in chains:
            mid_vox  = chain_voxels[len(chain_voxels) // 2]
            vox_a    = chain_voxels[0]
            vox_end  = chain_voxels[-1]
            # Determine direction from first to last
            di = vox_end.grid_ijk[0] - vox_a.grid_ijk[0]
            dj = vox_end.grid_ijk[1] - vox_a.grid_ijk[1]
            dk = vox_end.grid_ijk[2] - vox_a.grid_ijk[2]
            # Normalise to face direction string
            if di != 0: fd = "+X" if di > 0 else "-X"
            elif dj != 0: fd = "+Y" if dj > 0 else "-Y"
            else: fd = "+Z" if dk > 0 else "-Z"

            src_geos, lbl = get_type(mid_vox)
            tgt = _build_bridge_plane(vox_a, vox_end, fd)
            tgt = _apply_orient(tgt, mid_vox, face_idx)
            face_idx += 1

            new_g = _orient_and_add(src_geos, lbl, tgt, mid_vox.size, span_n=span)
            _record(new_g, lbl)

    # ── Group output ──────────────────────────────────────────────────────────
    # V16 — group all 6 element buckets separately + combined
    ts    = int(_time.time())
    all_g = []
    for _lbl in ("A", "B", "C", "D", "E", "F"):
        all_g.extend(guids_by_lbl[_lbl])
    _group_objects(all_g, "VOXELGEN_Discrete_{}".format(ts))
    for _lbl in ("A", "B", "C", "D", "E", "F"):
        if guids_by_lbl[_lbl]:
            _group_objects(guids_by_lbl[_lbl],
                           "VOXELGEN_Discrete_{}_{}".format(_lbl, ts))
    if interlocking and all_g:
        jc = _apply_interlocking_joints(all_g)
        print(">>> Interlocking joints cut: {}".format(jc))
    return len(all_g)


# ==============================================================================
#  STRUCTURE MODE  —  Columns, Beams, X-Brace, Flat Slab, Full Frame
# ==============================================================================

def _diagonal_box(pt_a, pt_b, ps):
    """Thin rectangular box (ps × ps cross-section) from pt_a to pt_b."""
    d = rg.Vector3d(pt_b.X - pt_a.X, pt_b.Y - pt_a.Y, pt_b.Z - pt_a.Z)
    length = d.Length
    if length < 1e-6:
        return None
    d.Unitize()
    ref = rg.Vector3d.ZAxis if abs(d.Z) < 0.99 else rg.Vector3d.XAxis
    perp  = rg.Vector3d.CrossProduct(d, ref);  perp.Unitize()
    perp2 = rg.Vector3d.CrossProduct(d, perp); perp2.Unitize()
    origin = rg.Point3d(
        pt_a.X - perp.X * ps * 0.5 - perp2.X * ps * 0.5,
        pt_a.Y - perp.Y * ps * 0.5 - perp2.Y * ps * 0.5,
        pt_a.Z - perp.Z * ps * 0.5 - perp2.Z * ps * 0.5,
    )
    box = rg.Box(
        rg.Plane(origin, perp, perp2),
        rg.Interval(0, ps),
        rg.Interval(0, ps),
        rg.Interval(0, length),
    )
    return box.ToBrep() if box.IsValid else None


def _face_corners(vox, face_dir):
    """Return 4 corners of a voxel face, ordered CCW from outside."""
    fp   = get_face_plane(vox, face_dir)
    half = vox.size / 2.0
    xa, ya = fp.XAxis * half, fp.YAxis * half
    return [
        rg.Point3d(fp.Origin.X - xa.X - ya.X, fp.Origin.Y - xa.Y - ya.Y, fp.Origin.Z - xa.Z - ya.Z),
        rg.Point3d(fp.Origin.X + xa.X - ya.X, fp.Origin.Y + xa.Y - ya.Y, fp.Origin.Z + xa.Z - ya.Z),
        rg.Point3d(fp.Origin.X + xa.X + ya.X, fp.Origin.Y + xa.Y + ya.Y, fp.Origin.Z + xa.Z + ya.Z),
        rg.Point3d(fp.Origin.X - xa.X + ya.X, fp.Origin.Y - xa.Y + ya.Y, fp.Origin.Z - xa.Z + ya.Z),
    ]


def apply_structure_mode(voxels_dict, target_layers,
                         struct_mode, profile_pct, place_at, voxel_size=1.0):
    """
    struct_mode : "Column" | "Beam" | "Both" | "X-Brace" | "Flat Slab" | "Full Frame"
    profile_pct : 1-25  — profile thickness as % of voxel size
    place_at    : "All voxels" | "Boundary only" | "Perimeter" |
                  "Grid 2×2" | "Grid 3×3" | "Vertical stacks"
    """
    layer_name = ensure_output_layer("Structure")
    voxels_all = _target_voxels(voxels_dict, target_layers)

    # ── Place-at filtering ────────────────────────────────────────────────────
    if place_at == "Boundary only":
        voxels = [v for v in voxels_all
                  if any(ft in ("exterior", "inter_program", "top", "bottom")
                         for ft in v.face_types.values())]

    elif place_at == "Perimeter":
        # Voxels that have at least one exterior SIDE face (not top/bottom)
        voxels = [v for v in voxels_all
                  if any(v.face_types.get(fd) == "exterior"
                         for fd in SIDE_FACES)]

    elif place_at == "Grid 2×2":
        voxels = [v for v in voxels_all
                  if (v.grid_ijk[0] % 2 == 0) and (v.grid_ijk[1] % 2 == 0)]

    elif place_at == "Grid 3×3":
        voxels = [v for v in voxels_all
                  if (v.grid_ijk[0] % 3 == 0) and (v.grid_ijk[1] % 3 == 0)]

    elif place_at == "Vertical stacks":
        # Only (i,j) columns that have 2+ voxels stacked
        from collections import Counter
        ij_count = Counter((v.grid_ijk[0], v.grid_ijk[1]) for v in voxels_all)
        voxels = [v for v in voxels_all
                  if ij_count[(v.grid_ijk[0], v.grid_ijk[1])] >= 2]

    else:  # "All voxels"
        voxels = voxels_all

    # ── Profile size (% of voxel size) ───────────────────────────────────────
    v_size = voxel_size if voxel_size > 1e-6 else 1.0
    ps = max(0.01, (profile_pct / 100.0) * v_size)

    placed_corners = set()
    placed_edges   = set()
    placed_slabs   = set()
    placed_braces  = set()
    count          = 0
    all_guids      = []

    for vox in voxels:
        half = vox.size / 2.0
        c    = vox.center

        # ── Column ───────────────────────────────────────────────────────────
        if struct_mode in ("Column", "Both", "Full Frame"):
            for cx, cy in [(c.X - half, c.Y - half),
                           (c.X + half, c.Y - half),
                           (c.X + half, c.Y + half),
                           (c.X - half, c.Y + half)]:
                key = (round(cx, 2), round(cy, 2), round(c.Z - half, 2))
                if key in placed_corners:
                    continue
                placed_corners.add(key)
                origin = rg.Point3d(cx - ps * 0.5, cy - ps * 0.5, c.Z - half)
                box = rg.Box(
                    rg.Plane(origin, rg.Vector3d.XAxis, rg.Vector3d.YAxis),
                    rg.Interval(0, ps), rg.Interval(0, ps), rg.Interval(0, vox.size),
                )
                if box.IsValid:
                    g = _add_brep(box.ToBrep(), layer_name)
                    if g: all_guids.append(g)
                    count += 1

        # ── Beam ─────────────────────────────────────────────────────────────
        if struct_mode in ("Beam", "Both", "Full Frame"):
            top_z = c.Z + half
            for (ex, ey, ez, edir) in [
                (c.X - half, c.Y - half, top_z, "+X"),
                (c.X - half, c.Y + half, top_z, "+X"),
                (c.X - half, c.Y - half, top_z, "+Y"),
                (c.X + half, c.Y - half, top_z, "+Y"),
            ]:
                key = (round(ex, 2), round(ey, 2), round(ez, 2), edir)
                if key in placed_edges:
                    continue
                placed_edges.add(key)
                if edir == "+X":
                    origin = rg.Point3d(ex, ey - ps * 0.5, ez - ps)
                    box = rg.Box(
                        rg.Plane(origin, rg.Vector3d.XAxis, rg.Vector3d.YAxis),
                        rg.Interval(0, vox.size), rg.Interval(0, ps), rg.Interval(0, ps),
                    )
                else:
                    origin = rg.Point3d(ex - ps * 0.5, ey, ez - ps)
                    box = rg.Box(
                        rg.Plane(origin, rg.Vector3d.XAxis, rg.Vector3d.YAxis),
                        rg.Interval(0, ps), rg.Interval(0, vox.size), rg.Interval(0, ps),
                    )
                if box.IsValid:
                    g = _add_brep(box.ToBrep(), layer_name)
                    if g: all_guids.append(g)
                    count += 1

        # ── X-Brace ──────────────────────────────────────────────────────────
        # Diagonal cross on each exterior or inter-program SIDE face
        if struct_mode in ("X-Brace", "Full Frame"):
            for face_dir in SIDE_FACES:
                ftype = vox.face_types.get(face_dir, "exterior")
                if ftype not in ("exterior", "inter_program"):
                    continue
                key = (vox.grid_ijk, face_dir)
                if key in placed_braces:
                    continue
                placed_braces.add(key)
                # Also mark the neighbour's opposite face to avoid double-brace
                nb = vox.neighbors.get(face_dir)
                if nb:
                    opp = {"+X": "-X", "-X": "+X", "+Y": "-Y", "-Y": "+Y"}[face_dir]
                    placed_braces.add((nb.grid_ijk, opp))
                corners = _face_corners(vox, face_dir)
                # Two diagonals: 0↔2 and 1↔3
                for (a, b) in [(corners[0], corners[2]), (corners[1], corners[3])]:
                    br = _diagonal_box(a, b, ps)
                    if br:
                        g = _add_brep(br, layer_name)
                        if g: all_guids.append(g)
                        count += 1

        # ── Flat Slab ────────────────────────────────────────────────────────
        # Thin horizontal plate at the bottom of each voxel
        if struct_mode in ("Flat Slab", "Full Frame"):
            key = (round(c.X, 2), round(c.Y, 2), round(c.Z - half, 2))
            if key not in placed_slabs:
                placed_slabs.add(key)
                slab_t = max(ps * 0.5, ps)   # slab thickness = profile size
                origin = rg.Point3d(c.X - half, c.Y - half, c.Z - half)
                box = rg.Box(
                    rg.Plane(origin, rg.Vector3d.XAxis, rg.Vector3d.YAxis),
                    rg.Interval(0, vox.size),
                    rg.Interval(0, vox.size),
                    rg.Interval(0, slab_t),
                )
                if box.IsValid:
                    g = _add_brep(box.ToBrep(), layer_name)
                    if g: all_guids.append(g)
                    count += 1

    import time as _time
    _group_objects(all_guids, "VOXELGEN_Structure_{}".format(int(_time.time())))
    return count


# ==============================================================================
#  ORNAMENT MODE  —  Attractor-Based Transformation
# ==============================================================================

def _dist_to_attractor(attractor_geos, test_pt):
    """
    Minimum distance from test_pt to ANY geometry in attractor_geos.
    Supports: Point, Curve, Brep, Mesh, SubD — any Rhino geometry type.
    Returns float distance.
    """
    min_dist = float("inf")
    for geo in attractor_geos:
        try:
            if isinstance(geo, rg.Point):
                d = test_pt.DistanceTo(geo.Location)
            elif isinstance(geo, rg.Curve):
                ok, t = geo.ClosestPoint(test_pt)
                d = test_pt.DistanceTo(geo.PointAt(t)) if ok else float("inf")
            elif isinstance(geo, rg.Brep):
                cp = geo.ClosestPoint(test_pt)
                d = test_pt.DistanceTo(cp)
            elif isinstance(geo, rg.Mesh):
                cp = geo.ClosestPoint(test_pt)
                d = test_pt.DistanceTo(cp)
            elif isinstance(geo, rg.SubD):
                b = geo.ToBrep(rg.SubDToBrepOptions())
                d = test_pt.DistanceTo(b.ClosestPoint(test_pt)) if b else float("inf")
            else:
                # Fallback: use bounding box centre
                bb = geo.GetBoundingBox(True)
                d = test_pt.DistanceTo(bb.Center) if bb.IsValid else float("inf")
            if d < min_dist:
                min_dist = d
        except Exception:
            pass
    return min_dist if min_dist < float("inf") else 0.0


def apply_structure_mode_custom(voxels_dict, target_layers,
                                col_geos, beam_geos,
                                spacing_x, spacing_y, spacing_z=1,
                                struct_mode="Both", profile_pct=8,
                                place_at="All voxels", voxel_size=1.0,
                                col_geos_b=None):
    """
    Structural placement with custom column/beam elements and 3D grid spacing.

    spacing_x / spacing_y / spacing_z : column grid interval in each axis.
      - Columns placed at VOXEL CORNERS (not centres): (i%sx==0, j%sy==0, k%sz==0)
        corner = (vox.center − half_voxel) in XY; spans sz floors tall.
      - Beams run at column top, spanning the CORNER-to-CORNER distance.
      - A beam is only placed when both endpoint column grid nodes exist in field.

    col_geos   : custom column element (optional, procedural box fallback).
    col_geos_b : second column element — alternates A/B per column position.
    beam_geos  : custom beam element  (optional, procedural box fallback).
    """
    import random as _rnd

    layer_name = ensure_output_layer("Structure")
    voxels_all = _target_voxels(voxels_dict, target_layers)
    if not voxels_all:
        return 0

    # ── Place-at filtering (reuse same logic as apply_structure_mode) ─────────
    if place_at == "Boundary only":
        voxels = [v for v in voxels_all
                  if any(ft in ("exterior", "inter_program", "top", "bottom")
                         for ft in v.face_types.values())]
    elif place_at == "Perimeter":
        voxels = [v for v in voxels_all
                  if any(v.face_types.get(fd) == "exterior" for fd in SIDE_FACES)]
    elif place_at == u"Grid 2\u00d72":
        voxels = [v for v in voxels_all
                  if (v.grid_ijk[0] % 2 == 0) and (v.grid_ijk[1] % 2 == 0)]
    elif place_at == u"Grid 3\u00d73":
        voxels = [v for v in voxels_all
                  if (v.grid_ijk[0] % 3 == 0) and (v.grid_ijk[1] % 3 == 0)]
    else:
        voxels = voxels_all

    v_size  = voxel_size if voxel_size > 1e-6 else 1.0
    ps      = max(0.01, (profile_pct / 100.0) * v_size)
    sx, sy, sz = max(1, spacing_x), max(1, spacing_y), max(1, spacing_z)

    count = 0
    placed_col  = set()
    placed_beam = set()
    all_guids   = []

    def _place_custom(geos, src_plane, src_size, src_depth, target_pt,
                      scale_xy, scale_z, axis=None):
        """Orient geometry from src_plane to target_pt (Z-up by default, or axis)."""
        if axis is None:
            tgt_plane = rg.Plane(target_pt, rg.Vector3d.ZAxis)
        else:
            perp = rg.Vector3d.CrossProduct(axis, rg.Vector3d.ZAxis)
            if perp.IsZero:
                perp = rg.Vector3d.XAxis
            perp.Unitize()
            tgt_plane = rg.Plane(target_pt, perp, axis)

        oriented = _orient_geos(geos, src_plane, tgt_plane)
        # Scale: uniform XY to column/beam width; Z to height or span
        xf = rg.Transform.Scale(
            tgt_plane,
            scale_xy / max(src_size, 1e-6),
            scale_xy / max(src_size, 1e-6),
            scale_z  / max(src_depth, 1e-6),
        )
        for g in oriented:
            g.Transform(xf)
        return oriented

    def _src_frame(geos):
        """Return (src_plane, src_size, src_depth) from element bounding box."""
        bb      = _combined_bb(geos)
        origin  = rg.Point3d(bb.Center.X, bb.Center.Y, bb.Center.Z)
        plane   = rg.Plane(origin, rg.Vector3d.ZAxis)
        size_xy = max(bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, 1e-6)
        depth_z = max(bb.Max.Z - bb.Min.Z, 1e-6)
        return plane, size_xy, depth_z

    def _add_proc_box(origin_pt, dx, dy, dz):
        """Add a procedural box with given dimensions at origin_pt."""
        box = rg.Box(
            rg.Plane(origin_pt, rg.Vector3d.XAxis, rg.Vector3d.YAxis),
            rg.Interval(0, dx), rg.Interval(0, dy), rg.Interval(0, dz),
        )
        if box.IsValid:
            g = _add_brep(box.ToBrep(), layer_name)
            if g:
                all_guids.append(g)
                return 1
        return 0

    # ── Voxel lookup for beam endpoint validation ─────────────────────────────
    # Build a set of (i,j,k) that exist in the full field
    # Also build a dict of (i,j,k) → voxel world-centre for corner calculation
    ijk_to_center = {v.grid_ijk: v.center for v in voxels_all}

    # Pre-compute col-grid voxels: at 3D grid intersections (i%sx==0, j%sy==0, k%sz==0)
    col_voxels = [v for v in voxels
                  if (v.grid_ijk[0] % sx == 0)
                  and (v.grid_ijk[1] % sy == 0)
                  and (v.grid_ijk[2] % sz == 0)]

    half       = v_size * 0.5
    col_height = sz * v_size   # column spans sz voxel floors

    # All 4 corner offsets of a voxel (dx, dy) relative to its centre
    CORNER_OFFSETS = [(-half, -half), (+half, -half),
                      (+half, +half), (-half, +half)]

    # ── Columns ───────────────────────────────────────────────────────────────
    # Columns sit at ALL 4 corners of each col_voxel.
    # Shared corners between adjacent col_voxels are deduplicated by world pos.
    # Column body  → VOXELGEN_Structure
    # Column joint → VOXELGEN_Structure_Joint  (same position, separate material)
    joint_layer = ensure_output_layer("Structure_Joint")

    if struct_mode in ("Column", "Both"):
        if col_geos:
            sp, ss, src_dz = _src_frame(col_geos)
        if col_geos_b:
            sp_b, ss_b, src_dz_b = _src_frame(col_geos_b)

        for vox in col_voxels:
            cz_bot = vox.center.Z - half          # bottom of column level
            cz_mid = cz_bot + col_height * 0.5   # midpoint for element origin

            for (dx, dy) in CORNER_OFFSETS:
                cx = vox.center.X + dx
                cy = vox.center.Y + dy
                col_key = (round(cx, 4), round(cy, 4), round(cz_bot, 4))
                if col_key in placed_col:
                    continue                      # already placed by adjacent voxel
                placed_col.add(col_key)

                target_pt = rg.Point3d(cx, cy, cz_mid)

                # Column body (Geometry 1) → Structure layer
                if col_geos:
                    oriented = _place_custom(col_geos, sp, ss, src_dz,
                                             target_pt, ps, col_height)
                    for g in oriented:
                        guids = _add_geos([g], layer_name)
                        all_guids.extend(guids)
                        count += len(guids)
                else:
                    # Procedural box centred on corner
                    count += _add_proc_box(
                        rg.Point3d(cx - ps * 0.5, cy - ps * 0.5, cz_bot),
                        ps, ps, col_height)

                # Column joint (Geometry 2) → Structure_Joint layer
                if col_geos_b:
                    oriented_j = _place_custom(col_geos_b, sp_b, ss_b, src_dz_b,
                                               target_pt, ps, col_height)
                    for g in oriented_j:
                        guids = _add_geos([g], joint_layer)
                        all_guids.extend(guids)
                        count += len(guids)

    # ── Beams ─────────────────────────────────────────────────────────────────
    # Beams span at column-top level between the FACING corners of adjacent bays.
    # In +X: from (+X,±Y corners of bay ci) to (-X,±Y corners of bay ci+sx)
    # In +Y: from (±X,+Y corners of bay cj) to (±X,-Y corners of bay cj+sy)
    # This creates 2 parallel beams per bay in each direction.
    if struct_mode in ("Beam", "Both"):
        if beam_geos:
            bp, bs, bd_z = _src_frame(beam_geos)

        for vox in col_voxels:
            ci, cj, ck = vox.grid_ijk
            beam_z = vox.center.Z - half + col_height  # beam sits at column top

            # ── Beams in +X ──────────────────────────────────────────────────
            nb_x_ijk = (ci + sx, cj, ck)
            if nb_x_ijk in ijk_to_center:
                nb_cx  = ijk_to_center[nb_x_ijk].X
                x_from = vox.center.X + half   # +X edge of this bay
                x_to   = nb_cx - half          # −X edge of next bay
                span_x = x_to - x_from
                if span_x > 1e-6:
                    for cy_off in (-half, +half):   # one beam per Y-edge of bay
                        cy_b  = vox.center.Y + cy_off
                        bkey  = (round(x_from, 4), round(cy_b, 4),
                                 round(beam_z, 4), "+X")
                        if bkey in placed_beam:
                            continue
                        placed_beam.add(bkey)
                        mid_pt = rg.Point3d(x_from + span_x * 0.5,
                                            cy_b, beam_z - ps * 0.5)
                        if beam_geos:
                            oriented = _place_custom(beam_geos, bp, bs, bd_z,
                                                     mid_pt, ps, span_x,
                                                     axis=rg.Vector3d.XAxis)
                            for g in oriented:
                                guids = _add_geos([g], layer_name)
                                all_guids.extend(guids)
                                count += len(guids)
                        else:
                            count += _add_proc_box(
                                rg.Point3d(x_from, cy_b - ps * 0.5, beam_z - ps),
                                span_x, ps, ps)

            # ── Beams in +Y ──────────────────────────────────────────────────
            nb_y_ijk = (ci, cj + sy, ck)
            if nb_y_ijk in ijk_to_center:
                nb_cy  = ijk_to_center[nb_y_ijk].Y
                y_from = vox.center.Y + half
                y_to   = nb_cy - half
                span_y = y_to - y_from
                if span_y > 1e-6:
                    for cx_off in (-half, +half):   # one beam per X-edge of bay
                        cx_b  = vox.center.X + cx_off
                        bkey  = (round(cx_b, 4), round(y_from, 4),
                                 round(beam_z, 4), "+Y")
                        if bkey in placed_beam:
                            continue
                        placed_beam.add(bkey)
                        mid_pt = rg.Point3d(cx_b, y_from + span_y * 0.5,
                                            beam_z - ps * 0.5)
                        if beam_geos:
                            oriented = _place_custom(beam_geos, bp, bs, bd_z,
                                                     mid_pt, ps, span_y,
                                                     axis=rg.Vector3d.YAxis)
                            for g in oriented:
                                guids = _add_geos([g], layer_name)
                                all_guids.extend(guids)
                                count += len(guids)
                        else:
                            count += _add_proc_box(
                                rg.Point3d(cx_b - ps * 0.5, y_from, beam_z - ps),
                                ps, span_y, ps)

    if all_guids:
        import time as _time
        _group_objects(all_guids, "VOXELGEN_Structure_Custom_{}".format(int(_time.time())))

    return count


def _ornament_core(voxels, source_geos, attractor_geos, effect,
                   val_min, val_max, invert, auto_scale,
                   density_falloff, density_min, face_filter, layer_name):
    """Inner ornament loop for one voxel list + one source_geos set.
    Returns (count, guid_list)."""
    import random as _rand

    src_bb     = _combined_bb(source_geos)
    src_origin = rg.Point3d(src_bb.Center.X, src_bb.Center.Y, src_bb.Min.Z)
    src_plane  = rg.Plane(src_origin, rg.Vector3d.ZAxis)
    src_face_w = src_bb.Max.X - src_bb.Min.X
    src_face_h = src_bb.Max.Y - src_bb.Min.Y
    src_size   = max(src_face_w, src_face_h, 1e-6)

    if face_filter == "Top+Bottom only":
        candidate_dirs = ["+Z", "-Z"]
    elif face_filter == "All faces":
        candidate_dirs = list(ALL_FACES)
    else:
        candidate_dirs = list(SIDE_FACES)

    face_data = []
    all_z     = []
    for vox in voxels:
        all_z.append(vox.center.Z)
        for face_dir in candidate_dirs:
            ftype = vox.face_types.get(face_dir, "exterior")
            if ftype not in ("exterior", "inter_program", "top", "bottom"):
                continue
            plane = get_face_plane(vox, face_dir)
            dist  = _dist_to_attractor(attractor_geos, plane.Origin) if attractor_geos else 0.0
            face_data.append((vox, face_dir, plane, dist))

    if not face_data:
        return 0, []

    if attractor_geos:
        dists   = [fd[3] for fd in face_data]
        d_min   = min(dists)
        d_range = max(dists) - d_min or 1.0
    else:
        d_min, d_range = 0.0, 1.0

    z_min   = min(all_z) if all_z else 0.0
    z_range = (max(all_z) - z_min) if all_z and max(all_z) > z_min else 1.0

    count = 0
    guids = []

    for vox, face_dir, target_plane, dist in face_data:
        t_raw = (dist - d_min) / d_range if attractor_geos else 0.0

        if density_falloff and attractor_geos:
            keep_prob = 1.0 - t_raw * (1.0 - density_min / 100.0)
            if _rand.random() > keep_prob:
                continue

        t = t_raw if attractor_geos else 0.5
        if invert:
            t = 1.0 - t
        eff_val = val_min + t * (val_max - val_min)

        oriented_geos = _orient_geos(source_geos, src_plane, target_plane)

        if auto_scale and src_size > 1e-6:
            pre_sf = vox.size / src_size
            xform  = rg.Transform.Scale(target_plane.Origin, pre_sf)
            for g in oriented_geos:
                g.Transform(xform)

        if effect == "Rotation":
            rad   = math.radians(eff_val)
            xform = rg.Transform.Rotation(rad, target_plane.ZAxis, target_plane.Origin)
            for g in oriented_geos:
                g.Transform(xform)

        elif effect == "Scale":
            sf    = max(0.001, eff_val)
            xform = rg.Transform.Scale(target_plane.Origin, sf)
            for g in oriented_geos:
                g.Transform(xform)

        elif effect == "Spiral":
            ht    = (vox.center.Z - z_min) / z_range
            rad   = math.radians(ht * eff_val)
            xform = rg.Transform.Rotation(rad, rg.Vector3d.ZAxis, target_plane.Origin)
            for g in oriented_geos:
                g.Transform(xform)

        elif effect == "Projection":
            xform = rg.Transform.Translation(target_plane.ZAxis * eff_val)
            for g in oriented_geos:
                g.Transform(xform)

        elif effect == "Scale+Project":
            proj_depth = eff_val
            v_range    = max(abs(val_max - val_min), 1e-6)
            sf         = 0.1 + 0.9 * abs(eff_val - val_min) / v_range
            xf_scale   = rg.Transform.Scale(target_plane.Origin, sf)
            xf_proj    = rg.Transform.Translation(target_plane.ZAxis * proj_depth)
            for g in oriented_geos:
                g.Transform(xf_scale)
                g.Transform(xf_proj)

        elif effect == "Taper":
            rad     = math.radians(eff_val)
            v_range = max(abs(val_max - val_min), 1e-6)
            sf      = 0.2 + 0.8 * abs(eff_val - val_min) / v_range
            xf_r    = rg.Transform.Rotation(rad, target_plane.ZAxis, target_plane.Origin)
            xf_s    = rg.Transform.Scale(target_plane.Origin, sf)
            for g in oriented_geos:
                g.Transform(xf_s)
                g.Transform(xf_r)

        guids.extend(_add_geos(oriented_geos, layer_name))
        count += 1

    return count, guids


def apply_ornament_mode(voxels_dict, target_layers, source_geos,
                        attractor_geos, effect, val_min, val_max, invert, auto_scale=True,
                        density_falloff=False, density_min=20, face_filter="Sides only",
                        place_at="All voxels",
                        src_geos_b=None, src_geos_c=None, cluster_seed=0):
    """
    place_at     : any PLACE_AT_OPTIONS value including "Random Cluster Groups"
    src_geos_b/c : optional alternate source geos for cluster B and C
    """
    import time as _time
    layer_name = ensure_output_layer("Ornament")
    raw_vox    = _target_voxels(voxels_dict, target_layers)
    count      = 0
    all_guids  = []

    if place_at == "Random Cluster Groups":
        clusters = _split_3_clusters(raw_vox, seed=cluster_seed)
        geos_abc = [
            source_geos,
            src_geos_b if src_geos_b else source_geos,
            src_geos_c if src_geos_c else source_geos,
        ]
        for cluster_voxels, cluster_geos in zip(clusters, geos_abc):
            if not cluster_voxels or not cluster_geos:
                continue
            n, guids = _ornament_core(
                cluster_voxels, cluster_geos, attractor_geos,
                effect, val_min, val_max, invert, auto_scale,
                density_falloff, density_min, face_filter, layer_name)
            count    += n
            all_guids.extend(guids)
    else:
        voxels = _filter_by_place_at(raw_vox, place_at)
        count, all_guids = _ornament_core(
            voxels, source_geos, attractor_geos,
            effect, val_min, val_max, invert, auto_scale,
            density_falloff, density_min, face_filter, layer_name)

    _group_objects(all_guids, "VOXELGEN_Ornament_{}".format(int(_time.time())))
    return count


# ==============================================================================
#  CIRCULATION MODE  —  Parametric Stair in Vertical Stacks
# ==============================================================================

def _build_stair(base_center, vox_size, num_levels,
                 stair_width, step_rise, step_run, rot_x_deg, mirror):
    breps        = []
    total_h      = vox_size * num_levels
    num_steps    = max(1, int(round(total_h / step_rise)))
    actual_rise  = total_h / num_steps
    actual_run   = min(step_run,   vox_size * 0.9)
    actual_width = min(stair_width, vox_size * 0.9)

    base_x = base_center.X - actual_width * 0.5
    base_y = base_center.Y - (num_steps * actual_run) * 0.5
    base_z = base_center.Z - vox_size * num_levels * 0.5

    for s in range(num_steps):
        origin = rg.Point3d(base_x,
                            base_y + s * actual_run,
                            base_z + s * actual_rise)
        box = rg.Box(
            rg.Plane(origin, rg.Vector3d.XAxis, rg.Vector3d.YAxis),
            rg.Interval(0, actual_width),
            rg.Interval(0, actual_run),
            rg.Interval(0, actual_rise),
        )
        if box.IsValid:
            breps.append(box.ToBrep())

    if not breps:
        return []

    # X-axis rotation
    if rot_x_deg:
        pivot  = rg.Point3d(base_center.X, base_center.Y,
                            base_z + total_h * 0.5)
        xform  = rg.Transform.Rotation(
            math.radians(rot_x_deg), rg.Vector3d.XAxis, pivot)
        for b in breps:
            b.Transform(xform)

    # Mirror across X plane at voxel centre
    if mirror:
        mp    = rg.Plane(base_center, rg.Vector3d.XAxis)
        xform = rg.Transform.Mirror(mp)
        for b in breps:
            b.Transform(xform)

    return breps


def apply_circulation_mode(voxels_dict, target_layers,
                            stair_width, step_rise, step_run,
                            rot_x_deg, mirror, handrail,
                            place_at="All voxels"):
    layer_name = ensure_output_layer("Circulation")

    stacks = {}
    _voxels = _filter_by_place_at(_target_voxels(voxels_dict, target_layers), place_at)
    for vox in _voxels:
        ij = (vox.grid_ijk[0], vox.grid_ijk[1])
        stacks.setdefault(ij, []).append(vox)

    count     = 0
    all_guids = []
    for stack_voxels in stacks.values():
        if len(stack_voxels) < 2:
            continue
        stack_voxels.sort(key=lambda v: v.grid_ijk[2])
        base = stack_voxels[0]

        # Stair centre spans the full column height
        col_center = rg.Point3d(
            base.center.X,
            base.center.Y,
            base.center.Z + base.size * (len(stack_voxels) - 1) * 0.5,
        )

        step_breps = _build_stair(
            col_center, base.size, len(stack_voxels),
            stair_width, step_rise, step_run, rot_x_deg, mirror)

        for b in step_breps:
            g = _add_brep(b, layer_name)
            if g: all_guids.append(g)
        count += len(step_breps)

    import time as _time
    _group_objects(all_guids, "VOXELGEN_Circulation_{}".format(int(_time.time())))
    return count


# ==============================================================================
#  GUI
# ==============================================================================

class DistributionVoxelsForm(eforms.Form):

    def __init__(self):
        eforms.Form.__init__(self)          # required by Rhino 8 CPython .NET inheritance
        self.Title           = "Distribution Voxels Component  V16"
        self.Resizable       = True
        self.MinimumSize     = edrawing.Size(480, 540)
        self.ClientSize      = edrawing.Size(500, 700)
        self.Padding         = edrawing.Padding(6)
        self.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        self._voxels_dict  = {}
        self._voxel_size   = 0.0
        self._avail_layers = []
        self._facade_src   = None   # list of GUIDs — facade element A
        self._facade_src_b = None   # list of GUIDs — facade element B (cluster)
        self._facade_src_c = None   # list of GUIDs — facade element C (cluster)
        self._orn_src      = None   # list of GUIDs — ornament element A
        self._orn_src_b    = None   # list of GUIDs — ornament element B (cluster)
        self._orn_src_c    = None   # list of GUIDs — ornament element C (cluster)
        self._struct_src_col   = None   # list of GUIDs — column element A (optional)
        self._struct_src_col_b = None   # list of GUIDs — column element B (optional)
        self._struct_src_beam  = None   # list of GUIDs — beam element (optional)
        self._struct_gx        = None   # grid X spinner widget
        self._struct_gy        = None   # grid Y spinner widget
        self._struct_gz        = None   # grid Z spinner widget
        self._disc_src_a   = None   # list of GUIDs — discrete element A (required)
        self._disc_src_b   = None   # list of GUIDs — discrete element B (optional)
        self._disc_src_c   = None   # list of GUIDs — discrete element C (optional)
        self._disc_src_d   = None   # list of GUIDs — discrete element D (optional) — V16
        self._disc_src_e   = None   # list of GUIDs — discrete element E (optional) — V16
        self._disc_src_f   = None   # list of GUIDs — discrete element F (optional) — V16
        # V7 discrete controls
        self._disc_span_cb         = None   # CheckBox "Custom span length"
        self._disc_span_num        = None   # NumericStepper 1–20
        self._disc_invert_placement = None  # CheckBox invert face-level filter
        # Solar shield sub-panel controls
        self._disc_sun_az     = None
        self._disc_sun_alt    = None
        self._disc_sun_thresh = None
        self._disc_sun_panel  = None
        self._disc_sun_status = None   # label showing peak-sun load status
        # Attractor gradient sub-panel controls
        self._disc_attractor_pt  = None   # Point3d or None
        self._disc_attr_radius   = None
        self._disc_attr_min      = None
        self._disc_attr_max      = None
        self._disc_attr_panel    = None
        # V8 — Cluster placement sub-panel controls
        self._disc_cluster_target = None   # Dropdown: All/A/B/C only
        self._disc_cluster_faces  = None   # Dropdown: All exposed / Inter-cluster boundary only
        self._disc_cluster_panel  = None
        # V8 — Sub-Placement controls
        self._disc_sub_cb         = None   # CheckBox: Sub-Placement mode toggle
        self._disc_sub_placement  = None   # Dropdown: sub-placement position type
        self._disc_sub_invert     = None   # CheckBox: invert sub-placement
        self._disc_sub_inside     = None   # CheckBox: place inside voxels
        self._disc_sub_panel      = None
        # V8 — Resolution mode controls (mutually exclusive)
        self._disc_hi_res_cb      = None   # CheckBox: High Resolution mode ON/OFF
        self._disc_hi_res         = None   # NumericStepper: N for N×N face sub-grid (2–8)
        self._disc_lo_res_cb      = None   # CheckBox: Low Resolution (Bay) mode ON/OFF
        self._disc_lo_res_x       = None   # NumericStepper: bay group width in X (2–16)
        self._disc_lo_res_y       = None   # NumericStepper: bay group depth in Y (2–16)
        self._disc_lo_res_z       = None   # NumericStepper: bay group height in Z (1–16)
        # V12 — Density threshold
        self._disc_thresh_cb      = None   # CheckBox: enable density threshold ON/OFF
        self._disc_thresh_density = None   # NumericStepper: fill fraction 0.0–1.0
        # V13 — Grid X×Y×Z (contiguous block) place_at
        self._disc_grid_x         = None   # NumericStepper: block width  (voxels)
        self._disc_grid_y         = None   # NumericStepper: block depth  (voxels)
        self._disc_grid_z         = None   # NumericStepper: block height (voxels)
        self._disc_grid_panel     = None
        # V13 — Circulation gap
        self._disc_circ_cb        = None   # CheckBox: enable circulation gap ON/OFF
        self._disc_circ_rooms     = None   # NumericStepper: number of clusters/rooms
        self._disc_circ_gap       = None   # NumericStepper: gap width in voxels (X/Y)
        # Solar Voxel Bake controls
        self._solar_epw_path      = None   # str — full path to EPW file
        self._solar_epw_lbl       = None
        self._solar_occlusion_cb  = None
        self._solar_key_hours_cb  = None
        self._solar_chart_cb      = None
        self._solar_chart_origin  = None   # Point3d or None
        self._solar_chart_radius  = None
        self._solar_thresh_5      = None   # NumericStepper for tier thresholds
        self._solar_thresh_4      = None
        self._solar_thresh_3      = None
        self._solar_thresh_2      = None
        self._solar_status        = None
        # comfort data is read directly from sc.sticky["comfort_data"] at runtime
        self._attractor_geos = []   # list of raw geometries used as attractor
        self._log_history  = []     # last N status messages

        # Skywalk attributes
        self._sky_curves   = []     # list of Curve objects
        self._sky_attractors = []   # list of Point3d objects
        self._sky_profiles = {}     # dict of predefined profiles
        self._sky_default_width = 2.0  # meters
        self._sky_default_height = 0.6  # meters

        # Room Cluster mode — kept for V5 compat, not used in V6 Discrete tab
        self._clust_on          = None
        self._clust_assign_dd   = None
        self._clust_shell_depth = None
        self._clust_status      = None
        self._clust_panel       = None

        # Discrete Room cluster tab — own element sources + widgets
        self._rc_src_a      = None   # list of GUIDs — Element A (required)
        self._rc_src_b      = None   # list of GUIDs — Element B (optional)
        self._rc_src_c      = None   # list of GUIDs — Element C (optional)
        self._rc_n_clusters = None   # spinner widget — number of Voronoi clusters
        self._rc_invert     = None   # checkbox — invert boundary selection

        self._build_ui()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _lbl(self, text, bold=False, width=None):
        lb = eforms.Label()
        lb.Text      = text
        lb.TextColor = edrawing.Color.FromArgb(175, 175, 175)
        lb.Font      = edrawing.Font(lb.Font.FamilyName, 8.0)          # compact 8 pt
        if bold:
            lb.Font = edrawing.Font(lb.Font.FamilyName, 8.0, edrawing.FontStyle.Bold)
        if width is not None:
            lb.Width = width
        lb.VerticalAlignment = eforms.VerticalAlignment.Center
        return lb

    def _section(self, title):
        lb = self._lbl(title, bold=True)
        lb.TextColor = edrawing.Color.FromArgb(155, 155, 155)   # fg_dim lifted for #121212 bg
        return lb

    def _num(self, value, lo, hi, dec=0, inc=1):
        ns = eforms.NumericStepper()
        ns.Value         = value
        ns.MinValue      = lo
        ns.MaxValue      = hi
        ns.DecimalPlaces = dec
        ns.Increment     = inc
        ns.Width         = 80
        return ns

    def _slider(self, value, lo, hi, width=140):
        sl = eforms.Slider()
        sl.MinValue = lo
        sl.MaxValue = hi
        sl.Value    = value
        sl.Width    = width
        return sl

    def _row(self, label, ctrl, lbl_w=150):
        tl = eforms.TableLayout()
        tl.Spacing = edrawing.Size(5, 0)
        lb = self._lbl(label, width=lbl_w)
        spacer = eforms.Label()
        spacer_cell = eforms.TableCell(spacer); spacer_cell.ScaleWidth = True
        tl.Rows.Add(eforms.TableRow(eforms.TableCell(lb), eforms.TableCell(ctrl), spacer_cell))
        return tl

    def _slider_row(self, label, slider, val_lbl, lbl_w=150):
        tl = eforms.TableLayout()
        tl.Spacing = edrawing.Size(5, 0)
        lb = self._lbl(label, width=lbl_w)
        val_lbl.Width = 42
        val_lbl.VerticalAlignment = eforms.VerticalAlignment.Center
        tl.Rows.Add(eforms.TableRow(
            eforms.TableCell(lb),
            eforms.TableCell(eforms.TableLayout.AutoSized(slider)),
            eforms.TableCell(val_lbl),
        ))
        return tl

    def _dropdown(self, items, idx=0):
        dd = eforms.DropDown()
        for item in items:
            li = eforms.ListItem(); li.Text = item; dd.Items.Add(li)
        dd.SelectedIndex = min(idx, len(items) - 1)
        dd.Width = 185
        return dd

    def _checkbox(self, label, checked=False):
        cb = eforms.CheckBox()
        cb.Text      = label
        cb.Checked   = checked
        cb.TextColor = edrawing.Color.FromArgb(175, 175, 175)   # prevent OS-default black
        return cb

    def _pick_btn(self, label, handler, width=90):
        btn = eforms.Button()
        btn.Text            = label
        btn.Click          += handler
        btn.Width           = width
        btn.BackgroundColor = edrawing.Color.FromArgb(50, 50, 50)
        btn.TextColor       = edrawing.Color.FromArgb(218, 218, 218)
        return btn

    def _ensure_layer_exists(self, layer_name, color):
        """Create layer if it doesn't exist"""
        if not rs.IsLayer(layer_name):
            rs.AddLayer(layer_name, color)

    def _set_status(self, msg):
        """Update status label"""
        if hasattr(self, '_status'):
            self._status.Text = msg

    def _pick_row(self, status_lbl, btn):
        tl = eforms.TableLayout()
        tl.Spacing = edrawing.Size(5, 0)
        status_cell = eforms.TableCell(status_lbl); status_cell.ScaleWidth = True
        tl.Rows.Add(eforms.TableRow(
            status_cell,
            eforms.TableCell(btn),
        ))
        return tl

    def _mk_panel(self):
        """Dark-themed Panel for collapsible sub-sections."""
        p = eforms.Panel()
        p.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        return p

    def _mk_lay(self):
        """Dark-themed DynamicLayout for tab content."""
        lay = eforms.DynamicLayout()
        lay.DefaultSpacing  = edrawing.Size(4, 4)
        lay.Padding         = edrawing.Padding(7)
        lay.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        return lay

    def _desc(self, text):
        """Dim one-line description label placed below a control."""
        lbl = eforms.Label()
        lbl.Text      = text
        lbl.TextColor = edrawing.Color.FromArgb(108, 108, 108)   # hint text — dim but readable
        lbl.Font      = edrawing.Font(lbl.Font.FamilyName, 7.0)
        return lbl

    def _seed_row(self, label_text, num_widget, rand_handler):
        """Row: label + stepper + Roll button + trailing spacer."""
        btn = eforms.Button()
        btn.Text            = u"▦ Roll"
        btn.Width           = 50
        btn.BackgroundColor = edrawing.Color.FromArgb(50, 50, 50)
        btn.TextColor       = edrawing.Color.FromArgb(218, 218, 218)
        btn.Click          += rand_handler
        tl = eforms.TableLayout()
        tl.Spacing = edrawing.Size(5, 0)
        lbl = eforms.Label(); lbl.Text = label_text; lbl.Width = 95
        lbl.TextColor = edrawing.Color.FromArgb(175, 175, 175)
        spacer = eforms.Label()
        spacer_cell = eforms.TableCell(spacer); spacer_cell.ScaleWidth = True
        tl.Rows.Add(eforms.TableRow(
            eforms.TableCell(lbl),
            eforms.TableCell(num_widget),
            eforms.TableCell(btn),
            spacer_cell,
        ))
        return tl
    def _pick_row3(self, status_lbl, btn_load, btn_clear):
        tl = eforms.TableLayout()
        tl.Spacing = edrawing.Size(4, 0)
        spacer = eforms.Label()
        spacer_cell = eforms.TableCell(spacer); spacer_cell.ScaleWidth = True
        tl.Rows.Add(eforms.TableRow(
            eforms.TableCell(status_lbl),
            eforms.TableCell(btn_load),
            eforms.TableCell(btn_clear),
            spacer_cell,
        ))
        return tl

    # ── build UI ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── HEADER (fixed height) ──────────────────────────────────────────────
        header = eforms.DynamicLayout()
        header.DefaultSpacing = edrawing.Size(4, 3)
        header.Padding        = edrawing.Padding(4, 4, 4, 0)
        header.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        step_lbl = self._lbl(u"  \u2460 SELECT VOXELS   \u2461 CONFIGURE MODE   \u2462 APPLY", bold=True)
        step_lbl.TextColor = edrawing.Color.FromArgb(218, 218, 218)
        header.AddRow(step_lbl)

        sel_row = eforms.TableLayout()
        sel_row.Spacing = edrawing.Size(6, 0)
        btn_sel = eforms.Button(); btn_sel.Text = u"\u25b6  Load Selected Voxels"
        btn_sel.Click += self._on_select_voxels; btn_sel.Width = 160; btn_sel.Height = 22
        btn_sel.BackgroundColor = edrawing.Color.FromArgb(65, 65, 65); btn_sel.TextColor = edrawing.Color.FromArgb(218, 218, 218)
        btn_dbg = eforms.Button(); btn_dbg.Text = "Debug Info"
        btn_dbg.Click += self._on_debug; btn_dbg.Width = 68; btn_dbg.Height = 22
        btn_dbg.BackgroundColor = edrawing.Color.FromArgb(50, 50, 50); btn_dbg.TextColor = edrawing.Color.FromArgb(218, 218, 218)
        sel_row.Rows.Add(eforms.TableRow(
            eforms.TableCell(btn_sel),
            eforms.TableCell(eforms.TableLayout.AutoSized(eforms.Label())),
            eforms.TableCell(btn_dbg),
        ))
        header.AddRow(sel_row)

        self._layers_lbl = self._lbl(u"\u2460 Select voxels in viewport first, then click \u25b6 Load Selected Voxels")
        self._layers_lbl.Wrap = eforms.WrapMode.Word
        header.AddRow(self._layers_lbl)

        self._size_lbl = self._lbl("Voxel size: —")
        header.AddRow(self._size_lbl)

        # ── TABS (scrollable content) ──────────────────────────────────────────
        self._tabs = eforms.TabControl()

        _dk = edrawing.Color.FromArgb(18, 18, 18)   # bg_form dark token

        def _scrollable(content):
            sc_w = eforms.Scrollable()
            sc_w.Content             = content
            sc_w.ExpandContentWidth  = True
            sc_w.ExpandContentHeight = False
            sc_w.BackgroundColor     = _dk
            return sc_w

        def _tab(text, build_fn):
            tp = eforms.TabPage()
            tp.Text            = text
            tp.BackgroundColor = _dk
            tp.Content         = _scrollable(build_fn())
            return tp

        self._tabs.BackgroundColor = _dk
        self._tabs.Pages.Add(_tab("Room",                   self._build_room_tab))
        self._tabs.Pages.Add(_tab("Facade",                 self._build_facade_tab))
        self._tabs.Pages.Add(_tab("Structure",              self._build_structure_tab))
        self._tabs.Pages.Add(_tab("Ornament",               self._build_ornament_tab))
        self._tabs.Pages.Add(_tab("Circulation",            self._build_circulation_tab))
        self._tabs.Pages.Add(_tab("Discrete",               self._build_discrete_tab))
        self._tabs.Pages.Add(_tab("Skywalk",                self._build_skywalk_tab))
        self._tabs.Pages.Add(_tab("Discrete Room cluster",  self._build_room_cluster_tab))

        # ── LIVE MODE — debounce timer + param wiring ──────────────────────────
        # UITimer fires on the UI thread → safe to call Rhino API directly.
        # Interval = 0.4 s debounce: any param change restarts the timer so rapid
        # rolling (seed steppers, dropdowns) waits for the user to pause before
        # triggering an apply.
        self._live_timer = eforms.UITimer()
        self._live_timer.Interval = 0.4
        self._live_timer.Elapsed += self._on_live_tick

        # Wire all Discrete-tab param controls so changes trigger live re-apply.
        _lpc = self._on_live_param_changed
        for _ctrl in [self._disc_cluster_seed, self._disc_rand_seed,
                      self._disc_orient_strength, self._disc_span_num,
                      self._disc_hi_res, self._disc_grid_x,
                      self._disc_grid_y, self._disc_grid_z]:
            if _ctrl is not None:
                _ctrl.ValueChanged += _lpc
        for _ctrl in [self._disc_place_dd, self._disc_assign_dd,
                      self._disc_layer_dd, self._disc_cluster_target,
                      self._disc_cluster_faces, self._disc_orient_dd,
                      self._disc_sub_placement]:
            if _ctrl is not None:
                _ctrl.SelectedIndexChanged += _lpc
        for _ctrl in [self._disc_scale, self._disc_invert_placement,
                      self._disc_sub_cb, self._disc_sub_invert,
                      self._disc_sub_inside, self._disc_hi_res_cb,
                      self._disc_span_cb, self._disc_cluster_invert]:
            if _ctrl is not None:
                _ctrl.CheckedChanged += _lpc

        # ── FOOTER (fixed height) ──────────────────────────────────────────────
        self._status = eforms.Label()
        self._status.Text      = u"● Select voxels in viewport, then click \u25b6 Load Selected Voxels"
        self._status.TextColor = edrawing.Color.FromArgb(130, 130, 130)
        self._status.Wrap      = eforms.WrapMode.Word

        self._history_lbl = eforms.Label()
        self._history_lbl.Text      = ""
        self._history_lbl.TextColor = edrawing.Color.FromArgb(130, 130, 130)
        self._history_lbl.Wrap      = eforms.WrapMode.Word

        _bg_hi  = edrawing.Color.FromArgb(65, 65, 65)
        _bg_btn = edrawing.Color.FromArgb(50, 50, 50)
        _fg_btn = edrawing.Color.FromArgb(218, 218, 218)
        btn_apply = eforms.Button(); btn_apply.Text = "Apply";      btn_apply.Click += self._on_apply;  btn_apply.Width = 48; btn_apply.Height = 20; btn_apply.BackgroundColor = _bg_hi;  btn_apply.TextColor = _fg_btn
        btn_clear = eforms.Button(); btn_clear.Text = "Clear Last"; btn_clear.Click += self._on_clear;  btn_clear.Width = 68; btn_clear.Height = 20; btn_clear.BackgroundColor = _bg_btn; btn_clear.TextColor = _fg_btn
        btn_close = eforms.Button(); btn_close.Text = "Close";      btn_close.Click += lambda s, e: self.Close(); btn_close.Width = 46; btn_close.Height = 20; btn_close.BackgroundColor = _bg_btn; btn_close.TextColor = _fg_btn

        # Live toggle — glows green when active
        self._live_cb = eforms.CheckBox()
        self._live_cb.Text    = u"● Live"
        self._live_cb.Checked = False
        self._live_cb.TextColor       = edrawing.Color.FromArgb(110, 110, 110)
        self._live_cb.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        self._live_cb.CheckedChanged  += self._on_live_toggle

        btn_row = eforms.TableLayout()
        btn_row.Spacing = edrawing.Size(6, 0)
        _spacer_cell = eforms.TableCell(eforms.Label()); _spacer_cell.ScaleWidth = True
        btn_row.Rows.Add(eforms.TableRow(
            eforms.TableCell(btn_apply),
            eforms.TableCell(btn_clear),
            _spacer_cell,
            eforms.TableCell(self._live_cb),
            eforms.TableCell(btn_close),
        ))

        footer = eforms.DynamicLayout()
        footer.DefaultSpacing  = edrawing.Size(4, 2)
        footer.Padding         = edrawing.Padding(4, 2, 4, 3)
        footer.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        footer.AddRow(self._status)
        footer.AddRow(self._history_lbl)
        footer.AddRow(btn_row)

        # ── OUTER: TableLayout so only tab row scales ──────────────────────────
        outer = eforms.TableLayout()
        outer.Spacing = edrawing.Size(0, 0)
        outer.Padding = edrawing.Padding(0)

        outer.Rows.Add(eforms.TableRow(eforms.TableCell(header)))

        tab_row = eforms.TableRow(eforms.TableCell(self._tabs))
        tab_row.ScaleHeight = True
        outer.Rows.Add(tab_row)

        outer.Rows.Add(eforms.TableRow(eforms.TableCell(footer)))

        self.Content = outer

    # ── tab builders ─────────────────────────────────────────────────────────

    def _build_room_tab(self):
        lay = eforms.DynamicLayout()
        lay.DefaultSpacing  = edrawing.Size(4, 4)
        lay.Padding         = edrawing.Padding(7)
        lay.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        lay.AddRow(self._section("ROOM  —  Multi-Voxel Distribution"))
        self._room_prereq = self._lbl(u"\u2717 Voxels not selected yet", width=400)
        self._room_prereq.TextColor = edrawing.Color.FromArgb(220, 80, 80)
        lay.AddRow(self._room_prereq)
        lay.AddRow(None)

        self._room_layer_dd = self._dropdown(["All layers"])
        lay.AddRow(self._row("Target layer:", self._room_layer_dd))

        # ── Distribution type ────────────────────────────────────────────────
        lay.AddRow(self._section("Room Distribution"))
        self._room_dist_dd = self._dropdown([
            "Single Voxel",
            "Random Clusters",
            "Grid 2\u00d72",
            "Grid 2\u00d73",
            "Grid 3\u00d73",
            "Voronoi",
            "Bands X",
            "Bands Y",
        ])
        lay.AddRow(self._row("Strategy:", self._room_dist_dd))

        # Min size / band width
        self._room_min_sl  = self._slider(1, 1, 12, width=140)
        self._room_min_lbl = self._lbl("1 vox")
        self._room_min_sl.ValueChanged += self._on_room_size_changed
        lay.AddRow(self._slider_row(u"Min size / band (vox):",
                                    self._room_min_sl, self._room_min_lbl))

        # Max size / num Voronoi seeds
        self._room_max_sl  = self._slider(4, 1, 20, width=140)
        self._room_max_lbl = self._lbl("4 vox")
        self._room_max_sl.ValueChanged += self._on_room_size_changed
        lay.AddRow(self._slider_row(u"Max size / seeds (vox):",
                                    self._room_max_sl, self._room_max_lbl))

        # Random seed
        self._room_seed = self._num(42, 0, 99999, 0, 1)
        lay.AddRow(self._row("Random seed:", self._room_seed))

        lay.AddRow(None)

        # ── Envelope treatment ───────────────────────────────────────────────
        lay.AddRow(self._section("Envelope"))

        self._room_side_dd = self._dropdown(["Window Frame", "Solid", "Open"])
        lay.AddRow(self._row("Exterior side:", self._room_side_dd))

        self._room_wwr_sl = self._slider(DEFAULTS["room_wwr"], 0, 100)
        self._room_wwr_lb = self._lbl(str(DEFAULTS["room_wwr"]) + "%")
        self._room_wwr_sl.ValueChanged += lambda s, e: setattr(
            self._room_wwr_lb, "Text", str(self._room_wwr_sl.Value) + "%")
        lay.AddRow(self._slider_row("Window-wall ratio:", self._room_wwr_sl, self._room_wwr_lb))

        self._room_slab = self._num(DEFAULTS["room_slab_t"], 0.01, 10.0, 2, 0.05)
        lay.AddRow(self._row("Slab thickness (units):", self._room_slab))

        lay.AddRow(None)
        self._room_place_dd = self._dropdown(PLACE_AT_OPTIONS)
        lay.AddRow(self._row("Place at:", self._room_place_dd))

        return lay

    def _on_room_size_changed(self, s, e):
        mn = int(self._room_min_sl.Value)
        mx = int(self._room_max_sl.Value)
        dist = self._dd_val(self._room_dist_dd)
        if "Voronoi" in dist:
            self._room_min_lbl.Text = "{} vox".format(mn)
            self._room_max_lbl.Text = "{} seeds".format(mx)
        elif "Bands" in dist:
            self._room_min_lbl.Text = "{} vox wide".format(mn)
            self._room_max_lbl.Text = u"\u2014"
        else:
            self._room_min_lbl.Text = "{} vox".format(mn)
            self._room_max_lbl.Text = "{} vox".format(mx)

    def _build_facade_tab(self):
        lay = eforms.DynamicLayout()
        lay.DefaultSpacing  = edrawing.Size(4, 4)
        lay.Padding         = edrawing.Padding(7)
        lay.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        lay.AddRow(self._section("FACADE  —  Component Distribution"))
        self._facade_prereq = self._lbl(u"\u2717 Voxels not selected  \u2717 No source element", width=400)
        self._facade_prereq.TextColor = edrawing.Color.FromArgb(220, 80, 80)
        lay.AddRow(self._facade_prereq)
        lay.AddRow(None)

        self._facade_src_lbl = self._lbl("Select element(s), then click button \u2192", width=240)
        lay.AddRow(self._pick_row(self._facade_src_lbl,
                                  self._pick_btn("Load Selected as Element", self._on_pick_facade, width=170)))

        self._facade_layer_dd = self._dropdown(["All layers"])
        lay.AddRow(self._row("Target layer:", self._facade_layer_dd))

        self._facade_face_dd = self._dropdown(
            ["All exterior", "Sides only", "Top/Bottom only", "N/S only", "E/W only"])
        lay.AddRow(self._row("Face filter:", self._facade_face_dd))

        self._facade_offset = self._num(DEFAULTS["facade_offset"], -5000, 5000, 0, 10)
        lay.AddRow(self._row("Push-out offset (mm):", self._facade_offset))

        self._facade_every = self._num(DEFAULTS["facade_every_n"], 1, 20, 0, 1)
        lay.AddRow(self._row("Place every N faces:", self._facade_every))

        self._facade_scale = self._checkbox("Scale element to fit voxel face", True)
        lay.AddRow(self._facade_scale)

        lay.AddRow(None)
        self._facade_place_dd = self._dropdown(PLACE_AT_OPTIONS)
        lay.AddRow(self._row("Place at:", self._facade_place_dd))

        lay.AddRow(self._section(u"Cluster Groups  \u2014  Element B & C  (for 'Random Cluster Groups')"))
        self._facade_src_b_lbl = self._lbl(u"Cluster B \u2014 select in viewport \u2192", width=240)
        lay.AddRow(self._pick_row(self._facade_src_b_lbl,
            self._pick_btn("Load as Element B", self._on_pick_facade_b, width=145)))
        self._facade_src_c_lbl = self._lbl(u"Cluster C \u2014 select in viewport \u2192", width=240)
        lay.AddRow(self._pick_row(self._facade_src_c_lbl,
            self._pick_btn("Load as Element C", self._on_pick_facade_c, width=145)))
        self._facade_cluster_seed = self._num(0, 0, 9999, 0, 1)
        lay.AddRow(self._row("Cluster seed:", self._facade_cluster_seed))

        return lay

    def _build_structure_tab(self):
        lay = eforms.DynamicLayout()
        lay.DefaultSpacing  = edrawing.Size(4, 4)
        lay.Padding         = edrawing.Padding(7)
        lay.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        lay.AddRow(self._section("STRUCTURE  —  Structural System"))
        self._struct_prereq = self._lbl(u"\u2717 Voxels not selected yet", width=400)
        self._struct_prereq.TextColor = edrawing.Color.FromArgb(220, 80, 80)
        lay.AddRow(self._struct_prereq)
        lay.AddRow(None)

        # ── Column element A ──────────────────────────────────────────────────
        lay.AddRow(self._section(u"Column Element  (optional)"))
        self._struct_col_lbl = self._lbl(
            u"None \u2014 procedural box column", width=260)
        lay.AddRow(self._pick_row3(
            self._struct_col_lbl,
            self._pick_btn(u"Load Column", self._on_pick_struct_col, width=110),
            self._pick_btn(u"\u2715 Clear",  self._on_clear_struct_col, width=50)))
        lay.AddRow(self._desc(
            u"Column body: placed at voxel CORNERS, spans Z-grid height. "
            u"Output \u2192 VOXELGEN_Structure. If empty: procedural box."))

        # ── Column joint element ──────────────────────────────────────────────
        lay.AddRow(None)
        lay.AddRow(self._section(u"Column Joint  (optional)"))
        self._struct_col_b_lbl = self._lbl(
            u"None \u2014 placed at same position as Column", width=260)
        lay.AddRow(self._pick_row3(
            self._struct_col_b_lbl,
            self._pick_btn(u"Load Joint", self._on_pick_struct_col_b, width=110),
            self._pick_btn(u"\u2715 Clear", self._on_clear_struct_col_b, width=50)))
        lay.AddRow(self._desc(
            u"Placed at EVERY column position alongside the Column element.\n"
            u"Output goes to VOXELGEN_Structure_Joint \u2014 assign a different material there."))

        # ── Beam element ──────────────────────────────────────────────────────
        lay.AddRow(None)
        lay.AddRow(self._section(u"Beam Element  (optional)"))
        self._struct_beam_lbl = self._lbl(
            u"None \u2014 procedural box beam", width=260)
        lay.AddRow(self._pick_row3(
            self._struct_beam_lbl,
            self._pick_btn(u"Load Beam", self._on_pick_struct_beam, width=110),
            self._pick_btn(u"\u2715 Clear",  self._on_clear_struct_beam, width=50)))
        lay.AddRow(self._desc(
            u"Beam runs between column corners along X and Y, scaled to span. "
            u"If empty: procedural box."))

        # ── X×Y×Z Grid spacing ────────────────────────────────────────────────
        lay.AddRow(None)
        lay.AddRow(self._section(u"Grid Spacing  X \u00d7 Y \u00d7 Z  (voxels)"))

        grid_row = eforms.DynamicLayout()
        grid_row.DefaultSpacing  = edrawing.Size(6, 0)
        grid_row.Padding         = edrawing.Padding(0)
        grid_row.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        grid_row.BeginHorizontal()
        grid_row.Add(self._lbl(u"X:", width=22))
        self._struct_gx = self._num(2, 1, 20, 0, 1)
        grid_row.Add(self._struct_gx)
        grid_row.Add(self._lbl(u"  Y:", width=28))
        self._struct_gy = self._num(2, 1, 20, 0, 1)
        grid_row.Add(self._struct_gy)
        grid_row.Add(self._lbl(u"  Z:", width=28))
        self._struct_gz = self._num(3, 1, 20, 0, 1)
        grid_row.Add(self._struct_gz)
        grid_row.EndHorizontal()
        lay.AddRow(grid_row)
        lay.AddRow(self._desc(
            u"e.g. 2\u00d72\u00d73 or 3\u00d73\u00d73 \u2014 columns placed every "
            u"Nth voxel in each axis.  Used when \u2018Place at\u2019 = Grid X\u00d7Y\u00d7Z."))

        # ── Target layer & type ───────────────────────────────────────────────
        lay.AddRow(None)
        self._struct_layer_dd = self._dropdown(["All layers"])
        lay.AddRow(self._row("Target layer:", self._struct_layer_dd))

        self._struct_mode_dd = self._dropdown([
            "Column", "Beam", "Both",
            "X-Brace", "Flat Slab", "Full Frame",
        ])
        lay.AddRow(self._row("Structure type:", self._struct_mode_dd))
        lay.AddRow(self._desc(
            u"Column/Beam/Both: uses Grid X\u00d7Y\u00d7Z spacing + custom elements.\n"
            u"X-Brace, Flat Slab, Full Frame use built-in procedural geometry."))

        # Profile size — for procedural fallback
        self._struct_size     = self._slider(DEFAULTS["struct_size"], 1, 30, width=160)
        self._struct_size_lbl = self._lbl("8%  (~0.26 u)")
        self._struct_size.ValueChanged += self._on_struct_size_changed
        lay.AddRow(self._slider_row(u"Profile size (% voxel):",
                                    self._struct_size, self._struct_size_lbl))
        lay.AddRow(self._desc(u"Profile size used for procedural box fallback only."))

        # Place at — includes the new Grid X×Y×Z option
        _struct_place_opts = [u"Grid X\u00d7Y\u00d7Z"] + PLACE_AT_OPTIONS
        self._struct_place_dd = self._dropdown(_struct_place_opts)
        self._struct_place_dd.SelectedIndex = 0
        lay.AddRow(self._row("Place at:", self._struct_place_dd))

        return lay

    def _on_struct_size_changed(self, s, e):
        pct = int(self._struct_size.Value)
        actual = (pct / 100.0) * self._voxel_size if self._voxel_size > 0 else 0.0
        self._struct_size_lbl.Text = "{}%  (~{:.2f} u)".format(pct, actual)

    def _build_ornament_tab(self):
        lay = eforms.DynamicLayout()
        lay.DefaultSpacing  = edrawing.Size(4, 4)
        lay.Padding         = edrawing.Padding(7)
        lay.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        lay.AddRow(self._section("ORNAMENT  —  Attractor Distribution"))
        self._orn_prereq = self._lbl(u"\u2717 Voxels  \u2717 Source element", width=400)
        self._orn_prereq.TextColor = edrawing.Color.FromArgb(220, 80, 80)
        lay.AddRow(self._orn_prereq)
        lay.AddRow(None)

        self._orn_src_lbl = self._lbl("Select element(s), then click \u2192", width=240)
        lay.AddRow(self._pick_row(self._orn_src_lbl,
                                  self._pick_btn("Load Selected as Element", self._on_pick_orn, width=170)))

        self._orn_attr_lbl = self._lbl(u"Optional attractor \u2014 select any geo \u2192", width=260)
        lay.AddRow(self._pick_row(self._orn_attr_lbl,
                                  self._pick_btn("Load Selected as Attractor", self._on_pick_attr, width=180)))

        self._orn_layer_dd = self._dropdown(["All layers"])
        lay.AddRow(self._row("Target layer:", self._orn_layer_dd))

        self._orn_face_dd = self._dropdown(["Sides only", "All faces", "Top+Bottom only"])
        lay.AddRow(self._row("Face filter:", self._orn_face_dd))

        self._orn_effect_dd = self._dropdown([
            "Scale+Project", "Projection", "Scale", "Rotation", "Spiral", "Taper",
        ])
        lay.AddRow(self._row("Effect:", self._orn_effect_dd))

        self._orn_min = self._num(DEFAULTS["orn_min"], -360, 360, 0, 5)
        lay.AddRow(self._row("Min value (dist / depth):", self._orn_min))

        self._orn_max = self._num(DEFAULTS["orn_max"], -360, 360, 0, 5)
        lay.AddRow(self._row("Max value (dist / depth):", self._orn_max))

        self._orn_invert = self._checkbox("Invert  (near attractor = more effect)", True)
        self._orn_scale  = self._checkbox("Auto-scale to voxel face size", True)
        lay.AddRow(self._orn_invert)
        lay.AddRow(self._orn_scale)
        lay.AddRow(None)

        # ── Density falloff ──────────────────────────────────────────────────
        lay.AddRow(self._section("Density Falloff  (attractor-driven)"))
        self._orn_density_cb  = self._checkbox(
            "Enable  \u2014 attractor drives how many faces are populated", False)
        lay.AddRow(self._orn_density_cb)

        self._orn_density_sl  = self._slider(20, 0, 100, width=160)
        self._orn_density_lbl = self._lbl("20%  min at edge")
        self._orn_density_sl.ValueChanged += self._on_orn_density_changed
        lay.AddRow(self._slider_row("Min density at edge:",
                                    self._orn_density_sl, self._orn_density_lbl))

        lay.AddRow(None)
        self._orn_place_dd = self._dropdown(PLACE_AT_OPTIONS)
        lay.AddRow(self._row("Place at:", self._orn_place_dd))

        lay.AddRow(self._section(u"Cluster Groups  \u2014  Element B & C  (for 'Random Cluster Groups')"))
        self._orn_src_b_lbl = self._lbl(u"Cluster B \u2014 select in viewport \u2192", width=240)
        lay.AddRow(self._pick_row(self._orn_src_b_lbl,
            self._pick_btn("Load as Element B", self._on_pick_orn_b, width=145)))
        self._orn_src_c_lbl = self._lbl(u"Cluster C \u2014 select in viewport \u2192", width=240)
        lay.AddRow(self._pick_row(self._orn_src_c_lbl,
            self._pick_btn("Load as Element C", self._on_pick_orn_c, width=145)))
        self._orn_cluster_seed = self._num(0, 0, 9999, 0, 1)
        lay.AddRow(self._row("Cluster seed:", self._orn_cluster_seed))

        return lay

    def _on_orn_density_changed(self, s, e):
        v = int(self._orn_density_sl.Value)
        self._orn_density_lbl.Text = "{}%  min at edge".format(v)

    def _build_circulation_tab(self):
        lay = eforms.DynamicLayout()
        lay.DefaultSpacing  = edrawing.Size(4, 4)
        lay.Padding         = edrawing.Padding(7)
        lay.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        lay.AddRow(self._section("CIRCULATION  —  Parametric Stair"))
        lay.AddRow(self._lbl(u"Targets vertical stacks of \u2265 2 voxels at same XY position."))
        self._circ_prereq = self._lbl(u"\u2717 Voxels not selected yet", width=400)
        self._circ_prereq.TextColor = edrawing.Color.FromArgb(220, 80, 80)
        lay.AddRow(self._circ_prereq)
        lay.AddRow(None)

        self._circ_layer_dd = self._dropdown(["All layers"])
        lay.AddRow(self._row("Target layer:", self._circ_layer_dd))

        self._circ_place_dd = self._dropdown(PLACE_AT_OPTIONS)
        lay.AddRow(self._row("Place at:", self._circ_place_dd))

        self._stair_width = self._num(DEFAULTS["stair_width"], 100, 5000, 0, 50)
        lay.AddRow(self._row("Stair width (mm):", self._stair_width))

        self._step_rise = self._num(DEFAULTS["stair_rise"], 50, 400, 0, 5)
        lay.AddRow(self._row("Step rise (mm):", self._step_rise))

        self._step_run = self._num(DEFAULTS["stair_run"], 100, 600, 0, 10)
        lay.AddRow(self._row("Step run (mm):", self._step_run))

        self._rot_x_sl = self._slider(DEFAULTS["stair_rot_x"], 0, 360)
        self._rot_x_lb = self._lbl(str(DEFAULTS["stair_rot_x"]) + u"\u00b0")
        self._rot_x_sl.ValueChanged += lambda s, e: setattr(
            self._rot_x_lb, "Text", str(self._rot_x_sl.Value) + u"\u00b0")
        lay.AddRow(self._slider_row("Rotation X-axis:", self._rot_x_sl, self._rot_x_lb))

        self._stair_mirror   = self._checkbox("Mirror / Flip side")
        self._stair_handrail = self._checkbox("Add simple handrail")
        lay.AddRow(self._stair_mirror)
        lay.AddRow(self._stair_handrail)

        return lay

    def _build_discrete_tab(self):
        lay = eforms.DynamicLayout()
        lay.DefaultSpacing  = edrawing.Size(4, 4)
        lay.Padding         = edrawing.Padding(7)
        lay.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        lay.AddRow(self._section("DISCRETE  \u2014  Combinatorial Distribution"))
        self._disc_prereq = self._lbl(
            u"\u2717 Voxels not selected  \u2717 No Element A", width=420)
        self._disc_prereq.TextColor = edrawing.Color.FromArgb(220, 80, 80)
        lay.AddRow(self._disc_prereq)
        lay.AddRow(None)

        # ── Elements ──────────────────────────────────────────────────────────
        lay.AddRow(self._section("Elements  (A required, B-F optional)"))

        self._disc_src_a_lbl = self._lbl(
            u"Element A  (required) \u2014 select \u2192", width=240)
        lay.AddRow(self._pick_row3(
            self._disc_src_a_lbl,
            self._pick_btn("Load as Element A", self._on_pick_disc_a, width=130),
            self._pick_btn(u"\u2715 Clear", self._on_clear_disc_a, width=50)))

        self._disc_src_b_lbl = self._lbl(
            u"Element B  (optional) \u2014 select \u2192", width=240)
        lay.AddRow(self._pick_row3(
            self._disc_src_b_lbl,
            self._pick_btn("Load as Element B", self._on_pick_disc_b, width=130),
            self._pick_btn(u"\u2715 Clear", self._on_clear_disc_b, width=50)))

        self._disc_src_c_lbl = self._lbl(
            u"Element C  (optional) \u2014 select \u2192", width=240)
        lay.AddRow(self._pick_row3(
            self._disc_src_c_lbl,
            self._pick_btn("Load as Element C", self._on_pick_disc_c, width=130),
            self._pick_btn(u"\u2715 Clear", self._on_clear_disc_c, width=50)))

        # V16 \u2014 Elements D / E / F
        self._disc_src_d_lbl = self._lbl(
            u"Element D  (optional) \u2014 select \u2192", width=240)
        lay.AddRow(self._pick_row3(
            self._disc_src_d_lbl,
            self._pick_btn("Load as Element D", self._on_pick_disc_d, width=130),
            self._pick_btn(u"\u2715 Clear", self._on_clear_disc_d, width=50)))

        self._disc_src_e_lbl = self._lbl(
            u"Element E  (optional) \u2014 select \u2192", width=240)
        lay.AddRow(self._pick_row3(
            self._disc_src_e_lbl,
            self._pick_btn("Load as Element E", self._on_pick_disc_e, width=130),
            self._pick_btn(u"\u2715 Clear", self._on_clear_disc_e, width=50)))

        self._disc_src_f_lbl = self._lbl(
            u"Element F  (optional) \u2014 select \u2192", width=240)
        lay.AddRow(self._pick_row3(
            self._disc_src_f_lbl,
            self._pick_btn("Load as Element F", self._on_pick_disc_f, width=130),
            self._pick_btn(u"\u2715 Clear", self._on_clear_disc_f, width=50)))

        lay.AddRow(None)

        # ── Distribution Controls ──────────────────────────────────────────────
        self._disc_layer_dd = self._dropdown(["All layers"])
        lay.AddRow(self._row("Target layer:", self._disc_layer_dd))
        lay.AddRow(self._desc("Filter which voxel colour-layers receive elements."))

        self._disc_assign_dd = self._dropdown(
            ["By Z-level", "By adjacency", "By cluster", "Random mix"])
        self._disc_assign_dd.SelectedIndex = 0
        lay.AddRow(self._row("Assignment:", self._disc_assign_dd))
        lay.AddRow(self._desc(
            u"How A/B/C types are assigned \u2014 Z-level: low\u2192A mid\u2192B top\u2192C  "
            u"| Adjacency: corner/edge/face exposure  | Cluster: Voronoi 3-zone  | Random: seeded shuffle"))

        # ── V8 Sub-Placement mode ─────────────────────────────────────────────
        # When ON, the Assignment becomes a NAVIGATOR that buckets voxels into A/B/C
        # voxel pools. A single Sub-Placement position type (same options as
        # Placement) is then applied to each bucket with its own input element.
        # The main Placement dropdown is bypassed while Sub-Placement is ON.
        self._disc_sub_cb = self._checkbox(
            u"Sub-Placement mode  \u2014 Assignment navigates, Sub-Placement positions", False)
        lay.AddRow(self._disc_sub_cb)

        self._disc_sub_placement = self._dropdown(
            ["Exterior faces", "Wall", "Top edges", "All exposed",
             "Ceiling", "Floor", "Facade sides", "Facade sides+dividers",
             "Corner expression", "Solar shield", "Threshold",
             "Cluster", "Random", "Replace voxel"])
        self._disc_sub_placement.SelectedIndex = 1   # default: Wall
        self._disc_sub_invert  = self._checkbox(u"Invert sub-placement", False)
        self._disc_sub_inside  = self._checkbox(
            u"Place inside voxels  \u2014 element projects inward instead of outward", False)

        self._disc_sub_panel = self._mk_panel()
        _sub_inner = eforms.DynamicLayout()
        _sub_inner.DefaultSpacing  = edrawing.Size(4, 2)
        _sub_inner.Padding         = edrawing.Padding(0)
        _sub_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        _sub_inner.AddRow(self._row(u"  Sub-Placement type:", self._disc_sub_placement))
        _sub_inner.AddRow(self._disc_sub_invert)
        _sub_inner.AddRow(self._disc_sub_inside)
        _sub_inner.AddRow(self._desc(
            u"  Assignment \u2192 A/B/C voxel buckets (no placement yet).\n"
            u"  Sub-Placement \u2192 applies this position type to each bucket,\n"
            u"  using Element A on bucket A's voxels, B on B's, C on C's.\n"
            u"  'Place inside' flips the face normal inward \u2014 elements line the\n"
            u"  inner surface of voxels rather than cladding the outside.\n"
            u"  Best paired with By Z-level / By adjacency / By cluster\n"
            u"  (spatially coherent buckets). Random mix scatters labels and\n"
            u"  degrades Wall / Threshold / Cluster sub-placements."))
        self._disc_sub_panel.Content = _sub_inner
        self._disc_sub_panel.Visible = False
        lay.AddRow(self._disc_sub_panel)

        def _on_sub_cb_changed(s, e):
            self._disc_sub_panel.Visible = bool(self._disc_sub_cb.Checked)
            # Grey out main Placement dropdown to signal bypass
            try:
                self._disc_place_dd.Enabled = not bool(self._disc_sub_cb.Checked)
            except Exception:
                pass
        self._disc_sub_cb.CheckedChanged += _on_sub_cb_changed

        # ── Span ─────────────────────────────────────────────────────────────
        self._disc_span_cb  = self._checkbox(u"Custom span length", False)
        self._disc_span_num = self._num(2, 1, 20, 0, 1)
        _span_sub = self._mk_panel()
        _span_inner = eforms.DynamicLayout()
        _span_inner.DefaultSpacing  = edrawing.Size(6, 3)
        _span_inner.Padding         = edrawing.Padding(0)
        _span_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        _span_inner.AddRow(self._row(u"  Span length (voxels):", self._disc_span_num))
        _span_inner.AddRow(self._desc(
            u"2 = bridge 2 adjacent voxels  |  3 = chain 3 collinear  |  up to 20"))
        _span_sub.Content = _span_inner
        _span_sub.Visible = False

        def _on_span_cb_changed(s, e):
            _span_sub.Visible = bool(self._disc_span_cb.Checked)
        self._disc_span_cb.CheckedChanged += _on_span_cb_changed

        lay.AddRow(self._disc_span_cb)
        lay.AddRow(_span_sub)
        lay.AddRow(self._desc(
            u"Unchecked = single element per face (span 1).  "
            u"Checked = elements bridge/chain across N adjacent collinear voxels."))

        # ── Placement ─────────────────────────────────────────────────────────
        self._disc_place_dd = self._dropdown(
            ["Exterior faces", "Wall", "Top edges", "All exposed",
             "Ceiling", "Floor", "Facade sides", "Facade sides+dividers",
             "Corner expression", "Solar shield", "Threshold",
             "Cluster", "Random", "Replace voxel"])
        self._disc_place_dd.SelectedIndex = 0
        lay.AddRow(self._row("Placement:", self._disc_place_dd))
        lay.AddRow(self._desc(
            u"Exterior: outer faces only  | Wall: shared interface between adjacent voxels  "
            u"| Top edges: +Z cap  | All exposed: every non-interior face\n"
            u"Ceiling: +Z inward  | Floor: \u2212Z inward  "
            u"| Facade sides: outward cladding on TRUE exterior side faces only (no program dividers)\n"
            u"Facade sides+dividers: V7 behaviour \u2014 include interior program-divider faces too\n"
            u"Corner expression: voxels with \u22653 exposed sides (massing corners)  "
            u"| Solar shield: faces within N\u00b0 of sun direction\n"
            u"Threshold: shared face between different program layers  "
            u"| Cluster: 3-seed Voronoi grouping (uses cluster seed)  "
            u"| Random: seeded 50% random face selection\n"
            u"Replace voxel: one element per voxel placed at voxel centre (fills voxel volume — use with Density Threshold for sparse fill)"))

        # Solar shield sub-panel — visible only when "Solar shield" is selected
        self._disc_sun_az     = self._num(180, 0, 360, 0, 5)
        self._disc_sun_alt    = self._num(45, 0, 90, 0, 5)
        self._disc_sun_thresh = self._num(60, 10, 90, 0, 5)
        self._disc_sun_panel  = self._mk_panel()
        sun_inner = eforms.DynamicLayout()
        sun_inner.DefaultSpacing  = edrawing.Size(6, 3)
        sun_inner.Padding         = edrawing.Padding(0)
        sun_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        # ── Solar shield ↔ Solar Bake integration ─────────────────────────────
        _btn_load_peak = eforms.Button()
        _btn_load_peak.Text = u"\U0001f4e5  Load peak sun from EPW bake"
        _btn_load_peak.Click += self._on_load_peak_sun
        sun_inner.AddRow(_btn_load_peak)
        self._disc_sun_status = self._lbl(u"Run 'Bake Solar Voxels' first, then click above.", width=360)
        self._disc_sun_status.TextColor = edrawing.Color.FromArgb(130, 130, 130)
        sun_inner.AddRow(self._disc_sun_status)
        sun_inner.AddRow(None)

        sun_inner.AddRow(self._row(u"  Sun azimuth (\u00b0):", self._disc_sun_az))
        sun_inner.AddRow(self._desc(u"  0=N  90=E  180=S  270=W  (Melbourne peak sun \u2248 az 310\u00b0 alt 72\u00b0 in summer)"))
        sun_inner.AddRow(self._row(u"  Sun altitude (\u00b0):", self._disc_sun_alt))
        sun_inner.AddRow(self._row(u"  Cone threshold (\u00b0):", self._disc_sun_thresh))
        sun_inner.AddRow(self._desc(
            u"  Faces within this many degrees of the sun direction are included.\n"
            u"  Combine with Place at = 'Solar high zones' to restrict placement to\n"
            u"  only the voxels the bake identified as high-radiation."))
        self._disc_sun_panel.Content = sun_inner
        self._disc_sun_panel.Visible = False
        lay.AddRow(self._disc_sun_panel)

        # V8 — Cluster placement sub-panel (visible only when Placement = "Cluster")
        self._disc_cluster_target = self._dropdown(
            [u"All", u"A only", u"B only", u"C only",
             u"D only", u"E only", u"F only"])
        self._disc_cluster_target.SelectedIndex = 0
        self._disc_cluster_faces = self._dropdown(
            [u"All exposed", u"Wall cluster",
             u"Wall cluster - no facade", u"Wall cluster - only facade",
             u"Floor cluster", u"Ceiling cluster"])
        self._disc_cluster_faces.SelectedIndex = 0
        self._disc_cluster_panel = self._mk_panel()
        _cl_inner = eforms.DynamicLayout()
        _cl_inner.DefaultSpacing  = edrawing.Size(6, 3)
        _cl_inner.Padding         = edrawing.Padding(0)
        _cl_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        self._disc_cluster_invert = self._checkbox(u"  Invert cluster placement", False)
        _cl_inner.AddRow(self._row(u"  Cluster target:", self._disc_cluster_target))
        _cl_inner.AddRow(self._row(u"  Cluster faces:",  self._disc_cluster_faces))
        _cl_inner.AddRow(self._disc_cluster_invert)
        _cl_inner.AddRow(self._desc(
            u"  Splits voxels into 3 Voronoi groups via the Cluster seed below.\n"
            u"  'All' = every cluster receives elements  |  'A-F only' = just that group (6 zones).\n"
            u"  'All exposed' = every non-interior face of cluster voxels (incl top/bottom).\n"
            u"  'Wall cluster' = hollow ROOM: outer perimeter + inter-cluster dividers, side only.\n"
            u"  'Wall cluster - no facade' = inter-cluster dividers only; outer field boundary open.\n"
            u"  'Wall cluster - only facade' = outer field boundary only; no internal dividers.\n"
            u"  'Floor cluster' = -Z face per zone: field-bottom slab + inter-cluster threshold floors.\n"
            u"  'Ceiling cluster' = +Z face per zone: field-top cap + inter-cluster threshold ceilings."))
        self._disc_cluster_panel.Content = _cl_inner
        self._disc_cluster_panel.Visible = False
        lay.AddRow(self._disc_cluster_panel)

        def _on_place_mode_changed(s, e):
            m = self._dd_val(self._disc_place_dd)
            self._disc_sun_panel.Visible     = (m == "Solar shield")
            self._disc_cluster_panel.Visible = (m == "Cluster")
        self._disc_place_dd.SelectedIndexChanged += _on_place_mode_changed

        # Invert placement (face-level invert, complements existing voxel-level invert)
        self._disc_invert_placement = self._checkbox(
            u"Invert placement  \u2014 place on the excluded faces instead", False)
        lay.AddRow(self._disc_invert_placement)
        lay.AddRow(self._desc(
            u"Flips the face filter: Exterior \u2192 interior faces  |  Facade sides \u2192 top/bottom only  "
            u"|  Random \u2192 the other 50%  |  Corner expression \u2192 infill between corners"))

        self._disc_orient_dd = self._dropdown(
            ["Face-normal", "Rotated sequence", "Edge-aligned",
             "Centrifugal", "Shard outward", "Vortex"])
        self._disc_orient_dd.SelectedIndex = 1   # default: Rotated sequence
        lay.AddRow(self._row("Orientation:", self._disc_orient_dd))
        lay.AddRow(self._desc(
            u"Face-normal: Z to face  | Rotated: +90\u00b0 steps  | Edge-aligned: 90\u00b0 constant  "
            u"| Centrifugal: lean away from field centre  "
            u"| Shard outward: radial + upward tilt (crystal burst)  | Vortex: tangential spin"))

        self._disc_orient_strength = self._num(0.7, 0.0, 1.0, 2, 0.05)
        lay.AddRow(self._row(u"Orient strength:", self._disc_orient_strength))
        lay.AddRow(self._desc(
            u"0 = pure face-normal  \u2192  1 = full lean (applies to Centrifugal / Shard / Vortex only)"))

        self._disc_scale = self._checkbox("Scale to fit voxel size", False)  # default OFF
        lay.AddRow(self._disc_scale)
        lay.AddRow(self._desc(u"Uniform scale so element footprint matches voxel face size."))

        # ── Resolution Mode ──────────────────────────────────────────────────────
        # High Resolution and Low Resolution are mutually exclusive.
        # Checking one automatically unchecks the other.
        lay.AddRow(None)
        lay.AddRow(self._section(u"Resolution Mode"))

        # ── High Resolution ──────────────────────────────────────────────────────
        self._disc_hi_res_cb = self._checkbox(
            u"High Resolution mode  \u2014 subdivide each voxel face into N\u00d7N cells", False)
        lay.AddRow(self._disc_hi_res_cb)

        self._disc_hi_res = self._num(2, 2, 8, 0, 1)
        _hires_panel = self._mk_panel()
        _hires_inner = eforms.DynamicLayout()
        _hires_inner.DefaultSpacing  = edrawing.Size(6, 3)
        _hires_inner.Padding         = edrawing.Padding(0)
        _hires_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        _hires_inner.AddRow(self._row(u"  Sub-grid N\u00d7N per face:", self._disc_hi_res))
        _hires_inner.AddRow(self._desc(
            u"  2 \u2192 2\u00d72 = 4 elements per face  |  4 \u2192 4\u00d74 = 16  "
            u"|  8 \u2192 8\u00d78 = 64  (max)\n"
            u"  Element is scaled to fit each sub-cell.  "
            u"Mutually exclusive with Low Resolution mode."))
        _hires_panel.Content = _hires_inner
        _hires_panel.Visible = False
        lay.AddRow(_hires_panel)

        # ── Low Resolution (Bay) ─────────────────────────────────────────────────
        self._disc_lo_res_cb = self._checkbox(
            u"Low Resolution mode  \u2014 merge voxels into bay super-units", False)
        lay.AddRow(self._disc_lo_res_cb)

        self._disc_lo_res_x = self._num(2, 1, 16, 0, 1)
        self._disc_lo_res_y = self._num(2, 1, 16, 0, 1)
        self._disc_lo_res_z = self._num(1, 1, 16, 0, 1)
        _lores_panel = self._mk_panel()
        _lores_inner = eforms.DynamicLayout()
        _lores_inner.DefaultSpacing  = edrawing.Size(6, 3)
        _lores_inner.Padding         = edrawing.Padding(0)
        _lores_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        _lores_inner.AddRow(self._row(u"  Bay width  X (voxels):", self._disc_lo_res_x))
        _lores_inner.AddRow(self._row(u"  Bay depth  Y (voxels):", self._disc_lo_res_y))
        _lores_inner.AddRow(self._row(u"  Bay height Z (voxels):", self._disc_lo_res_z))
        _lores_inner.AddRow(self._desc(
            u"  Reads N\u00d7M\u00d7P voxels as one bay, places ONE element per bay face.\n"
            u"  Incomplete bays at field edges are skipped (clean grid only).\n"
            u"  2\u00d72\u00d71 = 4 voxels \u2192 1 unit  |  2\u00d72\u00d72 = 8 voxels \u2192 1 unit.\n"
            u"  Z=1 = no vertical grouping  |  Z>1 = stack Z levels into one block.\n"
            u"  Geometry projects INWARD (fills bay volume from face inward).\n"
            u"  Mutually exclusive with High Resolution mode."))
        _lores_panel.Content = _lores_inner
        _lores_panel.Visible = False
        lay.AddRow(_lores_panel)

        # ── mutual-exclusion handlers ─────────────────────────────────────────────
        def _on_hires_cb_changed(s, e):
            on = bool(self._disc_hi_res_cb.Checked)
            _hires_panel.Visible = on
            if on and bool(self._disc_lo_res_cb.Checked):
                self._disc_lo_res_cb.Checked = False
                _lores_panel.Visible = False

        def _on_lores_cb_changed(s, e):
            on = bool(self._disc_lo_res_cb.Checked)
            _lores_panel.Visible = on
            if on and bool(self._disc_hi_res_cb.Checked):
                self._disc_hi_res_cb.Checked = False
                _hires_panel.Visible = False

        self._disc_hi_res_cb.CheckedChanged += _on_hires_cb_changed
        self._disc_lo_res_cb.CheckedChanged += _on_lores_cb_changed

        lay.AddRow(None)
        # V13: discrete-specific place_at list \u2014 drop fixed Grid 2\u00d72 / 3\u00d73,
        # add customisable "Grid X\u00d7Y\u00d7Z" contiguous-block option.
        _disc_place_opts = [o for o in PLACE_AT_OPTIONS
                            if o not in (u"Grid 2\u00d72", u"Grid 3\u00d73")]
        _disc_place_opts.insert(3, u"Grid X\u00d7Y\u00d7Z")
        self._disc_vox_place_dd = self._dropdown(_disc_place_opts)
        self._disc_vox_place_dd.SelectedIndex = 0
        lay.AddRow(self._row("Place at:", self._disc_vox_place_dd))
        lay.AddRow(self._desc(
            u"Voxel filter: All / Boundary / Perimeter / Grid X\u00d7Y\u00d7Z / Stacks / Clusters\n"
            u"V7: Z-gradient | Checkerboard XY/3D | Attractor gradient\n"
            u"\u2600 Solar integration (requires 'Bake Solar Voxels' first):\n"
            u"  Solar high zones = CritHigh+High tiers only  "
            u"| Solar exposed zones = High+Med  "
            u"| Solar shade zones = Low+Shade\n"
            u"  Combine Solar high zones + Solar shield placement for fully EPW-driven facade."))

        # \u2500\u2500 V13: Grid X\u00d7Y\u00d7Z block panel \u2014 visible only when that option selected \u2500\u2500
        self._disc_grid_x = self._num(2, 1, 32, 0, 1)
        self._disc_grid_y = self._num(2, 1, 32, 0, 1)
        self._disc_grid_z = self._num(1, 1, 32, 0, 1)
        self._disc_grid_panel = self._mk_panel()
        _grid_inner = eforms.DynamicLayout()
        _grid_inner.DefaultSpacing  = edrawing.Size(6, 3)
        _grid_inner.Padding         = edrawing.Padding(0)
        _grid_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        _grid_xyz = eforms.DynamicLayout()
        _grid_xyz.DefaultSpacing  = edrawing.Size(6, 0)
        _grid_xyz.Padding         = edrawing.Padding(0)
        _grid_xyz.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        _grid_xyz.BeginHorizontal()
        _grid_xyz.Add(self._lbl(u"  X:", width=26))
        _grid_xyz.Add(self._disc_grid_x)
        _grid_xyz.Add(self._lbl(u"  Y:", width=28))
        _grid_xyz.Add(self._disc_grid_y)
        _grid_xyz.Add(self._lbl(u"  Z:", width=28))
        _grid_xyz.Add(self._disc_grid_z)
        _grid_xyz.EndHorizontal()
        _grid_inner.AddRow(_grid_xyz)
        _grid_inner.AddRow(self._desc(
            u"  Groups voxels into contiguous X\u00d7Y\u00d7Z blocks \u2014 ONE element per block,\n"
            u"  scaled to fill the block volume (like Low-Resolution bays).\n"
            u"  e.g. 1\u00d71\u00d71 = per voxel | 2\u00d72\u00d71 = floor bay | 2\u00d72\u00d72 = cube | 2\u00d73\u00d72.\n"
            u"  Overrides the Placement mode (block-fill takes precedence)."))
        self._disc_grid_panel.Content = _grid_inner
        self._disc_grid_panel.Visible = False
        lay.AddRow(self._disc_grid_panel)

        # Shell depth — visible only when "Boundary only" is selected
        self._disc_shell_depth = self._num(1, 1, 20, 0, 1)
        shell_row_lbl  = self._row(u"  Boundary shell depth:", self._disc_shell_depth)
        shell_desc_lbl = self._desc(
            u"1 = outermost ring only  |  2 = 2 layers deep  |  3 = 3 layers inward\u2026")

        self._disc_shell_panel = self._mk_panel()
        shell_inner = eforms.DynamicLayout()
        shell_inner.DefaultSpacing  = edrawing.Size(6, 3)
        shell_inner.Padding         = edrawing.Padding(0)
        shell_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        shell_inner.AddRow(shell_row_lbl)
        shell_inner.AddRow(shell_desc_lbl)
        self._disc_shell_panel.Content = shell_inner
        self._disc_shell_panel.Visible = False   # hidden by default

        lay.AddRow(self._disc_shell_panel)

        # Attractor gradient sub-panel — visible only when "Attractor gradient" is selected
        self._disc_attr_radius = self._num(20, 1, 500, 0, 1)
        self._disc_attr_min    = self._num(0.0, 0.0, 1.0, 2, 0.05)
        self._disc_attr_max    = self._num(1.0, 0.0, 1.0, 2, 0.05)
        self._disc_attr_panel  = self._mk_panel()
        attr_inner = eforms.DynamicLayout()
        attr_inner.DefaultSpacing  = edrawing.Size(6, 3)
        attr_inner.Padding         = edrawing.Padding(0)
        attr_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        _btn_attr = eforms.Button(); _btn_attr.Text = u"Pick attractor point (Rhino)"
        _btn_attr.Click += self._on_pick_attractor_pt
        attr_inner.AddRow(_btn_attr)
        self._disc_attr_lbl = self._lbl(u"No point picked", width=220)
        attr_inner.AddRow(self._row(u"  Point:", self._disc_attr_lbl))
        attr_inner.AddRow(self._row(u"  Influence radius:", self._disc_attr_radius))
        attr_inner.AddRow(self._desc(u"  Elements become sparse beyond this distance from the attractor."))
        attr_inner.AddRow(self._row(u"  Min probability (far):", self._disc_attr_min))
        attr_inner.AddRow(self._row(u"  Max probability (near):", self._disc_attr_max))
        self._disc_attr_panel.Content = attr_inner
        self._disc_attr_panel.Visible = False
        lay.AddRow(self._disc_attr_panel)

        def _on_place_dd_changed(s, e):
            sel = self._dd_val(self._disc_vox_place_dd)
            self._disc_shell_panel.Visible = (sel == "Boundary only")
            self._disc_attr_panel.Visible  = (sel == "Attractor gradient")
            self._disc_grid_panel.Visible  = (sel == u"Grid X×Y×Z")

        self._disc_vox_place_dd.SelectedIndexChanged += _on_place_dd_changed

        self._disc_invert_place = self._checkbox(u"Invert selection  \u2014 place on the excluded voxels instead", False)
        lay.AddRow(self._disc_invert_place)
        lay.AddRow(self._desc(u"Flips the filter: e.g. Boundary \u2192 interior only, Perimeter \u2192 non-perimeter voxels."))

        # \u2500\u2500 V11: Exposure Threshold \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        lay.AddRow(None)
        lay.AddRow(self._section(u"Density Threshold"))
        self._disc_thresh_cb = self._checkbox(
            u"Enable density threshold  \u2014 randomly leave voxels empty", False)
        lay.AddRow(self._disc_thresh_cb)

        self._disc_thresh_density = self._num(0.7, 0.0, 1.0, 2, 0.05)
        _thresh_panel = self._mk_panel()
        _thresh_inner = eforms.DynamicLayout()
        _thresh_inner.DefaultSpacing  = edrawing.Size(6, 3)
        _thresh_inner.Padding         = edrawing.Padding(0)
        _thresh_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        _thresh_inner.AddRow(self._row(u"  Fill density (0.0 \u2013 1.0):", self._disc_thresh_density))
        _thresh_inner.AddRow(self._desc(
            u"  1.0 = all qualifying voxels receive elements (no empty space)\n"
            u"  0.7 = 70% filled, 30% randomly left empty\n"
            u"  0.0 = all voxels skipped (nothing placed)\n"
            u"  Seeded \u2014 same seed + density gives same pattern. "
            u"Pair with \u2018Replace voxel\u2019 placement for sparse volumetric fill."))
        _thresh_panel.Content = _thresh_inner
        _thresh_panel.Visible = False
        lay.AddRow(_thresh_panel)

        def _on_thresh_cb(s, e):
            _thresh_panel.Visible = bool(self._disc_thresh_cb.Checked)
        self._disc_thresh_cb.CheckedChanged += _on_thresh_cb

        # ── V13: Circulation Gap ────────────────────────────────────────────────
        lay.AddRow(None)
        lay.AddRow(self._section(u"Circulation Gap"))
        self._disc_circ_cb = self._checkbox(
            u"Enable circulation — leave empty gaps between voxel clusters", False)
        lay.AddRow(self._disc_circ_cb)

        self._disc_circ_rooms = self._num(6, 2, 50, 0, 1)
        self._disc_circ_gap   = self._num(1, 1, 5, 0, 1)
        _circ_panel = self._mk_panel()
        _circ_inner = eforms.DynamicLayout()
        _circ_inner.DefaultSpacing  = edrawing.Size(6, 3)
        _circ_inner.Padding         = edrawing.Padding(0)
        _circ_inner.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        _circ_inner.AddRow(self._row(u"  Clusters (rooms):", self._disc_circ_rooms))
        _circ_inner.AddRow(self._row(u"  Gap width (voxels):", self._disc_circ_gap))
        _circ_inner.AddRow(self._desc(
            u"  Partitions voxels into N Voronoi clusters (uses Cluster seed), then\n"
            u"  removes voxels within ‘gap’ of a different cluster — in X/Y only,\n"
            u"  never top/bottom. Carves empty circulation corridors between rooms."))
        _circ_panel.Content = _circ_inner
        _circ_panel.Visible = False
        lay.AddRow(_circ_panel)

        def _on_circ_cb(s, e):
            _circ_panel.Visible = bool(self._disc_circ_cb.Checked)
        self._disc_circ_cb.CheckedChanged += _on_circ_cb

        lay.AddRow(None)
        self._disc_constrain = self._checkbox(u"Constrain to field bounds", False)
        lay.AddRow(self._disc_constrain)
        lay.AddRow(self._desc(u"Reject elements whose placement centre falls outside the voxel field."))
        self._disc_margin = self._num(0.5, 0.0, 5.0, 1, 0.25)
        lay.AddRow(self._row(u"  Field margin (voxels):", self._disc_margin))
        lay.AddRow(self._desc(u"How far outside the field edge is still allowed (0 = strict inside)."))

        lay.AddRow(None)
        self._disc_interlock = self._checkbox(
            u"Interlocking joint \u2014 boolean-cut overlapping elements", False)
        lay.AddRow(self._disc_interlock)
        lay.AddRow(self._desc(u"Detects overlapping Brep pairs and cuts a mutual half-lap notch at each contact."))

        lay.AddRow(None)
        self._disc_cluster_seed = self._num(0, 0, 9999, 0, 1)
        lay.AddRow(self._seed_row(
            "Cluster seed:", self._disc_cluster_seed, self._on_rand_cluster_seed))
        lay.AddRow(self._desc(u"Seed for Voronoi cluster split (By cluster / Random Cluster Groups)."))

        self._disc_rand_seed = self._num(42, 0, 9999, 0, 1)
        lay.AddRow(self._seed_row(
            "Random seed:", self._disc_rand_seed, self._on_rand_rand_seed))
        lay.AddRow(self._desc(u"Seed for Random mix assignment. Same seed always gives same pattern."))

        # ── Climate Adaptive Mode ──────────────────────────────────────────────
        lay.AddRow(None)
        lay.AddRow(self._section(u"Climate Adaptive Mode  (auto-behavior)"))

        self._disc_climate_on = self._checkbox(
            u"\u2600 Enable climate response  \u2014  auto-adjusts skin depth & density", False)
        lay.AddRow(self._disc_climate_on)
        lay.AddRow(self._desc(
            u"Reads sc.sticky[\u2018comfort_data\u2019] from Climate Comfort Agent V2 and runs 5 passes with zone-specific parameters."))

        # Climate source panel — visible when checkbox is ON
        self._disc_climate_panel = self._mk_panel()
        clin = eforms.DynamicLayout()
        clin.DefaultSpacing  = edrawing.Size(6, 4)
        clin.Padding         = edrawing.Padding(0)
        clin.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)

        import scriptcontext as _sc
        _has_data = bool(_sc.sticky.get("comfort_data"))
        self._disc_climate_path_lbl = self._lbl(
            u"\u2705 comfort_data ready in sc.sticky" if _has_data
            else u"\u26a0 No comfort data \u2014 run Climate Comfort Agent V2 first",
            width=380)
        self._disc_climate_path_lbl.TextColor = (
            edrawing.Color.FromArgb(80, 190, 80) if _has_data else edrawing.Color.FromArgb(220, 80, 80))
        clin.AddRow(self._disc_climate_path_lbl)
        clin.AddRow(self._desc(
            u"Reads sc.sticky[\u2018comfort_data\u2019] written automatically by Climate Comfort Agent V2 "
            u"when agents complete.  Run Climate Comfort first, then open this script."))

        clin.AddRow(None)
        clin.AddRow(self._lbl(
            u"Auto rules per zone  (depth = boundary shell rings, density = Place at):", width=420))

        # Compact zone-rule table headers
        hdr = eforms.DynamicLayout()
        hdr.DefaultSpacing  = edrawing.Size(4, 0)
        hdr.Padding         = edrawing.Padding(0)
        hdr.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
        hdr.BeginHorizontal()
        hdr.Add(self._lbl(u"Zone", width=100))
        hdr.Add(self._lbl(u"Depth", width=48))
        hdr.Add(self._lbl(u"Place at", width=120))
        hdr.Add(self._lbl(u"Element", width=70))
        hdr.EndHorizontal()
        clin.AddRow(hdr)

        # One editable row per zone
        zone_display = {
            "hot_stagnant": u"\u25a0 Hot+Stagnant",
            "overheated":   u"\u25b2 Overheated",
            "marginal":     u"\u25c6 Marginal",
            "passive":      u"\u25cb Passive",
            "tunnel":       u"\u25ba Wind Tunnel",
        }
        self._disc_clim_depth   = {}
        self._disc_clim_place   = {}
        self._disc_clim_element = {}
        place_opts = [u"Boundary only", u"Grid 2\u00d72", u"Grid 3\u00d73",
                      u"All voxels", u"Perimeter"]
        elem_opts  = ["A", "B", "C", "D", "E", "F"]   # V16

        for zone in CLIMATE_ZONES:
            rule = CLIMATE_RULES_DEFAULT[zone]
            depth_num = self._num(rule["depth"], 1, 10, 0, 1)
            place_dd  = self._dropdown(place_opts)
            # Select matching place option
            for pi, p in enumerate(place_opts):
                if p == rule["place_at"] or p.replace(u"\u00d7", u"\u00d7") == rule["place_at"]:
                    place_dd.SelectedIndex = pi
                    break
            elem_dd = self._dropdown(elem_opts)
            elem_dd.SelectedIndex = elem_opts.index(rule["element"])

            self._disc_clim_depth[zone]   = depth_num
            self._disc_clim_place[zone]   = place_dd
            self._disc_clim_element[zone] = elem_dd

            zrow = eforms.DynamicLayout()
            zrow.DefaultSpacing  = edrawing.Size(4, 0)
            zrow.Padding         = edrawing.Padding(0)
            zrow.BackgroundColor = edrawing.Color.FromArgb(18, 18, 18)
            zrow.BeginHorizontal()
            zrow.Add(self._lbl(zone_display.get(zone, zone), width=100))
            zrow.Add(depth_num)
            zrow.Add(place_dd)
            zrow.Add(elem_dd)
            zrow.EndHorizontal()
            clin.AddRow(zrow)

        clin.AddRow(None)
        self._disc_clim_status = self._lbl(u"", width=420)
        self._disc_clim_status.TextColor = edrawing.Color.FromArgb(80, 190, 80)
        clin.AddRow(self._disc_clim_status)

        self._disc_climate_panel.Content = clin
        self._disc_climate_panel.Visible = False

        def _on_climate_toggle(s, e):
            self._disc_climate_panel.Visible = bool(self._disc_climate_on.Checked)
            if self._disc_climate_panel.Visible:
                self._refresh_climate_status()
        self._disc_climate_on.CheckedChanged += _on_climate_toggle

        lay.AddRow(self._disc_climate_panel)

        # ── Solar Voxel Analysis ───────────────────────────────────────────────
        lay.AddRow(None)
        lay.AddRow(self._section(u"\u2600 Solar Voxel Analysis  (EPW + ray shadow casting)"))
        lay.AddRow(self._desc(
            u"Reads Melbourne EPW weather data, casts shadow rays between voxels "
            u"for every daytime sun position, and classifies each voxel into "
            u"5 radiation tiers (kWh/m\u00b2/year). Also draws a stereographic "
            u"sun path chart with shading frequency overlay."))

        # EPW file picker
        _btn_epw = eforms.Button(); _btn_epw.Text = u"\U0001f4c2  Browse EPW file\u2026"
        _btn_epw.Click += self._on_browse_epw
        _default_epw = (u"D:\\RMIT_SEM1 26_AI Accelerated Agentic Architecture TECTONIC"
                        u"\\Week 2\\EPW file-Ladybug\\AUS_VIC_Melbourne.RO.948680_TMYx.epw")
        self._solar_epw_path = _default_epw
        self._solar_epw_lbl  = self._lbl(u"Melbourne EPW (auto-detected)", width=340)
        lay.AddRow(self._row(u"EPW file:", _btn_epw))
        lay.AddRow(self._solar_epw_lbl)

        # Options
        self._solar_occlusion_cb = self._checkbox(
            u"Voxel-to-voxel shadow casting  (Option 3 \u2014 accurate, ~5\u201320s)", True)
        lay.AddRow(self._solar_occlusion_cb)

        self._solar_key_hours_cb = self._checkbox(
            u"Key-hour sampling only  (48 hours, fast preview)", False)
        lay.AddRow(self._solar_key_hours_cb)
        lay.AddRow(self._desc(
            u"Unchecked = full 8760-hour EPW analysis.  "
            u"Checked = 48 representative hours (\u00d7 scaled weight) for fast preview."))

        # Radiation thresholds
        lay.AddRow(None)
        lay.AddRow(self._section(u"Radiation thresholds (kWh/m\u00b2/year)"))
        self._solar_thresh_5 = self._num(600, 0, 3000, 0, 50)
        self._solar_thresh_4 = self._num(400, 0, 3000, 0, 50)
        self._solar_thresh_3 = self._num(200, 0, 3000, 0, 50)
        self._solar_thresh_2 = self._num( 50, 0, 3000, 0, 50)
        lay.AddRow(self._row(u"  \u25A0 Critical high \u2265 :", self._solar_thresh_5))
        lay.AddRow(self._row(u"  \u25A0 High \u2265 :",          self._solar_thresh_4))
        lay.AddRow(self._row(u"  \u25A0 Medium \u2265 :",        self._solar_thresh_3))
        lay.AddRow(self._row(u"  \u25A0 Low \u2265 :",           self._solar_thresh_2))
        lay.AddRow(self._desc(
            u"Melbourne typical max south-facing exposure ~900 kWh/m\u00b2/yr.\n"
            u"North-facing (SH) = highest; South-facing = lowest."))

        # Solar chart options
        lay.AddRow(None)
        self._solar_chart_cb = self._checkbox(u"Draw stereographic sun path chart", True)
        lay.AddRow(self._solar_chart_cb)
        _btn_chart_pt = eforms.Button()
        _btn_chart_pt.Text = u"Pick chart origin (Rhino)"
        _btn_chart_pt.Click += self._on_pick_solar_chart_origin
        self._solar_chart_radius = self._num(10, 1, 200, 0, 1)
        lay.AddRow(self._row(u"  Chart origin:", _btn_chart_pt))
        lay.AddRow(self._row(u"  Chart radius (model units):", self._solar_chart_radius))
        lay.AddRow(self._desc(
            u"Chart placed at picked point (or 50m from field centroid if not picked).\n"
            u"Sun path curves: Jan 21 (summer-SH), Jun 21 (winter-SH), Mar 21 (equinox).\n"
            u"Dots coloured by DNI value. Shading frequency % overlay per sun position."))

        # Status + buttons
        lay.AddRow(None)
        self._solar_status = self._lbl(u"", width=400)
        lay.AddRow(self._solar_status)

        _bg_hi  = edrawing.Color.FromArgb(65, 65, 65)
        _fg_btn = edrawing.Color.FromArgb(218, 218, 218)
        _btn_solar_bake  = eforms.Button()
        _btn_solar_bake.Text            = u"\u25B6 Bake Solar Voxels"
        _btn_solar_bake.Width           = 96
        _btn_solar_bake.Height          = 20
        _btn_solar_bake.BackgroundColor = _bg_hi
        _btn_solar_bake.TextColor       = _fg_btn
        _btn_solar_bake.Click          += self._on_solar_bake

        _btn_chart_only  = eforms.Button()
        _btn_chart_only.Text            = u"\u25B6 Draw Solar Chart Only"
        _btn_chart_only.Width           = 102
        _btn_chart_only.Height          = 20
        _btn_chart_only.BackgroundColor = _bg_hi
        _btn_chart_only.TextColor       = _fg_btn
        _btn_chart_only.Click          += self._on_solar_chart_only

        solar_btn_row = eforms.TableLayout()
        solar_btn_row.Spacing = edrawing.Size(6, 0)
        _sc = eforms.TableCell(eforms.Label()); _sc.ScaleWidth = True
        solar_btn_row.Rows.Add(eforms.TableRow(
            eforms.TableCell(_btn_solar_bake),
            eforms.TableCell(_btn_chart_only),
            _sc,
        ))
        lay.AddRow(solar_btn_row)

        return lay

    # ── status helpers ────────────────────────────────────────────────────────

    def _set_status(self, msg, ok=True):
        # Keep last status in history before replacing
        if self._status.Text and self._status.Text != msg:
            self._log_history.append(self._status.Text)
            self._log_history = self._log_history[-2:]  # keep last 2
            self._history_lbl.Text = u"  \u21b3 prev: " + self._log_history[-1]
        self._status.Text      = msg
        self._status.TextColor = (edrawing.Color.FromArgb(80, 190, 80) if ok
                                  else edrawing.Color.FromArgb(220, 80, 80))

    def _refresh_layer_dropdowns(self):
        items = ["All layers"] + sorted(self._avail_layers)
        for dd in (self._room_layer_dd, self._facade_layer_dd,
                   self._struct_layer_dd, self._orn_layer_dd,
                   self._circ_layer_dd, self._disc_layer_dd):
            prev = dd.SelectedIndex
            dd.Items.Clear()
            for item in items:
                li = eforms.ListItem(); li.Text = item; dd.Items.Add(li)
            dd.SelectedIndex = min(prev, len(items) - 1)

    def _dd_val(self, dd):
        """Safe DropDown value reader — SelectedItem doesn't exist in Rhino 8 CPython."""
        idx = dd.SelectedIndex
        if 0 <= idx < dd.Items.Count:
            return dd.Items[idx].Text
        return ""

    def _get_target_layers(self, dd):
        text = self._dd_val(dd)
        return self._avail_layers if (not text or text == "All layers") else [text]

    def _active_tab(self):
        page = self._tabs.SelectedPage
        return page.Text if page else "Room"

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_select_voxels(self, s, e):
        """Read pre-selected objects from viewport and build voxel dict."""
        guids = rs.SelectedObjects()

        if not guids:
            self._set_status(
                u"● No objects selected \u2014 select voxels in viewport first, "
                u"then click this button.", False)
            print(">>> TIP: window-select your voxels in the viewport, "
                  "then click 'Load Selected Voxels'.")
            return

        self._set_status("Processing {} selected objects…".format(len(guids)))
        try:
            vd, vs, skipped = load_voxels_from_ids(guids)
            if not vd:
                self._set_status(
                    u"● 0 valid voxels from {} selected. "
                    u"Need closed solid BREPs/Extrusions. ({} skipped)".format(
                        len(guids), skipped), False)
                return

            self._voxels_dict = vd
            self._voxel_size  = vs
            compute_adjacency(self._voxels_dict)

            self._avail_layers = list({v.layer for v in self._voxels_dict.values()})
            self._refresh_layer_dropdowns()

            # Per-layer count string
            by_layer = {}
            for v in self._voxels_dict.values():
                short = v.layer.split("::")[-1]
                by_layer[short] = by_layer.get(short, 0) + 1
            layer_str = "  ".join("{}({})".format(n, c)
                                   for n, c in sorted(by_layer.items()))
            skip_note = "  [{} skipped]".format(skipped) if skipped else ""

            self._layers_lbl.Text = u"{} voxels \u2014 {}{}".format(
                len(self._voxels_dict), layer_str, skip_note)
            self._size_lbl.Text = "Voxel size (auto): {:.1f}".format(self._voxel_size)
            self._update_prereqs()
            self._set_status(u"● \u2460 Done: {} voxels loaded. Now \u2461 configure a mode and \u2462 Apply.".format(
                len(self._voxels_dict)), True)
        except Exception as ex:
            self._set_status("Selection error: " + str(ex), False)
            print(traceback.format_exc())

    def _on_debug(self, s, e):
        """Print detailed voxel stats to Rhino command line for troubleshooting."""
        if not self._voxels_dict:
            print("=== No voxels loaded ===")
            print("Click 'Select Voxels in Viewport' first.")
            return
        print("=== VOXEL FIELD DEBUG INFO ===")
        print("Total voxels: {}".format(len(self._voxels_dict)))
        print("Voxel size (auto): {:.3f}".format(self._voxel_size))

        by_layer = {}
        for v in self._voxels_dict.values():
            by_layer.setdefault(v.layer, []).append(v)
        print("\nPer-layer breakdown:")
        for layer, voxels in sorted(by_layer.items()):
            short = layer.split("::")[-1]
            print("  {} : {} voxels".format(short, len(voxels)))

        face_counts = {}
        for v in self._voxels_dict.values():
            for ft in v.face_types.values():
                face_counts[ft] = face_counts.get(ft, 0) + 1
        print("\nFace type counts:")
        for ft, cnt in sorted(face_counts.items()):
            print("  {} : {}".format(ft, cnt))

        all_i = [ijk[0] for ijk in self._voxels_dict]
        all_j = [ijk[1] for ijk in self._voxels_dict]
        all_k = [ijk[2] for ijk in self._voxels_dict]
        print("\nGrid extents: X[{},{}] Y[{},{}] Z[{},{}]".format(
            min(all_i), max(all_i), min(all_j), max(all_j), min(all_k), max(all_k)))

        stacks = {}
        for v in self._voxels_dict.values():
            ij = (v.grid_ijk[0], v.grid_ijk[1])
            stacks.setdefault(ij, []).append(v)
        vert_stacks = sum(1 for sv in stacks.values() if len(sv) >= 2)
        print("\nVertical stacks (>=2 voxels same XY): {}".format(vert_stacks))
        print("=== END ===")
        self._set_status("● Debug info printed to Rhino command line.", True)

    def _update_prereqs(self):
        """Update all prerequisite labels with current ✓/✗ state."""
        has_v = bool(self._voxels_dict)
        n     = len(self._voxels_dict)
        v_ok  = u"\u2713 {} voxels selected".format(n) if has_v else u"\u2717 Voxels not selected"
        v_col = edrawing.Color.FromArgb(80, 190, 80) if has_v else edrawing.Color.FromArgb(220, 80, 80)

        # Room
        self._room_prereq.Text      = v_ok
        self._room_prereq.TextColor = v_col

        # Facade
        has_fs = self._facade_src is not None
        fs_ok  = u"\u2713 Source element" if has_fs else u"\u2717 No source element \u2192 click Pick Element"
        self._facade_prereq.Text = u"{}   {}".format(v_ok, fs_ok)
        self._facade_prereq.TextColor = (edrawing.Color.FromArgb(80, 190, 80)
                                          if (has_v and has_fs) else edrawing.Color.FromArgb(220, 80, 80))

        # Structure
        self._struct_prereq.Text      = v_ok
        self._struct_prereq.TextColor = v_col

        # Ornament
        has_os = self._orn_src is not None
        has_at = bool(self._attractor_geos)
        os_ok  = u"\u2713 Element" if has_os else u"\u2717 Element"
        at_ok  = u"\u2713 Attractor" if has_at else u"\u2717 Attractor"
        self._orn_prereq.Text = u"{}   {}   {}".format(v_ok, os_ok, at_ok)
        self._orn_prereq.TextColor = (edrawing.Color.FromArgb(80, 190, 80)
                                       if (has_v and has_os and has_at) else edrawing.Color.FromArgb(220, 80, 80))

        # Circulation
        self._circ_prereq.Text      = v_ok
        self._circ_prereq.TextColor = v_col

        # Discrete
        has_da = self._disc_src_a is not None
        da_ok  = (u"\u2713 Element A" if has_da
                  else u"\u2717 No Element A \u2192 select in viewport, then Load")
        self._disc_prereq.Text = u"{}   {}".format(v_ok, da_ok)
        self._disc_prereq.TextColor = (edrawing.Color.FromArgb(80, 190, 80)
                                       if (has_v and has_da) else edrawing.Color.FromArgb(220, 80, 80))

    def _pre_check(self, tab):
        """Return (ok, hint) before dispatching Apply."""
        if not self._voxels_dict:
            return False, u"\u2460 First: click \u25b6 Select Voxels in Viewport"
        if tab == "Facade" and not self._facade_src:
            return False, u"Facade \u2192 select element(s) in viewport, then 'Load Selected as Element'"
        if tab == "Ornament" and not self._orn_src:
            return False, u"Ornament \u2192 select element(s) in viewport, then 'Load Selected as Element'"
        if tab == "Discrete" and not self._disc_src_a:
            return False, u"Discrete \u2192 select Element A in viewport, then 'Load as Element A'"
        if tab == "Discrete Room cluster" and not getattr(self, "_rc_src_a", None):
            return False, u"Discrete Room cluster \u2192 select Element A in viewport, then 'Load as Element A'"
        # attractor is optional in Ornament — no block here
        return True, ""

    def _hide_for_pick(self):
        self.Visible = False

    def _show_after_pick(self):
        self.Visible = True

    def _obj_type_tag(self, obj_id):
        """Return short type string for display, e.g. '[Brep]' '[Mesh]'."""
        obj = sc.doc.Objects.FindId(obj_id)
        if not obj:
            return ""
        t = obj.ObjectType
        tags = {rd.ObjectType.Brep: "[Brep]", rd.ObjectType.Mesh: "[Mesh]",
                rd.ObjectType.Extrusion: "[Extrusion]", rd.ObjectType.SubD: "[SubD]"}
        return tags.get(t, "[?]")

    def _load_selected_as_src(self, attr_name, lbl_widget, kind):
        """Pre-selection loader for source element (facade / ornament).
        Select objects in viewport first, then click the button.
        Stores a list of GUIDs so mesh groups are fully supported.
        """
        guids = rs.SelectedObjects()
        if not guids:
            self._set_status(
                u"● Select your {} element(s) in the viewport first, "
                u"then click this button.".format(kind), False)
            print(">>> TIP: select your {} element(s) in the viewport, "
                  "then click 'Load Selected as Element'.".format(kind))
            return
        setattr(self, attr_name, list(guids))
        count = len(guids)
        lbl_widget.Text = u"\u2713 {} object(s) loaded as {} source".format(count, kind)
        print(u"\u2713 {} source: {} object(s) loaded.".format(kind, count))
        self._update_prereqs()

    def _on_pick_facade(self, s, e):
        self._load_selected_as_src("_facade_src", self._facade_src_lbl, "Facade")

    def _on_pick_facade_b(self, s, e):
        self._load_selected_as_src("_facade_src_b", self._facade_src_b_lbl, "Facade B")

    def _on_pick_facade_c(self, s, e):
        self._load_selected_as_src("_facade_src_c", self._facade_src_c_lbl, "Facade C")

    def _on_pick_orn(self, s, e):
        self._load_selected_as_src("_orn_src", self._orn_src_lbl, "Ornament")

    def _on_pick_orn_b(self, s, e):
        self._load_selected_as_src("_orn_src_b", self._orn_src_b_lbl, "Ornament B")

    def _on_pick_orn_c(self, s, e):
        self._load_selected_as_src("_orn_src_c", self._orn_src_c_lbl, "Ornament C")

    def _on_pick_struct_col(self, s, e):
        self._load_selected_as_src("_struct_src_col", self._struct_col_lbl, "Column A")

    def _on_clear_struct_col(self, s, e):
        self._struct_src_col = None
        self._struct_col_lbl.Text = u"None \u2014 procedural box column"

    def _on_pick_struct_col_b(self, s, e):
        self._load_selected_as_src("_struct_src_col_b", self._struct_col_b_lbl, "Column B")

    def _on_clear_struct_col_b(self, s, e):
        self._struct_src_col_b = None
        self._struct_col_b_lbl.Text = u"None \u2014 placed at same position as Column"

    def _on_pick_struct_beam(self, s, e):
        self._load_selected_as_src("_struct_src_beam", self._struct_beam_lbl, "Beam")

    def _on_clear_struct_beam(self, s, e):
        self._struct_src_beam = None
        self._struct_beam_lbl.Text = u"None \u2014 procedural box beam"

    def _on_pick_disc_a(self, s, e):
        self._load_selected_as_src("_disc_src_a", self._disc_src_a_lbl, "Discrete A")

    def _on_pick_disc_b(self, s, e):
        self._load_selected_as_src("_disc_src_b", self._disc_src_b_lbl, "Discrete B")

    def _on_pick_disc_c(self, s, e):
        self._load_selected_as_src("_disc_src_c", self._disc_src_c_lbl, "Discrete C")

    def _on_pick_disc_d(self, s, e):
        self._load_selected_as_src("_disc_src_d", self._disc_src_d_lbl, "Discrete D")

    def _on_pick_disc_e(self, s, e):
        self._load_selected_as_src("_disc_src_e", self._disc_src_e_lbl, "Discrete E")

    def _on_pick_disc_f(self, s, e):
        self._load_selected_as_src("_disc_src_f", self._disc_src_f_lbl, "Discrete F")

    def _on_pick_attractor_pt(self, s, e):
        """Let the user pick a single point in Rhino for the Attractor gradient filter."""
        try:
            import Rhino
            gp = Rhino.Input.Custom.GetPoint()
            gp.SetCommandPrompt("Pick attractor point for Attractor gradient voxel filter")
            result = gp.Get()
            if result == Rhino.Input.GetResult.Point:
                self._disc_attractor_pt = gp.Point()
                self._disc_attr_lbl.Text = u"({:.1f}, {:.1f}, {:.1f})".format(
                    self._disc_attractor_pt.X,
                    self._disc_attractor_pt.Y,
                    self._disc_attractor_pt.Z)
            else:
                self._disc_attr_lbl.Text = u"Cancelled — no point picked"
        except Exception as ex:
            self._disc_attr_lbl.Text = u"Error: {}".format(ex)

    # ── Solar event handlers ───────────────────────────────────────────────────

    def _on_browse_epw(self, s, e):
        try:
            import Rhino.UI as _rui
            fd = _rui.OpenFileDialog()
            fd.Filter = "EPW Weather Files (*.epw)|*.epw|All files (*.*)|*.*"
            fd.Title  = "Select EPW Weather File"
            if fd.ShowDialog() == True:
                self._solar_epw_path = fd.FileName
                self._solar_epw_lbl.Text = self._solar_epw_path
        except Exception as ex:
            self._solar_epw_lbl.Text = u"Error opening dialog: {}".format(ex)

    def _on_load_peak_sun(self, s, e):
        """
        Load the EPW peak sun direction into Solar shield az/alt spinners.
        Uses sc.sticky["voxelgen_solar_peak_sun"] written by _do_solar_bake().
        Falls back to parsing the EPW directly if sticky has no data yet.
        """
        try:
            peak = sc.sticky.get("voxelgen_solar_peak_sun")
            if peak is None:
                # Try to parse EPW directly for peak DNI hour
                epw = self._solar_epw_path
                import os
                if epw and os.path.isfile(epw):
                    lat, _, _, rows = _parse_epw(epw)
                    best = max((r for r in rows if r["dni"] > 0),
                               key=lambda r: r["dni"], default=None)
                    if best:
                        pos = _sun_position(lat, best["month"], best["day"], best["hour"])
                        if pos:
                            peak = pos
                            sc.sticky["voxelgen_solar_peak_sun"] = peak
                if peak is None:
                    if self._disc_sun_status:
                        self._disc_sun_status.Text = (
                            u"\u2717 No bake data and no EPW path. Run bake first.")
                        self._disc_sun_status.TextColor = edrawing.Color.FromArgb(220, 80, 80)
                    return

            alt_d, az_d = peak
            if self._disc_sun_az:
                self._disc_sun_az.Value  = round(az_d  / 5) * 5   # snap to 5° grid
            if self._disc_sun_alt:
                self._disc_sun_alt.Value = round(alt_d / 5) * 5
            if self._disc_sun_status:
                self._disc_sun_status.Text = (
                    u"\u2714 Peak sun loaded: az={:.0f}\u00b0  alt={:.0f}\u00b0  "
                    u"| Now set Place at \u2192 'Solar high zones'".format(az_d, alt_d))
                self._disc_sun_status.TextColor = edrawing.Color.FromArgb(80, 190, 80)
        except Exception as ex:
            if self._disc_sun_status:
                self._disc_sun_status.Text = u"\u2717 Error: {}".format(ex)
                self._disc_sun_status.TextColor = edrawing.Color.FromArgb(220, 80, 80)

    def _on_pick_solar_chart_origin(self, s, e):
        try:
            import Rhino
            gp = Rhino.Input.Custom.GetPoint()
            gp.SetCommandPrompt("Pick solar chart origin point")
            result = gp.Get()
            if result == Rhino.Input.GetResult.Point:
                self._solar_chart_origin = gp.Point()
                self._solar_status.Text = u"Chart origin: ({:.1f}, {:.1f}, {:.1f})".format(
                    self._solar_chart_origin.X,
                    self._solar_chart_origin.Y,
                    self._solar_chart_origin.Z)
        except Exception as ex:
            self._solar_status.Text = u"Error: {}".format(ex)

    def _on_solar_bake(self, s, e):
        try:
            self._do_solar_bake(draw_chart=bool(self._solar_chart_cb.Checked))
        except Exception as ex:
            self._solar_status.Text = u"\u2717 Error: {}".format(ex)
            import traceback; traceback.print_exc()

    def _on_solar_chart_only(self, s, e):
        try:
            self._do_solar_bake(draw_chart=True, bake_voxels=False)
        except Exception as ex:
            self._solar_status.Text = u"\u2717 Error: {}".format(ex)
            import traceback; traceback.print_exc()

    def _do_solar_bake(self, draw_chart=True, bake_voxels=True):
        """
        Orchestrate EPW solar analysis:
        1. Parse EPW and compute per-voxel radiation with shadow casting
        2. Colour voxels into 5 output layers
        3. Draw stereographic sun path chart with shading frequency overlay
        """
        if not self._voxels_dict:
            self._solar_status.Text = u"\u2717 No voxels loaded — select voxels first."
            return

        epw_path = self._solar_epw_path
        if not epw_path:
            self._solar_status.Text = u"\u2717 No EPW file selected."
            return

        import os
        if not os.path.isfile(epw_path):
            self._solar_status.Text = u"\u2717 EPW file not found:\n  {}".format(epw_path)
            return

        use_occlusion = bool(self._solar_occlusion_cb.Checked)
        key_hours     = bool(self._solar_key_hours_cb.Checked)
        thresh_5      = float(self._solar_thresh_5.Value)
        thresh_4      = float(self._solar_thresh_4.Value)
        thresh_3      = float(self._solar_thresh_3.Value)
        thresh_2      = float(self._solar_thresh_2.Value)
        chart_radius  = float(self._solar_chart_radius.Value)

        mode_str = "shadow+EPW" if use_occlusion else "EPW no-shadow"
        hr_str   = "key-hours" if key_hours else "8760h"
        self._solar_status.Text = u"\u23f3 Computing {} {}...".format(mode_str, hr_str)
        sc.doc.Views.Redraw()

        # ── Step 1: compute solar radiation + shadow casting ─────────────────
        if bake_voxels:
            tier_map, sun_pts = _bake_solar_voxels(
                self._voxels_dict, epw_path,
                use_occlusion=use_occlusion,
                key_hours_only=key_hours,
                thresh_crit=thresh_5, thresh_high=thresh_4,
                thresh_med=thresh_3,  thresh_low=thresh_2)

            # ── Persist tier map to sc.sticky so Solar shield Place-at can read it ──
            if tier_map:
                sc.sticky["voxelgen_solar_tiers"] = tier_map
                # Store peak sun direction (hour with max DNI) for auto-fill
                lat_s, _, _, hourly_s = _parse_epw(epw_path)
                best_row = max(
                    (r for r in hourly_s if r["dni"] > 0),
                    key=lambda r: r["dni"], default=None)
                if best_row:
                    peak_pos = _sun_position(lat_s, best_row["month"],
                                             best_row["day"], best_row["hour"])
                    if peak_pos:
                        sc.sticky["voxelgen_solar_peak_sun"] = peak_pos  # (alt, az)
                        print(">>> Solar peak sun stored: alt={:.1f}° az={:.1f}°  "
                              "DNI={:.0f} W/m²".format(
                                  peak_pos[0], peak_pos[1], best_row["dni"]))
                print(">>> Solar tier map stored in sc.sticky for 'Solar high zones' filter.")
                # Update the Solar shield sub-panel status hint
                if self._disc_sun_panel:
                    peak = sc.sticky.get("voxelgen_solar_peak_sun")
                    if peak:
                        self._solar_status.Text = (
                            u"\u2714 Bake complete. Peak sun: alt={:.0f}\u00b0 az={:.0f}\u00b0  "
                            u"| Click '\U0001f4e5 Load peak sun' in Solar shield to auto-fill.".format(
                                peak[0], peak[1]))
        else:
            # Chart-only: still need sun positions → parse EPW
            lat, lon, tz, hourly_rows = _parse_epw(epw_path)
            sun_pts = []
            for row in hourly_rows:
                if row["dni"] < 1.0: continue
                pos = _sun_position(lat, row["month"], row["day"], row["hour"])
                if pos is None: continue
                alt_d, az_d = pos
                if alt_d > 0:
                    sun_pts.append({"month": row["month"], "day": row["day"],
                                    "hour": row["hour"],
                                    "alt": alt_d, "az": az_d,
                                    "dni": row["dni"], "ghi": row["ghi"]})
            tier_map = {}

        # ── Step 2: bake voxels to output layers ─────────────────────────────
        if bake_voxels and tier_map:
            # Ensure all 5 solar layers exist
            for key in ("Solar_5_CritHigh","Solar_4_High","Solar_3_Med",
                        "Solar_2_Low","Solar_1_Shade"):
                ensure_output_layer(key)

            tier_counts = {}
            for ijk, tier in tier_map.items():
                vox = self._voxels_dict.get(ijk)
                if vox is None: continue
                layer_name = ensure_output_layer(tier)
                # Copy voxel brep to solar layer (keep original in place)
                obj = sc.doc.Objects.FindId(vox.guid) if hasattr(vox, "guid") else None
                if obj is not None:
                    brep = obj.Geometry
                    if brep:
                        new_attr = obj.Attributes.Duplicate()
                        li = sc.doc.Layers.FindName(layer_name)
                        if li:
                            new_attr.LayerIndex = li.Index
                        sc.doc.Objects.AddBrep(brep, new_attr)
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

            summary = u"  |  ".join(
                u"{}: {}v".format(k.replace("Solar_",""), v)
                for k, v in sorted(tier_counts.items(), reverse=True))
            self._solar_status.Text = u"\u2714 Baked {} voxels \u2014 {}".format(
                len(tier_map), summary)
        elif bake_voxels:
            self._solar_status.Text = u"\u2717 No voxels classified — check EPW path."
            return

        # ── Step 3: shading frequency per sun position ────────────────────────
        vox_shade_freq = None
        if use_occlusion and bake_voxels and self._voxels_dict:
            # Compute fraction of field in shadow for each unique sun bucket
            from collections import defaultdict
            lat, lon, tz, _ = _parse_epw(epw_path)   # re-read location header only
            buckets  = defaultdict(list)   # (az_b, alt_b) → [is_shaded, ...]
            for row in _parse_epw(epw_path)[3]:
                if row["dni"] < 1.0: continue
                pos = _sun_position(lat, row["month"], row["day"], row["hour"])
                if pos is None: continue
                alt_d, az_d = pos
                if alt_d <= 2.0: continue
                az_b  = int(round(az_d  / 5.0)) * 5
                alt_b = int(round(alt_d / 5.0)) * 5
                sv   = _sun_vec_from_alt_az(alt_d, az_d)
                step = (sv.X, sv.Y, sv.Z)
                n_shaded = sum(1 for ijk in self._voxels_dict
                               if _shadow_march(ijk, step, self._voxels_dict))
                total = len(self._voxels_dict)
                buckets[(az_b, alt_b)].append(n_shaded / max(total, 1))
            vox_shade_freq = {k: sum(v)/len(v) for k, v in buckets.items() if v}

        # ── Step 4: draw solar chart ──────────────────────────────────────────
        if draw_chart and sun_pts:
            # Re-read lat for chart
            lat, _, _, _ = _parse_epw(epw_path)
            # Chart origin: user-picked or auto-position (50m east of field centroid)
            if self._solar_chart_origin:
                chart_pt = self._solar_chart_origin
            else:
                all_vox = list(self._voxels_dict.values())
                cx = sum(v.center.X for v in all_vox) / len(all_vox)
                cy = sum(v.center.Y for v in all_vox) / len(all_vox)
                cz = min(v.center.Z for v in all_vox)
                chart_pt = rg.Point3d(cx + 50.0 + chart_radius, cy, cz)

            guids = _draw_solar_chart(
                lat, sun_pts, chart_pt,
                chart_radius=chart_radius,
                vox_shade_freq=vox_shade_freq)

            chart_status = u"  |  Chart: {} objects on VOXELGEN_Solar_Chart".format(len(guids))
            if bake_voxels:
                self._solar_status.Text += chart_status
            else:
                self._solar_status.Text = u"\u2714 Solar chart drawn ({} objects){}.".format(
                    len(guids), u"  with shading freq" if vox_shade_freq else "")

        sc.doc.Views.Redraw()

    def _on_clear_disc_d(self, s, e):
        self._disc_src_d = None
        self._disc_src_d_lbl.Text = u"Element D  (optional) \u2014 select \u2192"

    def _on_clear_disc_e(self, s, e):
        self._disc_src_e = None
        self._disc_src_e_lbl.Text = u"Element E  (optional) \u2014 select \u2192"

    def _on_clear_disc_f(self, s, e):
        self._disc_src_f = None
        self._disc_src_f_lbl.Text = u"Element F  (optional) \u2014 select \u2192"

    def _on_clear_disc_a(self, s, e):
        self._disc_src_a = None
        self._disc_src_a_lbl.Text = u"Element A  (required) \u2014 select \u2192"
        self._update_prereqs()

    def _on_clear_disc_b(self, s, e):
        self._disc_src_b = None
        self._disc_src_b_lbl.Text = u"Element B  (optional) \u2014 select \u2192"
        self._update_prereqs()

    def _on_clear_disc_c(self, s, e):
        self._disc_src_c = None
        self._disc_src_c_lbl.Text = u"Element C  (optional) \u2014 select \u2192"
        self._update_prereqs()

    def _on_rand_cluster_seed(self, s, e):
        import random as _r
        self._disc_cluster_seed.Value = _r.randint(0, 9999)

    def _on_rand_rand_seed(self, s, e):
        import random as _r
        self._disc_rand_seed.Value = _r.randint(0, 9999)

    def _on_room_cluster_generate(self, s, e):
        """'Generate Room Clusters' button — triggers Room Cluster mode directly."""
        ok, hint = self._pre_check("Discrete")
        if not ok:
            self._set_status(u"\u25cf " + hint, False)
            return
        self._set_status(u"\u2462 Room Cluster: classifying voxels\u2026")
        rs.EnableRedraw(False)
        undo_id = sc.doc.BeginUndoRecord("DVC_RoomCluster")
        try:
            self._do_room_cluster()
        except Exception as ex:
            self._set_status(u"\u25cf Room Cluster error: {}".format(ex), False)
            import traceback; traceback.print_exc()
        finally:
            sc.doc.EndUndoRecord(undo_id)
            rs.EnableRedraw(True)
            sc.doc.Views.Redraw()

    def _refresh_climate_status(self):
        """Update the climate status label to reflect current sc.sticky state."""
        import scriptcontext as _sc
        has_data = bool(_sc.sticky.get("comfort_data"))
        self._disc_climate_path_lbl.Text = (
            u"\u2705 comfort_data ready in sc.sticky" if has_data
            else u"\u26a0 No comfort data \u2014 run Climate Comfort Agent V2 first")
        self._disc_climate_path_lbl.TextColor = (
            edrawing.Color.FromArgb(80, 190, 80) if has_data else edrawing.Color.FromArgb(220, 80, 80))

    def _do_climate_response(self, geos_a, geos_b, geos_c, layers,
                             span, placement, orientation, scale_fit, orient_strength,
                             geos_d=None, geos_e=None, geos_f=None):    # V16
        """
        Classify all targeted voxels into 5 climate zones, then run
        apply_discrete_mode once per zone with zone-specific parameters.
        Reports total counts per zone in the status label.
        """
        all_vox = _target_voxels(self._voxels_dict, layers)
        if not all_vox:
            self._set_status(u"● Climate Response: no voxels found in target layers.", False)
            return

        zones = _classify_voxels_by_climate(all_vox)

        c_seed = int(self._disc_cluster_seed.Value)
        r_seed = int(self._disc_rand_seed.Value)

        # V16 — extended fallback chain for 6 labels
        _b = geos_b or geos_a
        _c = geos_c or _b
        _d = geos_d or _c
        _e = geos_e or _d
        _f = geos_f or _e
        src_map = {"A": geos_a, "B": _b, "C": _c, "D": _d, "E": _e, "F": _f}

        total = 0
        report_parts = []
        for zone in CLIMATE_ZONES:
            zone_voxels = zones.get(zone, [])
            if not zone_voxels:
                continue

            depth_val   = int(self._disc_clim_depth[zone].Value)
            place_val   = self._dd_val(self._disc_clim_place[zone])
            elem_label  = self._dd_val(self._disc_clim_element[zone])
            out_layer   = CLIMATE_ZONE_LAYERS[zone]

            # Build a sub-dict so apply_discrete_mode targets this zone only
            zone_dict = {v.grid_ijk: v for v in zone_voxels}

            # Pick element list for this zone
            src_a_zone = src_map[elem_label]
            src_b_zone = None   # single-element per zone (cleaner output)
            src_c_zone = None

            n = apply_discrete_mode(
                zone_dict, None,           # None → no layer filter (all zone voxels)
                src_a_zone, src_b_zone, src_c_zone,
                "Random mix", span, placement, orientation,
                scale_fit, place_val, c_seed, r_seed,
                interlocking=False,
                constrain_to_field=False, field_margin=0.5,
                orient_strength=orient_strength,
                invert_place_at=False,
                shell_depth=depth_val,
                _output_layer_override=out_layer,
            )
            total += n
            zone_label = zone.replace("_", " ").title()
            report_parts.append(u"{}={} obj".format(zone_label, n))

        self._disc_clim_status.Text = u"  ".join(report_parts)
        self._set_status(
            u"\u25cf Climate Response: {} objects  [{}]".format(
                total, u" | ".join(report_parts)))

    def _do_room_cluster(self):
        """Room Cluster mode.

        1. Classify all loaded voxels into spatially-connected clusters via BFS.
        2. For each cluster, find the outer shell (depth N rings).
        3. Apply Discrete Element A/B/C to those shell voxels only.
        All output lands on the VOXELGEN_Cluster_Shell layer.
        """
        if not self._disc_src_a:
            self._set_status(
                u"\u25cf Room Cluster \u2192 select Element A in viewport, "
                u"then click 'Load as Element A'.", False)
            return

        geos_a = self._get_geos(self._disc_src_a, "Discrete A")
        if not geos_a:
            return
        geos_b = self._get_geos(self._disc_src_b, "Discrete B") if self._disc_src_b else None
        geos_c = self._get_geos(self._disc_src_c, "Discrete C") if self._disc_src_c else None
        geos_d = self._get_geos(self._disc_src_d, "Discrete D") if self._disc_src_d else None   # V16
        geos_e = self._get_geos(self._disc_src_e, "Discrete E") if self._disc_src_e else None   # V16
        geos_f = self._get_geos(self._disc_src_f, "Discrete F") if self._disc_src_f else None   # V16

        if not self._voxels_dict:
            self._set_status(u"\u25cf Room Cluster: no voxels loaded.", False)
            return

        shell_depth  = int(self._clust_shell_depth.Value)
        assign_mode  = self._dd_val(self._clust_assign_dd)

        # Reuse Discrete tab params for placement style
        placement    = self._dd_val(self._disc_place_dd)
        orientation  = self._dd_val(self._disc_orient_dd)
        scale_fit    = bool(self._disc_scale.Checked)
        orient_str   = float(self._disc_orient_strength.Value)
        c_seed       = int(self._disc_cluster_seed.Value)
        r_seed       = int(self._disc_rand_seed.Value)

        # 1. Classify connected clusters
        self._set_status(u"\u2462 Room Cluster: BFS clustering\u2026")
        clusters = _classify_voxel_clusters(self._voxels_dict)
        if not clusters:
            self._set_status(u"\u25cf Room Cluster: no clusters found.", False)
            return

        out_key   = "Cluster_Shell"
        out_layer = OUTPUT_LAYERS[out_key][0]

        # Helper: resolve effective element list for an assignment slot
        _resolve = lambda ga, gb, gc: (ga, gb, gc)
        src_cycle = [
            geos_a,
            geos_b if geos_b else geos_a,
            geos_c if geos_c else (geos_b if geos_b else geos_a),
        ]

        total_placed = 0
        parts        = []

        for cid, ijk_list in clusters.items():
            # 2. Get outer shell voxels for this cluster
            shell_dict = _get_cluster_shell(ijk_list, self._voxels_dict, shell_depth)
            if not shell_dict:
                continue

            # 3. Determine element(s) for this cluster
            if assign_mode == u"Cycle A\u2192B\u2192C per cluster":
                eff_a = src_cycle[cid % 3]
                eff_b = None
                eff_c = None
                a_rule = "Random mix"
            elif assign_mode == u"Element A only":
                eff_a, eff_b, eff_c = geos_a, None, None
                a_rule = "Random mix"
            elif assign_mode == u"Element B only":
                eff_a, eff_b, eff_c = geos_b or geos_a, None, None
                a_rule = "Random mix"
            elif assign_mode == u"Element C only":
                eff_a, eff_b, eff_c = geos_c or geos_b or geos_a, None, None
                a_rule = "Random mix"
            else:  # "Mix A/B/C (random)"
                eff_a, eff_b, eff_c = geos_a, geos_b, geos_c
                a_rule = "Random mix"

            # 4. Apply discrete elements to shell voxels (V16: pass D/E/F too)
            n = apply_discrete_mode(
                shell_dict, None,          # None = no layer filter (already a sub-dict)
                eff_a, eff_b, eff_c,
                a_rule,
                1,                         # span=1 (single voxel)
                placement, orientation,
                scale_fit,
                "All voxels",              # place_at: all shell voxels qualify
                c_seed + cid, r_seed + cid,
                src_geos_d=geos_d, src_geos_e=geos_e, src_geos_f=geos_f,
                interlocking=False,
                constrain_to_field=False, field_margin=0.5,
                orient_strength=orient_str,
                invert_place_at=False,
                shell_depth=1,             # inner filter already done above
                _output_layer_override=out_layer,
            )
            total_placed += n
            parts.append(u"C{}={}".format(cid, n))

        summary = u"  ".join(parts) if parts else u"(none)"
        self._clust_status.Text = u"\u2714 {} cluster(s) \u2192 {} objects".format(
            len(clusters), total_placed)
        self._clust_status.TextColor = edrawing.Color.FromArgb(80, 190, 80)
        self._set_status(
            u"\u25cf Room Cluster: {} clusters, {} objects \u2192 {}  [depth={}, {}]".format(
                len(clusters), total_placed, out_layer, shell_depth, summary))

    def _on_pick_attr(self, s, e):
        """Pre-selection attractor loader — any geometry type supported."""
        guids = rs.SelectedObjects()
        if not guids:
            self._set_status(
                u"● Select attractor geometry in viewport first "
                u"(point, curve, surface, mesh…), then click this button.", False)
            print(">>> TIP: select any geometry as attractor, then click 'Load Selected as Attractor'.")
            return
        raw_geos = [self._raw_geo(g) for g in guids if self._raw_geo(g) is not None]
        if not raw_geos:
            self._set_status(u"● Selected attractor objects have no geometry.", False)
            return
        self._attractor_geos = raw_geos
        type_names = list({type(g).__name__ for g in raw_geos})
        self._orn_attr_lbl.Text = u"\u2713 Attractor: {} obj ({})".format(
            len(raw_geos), ", ".join(type_names))
        print(u"\u2713 Attractor: {} object(s) loaded — types: {}".format(
            len(raw_geos), ", ".join(type_names)))
        self._update_prereqs()

    def _on_apply(self, s, e):
        tab = self._active_tab()
        ok, hint = self._pre_check(tab)
        if not ok:
            self._set_status(u"● " + hint, False)
            return

        self._set_status(u"\u2462 Applying {}…".format(tab))
        rs.EnableRedraw(False)
        undo_id = sc.doc.BeginUndoRecord("DVC_" + tab)

        try:
            if   tab == "Room":                    self._do_room()
            elif tab == "Facade":                  self._do_facade()
            elif tab == "Structure":               self._do_structure()
            elif tab == "Ornament":                self._do_ornament()
            elif tab == "Circulation":             self._do_circulation()
            elif tab == "Discrete":                self._do_discrete()
            elif tab == "Discrete Room cluster":   self._do_room_cluster_tab()
        except Exception as ex:
            self._set_status("Error: " + str(ex), False)
            print(traceback.format_exc())
        finally:
            sc.doc.EndUndoRecord(undo_id)
            rs.EnableRedraw(True)
            sc.doc.Views.Redraw()

    def _on_clear(self, s, e):
        try:
            tab = self._active_tab()
            # "Discrete Room cluster" is not a key in OUTPUT_LAYERS — handle separately
            if tab == "Discrete Room cluster":
                clear_output_layer("Cluster_Shell")
                self._set_status(u"● {} output cleared.".format(tab), True)
                sc.doc.Views.Redraw()
                return
            clear_output_layer(tab)
            if tab == "Discrete":
                for sub in ("Discrete_A", "Discrete_B", "Discrete_C",
                            "Discrete_D", "Discrete_E", "Discrete_F",
                            "Discrete_ClimHot", "Discrete_ClimWarm", "Discrete_ClimMid",
                            "Discrete_ClimPassive", "Discrete_ClimWind"):
                    clear_output_layer(sub)
            self._set_status(u"● {} output cleared.".format(tab), True)
            sc.doc.Views.Redraw()
        except Exception as ex:
            self._set_status("Clear error: " + str(ex), False)

    # ── Live mode handlers ────────────────────────────────────────────────────

    def _on_live_toggle(self, s, e):
        """Live checkbox toggled: update visual colour and stop timer if turning off."""
        on = bool(self._live_cb.Checked)
        self._live_cb.TextColor = (
            edrawing.Color.FromArgb(80, 220, 80) if on
            else edrawing.Color.FromArgb(110, 110, 110))
        if not on:
            self._live_timer.Stop()

    def _on_live_param_changed(self, s, e):
        """Any wired parameter changed: restart debounce timer if Live is ON."""
        if self._live_cb.Checked:
            self._live_timer.Stop()
            self._live_timer.Start()

    def _on_live_tick(self, s, e):
        """Debounce timer elapsed: clear previous output then re-apply."""
        self._live_timer.Stop()
        self._on_clear(None, None)
        self._on_apply(None, None)

    # ── mode dispatchers ──────────────────────────────────────────────────────

    def _do_room(self):
        layers    = self._get_target_layers(self._room_layer_dd)
        wwr       = int(self._room_wwr_sl.Value)
        side      = self._dd_val(self._room_side_dd)
        slab_t    = float(self._room_slab.Value)
        dist_type = self._dd_val(self._room_dist_dd)
        min_sz    = int(self._room_min_sl.Value)
        max_sz    = int(self._room_max_sl.Value)
        seed      = int(self._room_seed.Value)
        place_at  = self._dd_val(self._room_place_dd)
        n, nr     = apply_room_mode(self._voxels_dict, layers, wwr, side, slab_t,
                                    dist_type=dist_type, min_sz=min_sz,
                                    max_sz=max_sz, rand_seed=seed,
                                    place_at=place_at)
        self._set_status(u"● Room: {} elements  \u2014  {} rooms  [{} | seed {}]".format(
            n, nr, dist_type, seed))

    def _raw_geo(self, obj_id):
        """Return raw geometry from a GUID (no conversion). None if not found."""
        obj = sc.doc.Objects.FindId(obj_id)
        return obj.Geometry if obj else None

    def _get_geos(self, guid_list, label):
        """
        Return list of raw geometries from a list of GUIDs.
        Accepts any object type — Brep, Mesh, Extrusion, SubD, Curve, etc.
        Reports failure only if list is empty or nothing resolves.
        """
        geos = []
        for guid in guid_list:
            g = self._raw_geo(guid)
            if g is not None:
                geos.append(g)
        if not geos:
            self._set_status(u"● {} \u2014 no valid geometry found.".format(label), False)
        return geos

    def _do_facade(self):
        if not self._facade_src:
            self._set_status(u"● Select element(s) in viewport, then click 'Load Selected as Element'.", False)
            return
        geos = self._get_geos(self._facade_src, "Facade source")
        if not geos:
            return
        layers       = self._get_target_layers(self._facade_layer_dd)
        ff           = self._dd_val(self._facade_face_dd)
        offset       = float(self._facade_offset.Value)
        every        = int(self._facade_every.Value)
        scale        = bool(self._facade_scale.Checked)
        place_at     = self._dd_val(self._facade_place_dd)
        cluster_seed = int(self._facade_cluster_seed.Value)
        geos_b = self._get_geos(self._facade_src_b, "Facade B") if self._facade_src_b else None
        geos_c = self._get_geos(self._facade_src_c, "Facade C") if self._facade_src_c else None
        n = apply_facade_mode(self._voxels_dict, layers, geos, ff, offset, every, scale,
                              place_at=place_at,
                              src_geos_b=geos_b, src_geos_c=geos_c,
                              cluster_seed=cluster_seed)
        self._set_status("● Facade: {} placements ({} obj each).".format(n, len(geos)))

    def _do_structure(self):
        layers  = self._get_target_layers(self._struct_layer_dd)
        mode    = self._dd_val(self._struct_mode_dd)
        pct     = int(self._struct_size.Value)
        place   = self._dd_val(self._struct_place_dd)
        gx      = int(self._struct_gx.Value)
        gy      = int(self._struct_gy.Value)
        gz      = int(self._struct_gz.Value)

        col_geos   = self._get_geos(self._struct_src_col,   "Column A") if self._struct_src_col   else None
        col_geos_b = self._get_geos(self._struct_src_col_b, "Column B") if self._struct_src_col_b else None
        beam_geos  = self._get_geos(self._struct_src_beam,  "Beam")     if self._struct_src_beam  else None

        # Column/Beam/Both always use the grid-spacing custom path
        if mode in ("Column", "Beam", "Both"):
            # "Grid X×Y×Z" → use spinner values; other place_at options → spacing=1
            if place == u"Grid X\u00d7Y\u00d7Z":
                eff_sx, eff_sy, eff_sz = gx, gy, gz
                eff_place = "All voxels"
            else:
                eff_sx, eff_sy, eff_sz = 1, 1, 1
                eff_place = place
            n = apply_structure_mode_custom(
                self._voxels_dict, layers,
                col_geos=col_geos, beam_geos=beam_geos,
                spacing_x=eff_sx, spacing_y=eff_sy, spacing_z=eff_sz,
                struct_mode=mode, profile_pct=pct,
                place_at=eff_place, voxel_size=self._voxel_size,
                col_geos_b=col_geos_b)
        else:
            n = apply_structure_mode(self._voxels_dict, layers, mode, pct, place,
                                     voxel_size=self._voxel_size)
        self._set_status(u"● Structure: {} elements placed.".format(n))

    def _do_ornament(self):
        if not self._orn_src:
            self._set_status(u"● Select element(s) in viewport, then click 'Load Selected as Element'.", False)
            return
        geos = self._get_geos(self._orn_src, "Ornament source")
        if not geos:
            return
        layers          = self._get_target_layers(self._orn_layer_dd)
        effect          = self._dd_val(self._orn_effect_dd)
        face_filter     = self._dd_val(self._orn_face_dd)
        v_min           = float(self._orn_min.Value)
        v_max           = float(self._orn_max.Value)
        invert          = bool(self._orn_invert.Checked)
        auto_scale      = bool(self._orn_scale.Checked)
        density_falloff = bool(self._orn_density_cb.Checked)
        density_min     = int(self._orn_density_sl.Value)
        place_at        = self._dd_val(self._orn_place_dd)
        cluster_seed    = int(self._orn_cluster_seed.Value)
        geos_b = self._get_geos(self._orn_src_b, "Ornament B") if self._orn_src_b else None
        geos_c = self._get_geos(self._orn_src_c, "Ornament C") if self._orn_src_c else None
        n = apply_ornament_mode(
            self._voxels_dict, layers, geos,
            self._attractor_geos or None,
            effect, v_min, v_max, invert, auto_scale,
            density_falloff=density_falloff,
            density_min=density_min,
            face_filter=face_filter,
            place_at=place_at,
            src_geos_b=geos_b, src_geos_c=geos_c,
            cluster_seed=cluster_seed,
        )
        attr_str    = "with attractor" if self._attractor_geos else "no attractor (uniform)"
        density_str = "  density-falloff ON" if density_falloff else ""
        self._set_status(u"● Ornament: {} placements  {}{}  ({} obj each).".format(
            n, attr_str, density_str, len(geos)))

    def _do_circulation(self):
        layers   = self._get_target_layers(self._circ_layer_dd)
        width    = float(self._stair_width.Value)
        rise     = float(self._step_rise.Value)
        run      = float(self._step_run.Value)
        rot_x    = int(self._rot_x_sl.Value)
        mirror   = bool(self._stair_mirror.Checked)
        handrail = bool(self._stair_handrail.Checked)
        place_at = self._dd_val(self._circ_place_dd)
        n = apply_circulation_mode(self._voxels_dict, layers,
                                    width, rise, run, rot_x, mirror, handrail,
                                    place_at=place_at)
        self._set_status("● Circulation: {} step BREPs generated.".format(n))

    def _do_discrete(self):
        if not self._disc_src_a:
            self._set_status(
                u"● Discrete \u2192 select Element A in viewport, "
                u"then click 'Load as Element A'.", False)
            return
        geos_a = self._get_geos(self._disc_src_a, "Discrete A")
        if not geos_a:
            return
        geos_b = self._get_geos(self._disc_src_b, "Discrete B") if self._disc_src_b else None
        geos_c = self._get_geos(self._disc_src_c, "Discrete C") if self._disc_src_c else None
        geos_d = self._get_geos(self._disc_src_d, "Discrete D") if self._disc_src_d else None   # V16
        geos_e = self._get_geos(self._disc_src_e, "Discrete E") if self._disc_src_e else None   # V16
        geos_f = self._get_geos(self._disc_src_f, "Discrete F") if self._disc_src_f else None   # V16

        layers           = self._get_target_layers(self._disc_layer_dd)
        placement        = self._dd_val(self._disc_place_dd)
        orientation      = self._dd_val(self._disc_orient_dd)
        scale_fit        = bool(self._disc_scale.Checked)
        orient_strength  = float(self._disc_orient_strength.Value)
        invert_placement = bool(self._disc_invert_placement.Checked)

        # V7 span: checkbox + stepper replaces old fixed dropdown
        if bool(self._disc_span_cb.Checked):
            span = max(1, int(self._disc_span_num.Value))
        else:
            span = 1

        # Solar shield parameters
        sun_az     = float(self._disc_sun_az.Value)    if self._disc_sun_az    else 180
        sun_alt    = float(self._disc_sun_alt.Value)   if self._disc_sun_alt   else 45
        sun_thresh = float(self._disc_sun_thresh.Value) if self._disc_sun_thresh else 60

        # ── Climate Adaptive Mode (agentic auto-behavior) ─────────────────────
        if bool(self._disc_climate_on.Checked):
            self._do_climate_response(
                geos_a, geos_b, geos_c, layers,
                span, placement, orientation, scale_fit, orient_strength,
                geos_d=geos_d, geos_e=geos_e, geos_f=geos_f)
            return

        # ── Standard manual mode ──────────────────────────────────────────────
        assign       = self._dd_val(self._disc_assign_dd)
        place_at     = self._dd_val(self._disc_vox_place_dd)
        shell_depth  = int(self._disc_shell_depth.Value)
        invert_place = bool(self._disc_invert_place.Checked)
        c_seed       = int(self._disc_cluster_seed.Value)
        r_seed       = int(self._disc_rand_seed.Value)
        constrain    = bool(self._disc_constrain.Checked)
        field_margin = float(self._disc_margin.Value)
        interlocking = bool(self._disc_interlock.Checked)

        # Attractor gradient parameters
        attr_pt     = self._disc_attractor_pt
        attr_radius = float(self._disc_attr_radius.Value) if self._disc_attr_radius else 20.0
        attr_min    = float(self._disc_attr_min.Value)    if self._disc_attr_min    else 0.0
        attr_max    = float(self._disc_attr_max.Value)    if self._disc_attr_max    else 1.0

        # V8 — Cluster placement parameters
        cluster_target = self._dd_val(self._disc_cluster_target)  if self._disc_cluster_target  else "All"
        cluster_faces  = self._dd_val(self._disc_cluster_faces)   if self._disc_cluster_faces   else "All exposed"
        cluster_invert = bool(self._disc_cluster_invert.Checked)  if self._disc_cluster_invert  else False

        # V8 — Sub-Placement mode
        sub_on = bool(self._disc_sub_cb.Checked) if self._disc_sub_cb else False

        # V8 — Resolution mode parameters (mutually exclusive)
        _hi_res_on = bool(self._disc_hi_res_cb.Checked) if self._disc_hi_res_cb else False
        hi_res     = int(self._disc_hi_res.Value) if (_hi_res_on and self._disc_hi_res) else 1
        _lo_res_on = bool(self._disc_lo_res_cb.Checked) if self._disc_lo_res_cb else False
        lo_res_x   = int(self._disc_lo_res_x.Value) if (_lo_res_on and self._disc_lo_res_x) else 1
        lo_res_y   = int(self._disc_lo_res_y.Value) if (_lo_res_on and self._disc_lo_res_y) else 1
        lo_res_z   = int(self._disc_lo_res_z.Value) if (_lo_res_on and self._disc_lo_res_z) else 1

        # V12 — Density threshold
        _thresh_on      = bool(self._disc_thresh_cb.Checked)         if self._disc_thresh_cb      else False
        _thresh_density = float(self._disc_thresh_density.Value)      if (_thresh_on and self._disc_thresh_density) else 1.0

        # V13 — Grid X×Y×Z place_at → drive contiguous-block grouping via lo-res bays.
        # Overrides lo_res spinners and resolves place_at to "All voxels" so bays
        # form from every voxel. The Placement dropdown is still respected:
        #   Wall         → thin panel at each shared bay interface
        #   Replace voxel→ one element volumetrically filling each bay
        #   All exposed  → element on every exterior bay face
        _place_at_label = place_at
        if place_at == u"Grid X×Y×Z":
            lo_res_x = max(1, int(self._disc_grid_x.Value)) if self._disc_grid_x else 1
            lo_res_y = max(1, int(self._disc_grid_y.Value)) if self._disc_grid_y else 1
            lo_res_z = max(1, int(self._disc_grid_z.Value)) if self._disc_grid_z else 1
            _place_at_label = u"Grid {}×{}×{}".format(lo_res_x, lo_res_y, lo_res_z)
            place_at        = "All voxels"

        # V13 — Circulation gap
        _circ_on    = bool(self._disc_circ_cb.Checked) if self._disc_circ_cb else False
        _circ_rooms = int(self._disc_circ_rooms.Value) if (_circ_on and self._disc_circ_rooms) else 6
        _circ_gap   = int(self._disc_circ_gap.Value)   if (_circ_on and self._disc_circ_gap)   else 1

        _common_kwargs = dict(
            src_geos_d=geos_d, src_geos_e=geos_e, src_geos_f=geos_f,   # V16
            interlocking=interlocking,
            constrain_to_field=constrain, field_margin=field_margin,
            orient_strength=orient_strength,
            invert_place_at=invert_place,
            shell_depth=shell_depth,
            sun_az=sun_az, sun_alt=sun_alt, sun_thresh=sun_thresh,
            attractor_pt=attr_pt,
            attr_radius=attr_radius, attr_min=attr_min, attr_max=attr_max,
            cluster_target=cluster_target, cluster_faces=cluster_faces,
            cluster_invert=cluster_invert,
            hi_res=hi_res,
            lo_res_x=lo_res_x, lo_res_y=lo_res_y, lo_res_z=lo_res_z,
            density_thresh_active=_thresh_on, density_thresh=_thresh_density,
            circulation_active=_circ_on, circ_rooms=_circ_rooms, circ_gap=_circ_gap,
        )

        if sub_on:
            # Sub-Placement: Assignment becomes a navigator — bucket voxels into A/B/C,
            # then run the placement engine 3 times, one per bucket, with each bucket's
            # own input element. The main Placement dropdown is bypassed.
            sub_placement = self._dd_val(self._disc_sub_placement)
            sub_invert    = bool(self._disc_sub_invert.Checked)
            sub_inside    = bool(self._disc_sub_inside.Checked) if self._disc_sub_inside else False

            # Build the bucket lookup by reusing Assignment semantics against all voxels
            target_voxels_all = (
                list(self._voxels_dict.values()) if layers is None
                else _target_voxels(self._voxels_dict, layers))
            bucket = self._bucket_voxels_by_assignment(
                target_voxels_all, assign, c_seed, r_seed)

            n_total, bucket_counts = 0, {}
            for lbl in ("A", "B", "C", "D", "E", "F"):    # V16 — 6 buckets
                bv = bucket.get(lbl, [])
                if not bv:
                    bucket_counts[lbl] = 0
                    continue
                # Per-bucket mini voxels_dict so apply_discrete_mode sees only bucket voxels
                mini_dict = {v.grid_ijk: v for v in bv}
                n_bucket = apply_discrete_mode(
                    mini_dict, None,                # layers=None → use all voxels in mini_dict
                    geos_a, geos_b, geos_c,
                    "__sub_fixed__", span, sub_placement, orientation,
                    scale_fit, place_at, c_seed + 1, r_seed,  # +1 offsets cluster split
                    invert_placement=sub_invert,
                    forced_label=lbl,
                    place_inside=sub_inside,
                    **_common_kwargs)
                n_total += n_bucket
                bucket_counts[lbl] = n_bucket
            self._set_status(
                u"● Discrete (Sub-Placement): {} objects  [{} \u2192 {} | span {} | A:{} B:{} C:{} D:{} E:{} F:{}]".format(
                    n_total, assign, sub_placement, span,
                    bucket_counts.get("A", 0),
                    bucket_counts.get("B", 0),
                    bucket_counts.get("C", 0),
                    bucket_counts.get("D", 0),
                    bucket_counts.get("E", 0),
                    bucket_counts.get("F", 0)))
            return

        n = apply_discrete_mode(
            self._voxels_dict, layers,
            geos_a, geos_b, geos_c,
            assign, span, placement, orientation,
            scale_fit, place_at, c_seed, r_seed,
            invert_placement=invert_placement,
            **_common_kwargs)
        _circ_note = u" | circ {}r/{}g".format(_circ_rooms, _circ_gap) if _circ_on else u""
        self._set_status(
            u"● Discrete: {} objects placed  [{} | span {} | {} | {}{}]".format(
                n, assign, span, placement, _place_at_label, _circ_note))

    def _bucket_voxels_by_assignment(self, voxels, assignment_rule, cluster_seed, rand_seed):
        """V8/V16 Sub-Placement helper: split voxels into A-F buckets using the
        same logic as _make_get_type, but without needing element geometry.
        Returns {'A': [...], 'B': [...], ..., 'F': [...]}."""
        import random as _random
        _LBLS = ("A", "B", "C", "D", "E", "F")
        bucket = {lbl: [] for lbl in _LBLS}
        if not voxels:
            return bucket

        if assignment_rule == "By Z-level":
            k_vals  = [v.grid_ijk[2] for v in voxels]
            k_min   = min(k_vals)
            k_range = max(max(k_vals) - k_min, 1)
            for v in voxels:
                t = (v.grid_ijk[2] - k_min) / k_range
                idx = min(5, int(t * 6))
                bucket[_LBLS[idx]].append(v)

        elif assignment_rule == "By adjacency":
            _ADJ_MAP = {4: 0, 3: 1, 2: 2, 1: 3, 0: 4}
            for v in voxels:
                n = sum(1 for fd in SIDE_FACES
                        if v.face_types.get(fd) == "exterior")
                idx = _ADJ_MAP.get(n, 5)
                bucket[_LBLS[idx]].append(v)

        elif assignment_rule == "By cluster":
            grps = _split_6_clusters(voxels, cluster_seed)
            for lbl, grp in zip(_LBLS, grps):
                bucket[lbl].extend(grp)

        else:  # "Random mix"
            rng = _random.Random(rand_seed)
            for v in voxels:
                bucket[rng.choice(_LBLS)].append(v)
        return bucket

    def _build_room_cluster_tab(self):
        """Discrete Room Cluster — shell-only element distribution per spatial cluster.

        Reads the whole loaded voxel field, classifies spatially-isolated groups via
        6-connected BFS, then applies Element A/B/C only to the outer shell of each
        cluster.  Output lands on VOXELGEN_Cluster_Shell.
        """
        lay = eforms.DynamicLayout()
        lay.DefaultSpacing = edrawing.Size(6, 6)
        lay.Padding = edrawing.Padding(10)

        # ── Prereq label ──────────────────────────────────────────────────────
        self._rc_prereq = self._lbl(u"", width=400)
        lay.AddRow(self._rc_prereq)
        lay.AddRow(None)

        # ── Elements ──────────────────────────────────────────────────────────
        lay.AddRow(self._section(u"Elements"))

        self._rc_src_a_lbl = self._lbl(
            u"Element A  (required) \u2014 select \u2192", width=240)
        lay.AddRow(self._pick_row3(
            self._rc_src_a_lbl,
            self._pick_btn(u"Load as Element A", self._on_pick_rc_a, width=130),
            self._pick_btn(u"\u2715 Clear", self._on_clear_rc_a, width=50)))

        self._rc_src_b_lbl = self._lbl(
            u"Element B  (optional) \u2014 select \u2192", width=240)
        lay.AddRow(self._pick_row3(
            self._rc_src_b_lbl,
            self._pick_btn(u"Load as Element B", self._on_pick_rc_b, width=130),
            self._pick_btn(u"\u2715 Clear", self._on_clear_rc_b, width=50)))

        self._rc_src_c_lbl = self._lbl(
            u"Element C  (optional) \u2014 select \u2192", width=240)
        lay.AddRow(self._pick_row3(
            self._rc_src_c_lbl,
            self._pick_btn(u"Load as Element C", self._on_pick_rc_c, width=130),
            self._pick_btn(u"\u2715 Clear", self._on_clear_rc_c, width=50)))

        lay.AddRow(self._desc(
            u"B and C are optional \u2014 if omitted, A is used for all clusters."))

        # ── Cluster & Shell Settings ──────────────────────────────────────────
        lay.AddRow(None)
        lay.AddRow(self._section(u"Cluster & Shell Settings"))

        self._rc_n_clusters = self._num(6, 2, 64, 0, 1)
        lay.AddRow(self._row(u"Number of clusters (N):", self._rc_n_clusters))
        lay.AddRow(self._desc(
            u"Divides the field into N floor-band zones (like Program Classifier V6).\n"
            u"Each zone grows BFS within its floor band. Change seed to vary layout."))

        assign_opts = [u"Cycle A\u2192B\u2192C per cluster",
                       u"Mix A/B/C (random)",
                       u"Element A only",
                       u"Element B only",
                       u"Element C only"]
        self._rc_assign_dd = self._dropdown(assign_opts)
        lay.AddRow(self._row(u"Assignment:", self._rc_assign_dd))
        lay.AddRow(self._desc(
            u"Cycle: cluster 0\u2192A, 1\u2192B, 2\u2192C repeating.  "
            u"Mix: random A/B/C per boundary voxel."))

        self._rc_shell_depth = self._num(1, 1, 10, 0, 1)
        lay.AddRow(self._row(u"Ring depth:", self._rc_shell_depth))
        lay.AddRow(self._desc(
            u"1 = single voxel boundary (where clusters meet).  "
            u"3 = 3 voxels deep inward from each cluster boundary."))

        self._rc_scale = self._checkbox(u"Scale to fit voxel size", True)
        lay.AddRow(self._rc_scale)

        self._rc_invert = self._checkbox(u"Invert  \u2014  place on interior voxels instead of boundary", False)
        lay.AddRow(self._rc_invert)
        lay.AddRow(self._desc(
            u"Off: elements on boundary rings only (where clusters meet).\n"
            u"On:  elements on everything inside the boundary (interior of each cluster)."))

        # ── Seeds ─────────────────────────────────────────────────────────────
        lay.AddRow(None)
        self._rc_rand_seed = self._num(42, 0, 9999, 0, 1)
        lay.AddRow(self._seed_row(
            u"Cluster seed:", self._rc_rand_seed, self._on_rand_rc_seed))
        lay.AddRow(self._desc(u"Controls Voronoi seed placement. Same seed = same cluster layout."))

        # ── Status & Apply ────────────────────────────────────────────────────
        lay.AddRow(None)
        self._rc_status = self._lbl(u"", width=420)
        self._rc_status.TextColor = edrawing.Color.FromArgb(80, 190, 80)
        lay.AddRow(self._rc_status)

        lay.AddRow(self._desc(
            u"One element placed per boundary voxel (at voxel centre, scaled to fit).\n"
            u"Output: VOXELGEN_Cluster_Shell  (orange).\n"
            u"Uses the full loaded voxel field \u2014 no target layer needed."))

        return lay

    # ── Room Cluster event handlers ───────────────────────────────────────────

    def _on_pick_rc_a(self, s, e):
        self._load_selected_as_src("_rc_src_a", self._rc_src_a_lbl, "RC Element A")
        self._update_rc_prereq()

    def _on_pick_rc_b(self, s, e):
        self._load_selected_as_src("_rc_src_b", self._rc_src_b_lbl, "RC Element B")

    def _on_pick_rc_c(self, s, e):
        self._load_selected_as_src("_rc_src_c", self._rc_src_c_lbl, "RC Element C")

    def _on_clear_rc_a(self, s, e):
        self._rc_src_a = None
        self._rc_src_a_lbl.Text = u"Element A  (required) \u2014 select \u2192"
        self._update_rc_prereq()

    def _on_clear_rc_b(self, s, e):
        self._rc_src_b = None
        self._rc_src_b_lbl.Text = u"Element B  (optional) \u2014 select \u2192"

    def _on_clear_rc_c(self, s, e):
        self._rc_src_c = None
        self._rc_src_c_lbl.Text = u"Element C  (optional) \u2014 select \u2192"

    def _on_rand_rc_seed(self, s, e):
        import random as _r
        self._rc_rand_seed.Value = _r.randint(0, 9999)

    def _update_rc_prereq(self):
        has_v = bool(self._voxels_dict)
        has_a = bool(getattr(self, "_rc_src_a", None))
        if has_v and has_a:
            self._rc_prereq.Text = u"\u2705 Ready \u2014 click Apply"
            self._rc_prereq.TextColor = edrawing.Color.FromArgb(80, 190, 80)
        else:
            msgs = []
            if not has_v: msgs.append(u"\u2460 Load voxels first")
            if not has_a: msgs.append(u"\u2461 Load Element A")
            self._rc_prereq.Text = u"  \u2022  ".join(msgs)
            self._rc_prereq.TextColor = edrawing.Color.FromArgb(220, 80, 80)

    def _do_room_cluster_tab(self):
        """Room Cluster tab — Voronoi BFS subdivision + boundary ring placement.

        1. Partition ALL loaded voxels into N Voronoi clusters via Multi-Source BFS.
        2. Find the topological boundary (voxels adjacent to a different cluster).
        3. Expand inward ring_depth layers within each cluster.
        4. Place one element per boundary voxel, centred at the voxel centre.
        """
        if not getattr(self, "_rc_src_a", None):
            self._set_status(
                u"\u25cf Discrete Room cluster \u2192 select Element A, "
                u"then click \u2018Load as Element A\u2019.", False)
            return

        geos_a = self._get_geos(self._rc_src_a, "RC Element A")
        if not geos_a:
            return
        geos_b = self._get_geos(self._rc_src_b, "RC Element B") if getattr(self, "_rc_src_b", None) else None
        geos_c = self._get_geos(self._rc_src_c, "RC Element C") if getattr(self, "_rc_src_c", None) else None

        if not self._voxels_dict:
            self._set_status(u"\u25cf Room Cluster: no voxels loaded.", False)
            return

        n_clusters  = int(self._rc_n_clusters.Value)
        ring_depth  = int(self._rc_shell_depth.Value)
        assign_mode = self._dd_val(self._rc_assign_dd)
        scale_fit   = bool(self._rc_scale.Checked)
        invert      = bool(self._rc_invert.Checked) if self._rc_invert else False
        seed        = int(self._rc_rand_seed.Value)
        import random as _rng

        self._set_status(u"\u2462 Room Cluster: Voronoi BFS ({} clusters)\u2026".format(n_clusters))

        # 1. Voronoi Multi-Source BFS → {ijk: cluster_id} for every voxel
        cluster_map = _voronoi_cluster_bfs(self._voxels_dict, n_clusters, seed)
        if not cluster_map:
            self._set_status(u"\u25cf Room Cluster: no voxels to cluster.", False)
            return

        # 2+3. Topological boundary + inward ring expansion → {cluster_id: {ijk: Voxel}}
        boundary_by_cluster = _get_voronoi_boundary(cluster_map, self._voxels_dict, ring_depth)
        if not boundary_by_cluster:
            self._set_status(u"\u25cf Room Cluster: no cluster boundaries found.", False)
            return

        # 4. Invert — swap to interior voxels (everything NOT in the boundary rings)
        if invert:
            # Build full per-cluster dict from cluster_map
            all_by_cluster = {}
            for ijk, cid in cluster_map.items():
                if cid not in all_by_cluster:
                    all_by_cluster[cid] = {}
                if ijk in self._voxels_dict:
                    all_by_cluster[cid][ijk] = self._voxels_dict[ijk]
            # Subtract boundary voxels
            active_by_cluster = {}
            for cid, all_dict in all_by_cluster.items():
                boundary_ijk = set(boundary_by_cluster.get(cid, {}).keys())
                interior = {ijk: v for ijk, v in all_dict.items()
                            if ijk not in boundary_ijk}
                if interior:
                    active_by_cluster[cid] = interior
        else:
            active_by_cluster = boundary_by_cluster

        out_layer = ensure_output_layer("Cluster_Shell")

        # Source frames — origin at element CENTRE (not bottom) so element is
        # centred in the voxel cell (fixes the Z-offset issue).
        def _src_frame(geos):
            bb     = _combined_bb(geos)
            origin = rg.Point3d(bb.Center.X, bb.Center.Y, bb.Center.Z)
            plane  = rg.Plane(origin, rg.Vector3d.ZAxis)
            size   = max(bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, 1e-6)
            return plane, size

        frame_a = _src_frame(geos_a)
        frame_b = _src_frame(geos_b) if geos_b else frame_a
        frame_c = _src_frame(geos_c) if geos_c else frame_b

        src_cycle_geos   = [geos_a,
                            geos_b if geos_b else geos_a,
                            geos_c if geos_c else (geos_b if geos_b else geos_a)]
        src_cycle_frames = [frame_a,
                            frame_b if geos_b else frame_a,
                            frame_c if geos_c else (frame_b if geos_b else frame_a)]

        rnd          = _rng.Random(seed)
        total_placed = 0
        all_guids    = []
        parts        = []

        for cid, shell_dict in active_by_cluster.items():
            if not shell_dict:
                continue

            # Pick element set for this cluster
            if assign_mode == u"Cycle A\u2192B\u2192C per cluster":
                idx = cid % 3
                eff_geos, eff_frame = src_cycle_geos[idx], src_cycle_frames[idx]
                mix = False
            elif assign_mode == u"Element A only":
                eff_geos, eff_frame = geos_a, frame_a
                mix = False
            elif assign_mode == u"Element B only":
                eff_geos, eff_frame = src_cycle_geos[1], src_cycle_frames[1]
                mix = False
            elif assign_mode == u"Element C only":
                eff_geos, eff_frame = src_cycle_geos[2], src_cycle_frames[2]
                mix = False
            else:  # Mix A/B/C — random per voxel
                mix = True

            n = 0
            for vox in shell_dict.values():
                if mix:
                    idx       = rnd.randint(0, 2)
                    eff_geos  = src_cycle_geos[idx]
                    eff_frame = src_cycle_frames[idx]

                # Target plane at voxel CENTRE, Z-up
                target_plane = rg.Plane(vox.center, rg.Vector3d.ZAxis)

                # Orient element centre → voxel centre
                oriented = _orient_geos(eff_geos, eff_frame[0], target_plane)

                # Uniform scale to fit voxel cell
                if scale_fit and eff_frame[1] > 1e-6:
                    sf = vox.size / eff_frame[1]
                    xf = rg.Transform.Scale(target_plane, sf, sf, sf)
                    for g in oriented:
                        g.Transform(xf)

                guids = _add_geos(oriented, out_layer)
                all_guids.extend(guids)
                n += len(guids)

            total_placed += n
            parts.append(u"C{}={}".format(cid, n))

        import time as _t
        if all_guids:
            _group_objects(all_guids, u"VOXELGEN_ClusterShell_{}".format(int(_t.time())))

        summary = u"  ".join(parts) if parts else u"(none)"
        self._rc_status.Text = u"\u2714 {} cluster(s) \u2192 {} objects  [{}]".format(
            n_clusters, total_placed, summary)
        self._rc_status.TextColor = edrawing.Color.FromArgb(80, 190, 80)
        mode_tag = u"interior" if invert else u"rings={}".format(ring_depth)
        self._set_status(
            u"\u25cf Discrete Room cluster: N={} clusters, {} objects  "
            u"[{} | seed={} | {}]".format(
                n_clusters, total_placed, mode_tag, seed, summary))

    def _build_skywalk_tab(self):
        """Skywalk - Adaptive Elevated Circulation

        Sweep profiles along curves with parametric response to attractor points.
        Supports elevation ramps, width modulation, profile changes, and landing platforms.
        """
        layout = eforms.DynamicLayout()
        layout.DefaultSpacing = edrawing.Size(4, 8)
        layout.Padding = edrawing.Padding(8)

        # Element Selection
        layout.AddRow(self._section("Element Selection"))

        self._sky_curves_lbl = self._lbl("Curves: [none loaded]")
        btn_load_curves = self._pick_btn("Load Curves", self._on_sky_load_curves, width=130)
        layout.AddRow(self._row("Circulation paths", eforms.TableLayout.AutoSized(btn_load_curves)))
        layout.AddRow(self._sky_curves_lbl)

        self._sky_attractors_lbl = self._lbl("Attractors: [none loaded]")
        btn_load_attr = self._pick_btn("Load Attractors", self._on_sky_load_attractors, width=130)
        layout.AddRow(self._row("Attractor points", eforms.TableLayout.AutoSized(btn_load_attr)))
        layout.AddRow(self._sky_attractors_lbl)

        # Profile Configuration
        layout.AddRow(self._section("Profile Configuration"))

        profile_opts = ["ChannelU", "Box", "Stepped", "Hollow", "Tapered", "Asymmetric"]
        self._sky_profile_dd = self._dropdown(profile_opts)
        layout.AddRow(self._row("Profile type", self._sky_profile_dd, lbl_w=160))

        self._sky_width_input = self._num(self._sky_default_width, 0.5, 10.0, dec=2, inc=0.1)
        layout.AddRow(self._row("Width (m)", self._sky_width_input, lbl_w=160))

        self._sky_height_input = self._num(self._sky_default_height, 0.1, 5.0, dec=2, inc=0.1)
        layout.AddRow(self._row("Height (m)", self._sky_height_input, lbl_w=160))

        # Attractor Behavior
        layout.AddRow(self._section("Attractor Behavior"))

        self._sky_elev_ramp_chk = self._checkbox("Enable elevation ramp", checked=True)
        layout.AddRow(self._sky_elev_ramp_chk)

        self._sky_elev_delta_input = self._num(0.5, -2.0, 2.0, dec=2, inc=0.1)
        layout.AddRow(self._row("Elevation change (m)", self._sky_elev_delta_input, lbl_w=160))

        self._sky_width_mod_chk = self._checkbox("Enable width modulation", checked=True)
        layout.AddRow(self._sky_width_mod_chk)

        self._sky_width_scale_input = self._num(1.5, 1.0, 3.0, dec=2, inc=0.1)
        layout.AddRow(self._row("Width scale at attractor", self._sky_width_scale_input, lbl_w=160))

        self._sky_profile_change_chk = self._checkbox("Enable profile change", checked=True)
        layout.AddRow(self._sky_profile_change_chk)

        self._sky_landing_chk = self._checkbox("Enable landing platform", checked=True)
        layout.AddRow(self._sky_landing_chk)

        # Variation Control
        layout.AddRow(self._section("Variation Control"))

        self._sky_seed_input = self._num(42, 0, 9999, inc=1)
        layout.AddRow(self._row("Seed", self._sky_seed_input, lbl_w=160))

        layout.AddRow(self._lbl("Seed modes (all active):", bold=False))

        self._sky_var_mode1_chk = self._checkbox("Mode 1: Dimension variation (\u00b1%)", checked=True)
        layout.AddRow(self._sky_var_mode1_chk)
        self._sky_var_width_pct = self._num(10, 0, 50, inc=1)
        layout.AddRow(self._row("  Width variation %", self._sky_var_width_pct, lbl_w=160))

        self._sky_var_mode2_chk = self._checkbox("Mode 2: Profile selection", checked=True)
        layout.AddRow(self._sky_var_mode2_chk)

        self._sky_var_mode3_chk = self._checkbox("Mode 3: Shape distortion", checked=True)
        layout.AddRow(self._sky_var_mode3_chk)

        # Node & Intersection
        layout.AddRow(self._section("Node & Intersection"))

        self._sky_node_size_input = self._num(2.0, 1.5, 3.0, dec=2, inc=0.1)
        layout.AddRow(self._row("Node cluster size (multiplier)", self._sky_node_size_input, lbl_w=160))

        self._sky_merge_intersect_chk = self._checkbox("Merge at intersections", checked=True)
        layout.AddRow(self._sky_merge_intersect_chk)

        self._sky_simplify_chk = self._checkbox("Simplify node geometry", checked=True)
        layout.AddRow(self._sky_simplify_chk)

        # Control buttons
        layout.AddRow(self._lbl("─────────────────────────────────────"))
        btn_gen = eforms.Button(); btn_gen.Text = u"\u25b6  Generate Skywalk"
        btn_gen.Click += self._on_sky_generate; btn_gen.Height = 32
        btn_clr = eforms.Button(); btn_clr.Text = "Clear Skywalk"
        btn_clr.Click += self._on_sky_clear; btn_clr.Height = 32

        btn_layout = eforms.TableLayout()
        btn_layout.Spacing = edrawing.Size(6, 0)
        btn_layout.Rows.Add(eforms.TableRow(
            eforms.TableCell(btn_gen),
            eforms.TableCell(btn_clr),
        ))
        layout.AddRow(btn_layout)

        self._sky_status_lbl = self._lbl("Status: [ready]")
        layout.AddRow(self._sky_status_lbl)

        return layout

    def _on_sky_load_curves(self, s, e):
        """Load curves from Rhino viewport"""
        try:
            doc = Rhino.RhinoDoc.ActiveDoc
            self._sky_curves = []
            sel_objs = doc.Objects.GetSelectedObjects(False, False)
            for obj in sel_objs:
                geo = obj.Geometry
                if isinstance(geo, rg.Curve):
                    self._sky_curves.append(geo)
            self._sky_curves_lbl.Text = "Curves: {} loaded".format(len(self._sky_curves))
            self._set_status(u"● Loaded {} curves".format(len(self._sky_curves)))
        except Exception as ex:
            self._set_status("Error loading curves: {}".format(str(ex)))

    def _on_sky_load_attractors(self, s, e):
        """Load attractor points from Rhino viewport"""
        try:
            doc = Rhino.RhinoDoc.ActiveDoc
            self._sky_attractors = []
            sel_objs = doc.Objects.GetSelectedObjects(False, False)
            for obj in sel_objs:
                geo = obj.Geometry
                if isinstance(geo, rg.Point):
                    self._sky_attractors.append(geo.Location)
                elif isinstance(geo, rg.PointCloud):
                    for pt in geo:
                        self._sky_attractors.append(pt)
            self._sky_attractors_lbl.Text = "Attractors: {} loaded".format(len(self._sky_attractors))
            self._set_status(u"● Loaded {} attractor points".format(len(self._sky_attractors)))
        except Exception as ex:
            self._set_status("Error loading attractors: {}".format(str(ex)))

    def _on_sky_generate(self, s, e):
        """Generate skywalk geometry"""
        try:
            if not self._sky_curves:
                self._sky_status_lbl.Text = "Status: [error] No curves loaded"
                return

            self._sky_status_lbl.Text = u"Status: \u23f3  Generating..."

            self._do_skywalk()

            self._sky_status_lbl.Text = "Status: [complete]"
            self._set_status(u"● Skywalk generated successfully")
        except Exception as ex:
            self._sky_status_lbl.Text = "Status: [error]"
            self._set_status("Error generating skywalk: {}".format(str(ex)))
            traceback.print_exc()

    def _on_sky_clear(self, s, e):
        """Clear skywalk layers"""
        try:
            # Clear layer objects
            for layer_name in ["VOXELGEN_Skywalk_Paths", "VOXELGEN_Skywalk_Nodes"]:
                if rs.IsLayer(layer_name):
                    rs.LayerLocked(layer_name, False)
                    objs = rs.ObjectsByLayer(layer_name)
                    if objs:
                        rs.DeleteObjects(objs)
            self._sky_status_lbl.Text = "Status: [cleared]"
            self._set_status("● Skywalk layers cleared")
        except Exception as ex:
            self._set_status("Error clearing skywalk: {}".format(str(ex)))

    def _do_skywalk(self):
        """Main orchestration: offset-trim-extrude-loft-thicken approach."""
        doc  = Rhino.RhinoDoc.ActiveDoc
        tol  = doc.ModelAbsoluteTolerance

        width      = float(self._sky_width_input.Value)
        height     = float(self._sky_height_input.Value)
        node_scale = float(self._sky_node_size_input.Value)
        half_w     = width  / 2.0
        wall_t     = max(width * 0.06, 0.04)   # panel thickness

        paths_placed = 0
        nodes_placed = 0

        self._ensure_layer_exists("VOXELGEN_Skywalk_Paths", sd.Color.FromArgb(100, 200, 100))
        self._ensure_layer_exists("VOXELGEN_Skywalk_Nodes", sd.Color.FromArgb(150, 255, 100))

        def layer_idx(name):
            return doc.Layers.FindByFullPath(name, -1)

        def add_brep(brep, layer_name):
            if not brep or not brep.IsValid:
                return False
            attrs = rd.ObjectAttributes()
            li = layer_idx(layer_name)
            if li >= 0:
                attrs.LayerIndex = li
            return doc.Objects.AddBrep(brep, attrs) != System.Guid.Empty

        # ── helper: build solid from closed boundary curve + extrusion ───────
        def _closed_extrusion(boundary_crv, z_bottom, z_top):
            """PlanarSrf on boundary_crv, extrude from z_bottom to z_top → solid."""
            try:
                srfs = rg.Brep.CreatePlanarBreps([boundary_crv], tol)
                if not srfs:
                    return None
                srf = srfs[0]
                # Move to z_bottom
                if abs(z_bottom) > tol:
                    srf.Transform(rg.Transform.Translation(0, 0, z_bottom))
                dz   = z_top - z_bottom
                path = rg.Line(rg.Point3d(0, 0, 0),
                               rg.Point3d(0, 0, dz)).ToNurbsCurve()
                solid = srf.Faces[0].CreateExtrusion(path, True)
                if solid:
                    solid.Faces.SplitKinkyFaces(rg.RhinoMath.DefaultAngleTolerance, True)
                    return solid
            except Exception as ex:
                print("_closed_extrusion failed: {}".format(ex))
            return None

        def _boundary_curve(left, right):
            """Closed boundary curve from left + right offset rails."""
            try:
                s_line = rg.Line(left.PointAtStart, right.PointAtStart).ToNurbsCurve()
                e_line = rg.Line(right.PointAtEnd,  left.PointAtEnd).ToNurbsCurve()
                r_rev  = right.DuplicateCurve(); r_rev.Reverse()
                joined = rg.Curve.JoinCurves([left, e_line, r_rev, s_line], tol)
                return joined[0] if joined else None
            except Exception as ex:
                print("_boundary_curve failed: {}".format(ex))
            return None

        # ── 1. Offset each curve ±half_w → outer boundary → solid box ─────
        #       Then subtract inner cavity → U-channel
        all_solids = []

        for crv in self._sky_curves:
            rail = crv.DuplicateCurve()
            if not rail or not rail.IsValid:
                continue

            # Outer offset rails (full-width box)
            L_arr = rail.Offset(rg.Plane.WorldXY,  half_w, tol, rg.CurveOffsetCornerStyle.Sharp)
            R_arr = rail.Offset(rg.Plane.WorldXY, -half_w, tol, rg.CurveOffsetCornerStyle.Sharp)
            if not L_arr or not R_arr:
                print("Offset failed, skipping")
                continue
            left  = L_arr[0] if len(L_arr) == 1 else rg.Curve.JoinCurves(list(L_arr), tol)[0]
            right = R_arr[0] if len(R_arr) == 1 else rg.Curve.JoinCurves(list(R_arr), tol)[0]
            if not left or not right:
                continue

            # Outer boundary → full-height solid box
            outer_bnd = _boundary_curve(left, right)
            if not outer_bnd:
                continue
            outer_solid = _closed_extrusion(outer_bnd, 0, height)
            if not outer_solid:
                continue

            # Inner offset rails (cavity = box minus 2×wall_t in width)
            inner_hw = half_w - wall_t
            if inner_hw <= 0:
                # Too thin for cavity — just use solid box
                all_solids.append(outer_solid)
                continue

            Li_arr = rail.Offset(rg.Plane.WorldXY,  inner_hw, tol, rg.CurveOffsetCornerStyle.Sharp)
            Ri_arr = rail.Offset(rg.Plane.WorldXY, -inner_hw, tol, rg.CurveOffsetCornerStyle.Sharp)
            if not Li_arr or not Ri_arr:
                all_solids.append(outer_solid)
                continue
            l_inner = Li_arr[0] if len(Li_arr) == 1 else rg.Curve.JoinCurves(list(Li_arr), tol)[0]
            r_inner = Ri_arr[0] if len(Ri_arr) == 1 else rg.Curve.JoinCurves(list(Ri_arr), tol)[0]

            inner_bnd = _boundary_curve(l_inner, r_inner)
            if not inner_bnd:
                all_solids.append(outer_solid)
                continue

            # Inner cavity: from floor_t up to full height (open-top U-channel)
            inner_cavity = _closed_extrusion(inner_bnd, wall_t, height)
            if not inner_cavity:
                all_solids.append(outer_solid)
                continue

            # BooleanDifference: outer box − inner cavity = U-channel solid
            try:
                result = rg.Brep.CreateBooleanDifference(
                    [outer_solid], [inner_cavity], tol)
                if result:
                    all_solids.extend(result)
                else:
                    all_solids.append(outer_solid)   # fallback: solid box
            except Exception as ex:
                print("BooleanDiff failed: {}".format(ex))
                all_solids.append(outer_solid)

        # ── 2. BooleanUnion all path solids → clean T/X junctions ─────────
        if not all_solids:
            self._set_status("Skywalk: generation failed for all curves")
            return

        if len(all_solids) > 1:
            try:
                merged = rg.Brep.CreateBooleanUnion(all_solids, tol)
                if merged:
                    all_solids = list(merged)
            except Exception as ex:
                print("BooleanUnion failed, keeping separate: {}".format(ex))

        for s in all_solids:
            if add_brep(s, "VOXELGEN_Skywalk_Paths"):
                paths_placed += 1

        # ── 4. Node clusters at junctions ─────────────────────────────────
        if len(self._sky_curves) > 1:
            intersections = self._detect_curve_intersections(self._sky_curves)
            for (idx1, idx2, int_pt) in intersections:
                try:
                    node = self._create_node_cluster(
                        int_pt,
                        [self._sky_curves[idx1], self._sky_curves[idx2]],
                        node_scale, 42, width, height)
                    if node and add_brep(node, "VOXELGEN_Skywalk_Nodes"):
                        nodes_placed += 1
                except Exception as ex:
                    print("Node cluster error: {}".format(ex))

        doc.Views.Redraw()
        self._set_status(
            u"● Skywalk: {} surfaces, {} nodes".format(paths_placed, nodes_placed))

    def _make_profile_curve(self, width, height, profile_name, plane):
        """Build a U-channel profile in the given plane.

        The plane origin is the bottom-center of the profile.
        plane.XAxis = width direction (horizontal, perpendicular to curve)
        plane.YAxis = height direction (vertical, up)
        """
        half_w = width / 2.0
        wt     = max(width * 0.08, 0.02)   # wall thickness: 8% of width
        ft     = max(height * 0.12, 0.02)  # floor thickness: 12% of height

        def pt(u, v):
            return plane.Origin + plane.XAxis * u + plane.YAxis * v

        if profile_name == "ChannelU":
            # Classic symmetric U-channel
            pts = [
                pt(-half_w,       0),
                pt(-half_w,       height),
                pt(-half_w + wt,  height),
                pt(-half_w + wt,  ft),
                pt( half_w - wt,  ft),
                pt( half_w - wt,  height),
                pt( half_w,       height),
                pt( half_w,       0),
                pt(-half_w,       0),
            ]
        elif profile_name == "Box":
            # Closed hollow box
            pts = [
                pt(-half_w, 0),
                pt(-half_w, height),
                pt( half_w, height),
                pt( half_w, 0),
                pt(-half_w, 0),
            ]
        elif profile_name == "Stepped":
            # Stepped/tiered profile (bleacher-like)
            step = height / 3.0
            pts = [
                pt(-half_w,       0),
                pt(-half_w,       step),
                pt(-half_w/3,     step),
                pt(-half_w/3,     step * 2),
                pt( half_w/3,     step * 2),
                pt( half_w/3,     height),
                pt( half_w,       height),
                pt( half_w,       0),
                pt(-half_w,       0),
            ]
        elif profile_name == "Hollow":
            # Thin-wall box (hollow rectangle outline)
            pts = [
                pt(-half_w,       0),
                pt(-half_w,       height),
                pt( half_w,       height),
                pt( half_w,       0),
                pt( half_w - wt,  0),
                pt( half_w - wt,  height - wt),
                pt(-half_w + wt,  height - wt),
                pt(-half_w + wt,  0),
                pt(-half_w,       0),
            ]
        elif profile_name == "Tapered":
            # Tapered U (narrower at top)
            taper = half_w * 0.2
            pts = [
                pt(-half_w,            0),
                pt(-half_w + taper,    height),
                pt(-half_w + taper + wt, height),
                pt(-half_w + wt,       ft),
                pt( half_w - wt,       ft),
                pt( half_w - taper - wt, height),
                pt( half_w - taper,    height),
                pt( half_w,            0),
                pt(-half_w,            0),
            ]
        else:  # Asymmetric
            # One side taller than the other
            pts = [
                pt(-half_w,       0),
                pt(-half_w,       height * 1.3),
                pt(-half_w + wt,  height * 1.3),
                pt(-half_w + wt,  ft),
                pt( half_w - wt,  ft),
                pt( half_w - wt,  height * 0.7),
                pt( half_w,       height * 0.7),
                pt( half_w,       0),
                pt(-half_w,       0),
            ]

        poly = rg.Polyline(pts)
        return poly.ToNurbsCurve()

    def _sweep_profile_along_curve(self, curve, width, height, seed, segment_count=35):
        """Sweep a U-channel profile along a curve.

        Profile is built in the plane perpendicular to the curve at its start,
        so it sweeps correctly on-curve rather than at world origin.
        """
        import random
        try:
            profile_name = self._dd_val(self._sky_profile_dd)
            print("DEBUG sweep: profile='{}' w={} h={}".format(profile_name, width, height))

            # ── Duplicate curve to avoid reference issues ─────────────────────
            rail = curve.DuplicateCurve() if hasattr(curve, 'DuplicateCurve') else curve
            if not rail or not rail.IsValid:
                print("DEBUG sweep: rail curve invalid, skipping")
                return None
            print("DEBUG sweep: rail len={:.3f}  domain=[{:.3f},{:.3f}]".format(
                rail.GetLength(), rail.Domain.Min, rail.Domain.Max))

            # ── Build perpendicular plane at curve start ──────────────────────
            t0      = rail.Domain.Min
            origin  = rail.PointAt(t0)
            tangent = rail.TangentAt(t0)
            tangent.Unitize()
            print("DEBUG sweep: origin={} tangent={}".format(origin, tangent))

            # Use world Z for "up"; fall back to world Y if curve goes straight up
            world_z = rg.Vector3d(0, 0, 1)
            x_axis  = rg.Vector3d.CrossProduct(world_z, tangent)
            if x_axis.Length < 0.001:
                x_axis = rg.Vector3d.CrossProduct(rg.Vector3d(0, 1, 0), tangent)
            x_axis.Unitize()
            y_axis = rg.Vector3d.CrossProduct(tangent, x_axis)
            y_axis.Unitize()

            # Profile plane: origin at bottom-centre of curve start
            profile_plane = rg.Plane(origin, x_axis, y_axis)
            print("DEBUG sweep: profile_plane valid={} origin={}".format(
                profile_plane.IsValid, profile_plane.Origin))

            # ── Build profile in that plane ───────────────────────────────────
            profile = self._make_profile_curve(width, height, profile_name, profile_plane)
            if not profile or not profile.IsValid:
                print("DEBUG sweep: profile curve is invalid!")
                return None
            bb = profile.GetBoundingBox(False)
            print("DEBUG sweep: profile bb min={} max={}".format(bb.Min, bb.Max))

            # ── Sweep ─────────────────────────────────────────────────────────
            doc_tol = Rhino.RhinoDoc.ActiveDoc.ModelAbsoluteTolerance
            print("DEBUG sweep: calling CreateFromSweep, doc_tol={}".format(doc_tol))
            brep_array = rg.Brep.CreateFromSweep(rail, [profile], False, doc_tol)
            print("DEBUG sweep: brep_array count={}".format(
                len(brep_array) if brep_array else 0))

            if brep_array and len(brep_array) > 0:
                swept = brep_array[0]
                print("DEBUG sweep: success, faces={}".format(swept.Faces.Count))

                # Mode 1: slight dimension variation per-seed
                if self._sky_var_mode1_chk.Checked:
                    rnd       = random.Random(seed)
                    pct       = float(self._sky_var_width_pct.Value) / 100.0
                    factor    = 1.0 + rnd.uniform(-pct, pct)
                    center_pt = swept.GetBoundingBox(False).Center
                    swept.Transform(rg.Transform.Scale(center_pt, factor))

                return swept

            print("DEBUG sweep: CreateFromSweep returned empty array!")
            return None

        except Exception as ex:
            print("Error in _sweep_profile_along_curve: {}".format(str(ex)))
            traceback.print_exc()
            return None

    def _apply_attractor_behavior(self, swept_geo, curve, attractors, width, height, seed):
        """Apply adaptive behavior (elevation, width, profile changes) near attractor points"""
        try:
            # For each attractor, compute influence and apply deformations
            # This is a simplified version - full implementation would deform the swept surface
            # For now, create supplemental geometry (landing platforms) at attractor zones

            # Find closest point on curve to each attractor
            for attr_pt in attractors:
                # Find closest parameter on curve
                param = curve.ClosestPoint(attr_pt)[1]
                closest_pt = curve.PointAt(param)
                dist_to_attr = closest_pt.DistanceTo(attr_pt)

                # If within influence radius, create landing platform
                influence_radius = 5.0  # meters
                if dist_to_attr < influence_radius:
                    # Create elliptical landing platform
                    # Major axis: along curve tangent
                    # Minor axis: perpendicular
                    pass  # Landing platforms are added in _do_skywalk

            # Return modified geometry (for now, return swept as-is)
            # Full implementation would apply surface deformations
            return swept_geo
        except Exception as ex:
            print("Error in _apply_attractor_behavior: {}".format(str(ex)))
            return swept_geo

    def _detect_curve_intersections(self, curves, tolerance=0.5):
        """Find curve intersections and proximity"""
        intersections = []
        try:
            for i in range(len(curves)):
                for j in range(i + 1, len(curves)):
                    curve_a = curves[i]
                    curve_b = curves[j]

                    # Check for intersection
                    params_a, params_b = rg.Intersection.CurveCurve(
                        curve_a, curve_b, 1e-6, 1e-6
                    )

                    for k in range(len(params_a)):
                        pt_a = curve_a.PointAt(params_a[k])
                        pt_b = curve_b.PointAt(params_b[k])
                        mid_pt = rg.Point3d(
                            (pt_a.X + pt_b.X) / 2,
                            (pt_a.Y + pt_b.Y) / 2,
                            (pt_a.Z + pt_b.Z) / 2
                        )
                        intersections.append((i, j, mid_pt))
        except:
            pass

        return intersections

    def _create_node_cluster(self, intersection_point, converging_curves, node_scale, seed, width, height):
        """Create expanded hub at intersection"""
        try:
            # Create a simple expanded cylinder at intersection
            radius = width * node_scale / 2
            hub = rg.Cylinder(
                rg.Plane(intersection_point, rg.Vector3d.ZAxis),
                radius,
                height * node_scale
            ).ToBrep()
            return hub
        except:
            return None


# ==============================================================================
#  ENTRY POINT
# ==============================================================================

def run():
    form = DistributionVoxelsForm()
    form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    form.Show()


if __name__ == "__main__":
    run()
