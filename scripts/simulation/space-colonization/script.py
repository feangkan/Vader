#! python3
"""
Space Colonization Algorithm V4
================================
Rhino 8 / CPython 3

Builds on V2 with one new system:

  NEW  Point Attractor Field         Pick any Rhino points — they bias SCA
                                     growth direction across ALL modes.
                                     Six behaviour presets control how points
                                     shape the network:
                                       Density Pull      — clusters attract harder
                                       Repulsion         — push branches away
                                       Weighted Strength — manual weight per point
                                       Depth Gradient    — Z height = pull strength
                                       Waypoint Sequence — directed sequential paths
                                       Orbital Swirl     — branches orbit points

  The Point Attractor Field is a persistent bias layer (points are never
  consumed).  Run Surface Branching mode + dense point clusters on the facade
  → SCA branches concentrate where points are dense, thin out elsewhere.

MODES (unchanged from V2)
-----
  0  Structural Tree Column     — random attractors in reference box
  1  Voxel Circulation Network  — voxel bounding-box centres as attractors
  2  Facade / Surface Branching — UV-sampled attractors on picked surface/mesh
  3  Climate-Responsive Growth  — radiation-weighted attractors from climate voxels
  4  Urban Canopy (Site Scale)  — multi-cluster roots in large site volume
  5  Curve Network              — attractors sampled along picked curves

OUTPUT
------
  SCA_Branches::Depth_N  NurbsCurves coloured warm→cool by branch depth
  SCA_Pipes              (optional) tapered Brep pipes per branch segment
"""

import math
import random
import time
import traceback

import rhinoscriptsyntax as rs
import Rhino
import Rhino.Geometry as rg
import Rhino.Display as rd
import scriptcontext as sc
import System
import System.Drawing as sd

try:
    import Eto.Forms as ef
    import Eto.Drawing as edraw
    _ETO = True
except Exception:
    _ETO = False
    print("Eto.Forms not available — cannot open GUI")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

SCA_MODES = [
    "Structural Tree Column",
    "Voxel Circulation Network",
    "Facade / Surface Branching",
    "Climate-Responsive Growth",
    "Urban Canopy (Site Scale)",
    "Curve Network",
]

INFLUENCE_TYPES = [
    "None",
    "Climate Heat Index",
    "Sun Direction",
    "Wind",
    "Gravity",
    "Custom XYZ",
]

POINT_BEHAVIORS = [
    "Density Pull",       # clusters pull harder — dense points = dense branching
    "Repulsion",          # push branches away — creates clear voids
    "Weighted Strength",  # manual weight per point via name "w=2.5"
    "Depth Gradient",     # Z height drives pull strength (highest = strongest)
    "Waypoint Sequence",  # sequential directed paths — reach pt N before N+1
    "Orbital Swirl",      # branches rotate around nearby points (vortex)
]

DISPLAY_STYLES = [
    "Bloom + Trail",      # A default: consumed flash white ring, branch leading-edge glow
    "Glowing Neon",       # B: cyan glow attractors, tapered warm→cool branches
    "Heat Map Density",   # C: attractors coloured red→blue by local cluster density
    "Branch-Only",        # D: hide all dots, show only glowing branch lines
    "Particle Field",     # E: attractors resize by proximity to nearest node
    "Depth Fog",          # F: brightness/size fade with Z-height for 3D depth
]

LAYER_BRANCHES = "SCA_Branches"
LAYER_PIPES    = "SCA_Pipes"

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────

DEFAULTS = {
    "attractor_mode": 2,   # Facade / Surface Branching — primary workflow in V3

    # Mode 0 — Structural Tree Column
    "bbox_x": 100.0,
    "bbox_y": 100.0,
    "bbox_z": 150.0,
    "num_attractors": 150,

    # Mode 1 — Voxel Circulation Network
    "voxel_guids": [],
    "voxel_layer_filter": "",

    # Mode 2 — Facade / Surface Branching
    "surface_guids":         [],     # list — supports multiple picked surfaces
    "surface_u_div":         14,
    "surface_v_div":         14,
    "surface_noise":         0.2,
    "surface_3d_mode":       False,     # False = flat on surface, True = 3D offset growth
    "surface_3d_type":       "Offset",  # "Offset" = single cloud | "Shells" = multi-layer
    "surface_growth_depth":  10.0,      # world units — max attractor distance from surface
    "surface_shell_count":   3,         # number of attractor shells (Shells mode only)
    "surface_root_offset":   0.0,       # root offset from surface (0 = on surface face)

    # Mode 3 — Climate-Responsive Growth
    "climate_voxel_guids": [],
    "radiation_bias": 3.0,

    # Mode 4 — Urban Canopy
    "site_bbox_x": 500.0,
    "site_bbox_y": 500.0,
    "site_bbox_z": 80.0,
    "site_num_attractors": 400,
    "num_clusters": 4,

    # Mode 5 — Curve Network
    "curve_guids": [],
    "curve_sample_count": 30,
    "curve_noise": 0.0,

    # Growth — shared
    "num_roots": 5,
    "influence_radius": 50.0,
    "kill_distance": 6.0,
    "step_distance": 7.0,
    "random_noise": 0.70,
    "max_iterations": 300,

    # Simulation display
    "show_attractors": True,
    "draw_delay_ms":   150,
    "display_style":   "Bloom + Trail",  # see DISPLAY_STYLES list

    # Output
    "output_pipes": False,
    "pipe_radius": 1.0,
    "taper_ratio": 4.0,

    "seed": 42,

    # Influence field
    "influence_type":   "None",
    "influence_weight": 0.0,
    "sun_month":        6,
    "sun_hour":         12.0,
    "wind_direction":   225.0,
    "custom_ix":        0.0,
    "custom_iy":        0.0,
    "custom_iz":        1.0,

    # Point Attractor Field (works across all modes)
    "point_guids":            [],
    "point_behavior":         "Density Pull",
    "point_attractor_enabled": False,     # on/off toggle
    "point_attractor_weight": 0.10,       # active weight when enabled
    "point_invert":           False,      # True = repel branches away from points
    "point_search_radius":    0.0,        # 0 = auto (2× influence_radius)
    "point_density_radius":   20.0,       # Density Pull: neighbour search radius
    "point_weight_default":   1.0,        # Weighted Strength: fallback weight
    "point_waypoint_active":  0,          # Waypoint Sequence: current gate index

    # Aggregation (post-bake stage)
    "agg_enabled":         False,
    "agg_manual_axis":     False,  # False = auto bbox detection (default); True = manual Start/End
    "agg_module_guids":    [],
    "agg_start_ref":       None,   # (x,y,z) tuple — modular geometry axis start (manual only)
    "agg_end_ref":         None,   # (x,y,z) tuple — modular geometry axis end   (manual only)
    "agg_scale_mode":      "Fit",  # "Fit" | "Repeat"
    "agg_module_gap":      0.40,   # pullback from each segment end (0 = flush, no gap)
    "agg_module_scale":    0.30,   # cross-section multiplier: 1.0=original width, 2.0=twice as thick
    "agg_joint_enabled":   False,
    # Node geometry — placed once at each branching node
    "agg_node_guids":      [],
    "agg_node_start_ref":  None,   # (x,y,z) — node geometry axis start
    "agg_node_end_ref":    None,   # (x,y,z) — node geometry axis end
    "agg_node_scale":      0.30,   # multiplier on auto-fit: 1.0=match bar width, 2.0=twice, 0.5=half
    # Arm geometry — placed once per connected branch at each node
    "agg_arm_guids":       [],
    "agg_arm_start_ref":   None,   # (x,y,z) — arm centre-side end
    "agg_arm_end_ref":     None,   # (x,y,z) — arm outer tip
    "agg_arm_offset":      0.30,   # distance from node centre to arm start (0 = at node centre)
    "agg_arm_scale":       0.30,   # multiplier: 1.0 = original modelled size
    "agg_seed":            42,
}

# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

class SCANode:
    __slots__ = ("id", "position", "xyz", "parent_id", "children", "depth")

    def __init__(self, nid, position, parent_id, depth):
        self.id        = nid
        self.position  = position
        self.xyz       = (position.X, position.Y, position.Z)
        self.parent_id = parent_id
        self.children  = []
        self.depth     = depth


class SCAAttractor:
    __slots__ = ("position", "xyz", "alive", "tag")

    def __init__(self, position, tag=""):
        self.position = position
        self.xyz      = (position.X, position.Y, position.Z)
        self.alive    = True
        self.tag      = tag

# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _depth_color(depth, max_depth):
    """Warm orange (root) → cool blue (tips)."""
    t = depth / float(max(max_depth, 1))
    r = int(220 + (70  - 220) * t)
    g = int(140 + (160 - 140) * t)
    b = int(40  + (220 - 40)  * t)
    return sd.Color.FromArgb(r, g, b)


def _get_or_create_layer(full_name, color):
    parts = full_name.split("::")
    for i in range(len(parts)):
        partial = "::".join(parts[:i + 1])
        if not rs.IsLayer(partial):
            c = color if i == len(parts) - 1 else sd.Color.FromArgb(180, 180, 180)
            rs.AddLayer(partial, c)
    idx = sc.doc.Layers.FindByFullPath(full_name, -1)
    if idx < 0:
        idx = sc.doc.Layers.FindByFullPath(full_name, 0)
    return idx


def _clear_sca_layers():
    for lname in (LAYER_BRANCHES, LAYER_PIPES):
        if not rs.IsLayer(lname):
            continue
        def _clear_recursive(layer_name):
            objs = rs.ObjectsByLayer(layer_name)
            if objs:
                rs.DeleteObjects(objs)
            layer_obj = sc.doc.Layers.FindByFullPath(layer_name, -1)
            if layer_obj >= 0:
                children = sc.doc.Layers[layer_obj].GetChildren()
                if children:
                    for ch in children:
                        _clear_recursive(ch.FullPath)
        _clear_recursive(lname)

# ─────────────────────────────────────────────────────────────────────────────
# CORE ALGORITHM — pure Python math (avoids .NET struct mutation)
# ─────────────────────────────────────────────────────────────────────────────

def _dist3(ax, ay, az, bx, by, bz):
    dx = ax - bx; dy = ay - by; dz = az - bz
    return math.sqrt(dx*dx + dy*dy + dz*dz)


def _norm3(dx, dy, dz):
    L = math.sqrt(dx*dx + dy*dy + dz*dz)
    if L < 1e-10:
        return (0.0, 0.0, 1.0)
    return (dx/L, dy/L, dz/L)


def _perp_to(d):
    """Return any unit vector perpendicular to direction tuple d."""
    x, y, z = d
    # Cross d with global Z: gives (y, -x, 0)
    px, py, pz = y, -x, 0.0
    L = math.sqrt(px*px + py*py + pz*pz)
    if L < 1e-6:
        # d is along Z — cross with global X instead: (0, z, -y)
        px, py, pz = 0.0, z, -y
        L = math.sqrt(px*px + py*py + pz*pz)
    if L < 1e-6:
        return (1.0, 0.0, 0.0)
    return (px/L, py/L, pz/L)


def _branch_plane_normal(branch_dirs):
    """Compute the unit normal to the best-fit plane of all branch directions.

    This is the direction MOST PERPENDICULAR to all branches — the correct
    axis for a flat disc node so that every arm radiates from the disc rim:

      2-way elbow  : cross(d0, d1)  → disc is the hinge plate
      3-way Y      : normal to the 3-branch plane
      4-way +      : normal to dominant branch plane
      2-way straight (collinear): no plane → disc becomes a collar,
                                  normal = any perpendicular to the branch

    Algorithm: sum all pairwise cross-product unit vectors, aligning each
    to a consistent hemisphere (flip sign when dot < 0 vs running reference)
    so symmetric branches reinforce rather than cancel.
    """
    n = len(branch_dirs)
    if n == 0:
        return (0.0, 0.0, 1.0)
    if n == 1:
        return _perp_to(branch_dirs[0])

    sx, sy, sz = 0.0, 0.0, 0.0
    ref = None  # first non-degenerate cross product sets the hemisphere

    for i in range(n):
        for j in range(i + 1, n):
            a = branch_dirs[i]
            b = branch_dirs[j]
            cx = a[1]*b[2] - a[2]*b[1]
            cy = a[2]*b[0] - a[0]*b[2]
            cz = a[0]*b[1] - a[1]*b[0]
            L = math.sqrt(cx*cx + cy*cy + cz*cz)
            if L < 1e-8:
                continue           # parallel / anti-parallel pair → skip
            cx, cy, cz = cx/L, cy/L, cz/L
            if ref is None:
                ref = (cx, cy, cz)
                sx, sy, sz = cx, cy, cz
            else:
                # Flip if pointing into the opposite hemisphere
                if ref[0]*cx + ref[1]*cy + ref[2]*cz < 0:
                    sx -= cx; sy -= cy; sz -= cz
                else:
                    sx += cx; sy += cy; sz += cz

    if ref is None:
        # All pairs were collinear (e.g. straight 2-way) → collar orientation
        return _perp_to(branch_dirs[0])

    return _norm3(sx, sy, sz)


def find_closest_node(qx, qy, qz, nodes):
    best_dist = float("inf")
    best_node = None
    for node in nodes:
        nx, ny, nz = node.xyz
        d = _dist3(qx, qy, qz, nx, ny, nz)
        if d < best_dist:
            best_dist = d
            best_node = node
    return best_node, best_dist


def grow_one_iteration(params, nodes, attractors, rng, inf_vec=None):
    """One SCA growth step.  inf_vec biases direction:
       - None          : pure SCA (V2 behaviour)
       - (dx,dy,dz)    : global unit vector added with influence_weight
       - "ClimateHeat" : per-node local gradient toward nearby hot voxels
                         (params["_heat_voxels"] = [(wx,wy,wz,heat), ...])

    Point Attractor Field (V3 new):
       params["_point_field"] = [(x,y,z,w), ...]  — persistent bias points.
       Applied on top of inf_vec.  w>0 = attract, w<0 = repel.
       Orbital Swirl behaviour uses tangential deflection instead of radial.
    """
    inf_r  = float(params["influence_radius"])
    kill_d = float(params["kill_distance"])
    step_d = float(params["step_distance"])
    noise  = float(params["random_noise"])
    inf_w  = float(params.get("influence_weight", 0.0)) if inf_vec else 0.0

    # Pre-fetch heat voxel list once per iteration (fast reference)
    heat_voxels   = params.get("_heat_voxels", []) if inf_vec == "ClimateHeat" else []
    heat_search_r = inf_r * 3.0   # search radius = 3× influence radius

    # Pre-fetch point attractor field once per iteration
    point_field = params.get("_point_field", [])
    pt_w        = float(params.get("point_attractor_weight", 0.0))
    if params.get("point_invert", False):
        pt_w = -pt_w   # negative weight = repel instead of attract
    pt_r_param  = float(params.get("point_search_radius", 0.0))
    pt_r        = pt_r_param if pt_r_param > 0.0 else inf_r * 2.5
    pt_behavior = params.get("point_behavior", "Density Pull")

    influence_map = {}

    for attr in attractors:
        if not attr.alive:
            continue
        ax, ay, az = attr.xyz
        node, dist = find_closest_node(ax, ay, az, nodes)
        if node is None or dist > inf_r:
            continue
        if dist < kill_d:
            attr.alive = False
            continue
        nx, ny, nz = node.xyz
        uvec = _norm3(ax - nx, ay - ny, az - nz)
        if node.id not in influence_map:
            influence_map[node.id] = []
        influence_map[node.id].append(uvec)

    new_nodes = []

    for node_id, vecs in influence_map.items():
        parent = nodes[node_id]
        px, py, pz = parent.xyz
        n = float(len(vecs))
        ax = sum(v[0] for v in vecs) / n
        ay = sum(v[1] for v in vecs) / n
        az = sum(v[2] for v in vecs) / n

        # ── Apply influence field ────────────────────────────────────────────
        if inf_w > 0 and inf_vec:
            if inf_vec == "ClimateHeat" and heat_voxels:
                # Local gradient: weighted direction toward nearby hot voxels.
                # w = heat² / (dist+1) so hot + close voxels pull hardest.
                # Branches in cool zones still grow but lean toward warmth.
                gx = gy = gz = tw = 0.0
                for (vx, vy, vz, h) in heat_voxels:
                    d = _dist3(px, py, pz, vx, vy, vz)
                    if 0.0 < d < heat_search_r:
                        w = (h * h) / (d + 1.0)
                        gx += (vx - px) * w
                        gy += (vy - py) * w
                        gz += (vz - pz) * w
                        tw += w
                if tw > 1e-6:
                    bvec = _norm3(gx, gy, gz)
                    ax += bvec[0] * inf_w
                    ay += bvec[1] * inf_w
                    az += bvec[2] * inf_w
            elif inf_vec != "ClimateHeat":
                # Global directional bias (Sun, Wind, Gravity, Custom)
                ax += inf_vec[0] * inf_w
                ay += inf_vec[1] * inf_w
                az += inf_vec[2] * inf_w
        # ────────────────────────────────────────────────────────────────────

        # ── Point Attractor Field (V3) ───────────────────────────────────────
        if pt_w != 0.0 and point_field:
            if pt_behavior == "Orbital Swirl":
                # Tangential deflection: cross(toward_point, Z-up) rotates branch
                # around the nearest point → spiral / vortex approach.
                for (fpx, fpy, fpz, fw) in point_field:
                    d = _dist3(px, py, pz, fpx, fpy, fpz)
                    if 0.0 < d < pt_r:
                        # Radial unit vector (node → point)
                        rx = (fpx - px) / d
                        ry = (fpy - py) / d
                        # Tangent in XY plane: rotate radial 90°
                        tx = -ry;  ty = rx
                        tl = math.sqrt(tx * tx + ty * ty)
                        if tl > 1e-6:
                            w = fw / (d + 1.0) * pt_w
                            ax += (tx / tl) * w
                            ay += (ty / tl) * w
                            # Z component stays from attractor pull — no vertical swirl
            else:
                # All other behaviours: weighted directional pull or push
                # w>0 → attract (node moves toward point)
                # w<0 → repel  (node moves away from point)
                gx = gy = gz = tw = 0.0
                for (fpx, fpy, fpz, fw) in point_field:
                    d = _dist3(px, py, pz, fpx, fpy, fpz)
                    if 0.0 < d < pt_r:
                        # Linear falloff: full effect at d=0, zero at d=pt_r
                        falloff = 1.0 - (d / pt_r)
                        w = fw * falloff * falloff   # quadratic falloff — smooth edges
                        gx += (fpx - px) / d * w
                        gy += (fpy - py) / d * w
                        gz += (fpz - pz) / d * w
                        tw += abs(w)
                if tw > 1e-6:
                    bvec = _norm3(gx, gy, gz)
                    ax += bvec[0] * pt_w
                    ay += bvec[1] * pt_w
                    az += bvec[2] * pt_w
        # ────────────────────────────────────────────────────────────────────

        ax += rng.uniform(-1.0, 1.0) * noise
        ay += rng.uniform(-1.0, 1.0) * noise
        az += rng.uniform(-1.0, 1.0) * noise
        ax, ay, az = _norm3(ax, ay, az)

        cx = px + ax * step_d
        cy = py + ay * step_d
        cz = pz + az * step_d
        nid = len(nodes) + len(new_nodes)
        child = SCANode(nid, rg.Point3d(cx, cy, cz), node_id, parent.depth + 1)
        parent.children.append(nid)
        new_nodes.append(child)

    return new_nodes

# ─────────────────────────────────────────────────────────────────────────────
# INFLUENCE FIELD BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _solar_position(month_idx, hour_float):
    """Melbourne approximate solar position → (azimuth_deg, altitude_deg).
    Self-contained — no external imports needed."""
    lat  = math.radians(-37.8)
    decl = math.radians(23.45 * math.sin(math.radians(360.0/365.0*(284.0 + month_idx*30.4))))
    ha   = math.radians((hour_float - 12.0) * 15.0)
    sin_alt = (math.sin(lat)*math.sin(decl) +
               math.cos(lat)*math.cos(decl)*math.cos(ha))
    sin_alt = _clamp(sin_alt, -1.0, 1.0)
    alt  = math.asin(sin_alt)
    az   = math.atan2(-math.cos(decl)*math.sin(ha),
                      math.sin(decl)*math.cos(lat) -
                      math.cos(decl)*math.cos(ha)*math.sin(lat))
    return (math.degrees(az) % 360.0, math.degrees(alt))


