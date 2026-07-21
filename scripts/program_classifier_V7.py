# program_classifier_V7.py
# RMIT TECTONIC — GenLab Program Classifier  V7
#
# Zone-aware program classifier for makerspace / research building.
# Reads voxels from ticked layers → assigns programs by floor band + character.
# Run from Rhino 8 Script Editor.

import math, random, traceback
from collections import Counter, deque
from collections import OrderedDict

import Rhino, Rhino.DocObjects as rd, Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import System, System.Drawing as sd
import Eto.Drawing as edrawing, Eto.Forms as eforms

# ---------------------------------------------------------------------------
# Program definitions
# zone       : LOUD | SEMI | QUIET | SPECIAL
# band       : (floor_lo_pct, floor_hi_pct)  — fraction of total height
# default_pct: target % of total voxels
# color      : (R,G,B)
# desc       : short description shown in GUI
# ---------------------------------------------------------------------------

PROGRAM_DEFS = OrderedDict([
    # LOUD zone: Robotics_Lab (ground) → Digital_Fab → Makerspace (lower-mid).
    # SPECIAL: Atrium core anchored at geometric centre above LOUD top floor.
    # QUIET: Seminar / Quiet_Research / Classroom fill upper floors.
    ("Robotics_Lab",    dict(zone="LOUD",    band=(0.00,0.10), pct=20, color=(210, 50, 50),   desc="Heavy machinery, high noise — ground floor only")),
    ("Digital_Fab",     dict(zone="LOUD",    band=(0.12,0.32), pct=10, color=(200, 100, 40),  desc="CNC, laser, 3D printing — above Robotics Lab")),
    ("Social_Breakout", dict(zone="SPECIAL", band=(0.32,0.68), pct=30, color=(255, 205, 60),  desc="Central atrium hub — grows from geometric core above LOUD zone")),
    ("Seminar",         dict(zone="QUIET",   band=(0.48,0.80), pct=15, color=( 90, 175, 220), desc="Lectures, group presentations")),
    ("Quiet_Research",  dict(zone="QUIET",   band=(0.60,1.00), pct=15, color=(130, 195, 155), desc="Individual study, deep focus")),
    ("Classroom",       dict(zone="QUIET",   band=(0.42,0.78), pct=10, color=(175, 135, 210), desc="Structured teaching")),
])
# Default total = 100 %

# LOUD first → claims lower floors (Robotics_Lab + Digital_Fab + Makerspace).
# SPECIAL second → Atrium anchors at geometric core above LOUD top floor.
# QUIET fills upper floors last.  SEMI zone removed.
ZONE_ORDER    = ["LOUD", "SPECIAL", "QUIET"]
PARENT_LAYER  = "PROGRAM_CLASSIFIER"

def _sd(r, g, b): return sd.Color.FromArgb(r, g, b)

PROGRAM_LAYERS = {
    name: ("PROGRAM_CLASSIFIER::" + name, _sd(*d["color"]))
    for name, d in PROGRAM_DEFS.items()
}
PROGRAM_LAYERS["Unclassified"] = ("PROGRAM_CLASSIFIER::Unclassified",
                                   _sd(200, 200, 200))

# ---------------------------------------------------------------------------
# Cluster character options
# ---------------------------------------------------------------------------

CHARACTERS = ["Compact", "Stepped", "Elongated", "Fragmented", "Hollow"]

CHARACTER_DESC = {
    "Compact":    "Solid rounded mass — equal BFS expansion in all directions",
    "Stepped":    "Stepped pyramid — BFS prefers lower floors, narrows up",
    "Elongated":  "Linear bar/slab — BFS expands in dominant XY axis first",
    "Fragmented": "Scattered sub-clusters — many small seeds spread across zone",
    "Hollow":     "Shell/ring — BFS prefers high-exposure (perimeter) voxels",
}

ZONE_DEFAULT_CHAR = {
    "LOUD":    "Compact",
    "SEMI":    "Fragmented",
    "QUIET":   "Elongated",
    "SPECIAL": "Compact",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OFFSETS = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]

# 18-connectivity: face (6) + edge (12) neighbors — bridges diagonal adjacency
# that 6-connectivity misses, preventing false floor-gap splits.
_OFFSETS_18 = [(di, dj, dk)
               for di in (-1, 0, 1)
               for dj in (-1, 0, 1)
               for dk in (-1, 0, 1)
               if (di, dj, dk) != (0, 0, 0) and abs(di)+abs(dj)+abs(dk) <= 2]

class Voxel(object):
    __slots__ = ("brep_id","center","ijk","layer","size",
                 "program","tectonic_role","floor_index","ext_faces")
    def __init__(self, brep_id, center, ijk, layer, size):
        self.brep_id      = brep_id
        self.center       = center
        self.ijk          = ijk
        self.layer        = layer
        self.size         = size
        self.program      = "Unclassified"
        self.tectonic_role = "MID"
        self.floor_index  = ijk[2]
        self.ext_faces    = 0

def get_all_geometry_layers():
    result = []
    for layer in sc.doc.Layers:
        if layer.IsDeleted: continue
        lname = layer.FullPath
        if lname.startswith(PARENT_LAYER): continue
        objs = sc.doc.Objects.FindByLayer(layer)
        if objs and len(list(objs)) > 0:
            result.append(lname)
    return sorted(result)

def _angle_from_edge(dx, dy, dz, length):
    """Return normalised grid angle from a single horizontal edge, or None."""
    if length < 1e-6 or abs(dz) > length * 0.3:
        return None            # vertical / degenerate
    a = math.atan2(dy, dx) % (math.pi / 2)
    if a > math.pi / 4:
        a -= math.pi / 2
    return a