def _build_influence_vec(params):
    """Compute influence bias vector once before the growth loop.

    Returns:
      None           — no influence (pure V1 SCA)
      (dx, dy, dz)   — global unit vector applied to every branch
      "ClimateHeat"  — sentinel; per-node local gradient from params["_heat_voxels"]
                       (list of (wx,wy,wz,heat) tuples for all voxels)
    """
    inf_type = params.get("influence_type", "None")

    if inf_type == "Climate Heat Index":
        # ── Source A: Climate Comfort Special V1  (ccs_data) ─────────────────
        # Format: list of dicts {ix, iy, iz, heat_index, solar, ...}
        ccs       = sc.sticky.get("ccs_data")
        # ── Source B: Melbourne Climate Voxel Attractor V1 (climate_voxels) ──
        # Format: list of tuples (ix, iy, iz, density)
        clim_vox  = sc.sticky.get("climate_voxels")

        if not ccs and not clim_vox:
            print("SCA V2  WARNING: no climate sticky data found.\n"
                  "  Run Melbourne Climate Voxel Attractor V1 (writes climate_voxels)\n"
                  "  OR Climate Comfort Special V1 (writes ccs_data).  Influence disabled.")
            return None

        gx = gy = gz = total_w = 0.0

        if ccs:
            # Climate Comfort Special V1 format
            origin    = sc.sticky.get("ccs_origin", rg.Point3d.Origin)
            cell_size = float(sc.sticky.get("ccs_cell_size", 1.0))
            ox = origin.X if hasattr(origin, "X") else float(origin[0]) if origin else 0.0
            oy = origin.Y if hasattr(origin, "Y") else float(origin[1]) if origin else 0.0
            oz = origin.Z if hasattr(origin, "Z") else float(origin[2]) if origin else 0.0
            for v in ccs:
                h = float(v.get("heat_index", 0.0))
                gx += (ox + v["ix"] * cell_size) * h
                gy += (oy + v["iy"] * cell_size) * h
                gz += (oz + v["iz"] * cell_size) * h
                total_w += h
            source_name = "ccs_data ({} voxels)".format(len(ccs))

        else:
            # Melbourne Climate Voxel Attractor V1 format
            # climate_voxels = [(ix, iy, iz, density), ...]
            # climate_origin  = (ox, oy, oz) plain tuple
            # climate_cell_size = float step
            origin_raw = sc.sticky.get("climate_origin", (0.0, 0.0, 0.0))
            cell_size  = float(sc.sticky.get("climate_cell_size", 1.0))
            ox = float(origin_raw[0]) if origin_raw else 0.0
            oy = float(origin_raw[1]) if origin_raw else 0.0
            oz = float(origin_raw[2]) if origin_raw else 0.0
            for v in clim_vox:
                # v = (ix, iy, iz, density)
                h = float(v[3])
                gx += (ox + v[0] * cell_size) * h
                gy += (oy + v[1] * cell_size) * h
                gz += (oz + v[2] * cell_size) * h
                total_w += h
            source_name = "climate_voxels ({} voxels)".format(len(clim_vox))

        if total_w < 1e-6:
            print("SCA V2  WARNING: climate data weights all zero.  Influence disabled.")
            return None

        # Build per-voxel world-position + heat list for local gradient sampling
        # (replaces single centroid — branches sample locally, not globally)
        heat_voxels = []
        if ccs:
            origin    = sc.sticky.get("ccs_origin", rg.Point3d.Origin)
            cell_size = float(sc.sticky.get("ccs_cell_size", 1.0))
            ox2 = origin.X if hasattr(origin, "X") else float(origin[0]) if origin else 0.0
            oy2 = origin.Y if hasattr(origin, "Y") else float(origin[1]) if origin else 0.0
            oz2 = origin.Z if hasattr(origin, "Z") else float(origin[2]) if origin else 0.0
            for v in ccs:
                h = float(v.get("heat_index", 0.0))
                heat_voxels.append((ox2 + v["ix"]*cell_size,
                                    oy2 + v["iy"]*cell_size,
                                    oz2 + v["iz"]*cell_size, h))
        else:
            origin_raw = sc.sticky.get("climate_origin", (0.0, 0.0, 0.0))
            cell_size  = float(sc.sticky.get("climate_cell_size", 1.0))
            ox2 = float(origin_raw[0]) if origin_raw else 0.0
            oy2 = float(origin_raw[1]) if origin_raw else 0.0
            oz2 = float(origin_raw[2]) if origin_raw else 0.0
            for v in clim_vox:
                heat_voxels.append((ox2 + v[0]*cell_size,
                                    oy2 + v[1]*cell_size,
                                    oz2 + v[2]*cell_size, float(v[3])))

        params["_heat_voxels"] = heat_voxels
        print("SCA V2  Climate heat field: {} voxels ready  source={}".format(
              len(heat_voxels), source_name))
        return "ClimateHeat"

    elif inf_type == "Sun Direction":
        month = int(params.get("sun_month", 6))
        hour  = float(params.get("sun_hour", 12.0))
        az, alt = _solar_position(month, hour)
        if alt <= 0:
            print("SCA V2  WARNING: sun is below horizon for month={} hour={}.  "
                  "Influence will point downward.".format(month, hour))
        az_r  = math.radians(az)
        alt_r = math.radians(alt)
        sx = math.cos(alt_r) * math.sin(az_r)
        sy = math.cos(alt_r) * math.cos(az_r)
        sz = math.sin(alt_r)
        vec = _norm3(sx, sy, sz)
        print("SCA V2  Sun vector: ({:.2f}, {:.2f}, {:.2f})  "
              "az={:.1f}° alt={:.1f}°".format(vec[0], vec[1], vec[2], az, alt))
        return vec

    elif inf_type == "Wind":
        deg = float(params.get("wind_direction", 225.0))
        rad = math.radians(deg)
        vec = _norm3(math.sin(rad), math.cos(rad), 0.0)
        print("SCA V2  Wind vector: ({:.2f}, {:.2f}, 0)  "
              "dir={}°N".format(vec[0], vec[1], deg))
        return vec

    elif inf_type == "Gravity":
        print("SCA V2  Influence: Gravity (0, 0, -1)")
        return (0.0, 0.0, -1.0)

    elif inf_type == "Custom XYZ":
        ix = float(params.get("custom_ix", 0.0))
        iy = float(params.get("custom_iy", 0.0))
        iz = float(params.get("custom_iz", 1.0))
        vec = _norm3(ix, iy, iz)
        print("SCA V2  Custom vector: ({:.2f}, {:.2f}, {:.2f})".format(*vec))
        return vec

    return None  # "None" type

# ─────────────────────────────────────────────────────────────────────────────
# POINT ATTRACTOR FIELD BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_point_field(params):
    """Build the point attractor field from picked Rhino point objects.

    Stores params["_point_field"] = [(x, y, z, weight), ...]
    Weight > 0  = attract toward this point.
    Weight < 0  = repel away from this point.
    Points are NEVER consumed — they persistently bias every growth step.

    For Waypoint Sequence, also stores:
      params["_waypoint_positions"] = [(x,y,z), ...]
      params["_waypoint_active"]    = int  (index of current gate)
    """
    import re as _re

    guids = params.get("point_guids", [])
    if not guids:
        params["_point_field"] = []
        return

    behavior = params.get("point_behavior", "Density Pull")

    # Collect (Point3d, DocObject) pairs from picked GUIDs
    pts = []
    for g in guids:
        obj = sc.doc.Objects.FindId(g)
        if not obj or obj.IsDeleted:
            continue
        geo = obj.Geometry
        if isinstance(geo, rg.Point):
            pts.append((geo.Location, obj))

    if not pts:
        params["_point_field"] = []
        print("SCA V3  Point field: no valid point objects found.")
        return

    positions = [p for p, _ in pts]
    objects   = [o for _, o in pts]

    # ── Density Pull ─────────────────────────────────────────────────────────
    if behavior == "Density Pull":
        r = float(params.get("point_density_radius", 20.0))
        field = []
        for i, pos in enumerate(positions):
            px, py, pz = pos.X, pos.Y, pos.Z
            neighbors = sum(
                1 for j, p2 in enumerate(positions)
                if j != i and _dist3(px, py, pz, p2.X, p2.Y, p2.Z) < r
            )
            # Isolated point → weight 1.  Clustered → proportionally stronger.
            weight = 1.0 + neighbors * 1.5
            field.append((px, py, pz, weight))
        params["_point_field"] = field

    # ── Repulsion ────────────────────────────────────────────────────────────
    elif behavior == "Repulsion":
        # Negative weight → direction flips in grow_one_iteration
        params["_point_field"] = [(p.X, p.Y, p.Z, -1.0) for p in positions]

    # ── Weighted Strength ────────────────────────────────────────────────────
    elif behavior == "Weighted Strength":
        default_w = float(params.get("point_weight_default", 1.0))
        field = []
        for pos, obj in zip(positions, objects):
            w = default_w
            name = obj.Attributes.Name or ""
            m = _re.search(r'w(?:eight)?[=:]\s*(\d+(?:\.\d+)?)', name, _re.IGNORECASE)
            if m:
                try:
                    w = float(m.group(1))
                except Exception:
                    pass
            field.append((pos.X, pos.Y, pos.Z, w))
        params["_point_field"] = field

    # ── Depth Gradient ───────────────────────────────────────────────────────
    elif behavior == "Depth Gradient":
        zs      = [p.Z for p in positions]
        z_min   = min(zs)
        z_range = max(max(zs) - z_min, 1e-6)
        field   = []
        for pos in positions:
            t = (pos.Z - z_min) / z_range   # 0 (low) → 1 (high)
            w = 0.3 + t * 2.7               # 0.3 (lowest) → 3.0 (highest)
            field.append((pos.X, pos.Y, pos.Z, w))
        params["_point_field"] = field

    # ── Waypoint Sequence ────────────────────────────────────────────────────
    elif behavior == "Waypoint Sequence":
        # Store all waypoints; grow toward the active one only.
        # run_simulation advances _waypoint_active when SCA reaches each gate.
        wp_positions = [(p.X, p.Y, p.Z) for p in positions]
        params["_waypoint_positions"] = wp_positions
        params["_waypoint_active"]    = 0
        # Initial field = just the first waypoint
        if wp_positions:
            wx, wy, wz = wp_positions[0]
            params["_point_field"] = [(wx, wy, wz, 2.0)]
        else:
            params["_point_field"] = []

    # ── Orbital Swirl ────────────────────────────────────────────────────────
    elif behavior == "Orbital Swirl":
        # Weight = 1 for all (the swirl direction is handled in grow_one_iteration)
        params["_point_field"] = [(p.X, p.Y, p.Z, 1.0) for p in positions]

    else:
        params["_point_field"] = [(p.X, p.Y, p.Z, 1.0) for p in positions]

    print("SCA V3  Point field: {} points  behaviour={}  weight={:.2f}".format(
          len(positions), behavior,
          float(params.get("point_attractor_weight", 0.0))))

# ─────────────────────────────────────────────────────────────────────────────
# ATTRACTOR GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def _gen_attractors_mode0(params, rng):
    bx, by, bz = params["bbox_x"], params["bbox_y"], params["bbox_z"]
    return [SCAAttractor(rg.Point3d(
        rng.uniform(0.0, bx), rng.uniform(0.0, by), rng.uniform(0.0, bz)),
        tag="box") for _ in range(int(params["num_attractors"]))]


def _gen_attractors_mode1(params):
    """Voxel bounding-box centres — handles joined meshes via ExplodeAtUnweldedEdges."""
    guids      = params.get("voxel_guids", [])
    layer_filt = params.get("voxel_layer_filter", "").strip()
    accepted   = (Rhino.DocObjects.ObjectType.Brep,
                  Rhino.DocObjects.ObjectType.Extrusion,
                  Rhino.DocObjects.ObjectType.Mesh,
                  Rhino.DocObjects.ObjectType.SubD)
    candidates = []

    def _extract_centres(geo):
        if isinstance(geo, rg.Mesh):
            pieces = geo.ExplodeAtUnweldedEdges()
            if pieces:
                for piece in pieces:
                    bb = piece.GetBoundingBox(True)
                    if bb.IsValid:
                        candidates.append(bb.Center)
                return
            for fi in range(geo.Faces.Count):
                candidates.append(geo.Faces.GetFaceCenter(fi))
            return
        bb = geo.GetBoundingBox(True)
        if bb.IsValid:
            candidates.append(bb.Center)

    if guids:
        for g in guids:
            obj = sc.doc.Objects.FindId(g)
            if obj and not obj.IsDeleted and obj.ObjectType in accepted:
                _extract_centres(obj.Geometry)
    elif layer_filt:
        for obj in sc.doc.Objects:
            if obj.IsDeleted or obj.ObjectType not in accepted:
                continue
            ln = sc.doc.Layers[obj.Attributes.LayerIndex].FullPath
            if layer_filt in ln:
                _extract_centres(obj.Geometry)

    return [SCAAttractor(pt, tag="voxel") for pt in candidates]


def _gen_attractors_mode2(params, rng):
    """UV-sample attractors on a picked surface, mesh, or SubD.

    3D Growth modes (when surface_3d_mode is True):
      "Offset" — each surface point is offset outward by surface_growth_depth
                 along its surface normal.  One attractor per UV sample.
      "Shells" — surface_shell_count concentric attractor layers from 0 to
                 surface_growth_depth.  Multiplies attractor count by shell_count.

    Flat mode (surface_3d_mode False, default) — unchanged from V3.
    """
    guids = params.get("surface_guids", [])
    if not guids:
        return []
    u_div   = int(params["surface_u_div"])
    v_div   = int(params["surface_v_div"])
    noise   = float(params["surface_noise"])
    mode3d  = bool(params.get("surface_3d_mode", False))
    typ3d   = params.get("surface_3d_type", "Offset")
    depth   = float(params.get("surface_growth_depth", 10.0))
    n_shells= max(2, int(params.get("surface_shell_count", 3)))
    result  = []

    def _add_pt(pt, nx, ny, nz):
        """Add attractor(s) for a surface point + outward unit normal."""
        if not pt.IsValid:
            return
        if not mode3d:
            result.append(SCAAttractor(pt, tag="surface"))
            return
        if typ3d == "Shells":
            for s in range(n_shells):
                t = s / float(n_shells - 1) if n_shells > 1 else 1.0
                d = depth * t
                op = rg.Point3d(pt.X + nx*d, pt.Y + ny*d, pt.Z + nz*d)
                result.append(SCAAttractor(op, tag="surface"))
        else:  # "Offset" — single cloud at full depth
            op = rg.Point3d(pt.X + nx*depth, pt.Y + ny*depth, pt.Z + nz*depth)
            result.append(SCAAttractor(op, tag="surface"))

    def _sample_geo(geo):
        """Sample attractors from one geometry object."""
        # ── Mesh ──────────────────────────────────────────────────────────────
        if isinstance(geo, rg.Mesh):
            geo.FaceNormals.ComputeFaceNormals()
            for fi in range(geo.Faces.Count):
                pt = geo.Faces.GetFaceCenter(fi)
                fn = geo.FaceNormals[fi]
                _add_pt(pt, fn.X, fn.Y, fn.Z)
            return

        # ── SubD ──────────────────────────────────────────────────────────────
        if isinstance(geo, rg.SubD):
            mesh = rg.Mesh.CreateFromSubD(geo, 3)
            if mesh and mesh.IsValid:
                mesh.FaceNormals.ComputeFaceNormals()
                for fi in range(mesh.Faces.Count):
                    pt = mesh.Faces.GetFaceCenter(fi)
                    fn = mesh.FaceNormals[fi]
                    _add_pt(pt, fn.X, fn.Y, fn.Z)
            return

        # ── NURBS surface / Brep ───────────────────────────────────────────────
        nsfrs = []
        if isinstance(geo, rg.Brep):
            for face in geo.Faces:
                ns = face.ToNurbsSurface()
                if ns:
                    nsfrs.append(ns)
        elif isinstance(geo, rg.NurbsSurface):
            nsfrs.append(geo)
        elif hasattr(geo, "ToNurbsSurface"):
            ns = geo.ToNurbsSurface()
            if ns:
                nsfrs.append(ns)

        for nsrf in nsfrs:
            ud = nsrf.Domain(0)
            vd = nsrf.Domain(1)
            for i in range(u_div):
                for j in range(v_div):
                    uf = _clamp((i + 0.5 + rng.uniform(-1.0, 1.0) * noise) / u_div, 0.0, 1.0)
                    vf = _clamp((j + 0.5 + rng.uniform(-1.0, 1.0) * noise) / v_div, 0.0, 1.0)
                    u  = ud.ParameterAt(uf)
                    v  = vd.ParameterAt(vf)
                    pt = nsrf.PointAt(u, v)
                    if mode3d:
                        nv = nsrf.NormalAt(u, v)
                        nv.Unitize()
                        _add_pt(pt, nv.X, nv.Y, nv.Z)
                    else:
                        _add_pt(pt, 0.0, 0.0, 1.0)

    # Iterate over all picked surfaces
    for guid in guids:
        obj = sc.doc.Objects.FindId(guid)
        if obj and not obj.IsDeleted:
            _sample_geo(obj.Geometry)

    return result


def _gen_attractors_mode3(params, rng):
    """Climate-weighted attractors — Z-position as radiation proxy."""
    guids = params.get("climate_voxel_guids", [])
    bias  = float(params.get("radiation_bias", 3.0))
    accepted = (Rhino.DocObjects.ObjectType.Brep,
                Rhino.DocObjects.ObjectType.Extrusion,
                Rhino.DocObjects.ObjectType.Mesh,
                Rhino.DocObjects.ObjectType.SubD)
    centres = []
    for g in guids:
        obj = sc.doc.Objects.FindId(g)
        if obj and not obj.IsDeleted and obj.ObjectType in accepted:
            bb = obj.Geometry.GetBoundingBox(True)
            if bb.IsValid:
                centres.append(bb.Center)
    if not centres:
        return []
    z_vals = [c.Z for c in centres]
    z_min, z_range = min(z_vals), max(max(z_vals) - min(z_vals), 1e-6)
    result = []
    for c in centres:
        t     = (c.Z - z_min) / z_range
        count = max(1, int(round(1.0 + (bias - 1.0) * t)))
        for _ in range(count):
            pt = rg.Point3d(c.X + rng.uniform(-3.0, 3.0),
                            c.Y + rng.uniform(-3.0, 3.0),
                            c.Z + rng.uniform(-2.0, 2.0))
            result.append(SCAAttractor(pt, tag="climate"))
    return result


def _gen_attractors_mode4(params, rng):
    bx, by, bz = params["site_bbox_x"], params["site_bbox_y"], params["site_bbox_z"]
    n = int(params["site_num_attractors"])
    return [SCAAttractor(rg.Point3d(
        rng.uniform(0.0, bx), rng.uniform(0.0, by), rng.uniform(0.0, bz)),
        tag="site") for _ in range(n)]


def _gen_attractors_mode5(params, rng):
    """Mode 5 — Curve Network: sample points along picked curves."""
    guids   = params.get("curve_guids", [])
    n_pts   = max(2, int(params.get("curve_sample_count", 30)))
    noise   = float(params.get("curve_noise", 0.0))
    result  = []

    for g in guids:
        obj = sc.doc.Objects.FindId(g)
        if not obj or obj.IsDeleted:
            continue
        geo = obj.Geometry
        if not isinstance(geo, rg.Curve):
            continue
        dom = geo.Domain
        for i in range(n_pts):
            t_norm = i / float(n_pts - 1) if n_pts > 1 else 0.5
            t = dom.ParameterAt(t_norm)
            pt = geo.PointAt(t)
            if not pt.IsValid:
                continue
            if noise > 0:
                pt = rg.Point3d(pt.X + rng.uniform(-1.0, 1.0) * noise,
                                pt.Y + rng.uniform(-1.0, 1.0) * noise,
                                pt.Z + rng.uniform(-1.0, 1.0) * noise)
            result.append(SCAAttractor(pt, tag="curve"))

    return result

# ─────────────────────────────────────────────────────────────────────────────
# ROOT PLACERS
# ─────────────────────────────────────────────────────────────────────────────

def _place_roots(attractors, params, rng):
    """Scatter num_roots below the attractor cloud (Z = zmin - step_distance)."""
    if not attractors:
        return []
    xs   = [a.xyz[0] for a in attractors]
    ys   = [a.xyz[1] for a in attractors]
    zs   = [a.xyz[2] for a in attractors]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    root_z = min(zs) - float(params["step_distance"])
    nodes  = []
    for i in range(int(params["num_roots"])):
        x = rng.uniform(min_x + 0.1*(max_x - min_x), min_x + 0.9*(max_x - min_x))
        y = rng.uniform(min_y + 0.1*(max_y - min_y), min_y + 0.9*(max_y - min_y))
        nodes.append(SCANode(i, rg.Point3d(x, y, root_z), None, 0))
    return nodes


def _place_roots_on_surface(attractors, params, rng):
    """Mode 2: roots chosen from lowest-Z attractors.

    In flat mode, roots sit ON the surface (attractors are already on surface).
    In 3D mode, attractors are offset — so to anchor roots ON the surface we
    need the raw surface point.  We recompute it by projecting back to the
    surface, then apply surface_root_offset along the surface normal.
    When surface_root_offset = 0 (default), roots are placed on the surface face.
    """
    if not attractors:
        return []
    num         = int(params["num_roots"])
    mode3d      = bool(params.get("surface_3d_mode", False))
    root_offset = float(params.get("surface_root_offset", 0.0))

    # Pool = lowest-Z attractors (bottom 20% or at least num_roots)
    pool   = sorted(attractors, key=lambda a: a.xyz[2])
    pool   = pool[:max(num, len(pool) // 5)]
    chosen = rng.sample(pool, min(num, len(pool)))

    if not mode3d or root_offset == 0.0:
        # Flat mode OR 3D mode with roots on surface — use attractor positions directly
        # In flat mode: attractors are ON the surface → correct.
        # In 3D mode with root_offset=0: we want roots on the surface, so project back.
        if mode3d:
            proj = _build_surface_projector(params)
            if proj:
                nodes = []
                for i, a in enumerate(chosen):
                    px, py, pz = proj(a.xyz[0], a.xyz[1], a.xyz[2])
                    nodes.append(SCANode(i, rg.Point3d(px, py, pz), None, 0))
                return nodes
        return [SCANode(i, rg.Point3d(a.xyz[0], a.xyz[1], a.xyz[2]), None, 0)
                for i, a in enumerate(chosen)]

    # 3D mode with root_offset > 0: project each attractor to the CLOSEST surface
    # then offset along that surface's normal.
    guids = params.get("surface_guids", [])
    nodes = []
    for i, a in enumerate(chosen):
        ax, ay, az = a.xyz[0], a.xyz[1], a.xyz[2]
        best_rx, best_ry, best_rz = ax, ay, az
        best_nx, best_ny, best_nz = 0.0, 0.0, 1.0
        best_d = float("inf")

        for guid in guids:
            obj = sc.doc.Objects.FindId(guid)
            if not obj or obj.IsDeleted:
                continue
            geo = obj.Geometry
            if isinstance(geo, (rg.Mesh, rg.SubD)):
                mesh = (rg.Mesh.CreateFromSubD(geo, 3)
                        if isinstance(geo, rg.SubD) else geo)
                if not mesh:
                    continue
                sp = mesh.ClosestPoint(rg.Point3d(ax, ay, az))
                if sp.IsValid:
                    d = (sp.X-ax)**2 + (sp.Y-ay)**2 + (sp.Z-az)**2
                    if d < best_d:
                        best_d = d
                        best_rx, best_ry, best_rz = sp.X, sp.Y, sp.Z
                        mesh.FaceNormals.ComputeFaceNormals()
                        mpt = mesh.ClosestMeshPoint(sp, 0)
                        fi  = mpt.FaceIndex if mpt else -1
                        if 0 <= fi < mesh.FaceNormals.Count:
                            fn = mesh.FaceNormals[fi]
                            best_nx, best_ny, best_nz = fn.X, fn.Y, fn.Z
            else:
                nsfrs = []
                if isinstance(geo, rg.Brep):
                    for face in geo.Faces:
                        ns = face.ToNurbsSurface()
                        if ns: nsfrs.append(ns)
                elif isinstance(geo, rg.NurbsSurface):
                    nsfrs.append(geo)
                for nsrf in nsfrs:
                    ok, u, v = nsrf.ClosestPoint(rg.Point3d(ax, ay, az))
                    if ok:
                        sp = nsrf.PointAt(u, v)
                        d  = (sp.X-ax)**2 + (sp.Y-ay)**2 + (sp.Z-az)**2
                        if d < best_d:
                            best_d = d
                            best_rx, best_ry, best_rz = sp.X, sp.Y, sp.Z
                            nv = nsrf.NormalAt(u, v); nv.Unitize()
                            best_nx, best_ny, best_nz = nv.X, nv.Y, nv.Z

        pt = rg.Point3d(best_rx + best_nx * root_offset,
                        best_ry + best_ny * root_offset,
                        best_rz + best_nz * root_offset)
        nodes.append(SCANode(i, pt, None, 0))
    return nodes


def _place_roots_clusters(attractors, params, rng):
    """Mode 4: multiple building-cluster root groups below the attractor cloud."""
    if not attractors:
        return []
    xs     = [a.xyz[0] for a in attractors]
    ys     = [a.xyz[1] for a in attractors]
    root_z = min(a.xyz[2] for a in attractors) - float(params["step_distance"])
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    num_clusters      = max(1, int(params["num_clusters"]))
    roots_per_cluster = max(1, int(params["num_roots"]) // num_clusters)
    cluster_r         = min(max_x - min_x, max_y - min_y) / (num_clusters * 3.0)
    nodes = []; nid = 0
    for _ in range(num_clusters):
        cx = rng.uniform(min_x + 0.15*(max_x-min_x), min_x + 0.85*(max_x-min_x))
        cy = rng.uniform(min_y + 0.15*(max_y-min_y), min_y + 0.85*(max_y-min_y))
        for _ in range(roots_per_cluster):
            angle = rng.uniform(0.0, 2.0*math.pi)
            d     = rng.uniform(0.0, cluster_r)
            nodes.append(SCANode(nid, rg.Point3d(
                cx + d*math.cos(angle), cy + d*math.sin(angle), root_z), None, 0))
            nid += 1
    return nodes


def _build_surface_projector(params):
    """Return project(x,y,z)->(px,py,pz) closure for Mode 2 surface constraint.
    Supports multiple surfaces — projects to the closest point across all of them.
    """
    guids = params.get("surface_guids", [])
    if not guids:
        return None

    # Pre-build per-object projectors; collect meshes + nurbs surfaces once
    meshes = []   # list of Mesh objects
    nsfrs  = []   # list of NurbsSurface objects

    for guid in guids:
        obj = sc.doc.Objects.FindId(guid)
        if not obj or obj.IsDeleted:
            continue
        geo = obj.Geometry
        if isinstance(geo, rg.Mesh):
            meshes.append(geo)
        elif isinstance(geo, rg.SubD):
            mesh = rg.Mesh.CreateFromSubD(geo, 3)
            if mesh and mesh.IsValid:
                meshes.append(mesh)
        else:
            if isinstance(geo, rg.Brep):
                for face in geo.Faces:
                    ns = face.ToNurbsSurface()
                    if ns: nsfrs.append(ns)
            elif isinstance(geo, rg.NurbsSurface):
                nsfrs.append(geo)
            elif hasattr(geo, "ToNurbsSurface"):
                ns = geo.ToNurbsSurface()
                if ns: nsfrs.append(ns)

    if not meshes and not nsfrs:
        return None

    def _proj_multi(x, y, z):
        pt = rg.Point3d(x, y, z)
        best_pt = None; best_d = float("inf")
        for mesh in meshes:
            cp = mesh.ClosestPoint(pt)
            if cp.IsValid:
                d = (cp.X-x)**2 + (cp.Y-y)**2 + (cp.Z-z)**2
                if d < best_d:
                    best_d = d; best_pt = (cp.X, cp.Y, cp.Z)
        for ns in nsfrs:
            ok, u, v = ns.ClosestPoint(pt)
            if ok:
                cp = ns.PointAt(u, v)
                if cp.IsValid:
                    d = (cp.X-x)**2 + (cp.Y-y)**2 + (cp.Z-z)**2
                    if d < best_d:
                        best_d = d; best_pt = (cp.X, cp.Y, cp.Z)
        return best_pt if best_pt else (x, y, z)

    return _proj_multi

# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT / BAKING
# ─────────────────────────────────────────────────────────────────────────────

def _radius_at_depth(depth, max_depth, base_r, taper):
    t = 1.0 - depth / float(max(max_depth, 1))
    return base_r + (base_r * taper - base_r) * t


def _bake_result(nodes, params):
    if not nodes:
        return
    tol     = sc.doc.ModelAbsoluteTolerance
    ang_tol = sc.doc.ModelAngleToleranceRadians
    max_d   = max(n.depth for n in nodes)
    _get_or_create_layer(LAYER_BRANCHES, sd.Color.FromArgb(220, 140, 40))
    depth_layer_idx = {}

    for node in nodes:
        if node.parent_id is None:
            continue
        parent = nodes[node.parent_id]
        d = node.depth
        if d not in depth_layer_idx:
            sub = "{}::Depth_{}".format(LAYER_BRANCHES, d)
            depth_layer_idx[d] = _get_or_create_layer(sub, _depth_color(d, max_d))
        crv = rg.Line(parent.position, node.position).ToNurbsCurve()
        oid = sc.doc.Objects.AddCurve(crv)
        if oid != System.Guid.Empty:
            obj = sc.doc.Objects.FindId(oid)
            if obj:
                obj.Attributes.LayerIndex = depth_layer_idx[d]
                obj.CommitChanges()

    if params.get("output_pipes"):
        pipe_idx = _get_or_create_layer(LAYER_PIPES, sd.Color.FromArgb(180, 100, 40))
        for node in nodes:
            if node.parent_id is None:
                continue
            parent = nodes[node.parent_id]
            r   = _radius_at_depth(node.depth, max_d, params["pipe_radius"], params["taper_ratio"])
            crv = rg.Line(parent.position, node.position).ToNurbsCurve()
            pipes = rg.Brep.CreatePipe(crv, r, False, rg.PipeCapMode.Flat, True, tol, ang_tol)
            if pipes:
                for pipe in pipes:
                    oid = sc.doc.Objects.AddBrep(pipe)
                    if oid != System.Guid.Empty:
                        obj = sc.doc.Objects.FindId(oid)
                        if obj:
                            obj.Attributes.LayerIndex = pipe_idx
                            obj.CommitChanges()

# ─────────────────────────────────────────────────────────────────────────────
# AGGREGATION SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

LAYER_AGG          = "SCA_Aggregation"
LAYER_AGG_MODULAR  = "SCA_Aggregation::Modular"
LAYER_AGG_JNT_NODE = "SCA_Aggregation::Joint_Node"
LAYER_AGG_JNT_ARM  = "SCA_Aggregation::Joint_Arm"


def _clear_aggregation_layers():
    """Delete all objects on SCA_Aggregation and its children."""
    for lname in (LAYER_AGG_MODULAR, LAYER_AGG_JNT_NODE, LAYER_AGG_JNT_ARM, LAYER_AGG):
        if not rs.IsLayer(lname):
            continue
        objs = rs.ObjectsByLayer(lname)
        if objs:
            rs.DeleteObjects(objs)


def _get_agg_segments(nodes):
    """Return list of (start_Point3d, end_Point3d, depth) from node tree."""
    segs = []
    for node in nodes:
        if node.parent_id is None:
            continue
        parent = nodes[node.parent_id]
        segs.append((parent.position, node.position, node.depth))
    return segs


def _get_joint_nodes(nodes):
    """Return ALL internal nodes (have parent AND at least one child).
    Includes 1-to-1 linear connections AND branching nodes.
    Excludes roots (no parent) and tips (no children)."""
    return [n for n in nodes if n.parent_id is not None and n.children]


def _auto_ref_pts(guid):
    """Detect geometry's primary axis from its bounding box longest dimension.
    Returns (start_Point3d, end_Point3d) centred on the cross-section midpoint.
    Used when the user has not manually set Start/End reference points."""
    obj = sc.doc.Objects.FindId(guid)
    if not obj or obj.IsDeleted:
        return None, None
    bb = obj.Geometry.GetBoundingBox(True)
    if not bb.IsValid:
        return None, None
    dx = bb.Max.X - bb.Min.X
    dy = bb.Max.Y - bb.Min.Y
    dz = bb.Max.Z - bb.Min.Z
    cx = (bb.Min.X + bb.Max.X) * 0.5
    cy = (bb.Min.Y + bb.Max.Y) * 0.5
    cz = (bb.Min.Z + bb.Max.Z) * 0.5
    if dx >= dy and dx >= dz:      # X is longest
        return (rg.Point3d(bb.Min.X, cy, cz),
                rg.Point3d(bb.Max.X, cy, cz))
    elif dy >= dz:                 # Y is longest
        return (rg.Point3d(cx, bb.Min.Y, cz),
                rg.Point3d(cx, bb.Max.Y, cz))
    else:                          # Z is longest
        return (rg.Point3d(cx, cy, bb.Min.Z),
                rg.Point3d(cx, cy, bb.Max.Z))


def _auto_short_ref_pts(guid):
    """Detect geometry's SHORTEST bbox axis — used for node joints so they sit
    flat (perpendicular) at the branch junction rather than rolling along it.
    E.g. a flat disc: short axis = height → face perpendicular to branch."""
    obj = sc.doc.Objects.FindId(guid)
    if not obj or obj.IsDeleted:
        return None, None
    bb = obj.Geometry.GetBoundingBox(True)
    if not bb.IsValid:
        return None, None
    dx = bb.Max.X - bb.Min.X
    dy = bb.Max.Y - bb.Min.Y
    dz = bb.Max.Z - bb.Min.Z
    cx = (bb.Min.X + bb.Max.X) * 0.5
    cy = (bb.Min.Y + bb.Max.Y) * 0.5
    cz = (bb.Min.Z + bb.Max.Z) * 0.5
    if dx <= dy and dx <= dz:      # X is shortest
        return (rg.Point3d(bb.Min.X, cy, cz),
                rg.Point3d(bb.Max.X, cy, cz))
    elif dy <= dz:                  # Y is shortest
        return (rg.Point3d(cx, bb.Min.Y, cz),
                rg.Point3d(cx, bb.Max.Y, cz))
    else:                           # Z is shortest
        return (rg.Point3d(cx, cy, bb.Min.Z),
                rg.Point3d(cx, cy, bb.Max.Z))


def _cross_section_size(guid, ref_s, ref_e):
    """Return the geometry's max bbox dimension PERPENDICULAR to its primary axis (ref_s→ref_e).
    Used to match node disc diameter to module cross-section width."""
    obj = sc.doc.Objects.FindId(guid)
    if not obj or obj.IsDeleted:
        return 1.0
    bb = obj.Geometry.GetBoundingBox(True)
    dx = bb.Max.X - bb.Min.X
    dy = bb.Max.Y - bb.Min.Y
    dz = bb.Max.Z - bb.Min.Z
    ax = abs(ref_e.X - ref_s.X)
    ay = abs(ref_e.Y - ref_s.Y)
    az = abs(ref_e.Z - ref_s.Z)
    if ax >= ay and ax >= az:   # X is primary axis
        return max(dy, dz)
    elif ay >= az:              # Y is primary axis
        return max(dx, dz)
    else:                       # Z is primary axis
        return max(dx, dy)


def _geo_bbox_axis_length(geo, ref_s, ref_e):
    """Length of joint geometry along its defined axis (start→end direction)."""
    axis = rg.Vector3d(ref_e.X - ref_s.X, ref_e.Y - ref_s.Y, ref_e.Z - ref_s.Z)
    L    = axis.Length
    if L < 1e-10:
        bb = geo.GetBoundingBox(True)
        diag = bb.Max - bb.Min
        return max(diag.X, diag.Y, diag.Z)
    return L


def _build_orient_xform(seg_start, seg_end, ref_s_pt, ref_e_pt,
                        scale_factor=1.0, radial_scale=None):
    """Build a Rhino Transform that maps geometry axis (ref_s→ref_e)
    onto segment axis (seg_start→seg_end), then scales and translates.

    Steps:
      1. Rotate: align geo axis → seg direction
      2. Scale:  apply scaling around ref_s_pt
      3. Translate: move ref_s_pt → seg_start

    radial_scale (optional):
      When None (or equal to scale_factor): uniform scale applied.
      When set: non-uniform scale — axial direction gets scale_factor,
      perpendicular (radial) directions get radial_scale.
      Use this to keep cross-section width independent of segment length.
    """
    geo_vec = rg.Vector3d(ref_e_pt.X - ref_s_pt.X,
                          ref_e_pt.Y - ref_s_pt.Y,
                          ref_e_pt.Z - ref_s_pt.Z)
    seg_vec = rg.Vector3d(seg_end.X - seg_start.X,
                          seg_end.Y - seg_start.Y,
                          seg_end.Z - seg_start.Z)
    if geo_vec.Length < 1e-10 or seg_vec.Length < 1e-10:
        return rg.Transform.Identity

    # Rotation aligning geo axis to segment direction, pivoting at ref_s
    rot = rg.Transform.Rotation(geo_vec, seg_vec, ref_s_pt)

    # Scale around ref_s_pt — uniform or non-uniform
    if radial_scale is not None and abs(radial_scale - scale_factor) > 1e-10:
        # Non-uniform: axial (along segment) = scale_factor,
        #              radial (perpendicular) = radial_scale.
        # IMPORTANT: rg.Plane(pt, vec) treats vec as Z-normal — wrong for scaling.
        # Must use rg.Plane(origin, xAxis, yAxis) so plane.XAxis = seg direction.
        seg_unit = rg.Vector3d(seg_vec)
        seg_unit.Unitize()
        # Find any perpendicular vector for the Y axis
        perp = rg.Vector3d.CrossProduct(seg_unit, rg.Vector3d.ZAxis)
        if perp.Length < 1e-6:
            perp = rg.Vector3d.CrossProduct(seg_unit, rg.Vector3d.XAxis)
        perp.Unitize()
        # Plane: X = seg direction (axial), Y = perp, Z = cross(X,Y) (radial)
        plane = rg.Plane(ref_s_pt, seg_unit, perp)
        # Scale: xScale (axial) = scale_factor, yScale/zScale (radial) = radial_scale
        scale = rg.Transform.Scale(plane, scale_factor, radial_scale, radial_scale)
    else:
        scale = rg.Transform.Scale(ref_s_pt, scale_factor)

    # Translation: move rotated+scaled ref_s_pt to seg_start
    # After rot+scale, ref_s_pt maps to itself (it's the pivot).
    # We just need to translate from ref_s_pt to seg_start.
    trans = rg.Transform.Translation(
        rg.Vector3d(seg_start.X - ref_s_pt.X,
                    seg_start.Y - ref_s_pt.Y,
                    seg_start.Z - ref_s_pt.Z))
    xform = trans * scale * rot
    return xform


def _duplicate_geo(guid):
    """Duplicate a geometry object and return the new Brep/Mesh/Extrusion."""
    obj = sc.doc.Objects.FindId(guid)
    if not obj or obj.IsDeleted:
        return None
    geo = obj.Geometry.Duplicate()
    return geo


def _place_geo(geo, xform, layer_idx):
    """Apply transform to geo duplicate and add to doc on given layer."""
    geo.Transform(xform)
    oid = System.Guid.Empty
    if isinstance(geo, rg.Brep):
        oid = sc.doc.Objects.AddBrep(geo)
    elif isinstance(geo, rg.Mesh):
        oid = sc.doc.Objects.AddMesh(geo)
    elif isinstance(geo, rg.Curve):
        oid = sc.doc.Objects.AddCurve(geo)
    elif isinstance(geo, rg.Extrusion):
        oid = sc.doc.Objects.AddExtrusion(geo)
    elif isinstance(geo, rg.SubD):
        # SubD: try native add; fall back to mesh conversion if it fails
        try:
            oid = sc.doc.Objects.AddSubD(geo)
        except Exception:
            mesh = rg.Mesh.CreateFromSubD(geo, 3)
            if mesh and mesh.IsValid:
                oid = sc.doc.Objects.AddMesh(mesh)
    else:
        # Unknown type — try generic Add as a last resort
        try:
            oid = sc.doc.Objects.Add(geo)
        except Exception:
            return
    if oid != System.Guid.Empty:
        obj = sc.doc.Objects.FindId(oid)
        if obj:
            obj.Attributes.LayerIndex = layer_idx
            obj.CommitChanges()


def run_aggregation(params, nodes):
    """Post-bake aggregation pass.

    MODULAR  — one geometry instance per branch segment, oriented along segment axis.
    JOINT    — two sub-geometries per branching node:
                 Node Geometry : placed once at node, axis = averaged branch direction
                 Arm Geometry  : placed once per connected branch, axis = branch direction
               Modular pieces are pulled back by joint_offset at both ends to leave room.
    """
    def _resolve_ref(coords):
        """Convert (x,y,z) tuple → Point3d, or return None."""
        if not coords:
            return None
        try:
            return rg.Point3d(coords[0], coords[1], coords[2])
        except Exception:
            return None

    def _auto_bbox_len(guid):
        """Longest bbox dimension of a geometry object."""
        obj = sc.doc.Objects.FindId(guid)
        if not obj or obj.IsDeleted:
            return 1.0
        bb = obj.Geometry.GetBoundingBox(True)
        return max(bb.Max.X - bb.Min.X,
                   bb.Max.Y - bb.Min.Y,
                   bb.Max.Z - bb.Min.Z)

    try:
        if not nodes:
            return {"ok": False, "msg": "No SCA nodes in memory. Run Simulate & Bake first."}

        # ── Collect params ────────────────────────────────────────────────────
        module_guids   = params.get("agg_module_guids", [])
        mod_ref_s      = _resolve_ref(params.get("agg_start_ref"))
        mod_ref_e      = _resolve_ref(params.get("agg_end_ref"))
        scale_mode     = params.get("agg_scale_mode", "Fit")
        module_gap     = float(params.get("agg_module_gap", 0.0))
        _raw_mod_scale = float(params.get("agg_module_scale", 1.0))
        # 0 = uniform auto-fit (length and cross-section scale together, original behaviour)
        module_scale   = None if _raw_mod_scale <= 0.0 else _raw_mod_scale
        joint_enabled  = bool(params.get("agg_joint_enabled", False))
        node_guids     = params.get("agg_node_guids", [])
        node_ref_s     = _resolve_ref(params.get("agg_node_start_ref"))
        node_ref_e     = _resolve_ref(params.get("agg_node_end_ref"))
        _raw_node_scale = float(params.get("agg_node_scale", 1.0))
        # 0 = pure auto-fit (disc diameter = bar cross-section, no multiplier)
        # >0 = multiplier on auto-fit
        node_scale     = 1.0 if _raw_node_scale <= 0.0 else _raw_node_scale
        arm_guids      = params.get("agg_arm_guids", [])
        arm_ref_s      = _resolve_ref(params.get("agg_arm_start_ref"))
        arm_ref_e      = _resolve_ref(params.get("agg_arm_end_ref"))
        arm_offset_override = float(params.get("agg_arm_offset", 0.0))
        arm_scale      = float(params.get("agg_arm_scale", 1.0))
        rng            = random.Random(int(params.get("agg_seed", 42)))

        if not module_guids:
            return {"ok": False, "msg": "No module geometries picked. Pick objects first."}

        # ── Auto-detect axes when manual refs not set ─────────────────────────
        # Modular axis
        if mod_ref_s is None or mod_ref_e is None:
            mod_ref_s, mod_ref_e = _auto_ref_pts(module_guids[0])
        if mod_ref_s is None or mod_ref_e is None:
            return {"ok": False, "msg": "Cannot detect modular geometry axis.  "
                    "Enable Manual Axis and set Start/End points manually."}
        mod_geo_len = mod_ref_s.DistanceTo(mod_ref_e)
        if mod_geo_len < 1e-10:
            return {"ok": False, "msg": "Modular geometry has zero length along its axis."}

        # Arm axis
        arm_geo_len = 1.0
        if arm_guids:
            if arm_ref_s is None or arm_ref_e is None:
                arm_ref_s, arm_ref_e = _auto_ref_pts(arm_guids[0])
            if arm_ref_s and arm_ref_e:
                arm_geo_len = arm_ref_s.DistanceTo(arm_ref_e)
            if arm_geo_len < 1e-10:
                arm_geo_len = _auto_bbox_len(arm_guids[0])

        # Node axis — use SHORT axis so node sits flat / perpendicular to branch
        node_geo_len = 1.0
        if node_guids:
            if node_ref_s is None or node_ref_e is None:
                node_ref_s, node_ref_e = _auto_short_ref_pts(node_guids[0])
            if node_ref_s and node_ref_e:
                node_geo_len = node_ref_s.DistanceTo(node_ref_e)
            if node_geo_len < 1e-10:
                node_geo_len = _auto_bbox_len(node_guids[0])

        # ── Compute final node scale ──────────────────────────────────────────
        # base_scale = auto-fit so disc diameter matches module cross-section width.
        # node_scale is a multiplier ON TOP: 1.0 = match bar, 2.0 = twice, 0.5 = half.
        if (node_guids and node_ref_s and node_ref_e
                and module_guids and mod_ref_s and mod_ref_e):
            mod_cross  = _cross_section_size(module_guids[0], mod_ref_s, mod_ref_e)
            node_cross = _cross_section_size(node_guids[0],   node_ref_s, node_ref_e)
            base_scale = mod_cross / node_cross if node_cross > 1e-10 else 1.0
        else:
            base_scale = 1.0
        final_scale = base_scale * node_scale   # node_scale=1.0 → exact auto-fit

        # ── Prepare layers ────────────────────────────────────────────────────
        _clear_aggregation_layers()
        _get_or_create_layer(LAYER_AGG,          sd.Color.FromArgb(200, 160, 80))
        mod_layer  = _get_or_create_layer(LAYER_AGG_MODULAR,  sd.Color.FromArgb(220, 180, 100))
        node_layer = _get_or_create_layer(LAYER_AGG_JNT_NODE, sd.Color.FromArgb(100, 180, 220))
        arm_layer  = _get_or_create_layer(LAYER_AGG_JNT_ARM,  sd.Color.FromArgb(140, 200, 180))

        segs   = _get_agg_segments(nodes)
        n_mod  = 0
        n_node = 0
        n_arm  = 0

        rs.EnableRedraw(False)
        uid = sc.doc.BeginUndoRecord("SCA V3 Aggregate")
        try:
            # ── MODULAR ───────────────────────────────────────────────────────
            for (seg_s, seg_e, depth) in segs:
                seg_len = seg_s.DistanceTo(seg_e)
                if seg_len < 1e-10:
                    continue

                # Apply manual gap pullback from each segment end
                if module_gap > 0.0:
                    sv = rg.Vector3d(seg_e.X - seg_s.X,
                                     seg_e.Y - seg_s.Y,
                                     seg_e.Z - seg_s.Z)
                    sv.Unitize()
                    seg_s = rg.Point3d(seg_s.X + sv.X * module_gap,
                                       seg_s.Y + sv.Y * module_gap,
                                       seg_s.Z + sv.Z * module_gap)
                    seg_e = rg.Point3d(seg_e.X - sv.X * module_gap,
                                       seg_e.Y - sv.Y * module_gap,
                                       seg_e.Z - sv.Z * module_gap)
                    seg_len = seg_s.DistanceTo(seg_e)
                    if seg_len < 1e-10:
                        continue

                if scale_mode == "Fit":
                    scale_f = seg_len / mod_geo_len
                    guid    = rng.choice(module_guids)
                    geo     = _duplicate_geo(guid)
                    if geo is None:
                        continue
                    xform = _build_orient_xform(seg_s, seg_e, mod_ref_s, mod_ref_e,
                                                scale_f, radial_scale=module_scale)  # None=uniform
                    _place_geo(geo, xform, mod_layer)
                    n_mod += 1

                else:  # Repeat
                    sv = rg.Vector3d(seg_e.X - seg_s.X,
                                     seg_e.Y - seg_s.Y,
                                     seg_e.Z - seg_s.Z)
                    sv.Unitize()
                    travelled = 0.0
                    while travelled + mod_geo_len <= seg_len + 1e-6:
                        tile_s = rg.Point3d(seg_s.X + sv.X * travelled,
                                            seg_s.Y + sv.Y * travelled,
                                            seg_s.Z + sv.Z * travelled)
                        tile_e = rg.Point3d(tile_s.X + sv.X * mod_geo_len,
                                            tile_s.Y + sv.Y * mod_geo_len,
                                            tile_s.Z + sv.Z * mod_geo_len)
                        guid = rng.choice(module_guids)
                        geo  = _duplicate_geo(guid)
                        if geo is not None:
                            xform = _build_orient_xform(tile_s, tile_e,
                                                        mod_ref_s, mod_ref_e, 1.0,
                                                        radial_scale=module_scale)
                            _place_geo(geo, xform, mod_layer)
                            n_mod += 1
                        travelled += mod_geo_len

            # ── JOINTS: Node + Arm ────────────────────────────────────────────
            if joint_enabled and (node_guids or arm_guids):
                joint_nodes = _get_joint_nodes(nodes)

                for jnode in joint_nodes:
                    jx, jy, jz = jnode.xyz
                    node_pt = rg.Point3d(jx, jy, jz)

                    # Collect all branch directions at this node.
                    # Each direction points FROM the node OUTWARD along its branch —
                    # toward parent for the parent arm, toward child for each child arm.
                    branch_dirs = []
                    if jnode.parent_id is not None:
                        p = nodes[jnode.parent_id]
                        d = _norm3(p.xyz[0] - jx, p.xyz[1] - jy, p.xyz[2] - jz)  # node → parent
                        branch_dirs.append(d)
                    for cid in jnode.children:
                        c = nodes[cid]
                        d = _norm3(c.xyz[0] - jx, c.xyz[1] - jy, c.xyz[2] - jz)  # node → child
                        branch_dirs.append(d)

                    if not branch_dirs:
                        continue

                    # ── Place NODE geometry (once per branching node) ──────────
                    if node_guids and node_ref_s and node_ref_e:
                        # Disc axis = normal to the best-fit plane of all branches.
                        # For a flat disc this makes the face perpendicular to the
                        # branching plane so arms radiate from the disc rim:
                        #   2-way elbow   → disc is the hinge plate
                        #   3-way Y/T     → disc lies flat in the branch plane
                        #   4-way +       → disc faces the dominant branch plane
                        #   2-way straight → disc becomes a collar on the bar
                        disc_normal = _branch_plane_normal(branch_dirs)

                        # CENTER the node geometry at node_pt along the disc normal.
                        # World-space half = node_geo_len * final_scale * 0.5
                        half = node_geo_len * final_scale * 0.5
                        node_seg_s = rg.Point3d(node_pt.X - disc_normal[0] * half,
                                                node_pt.Y - disc_normal[1] * half,
                                                node_pt.Z - disc_normal[2] * half)
                        node_seg_e = rg.Point3d(node_pt.X + disc_normal[0] * half,
                                                node_pt.Y + disc_normal[1] * half,
                                                node_pt.Z + disc_normal[2] * half)
                        xform = _build_orient_xform(node_seg_s, node_seg_e,
                                                    node_ref_s, node_ref_e,
                                                    final_scale)
                        geo = _duplicate_geo(rng.choice(node_guids))
                        if geo is not None:
                            _place_geo(geo, xform, node_layer)
                            n_node += 1

                    # ── Place ARM geometry (one per branch direction) ──────────
                    if arm_guids and arm_ref_s and arm_ref_e:
                        # arm_offset_override = distance from node centre to arm ref_s pt.
                        # arm_scale           = uniform size multiplier (no stretching).
                        # Arm is placed at the offset position at its natural size —
                        # it does NOT stretch to fill any gap. The user sets module_gap
                        # >= arm_offset + arm_geo_len*arm_scale for a clean fit.
                        arm_natural_len = arm_geo_len * arm_scale
                        for d in branch_dirs:
                            # Arm ref_s sits at arm_offset_override from node centre
                            arm_seg_s = rg.Point3d(
                                node_pt.X + d[0] * arm_offset_override,
                                node_pt.Y + d[1] * arm_offset_override,
                                node_pt.Z + d[2] * arm_offset_override)
                            arm_seg_e = rg.Point3d(
                                arm_seg_s.X + d[0] * arm_natural_len,
                                arm_seg_s.Y + d[1] * arm_natural_len,
                                arm_seg_s.Z + d[2] * arm_natural_len)
                            xform = _build_orient_xform(arm_seg_s, arm_seg_e,
                                                        arm_ref_s, arm_ref_e,
                                                        arm_scale)
                            geo = _duplicate_geo(rng.choice(arm_guids))
                            if geo is not None:
                                _place_geo(geo, xform, arm_layer)
                                n_arm += 1

        finally:
            sc.doc.EndUndoRecord(uid)
        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()

        msg = "Aggregation done  |  {} modules".format(n_mod)
        if joint_enabled:
            msg += "  |  {} nodes  |  {} arms".format(n_node, n_arm)
        msg += "  |  Check SCA_Aggregation layer"
        return {"ok": True, "msg": msg}

    except Exception:
        return {"ok": False, "msg": traceback.format_exc()}

# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(params, conduit):
    try:
        rng  = random.Random(int(params["seed"]))
        mode = int(params["attractor_mode"])

        if   mode == 0: attractors = _gen_attractors_mode0(params, rng)
        elif mode == 1: attractors = _gen_attractors_mode1(params)
        elif mode == 2: attractors = _gen_attractors_mode2(params, rng)
        elif mode == 3: attractors = _gen_attractors_mode3(params, rng)
        elif mode == 4: attractors = _gen_attractors_mode4(params, rng)
        else:           attractors = _gen_attractors_mode5(params, rng)

        if not attractors:
            return {"ok": False, "msg": "No attractors generated. "
                    "Check mode settings / picked objects."}

        if mode == 4:
            nodes = _place_roots_clusters(attractors, params, rng)
        elif mode == 2:
            nodes = _place_roots_on_surface(attractors, params, rng)
        else:
            nodes = _place_roots(attractors, params, rng)

        # Flat mode: snap nodes back to surface each step.
        # 3D mode: free growth toward offset attractor cloud — no snapping.
        if mode == 2 and not params.get("surface_3d_mode", False):
            surface_project = _build_surface_projector(params)
        else:
            surface_project = None

        if not nodes:
            return {"ok": False, "msg": "Root placement failed."}

        # ── Build influence vector ONCE before the loop ──────────────────────
        inf_vec = _build_influence_vec(params)

        # ── Build point attractor field ONCE before the loop ─────────────────
        _build_point_field(params)
        waypoint_mode = (params.get("point_behavior") == "Waypoint Sequence"
                         and bool(params.get("point_guids"))
                         and float(params.get("point_attractor_weight", 0.0)) > 0.0)

        # ── Auto-scale influence_radius if needed ────────────────────────────
        inf_r = float(params["influence_radius"])
        in_range = sum(
            1 for a in attractors
            if any(_dist3(a.xyz[0], a.xyz[1], a.xyz[2],
                          n.xyz[0], n.xyz[1], n.xyz[2]) < inf_r for n in nodes)
        )
        axs = [a.xyz[0] for a in attractors]
        ays = [a.xyz[1] for a in attractors]
        azs = [a.xyz[2] for a in attractors]
        vol = max(1e-3, (max(axs)-min(axs))*(max(ays)-min(ays))*(max(azs)-min(azs)))
        avg_spacing   = (vol / max(len(attractors), 1)) ** (1.0/3.0)
        recommended_r = avg_spacing * 2.5

        if in_range == 0:
            params = dict(params)
            params["influence_radius"] = recommended_r
            inf_r = recommended_r
            in_range = sum(
                1 for a in attractors
                if any(_dist3(a.xyz[0], a.xyz[1], a.xyz[2],
                              n.xyz[0], n.xyz[1], n.xyz[2]) < inf_r for n in nodes)
            )
            print("SCA V2  WARNING: influence_radius auto-scaled to {:.1f} "
                  "(avg spacing {:.1f})".format(inf_r, avg_spacing))
        elif recommended_r > inf_r * 1.5:
            print("SCA V2  TIP: recommended influence_radius ≈ {:.1f}  "
                  "(current: {:.1f})".format(recommended_r, inf_r))

        inf_label = params.get("influence_type", "None")
        pt_label  = (" + Points/" + params.get("point_behavior", "")
                     if float(params.get("point_attractor_weight", 0.0)) > 0.0
                        and params.get("point_guids") else "")
        print("SCA V3  attractors={}  roots={}  in_range={}  "
              "inf_r={:.1f}  influence={}{}  weight={:.2f}".format(
              len(attractors), len(nodes), in_range, inf_r,
              inf_label, pt_label, float(params.get("influence_weight", 0))))

        # ── Growth loop ──────────────────────────────────────────────────────
        conduit._show_attr = bool(params.get("show_attractors", True))
        conduit._style     = params.get("display_style", "Bloom + Trail")
        conduit.begin(nodes, attractors)
        delay    = params["draw_delay_ms"] / 1000.0
        stagnant = 0
        stop_msg = ""

        try:
            for _iter in range(int(params["max_iterations"])):
                if not any(a.alive for a in attractors):
                    stop_msg = "all attractors consumed at iteration {}".format(_iter)
                    break

                new_nodes = grow_one_iteration(params, nodes, attractors, rng, inf_vec)

                if not new_nodes:
                    stagnant += 1
                    if stagnant >= 10:
                        stop_msg = "stagnant — stopped at iteration {}".format(_iter)
                        break
                    continue
                stagnant = 0

                if surface_project:
                    for nd in new_nodes:
                        px, py, pz = surface_project(nd.xyz[0], nd.xyz[1], nd.xyz[2])
                        nd.position = rg.Point3d(px, py, pz)
                        nd.xyz      = (px, py, pz)
                nodes.extend(new_nodes)

                # ── Waypoint Sequence: advance gate when SCA reaches it ───────
                if waypoint_mode:
                    wp_pts = params.get("_waypoint_positions", [])
                    wp_idx = params.get("_waypoint_active", 0)
                    if wp_idx < len(wp_pts):
                        wx, wy, wz = wp_pts[wp_idx]
                        gate_r = float(params["kill_distance"]) * 4.0
                        # Check if any node is close enough to current waypoint
                        if any(_dist3(n.xyz[0], n.xyz[1], n.xyz[2], wx, wy, wz) < gate_r
                               for n in nodes[-50:]):   # check only recent nodes (fast)
                            next_idx = wp_idx + 1
                            params["_waypoint_active"] = next_idx
                            if next_idx < len(wp_pts):
                                nx2, ny2, nz2 = wp_pts[next_idx]
                                params["_point_field"] = [(nx2, ny2, nz2, 2.0)]
                                print("SCA V3  Waypoint {}/{} reached → advancing to {}".format(
                                      wp_idx, len(wp_pts) - 1, next_idx))
                            else:
                                params["_point_field"] = []
                                print("SCA V3  Waypoint: all {} gates reached".format(
                                      len(wp_pts)))
                # ─────────────────────────────────────────────────────────────

                conduit.refresh(nodes, attractors)
                sc.doc.Views.Redraw()
                Rhino.RhinoApp.Wait()
                if delay > 0:
                    time.sleep(delay)
        except KeyboardInterrupt:
            stop_msg = "stopped by Escape"

        print("SCA V3  done — {} | total nodes: {}".format(
              stop_msg or "max iterations reached", len(nodes)))

        conduit.end()
        sc.doc.Views.Redraw()

        rs.EnableRedraw(False)
        uid = sc.doc.BeginUndoRecord("SCA V3 Bake")
        try:
            _bake_result(nodes, params)
        finally:
            sc.doc.EndUndoRecord(uid)
        rs.EnableRedraw(True)

        if len(nodes) > 1:
            try:
                xs = [n.xyz[0] for n in nodes]
                ys = [n.xyz[1] for n in nodes]
                zs = [n.xyz[2] for n in nodes]
                bb = rg.BoundingBox(
                    rg.Point3d(min(xs), min(ys), min(zs)),
                    rg.Point3d(max(xs), max(ys), max(zs)))
                # Inflate by 10% of the diagonal so the result sits nicely in frame
                diag = bb.Diagonal.Length
                bb.Inflate(max(diag * 0.1, float(params.get("step_distance", 5.0)) * 3))
                for vp in sc.doc.Views:
                    vp.ActiveViewport.ZoomBoundingBox(bb)
            except Exception:
                pass

        sc.doc.Views.Redraw()
        max_d = max(n.depth for n in nodes)
        return {
            "ok":    True,
            "msg":   "Done  |  nodes: {}  |  max depth: {}  |  "
                     "influence: {}  |  Check SCA_Branches layers".format(
                     len(nodes), max_d, inf_label),
            "nodes": nodes,
        }

    except Exception:
        return {"ok": False, "msg": traceback.format_exc()}

# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY CONDUIT
# ─────────────────────────────────────────────────────────────────────────────

class SCAConduit(rd.DisplayConduit):

    def __init__(self):
        super(SCAConduit, self).__init__()
        self._nodes        = []
        self._attractors   = []
        self._max_depth    = 1
        self._show_attr    = True
        self._style        = "Bloom + Trail"
        self._iter         = 0          # frame counter for animations
        self._flash_nodes  = set()      # node IDs that are newly added this frame
        self._prev_node_ids= set()

    def begin(self, nodes, attractors):
        self._iter          = 0
        self._flash_nodes   = set()
        self._prev_node_ids = {n.id for n in nodes}
        self.refresh(nodes, attractors)
        self.Enabled = True

    def refresh(self, nodes, attractors):
        all_ids = {n.id for n in nodes}
        self._flash_nodes   = all_ids - self._prev_node_ids
        self._prev_node_ids = all_ids
        self._nodes         = list(nodes)
        self._attractors    = list(attractors)
        self._max_depth     = max((n.depth for n in nodes), default=1)
        self._iter         += 1

    def end(self):
        self.Enabled = False

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _lerp_col(r0, g0, b0, r1, g1, b1, t):
        t = max(0.0, min(1.0, t))
        return sd.Color.FromArgb(int(r0+(r1-r0)*t), int(g0+(g1-g0)*t), int(b0+(b1-b0)*t))

    def _z_bounds(self):
        if not self._nodes:
            return 0.0, 1.0
        zs = [n.xyz[2] for n in self._nodes]
        lo, hi = min(zs), max(zs)
        return lo, (hi if hi > lo else lo + 1.0)

    # ── draw ──────────────────────────────────────────────────────────────────

    def PostDrawObjects(self, e):
        style = self._style
        md    = self._max_depth
        nodes = self._nodes
        it    = self._iter

        # ── A: Bloom + Trail ─────────────────────────────────────────────────
        if style == "Bloom + Trail":
            for node in nodes:
                if node.parent_id is None:
                    continue
                parent = nodes[node.parent_id]
                t      = node.depth / float(max(md, 1))
                col    = self._lerp_col(220, 140, 40, 70, 160, 220, t)
                weight = max(3, 10 - node.depth // 2)
                # New node = bright white flash
                if node.id in self._flash_nodes:
                    col    = sd.Color.White
                    weight = weight + 3
                px, py, pz = parent.xyz
                nx, ny, nz = node.xyz
                e.Display.DrawLine(
                    rg.Line(rg.Point3d(px, py, pz), rg.Point3d(nx, ny, nz)),
                    col, weight)
            if self._show_attr:
                for attr in self._attractors:
                    if attr.alive:
                        # Pulsing active: size oscillates 5..8
                        sz  = 6 + int(2 * math.sin(it * 0.4 + hash(str(attr.xyz)) * 0.01))
                        col = sd.Color.FromArgb(60, 230, 80)
                        e.Display.DrawPoint(attr.position,
                                            Rhino.Display.PointStyle.Circle, sz, col)
                    # Consumed: vanish completely (no drawing)

        # ── B: Glowing Neon ──────────────────────────────────────────────────
        elif style == "Glowing Neon":
            for node in nodes:
                if node.parent_id is None:
                    continue
                parent = nodes[node.parent_id]
                t      = node.depth / float(max(md, 1))
                col    = self._lerp_col(255, 160, 20, 20, 180, 255, t)
                weight = max(3, 10 - node.depth // 2)
                px, py, pz = parent.xyz
                nx, ny, nz = node.xyz
                e.Display.DrawLine(
                    rg.Line(rg.Point3d(px, py, pz), rg.Point3d(nx, ny, nz)),
                    col, weight)
            if self._show_attr:
                for attr in self._attractors:
                    if attr.alive:
                        # Cyan bright core + larger faint halo ring
                        e.Display.DrawPoint(attr.position,
                                            Rhino.Display.PointStyle.Circle, 8,
                                            sd.Color.FromArgb(0, 255, 255))
                        e.Display.DrawPoint(attr.position,
                                            Rhino.Display.PointStyle.Circle, 14,
                                            sd.Color.FromArgb(30, 0, 200, 220))
                    else:
                        # Consumed: tiny near-invisible dark dot
                        e.Display.DrawPoint(attr.position,
                                            Rhino.Display.PointStyle.Circle, 2,
                                            sd.Color.FromArgb(35, 35, 35))

        # ── C: Heat Map Density ───────────────────────────────────────────────
        elif style == "Heat Map Density":
            # Pre-compute alive-only positions for density check
            alive_pts = [a for a in self._attractors if a.alive]
            n_alive   = len(alive_pts)
            # Density search radius: coarse estimate
            dr = 30.0
            for node in nodes:
                if node.parent_id is None: continue
                parent = nodes[node.parent_id]
                col    = sd.Color.FromArgb(230, 230, 230)
                weight = max(3, 10 - node.depth // 2)
                px, py, pz = parent.xyz
                nx, ny, nz = node.xyz
                e.Display.DrawLine(
                    rg.Line(rg.Point3d(px, py, pz), rg.Point3d(nx, ny, nz)),
                    col, weight)
            if self._show_attr:
                for attr in self._attractors:
                    if attr.alive:
                        ax, ay, az = attr.xyz
                        count = sum(1 for b in alive_pts
                                    if abs(b.xyz[0]-ax)<dr
                                    and abs(b.xyz[1]-ay)<dr
                                    and abs(b.xyz[2]-az)<dr)
                        density = min(1.0, count / max(float(n_alive) * 0.1, 1.0))
                        # hot=red/orange dense → cool=blue sparse
                        col = self._lerp_col(255, 40, 20, 20, 80, 255, 1.0 - density)
                        sz  = 4 + int(density * 5)
                        e.Display.DrawPoint(attr.position,
                                            Rhino.Display.PointStyle.Circle, sz, col)
                    else:
                        e.Display.DrawPoint(attr.position,
                                            Rhino.Display.PointStyle.Circle, 2,
                                            sd.Color.FromArgb(40, 40, 40))

        # ── D: Branch-Only Minimal ────────────────────────────────────────────
        elif style == "Branch-Only":
            for node in nodes:
                if node.parent_id is None: continue
                parent = nodes[node.parent_id]
                t      = node.depth / float(max(md, 1))
                # New node = white flash, settled = warm→cool
                if node.id in self._flash_nodes:
                    col    = sd.Color.White
                    weight = 12
                else:
                    col    = self._lerp_col(255, 165, 30, 30, 140, 255, t)
                    weight = max(3, 10 - node.depth // 2)
                px, py, pz = parent.xyz
                nx, ny, nz = node.xyz
                e.Display.DrawLine(
                    rg.Line(rg.Point3d(px, py, pz), rg.Point3d(nx, ny, nz)),
                    col, weight)
            # Attractors: hidden completely

        # ── E: Particle Field ─────────────────────────────────────────────────
        elif style == "Particle Field":
            # Pre-build node positions for distance calc
            node_pts = [(n.xyz[0], n.xyz[1], n.xyz[2]) for n in nodes]
            for node in nodes:
                if node.parent_id is None: continue
                parent = nodes[node.parent_id]
                col    = sd.Color.FromArgb(220, 220, 200)
                weight = max(3, 10 - node.depth // 2)
                px, py, pz = parent.xyz
                nx, ny, nz = node.xyz
                e.Display.DrawLine(
                    rg.Line(rg.Point3d(px, py, pz), rg.Point3d(nx, ny, nz)),
                    col, weight)
            if self._show_attr:
                for attr in self._attractors:
                    if attr.alive:
                        ax, ay, az = attr.xyz
                        # Distance to nearest node: closer = larger, bright (about to be eaten)
                        min_d = min(
                            (abs(nx-ax)+abs(ny-ay)+abs(nz-az))
                            for (nx, ny, nz) in node_pts) if node_pts else 999.0
                        proximity = max(0.0, 1.0 - min_d / 40.0)
                        sz  = 3 + int(proximity * 9)  # 3 (far) .. 12 (about to be consumed)
                        # Colour: cold blue (far) → hot yellow-white (close)
                        col = self._lerp_col(40, 100, 200, 255, 240, 60, proximity)
                        e.Display.DrawPoint(attr.position,
                                            Rhino.Display.PointStyle.RoundActivePoint, sz, col)
                    # Consumed: vanish

        # ── F: Depth Fog ──────────────────────────────────────────────────────
        elif style == "Depth Fog":
            z_lo, z_hi = self._z_bounds()
            z_range    = z_hi - z_lo
            for node in nodes:
                if node.parent_id is None: continue
                parent = nodes[node.parent_id]
                tz     = (node.xyz[2] - z_lo) / z_range   # 0=bottom, 1=top
                alpha  = int(255 * (0.25 + 0.75 * (1.0 - tz)))  # bright at bottom
                col    = sd.Color.FromArgb(alpha,
                                           int(220 * (1.0-tz) + 80 * tz),
                                           int(140 * (1.0-tz) + 180 * tz),
                                           int(40  * (1.0-tz) + 220 * tz))
                weight = max(3, 10 - node.depth // 2)
                px, py, pz = parent.xyz
                nx, ny, nz = node.xyz
                e.Display.DrawLine(
                    rg.Line(rg.Point3d(px, py, pz), rg.Point3d(nx, ny, nz)),
                    col, weight)
            if self._show_attr:
                for attr in self._attractors:
                    tz    = (attr.xyz[2] - z_lo) / z_range
                    alpha = int(255 * (0.2 + 0.8 * (1.0 - tz)))
                    if attr.alive:
                        sz  = 3 + int((1.0 - tz) * 6)
                        col = sd.Color.FromArgb(alpha, 80, 220, 100)
                    else:
                        sz  = 2
                        col = sd.Color.FromArgb(max(20, alpha // 4), 50, 50, 50)
                    e.Display.DrawPoint(attr.position,
                                        Rhino.Display.PointStyle.Circle, sz, col)

        # ── Fallback (original) ───────────────────────────────────────────────
        else:
            for node in nodes:
                if node.parent_id is None: continue
                parent = nodes[node.parent_id]
                col    = _depth_color(node.depth, md)
                weight = max(3, 10 - node.depth // 2)
                px, py, pz = parent.xyz
                nx, ny, nz = node.xyz
                e.Display.DrawLine(
                    rg.Line(rg.Point3d(px, py, pz), rg.Point3d(nx, ny, nz)),
                    col, weight)
            if self._show_attr:
                for attr in self._attractors:
                    col = sd.Color.FromArgb(80, 220, 100) if attr.alive else sd.Color.FromArgb(55, 55, 55)
                    e.Display.DrawPoint(attr.position,
                                        Rhino.Display.PointStyle.Circle, 4, col)

# ─────────────────────────────────────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────────────────────────────────────

class SCADialogV3(ef.Form):

    def __init__(self, conduit):
        super(SCADialogV3, self).__init__()
        self._conduit       = conduit
        self._voxel_guids   = []
        self._climate_guids = []
        self._surface_guids = []   # list — supports multiple picked surfaces
        self._curve_guids   = []
        self._point_guids   = []

        # Aggregation state
        self._last_nodes       = []   # stored after each successful simulation
        self._agg_module_guids = []
        self._agg_start_ref    = None   # (x,y,z) — modular axis start
        self._agg_end_ref      = None   # (x,y,z) — modular axis end
        # Joint — node geometry
        self._agg_node_guids   = []
        self._agg_node_sref    = None   # (x,y,z) — node axis start
        self._agg_node_eref    = None   # (x,y,z) — node axis end
        # Joint — arm geometry
        self._agg_arm_guids    = []
        self._agg_arm_sref     = None   # (x,y,z) — arm centre-side end
        self._agg_arm_eref     = None   # (x,y,z) — arm outer tip

        self.Title       = "Space Colonization Algorithm V4"
        self.Resizable   = True
        self.MinimumSize = edraw.Size(440, 700)
        self.Padding     = edraw.Padding(10)
        self._build_ui()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _lbl(self, txt, bold=False, w=None):
        lb = ef.Label()
        lb.Text = txt
        if bold:
            lb.Font = edraw.Font(lb.Font.Family, lb.Font.Size, edraw.FontStyle.Bold)
        if w:
            lb.Width = w
        lb.VerticalAlignment = ef.VerticalAlignment.Center
        return lb

    def _section(self, txt):
        lb = self._lbl(txt, bold=True)
        lb.TextColor = edraw.Colors.DarkSlateGray
        return lb

    def _desc(self, txt):
        lb = ef.Label()
        lb.Text = txt
        lb.TextColor = edraw.Color.FromArgb(120, 120, 120)
        return lb

    def _num(self, val, lo, hi, dec=1, inc=1.0):
        ns = ef.NumericStepper()
        ns.Value = val; ns.MinValue = lo; ns.MaxValue = hi
        ns.DecimalPlaces = dec; ns.Increment = inc; ns.Width = 100
        return ns

    def _row(self, label, ctrl, lw=160):
        tl = ef.TableLayout(); tl.Spacing = edraw.Size(8, 0)
        tl.Rows.Add(ef.TableRow(ef.TableCell(self._lbl(label, w=lw)),
                                ef.TableCell(ctrl)))
        return tl

    def _sep(self):
        return ef.Label()

    # ── mode panels ──────────────────────────────────────────────────────────

    def _panel0(self):
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._p0_bx   = self._num(DEFAULTS["bbox_x"],  1, 10000, 1)
        self._p0_by   = self._num(DEFAULTS["bbox_y"],  1, 10000, 1)
        self._p0_bz   = self._num(DEFAULTS["bbox_z"],  1, 10000, 1)
        self._p0_natl = self._num(DEFAULTS["num_attractors"], 10, 5000, 0, 10)
        self._p0_natl.DecimalPlaces = 0
        ly.AddRow(self._row("Width (X):", self._p0_bx))
        ly.AddRow(self._row("Depth (Y):", self._p0_by))
        ly.AddRow(self._row("Height (Z):", self._p0_bz))
        ly.AddRow(self._desc("Defines the volume in which attractors are randomly placed.  Roots spawn below Z=0."))
        ly.AddRow(self._row("Attractor count:", self._p0_natl))
        ly.AddRow(self._desc("More attractors = denser branching.  Increase Influence Radius proportionally."))
        p = ef.Panel(); p.Content = ly; return p

    def _panel1(self):
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._p1_lbl  = self._lbl("0 objects selected")
        btn = ef.Button(); btn.Text = "Pick Voxel Objects"; btn.Click += self._on_pick_voxels
        self._p1_filt = ef.TextBox(); self._p1_filt.PlaceholderText = "e.g. VOXELGEN_Circulation"; self._p1_filt.Width = 200
        ly.AddRow(btn)
        ly.AddRow(self._desc("Select voxel Breps / meshes — their bounding-box centres become attractors."))
        ly.AddRow(self._p1_lbl)
        ly.AddRow(self._row("Layer filter:", self._p1_filt))
        ly.AddRow(self._desc("Optional: auto-select all objects whose layer name contains this text."))
        p = ef.Panel(); p.Content = ly; return p

    def _panel2(self):
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._p2_lbl  = self._lbl("0 surfaces picked")
        btn = ef.Button(); btn.Text = "Pick Surfaces / Meshes"; btn.Click += self._on_pick_surface
        clr = ef.Button(); clr.Text = "✕"; clr.Width = 28
        clr.Click += lambda s, e: self._clear_surface_list()
        self._p2_udiv = self._num(DEFAULTS["surface_u_div"], 2, 100, 0, 1); self._p2_udiv.DecimalPlaces = 0
        self._p2_vdiv = self._num(DEFAULTS["surface_v_div"], 2, 100, 0, 1); self._p2_vdiv.DecimalPlaces = 0
        self._p2_noise= self._num(DEFAULTS["surface_noise"]*100, 0, 100, 0, 5); self._p2_noise.DecimalPlaces = 0
        btn_row = ef.TableLayout(); btn_row.Spacing = edraw.Size(4, 0)
        btn_row.Rows.Add(ef.TableRow(ef.TableCell(btn), ef.TableCell(self._p2_lbl),
                                     ef.TableCell(clr)))
        ly.AddRow(btn_row)
        ly.AddRow(self._desc("Pick any geometry — NURBS surface, polysurface, mesh, or SubD.\n"
                              "Multiple objects allowed — each is sampled independently."))
        ly.AddRow(self._row("U Divisions:", self._p2_udiv))
        ly.AddRow(self._row("V Divisions:", self._p2_vdiv))
        ly.AddRow(self._desc("U × V = total attractor points sampled across the surface."))
        ly.AddRow(self._row("UV Jitter %:", self._p2_noise))
        ly.AddRow(self._desc("0% = uniform grid.  Higher % = scattered / organic distribution."))

        # ── 3D Growth Mode ────────────────────────────────────────────────────
        ly.AddRow(ef.Label())
        self._p2_3d_chk = ef.CheckBox()
        self._p2_3d_chk.Text    = "3D Growth Mode"
        self._p2_3d_chk.Checked = DEFAULTS["surface_3d_mode"]
        self._p2_3d_chk.CheckedChanged += self._on_p2_3d_changed
        ly.AddRow(self._p2_3d_chk)
        ly.AddRow(self._desc("Lifts attractors off the surface so branches grow outward in 3D\n"
                              "from roots anchored on the surface face."))

        # Sub-panel (visible only when 3D mode ON)
        self._p2_3d_panel = ef.Panel()
        p2_3d_ly = ef.DynamicLayout(); p2_3d_ly.DefaultSpacing = edraw.Size(4,2)

        self._p2_3d_type_dd = ef.DropDown()
        self._p2_3d_type_dd.Items.Add("Offset Cloud")
        self._p2_3d_type_dd.Items.Add("Multi-Shell")
        self._p2_3d_type_dd.SelectedIndex = (0 if DEFAULTS["surface_3d_type"] == "Offset" else 1)
        self._p2_3d_type_dd.SelectedIndexChanged += self._on_p2_3d_type_changed
        p2_3d_ly.AddRow(self._row("3D type:", self._p2_3d_type_dd))
        p2_3d_ly.AddRow(self._desc("Offset Cloud = one attractor layer at max depth.\n"
                                    "Multi-Shell = N concentric layers from surface to max depth."))

        self._p2_depth = self._num(DEFAULTS["surface_growth_depth"], 0.1, 50000, 1, 1.0)
        p2_3d_ly.AddRow(self._row("Growth depth:", self._p2_depth))
        p2_3d_ly.AddRow(self._desc("World units — how far attractors float above the surface normal."))

        # Shell count row — only visible in Multi-Shell mode
        self._p2_shells_row_lbl = ef.Label(); self._p2_shells_row_lbl.Text = "Shell count:"
        self._p2_shells = self._num(DEFAULTS["surface_shell_count"], 2, 8, 0, 1)
        self._p2_shells.DecimalPlaces = 0
        self._p2_shells_panel = ef.Panel()
        sh_ly = ef.DynamicLayout(); sh_ly.DefaultSpacing = edraw.Size(4,2)
        sh_ly.AddRow(self._row("Shell count:", self._p2_shells))
        sh_ly.AddRow(self._desc("Number of concentric attractor layers from surface to max depth.\n"
                                 "More shells = denser layered structure."))
        self._p2_shells_panel.Content = sh_ly
        self._p2_shells_panel.Visible = (DEFAULTS["surface_3d_type"] == "Shells")
        p2_3d_ly.AddRow(self._p2_shells_panel)

        self._p2_root_off = self._num(DEFAULTS["surface_root_offset"], 0.0, 50000, 1, 0.5)
        p2_3d_ly.AddRow(self._row("Root offset:", self._p2_root_off))
        p2_3d_ly.AddRow(self._desc("0 = roots placed on the surface face (default).\n"
                                    ">0 = float roots above surface by this distance."))

        self._p2_3d_panel.Content = p2_3d_ly
        self._p2_3d_panel.Visible = DEFAULTS["surface_3d_mode"]
        ly.AddRow(self._p2_3d_panel)

        p = ef.Panel(); p.Content = ly; return p

    def _panel3(self):
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._p3_lbl  = self._lbl("0 climate voxels selected")
        btn = ef.Button(); btn.Text = "Pick Climate Voxel Objects"; btn.Click += self._on_pick_climate
        self._p3_bias = self._num(DEFAULTS["radiation_bias"], 1, 20, 1, 0.5)
        ly.AddRow(btn)
        ly.AddRow(self._desc("Pick voxels from Melbourne Climate Voxel Attractor output."))
        ly.AddRow(self._p3_lbl)
        ly.AddRow(self._row("Radiation bias:", self._p3_bias))
        ly.AddRow(self._desc("Low-radiation voxels → 1 attractor.  High-radiation → up to this many."))
        p = ef.Panel(); p.Content = ly; return p

    def _panel4(self):
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._p4_sx  = self._num(DEFAULTS["site_bbox_x"], 10, 50000, 1)
        self._p4_sy  = self._num(DEFAULTS["site_bbox_y"], 10, 50000, 1)
        self._p4_sz  = self._num(DEFAULTS["site_bbox_z"], 5, 5000, 1)
        self._p4_nat = self._num(DEFAULTS["site_num_attractors"], 10, 5000, 0, 10); self._p4_nat.DecimalPlaces = 0
        self._p4_nc  = self._num(DEFAULTS["num_clusters"], 1, 50, 0, 1); self._p4_nc.DecimalPlaces = 0
        ly.AddRow(self._row("Site Width (X):", self._p4_sx))
        ly.AddRow(self._row("Site Depth (Y):", self._p4_sy))
        ly.AddRow(self._row("Site Height (Z):", self._p4_sz))
        ly.AddRow(self._desc("Defines the site volume.  Influence radius auto-scales if too small."))
        ly.AddRow(self._row("Attractor count:", self._p4_nat))
        ly.AddRow(self._desc("Spread across the full site.  Increase count OR radius for large volumes."))
        ly.AddRow(self._row("Building clusters:", self._p4_nc))
        ly.AddRow(self._desc("Each cluster = one building footprint.  Roots spawn within each cluster area."))
        p = ef.Panel(); p.Content = ly; return p

    def _panel5(self):
        """Mode 5 — Curve Network: attractors sampled along picked curves."""
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._p5_lbl   = self._lbl("0 curves selected")
        btn = ef.Button(); btn.Text = "Pick Curves"; btn.Click += self._on_pick_curves
        self._p5_samp  = self._num(DEFAULTS["curve_sample_count"], 2, 500, 0, 5)
        self._p5_samp.DecimalPlaces = 0
        self._p5_noise = self._num(DEFAULTS["curve_noise"], 0, 500, 1, 1)
        ly.AddRow(btn)
        ly.AddRow(self._desc("Pick any Rhino curves — SCA branches grow toward points along each curve."))
        ly.AddRow(self._p5_lbl)
        ly.AddRow(self._row("Sample count:", self._p5_samp))
        ly.AddRow(self._desc("Points sampled per curve.  More = denser attractor distribution."))
        ly.AddRow(self._row("Off-curve noise:", self._p5_noise))
        ly.AddRow(self._desc("Random scatter radius around each sample point.  0 = exactly on curve."))
        p = ef.Panel(); p.Content = ly; return p

    # ── influence sub-panels ─────────────────────────────────────────────────

    def _inf_panel_climate(self):
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._inf_ccs_lbl = self._lbl("")
        self._refresh_ccs_status()
        ly.AddRow(self._inf_ccs_lbl)
        ly.AddRow(self._desc("Branches lean toward zones of high solar heat index.\n"
                              "Run Climate Comfort Special V1 first to populate sticky data."))
        p = ef.Panel(); p.Content = ly; return p

    def _inf_panel_sun(self):
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._inf_sun_month = self._num(DEFAULTS["sun_month"], 1, 12, 0, 1)
        self._inf_sun_month.DecimalPlaces = 0
        self._inf_sun_hour  = self._num(DEFAULTS["sun_hour"], 0, 23, 1, 0.5)
        ly.AddRow(self._row("Month (1–12):", self._inf_sun_month))
        ly.AddRow(self._row("Hour (0–23):",  self._inf_sun_hour))
        ly.AddRow(self._desc("Melbourne sun angle.  Month 6 = June solstice.  Hour 12 = solar noon.\n"
                              "Branches lean toward the computed sun direction."))
        p = ef.Panel(); p.Content = ly; return p

    def _inf_panel_wind(self):
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._inf_wind_dir = self._num(DEFAULTS["wind_direction"], 0, 360, 1, 5)
        ly.AddRow(self._row("Direction (°N):", self._inf_wind_dir))
        ly.AddRow(self._desc("0=North  90=East  225=SW (Melbourne prevailing).\n"
                              "Branches lean in the downwind direction."))
        p = ef.Panel(); p.Content = ly; return p

    def _inf_panel_custom(self):
        ly = ef.DynamicLayout(); ly.DefaultSpacing = edraw.Size(4,2); ly.Padding = edraw.Padding(4)
        self._inf_cx = self._num(DEFAULTS["custom_ix"], -1, 1, 2, 0.1)
        self._inf_cy = self._num(DEFAULTS["custom_iy"], -1, 1, 2, 0.1)
        self._inf_cz = self._num(DEFAULTS["custom_iz"], -1, 1, 2, 0.1)
        ly.AddRow(self._row("X:", self._inf_cx))
        ly.AddRow(self._row("Y:", self._inf_cy))
        ly.AddRow(self._row("Z:", self._inf_cz))
        ly.AddRow(self._desc("Custom direction vector — will be normalized automatically.\n"
                              "(0,0,1) = upward.  (0,0,-1) = gravity / stalactite."))
        p = ef.Panel(); p.Content = ly; return p

    # ── main layout ──────────────────────────────────────────────────────────

    def _build_ui(self):
        ml = ef.DynamicLayout()
        ml.DefaultSpacing = edraw.Size(6, 6)
        ml.Padding        = edraw.Padding(8)

        # MODE SELECTOR
        ml.AddRow(self._section("ATTRACTOR MODE"))
        self._mode_dd = ef.DropDown()
        for m in SCA_MODES:
            self._mode_dd.Items.Add(m)
        self._mode_dd.SelectedIndex = DEFAULTS["attractor_mode"]
        self._mode_dd.SelectedIndexChanged += self._on_mode_changed
        ml.AddRow(self._mode_dd)
        ml.AddRow(self._desc("0 Tree Column  ·  1 Voxel Network  ·  2 Facade Surface  ·  "
                              "3 Climate Growth  ·  4 Urban Canopy  ·  5 Curve Network"))
        ml.AddRow(self._sep())

        self._panels = [
            self._panel0(), self._panel1(), self._panel2(),
            self._panel3(), self._panel4(), self._panel5(),
        ]
        for p in self._panels:
            ml.AddRow(p)
        self._sync_panels()
        ml.AddRow(self._sep())

        # GROWTH PARAMETERS
        ml.AddRow(self._section("GROWTH PARAMETERS"))
        self._num_roots = self._num(DEFAULTS["num_roots"], 1, 200, 0, 1); self._num_roots.DecimalPlaces = 0
        self._inf_r     = self._num(DEFAULTS["influence_radius"], 1, 5000, 1)
        self._kill_d    = self._num(DEFAULTS["kill_distance"], 0.1, 1000, 1)
        self._step_d    = self._num(DEFAULTS["step_distance"], 0.1, 1000, 1)
        self._max_iter  = self._num(DEFAULTS["max_iterations"], 10, 5000, 0, 10); self._max_iter.DecimalPlaces = 0

        self._jitter_sl  = ef.Slider(); self._jitter_sl.MinValue = 0; self._jitter_sl.MaxValue = 100
        self._jitter_sl.Value = int(DEFAULTS["random_noise"] * 100); self._jitter_sl.Width = 140
        self._jitter_lbl = self._lbl("{}%".format(self._jitter_sl.Value), w=40)
        self._jitter_sl.ValueChanged += lambda s, e: self._jitter_lbl.__setattr__(
            "Text", "{}%".format(self._jitter_sl.Value))

        self._draw_delay = self._num(DEFAULTS["draw_delay_ms"], 0, 2000, 0, 5); self._draw_delay.DecimalPlaces = 0
        self._show_attr  = ef.CheckBox(); self._show_attr.Text = ""; self._show_attr.Checked = DEFAULTS["show_attractors"]
        self._disp_style_dd = ef.DropDown()
        for s in DISPLAY_STYLES:
            self._disp_style_dd.Items.Add(s)
        self._disp_style_dd.SelectedIndex = DISPLAY_STYLES.index(DEFAULTS["display_style"])
        self._disp_style_dd.SelectedIndexChanged += self._on_disp_style_changed

        ml.AddRow(self._row("Root count:",       self._num_roots))
        ml.AddRow(self._desc("Seed points placed at the base of the attractor cloud.  More roots = wider coverage."))
        ml.AddRow(self._row("Influence radius:", self._inf_r))
        ml.AddRow(self._desc("Max reach an attractor has to pull a branch node.  Auto-scales if too small."))
        ml.AddRow(self._row("Kill distance:",    self._kill_d))
        ml.AddRow(self._desc("Attractor is consumed when a node comes this close.  Keep smaller than Step distance."))
        ml.AddRow(self._row("Step distance:",    self._step_d))
        ml.AddRow(self._desc("Length of each new branch segment per growth cycle.  Smaller = finer detail."))
        ml.AddRow(self._row("Max iterations:",   self._max_iter))
        ml.AddRow(self._desc("Maximum growth cycles.  Also stops early when all attractors are consumed."))

        jitter_tl = ef.TableLayout(); jitter_tl.Spacing = edraw.Size(8, 0)
        jitter_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("Jitter:", w=160)),
            ef.TableCell(ef.TableLayout.AutoSized(self._jitter_sl)),
            ef.TableCell(self._jitter_lbl)))
        ml.AddRow(jitter_tl)
        ml.AddRow(self._desc("Random direction noise.  0% = geometric.  15–25% = organic.  50%+ = chaotic cloud."))

        ml.AddRow(self._row("Display style:", self._disp_style_dd))
        ml.AddRow(self._desc("A Bloom+Trail: branch flash + pulsing dots.   B Glowing Neon: cyan glow.\n"
                              "C Heat Map: dots coloured by density.          D Branch-Only: clean lines.\n"
                              "E Particle Field: dot size = proximity.        F Depth Fog: Z-based fade."))
        ml.AddRow(self._row("Draw delay (ms):", self._draw_delay))
        ml.AddRow(self._desc("Pause between animation frames.  0 = instant.  20–50 ms = smooth visible animation."))
        ml.AddRow(self._row("Show attractors:", self._show_attr))
        ml.AddRow(self._desc("Display attractor dots.  Consumed dot behaviour varies by display style."))
        ml.AddRow(self._sep())

        # ── INFLUENCE FIELD ─────────────────────────────────────────────────
        ml.AddRow(self._section("INFLUENCE FIELD"))
        self._inf_type_dd = ef.DropDown()
        for t in INFLUENCE_TYPES:
            self._inf_type_dd.Items.Add(t)
        self._inf_type_dd.SelectedIndex = INFLUENCE_TYPES.index(DEFAULTS["influence_type"])
        self._inf_type_dd.SelectedIndexChanged += self._on_inf_type_changed
        ml.AddRow(self._inf_type_dd)
        ml.AddRow(self._desc("External force that biases branch growth direction on top of attractor pull."))

        self._inf_weight = self._num(DEFAULTS["influence_weight"], 0.0, 2.0, 2, 0.05)
        ml.AddRow(self._row("Influence weight:", self._inf_weight))
        ml.AddRow(self._desc("0 = pure SCA (no bias).  0.5 = balanced.  1.0+ = strongly driven by influence."))

        # Conditional sub-panels
        self._inf_p_climate = self._inf_panel_climate()
        self._inf_p_sun     = self._inf_panel_sun()
        self._inf_p_wind    = self._inf_panel_wind()
        self._inf_p_custom  = self._inf_panel_custom()
        for ip in (self._inf_p_climate, self._inf_p_sun, self._inf_p_wind, self._inf_p_custom):
            ml.AddRow(ip)
        self._sync_inf_panels()
        ml.AddRow(self._sep())

        # ── POINT ATTRACTOR FIELD ────────────────────────────────────────────
        # Section header + enable toggle on the same row
        pt_hdr_tl = ef.TableLayout(); pt_hdr_tl.Spacing = edraw.Size(8, 0)
        self._pt_enable = ef.CheckBox()
        self._pt_enable.Text    = "POINT ATTRACTOR FIELD"
        self._pt_enable.Checked = DEFAULTS["point_attractor_enabled"]
        self._pt_enable.Font    = edraw.Font(self._pt_enable.Font.Family,
                                             self._pt_enable.Font.Size,
                                             edraw.FontStyle.Bold)
        self._pt_enable.CheckedChanged += self._on_pt_enable_changed
        pt_hdr_tl.Rows.Add(ef.TableRow(ef.TableCell(self._pt_enable)))
        ml.AddRow(pt_hdr_tl)
        ml.AddRow(self._desc("Pick Rhino points — they persistently bias branch direction on top of attractor pull.\n"
                              "Works with any mode.  Dense clusters → dense branching.  Never consumed."))

        # All controls below live in a single panel so one .Enabled toggle greys them all
        self._pt_body = ef.Panel()
        pb = ef.DynamicLayout(); pb.DefaultSpacing = edraw.Size(6, 4); pb.Padding = edraw.Padding(0)

        pt_pick_btn = ef.Button(); pt_pick_btn.Text = "Pick Points"
        pt_pick_btn.Click += self._on_pick_points
        self._pt_lbl = self._lbl("0 points selected")
        pt_row = ef.TableLayout(); pt_row.Spacing = edraw.Size(8, 0)
        pt_row.Rows.Add(ef.TableRow(ef.TableCell(pt_pick_btn),
                                    ef.TableCell(self._pt_lbl)))
        pb.AddRow(pt_row)

        self._pt_beh_dd = ef.DropDown()
        for b in POINT_BEHAVIORS:
            self._pt_beh_dd.Items.Add(b)
        self._pt_beh_dd.SelectedIndex = 0
        self._pt_beh_dd.SelectedIndexChanged += self._on_pt_behavior_changed
        pb.AddRow(self._row("Behaviour:", self._pt_beh_dd))

        # Weight + Invert row
        self._pt_weight = self._num(DEFAULTS["point_attractor_weight"], 0.01, 3.0, 2, 0.05)
        self._pt_invert = ef.CheckBox(); self._pt_invert.Text = "Invert (repel)"
        self._pt_invert.Checked = DEFAULTS["point_invert"]
        wi_row = ef.TableLayout(); wi_row.Spacing = edraw.Size(8, 0)
        wi_row.Rows.Add(ef.TableRow(ef.TableCell(ef.Label() if False else
                        self._row("Point weight:", self._pt_weight)),
                        ef.TableCell(self._pt_invert)))
        pb.AddRow(self._row("Point weight:", self._pt_weight))
        pb.AddRow(self._pt_invert)
        pb.AddRow(self._desc("0.1–0.3 = subtle.  1.0+ = strong shaping.\n"
                              "Invert = branches are REPELLED away from points instead of attracted."))

        self._pt_search_r = self._num(DEFAULTS["point_search_radius"], 0.0, 5000.0, 1)
        pb.AddRow(self._row("Search radius:", self._pt_search_r))
        pb.AddRow(self._desc("Branches within this range feel the point field.  0 = auto (2.5× influence radius)."))

        self._pt_body.Content = pb
        self._pt_body.Enabled = DEFAULTS["point_attractor_enabled"]
        ml.AddRow(self._pt_body)

        # ── conditional behaviour sub-panels (inside _pt_body) ──────────────
        # Density Pull
        self._pt_p_density = ef.Panel()
        dl = ef.DynamicLayout(); dl.DefaultSpacing = edraw.Size(4,3); dl.Padding = edraw.Padding(4)
        self._pt_dens_r = self._num(DEFAULTS["point_density_radius"], 1, 5000, 1)
        dl.AddRow(self._desc("HOW IT WORKS  ·  Density Pull"))
        dl.AddRow(self._desc(
            "Each point checks how many other points sit within its density radius.\n"
            "Isolated point → pull weight 1.0 (baseline).\n"
            "Point with 1 neighbour → weight 2.5.  3 neighbours → weight 5.5.\n"
            "Result: SCA branches concentrate and densify where points are clustered\n"
            "while staying sparse in open areas — mimicking biological growth toward\n"
            "nutrient-rich zones.\n"
            "\n"
            "USE CASE  Place dense clusters on a facade where you want structural\n"
            "concentration (joints, corners, load paths) and isolated points where\n"
            "you want light branching."))
        dl.AddRow(self._sep())
        dl.AddRow(self._row("Density radius:", self._pt_dens_r))
        dl.AddRow(self._desc("Distance within which two points count as neighbours.\n"
                              "Increase to group more points into clusters."))
        self._pt_p_density.Content = dl

        # Repulsion
        self._pt_p_repul = ef.Panel()
        rl = ef.DynamicLayout(); rl.DefaultSpacing = edraw.Size(4,3); rl.Padding = edraw.Padding(4)
        rl.AddRow(self._desc("HOW IT WORKS  ·  Repulsion"))
        rl.AddRow(self._desc(
            "Picked points act as negative attractors — they push branches away\n"
            "using a quadratic falloff force.  The closer a branch is to a repulsion\n"
            "point, the stronger the push.  Effect fades to zero at Search Radius.\n"
            "\n"
            "Result: branches actively avoid repulsion zones, carving clear voids,\n"
            "openings, or gap corridors through the network.\n"
            "\n"
            "USE CASE  Place repulsion points where you need door openings, window\n"
            "voids, or circulation gaps in a facade branching pattern.  Combine with\n"
            "Density Pull on another run for push-pull control.  Increase Point Weight\n"
            "to widen the void; reduce to create only subtle thinning."))
        self._pt_p_repul.Content = rl

        # Weighted Strength
        self._pt_p_weight = ef.Panel()
        wl = ef.DynamicLayout(); wl.DefaultSpacing = edraw.Size(4,3); wl.Padding = edraw.Padding(4)
        self._pt_wt_default = self._num(DEFAULTS["point_weight_default"], 0.1, 20.0, 1, 0.5)
        wl.AddRow(self._desc("HOW IT WORKS  ·  Weighted Strength"))
        wl.AddRow(self._desc(
            "Each point has an individual pull strength you control manually.\n"
            "Strong points (high weight) pull branches from further away and\n"
            "create denser convergence.  Weak points (low weight) create only\n"
            "gentle local deflection.\n"
            "\n"
            "To set a custom weight: select the point in Rhino, open Object\n"
            "Properties, set the Name field to  w=2.5  (any number).\n"
            "Points without a name use the Default Weight below.\n"
            "\n"
            "USE CASE  Fine-tune which structural nodes attract more branches —\n"
            "e.g. column bases w=5.0, mid-span points w=1.0, tips w=0.5."))
        wl.AddRow(self._sep())
        wl.AddRow(self._row("Default weight:", self._pt_wt_default))
        wl.AddRow(self._desc("Fallback for all points not named 'w=N'.  1.0 = neutral baseline."))
        self._pt_p_weight.Content = wl

        # Depth Gradient
        self._pt_p_depth = ef.Panel()
        zl = ef.DynamicLayout(); zl.DefaultSpacing = edraw.Size(4,3); zl.Padding = edraw.Padding(4)
        zl.AddRow(self._desc("HOW IT WORKS  ·  Depth Gradient"))
        zl.AddRow(self._desc(
            "Pull strength is automatically derived from each point's Z height.\n"
            "The lowest picked point gets weight 0.3 (weak pull).\n"
            "The highest picked point gets weight 3.0 (strong pull).\n"
            "All points in between interpolate linearly.\n"
            "\n"
            "Result: SCA branches lean upward and concentrate around the highest\n"
            "points, creating a natural tapering structure — dense at the top,\n"
            "sparse at the base — without any manual weight assignment.\n"
            "\n"
            "USE CASE  Tall facades or towers where structural density should\n"
            "increase at the top (wind/load response).  Also useful for canopies\n"
            "where the apex attracts the most branching."))
        self._pt_p_depth.Content = zl

        # Waypoint Sequence
        self._pt_p_waypt = ef.Panel()
        ql = ef.DynamicLayout(); ql.DefaultSpacing = edraw.Size(4,3); ql.Padding = edraw.Padding(4)
        ql.AddRow(self._desc("HOW IT WORKS  ·  Waypoint Sequence"))
        ql.AddRow(self._desc(
            "Points are treated as ordered gates, numbered by pick order.\n"
            "SCA begins by pulling toward Gate 0 only.  Once any branch\n"
            "reaches within 4× Kill Distance of Gate 0, Gate 1 activates —\n"
            "the field shifts to pull toward the next point.  This continues\n"
            "sequentially through all picked points.\n"
            "\n"
            "Result: branches follow a prescribed directed route through the\n"
            "volume, visiting each gate in sequence like vascular tissue growing\n"
            "along a structural rib or program path.\n"
            "\n"
            "USE CASE  Circulation spines, staircase routes, structural ribs\n"
            "that must connect a series of program nodes in order.  Pick points\n"
            "along the desired path — SCA grows from one to the next.\n"
            "Tip: set Jitter low (5–10%) for cleaner directed paths."))
        self._pt_p_waypt.Content = ql

        # Orbital Swirl
        self._pt_p_orbital = ef.Panel()
        ol = ef.DynamicLayout(); ol.DefaultSpacing = edraw.Size(4,3); ol.Padding = edraw.Padding(4)
        ol.AddRow(self._desc("HOW IT WORKS  ·  Orbital Swirl"))
        ol.AddRow(self._desc(
            "Instead of pulling branches straight toward each point, Orbital\n"
            "Swirl adds a 90° tangential deflection — the cross product of the\n"
            "radial direction and the Z-up axis.  Branches are nudged sideways\n"
            "around each point rather than into it.\n"
            "\n"
            "Result: branches spiral and orbit around nearby points, creating\n"
            "vortex or whirlpool patterns.  The spiral tightens as branches\n"
            "approach, producing dense convergence at the centre.\n"
            "\n"
            "USE CASE  Decorative column capitals, joint details, or any area\n"
            "where rotational branching character is desired.  Works best with\n"
            "Point Weight 0.8–1.5, Jitter below 15%, and points spaced wider\n"
            "than the Influence Radius so orbits don't interfere."))
        self._pt_p_orbital.Content = ol

        for subp in (self._pt_p_density, self._pt_p_repul, self._pt_p_weight,
                     self._pt_p_depth, self._pt_p_waypt, self._pt_p_orbital):
            pb.AddRow(subp)
        self._sync_pt_panels()
        ml.AddRow(self._sep())

        # OUTPUT
        ml.AddRow(self._section("OUTPUT"))
        self._pipes_chk = ef.CheckBox(); self._pipes_chk.Text = "Bake pipe Breps"
        self._pipes_chk.Checked = DEFAULTS["output_pipes"]
        self._pipes_chk.CheckedChanged += self._on_pipes_toggle
        ml.AddRow(self._pipes_chk)
        ml.AddRow(self._desc("Solid tapered pipe Breps along each branch.  "
                              "Compatible with Discrete Element V6.  Baked to SCA_Pipes layer."))
        self._pipe_panel = ef.Panel()
        pipe_ly = ef.DynamicLayout(); pipe_ly.DefaultSpacing = edraw.Size(4,4); pipe_ly.Padding = edraw.Padding(4)
        self._pipe_r = self._num(DEFAULTS["pipe_radius"], 0.01, 500, 2, 0.5)
        self._taper  = self._num(DEFAULTS["taper_ratio"], 1.0, 20, 1, 0.5)
        pipe_ly.AddRow(self._row("Tip radius:",  self._pipe_r))
        pipe_ly.AddRow(self._desc("Pipe radius at the thinnest branch tips."))
        pipe_ly.AddRow(self._row("Taper ratio:", self._taper))
        pipe_ly.AddRow(self._desc("Root radius = Tip radius × Taper ratio.  1.0 = uniform.  4.0 = roots 4× thicker."))
        self._pipe_panel.Content = pipe_ly
        self._pipe_panel.Visible = DEFAULTS["output_pipes"]
        ml.AddRow(self._pipe_panel)
        ml.AddRow(self._sep())

        # ── AGGREGATION ─────────────────────────────────────────────────────────
        agg_hdr_tl = ef.TableLayout(); agg_hdr_tl.Spacing = edraw.Size(8, 0)
        self._agg_enable = ef.CheckBox()
        self._agg_enable.Text    = "AGGREGATION"
        self._agg_enable.Checked = DEFAULTS["agg_enabled"]
        self._agg_enable.Font    = edraw.Font(self._agg_enable.Font.Family,
                                              self._agg_enable.Font.Size,
                                              edraw.FontStyle.Bold)
        self._agg_enable.CheckedChanged += self._on_agg_enable_changed
        agg_hdr_tl.Rows.Add(ef.TableRow(ef.TableCell(self._agg_enable)))
        ml.AddRow(agg_hdr_tl)
        ml.AddRow(self._desc("Places geometry instances on baked SCA branch curves.\n"
                              "Run Simulate & Bake first — then press Aggregate."))

        # All aggregation controls wrapped in one panel for easy enable/disable
        self._agg_body = ef.Panel()
        agg_body_ly = ef.DynamicLayout()
        agg_body_ly.DefaultSpacing = edraw.Size(6, 4)
        agg_body_ly.Padding        = edraw.Padding(0)

        # ── Manual Axis toggle ───────────────────────────────────────────────
        self._agg_manual_axis = ef.CheckBox()
        self._agg_manual_axis.Text    = "Manual axis (Set Start / End Points)"
        self._agg_manual_axis.Checked = DEFAULTS["agg_manual_axis"]
        self._agg_manual_axis.CheckedChanged += self._on_agg_manual_axis_changed
        agg_body_ly.AddRow(self._agg_manual_axis)
        agg_body_ly.AddRow(self._desc(
            "OFF (default) — axis auto-detected from each geometry's longest bounding-box dimension.\n"
            "ON  — click Set Start / End points on your geometry for precise custom axis control."))
        agg_body_ly.AddRow(ef.Label())

        # ── MODULAR sub-section ──────────────────────────────────────────────
        agg_body_ly.AddRow(self._section("── MODULAR"))
        agg_body_ly.AddRow(self._desc("One geometry instance per branch segment, "
                                      "oriented and scaled to match the segment direction and length."))

        agg_mod_btn = ef.Button(); agg_mod_btn.Text = "Pick Module Geometries"
        agg_mod_btn.Click += self._on_pick_modules
        self._agg_mod_lbl = self._lbl("0 objects")
        agg_mod_clr = ef.Button(); agg_mod_clr.Text = "✕"; agg_mod_clr.Width = 28
        agg_mod_clr.Click += lambda s, e: self._clear_geo_list("module")
        agg_mod_row = ef.TableLayout(); agg_mod_row.Spacing = edraw.Size(4, 0)
        agg_mod_row.Rows.Add(ef.TableRow(ef.TableCell(agg_mod_btn),
                                         ef.TableCell(self._agg_mod_lbl),
                                         ef.TableCell(agg_mod_clr)))
        agg_body_ly.AddRow(agg_mod_row)

        # Manual axis panel for Modular — hidden by default
        self._agg_mod_axis_panel = ef.Panel()
        mod_axis_ly = ef.DynamicLayout(); mod_axis_ly.DefaultSpacing = edraw.Size(4, 2)
        agg_sref_btn = ef.Button(); agg_sref_btn.Text = "Set Start Point"
        agg_sref_btn.Click += self._on_pick_start_ref
        self._agg_sref_lbl = self._lbl("not set")
        agg_sref_row = ef.TableLayout(); agg_sref_row.Spacing = edraw.Size(8, 0)
        agg_sref_row.Rows.Add(ef.TableRow(ef.TableCell(agg_sref_btn),
                                           ef.TableCell(self._agg_sref_lbl)))
        mod_axis_ly.AddRow(agg_sref_row)
        agg_eref_btn = ef.Button(); agg_eref_btn.Text = "Set End Point"
        agg_eref_btn.Click += self._on_pick_end_ref
        self._agg_eref_lbl = self._lbl("not set")
        agg_eref_row = ef.TableLayout(); agg_eref_row.Spacing = edraw.Size(8, 0)
        agg_eref_row.Rows.Add(ef.TableRow(ef.TableCell(agg_eref_btn),
                                           ef.TableCell(self._agg_eref_lbl)))
        mod_axis_ly.AddRow(agg_eref_row)
        mod_axis_ly.AddRow(self._desc("Snap to the two ends of your geometry to define its local axis."))
        self._agg_mod_axis_panel.Content = mod_axis_ly
        self._agg_mod_axis_panel.Visible = DEFAULTS["agg_manual_axis"]
        agg_body_ly.AddRow(self._agg_mod_axis_panel)

        self._agg_scale_dd = ef.DropDown()
        self._agg_scale_dd.Items.Add("Fit")
        self._agg_scale_dd.Items.Add("Repeat")
        self._agg_scale_dd.SelectedIndex = 0
        agg_body_ly.AddRow(self._row("Scale mode:", self._agg_scale_dd))
        agg_body_ly.AddRow(self._desc("Fit = stretch one instance to fill the segment.\n"
                                      "Repeat = tile at original size, truncate at segment end."))

        self._agg_mod_scale = self._num(DEFAULTS["agg_module_scale"], 0.0, 100.0, 2, 0.1)
        agg_body_ly.AddRow(self._row("Module scale:", self._agg_mod_scale))
        agg_body_ly.AddRow(self._desc("Cross-section thickness multiplier.\n"
                                      "0 = uniform auto-fit (length and width scale together).\n"
                                      "1.0 = original modelled width. 2.0 = twice as thick.\n"
                                      "Length always fills the segment regardless of this value."))

        self._agg_mod_gap = self._num(DEFAULTS["agg_module_gap"], 0.0, 5000, 2, 0.5)
        agg_body_ly.AddRow(self._row("Module gap:", self._agg_mod_gap))
        agg_body_ly.AddRow(self._desc("Pulls each module back from both ends of its segment.\n"
                                      "0 = modules touch node points flush (default).\n"
                                      "Set > 0 to reveal joint geometry — gap fills with arm geo if picked."))
        agg_body_ly.AddRow(ef.Label())

        # ── JOINT sub-section ────────────────────────────────────────────────
        agg_body_ly.AddRow(self._section("── JOINT"))
        agg_body_ly.AddRow(self._desc("Places geometry at every internal node — linear connections and branching."))

        self._agg_joint_chk = ef.CheckBox()
        self._agg_joint_chk.Text    = "Enable joints"
        self._agg_joint_chk.Checked = DEFAULTS["agg_joint_enabled"]
        self._agg_joint_chk.CheckedChanged += self._on_joint_enable_changed
        agg_body_ly.AddRow(self._agg_joint_chk)

        self._agg_joint_panel = ef.Panel()
        jnt_ly = ef.DynamicLayout()
        jnt_ly.DefaultSpacing = edraw.Size(6, 4)
        jnt_ly.Padding        = edraw.Padding(4)

        # ── NODE geometry ────────────────────────────────────────────────────
        jnt_ly.AddRow(self._desc("NODE GEOMETRY  —  placed once at each branching node"))
        agg_node_btn = ef.Button(); agg_node_btn.Text = "Pick Node Geometries"
        agg_node_btn.Click += self._on_pick_node_geos
        self._agg_node_lbl = self._lbl("0 objects")
        agg_node_clr = ef.Button(); agg_node_clr.Text = "✕"; agg_node_clr.Width = 28
        agg_node_clr.Click += lambda s, e: self._clear_geo_list("node")
        agg_node_row = ef.TableLayout(); agg_node_row.Spacing = edraw.Size(4, 0)
        agg_node_row.Rows.Add(ef.TableRow(ef.TableCell(agg_node_btn),
                                           ef.TableCell(self._agg_node_lbl),
                                           ef.TableCell(agg_node_clr)))
        jnt_ly.AddRow(agg_node_row)

        agg_nref_s_btn = ef.Button(); agg_nref_s_btn.Text = "Set Node Start Pt"
        agg_nref_s_btn.Click += self._on_pick_node_start
        self._agg_nref_s_lbl = self._lbl("not set")
        agg_nref_s_row = ef.TableLayout(); agg_nref_s_row.Spacing = edraw.Size(8, 0)
        agg_nref_s_row.Rows.Add(ef.TableRow(ef.TableCell(agg_nref_s_btn),
                                             ef.TableCell(self._agg_nref_s_lbl)))

        agg_nref_e_btn = ef.Button(); agg_nref_e_btn.Text = "Set Node End Pt"
        agg_nref_e_btn.Click += self._on_pick_node_end
        self._agg_nref_e_lbl = self._lbl("not set")
        agg_nref_e_row = ef.TableLayout(); agg_nref_e_row.Spacing = edraw.Size(8, 0)
        agg_nref_e_row.Rows.Add(ef.TableRow(ef.TableCell(agg_nref_e_btn),
                                             ef.TableCell(self._agg_nref_e_lbl)))

        # Manual axis panel for Node — hidden by default
        self._agg_node_axis_panel = ef.Panel()
        node_axis_ly = ef.DynamicLayout(); node_axis_ly.DefaultSpacing = edraw.Size(4, 2)
        node_axis_ly.AddRow(agg_nref_s_row)
        node_axis_ly.AddRow(agg_nref_e_row)
        node_axis_ly.AddRow(self._desc("Snap to base then top of your node geometry to define its axis."))
        self._agg_node_axis_panel.Content = node_axis_ly
        self._agg_node_axis_panel.Visible = DEFAULTS["agg_manual_axis"]
        jnt_ly.AddRow(self._agg_node_axis_panel)

        self._agg_node_scale = self._num(DEFAULTS["agg_node_scale"], 0.0, 100.0, 2, 0.1)
        jnt_ly.AddRow(self._row("Node scale:", self._agg_node_scale))
        jnt_ly.AddRow(self._desc("Multiplier on auto-fit.\n"
                                  "0   = pure auto-fit (disc diameter = bar cross-section).\n"
                                  "1.0 = same as auto-fit (matches bar width).\n"
                                  "2.0 = twice as wide.   0.5 = half as wide.  Bars always flush."))
        jnt_ly.AddRow(ef.Label())

        # ── ARM geometry ─────────────────────────────────────────────────────
        jnt_ly.AddRow(self._desc("ARM GEOMETRY  —  one per connected branch at each node\n"
                                  "N branches at this node → N arms placed automatically."))
        agg_arm_btn = ef.Button(); agg_arm_btn.Text = "Pick Arm Geometries"
        agg_arm_btn.Click += self._on_pick_arm_geos
        self._agg_arm_lbl = self._lbl("0 objects")
        agg_arm_clr = ef.Button(); agg_arm_clr.Text = "✕"; agg_arm_clr.Width = 28
        agg_arm_clr.Click += lambda s, e: self._clear_geo_list("arm")
        agg_arm_row = ef.TableLayout(); agg_arm_row.Spacing = edraw.Size(4, 0)
        agg_arm_row.Rows.Add(ef.TableRow(ef.TableCell(agg_arm_btn),
                                          ef.TableCell(self._agg_arm_lbl),
                                          ef.TableCell(agg_arm_clr)))
        jnt_ly.AddRow(agg_arm_row)

        agg_aref_s_btn = ef.Button(); agg_aref_s_btn.Text = "Set Arm Start Pt"
        agg_aref_s_btn.Click += self._on_pick_arm_start
        self._agg_aref_s_lbl = self._lbl("not set")
        agg_aref_s_row = ef.TableLayout(); agg_aref_s_row.Spacing = edraw.Size(8, 0)
        agg_aref_s_row.Rows.Add(ef.TableRow(ef.TableCell(agg_aref_s_btn),
                                             ef.TableCell(self._agg_aref_s_lbl)))

        agg_aref_e_btn = ef.Button(); agg_aref_e_btn.Text = "Set Arm End Pt"
        agg_aref_e_btn.Click += self._on_pick_arm_end
        self._agg_aref_e_lbl = self._lbl("not set")
        agg_aref_e_row = ef.TableLayout(); agg_aref_e_row.Spacing = edraw.Size(8, 0)
        agg_aref_e_row.Rows.Add(ef.TableRow(ef.TableCell(agg_aref_e_btn),
                                             ef.TableCell(self._agg_aref_e_lbl)))

        # Manual axis panel for Arm — hidden by default
        self._agg_arm_axis_panel = ef.Panel()
        arm_axis_ly = ef.DynamicLayout(); arm_axis_ly.DefaultSpacing = edraw.Size(4, 2)
        arm_axis_ly.AddRow(agg_aref_s_row)
        arm_axis_ly.AddRow(agg_aref_e_row)
        arm_axis_ly.AddRow(self._desc("Start = centre-side end (sits at node).  End = outer tip."))
        self._agg_arm_axis_panel.Content = arm_axis_ly
        self._agg_arm_axis_panel.Visible = DEFAULTS["agg_manual_axis"]
        jnt_ly.AddRow(self._agg_arm_axis_panel)
        self._agg_arm_offset = self._num(DEFAULTS["agg_arm_offset"], 0.0, 5000, 2, 0.5)
        jnt_ly.AddRow(self._row("Arm offset:", self._agg_arm_offset))
        jnt_ly.AddRow(self._desc("Distance from node centre to the arm's start point (world units).\n"
                                  "0 = arm starts at node centre.\n"
                                  "Set to clear the node joint disc: arm offset ≥ node radius.\n"
                                  "For a flush fit: Module gap = Arm offset + (arm length × Arm scale)."))
        self._agg_arm_scale = self._num(DEFAULTS["agg_arm_scale"], 0.01, 100.0, 2, 0.1)
        jnt_ly.AddRow(self._row("Arm scale:", self._agg_arm_scale))
        jnt_ly.AddRow(self._desc("Uniform size multiplier for arm geometry.\n"
                                  "1.0 = original modelled size.  Arm is placed, not stretched."))

        self._agg_joint_panel.Content = jnt_ly
        self._agg_joint_panel.Visible = DEFAULTS["agg_joint_enabled"]
        agg_body_ly.AddRow(self._agg_joint_panel)
        agg_body_ly.AddRow(ef.Label())

        # Aggregation seed
        self._agg_seed = self._num(DEFAULTS["agg_seed"], 0, 999999, 0, 1)
        self._agg_seed.DecimalPlaces = 0
        agg_body_ly.AddRow(self._row("Aggregation seed:", self._agg_seed))
        agg_body_ly.AddRow(self._desc("Seed for random geometry pool selection.  "
                                      "Different seed = different per-segment assignments."))
        agg_body_ly.AddRow(ef.Label())

        # Aggregate + Clear buttons
        agg_btn     = ef.Button(); agg_btn.Text = "Aggregate";       agg_btn.Width = 120
        agg_clr_btn = ef.Button(); agg_clr_btn.Text = "Clear Aggregation"
        agg_btn.Click     += self._on_aggregate
        agg_clr_btn.Click += self._on_clear_aggregation
        agg_act_tl = ef.TableLayout(); agg_act_tl.Spacing = edraw.Size(8, 0)
        agg_act_tl.Rows.Add(ef.TableRow(ef.TableCell(agg_btn),
                                         ef.TableCell(agg_clr_btn)))
        agg_body_ly.AddRow(agg_act_tl)
        agg_body_ly.AddRow(self._desc(
            "Output → SCA_Aggregation::Modular  ·  ::Joint_Node  ·  ::Joint_Arm\n"
            "Ctrl+Z undoes all aggregation objects.  Re-run to replace."))

        self._agg_body.Content = agg_body_ly
        self._agg_body.Enabled = DEFAULTS["agg_enabled"]
        ml.AddRow(self._agg_body)
        ml.AddRow(self._sep())

        # SEED
        ml.AddRow(self._section("SEED"))
        self._seed_n = self._num(DEFAULTS["seed"], 0, 999999, 0, 1); self._seed_n.DecimalPlaces = 0
        rnd_btn = ef.Button(); rnd_btn.Text = "Randomize"
        rnd_btn.Click += lambda s, e: self._seed_n.__setattr__("Value", random.randint(0, 99999))
        seed_tl = ef.TableLayout(); seed_tl.Spacing = edraw.Size(8, 0)
        seed_tl.Rows.Add(ef.TableRow(ef.TableCell(self._lbl("Seed:", w=160)),
                                     ef.TableCell(self._seed_n),
                                     ef.TableCell(rnd_btn)))
        ml.AddRow(seed_tl)
        ml.AddRow(self._desc("Fixed seed = reproducible form every run.  Randomize to explore variations."))
        ml.AddRow(self._sep())

        # ACTION BUTTONS
        btn_sim = ef.Button(); btn_sim.Text = "Simulate & Bake"; btn_sim.Width = 140
        btn_clr = ef.Button(); btn_clr.Text = "Clear"
        btn_cls = ef.Button(); btn_cls.Text = "Close"
        btn_sim.Click += self._on_simulate
        btn_clr.Click += self._on_clear
        btn_cls.Click += lambda s, e: self.Close()
        act_tl = ef.TableLayout(); act_tl.Spacing = edraw.Size(8, 0)
        act_tl.Rows.Add(ef.TableRow(ef.TableCell(btn_sim),
                                    ef.TableCell(btn_clr),
                                    ef.TableCell(btn_cls)))
        ml.AddRow(act_tl)

        self._status = ef.Label()
        self._status.Text      = "Ready"
        self._status.TextColor = edraw.Colors.DarkSlateGray
        ml.AddRow(self._status)

        scr = ef.Scrollable(); scr.Content = ml
        scr.ExpandContentWidth = True; scr.ExpandContentHeight = False
        self.Content = scr

    # ── helpers ──────────────────────────────────────────────────────────────

    def _refresh_ccs_status(self):
        ccs      = sc.sticky.get("ccs_data")
        clim_vox = sc.sticky.get("climate_voxels")
        if ccs:
            self._inf_ccs_lbl.Text = "ccs_data: {} voxels loaded ✓  (Climate Comfort Special V1)".format(len(ccs))
            self._inf_ccs_lbl.TextColor = edraw.Colors.DarkGreen
        elif clim_vox:
            self._inf_ccs_lbl.Text = "climate_voxels: {} voxels loaded ✓  (Melbourne Climate Voxel Attractor)".format(len(clim_vox))
            self._inf_ccs_lbl.TextColor = edraw.Colors.DarkGreen
        else:
            self._inf_ccs_lbl.Text = ("⚠  No climate data in sticky.\n"
                                      "Run Melbourne Climate Voxel Attractor V1\n"
                                      "OR Climate Comfort Special V1 first.")
            self._inf_ccs_lbl.TextColor = edraw.Colors.OrangeRed

    def _sync_panels(self):
        sel = self._mode_dd.SelectedIndex
        for i, p in enumerate(self._panels):
            p.Visible = (i == sel)

    def _sync_inf_panels(self):
        sel = self._inf_type_dd.SelectedIndex
        # 0=None 1=ClimateHeat 2=Sun 3=Wind 4=Gravity 5=Custom
        self._inf_p_climate.Visible = (sel == 1)
        self._inf_p_sun.Visible     = (sel == 2)
        self._inf_p_wind.Visible    = (sel == 3)
        self._inf_p_custom.Visible  = (sel == 5)
        # Weight row visible for all except None
        self._inf_weight.Enabled    = (sel != 0)

    # ── event handlers ───────────────────────────────────────────────────────

    def _on_disp_style_changed(self, sender, e):
        self._conduit._style = DISPLAY_STYLES[self._disp_style_dd.SelectedIndex]
        sc.doc.Views.Redraw()

    def _on_mode_changed(self, sender, e):
        self._sync_panels()

    def _on_inf_type_changed(self, sender, e):
        self._sync_inf_panels()
        if self._inf_type_dd.SelectedIndex == 1:
            self._refresh_ccs_status()

    def _on_pipes_toggle(self, sender, e):
        self._pipe_panel.Visible = bool(self._pipes_chk.Checked)

    def _on_pick_voxels(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        guids = rs.GetObjects("Select voxel objects",
                              rs.filter.polysurface | rs.filter.mesh |
                              rs.filter.surface | rs.filter.extrusion, preselect=False)
        self.Visible = True
        if guids:
            self._voxel_guids = list(guids)
            self._p1_lbl.Text = "{} objects selected".format(len(guids))
        else:
            self._p1_lbl.Text = "0 objects selected"

    def _clear_surface_list(self):
        self._surface_guids = []
        self._p2_lbl.Text   = "0 surfaces picked"

    def _on_pick_surface(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        subd_filter = getattr(rs.filter, "subd", 262144)
        guids = rs.GetObjects("Pick surfaces / meshes (multiple allowed)",
                              rs.filter.surface | rs.filter.polysurface |
                              rs.filter.mesh | subd_filter, preselect=False)
        self.Visible = True
        if guids:
            self._surface_guids = list(guids)
            self._p2_lbl.Text   = "{} surface{}".format(
                len(guids), "s" if len(guids) != 1 else "")
        # if cancelled, keep existing selection

    def _on_pick_climate(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        guids = rs.GetObjects("Select climate voxel objects",
                              rs.filter.polysurface | rs.filter.mesh |
                              rs.filter.surface | rs.filter.extrusion, preselect=False)
        self.Visible = True
        if guids:
            self._climate_guids = list(guids)
            self._p3_lbl.Text = "{} climate voxels selected".format(len(guids))
        else:
            self._p3_lbl.Text = "0 climate voxels selected"

    def _on_pick_curves(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        guids = rs.GetObjects("Pick curves for SCA attractor network",
                              rs.filter.curve, preselect=False)
        self.Visible = True
        if guids:
            self._curve_guids = list(guids)
            self._p5_lbl.Text = "{} curves selected".format(len(guids))
        else:
            self._p5_lbl.Text = "0 curves selected"

    def _on_pick_points(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        guids = rs.GetObjects("Pick point objects for attractor field",
                              rs.filter.point, preselect=False)
        self.Visible = True
        if guids:
            self._point_guids = list(guids)
            self._pt_lbl.Text = "{} points selected".format(len(guids))
        else:
            self._pt_lbl.Text = "0 points selected"

    def _on_pt_enable_changed(self, sender, e):
        self._pt_body.Enabled = bool(self._pt_enable.Checked)

    def _on_pt_behavior_changed(self, sender, e):
        self._sync_pt_panels()

    def _sync_pt_panels(self):
        sel  = self._pt_beh_dd.SelectedIndex
        subs = [self._pt_p_density, self._pt_p_repul, self._pt_p_weight,
                self._pt_p_depth, self._pt_p_waypt, self._pt_p_orbital]
        for i, sub in enumerate(subs):
            sub.Visible = (i == sel)

    def _on_agg_enable_changed(self, sender, e):
        self._agg_body.Enabled = bool(self._agg_enable.Checked)

    def _on_agg_manual_axis_changed(self, sender, e):
        on = bool(self._agg_manual_axis.Checked)
        # Guard: panels may not exist yet during __init__ construction
        for attr in ("_agg_mod_axis_panel", "_agg_node_axis_panel", "_agg_arm_axis_panel"):
            panel = getattr(self, attr, None)
            if panel is not None:
                panel.Visible = on

    def _on_p2_3d_changed(self, sender, e):
        on = bool(self._p2_3d_chk.Checked)
        self._p2_3d_panel.Visible = on

    def _on_p2_3d_type_changed(self, sender, e):
        self._p2_shells_panel.Visible = (self._p2_3d_type_dd.SelectedIndex == 1)

    def _on_joint_enable_changed(self, sender, e):
        self._agg_joint_panel.Visible = bool(self._agg_joint_chk.Checked)

    def _on_pick_modules(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        guids = rs.GetObjects("Pick module geometries for aggregation",
                              rs.filter.polysurface | rs.filter.mesh |
                              rs.filter.surface | rs.filter.extrusion, preselect=False)
        self.Visible = True
        if guids:
            self._agg_module_guids = list(guids)
            self._agg_mod_lbl.Text = "{} objects".format(len(guids))
        else:
            self._agg_mod_lbl.Text = "0 objects"

    @staticmethod
    def _face_center(msg):
        """Pick a surface/face and return its UV centroid as Point3d.

        Works on:
          - Individual surface faces of a polysurface (Brep sub-object select)
          - Standalone surfaces
          - Mesh faces
        User hovers over the face they want and clicks — the script computes
        the UV midpoint of that face and returns it as a world-space point.
        """
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt(msg + "  (hover over face, then click)")
        # Accept surfaces — this enables picking individual faces of a polysurface
        go.GeometryFilter = Rhino.DocObjects.ObjectType.Surface
        go.EnableSubObjectSelect(True, True)
        go.SubObjectSelect = True
        go.DeselectAllBeforePostSelect = False

        result = go.Get()
        if result != Rhino.Input.GetResult.Object:
            # Fallback: try mesh face
            go2 = Rhino.Input.Custom.GetObject()
            go2.SetCommandPrompt(msg + "  (hover over mesh face, then click)")
            go2.GeometryFilter = Rhino.DocObjects.ObjectType.MeshFace
            go2.EnableSubObjectSelect(True, True)
            go2.SubObjectSelect = True
            result2 = go2.Get()
            if result2 == Rhino.Input.GetResult.Object:
                objref = go2.Object(0)
                mesh = objref.Mesh()
                if mesh:
                    ci = objref.GeometryComponentIndex
                    if ci.ComponentIndexType == rg.ComponentIndexType.MeshFace:
                        fidx = ci.Index
                        if 0 <= fidx < mesh.Faces.Count:
                            return mesh.Faces.GetFaceCenter(fidx)
            return None

        objref = go.Object(0)

        # Brep face (sub-object)
        face = objref.Face()
        if face is not None:
            u = (face.Domain(0).Min + face.Domain(0).Max) * 0.5
            v = (face.Domain(1).Min + face.Domain(1).Max) * 0.5
            return face.PointAt(u, v)

        # Whole standalone surface picked (not sub-object)
        srf = objref.Surface()
        if srf is not None:
            u = (srf.Domain(0).Min + srf.Domain(0).Max) * 0.5
            v = (srf.Domain(1).Min + srf.Domain(1).Max) * 0.5
            return srf.PointAt(u, v)

        # Brep picked as whole object — use its centroid face
        brep_obj = objref.Brep()
        if brep_obj and brep_obj.Faces.Count > 0:
            f = brep_obj.Faces[0]
            u = (f.Domain(0).Min + f.Domain(0).Max) * 0.5
            v = (f.Domain(1).Min + f.Domain(1).Max) * 0.5
            return f.PointAt(u, v)

        return None

    def _on_pick_start_ref(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        pt = self._face_center("Pick the START face of your module geometry — centre will be used")
        self.Visible = True
        if pt:
            self._agg_start_ref     = (pt.X, pt.Y, pt.Z)
            self._agg_sref_lbl.Text = "({:.1f}, {:.1f}, {:.1f})".format(pt.X, pt.Y, pt.Z)
        else:
            self._agg_sref_lbl.Text = "not set"

    def _on_pick_end_ref(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        pt = self._face_center("Pick the END face of your module geometry — centre will be used")
        self.Visible = True
        if pt:
            self._agg_end_ref       = (pt.X, pt.Y, pt.Z)
            self._agg_eref_lbl.Text = "({:.1f}, {:.1f}, {:.1f})".format(pt.X, pt.Y, pt.Z)
        else:
            self._agg_eref_lbl.Text = "not set"

    def _on_pick_node_geos(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        guids = rs.GetObjects("Pick NODE joint geometries (placed once at each branching node)",
                              rs.filter.polysurface | rs.filter.mesh |
                              rs.filter.surface | rs.filter.extrusion, preselect=False)
        self.Visible = True
        if guids:
            self._agg_node_guids   = list(guids)
            self._agg_node_lbl.Text = "{} objects".format(len(guids))
        else:
            self._agg_node_lbl.Text = "0 objects"

    def _on_pick_node_start(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        pt = self._face_center("Pick the BASE face of your node geometry — centre will be used")
        self.Visible = True
        if pt:
            self._agg_node_sref       = (pt.X, pt.Y, pt.Z)
            self._agg_nref_s_lbl.Text = "({:.1f}, {:.1f}, {:.1f})".format(pt.X, pt.Y, pt.Z)
        else:
            self._agg_nref_s_lbl.Text = "not set"

    def _on_pick_node_end(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        pt = self._face_center("Pick the TOP face of your node geometry — centre will be used")
        self.Visible = True
        if pt:
            self._agg_node_eref       = (pt.X, pt.Y, pt.Z)
            self._agg_nref_e_lbl.Text = "({:.1f}, {:.1f}, {:.1f})".format(pt.X, pt.Y, pt.Z)
        else:
            self._agg_nref_e_lbl.Text = "not set"

    def _on_pick_arm_geos(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        guids = rs.GetObjects("Pick ARM geometries (one placed per branch at each node)",
                              rs.filter.polysurface | rs.filter.mesh |
                              rs.filter.surface | rs.filter.extrusion, preselect=False)
        self.Visible = True
        if guids:
            self._agg_arm_guids   = list(guids)
            self._agg_arm_lbl.Text = "{} objects".format(len(guids))
        else:
            self._agg_arm_lbl.Text = "0 objects"

    def _on_pick_arm_start(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        pt = self._face_center("Pick the CENTRE-SIDE face of your arm geometry (sits at node)")
        self.Visible = True
        if pt:
            self._agg_arm_sref        = (pt.X, pt.Y, pt.Z)
            self._agg_aref_s_lbl.Text = "({:.1f}, {:.1f}, {:.1f})".format(pt.X, pt.Y, pt.Z)
        else:
            self._agg_aref_s_lbl.Text = "not set"

    def _on_pick_arm_end(self, sender, e):
        self.Visible = False; Rhino.RhinoApp.Wait()
        pt = self._face_center("Pick the OUTER TIP face of your arm geometry (faces the branch)")
        self.Visible = True
        if pt:
            self._agg_arm_eref        = (pt.X, pt.Y, pt.Z)
            self._agg_aref_e_lbl.Text = "({:.1f}, {:.1f}, {:.1f})".format(pt.X, pt.Y, pt.Z)
        else:
            self._agg_aref_e_lbl.Text = "not set"

    def _clear_geo_list(self, kind):
        if kind == "module":
            self._agg_module_guids  = []
            self._agg_mod_lbl.Text  = "0 objects"
        elif kind == "node":
            self._agg_node_guids    = []
            self._agg_node_lbl.Text = "0 objects"
        elif kind == "arm":
            self._agg_arm_guids     = []
            self._agg_arm_lbl.Text  = "0 objects"

    def _on_aggregate(self, sender, e):
        self._status.Text      = "Running aggregation…"
        self._status.TextColor = edraw.Colors.DarkOrange
        try:
            if not self._last_nodes:
                self._status.Text      = "No simulation data — run Simulate & Bake first."
                self._status.TextColor = edraw.Colors.OrangeRed
                return
            params = self._collect_agg_params()
            result = run_aggregation(params, self._last_nodes)
            if result["ok"]:
                self._status.Text      = result["msg"]
                self._status.TextColor = edraw.Colors.DarkGreen
            else:
                self._status.Text      = result["msg"]
                self._status.TextColor = edraw.Colors.Red
        except Exception as ex:
            self._status.Text      = "Aggregation error: " + str(ex)
            self._status.TextColor = edraw.Colors.Red

    def _on_clear_aggregation(self, sender, e):
        try:
            uid = sc.doc.BeginUndoRecord("SCA V3 Clear Aggregation")
            try:
                _clear_aggregation_layers()
            finally:
                sc.doc.EndUndoRecord(uid)
            sc.doc.Views.Redraw()
            self._status.Text      = "Aggregation layers cleared."
            self._status.TextColor = edraw.Colors.DarkSlateGray
        except Exception as ex:
            self._status.Text      = "Clear error: " + str(ex)
            self._status.TextColor = edraw.Colors.Red

    def _collect_agg_params(self):
        """Collect only aggregation parameters (passed to run_aggregation)."""
        p = {}
        manual = bool(self._agg_manual_axis.Checked)
        p["agg_manual_axis"]   = manual
        # Modular
        p["agg_module_guids"]  = self._agg_module_guids
        # Only pass manual refs when manual axis mode is on; None → auto bbox detection
        p["agg_start_ref"]     = self._agg_start_ref     if manual else None
        p["agg_end_ref"]       = self._agg_end_ref       if manual else None
        p["agg_scale_mode"]    = ["Fit", "Repeat"][self._agg_scale_dd.SelectedIndex]
        p["agg_module_scale"]  = float(self._agg_mod_scale.Value)
        p["agg_module_gap"]    = float(self._agg_mod_gap.Value)
        # Joint
        p["agg_joint_enabled"] = bool(self._agg_joint_chk.Checked)
        p["agg_node_guids"]    = self._agg_node_guids
        p["agg_node_start_ref"]= self._agg_node_sref     if manual else None
        p["agg_node_end_ref"]  = self._agg_node_eref     if manual else None
        p["agg_node_scale"]    = float(self._agg_node_scale.Value)
        p["agg_arm_guids"]     = self._agg_arm_guids
        p["agg_arm_start_ref"] = self._agg_arm_sref      if manual else None
        p["agg_arm_end_ref"]   = self._agg_arm_eref      if manual else None
        p["agg_arm_offset"]    = float(self._agg_arm_offset.Value)
        p["agg_arm_scale"]     = float(self._agg_arm_scale.Value)
        p["agg_seed"]          = int(self._agg_seed.Value)
        return p

    def _collect_params(self):
        p = {}
        p["attractor_mode"]  = int(self._mode_dd.SelectedIndex)
        p["bbox_x"]          = float(self._p0_bx.Value)
        p["bbox_y"]          = float(self._p0_by.Value)
        p["bbox_z"]          = float(self._p0_bz.Value)
        p["num_attractors"]  = int(self._p0_natl.Value)
        p["voxel_guids"]         = self._voxel_guids
        p["voxel_layer_filter"]  = self._p1_filt.Text.strip()
        p["surface_guids"]        = self._surface_guids
        p["surface_u_div"]        = int(self._p2_udiv.Value)
        p["surface_v_div"]        = int(self._p2_vdiv.Value)
        p["surface_noise"]        = self._p2_noise.Value / 100.0
        p["surface_3d_mode"]      = bool(self._p2_3d_chk.Checked)
        p["surface_3d_type"]      = ["Offset", "Shells"][self._p2_3d_type_dd.SelectedIndex]
        p["surface_growth_depth"] = float(self._p2_depth.Value)
        p["surface_shell_count"]  = int(self._p2_shells.Value)
        p["surface_root_offset"]  = float(self._p2_root_off.Value)
        p["climate_voxel_guids"] = self._climate_guids
        p["radiation_bias"]  = float(self._p3_bias.Value)
        p["site_bbox_x"]     = float(self._p4_sx.Value)
        p["site_bbox_y"]     = float(self._p4_sy.Value)
        p["site_bbox_z"]     = float(self._p4_sz.Value)
        p["site_num_attractors"] = int(self._p4_nat.Value)
        p["num_clusters"]    = int(self._p4_nc.Value)
        p["curve_guids"]         = self._curve_guids
        p["curve_sample_count"]  = int(self._p5_samp.Value)
        p["curve_noise"]         = float(self._p5_noise.Value)
        p["num_roots"]       = int(self._num_roots.Value)
        p["influence_radius"]= float(self._inf_r.Value)
        p["kill_distance"]   = float(self._kill_d.Value)
        p["step_distance"]   = float(self._step_d.Value)
        p["random_noise"]    = self._jitter_sl.Value / 100.0
        p["max_iterations"]  = int(self._max_iter.Value)
        p["show_attractors"] = bool(self._show_attr.Checked)
        p["display_style"]   = DISPLAY_STYLES[self._disp_style_dd.SelectedIndex]
        p["draw_delay_ms"]   = int(self._draw_delay.Value)
        p["output_pipes"]    = bool(self._pipes_chk.Checked)
        p["pipe_radius"]     = float(self._pipe_r.Value)
        p["taper_ratio"]     = float(self._taper.Value)
        p["seed"]            = int(self._seed_n.Value)
        # Influence field
        sel = self._inf_type_dd.SelectedIndex
        p["influence_type"]   = INFLUENCE_TYPES[sel]
        p["influence_weight"] = float(self._inf_weight.Value)
        p["sun_month"]        = int(self._inf_sun_month.Value)
        p["sun_hour"]         = float(self._inf_sun_hour.Value)
        p["wind_direction"]   = float(self._inf_wind_dir.Value)
        p["custom_ix"]        = float(self._inf_cx.Value)
        p["custom_iy"]        = float(self._inf_cy.Value)
        p["custom_iz"]        = float(self._inf_cz.Value)
        # Point Attractor Field
        pt_on = bool(self._pt_enable.Checked)
        p["point_attractor_enabled"] = pt_on
        p["point_guids"]             = self._point_guids if pt_on else []
        p["point_behavior"]          = POINT_BEHAVIORS[self._pt_beh_dd.SelectedIndex]
        # Weight is 0 when disabled — grow_one_iteration skips the field entirely
        p["point_attractor_weight"]  = float(self._pt_weight.Value) if pt_on else 0.0
        p["point_invert"]            = bool(self._pt_invert.Checked)
        p["point_search_radius"]     = float(self._pt_search_r.Value)
        p["point_density_radius"]    = float(self._pt_dens_r.Value)
        p["point_weight_default"]    = float(self._pt_wt_default.Value)
        return p

    def _on_simulate(self, sender, e):
        self._status.Text      = "Running simulation…"
        self._status.TextColor = edraw.Colors.DarkOrange
        # Push current display style into conduit before simulation starts
        self._conduit._style   = DISPLAY_STYLES[self._disp_style_dd.SelectedIndex]
        try:
            params = self._collect_params()
            result = run_simulation(params, self._conduit)
            if result["ok"]:
                self._last_nodes       = result.get("nodes", [])
                self._status.Text      = result["msg"]
                self._status.TextColor = edraw.Colors.DarkGreen
            else:
                self._status.Text      = result["msg"]
                self._status.TextColor = edraw.Colors.Red
        except Exception as ex:
            self._status.Text      = "Error: " + str(ex)
            self._status.TextColor = edraw.Colors.Red

    def _on_clear(self, sender, e):
        try:
            _clear_sca_layers()
            sc.doc.Views.Redraw()
            self._status.Text      = "Cleared SCA layers."
            self._status.TextColor = edraw.Colors.DarkSlateGray
        except Exception as ex:
            self._status.Text      = "Clear error: " + str(ex)
            self._status.TextColor = edraw.Colors.Red

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _ETO:
        print("Eto.Forms unavailable. Run inside Rhino 8 ScriptEditor.")
    else:
        try:
            _conduit = SCAConduit()
            _form    = SCADialogV3(_conduit)
            _form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
            _form.Show()
        except Exception as _ex:
            print("SCA V3 launch error:", _ex)
            print(traceback.format_exc())