def _detect_grid_angle_from_geometry(obj_id):
    """Read horizontal edge direction from a single voxel's actual geometry.
    Works for Brep, Extrusion and Mesh."""
    obj = sc.doc.Objects.FindId(obj_id)
    if obj is None or obj.IsDeleted:
        return None
    geom = obj.Geometry
    if isinstance(geom, rg.Extrusion):
        geom = geom.ToBrep()
    if isinstance(geom, rg.Brep):
        horiz = []
        for edge in geom.Edges:
            sv, ev = edge.PointAtStart, edge.PointAtEnd
            dx, dy, dz = ev.X-sv.X, ev.Y-sv.Y, ev.Z-sv.Z
            a = _angle_from_edge(dx, dy, dz, math.sqrt(dx*dx+dy*dy+dz*dz))
            if a is not None:
                horiz.append(a)
        if horiz:
            return sum(horiz) / len(horiz)
    elif isinstance(geom, rg.Mesh):
        topo = geom.TopologyEdges
        for idx in range(min(topo.Count, 24)):
            line = topo.EdgeLine(idx)
            dx = line.To.X - line.From.X
            dy = line.To.Y - line.From.Y
            dz = line.To.Z - line.From.Z
            a = _angle_from_edge(dx, dy, dz, math.sqrt(dx*dx+dy*dy+dz*dz))
            if a is not None:
                return a
    return None


def _detect_grid_angle(candidates, vsize):
    """Detect the XY rotation of the voxel grid.
    Primary: reads horizontal edge directions from actual geometry (exact).
    Fallback: nearest-neighbour analysis on voxel centres (approximate)."""
    # 1) Geometry-based (reliable — reads the box's own edges)
    for brep_id, center, lname, _ in candidates[:15]:
        a = _detect_grid_angle_from_geometry(brep_id)
        if a is not None:
            return a
    # 2) Centre-based fallback
    centers = [c[1] for c in candidates]
    sample  = centers[:min(40, len(centers))]
    if len(sample) < 2:
        return 0.0
    angles = []
    for idx in range(min(15, len(sample))):
        p1 = sample[idx]
        best_d    = float('inf')
        best_pair = None
        for p2 in sample:
            if p2 is p1: continue
            dx = p2.X - p1.X; dy = p2.Y - p1.Y; dz = p2.Z - p1.Z
            if abs(dz) > vsize * 0.4: continue
            d_xy = math.sqrt(dx*dx + dy*dy)
            if abs(d_xy - vsize) < vsize * 0.3 and d_xy < best_d:
                best_d    = d_xy
                best_pair = (dx / d_xy, dy / d_xy)
        if best_pair:
            a = math.atan2(best_pair[1], best_pair[0]) % (math.pi / 2)
            if a > math.pi / 4: a -= math.pi / 2
            angles.append(a)
    return sum(angles) / len(angles) if angles else 0.0


def _min_grid_step(values, noise):
    """Return the minimum meaningful spacing in a sorted list of floats.
    Pairs closer than `noise` apart are treated as identical (floating-point
    duplicates) and ignored.  Returns None if fewer than 2 distinct values."""
    sv = sorted(values)
    steps = [sv[i+1] - sv[i] for i in range(len(sv)-1) if sv[i+1] - sv[i] > noise]
    return min(steps) if steps else None


def _build_index(candidates, vsize):
    """Detect grid angle, snap all candidates into the grid-aligned frame.
    Returns (index, angle_rad, angle_deg, dupes, piv_x, piv_y, rx_ref, ry_ref).

    Un-rotation formula (inverse of R(angle)):
        rx =  cos(a)*dx + sin(a)*dy
        ry = -sin(a)*dx + cos(a)*dy
    Pivot is the XY centroid of all candidates for numerical stability.

    rx_ref / ry_ref are the sub-voxel XY offsets (un-rotated frame) of the
    bottom-left voxel, used as anchors so snapping and baking are consistent.
    This prevents a systematic half-voxel shift when voxel centres sit at
    half-integer multiples of vsize (e.g. 0.5v, 1.5v, 2.5v …).

    Grid steps (xy_step, z_step) are measured from actual centre-to-centre
    distances rather than from bounding-box dimensions.  This is correct for
    any voxel shape (flat slabs, tall towers, rotated boxes, etc.) and avoids
    the duplicate-snapping collapse that occurs when sz ≠ XY grid spacing."""
    angle = _detect_grid_angle(candidates, vsize)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    # Centroid pivot — avoids large-coordinate precision loss
    n = len(candidates)
    piv_x = sum(c[1].X for c in candidates) / n
    piv_y = sum(c[1].Y for c in candidates) / n

    # Pre-compute all un-rotated positions to find grid anchors
    all_rx = []
    all_ry = []
    for _, center, _, _ in candidates:
        dx = center.X - piv_x
        dy = center.Y - piv_y
        all_rx.append( cos_a * dx + sin_a * dy)
        all_ry.append(-sin_a * dx + cos_a * dy)

    # XY anchors = minimum un-rotated X and Y.
    rx_ref = min(all_rx)
    ry_ref = min(all_ry)

    # Z anchor = minimum Z centre (k=0 at bottom floor)
    z_ref = min(c[1].Z for c in candidates)

    # Measure actual centre-to-centre grid steps.
    # Using 10 % of the bb-based vsize as a noise floor to skip fp duplicates.
    noise    = vsize * 0.1
    xy_step  = _min_grid_step(all_rx, noise) or _min_grid_step(all_ry, noise) or vsize
    z_values = [c[1].Z for c in candidates]
    z_step   = _min_grid_step(z_values, noise) or vsize

    index = {}
    dupes = 0
    for (brep_id, center, lname, _), rx, ry in zip(candidates, all_rx, all_ry):
        ijk = (int(round((rx - rx_ref) / xy_step)),
               int(round((ry - ry_ref) / xy_step)),
               int(round((center.Z  - z_ref)  / z_step)))
        if ijk in index:
            dupes += 1; continue
        index[ijk] = Voxel(brep_id, center, ijk, lname, xy_step)
    return index, angle, math.degrees(angle), dupes, piv_x, piv_y, rx_ref, ry_ref


def collect_voxels_from_ids(obj_ids, status_cb):
    """Collect voxels from a list of Rhino object GUIDs (any geometry type)."""
    candidates = []
    for guid in obj_ids:
        obj = sc.doc.Objects.FindId(guid)
        if obj is None or obj.IsDeleted: continue
        geom = obj.Geometry
        if geom is None: continue
        bb = geom.GetBoundingBox(True)
        if not bb.IsValid: continue
        sz = bb.Max.Z - bb.Min.Z   # Z-height only — rotation-independent
        if sz < 1e-6: continue
        lname = sc.doc.Layers[obj.Attributes.LayerIndex].FullPath
        candidates.append((obj.Id, bb.Center, lname, sz))

    if not candidates:
        return {}, 0.0, "No valid geometry in manual selection."

    sizes = sorted(c[3] for c in candidates)
    vsize = sizes[len(sizes) // 2]
    index, angle_rad, angle_deg, dupes, piv_x, piv_y, rx_ref, ry_ref = \
        _build_index(candidates, vsize)

    stats = "Loaded {} voxels from manual selection  (size={:.2f}m, grid angle={:.1f}deg)".format(
        len(index), vsize, angle_deg)
    if dupes: stats += "  [{} dupes skipped]".format(dupes)
    return index, vsize, stats, angle_rad, piv_x, piv_y, rx_ref, ry_ref


def collect_voxels(layer_names, status_cb):
    candidates  = []
    layer_counts = {}
    for lname in layer_names:
        lidx = sc.doc.Layers.FindByFullPath(lname, -1)
        if lidx < 0: continue
        objs = sc.doc.Objects.FindByLayer(sc.doc.Layers[lidx])
        if not objs: continue
        count = 0
        for obj in objs:
            if obj.IsDeleted: continue
            bb = obj.Geometry.GetBoundingBox(True)
            if not bb.IsValid: continue
            sz = bb.Max.Z - bb.Min.Z   # Z-height only — rotation-independent
            if sz < 1e-6: continue
            candidates.append((obj.Id, bb.Center, lname, sz))
            count += 1
        if count: layer_counts[lname] = count

    if not candidates:
        return {}, 0.0, "No geometry on selected layers."

    sizes = sorted(c[3] for c in candidates)
    vsize = sizes[len(sizes) // 2]
    index, angle_rad, angle_deg, dupes, piv_x, piv_y, rx_ref, ry_ref = \
        _build_index(candidates, vsize)

    stats = "Loaded {} voxels  (size={:.2f}m, grid angle={:.1f}deg)".format(
        len(index), vsize, angle_deg)
    if dupes: stats += "  [{} dupes skipped]".format(dupes)
    for ln, cnt in sorted(layer_counts.items()):
        stats += "\n  {} : {}".format(ln, cnt)
    return index, vsize, stats, angle_rad, piv_x, piv_y, rx_ref, ry_ref

# ---------------------------------------------------------------------------
# Connected-component detection
# ---------------------------------------------------------------------------

def find_connected_components(index):
    """BFS flood-fill over the voxel grid to find spatially disconnected groups.
    Uses 18-connectivity (face + edge neighbours) to bridge diagonal adjacency
    that pure 6-connectivity misses — prevents false floor-gap splits.
    Returns a list of sub-dicts (each is {ijk: Voxel}).
    Voxel objects are shared by reference so programme assignments made on a
    component are visible in the original index — safe to bake from index after."""
    unvisited  = set(index.keys())
    components = []
    while unvisited:
        start = next(iter(unvisited))
        comp  = {}
        queue = deque([start])
        while queue:
            ijk = queue.popleft()
            if ijk not in unvisited:
                continue
            unvisited.discard(ijk)
            comp[ijk] = index[ijk]
            i, j, k = ijk
            for di, dj, dk in _OFFSETS_18:
                nijk = (i+di, j+dj, k+dk)
                if nijk in unvisited:
                    queue.append(nijk)
        components.append(comp)
    return components

# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

class Classifier(object):

    def __init__(self, params):
        self.p = params

    # ── per-voxel prep ──────────────────────────────────────────────────────

    def prep(self, index):
        for ijk, v in index.items():
            i, j, k = ijk
            v.floor_index = k
            v.ext_faces   = sum(1 for di,dj,dk in _OFFSETS
                                if (i+di,j+dj,k+dk) not in index)

    # ── tectonic roles ──────────────────────────────────────────────────────

    def tectonic_roles(self, index):
        for ijk, v in index.items():
            i, j, k = ijk
            if k == 0:
                v.tectonic_role = "BASE"; continue
            below = index.get((i,j,k-1))
            above = index.get((i,j,k+1))
            same_prog_below = below is not None and below.program == v.program
            if not same_prog_below:
                v.tectonic_role = "CANTILEVER"
            elif above is None or above.program != v.program:
                v.tectonic_role = "CROWN"
            else:
                v.tectonic_role = "MID"

    # ── character-specific priority key for BFS ─────────────────────────────

    def _priority_key(self, ijk, character, min_k, max_k, min_i, max_i,
                      min_j, max_j, cent_i, cent_j, index):
        i, j, k = ijk
        v       = index.get(ijk)
        ext     = v.ext_faces if v else 0

        if character == "Stepped":
            # lower floors get grown first → pyramid profile
            return k

        elif character == "Elongated":
            # prefer XY spread: penalise vertical, reward horizontal distance
            dx = abs(i - cent_i); dy = abs(j - cent_j)
            return -(dx + dy) + k * 2

        elif character == "Hollow":
            # prefer perimeter / exposed voxels first
            return -ext

        else:   # Compact, Fragmented (many seeds handled separately)
            return 0   # FIFO — natural BFS sphere

    # ── zone-aware seeded growth ────────────────────────────────────────────

    def grow(self, index, status_cb):
        rng      = random.Random(self.p["rand_seed"] if self.p["rand_seed"] >= 0 else None)
        n_seeds  = self.p["n_seeds"]
        total    = len(index)
        max_k    = max(v.floor_index for v in index.values())
        pcts     = self.p["pcts"]          # {prog_name: float 0-1}
        chars    = self.p["characters"]    # {prog_name: str}

        # Compute target counts — scale to 100% of total
        pct_sum   = sum(pcts.values()) or 1.0
        targets   = {n: int(total * pcts[n] / pct_sum) for n in pcts}
        # fix rounding so sum == total
        diff = total - sum(targets.values())
        for n in list(targets.keys())[:abs(diff)]:
            targets[n] += 1 if diff > 0 else -1

        claimed   = {}   # ijk → program name
        remaining = set(index.keys())

        # Field-wide XY centroid — computed once from ALL voxels so it never
        # shifts as programs claim voxels.  Used to anchor the SPECIAL zone.
        _all_ijk  = list(index.keys())
        field_ci  = sum(ijk[0] for ijk in _all_ijk) / len(_all_ijk)
        field_cj  = sum(ijk[1] for ijk in _all_ijk) / len(_all_ijk)
        loud_top_k = 0   # updated after LOUD zone runs; SPECIAL anchors above it

        for zone in ZONE_ORDER:
            prog_names = [n for n,d in PROGRAM_DEFS.items() if d["zone"] == zone]
            if not prog_names: continue

            for prog in prog_names:
                if prog not in pcts: continue
                target  = targets[prog]
                if target <= 0: continue

                char    = chars.get(prog, "Compact")
                blo, bhi = PROGRAM_DEFS[prog]["band"]
                klo     = int(math.floor(blo * max_k))
                khi     = int(math.ceil(bhi  * max_k))

                # Eligible unclaimed voxels in floor band
                eligible = [ijk for ijk in remaining
                            if klo <= ijk[2] <= khi]
                if not eligible:
                    # Widen band by up to 3 floors but never escape zone's floor range
                    klo_w = max(0,      klo - 3)
                    khi_w = min(max_k,  khi + 3)
                    eligible = [ijk for ijk in remaining
                                if klo_w <= ijk[2] <= khi_w]
                if not eligible:
                    continue  # no voxels in this zone's band — skip; flood fill handles gaps

                # Seed count
                if char == "Fragmented":
                    n_s = max(4, int(n_seeds * 2))
                elif zone == "SPECIAL":
                    # V5: anchor atrium at entire-field XY centroid, one floor
                    # above the highest LOUD-claimed floor.  This guarantees the
                    # atrium lands in the true geometric core of the mass at all
                    # times, surrounded by SEMI and QUIET programs.
                    # Manual Settings atrium_i/j still override when non-zero.
                    ai_set = self.p["atrium_i"]
                    aj_set = self.p["atrium_j"]
                    ai = ai_set if (ai_set != 0 or aj_set != 0) else field_ci
                    aj = aj_set if (ai_set != 0 or aj_set != 0) else field_cj
                    ak = loud_top_k + 1   # one floor above LOUD zone top

                    # Sort eligible: interior voxels near anchor axis first.
                    # XY dist to anchor + penalty for exposed faces keeps seeds
                    # deep inside the mass, away from the outer skin.
                    eligible.sort(key=lambda ijk: (
                        math.sqrt((ijk[0]-ai)**2 + (ijk[1]-aj)**2)
                        + (index[ijk].ext_faces if ijk in index else 6) * 1.5
                    ))
                    n_s = max(1, n_seeds // 4)
                    status_cb("  [Atrium anchor] ({:.1f},{:.1f},k={}) — {} eligible"
                              .format(ai, aj, ak, len(eligible)))
                else:
                    n_s = max(1, int(n_seeds * pcts[prog] / pct_sum))

                # Place seeds — Atrium picks from the innermost voxels only
                if zone == "SPECIAL":
                    seed_pool = eligible[:max(n_s * 2, 10)]
                else:
                    seed_pool = eligible
                n_s = min(n_s, len(seed_pool))
                seeds = rng.sample(seed_pool, n_s)

                # Compute centroid for elongated/hollow characters
                cent_i = sum(ijk[0] for ijk in eligible) / max(len(eligible),1)
                cent_j = sum(ijk[1] for ijk in eligible) / max(len(eligible),1)
                min_i  = min(ijk[0] for ijk in eligible)
                max_i  = max(ijk[0] for ijk in eligible)
                min_j  = min(ijk[1] for ijk in eligible)
                max_j  = max(ijk[1] for ijk in eligible)

                # Per-seed cap for Fragmented
                per_seed_cap = (int(target / n_s) + 2) if char == "Fragmented" else target

                grown_total = 0

                for seed_ijk in seeds:
                    if grown_total >= target: break
                    if seed_ijk not in remaining: continue

                    # BFS with character priority
                    # Using list as priority queue (small enough for typical fields)
                    queue    = [(self._priority_key(seed_ijk, char, klo, khi,
                                                    min_i, max_i, min_j, max_j,
                                                    cent_i, cent_j, index),
                                 seed_ijk)]
                    visited  = set()
                    grown    = 0

                    while queue and grown < per_seed_cap and grown_total < target:
                        queue.sort(key=lambda x: x[0])
                        _, cur = queue.pop(0)
                        if cur in visited or cur not in remaining:
                            continue
                        visited.add(cur)
                        claimed[cur] = prog
                        remaining.discard(cur)
                        grown       += 1
                        grown_total += 1

                        ci, cj, ck = cur
                        # BFS expansion hard-capped to this program's floor band
                        # (±3 floor tolerance for natural transitions).
                        # This prevents upper-zone programs crawling down to
                        # ground floor even when low-floor voxels are unclaimed.
                        bfs_klo = max(0,      klo - 3)
                        bfs_khi = min(max_k,  khi + 3)
                        for di, dj, dk in _OFFSETS:
                            nijk = (ci+di, cj+dj, ck+dk)
                            if (nijk in remaining and nijk not in visited
                                    and bfs_klo <= nijk[2] <= bfs_khi):
                                if zone == "SPECIAL":
                                    # Core interior growth:
                                    # Priority = XY distance to anchor axis
                                    #          + strong penalty for exposed faces.
                                    # This keeps the atrium as an interior core
                                    # blob, never touching the outer skin.
                                    ni, nj, nk = nijk
                                    nv  = index.get(nijk)
                                    ext = nv.ext_faces if nv else 6
                                    xy_dist = math.sqrt((ni-ai)**2 + (nj-aj)**2)
                                    pk = xy_dist + ext * 1.5
                                else:
                                    pk = self._priority_key(nijk, char, klo, khi,
                                                            min_i, max_i, min_j,
                                                            max_j, cent_i, cent_j,
                                                            index)
                                queue.append((pk, nijk))

                status_cb("  {} : {} voxels  ({})".format(prog, grown_total, char))

            # After all LOUD programs finish, record the highest claimed LOUD floor.
            # SPECIAL zone will anchor its seed one floor above this.
            if zone == "LOUD":
                loud_claimed = [ijk[2] for ijk, p in claimed.items()
                                if PROGRAM_DEFS.get(p, {}).get("zone") == "LOUD"]
                loud_top_k = max(loud_claimed) if loud_claimed else 0
                status_cb("  [Atrium anchor] loud_top_k={} → atrium starts k={}".format(
                    loud_top_k, loud_top_k + 1))

        # Assign claimed programs
        for ijk, prog in claimed.items():
            if ijk in index:
                index[ijk].program = prog

        # Precompute hard floor limits per program (band * max_k, with ±2 tolerance)
        FLOOR_BAND_TOLERANCE = 2
        prog_klo = {}
        prog_khi = {}
        for pname, pdef in PROGRAM_DEFS.items():
            blo, bhi = pdef["band"]
            prog_klo[pname] = max(0,      int(math.floor(blo * max_k)) - FLOOR_BAND_TOLERANCE)
            prog_khi[pname] = min(max_k,  int(math.ceil (bhi * max_k)) + FLOOR_BAND_TOLERANCE)

        # Fill unclaimed voxels → nearest claimed neighbour (band-aware flood fill)
        # A program only propagates into a neighbour whose floor is within that
        # program's band (± tolerance).  This prevents upper-zone programs
        # (e.g. Classroom) from bleeding down to the ground floor.
        if remaining:
            status_cb("  Filling {} unclaimed voxels...".format(len(remaining)))
            fill_queue = deque()
            for ijk in list(index.keys()):
                if ijk not in remaining:
                    i,j,k = ijk
                    for di,dj,dk in _OFFSETS:
                        nijk = (i+di,j+dj,k+dk)
                        if nijk in remaining:
                            fill_queue.append((nijk, index[ijk].program))
            while fill_queue:
                ijk, prog = fill_queue.popleft()
                if ijk not in remaining: continue
                nk = ijk[2]
                # Reject if this floor is outside the program's allowed band
                if prog in prog_klo and not (prog_klo[prog] <= nk <= prog_khi[prog]):
                    continue
                remaining.discard(ijk)
                index[ijk].program = prog
                i,j,k = ijk
                for di,dj,dk in _OFFSETS:
                    nijk = (i+di,j+dj,k+dk)
                    if nijk in remaining:
                        fill_queue.append((nijk, prog))

        # Any voxels still unclaimed (blocked by all band constraints) →
        # assign to the program whose band midpoint is closest to this floor.
        # Never force Robotics_Lab (red) onto upper floors.
        if remaining:
            for ijk in list(remaining):
                k = ijk[2]
                # First try: any program whose band strictly covers this floor
                assigned = None
                for pname, pdef in PROGRAM_DEFS.items():
                    blo, bhi = pdef["band"]
                    if int(math.floor(blo*max_k)) <= k <= int(math.ceil(bhi*max_k)):
                        assigned = pname; break
                if assigned is None:
                    # Nearest-band fallback: pick program with closest band midpoint
                    assigned = min(
                        PROGRAM_DEFS.items(),
                        key=lambda kv: abs(
                            ((kv[1]["band"][0]+kv[1]["band"][1])/2)*max_k - k
                        )
                    )[0]
                remaining.discard(ijk)
                index[ijk].program = assigned

    # ── bake ────────────────────────────────────────────────────────────────

    def bake(self, index, vsize):
        # Ensure all program layers exist
        if not rs.IsLayer(PARENT_LAYER):
            rs.AddLayer(PARENT_LAYER, sd.Color.FromArgb(180,180,180))
        for key, (lname, color) in PROGRAM_LAYERS.items():
            if not rs.IsLayer(lname):
                rs.AddLayer(lname, color)

        counts = Counter()

        mp = rg.MeshingParameters.FastRenderMesh

        # Convert each source voxel to a mesh and bake on its program layer.
        # Original source object is deleted so output count == input count.
        for v in index.values():
            prog            = v.program
            lname, lcolor   = PROGRAM_LAYERS.get(prog, PROGRAM_LAYERS["Unclassified"])
            lidx            = sc.doc.Layers.FindByFullPath(lname, -1)
            if lidx < 0: continue

            obj = sc.doc.Objects.FindId(v.brep_id)
            if obj is None or obj.IsDeleted: continue

            # Convert source geometry → mesh (handles Brep, Extrusion, Mesh)
            geom = obj.Geometry
            mesh = rg.Mesh()
            if isinstance(geom, rg.Mesh):
                mesh = geom.DuplicateMesh()
            else:
                if isinstance(geom, rg.Extrusion):
                    geom = geom.ToBrep()
                if isinstance(geom, rg.Brep):
                    parts = rg.Mesh.CreateFromBrep(geom, mp)
                    if parts:
                        for part in parts:
                            mesh.Append(part)
            if mesh is None or mesh.Faces.Count == 0:
                continue

            attrs = rd.ObjectAttributes()
            attrs.LayerIndex  = lidx
            attrs.ColorSource = rd.ObjectColorSource.ColorFromLayer
            if v.tectonic_role == "CANTILEVER":
                attrs.ColorSource = rd.ObjectColorSource.ColorFromObject
                attrs.ObjectColor = sd.Color.FromArgb(
                    max(0, lcolor.R - 50),
                    max(0, lcolor.G - 50),
                    max(0, lcolor.B - 50))

            sc.doc.Objects.AddMesh(mesh, attrs)
            sc.doc.Objects.Delete(obj, True)   # remove original
            counts[prog] += 1
        return counts

    # ── classify one connected component (no bake) ───────────────────────────

    def _classify_component(self, comp, comp_label, status_cb, global_max_k=None):
        """Prep + grow + tectonic roles for one connected voxel group.
        global_max_k: when set, all components share the same floor band scale
        so a mid-building slab is treated as mid-building, not as a ground floor.
        Modifies Voxel.program in-place (shared references with parent index)."""
        try:
            self.prep(comp)
            if not comp:
                return
            comp_max_k = max(v.floor_index for v in comp.values())
            # Use global scale if provided — ensures consistent zone stacking
            # across disconnected slabs (e.g. a 3-group building).
            max_k = global_max_k if global_max_k is not None else comp_max_k
            self.p["max_floor"] = max_k
            status_cb("  floors k={}..{}  (global scale k=0..{})".format(
                min(v.floor_index for v in comp.values()), comp_max_k, max_k))

            pcts  = self.p["pcts"]
            total = len(comp)
            pct_sum = max(sum(pcts.values()), 1e-9)
            status_cb("  Target allocations ({} voxels):".format(total))
            for name, pct in pcts.items():
                status_cb("    {:20s} {:5.1f}%  ~{}".format(
                    name, pct * 100, int(total * pct / pct_sum)))

            status_cb("  Growing program zones...")
            self.grow(comp, status_cb)

            status_cb("  Assigning tectonic roles...")
            self.tectonic_roles(comp)

            prog_counts = Counter(v.program for v in comp.values())
            status_cb("  Distribution:")
            for prog, cnt in sorted(prog_counts.items(), key=lambda x: -x[1]):
                status_cb("    {:20s} {:4d} ({:.1f}%)".format(
                    prog, cnt, 100 * cnt / max(total, 1)))
        except Exception as ex:
            status_cb("  ERROR in {}: {}".format(comp_label, ex))
            status_cb(traceback.format_exc())

    # ── full run ─────────────────────────────────────────────────────────────

    def run(self, layer_names, status_cb, manual_ids=None):
        status_cb("Collecting voxels...")
        if manual_ids:
            index, vsize, stats, grid_angle, piv_x, piv_y, rx_ref, ry_ref = \
                collect_voxels_from_ids(manual_ids, status_cb)
        else:
            index, vsize, stats, grid_angle, piv_x, piv_y, rx_ref, ry_ref = \
                collect_voxels(layer_names, status_cb)
        if not index: return stats
        status_cb(stats)
        self._grid_angle  = grid_angle
        self._grid_pivot  = (piv_x, piv_y)
        self._grid_xy_ref = (rx_ref, ry_ref)   # sub-voxel XY anchors for bake
        self._vsize       = vsize

        # ── auto-detect spatially disconnected groups ────────────────────────
        components = find_connected_components(index)

        # Fix 2: discard stray micro-components (grid-snap outliers).
        # Keep only groups with at least N_MIN voxels.
        N_MIN = 4
        before = len(components)
        components = [c for c in components if len(c) >= N_MIN]
        discarded = before - len(components)
        if discarded:
            # Remove orphaned voxels from the main index so they aren't baked.
            valid_ijks = set()
            for c in components:
                valid_ijks.update(c.keys())
            index = {k: v for k, v in index.items() if k in valid_ijks}
            status_cb("Discarded {} micro-component(s) < {} voxels "
                      "(stray grid-snap outliers).".format(discarded, N_MIN))

        n = len(components)

        # Global max_k — shared across all components so every slab uses the
        # same floor band scale.  A mid-building slab stays mid-building.
        global_max_k = max(v.floor_index for v in index.values())

        if n > 1:
            status_cb("Auto-detected {} separate voxel groups — "
                      "shared floor scale k=0..{}".format(n, global_max_k))
            components.sort(key=lambda c: -len(c))
        else:
            status_cb("Single voxel group (k=0..{}).".format(global_max_k))

        for ci, comp in enumerate(components):
            label = "Group {}/{}".format(ci + 1, n)
            if n > 1:
                status_cb("=== {} ({} voxels) ===".format(label, len(comp)))
            self._classify_component(comp, label, status_cb,
                                     global_max_k=global_max_k)

        # ── bake all voxels from the full index (programs assigned above) ────
        status_cb("Baking geometry ({} voxels total)...".format(len(index)))
        rs.EnableRedraw(False)
        uid = sc.doc.BeginUndoRecord("ProgramClassifier_V2")
        try:
            counts = self.bake(index, vsize)
        finally:
            sc.doc.EndUndoRecord(uid)
            rs.EnableRedraw(True)
            sc.doc.Views.Redraw()

        suffix = " across {} groups".format(n) if n > 1 else ""
        return "Done — {} voxels classified{}".format(sum(counts.values()), suffix)

# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class ProgramClassifierForm(eforms.Form):

    def __init__(self):
        super().__init__()
        self.Title       = "Program Classifier  V7"
        self.Resizable   = True
        self.MinimumSize = edrawing.Size(460, 780)
        self.Padding     = edrawing.Padding(10)
        self._layer_checks   = []
        self._pct_steppers   = {}    # prog_name → NumericStepper
        self._char_dropdowns = {}    # prog_name → DropDown
        self._live_update    = False
        self._manual_ids     = []    # GUIDs from manual object selection
        self._build_ui()

    # ── widget helpers ──────────────────────────────────────────────────────

    def _lbl(self, text, bold=False, w=None, color=None):
        lb = eforms.Label(); lb.Text = text
        if bold:
            lb.Font = edrawing.Font(lb.Font.Family, lb.Font.Size,
                                    edrawing.FontStyle.Bold)
        if w:    lb.Width = w
        if color: lb.TextColor = color
        lb.VerticalAlignment = eforms.VerticalAlignment.Center
        return lb

    def _num(self, val, lo, hi, dec=0, inc=1, w=70):
        ns = eforms.NumericStepper()
        ns.Value=val; ns.MinValue=lo; ns.MaxValue=hi
        ns.DecimalPlaces=dec; ns.Increment=inc; ns.Width=w
        return ns

    def _dropdown(self, items, sel=0, w=130):
        dd = eforms.DropDown(); dd.Width = w
        for it in items:
            li = eforms.ListItem(); li.Text = it; dd.Items.Add(li)
        dd.SelectedIndex = min(sel, len(items)-1)
        return dd

    def _row(self, *cells, **kw):
        tl = eforms.TableLayout()
        tl.Spacing = edrawing.Size(kw.get("sp",6), 0)
        row = eforms.TableRow()
        for c in cells:
            row.Cells.Add(eforms.TableCell(c))
        tl.Rows.Add(row)
        return tl

    def _sep(self, h=5):
        lb = eforms.Label(); lb.Height = h; return lb

    # ── build UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._tabs = eforms.TabControl()

        self._tabs.Pages.Add(self._build_programs_tab())
        self._tabs.Pages.Add(self._build_layers_tab())
        self._tabs.Pages.Add(self._build_settings_tab())

        # Bottom buttons
        btn_layout = eforms.TableLayout()
        btn_layout.Spacing = edrawing.Size(6,0)
        btn_layout.Padding = edrawing.Padding(0,8,0,0)

        self._btn_rand = eforms.Button()
        self._btn_rand.Text  = "Randomize Seed"
        self._btn_rand.Click += self._on_randomize

        self._chk_live = eforms.CheckBox()
        self._chk_live.Text    = "Live Update"
        self._chk_live.Checked = False
        self._chk_live.CheckedChanged += self._on_live_toggle

        self._btn_run = eforms.Button()
        self._btn_run.Text   = "Run Classifier"
        self._btn_run.Height = 30
        self._btn_run.Click += self._on_run

        row = eforms.TableRow()
        row.Cells.Add(eforms.TableCell(self._btn_rand))
        row.Cells.Add(eforms.TableCell(self._chk_live))
        row.Cells.Add(eforms.TableCell(eforms.Label()))  # spacer
        row.Cells.Add(eforms.TableCell(self._btn_run))
        btn_layout.Rows.Add(row)

        self._log = eforms.TextArea()
        self._log.ReadOnly = True; self._log.Height = 160
        self._log.Font = edrawing.Font(edrawing.FontFamilies.Monospace, 8.5)

        outer = eforms.TableLayout()
        outer.Spacing = edrawing.Size(0,4)
        def R(c,s=False): outer.Rows.Add(eforms.TableRow(eforms.TableCell(c,s)))
        R(self._tabs, True)
        R(btn_layout)
        R(self._log)
        self.Content = outer

        self._populate_layers()

    # ── Programs tab ────────────────────────────────────────────────────────

    def _build_programs_tab(self):
        page = eforms.TabPage(); page.Text = "Programs"
        layout = eforms.TableLayout()
        layout.Spacing = edrawing.Size(0,4)
        layout.Padding = edrawing.Padding(8)

        def R(c): layout.Rows.Add(eforms.TableRow(eforms.TableCell(c)))

        ZONE_COLORS_UI = {
            "LOUD":    edrawing.Color.FromArgb(220, 80,  80),
            "SEMI":    edrawing.Color.FromArgb(210,150,  30),
            "QUIET":   edrawing.Color.FromArgb( 70,150, 200),
            "SPECIAL": edrawing.Color.FromArgb(200,170,  20),
        }
        ZONE_NAMES = {
            "LOUD":    "Loud Zone  (Robotics Lab + Digital Fab + Makerspace)",
            "SEMI":    "Semi-loud Zone  (unused)",
            "QUIET":   "Quiet Zone  (mid-upper)",
            "SPECIAL": "Atrium Zone  (central core, above LOUD zone)",
        }

        shown_zones = []
        for prog_name, d in PROGRAM_DEFS.items():
            zone = d["zone"]
            if zone not in shown_zones:
                shown_zones.append(zone)
                zcol = ZONE_COLORS_UI.get(zone, edrawing.Colors.Gray)
                R(self._lbl(ZONE_NAMES[zone], bold=True, color=zcol))

            # Row: color swatch | name | desc | % stepper | character dropdown
            swatch = eforms.Label()
            r,g,b  = d["color"]
            swatch.BackgroundColor = edrawing.Color.FromArgb(r,g,b)
            swatch.Width = 14; swatch.Height = 14

            ns = self._num(d["pct"], 0, 100, inc=1)
            ns.Tag = prog_name
            ns.ValueChanged += self._on_pct_changed
            self._pct_steppers[prog_name] = ns

            dd = self._dropdown(CHARACTERS,
                                sel=CHARACTERS.index(ZONE_DEFAULT_CHAR.get(d["zone"],"Compact")))
            dd.Tag = prog_name
            dd.SelectedIndexChanged += self._on_char_changed
            self._char_dropdowns[prog_name] = dd

            name_lbl = self._lbl(prog_name.replace("_"," "), w=110)
            desc_lbl = self._lbl(d["desc"], w=165)
            desc_lbl.Font = edrawing.Font(desc_lbl.Font.Family, 7.5)
            desc_lbl.TextColor = edrawing.Colors.Gray

            row_tl = eforms.TableLayout()
            row_tl.Spacing = edrawing.Size(5,0)
            tr = eforms.TableRow()
            for cell in [swatch, name_lbl, desc_lbl,
                         self._lbl("%",w=10), ns, dd]:
                tr.Cells.Add(eforms.TableCell(cell))
            row_tl.Rows.Add(tr)
            R(row_tl)

        R(self._sep(4))

        # Total %
        self._total_lbl = self._lbl("Total: 100%", bold=True)
        R(self._total_lbl)

        R(self._sep(4))

        # Character descriptions
        R(self._lbl("Cluster Characters:", bold=True))
        for ch, desc in CHARACTER_DESC.items():
            R(self._lbl("  {}  —  {}".format(ch, desc)))

        scroll = eforms.Scrollable(); scroll.Content = layout
        page.Content = scroll
        return page

    # ── Layers tab ──────────────────────────────────────────────────────────

    def _build_layers_tab(self):
        page = eforms.TabPage(); page.Text = "Layers"
        layout = eforms.TableLayout()
        layout.Spacing = edrawing.Size(0,5)
        layout.Padding = edrawing.Padding(8)
        def R(c,s=False): layout.Rows.Add(eforms.TableRow(eforms.TableCell(c,s)))

        R(self._lbl("Tick layers that contain voxels:", bold=True))

        self._btn_refresh = eforms.Button()
        self._btn_refresh.Text = "Refresh layer list"
        self._btn_refresh.Click += lambda s,e: (self._populate_layers(),
                                                 self._log_msg("Layers refreshed."))
        R(self._btn_refresh)

        # Layer checkbox list in a fixed-height scrollable.
        # Fixed height forces the scrollbar to appear when there are many layers.
        self._layer_panel = eforms.StackLayout()
        self._layer_panel.Spacing = 3
        layer_scroll = eforms.Scrollable()
        layer_scroll.Content = self._layer_panel
        layer_scroll.Height = 250
        R(layer_scroll)                 # fixed height — scrollbar appears as needed

        R(self._sep(6))
        R(self._lbl("── Manual Selection ──────────────────", bold=True))
        R(self._lbl("Pick any geometry directly in the viewport.", color=edrawing.Colors.Gray))
        R(self._lbl("Manual selection overrides layer ticks when objects are selected.", color=edrawing.Colors.Gray))

        self._sel_label = self._lbl("No objects selected")

        btn_sel = eforms.Button(); btn_sel.Text = "Select Objects in Viewport"
        btn_sel.Click += self._on_select_objects

        btn_clr = eforms.Button(); btn_clr.Text = "Clear"
        btn_clr.Click += self._on_clear_selection

        R(self._row(btn_sel, btn_clr, self._sel_label, sp=6))

        page.Content = layout
        return page

    # ── Settings tab ────────────────────────────────────────────────────────

    def _build_settings_tab(self):
        page = eforms.TabPage(); page.Text = "Settings"
        layout = eforms.TableLayout()
        layout.Spacing = edrawing.Size(0,5)
        layout.Padding = edrawing.Padding(8)
        def R(c): layout.Rows.Add(eforms.TableRow(eforms.TableCell(c)))

        R(self._lbl("Clustering", bold=True))
        self._n_seeds = self._num(10, 2, 80)
        R(self._row(self._lbl("Seeds per zone", w=200), self._n_seeds))

        self._floor_bias = self._num(0.7, 0.0, 1.0, dec=2, inc=0.05)
        R(self._row(self._lbl("Floor bias (0=uniform 1=ground)", w=200), self._floor_bias))

        self._rand_seed = self._num(42, -1, 9999)
        R(self._row(self._lbl("Random seed  (-1=random)", w=200), self._rand_seed))

        R(self._sep())
        R(self._lbl("Atrium Centre override  (0,0 = auto-centre)", bold=True))

        self._atrium_i = self._num(0, 0, 9999)
        R(self._row(self._lbl("Atrium Centre  i  (grid)", w=200), self._atrium_i))

        self._atrium_j = self._num(0, 0, 9999)
        R(self._row(self._lbl("Atrium Centre  j  (grid)", w=200), self._atrium_j))

        R(self._sep())
        R(self._lbl("Bake Display", bold=True))
        self._gap_pct = self._num(1.0, 0.0, 49.0, dec=1, inc=0.5, w=70)
        R(self._row(
            self._lbl("Gap between voxels (%)", w=200),
            self._gap_pct,
            self._lbl("  0=flush  1=default  10=wide", color=edrawing.Colors.Gray)
        ))

        R(self._sep())
        self._clear_prev = eforms.CheckBox()
        self._clear_prev.Text = "Clear PROGRAM_CLASSIFIER before run"
        self._clear_prev.Checked = True
        R(self._clear_prev)

        page.Content = layout
        return page

    # ── layer list ──────────────────────────────────────────────────────────

    def _populate_layers(self):
        self._layer_checks = []
        self._layer_panel.Items.Clear()
        layers = get_all_geometry_layers()
        if not layers:
            self._layer_panel.Items.Add(
                eforms.StackLayoutItem(self._lbl("(no geometry layers found)")))
            return
        for lname in layers:
            cb = eforms.CheckBox(); cb.Text = lname
            lower = lname.lower()
            cb.Checked = any(kw in lower for kw in
                             ("voxel","field","room","positive","negative","human"))
            self._layer_checks.append((cb, lname))
            self._layer_panel.Items.Add(eforms.StackLayoutItem(cb))

    # ── events ──────────────────────────────────────────────────────────────

    def _update_total(self):
        total = sum(int(ns.Value) for ns in self._pct_steppers.values())
        color = edrawing.Colors.Red if total != 100 else edrawing.Colors.Black
        self._total_lbl.Text      = "Total: {}%{}".format(
            total, "" if total == 100 else "  ← adjust to reach 100%")
        self._total_lbl.TextColor = color

    def _on_pct_changed(self, s, e):
        self._update_total()
        if self._live_update:
            self._on_run(None, None)

    def _on_char_changed(self, s, e):
        if self._live_update:
            self._on_run(None, None)

    def _on_live_toggle(self, s, e):
        self._live_update = bool(self._chk_live.Checked)

    def _on_randomize(self, s, e):
        new_seed = random.randint(0, 9999)
        self._rand_seed.Value = new_seed
        self._log_msg("Seed → {}".format(new_seed))
        if self._live_update:
            self._on_run(None, None)

    def _on_select_objects(self, s, e):
        self.Visible = False
        try:
            objs = rs.GetObjects("Select voxel geometry (any type)", preselect=True)
        except Exception:
            objs = None
        finally:
            self.Visible = True
        if objs:
            self._manual_ids = list(objs)
            self._sel_label.Text = "{} objects selected".format(len(self._manual_ids))
            self._log_msg("Manual selection: {} objects".format(len(self._manual_ids)))
        else:
            self._log_msg("Selection cancelled.")

    def _on_clear_selection(self, s, e):
        self._manual_ids = []
        self._sel_label.Text = "No objects selected"
        self._log_msg("Manual selection cleared — using layer ticks.")

    def _log_msg(self, msg):
        current = self._log.Text or ""
        lines   = (current + msg + "\n").split("\n")
        self._log.Text = "\n".join(lines[-150:])

    def _on_run(self, s, e):
        selected = [lname for cb,lname in self._layer_checks if cb.Checked]
        use_manual = bool(self._manual_ids)
        if not use_manual and not selected:
            self._log_msg("No layers ticked and no manual selection."); return

        if self._clear_prev.Checked:
            for _,(lname,_) in PROGRAM_LAYERS.items():
                if rs.IsLayer(lname):
                    objs = rs.ObjectsByLayer(lname)
                    if objs: rs.DeleteObjects(objs)

        pcts = {}
        for name, ns in self._pct_steppers.items():
            pcts[name] = float(ns.Value) / 100.0

        chars = {}
        for name, dd in self._char_dropdowns.items():
            idx = dd.SelectedIndex
            chars[name] = CHARACTERS[idx] if 0 <= idx < len(CHARACTERS) else "Compact"

        params = {
            "n_seeds":   int(self._n_seeds.Value),
            "floor_bias":float(self._floor_bias.Value),
            "rand_seed": int(self._rand_seed.Value),
            "atrium_i":  float(self._atrium_i.Value),
            "atrium_j":  float(self._atrium_j.Value),
            "gap_pct":   float(self._gap_pct.Value),
            "pcts":      pcts,
            "characters":chars,
            "max_floor": 9,
        }

        if use_manual:
            self._log_msg("Source: manual selection ({} objects)".format(len(self._manual_ids)))
        else:
            self._log_msg("Source: {} ticked layer(s)".format(len(selected)))

        self._btn_run.Enabled = False
        self._log_msg("=" * 36)
        try:
            c      = Classifier(params)
            result = c.run(selected, self._log_msg,
                           manual_ids=self._manual_ids if use_manual else None)
            self._log_msg(result)
        except Exception as ex:
            self._log_msg("ERROR: " + str(ex))
            self._log_msg(traceback.format_exc())
        finally:
            self._btn_run.Enabled = True

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    form = ProgramClassifierForm()
    form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    form.Show()

main()
