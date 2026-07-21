
#! python 2
"""
Melbourne Climate Voxel Attractor — V7
=======================================
Changes from V5/V6:
  - Solar fix:    sun_vec points TOWARD sun (no negation).
                  North-facing + top = red/hot, correct for Melbourne.
  - heat_idx:     solar exposure score stored at voxel position 3.
                  Perlin noise still culls WHERE voxels appear;
                  heat_idx drives color + zone scoring.
  - Auto-fit:     default mode — voxel size computed from bbox / cell count.
  - Thick toggle: checkbox reveals manual mm inputs (V5 style).
  - Non-modal:    forms.Form base — viewport stays interactive while open.
  - Inline pick:  Hide → GetObject → Show (no dialog recreate / _copy_state_from).
  - No nav btns:  removed ◀▶▲▼ Top/Front/ISO/Frame buttons.
  - Scroll fix:   no AddRow(None), ExpandContentHeight = False.
  - Simulation:   tries seed + threshold combos to maximise climate score.
"""

import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import System
import System.Drawing as sd
import math
import random
import os

import Eto
import Eto.Drawing as drawing
import Eto.Forms as forms


# =========================================================================
#  SOLAR POSITION  (Melbourne  lat=-37.8136°)
# =========================================================================
MEL_LAT_DEG = -37.8136
_MONTH_DOY  = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]

def solar_position(month_idx, hour_float):
    """Return (azimuth_deg, altitude_deg) for Melbourne at given month/hour.
    month_idx 0 = Annual avg (uses June solstice reference).
    Returns altitude < 0 when sun is below horizon.
    """
    lat = math.radians(MEL_LAT_DEG)
    doy = 172 if month_idx == 0 else _MONTH_DOY[month_idx - 1]
    decl = math.radians(23.45 * math.sin(math.radians(360.0 / 365.0 * (doy - 81))))
    hour_angle = math.radians((hour_float - 12.0) * 15.0)
    sin_alt = (math.sin(lat) * math.sin(decl) +
               math.cos(lat) * math.cos(decl) * math.cos(hour_angle))
    altitude = math.asin(max(-1.0, min(1.0, sin_alt)))
    cos_az = ((math.sin(decl) - math.sin(lat) * math.sin(altitude)) /
              (math.cos(lat) * math.cos(altitude) + 1e-9))
    azimuth = math.acos(max(-1.0, min(1.0, cos_az)))
    if hour_angle > 0:
        azimuth = 2.0 * math.pi - azimuth
    return math.degrees(azimuth), math.degrees(altitude)


def sun_vec_from_angles(azimuth_deg, altitude_deg):
    """Unit vector pointing TOWARD the sun (scene → sun).

    Rhino world: +X = East, +Y = North, +Z = Up.
    Dot product with this vector: +1 = fully sun-facing surface,
    -1 = fully shaded.  In Melbourne (lat -37.8°) the sun always
    sits in the northern sky → north-facing surfaces score high →
    density_color maps them red/hot.  Correct.
    """
    az  = math.radians(azimuth_deg)
    alt = math.radians(altitude_deg)
    sx = math.sin(az) * math.cos(alt)   # East
    sy = math.cos(az) * math.cos(alt)   # North
    sz = math.sin(alt)                   # Up
    v  = rg.Vector3d(sx, sy, sz)         # toward sun — NO negation
    v.Unitize()
    return v


# =========================================================================
#  3-D PERLIN NOISE
# =========================================================================
class PerlinNoise(object):
    def __init__(self, seed=42):
        random.seed(seed)
        self.p = list(range(256))
        random.shuffle(self.p)
        self.p *= 2

    def noise3d(self, x, y, z):
        p = self.p
        xi = int(math.floor(x)); yi = int(math.floor(y)); zi = int(math.floor(z))
        X = xi & 255; Y = yi & 255; Z = zi & 255
        x -= xi; y -= yi; z -= zi
        u = x*x*x*(x*(x*6.0-15.0)+10.0)
        v = y*y*y*(y*(y*6.0-15.0)+10.0)
        w = z*z*z*(z*(z*6.0-15.0)+10.0)
        A  = p[X]+Y;   AA = p[A]+Z;   AB = p[A+1]+Z
        B  = p[X+1]+Y; BA = p[B]+Z;   BB = p[B+1]+Z
        x1 = x-1.0; y1 = y-1.0; z1 = z-1.0
        def _g(h, gx, gy, gz):
            h &= 15
            a = gx if h < 8 else gy
            b = gy if h < 4 else (gx if h == 12 or h == 14 else gz)
            return (a if (h & 1) == 0 else -a) + (b if (h & 2) == 0 else -b)
        g0=_g(p[AA],   x,  y,  z);  g1=_g(p[BA],   x1, y,  z)
        g2=_g(p[AB],   x,  y1, z);  g3=_g(p[BB],   x1, y1, z)
        g4=_g(p[AA+1], x,  y,  z1); g5=_g(p[BA+1], x1, y,  z1)
        g6=_g(p[AB+1], x,  y1, z1); g7=_g(p[BB+1], x1, y1, z1)
        l0=g0+u*(g1-g0); l1=g2+u*(g3-g2)
        l2=g4+u*(g5-g4); l3=g6+u*(g7-g6)
        m0=l0+v*(l1-l0); m1=l2+v*(l3-l2)
        return m0+w*(m1-m0)

    def octave_noise(self, x, y, z, octaves=4):
        val=0.0; freq=1.0; amp=1.0; max_amp=0.0
        for _ in range(octaves):
            val += self.noise3d(x*freq, y*freq, z*freq) * amp
            max_amp += amp; amp *= 0.5; freq *= 2.0
        return val / max_amp


# =========================================================================
#  EPW PARSER
# =========================================================================
def find_epw_path():
    candidates = [
        r"D:\RMIT_SEM1 26_AI Accelerated Agentic Architecture TECTONIC\Week 2\EPW file-Ladybug\AUS_VIC_Melbourne.RO.948680_TMYx.epw",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def parse_epw(filepath):
    monthly = {m: {"ghr": [], "dnr": [], "dhr": [], "temp": []} for m in range(1, 13)}
    with open(filepath, "r") as f:
        for line in f:
            if not line[0].isdigit():
                continue
            parts = line.strip().split(",")
            if len(parts) < 35:
                continue
            try:
                month = int(parts[1])
                monthly[month]["temp"].append(float(parts[6]))
                monthly[month]["ghr"].append(float(parts[13]))
                monthly[month]["dnr"].append(float(parts[14]))
                monthly[month]["dhr"].append(float(parts[15]))
            except (ValueError, IndexError):
                continue
    profiles = {}
    for m in range(1, 13):
        d  = monthly[m]
        n  = max(len(d["ghr"]), 1)
        profiles[m] = {key: sum(d[key]) / n for key in ("ghr", "dnr", "dhr", "temp")}
    return profiles


def normalise_profiles(profiles):
    for key in ("ghr", "dnr", "dhr", "temp"):
        vals = [profiles[m][key] for m in range(1, 13)]
        lo, hi = min(vals), max(vals)
        rng = hi - lo if hi > lo else 1.0
        for m in range(1, 13):
            profiles[m][key + "_n"] = (profiles[m][key] - lo) / rng
    return profiles


def get_climate_factors(profiles, month_index, sensitivity):
    if month_index == 0:
        # IronPython 2: avoid dict comprehensions with nested generators —
        # the loop variable isn't visible inside inner generator expressions.
        ghr = sum(profiles[m]["ghr_n"]  for m in range(1, 13)) / 12.0
        dnr = sum(profiles[m]["dnr_n"]  for m in range(1, 13)) / 12.0
        dhr = sum(profiles[m]["dhr_n"]  for m in range(1, 13)) / 12.0
        tmp = sum(profiles[m]["temp_n"] for m in range(1, 13)) / 12.0
        raw = {
            "ghr":  sum(profiles[m]["ghr"]  for m in range(1, 13)) / 12.0,
            "dnr":  sum(profiles[m]["dnr"]  for m in range(1, 13)) / 12.0,
            "dhr":  sum(profiles[m]["dhr"]  for m in range(1, 13)) / 12.0,
            "temp": sum(profiles[m]["temp"] for m in range(1, 13)) / 12.0,
        }
    else:
        p   = profiles[month_index]
        ghr, dnr, dhr, tmp = p["ghr_n"], p["dnr_n"], p["dhr_n"], p["temp_n"]
        raw = {"ghr": p["ghr"], "dnr": p["dnr"], "dhr": p["dhr"], "temp": p["temp"]}
    s = sensitivity
    return {
        "amplitude":   1.0 - s + s * (0.3 + 0.7 * ghr),
        "smoothness":  1.0 - s + s * (1.0 - 0.5 * dhr),
        "height_mult": 1.0 - s + s * (0.3 + 0.7 * tmp),
        "dir_bias":    s * dnr * 0.3,
        "ghr_n": ghr, "dnr_n": dnr, "dhr_n": dhr, "tmp_n": tmp,
        "ghr_raw": raw["ghr"], "dnr_raw": raw["dnr"],
        "dhr_raw": raw["dhr"], "temp_raw": raw["temp"],
    }


# =========================================================================
#  COLOUR GRADIENT   blue → teal → orange → red
# =========================================================================
def density_color(val):
    """Map heat_idx 0..1 → (R, G, B).
    0.0 = cool/shaded  (blue)
    0.5 = mid          (teal → orange)
    1.0 = hot/sunlit   (red)
    """
    if val < 0.5:
        t = val / 0.5
        r = int(30  + t * 30);  g = int(60  + t * 120); b = int(150 - t * 90)
    elif val < 0.75:
        t = (val - 0.5) / 0.25
        r = int(60  + t * 180); g = int(180 - t * 40);  b = int(60  - t * 30)
    else:
        t = (val - 0.75) / 0.25
        r = int(240 - t * 20);  g = int(140 - t * 90);  b = int(30)
    return (max(30, min(255, r)), max(30, min(255, g)), max(30, min(255, b)))


# =========================================================================
#  SCORE + ZONE STATS  (heat_idx at voxel position 3)
# =========================================================================
def compute_score(voxels, hot_target, mid_target):
    """Score 0..1: how well voxel heat_idx distribution matches targets."""
    total = len(voxels)
    if total == 0:
        return 0.0
    hot  = sum(1 for v in voxels if v[3] > 0.75)        / float(total)
    mid  = sum(1 for v in voxels if 0.5 < v[3] <= 0.75) / float(total)
    cool = 1.0 - hot - mid
    cool_target = 1.0 - hot_target - mid_target
    dist = (abs(hot - hot_target) + abs(mid - mid_target) + abs(cool - cool_target)) / 3.0
    # Also reward high average heat_idx (more thermally active mass)
    avg_heat = sum(v[3] for v in voxels) / float(total)
    return max(0.0, 0.7 * (1.0 - dist) + 0.3 * avg_heat)


def zone_percentages(voxels):
    total = len(voxels)
    if total == 0:
        return 0.0, 0.0, 0.0
    hot  = sum(1 for v in voxels if v[3] > 0.75)        / float(total)
    mid  = sum(1 for v in voxels if 0.5 < v[3] <= 0.75) / float(total)
    cool = max(0.0, 1.0 - hot - mid)
    return hot, mid, cool


# =========================================================================
#  CONTAINMENT MASK
# =========================================================================
def _extract_mesh_density(bound_mesh, min_pt, step_x, step_y, step_z,
                           grid_x, grid_y, grid_z):
    # Guard: zero step would cause ZeroDivisionError in vertex binning
    if step_x <= 0 or step_y <= 0 or step_z <= 0:
        return {}
    cell_vals   = {}
    cell_counts = {}
    verts  = bound_mesh.Vertices
    colors = bound_mesh.VertexColors
    has_colors = colors is not None and colors.Count == verts.Count

    if has_colors and colors.Count > 1:
        c0 = colors[0]; all_same = True
        for chk in range(min(colors.Count, 20)):
            cc = colors[chk]
            if cc.R != c0.R or cc.G != c0.G or cc.B != c0.B:
                all_same = False; break
        if all_same:
            has_colors = False

    for vi in range(verts.Count):
        vp = verts[vi]
        ci = int((vp.X - min_pt.X) / step_x)
        cj = int((vp.Y - min_pt.Y) / step_y)
        ck = int((vp.Z - min_pt.Z) / step_z)
        if 0 <= ci < grid_x and 0 <= cj < grid_y and 0 <= ck < grid_z:
            key = (ci, cj, ck)
            if has_colors:
                c = colors[vi]
                lum = (c.R * 0.299 + c.G * 0.587 + c.B * 0.114) / 255.0
                cell_vals.setdefault(key, []).append(lum)
            cell_counts[key] = cell_counts.get(key, 0) + 1

    result = {}
    if has_colors and cell_vals:
        for key, samples in cell_vals.items():
            result[key] = sum(samples) / len(samples)
    elif cell_counts:
        max_count = max(cell_counts.values()) or 1
        for key, cnt in cell_counts.items():
            result[key] = float(cnt) / float(max_count)
    return result


def compute_mask(mode, grid_x, grid_y, grid_z, brep_obj, bound_mesh,
                 min_pt, step_x, step_y, step_z, mesh_map_mode,
                 brep_objs=None):
    """Returns (brep_inside_set, mesh_density_dict).

    brep_objs — optional list of individual Brep objects for multi-building
    containment.  Each grid cell is accepted if it falls inside ANY brep.
    """
    any_brep = brep_objs if brep_objs else ([brep_obj] if brep_obj else [])
    if mode != 1 or (not any_brep and not bound_mesh):
        return None, None

    brep_inside  = set()
    mesh_density = None
    half_sx = step_x * 0.5
    half_sy = step_y * 0.5
    half_sz = step_z * 0.5

    if bound_mesh and not any_brep:
        mesh_density = _extract_mesh_density(
            bound_mesh, min_pt, step_x, step_y, step_z, grid_x, grid_y, grid_z)
        brep_inside  = set(mesh_density.keys())
        print("Mesh mask: %d cells" % len(brep_inside))
    else:
        for bi in range(grid_x):
            for bj in range(grid_y):
                for bk in range(grid_z):
                    pt = rg.Point3d(
                        min_pt.X + bi * step_x + half_sx,
                        min_pt.Y + bj * step_y + half_sy,
                        min_pt.Z + bk * step_z + half_sz)
                    inside = False
                    for b in any_brep:
                        try:
                            if b.IsPointInside(pt, 0.01, False):
                                inside = True
                                break
                        except:
                            pass
                    if inside:
                        brep_inside.add((bi, bj, bk))
        print("Brep mask: %d cells (%d breps)" % (len(brep_inside), len(any_brep)))

    return brep_inside, mesh_density


# =========================================================================
#  VOXEL GENERATION
#  Tuple format: (wx, wy, wz, heat_idx, scale, ix, iy, iz)
#  Position 3 = heat_idx (0=cool/shaded/ground, 1=hot/sunlit/top)
# =========================================================================
def generate_voxels(mode, grid_x, grid_y, grid_z,
                    freq, threshold, sun_mult,
                    climate_factors, perlin,
                    brep_obj=None, bound_mesh=None, sun_vec=None,
                    min_pt=None, max_pt=None,
                    step_x=3.2, step_y=3.2, step_z=3.2,
                    mesh_map_mode=0,
                    precomputed_mask=None,
                    brep_objs=None):
    """Returns list of (wx,wy,wz, heat_idx, scale, ix,iy,iz).

    heat_idx (pos 3) = solar exposure + height score:
      high (red)  = north-facing + upper floors  (thermally hot in Melbourne)
      low  (blue) = south-facing + ground floors  (cool / shaded)

    Perlin noise still determines spatial distribution / threshold culling.
    sun_mult biases the noise density so sun-facing voxels survive more easily.
    """
    oct_noise = perlin.octave_noise
    amp       = climate_factors["amplitude"]
    dnr_n     = climate_factors["dnr_n"]
    dir_bias  = climate_factors["dir_bias"]

    mid_x = (min_pt.X + max_pt.X) * 0.5
    mid_y = (min_pt.Y + max_pt.Y) * 0.5
    mid_z = (min_pt.Z + max_pt.Z) * 0.5
    gz_inv = 1.0 / float(max(1, grid_z - 1))
    gy_inv = 1.0 / float(max(1, grid_y - 1))
    half_sx = step_x * 0.5
    half_sy = step_y * 0.5
    half_sz = step_z * 0.5

    if precomputed_mask is not None:
        brep_inside, mesh_density = precomputed_mask
    elif mode == 1 and (brep_obj or bound_mesh or brep_objs):
        brep_inside, mesh_density = compute_mask(
            mode, grid_x, grid_y, grid_z, brep_obj, bound_mesh,
            min_pt, step_x, step_y, step_z, mesh_map_mode,
            brep_objs=brep_objs)
    else:
        brep_inside = None
        mesh_density = None

    voxels  = []
    _append = voxels.append

    ix = 0
    while ix < grid_x:
        iy = 0
        while iy < grid_y:
            iz = 0
            while iz < grid_z:
                if brep_inside is not None and (ix, iy, iz) not in brep_inside:
                    iz += 1; continue

                wx = min_pt.X + ix * step_x + half_sx
                wy = min_pt.Y + iy * step_y + half_sy
                wz = min_pt.Z + iz * step_z + half_sz

                # ── Perlin noise density (determines threshold survival) ──
                z_ratio   = iz * gz_inv
                layer_amp = amp * (1.0 - z_ratio) + (0.5 + 0.5 * dnr_n) * z_ratio
                z_decay   = 1.0 - z_ratio * 0.4
                n_val = oct_noise(
                    wx * freq + dir_bias * wy * 0.05,
                    wy * freq, wz * freq, 4)
                n_val = (n_val + 1.0) * 0.5
                combined  = n_val * layer_amp * z_decay

                # ── Solar geometry ──
                height_f = iz * gz_inv

                if sun_vec is not None and sun_mult > 0:
                    dvx = wx - mid_x; dvy = wy - mid_y; dvz = wz - mid_z
                    length = math.sqrt(dvx*dvx + dvy*dvy + dvz*dvz)
                    if length > 1e-6:
                        dvx /= length; dvy /= length; dvz /= length
                    # dot(outward_dir, sun_vec): +1=sun-facing, -1=shadow
                    # sun_vec points TOWARD sun → north faces +ve in Melbourne
                    dot      = dvx*sun_vec.X + dvy*sun_vec.Y + dvz*sun_vec.Z
                    solar_f  = (dot + 1.0) * 0.5   # 0..1
                    # Solar bonus: sun-facing voxels survive threshold more easily
                    combined += solar_f * sun_mult * 0.40
                else:
                    # Fallback: north-bias + height (Melbourne sun = north sky)
                    solar_f = iy * gy_inv * 0.55 + 0.45

                combined = max(0.0, min(1.0, combined))

                # Mesh density modulation
                if mesh_map_mode == 1 and mesh_density is not None:
                    combined *= mesh_density.get((ix, iy, iz), 1.0)

                # ── heat_idx: actual thermal exposure for color + zones ──
                # North-facing (solar_f high) + upper floor (height_f high) = hot
                heat_idx = solar_f * 0.65 + height_f * 0.35
                heat_idx = max(0.0, min(1.0, heat_idx))

                if mode == 2:
                    scale = 0.2 + combined * 0.8
                    if scale > 1.0: scale = 1.0
                    if combined >= threshold * 0.3:
                        _append((wx, wy, wz, heat_idx, scale, ix, iy, iz))
                else:
                    if combined > threshold:
                        _append((wx, wy, wz, heat_idx, 1.0, ix, iy, iz))

                iz += 1
            iy += 1
        ix += 1

    return voxels


# =========================================================================
#  MESH BUILDER
# =========================================================================
def build_combined_mesh(voxels, step_x, step_y, step_z):
    mesh = rg.Mesh()
    if not voxels:
        return mesh
    verts  = mesh.Vertices
    faces  = mesh.Faces
    colors = mesh.VertexColors
    _FA    = sd.Color.FromArgb
    hx = step_x * 0.48; hy = step_y * 0.48; hz = step_z * 0.48
    box_v = [(-hx,-hy,-hz),(hx,-hy,-hz),(hx,hy,-hz),(-hx,hy,-hz),
             (-hx,-hy, hz),(hx,-hy, hz),(hx,hy, hz),(-hx,hy, hz)]
    box_f = [(0,1,2,3),(4,5,6,7),(0,1,5,4),(2,3,7,6),(0,3,7,4),(1,2,6,5)]

    for (wx, wy, wz, val, scale, _i, _j, _k) in voxels:
        cr, cg, cb = density_color(val)
        col  = _FA(cr, cg, cb)
        base = verts.Count
        for (bx, by, bz) in box_v:
            verts.Add(wx + bx*scale, wy + by*scale, wz + bz*scale)
            colors.Add(col)
        for (a, b, c, d) in box_f:
            faces.AddFace(base+a, base+b, base+c, base+d)

    mesh.Normals.ComputeNormals()
    return mesh


# =========================================================================
#  PEAK DETECTION
# =========================================================================
def find_peaks(voxels, peak_threshold=0.75):
    lookup = {(v[5], v[6], v[7]): v[3] for v in voxels}
    peaks  = []
    for v in voxels:
        pi, pj, pk, val = v[5], v[6], v[7], v[3]
        if val < peak_threshold:
            continue
        is_peak = True
        for di in (-1, 0, 1):
            if not is_peak: break
            for dj in (-1, 0, 1):
                if not is_peak: break
                for dk in (-1, 0, 1):
                    if di == 0 and dj == 0 and dk == 0: continue
                    if lookup.get((pi+di, pj+dj, pk+dk), 0.0) >= val:
                        is_peak = False; break
        if is_peak:
            peaks.append(v)
    return peaks


def find_zoned_peaks(voxels, spacing=2):
    """Return three lists of attractor points (hot / mid / cool) using
    block-based subsampling — guaranteed to produce output from every zone
    regardless of grid size.

    Strategy: divide the voxel grid into (spacing)³ blocks and keep the
    highest heat_idx voxel per block per zone.

      Hot  (heat_idx >= 0.75) — block size = spacing
      Mid  (0.50 <= val < 0.75) — block size = spacing + 1  (coarser → fewer)
      Cool (val < 0.50)          — block size = spacing + 2  (coarsest → sparsest)

    spacing=1 → finest, most attractor points
    spacing=6 → coarsest, fewest points

    Unlike NMS-radius approaches, this ALWAYS yields at least one point per
    zone when that zone has any voxels — even on small grids.

    Returns (hot_peaks, mid_peaks, cool_peaks) — lists of full voxel tuples
    (wx, wy, wz, heat_idx, scale, ix, iy, iz).
    """
    hot_vox  = [v for v in voxels if v[3] >= 0.75]
    mid_vox  = [v for v in voxels if 0.50 <= v[3] < 0.75]
    cool_vox = [v for v in voxels if v[3] < 0.50]

    def _subsample(zone_voxels, block_r):
        """Keep the voxel with highest heat_idx inside each block_r³ block."""
        if block_r < 1: block_r = 1
        blocks = {}
        for v in zone_voxels:
            bk = (v[5] // block_r, v[6] // block_r, v[7] // block_r)
            if bk not in blocks or v[3] > blocks[bk][3]:
                blocks[bk] = v
        return list(blocks.values())

    hot  = _subsample(hot_vox,  max(1, spacing))
    mid  = _subsample(mid_vox,  max(1, spacing + 1))
    cool = _subsample(cool_vox, max(1, spacing + 2))
    return hot, mid, cool


# =========================================================================
#  LAYERS + BAKE
# =========================================================================
PARENT = "CLIMATE_VOXEL"
LAYER_COLORS = {
    "00_Site_Boundary":  sd.Color.FromArgb(120, 120, 120),
    "01_Voxel_Low":      sd.Color.FromArgb(30,  60,  150),
    "02_Voxel_Med":      sd.Color.FromArgb(60,  180, 160),
    "03_Voxel_High":     sd.Color.FromArgb(220, 50,  30),
    # Attractor points per zone — Hot=strong dent, Mid=moderate, Cool=open
    "04_Attract_Hot":    sd.Color.FromArgb(255, 80,  30),   # red-orange
    "05_Attract_Mid":    sd.Color.FromArgb(255, 210, 60),   # yellow
    "06_Attract_Cool":   sd.Color.FromArgb(60,  160, 255),  # blue
    "07_Metadata":       sd.Color.FromArgb(200, 200, 200),
    "08_Heat_Legend":    sd.Color.FromArgb(255, 200, 50),
}

def ensure_layers():
    if not rs.IsLayer(PARENT):
        rs.AddLayer(PARENT, sd.Color.White)
    for name, col in LAYER_COLORS.items():
        full = PARENT + "::" + name
        if not rs.IsLayer(full):
            rs.AddLayer(full, col)


def bake_final(voxels, hot_peaks, mid_peaks, cool_peaks,
               step_x, step_y, step_z,
               min_pt, climate_factors, month_label, grid_x, grid_y, grid_z):
    """Bake voxel mesh + per-zone attractor points to named layers.

    Attractor dent convention (for downstream scripts):
      04_Attract_Hot  — heat_idx 0.75-1.0  → strong dent / material cluster
      05_Attract_Mid  — heat_idx 0.50-0.75 → moderate dent
      06_Attract_Cool — heat_idx 0.00-0.50 → shallow / open (less dent)
    """
    ensure_layers()
    ox, oy, oz = min_pt.X, min_pt.Y, min_pt.Z

    rs.CurrentLayer(PARENT + "::00_Site_Boundary")
    w = grid_x * step_x; h = grid_y * step_y
    # System.Array required — IronPython 2 lists are not auto-cast to IEnumerable[Point3d]
    pts = System.Array[rg.Point3d]([
        rg.Point3d(ox,   oy,   oz), rg.Point3d(ox+w, oy,   oz),
        rg.Point3d(ox+w, oy+h, oz), rg.Point3d(ox,   oy+h, oz),
        rg.Point3d(ox,   oy,   oz)])
    sc.doc.Objects.AddCurve(rg.PolylineCurve(pts))

    for bname, lo, hi in [("01_Voxel_Low",  0.00, 0.50),
                           ("02_Voxel_Med",  0.50, 0.75),
                           ("03_Voxel_High", 0.75, 1.01)]:
        rs.CurrentLayer(PARENT + "::" + bname)
        band = [v for v in voxels if lo <= v[3] < hi]
        if band:
            m = build_combined_mesh(band, step_x, step_y, step_z)
            if m.Vertices.Count > 0:
                sc.doc.Objects.AddMesh(m)

    # ── Attractor points — one layer per zone ──
    for layer, zone_peaks in [("04_Attract_Hot",  hot_peaks),
                               ("05_Attract_Mid",  mid_peaks),
                               ("06_Attract_Cool", cool_peaks)]:
        if zone_peaks:
            rs.CurrentLayer(PARENT + "::" + layer)
            for v in zone_peaks:
                sc.doc.Objects.AddPoint(rg.Point3d(v[0], v[1], v[2]))

    rs.CurrentLayer(PARENT + "::07_Metadata")
    n_hot = len(hot_peaks); n_mid = len(mid_peaks); n_cool = len(cool_peaks)
    meta = ("%s | %d voxels | attract: %dH %dM %dC | GHR=%.0f T=%.1fC | seed=%s" % (
        month_label, len(voxels), n_hot, n_mid, n_cool,
        climate_factors.get("ghr_raw", 0),
        climate_factors.get("temp_raw", 0),
        climate_factors.get("best_seed", "N/A")))
    sc.doc.Objects.AddTextDot(rg.TextDot(meta, rg.Point3d(ox, oy - step_y*2, oz)))

    try:
        rs.CurrentLayer(PARENT + "::08_Heat_Legend")
        _bake_heat_legend(voxels, ox, oy, oz, step_x, step_y, step_z)
    except Exception as ex:
        print("Heat legend skipped: %s" % str(ex))

    rs.CurrentLayer("Default")
    sc.doc.Views.Redraw()


def _bake_heat_legend(voxels, ox, oy, oz, step_x, step_y, step_z):
    _FA   = sd.Color.FromArgb
    STEPS = 20
    lx = ox - step_x * 3.5
    lw = step_x * 0.6
    lh = step_z * 0.6

    legend_mesh = rg.Mesh()
    vts = legend_mesh.Vertices; fcs = legend_mesh.Faces; cls = legend_mesh.VertexColors
    for si in range(STEPS):
        val = float(si) / float(STEPS - 1)
        cr, cg, cb = density_color(val)
        col = _FA(cr, cg, cb)
        bz  = oz + si * lh
        base = vts.Count
        vts.Add(lx,      oy - lw*0.5, bz);      vts.Add(lx+lw, oy - lw*0.5, bz)
        vts.Add(lx+lw,   oy - lw*0.5, bz+lh);   vts.Add(lx,    oy - lw*0.5, bz+lh)
        for _ in range(4): cls.Add(col)
        fcs.AddFace(base, base+1, base+2, base+3)
    legend_mesh.Normals.ComputeNormals()
    if legend_mesh.Vertices.Count > 0:
        sc.doc.Objects.AddMesh(legend_mesh)

    for val, txt in [(0.0, "0.0  Cool/Shaded"), (0.5, "0.5  Mid"),
                     (0.75, "0.75 Hot Threshold"), (1.0, "1.0  Hot/Sunlit")]:
        sc.doc.Objects.AddTextDot(
            rg.TextDot(txt, rg.Point3d(lx + lw*1.2, oy, oz + val*(STEPS-1)*lh)))
    sc.doc.Objects.AddTextDot(
        rg.TextDot("HEAT INDEX\nblue=cool  red=hot (north+top)",
                   rg.Point3d(lx, oy - step_y*1.5, oz)))

    if not voxels: return
    col_max = {}
    for v in voxels:
        key = (v[5], v[6])
        if key not in col_max or v[3] > col_max[key]:
            col_max[key] = v[3]
    plan_z = oz - step_z * 1.2
    hw = step_x * 0.48; hd = step_y * 0.48
    plan_mesh = rg.Mesh()
    pvts = plan_mesh.Vertices; pfcs = plan_mesh.Faces; pcls = plan_mesh.VertexColors
    for (ix, iy), val in col_max.items():
        cx = ox + ix*step_x + step_x*0.5
        cy = oy + iy*step_y + step_y*0.5
        cr, cg, cb = density_color(val)
        col  = _FA(cr, cg, cb)
        base = pvts.Count
        pvts.Add(cx-hw, cy-hd, plan_z); pvts.Add(cx+hw, cy-hd, plan_z)
        pvts.Add(cx+hw, cy+hd, plan_z); pvts.Add(cx-hw, cy+hd, plan_z)
        for _ in range(4): pcls.Add(col)
        pfcs.AddFace(base, base+1, base+2, base+3)
    plan_mesh.Normals.ComputeNormals()
    if plan_mesh.Vertices.Count > 0:
        sc.doc.Objects.AddMesh(plan_mesh)
    sc.doc.Objects.AddTextDot(
        rg.TextDot("Plan Heat Map (max heat_idx per column)",
                   rg.Point3d(ox, oy - step_y*0.5, plan_z)))


def export_sticky(voxels, hot_peaks, mid_peaks, cool_peaks,
                  grid_x, grid_y, grid_z,
                  step_x, step_y, step_z, min_pt, cf):
    """Write all voxel + attractor data to sc.sticky for downstream scripts.

    Attractor dent convention  (x, y, z, strength):
      climate_attractor_hot  — strength 0.75–1.0 → strongest dent
      climate_attractor_mid  — strength 0.50–0.75
      climate_attractor_cool — strength 0.00–0.50 → least dent / open form
    """
    sc.sticky["climate_grid_size"] = (grid_x, grid_y, grid_z)
    sc.sticky["climate_cell_size"] = (step_x, step_y, step_z)
    sc.sticky["climate_origin"]    = (min_pt.X, min_pt.Y, min_pt.Z)

    # Per-zone attractor tuples: (x, y, z, heat_idx_strength)
    sc.sticky["climate_attractor_hot"]  = [(v[0], v[1], v[2], v[3]) for v in hot_peaks]
    sc.sticky["climate_attractor_mid"]  = [(v[0], v[1], v[2], v[3]) for v in mid_peaks]
    sc.sticky["climate_attractor_cool"] = [(v[0], v[1], v[2], v[3]) for v in cool_peaks]
    # Combined Rhino Point3d list (all zones) — legacy key for older downstream scripts
    all_peaks = hot_peaks + mid_peaks + cool_peaks
    sc.sticky["climate_attractor_pts"] = [rg.Point3d(v[0], v[1], v[2]) for v in all_peaks]

    # climate_voxels: (ix, iy, iz, heat_idx) — heat_idx replaces raw density
    sc.sticky["climate_voxels"]  = [(v[5], v[6], v[7], v[3]) for v in voxels]
    sc.sticky["climate_factors"] = cf

    # Legacy 2D grid: max heat_idx per XY column
    grid = [[0.0]*grid_y for _ in range(grid_x)]
    for v in voxels:
        i2, j2 = v[5], v[6]
        if i2 < grid_x and j2 < grid_y and v[3] > grid[i2][j2]:
            grid[i2][j2] = v[3]
    sc.sticky["climate_density_grid"] = grid


# =========================================================================
#  CUSTOM ZONE BAR  (replaces ProgressBar — native Win32 renders green)
# =========================================================================
class ZoneBar(object):
    """Black-background bar with white fill and white 1-px border.

    Drawn via Eto.Forms.Drawable so we have full colour control.
    ProgressBar on Windows ignores BackgroundColor/ForegroundColor
    and always renders with the system theme (green).

    width=None → bar stretches to fill its layout column (no fixed width).
    width=N    → bar is pinned to N pixels wide (for side-by-side zone bars).
    """
    BAR_H = 14

    def __init__(self, width=110):
        self._frac = 0.0
        d = forms.Drawable()
        if width is not None:
            d.Size = drawing.Size(width, self.BAR_H)
        else:
            # Only fix the height; let the layout stretch the width
            d.MinimumSize = drawing.Size(10, self.BAR_H)
            d.Height = self.BAR_H
        d.Paint += self._on_paint
        self.control = d        # place this in layouts instead of self

    def update(self, fraction):
        """Set fill level (0.0 – 1.0) and request repaint."""
        self._frac = max(0.0, min(1.0, float(fraction)))
        try:
            self.control.Invalidate()
        except Exception:
            pass

    def _on_paint(self, s, e):
        try:
            g  = e.Graphics
            # Read actual rendered size at paint time so stretching works
            cs = self.control.ClientSize
            W  = float(cs.Width)  if cs.Width  > 0 else float(self.control.Width)
            H  = float(cs.Height) if cs.Height > 0 else float(self.BAR_H)
            Bk = drawing.Colors.Black
            Wh = drawing.Colors.White

            # Black background
            g.FillRectangle(Bk, drawing.RectangleF(0.0, 0.0, W, H))

            # White proportional fill (inside 1-px border)
            fw = self._frac * (W - 2.0)
            if fw >= 1.0:
                g.FillRectangle(Wh, drawing.RectangleF(1.0, 1.0, fw, H - 2.0))

            # White border — drawn as four thin filled rectangles
            # (avoids needing a Pen object whose constructor varies by Eto version)
            g.FillRectangle(Wh, drawing.RectangleF(0.0,   0.0,   W,   1.0))  # top
            g.FillRectangle(Wh, drawing.RectangleF(0.0,   H-1.0, W,   1.0))  # bottom
            g.FillRectangle(Wh, drawing.RectangleF(0.0,   0.0,   1.0, H))    # left
            g.FillRectangle(Wh, drawing.RectangleF(W-1.0, 0.0,   1.0, H))    # right
        except Exception:
            pass


# =========================================================================
#  ATTRACTOR DISPLAY CONDUIT
# =========================================================================
class AttractorConduit(Rhino.Display.DisplayConduit):
    """Draws bullseye markers for hot / mid / cool attractor points.

    Renders into the viewport foreground (always on top of geometry,
    no z-fighting with voxels, fixed pixel size at any zoom level, no
    scene objects added or deleted).

    Each marker:
      ● outer filled circle (OUTER_R px) — zone colour
      ● inner filled circle (INNER_R px) — white centre

    Zone colours (temperature-intuitive):
      Hot  → RED    (255, 55,  30)
      Mid  → YELLOW (255, 205, 0)
      Cool → CYAN   (0,   215, 255)

    Markers are placed at the TOP FACE of each voxel + a small upward
    offset so they float visibly above the voxel surface.
    """
    _HOT_COLOR  = sd.Color.FromArgb(255, 55,  30)
    _MID_COLOR  = sd.Color.FromArgb(255, 205, 0)
    _COOL_COLOR = sd.Color.FromArgb(0,   215, 255)
    _WHITE      = sd.Color.White
    OUTER_R = 3    # outer ring radius in pixels
    INNER_R = 1    # white centre radius in pixels

    def __init__(self):
        super(AttractorConduit, self).__init__()
        self._hot  = []   # list of rg.Point3d (top-face + offset)
        self._mid  = []
        self._cool = []

    def update(self, hot_p, mid_p, cool_p, sz):
        """Rebuild point lists.  sz = voxel Z step (offset = sz/2 + small gap)."""
        offset = sz * 0.5 + sz * 0.05   # top face + 5 % clearance
        def _pts(vox_list):
            return [rg.Point3d(v[0], v[1], v[2] + offset) for v in vox_list]
        self._hot  = _pts(hot_p)
        self._mid  = _pts(mid_p)
        self._cool = _pts(cool_p)

    def clear(self):
        self._hot = []; self._mid = []; self._cool = []

    def DrawForeground(self, e):
        try:
            dp    = e.Display
            style = Rhino.Display.PointStyle.Circle
            or_   = self.OUTER_R
            ir_   = self.INNER_R
            for pt in self._hot:
                dp.DrawPoint(pt, style, or_, self._HOT_COLOR)
                dp.DrawPoint(pt, style, ir_, self._WHITE)
            for pt in self._mid:
                dp.DrawPoint(pt, style, or_, self._MID_COLOR)
                dp.DrawPoint(pt, style, ir_, self._WHITE)
            for pt in self._cool:
                dp.DrawPoint(pt, style, or_, self._COOL_COLOR)
                dp.DrawPoint(pt, style, ir_, self._WHITE)
        except Exception:
            pass


# =========================================================================
#  UI HELPERS
# =========================================================================
class SliderNumPair(object):
    def __init__(self, min_v, max_v, default, scale=100, decimals=2):
        self._scale    = float(scale)
        self._decimals = decimals
        self._min_v    = min_v
        self._max_v    = max_v
        self._updating = False
        self._cb       = None
        self._fmt      = "%." + str(decimals) + "f"
        self.slider  = forms.Slider(MinValue=int(min_v*scale),
                                    MaxValue=int(max_v*scale),
                                    Value   =int(default*scale))
        self.textbox = forms.TextBox(Text=self._fmt % default)
        self.textbox.Width = 62
        self.slider.ValueChanged  += self._sl_changed
        self.textbox.TextChanged  += self._tb_changed

    @property
    def value(self):
        return float(self.slider.Value) / self._scale

    @value.setter
    def value(self, v):
        v = max(self._min_v, min(self._max_v, float(v)))
        self._updating = True
        self.slider.Value  = int(v * self._scale)
        self.textbox.Text  = self._fmt % v
        self._updating = False

    def _sl_changed(self, s, e):
        if self._updating: return
        self._updating = True
        self.textbox.Text = self._fmt % self.value
        self._updating = False
        if self._cb: self._cb()

    def _tb_changed(self, s, e):
        if self._updating: return
        try:
            v = max(self._min_v, min(self._max_v, float(self.textbox.Text)))
            self._updating = True
            self.slider.Value = int(v * self._scale)
            self._updating = False
            if self._cb: self._cb()
        except: pass


class ArchInput(object):
    """Textbox for architectural dimensions in mm."""
    def __init__(self, default_mm, min_mm=100, max_mm=60000):
        self._mm       = float(default_mm)
        self._min_mm   = float(min_mm)
        self._max_mm   = float(max_mm)
        self._updating = False
        self._cb       = None
        self.textbox  = forms.TextBox(Text=str(int(default_mm)))
        self.textbox.Width = 72
        self.unit_lbl = forms.Label(Text="mm")
        self.textbox.TextChanged += self._tb_changed

    @property
    def value_mm(self):
        return self._mm

    @value_mm.setter
    def value_mm(self, v):
        v = max(self._min_mm, min(self._max_mm, float(v)))
        self._mm = v
        self._updating = True
        self.textbox.Text = str(int(round(v)))
        self._updating = False
        if self._cb: self._cb()

    @property
    def value_m(self):
        return self._mm / 1000.0

    def _tb_changed(self, s, e):
        if self._updating: return
        try:
            v = max(self._min_mm, min(self._max_mm, float(self.textbox.Text)))
            self._mm = v
            if self._cb: self._cb()
        except: pass


# =========================================================================
#  CONSTANTS
# =========================================================================
MONTH_NAMES = ["Annual Average",
               "January","February","March","April","May","June",
               "July","August","September","October","November","December"]

DEFAULT_CELLS    = 5      # grid cells per axis when no geometry picked
MAX_VOXELS_WARN  = 8000   # show ⚠ in grid label above this count
MAX_VOXELS       = 80000  # hard stop — above this, generation/sim is blocked

_Z_PRESETS_M   = [None, 1.6, 2.7, 3.0, 3.2, 4.0, 4.5, 6.4]
_Z_PRESET_LBLS = ["Custom",
                   "1600 mm  (half floor)",
                   "2700 mm  (low residential)",
                   "3000 mm  (residential)",
                   "3200 mm  (standard) *",
                   "4000 mm  (commercial)",
                   "4500 mm  (commercial hi)",
                   "6400 mm  (double floor)"]

_XY_PRESETS_M   = [None, 1.6, 3.2, 6.0, 6.4, 9.0, 9.6]
_XY_PRESET_LBLS = ["Custom",
                    "1600 mm  (half module)",
                    "3200 mm  (floor module) *",
                    "6000 mm  (column bay)",
                    "6400 mm  (double module)",
                    "9000 mm  (wide bay)",
                    "9600 mm  (triple module)"]


# =========================================================================
#  DARK THEME PALETTE  (monotone / charcoal)
#
#  Must use Eto.Drawing.Color (float 0-1), NOT System.Drawing.Color.
#  Eto controls (BackgroundColor, TextColor) reject System.Drawing.Color
#  with "expected Color, got Color" even though the names look identical.
# =========================================================================
def _ec(r, g, b):
    """Return an Eto.Drawing.Color from 0-255 int components."""
    return drawing.Color(r / 255.0, g / 255.0, b / 255.0)

_TH = {
    "bg_form":   _ec(18,  18,  18),   # form + scrollable bg
    "bg_ctrl":   _ec(36,  36,  36),   # textbox / combobox fill
    "bg_btn":    _ec(50,  50,  50),   # regular button
    "bg_btn_hi": _ec(65,  65,  65),   # primary / action button (bake, sim)
    "fg":        _ec(175, 175, 175),  # normal label text
    "fg_dim":    _ec(85,  85,  85),   # section separator / hint text
    "fg_bright": _ec(218, 218, 218),  # button text / value readouts
    "fg_status": _ec(130, 130, 130),  # status bar
}
del _ec


# =========================================================================
#  ETO GUI  —  composition wrapper around forms.Form
#  (avoids IronPython subclass / IHandler dispatch bug with Show())
# =========================================================================
class AttractorGUI(object):

    def __init__(self, profiles):
        # Create the Eto Form as a direct instance (no subclassing).
        # Calling Show() on a subclassed forms.Form triggers an IronPython 2
        # overload-resolution bug ("expected IHandler, got dict").
        # On a directly-constructed forms.Form() instance that bug doesn't apply.
        self._form = forms.Form()
        self._form.Title           = "Melbourne Climate Voxel Attractor  V7"
        self._form.ClientSize      = drawing.Size(440, 740)
        self._form.Padding         = drawing.Padding(8)
        self._form.Resizable       = True
        self._form.BackgroundColor = _TH["bg_form"]

        self.profiles = profiles
        self.perlin   = PerlinNoise(42)
        self._best_seed   = 42
        self._best_thresh = 0.40
        self._baked       = False   # True after on_bake → skip preview clear in Closed

        # Picked geometry
        self.brep_id      = None
        self.brep_obj     = None
        self.brep_objs    = []   # list of individual Breps (multi-building support)
        self.bound_mesh   = None
        self.line_id      = None
        self.sun_vec      = None
        self.site_obj_ids = []
        self._geo_hidden  = False

        # Generation state
        self.preview_ids      = []   # voxel mesh objects
        # Conduit draws bullseye markers in the viewport overlay (no scene objects)
        self._attract_conduit = AttractorConduit()
        self._attract_conduit.Enabled = True
        self.last_voxels    = []
        self.last_peaks     = []       # combined all zones (for count display)
        self.last_hot_peaks = []
        self.last_mid_peaks = []
        self.last_cool_peaks= []
        self._cf            = None
        self._mn          = None
        self._gx = DEFAULT_CELLS
        self._gy = DEFAULT_CELLS
        self._gz = DEFAULT_CELLS
        self._sx = 3.2; self._sy = 3.2; self._sz = 3.2
        self._generating  = False
        self._initialized = False
        self._model_mm    = False

        # Simulation state
        self._stop_sim    = False
        self._sim_running = False
        self._sim_mask    = None

        # ── Mode ──
        self.mode_combo = forms.ComboBox()
        self.mode_combo.DataStore = [
            "1. Standard Voxel Culling",
            "2. Site Boundary Envelope",
            "3. Adaptive Sizing (Porosity)",
            "4. Custom Sun Vector",
        ]
        self.mode_combo.SelectedIndex = 0

        self.mesh_mode_combo = forms.ComboBox()
        self.mesh_mode_combo.DataStore = ["Replace with Climate", "Modulate Original"]
        self.mesh_mode_combo.SelectedIndex = 0

        # ── Pickers ──
        self.btn_pick_brep = forms.Button(Text="Select Site Geometry")
        self.btn_pick_brep.Click += self.on_pick_brep
        self.btn_load_sticky = forms.Button(Text="Load Base Voxels (sticky)")
        self.btn_load_sticky.Click += self.on_load_sticky
        self.btn_pick_line = forms.Button(Text="Select Sun Line")
        self.btn_pick_line.Click += self.on_pick_line
        self.btn_hide_geo  = forms.Button(Text="Hide Base Geo")
        self.btn_hide_geo.Click += self._on_toggle_geo

        # ── Month ──
        self.month_combo = forms.ComboBox()
        self.month_combo.DataStore    = MONTH_NAMES
        self.month_combo.SelectedIndex = 0

        # ── Grid: auto-fit mode (default) ──
        # User specifies how many cells in each direction;
        # step size is computed from bbox / count automatically.
        self.tb_fit_nx = forms.TextBox(Text=str(DEFAULT_CELLS))
        self.tb_fit_ny = forms.TextBox(Text=str(DEFAULT_CELLS))
        self.tb_fit_nz = forms.TextBox(Text=str(DEFAULT_CELLS))   # same as X/Y
        for tb in (self.tb_fit_nx, self.tb_fit_ny, self.tb_fit_nz):
            tb.Width = 52

        self.btn_fit_grid = forms.Button(Text="Fit Grid to Geometry")
        self.btn_fit_grid.Click += self._on_fit_grid

        self.lbl_fit_info = forms.Label(Text="Step: auto | Grid: 8×8×4 | Vol: auto")

        # ── Thick toggle ──
        self.chk_thick = forms.CheckBox(Text="Custom voxel size (manual mm input)", Checked=False)
        self.chk_thick.CheckedChanged += self._on_thick_changed

        # ── Thick section: manual mm inputs ──
        self.lbl_unit_detect = forms.Label(Text="Units: meters (default)")
        self.arch_x  = ArchInput(3200, min_mm=100, max_mm=30000)
        self.arch_y  = ArchInput(3200, min_mm=100, max_mm=30000)
        self.xy_preset = forms.ComboBox()
        self.xy_preset.DataStore    = _XY_PRESET_LBLS
        self.xy_preset.SelectedIndex = 2
        self.tb_floor_h = forms.TextBox(Text="3200")
        self.tb_floor_h.Width = 72
        self.z_preset = forms.ComboBox()
        self.z_preset.DataStore    = _Z_PRESET_LBLS
        self.z_preset.SelectedIndex = 4
        self.tb_floors = forms.TextBox(Text="")
        self.tb_floors.Width = 50
        self.lbl_z_info = forms.Label(Text="Z: auto | floor = 3200 mm")

        self.vox_x = self.arch_x   # alias kept for _get_bounds backward compat
        self.vox_y = self.arch_y

        # Grid info (shown below both modes)
        self.lbl_grid_info  = forms.Label(Text="Grid: 8×8×4 | Vol: auto")
        self.lbl_vox_count  = forms.Label(Text="Est. cells: --")

        # ── Solar hour ──
        self.sl_sun_hour  = forms.Slider(MinValue=6, MaxValue=18, Value=12)
        self.lbl_sun_hour = forms.Label(Text="12:00")
        self.lbl_sun_pos  = forms.Label(Text="Az: --°  Alt: --°")
        self.btn_avg_sun  = forms.Button(Text="Use Daily Avg Sun")
        self.btn_avg_sun.Click += self._on_avg_sun

        self.chk_opt_time = forms.CheckBox(
            Text="Optimize time of day (6am–6pm)", Checked=False)

        # ── Noise sliders ──
        self.sl_freq    = forms.Slider(MinValue=1, MaxValue=30, Value=8)
        self.lbl_freq   = forms.Label(Text="0.08")
        self.sl_thresh  = forms.Slider(MinValue=10, MaxValue=80, Value=40)
        self.lbl_thresh = forms.Label(Text="0.40")
        self.sl_sun     = forms.Slider(MinValue=0, MaxValue=70, Value=20)
        self.lbl_sun    = forms.Label(Text="0.20")
        self.sl_climate = forms.Slider(MinValue=0, MaxValue=100, Value=60)
        self.lbl_climate= forms.Label(Text="0.60")

        # ── Optimisation ──
        self.opt_hot        = SliderNumPair(0.0, 0.70, 0.25, scale=100, decimals=2)
        self.opt_mid        = SliderNumPair(0.0, 0.80, 0.45, scale=100, decimals=2)
        self.lbl_cool_auto  = forms.Label(Text="Cool (auto): 30%")
        self.tb_max_iter    = forms.TextBox(Text="30")
        self.tb_max_iter.Width = 48
        self.opt_stop       = SliderNumPair(0.60, 1.0, 0.85, scale=100, decimals=2)
        self.btn_start_sim  = forms.Button(Text="Start Simulation")
        self.btn_stop_sim   = forms.Button(Text="Stop")
        self.btn_stop_sim.Enabled = False
        self.pb_progress    = ZoneBar(width=None)  # stretches full row width
        self.lbl_progress   = forms.Label(Text="0/0  |  Best: --")

        # ── Zone bars (custom Drawable — not native ProgressBar) ──
        self.pb_hot   = ZoneBar()
        self.pb_mid   = ZoneBar()
        self.pb_cool  = ZoneBar()
        self.lbl_hot_pct  = forms.Label(Text=" 0% Hot ")
        self.lbl_mid_pct  = forms.Label(Text=" 0% Mid ")
        self.lbl_cool_pct = forms.Label(Text=" 0% Cool")

        # ── Attractor spacing slider ──
        # Controls block size for subsampling: 1 = densest, 6 = sparsest.
        # Updates ONLY the attractor point preview (no voxel regen) for speed.
        self.sl_attract      = forms.Slider(MinValue=1, MaxValue=6, Value=2)
        self.lbl_attract_val = forms.Label(Text="2")

        # ── Bottom controls ──
        self.chk_live   = forms.CheckBox(Text="Live Preview", Checked=True)
        self.btn_update = forms.Button(Text="Force Update")
        self.btn_update.Click += self.on_update
        self.btn_bake   = forms.Button(Text="Bake to Layers")
        self.btn_bake.Click += self.on_bake
        self.btn_cancel = forms.Button(Text="Close")
        self.btn_cancel.Click += self.on_cancel
        self.lbl_status = forms.Label(Text="Ready")

        # ── Layout ──
        self._build_layout()

        # ── Connect events ──
        self.mode_combo.SelectedIndexChanged      += self.on_changed
        self.mesh_mode_combo.SelectedIndexChanged += self.on_changed
        self.month_combo.SelectedIndexChanged     += self.on_changed
        self.sl_freq.ValueChanged    += self.on_changed
        self.sl_thresh.ValueChanged  += self.on_changed
        self.sl_sun.ValueChanged     += self.on_changed
        self.sl_climate.ValueChanged += self.on_changed
        self.sl_sun_hour.ValueChanged += self._on_sun_hour_changed

        self.tb_fit_nx.TextChanged += self._on_fit_cell_changed
        self.tb_fit_ny.TextChanged += self._on_fit_cell_changed
        self.tb_fit_nz.TextChanged += self._on_fit_cell_changed

        self.arch_x._cb = self._on_vox_changed
        self.arch_y._cb = self._on_vox_changed
        self.opt_hot._cb = self._update_cool_label
        self.opt_mid._cb = self._update_cool_label

        self.z_preset.SelectedIndexChanged  += self._on_z_preset
        self.xy_preset.SelectedIndexChanged += self._on_xy_preset
        self.tb_floor_h.TextChanged += self._on_floor_changed
        self.tb_floors.TextChanged  += self._on_floor_changed

        self.btn_start_sim.Click  += self.on_start_sim
        self.btn_stop_sim.Click   += self.on_stop_sim
        self.sl_attract.ValueChanged += self._on_attract_changed

        # ── Cleanup on window close ──
        self._form.Closed += self._on_closed

        # Initial state for thick section (disabled by default)
        self._set_thick_enabled(False)

        self._initialized = True
        self._apply_dark_theme()

    # ── Dark theme ──
    def _apply_dark_theme(self):
        """Walk all stored widget attributes and apply the dark palette.

        Eto on Windows uses native Win32 controls for Slider and ProgressBar
        — those ignore BackgroundColor, so we skip them.  Everything else
        (Label, Button, TextBox, ComboBox, CheckBox, Scrollable) is styled.
        """
        th = _TH
        for attr, obj in self.__dict__.items():
            try:
                if isinstance(obj, forms.Label):
                    obj.TextColor = th["fg"]
                elif isinstance(obj, forms.Button):
                    obj.BackgroundColor = th["bg_btn"]
                    obj.TextColor       = th["fg_bright"]
                elif isinstance(obj, forms.TextBox):
                    obj.BackgroundColor = th["bg_ctrl"]
                    obj.TextColor       = th["fg_bright"]
                elif isinstance(obj, forms.ComboBox):
                    obj.BackgroundColor = th["bg_ctrl"]
                    obj.TextColor       = th["fg"]
                elif isinstance(obj, forms.CheckBox):
                    obj.TextColor = th["fg"]
                elif isinstance(obj, SliderNumPair):
                    obj.textbox.BackgroundColor = th["bg_ctrl"]
                    obj.textbox.TextColor       = th["fg_bright"]
                elif isinstance(obj, ArchInput):
                    obj.textbox.BackgroundColor = th["bg_ctrl"]
                    obj.textbox.TextColor       = th["fg_bright"]
            except Exception:
                pass

        # Primary / action buttons — slightly brighter than plain buttons
        for btn in (self.btn_bake, self.btn_start_sim, self.btn_avg_sun):
            try:
                btn.BackgroundColor = th["bg_btn_hi"]
                btn.TextColor       = th["fg_bright"]
            except Exception:
                pass

        # Status label — dimmer
        try:
            self.lbl_status.TextColor = th["fg_status"]
        except Exception:
            pass

        # Value readout labels — slightly brighter
        for lbl in (self.lbl_freq, self.lbl_thresh, self.lbl_sun,
                    self.lbl_climate, self.lbl_sun_hour,
                    self.lbl_attract_val, self.lbl_grid_info,
                    self.lbl_vox_count, self.lbl_fit_info,
                    self.lbl_hot_pct, self.lbl_mid_pct, self.lbl_cool_pct,
                    self.lbl_progress):
            try:
                lbl.TextColor = th["fg_bright"]
            except Exception:
                pass

    # ── Layout builder ──
    def _build_layout(self):
        layout = forms.DynamicLayout()
        layout.Spacing = drawing.Size(4, 3)

        th = _TH
        def lbl(text, dim=False):
            """Inline label factory with pre-applied theme colour."""
            l = forms.Label(Text=text)
            l.TextColor = th["fg_dim"] if dim else th["fg"]
            return l

        def sep(txt=""):
            """Styled section header — uppercase, dim grey."""
            l = forms.Label(Text=txt.upper() if txt else "")
            l.TextColor = th["fg_dim"]
            layout.AddRow(l)

        layout.AddRow(lbl("Mode:"))
        layout.AddRow(self.mode_combo)
        layout.AddRow(self.btn_pick_brep, self.btn_pick_line)
        layout.AddRow(self.btn_load_sticky)
        layout.AddRow(self.btn_hide_geo)
        layout.AddRow(lbl("Mesh Mapping:"))
        layout.AddRow(self.mesh_mode_combo)

        # ── Grid: auto-fit ──
        sep("Grid  —  cells × bbox step")
        def fit_row(label, tb):
            r = forms.DynamicLayout()
            r.Spacing = drawing.Size(3, 0)
            r.AddRow(lbl(label), tb, lbl("cells"))
            layout.AddRow(r)

        fit_row("X:", self.tb_fit_nx)
        fit_row("Y:", self.tb_fit_ny)
        fit_row("Z:", self.tb_fit_nz)
        layout.AddRow(self.lbl_fit_info)
        layout.AddRow(self.lbl_grid_info)
        layout.AddRow(self.lbl_vox_count)

        # ── Noise & Climate ──
        sep("Noise & Climate")
        layout.AddRow(lbl("Climate Month:"))
        layout.AddRow(self.month_combo)
        layout.AddRow(lbl("Climate Sensitivity:"), self.lbl_climate)
        layout.AddRow(self.sl_climate)
        layout.AddRow(lbl("Noise Frequency:"), self.lbl_freq)
        layout.AddRow(self.sl_freq)
        layout.AddRow(lbl("Density Threshold:"), self.lbl_thresh)
        layout.AddRow(self.sl_thresh)

        # ── Solar ──
        sep("Solar Position  —  Melbourne -37.8°")
        sun_row = forms.DynamicLayout()
        sun_row.Spacing = drawing.Size(4, 0)
        sun_row.AddRow(lbl("Hour:"), self.sl_sun_hour, self.lbl_sun_hour)
        layout.AddRow(sun_row)
        layout.AddRow(self.lbl_sun_pos)
        layout.AddRow(self.btn_avg_sun)
        layout.AddRow(lbl("Sun Influence:"), self.lbl_sun)
        layout.AddRow(self.sl_sun)

        # ── Optimization ──
        sep("Optimization  —  seed + threshold search")

        def opt_row(label, pair):
            r = forms.DynamicLayout()
            r.Spacing = drawing.Size(3, 0)
            r.AddRow(lbl(label), pair.slider, pair.textbox)
            layout.AddRow(r)

        opt_row("Hot target:", self.opt_hot)
        opt_row("Mid target:", self.opt_mid)
        layout.AddRow(self.lbl_cool_auto)

        iter_row = forms.DynamicLayout()
        iter_row.Spacing = drawing.Size(3, 0)
        iter_row.AddRow(lbl("Max iter:"), self.tb_max_iter,
                        lbl("  Stop>=:"),
                        self.opt_stop.slider, self.opt_stop.textbox)
        layout.AddRow(iter_row)
        layout.AddRow(self.chk_opt_time)
        layout.AddRow(self.btn_start_sim, self.btn_stop_sim)
        layout.AddRow(self.pb_progress.control)
        layout.AddRow(self.lbl_progress)

        # ── Zone bars ──
        sep("Zone Distribution  —  heat index")
        layout.AddRow(lbl("Hot: "),  self.pb_hot.control,  self.lbl_hot_pct)
        layout.AddRow(lbl("Mid: "),  self.pb_mid.control,  self.lbl_mid_pct)
        layout.AddRow(lbl("Cool:"),  self.pb_cool.control, self.lbl_cool_pct)

        # ── Attractor density ──
        sep("Attractor Points  —  red=hot  yellow=mid  cyan=cool")
        layout.AddRow(lbl("Density:"), self.sl_attract, self.lbl_attract_val)
        layout.AddRow(lbl("  1=dense  ←  →  6=sparse    (live update)", dim=True))

        # ── Bottom ──
        layout.AddRow(self.chk_live, self.btn_update)
        layout.AddRow(self.btn_bake,  self.btn_cancel)
        layout.AddRow(self.lbl_status)

        scroll = forms.Scrollable()
        scroll.BackgroundColor    = _TH["bg_form"]
        scroll.Content            = layout
        scroll.ExpandContentWidth  = True
        scroll.ExpandContentHeight = False
        self._form.Content = scroll

    # ── Startup ──
    def _init_generate(self):
        self._compute_sun_position()
        self._generate()

    # ── Helpers ──
    def _update_cool_label(self):
        cool_p = max(0.0, 1.0 - self.opt_hot.value - self.opt_mid.value)
        self.lbl_cool_auto.Text = "Cool (auto): %d%%" % int(cool_p * 100)

    def _set_thick_enabled(self, enabled):
        """Enable or disable the manual mm input controls."""
        for ctrl in (self.lbl_unit_detect, self.xy_preset,
                     self.arch_x.textbox, self.arch_x.unit_lbl,
                     self.arch_y.textbox, self.arch_y.unit_lbl,
                     self.z_preset, self.tb_floor_h,
                     self.tb_floors, self.lbl_z_info):
            ctrl.Enabled = enabled
        for ctrl in (self.tb_fit_nx, self.tb_fit_ny, self.tb_fit_nz,
                     self.btn_fit_grid, self.lbl_fit_info):
            ctrl.Enabled = not enabled

    def _on_thick_changed(self, s, e):
        if not self._initialized: return
        thick = self.chk_thick.Checked
        self._set_thick_enabled(thick)
        self._sim_mask = None
        if thick:
            self._update_z_info()
        else:
            self._update_fit_info()
        self._update_grid_label()
        if self.chk_live.Checked and not self._generating:
            self._generate()

    # ── Auto-fit helpers ──
    def _get_fit_count(self, tb, default):
        try:
            v = int(float(tb.Text))
            return max(1, min(200, v))
        except:
            return default

    def _on_fit_cell_changed(self, s, e):
        if not self._initialized: return
        if self.chk_thick.Checked: return
        self._sim_mask = None
        self._update_fit_info()
        self._update_grid_label()
        if self.chk_live.Checked and not self._generating:
            self._generate()

    def _geo_bbox(self):
        """Union bounding box of all selected geometry (multi-building safe)."""
        bb = rg.BoundingBox.Empty
        if self.brep_objs:
            for b in self.brep_objs:
                try:
                    bb = rg.BoundingBox.Union(bb, b.GetBoundingBox(True))
                except: pass
        elif self.brep_obj:
            try:
                bb = rg.BoundingBox.Union(bb, self.brep_obj.GetBoundingBox(True))
            except: pass
        if self.bound_mesh:
            try:
                bb = rg.BoundingBox.Union(bb, self.bound_mesh.GetBoundingBox(True))
            except: pass
        return bb

    def _on_fit_grid(self, s, e):
        """Suggest cell counts from geometry bbox at ~3.2m/3200mm per cell."""
        if not (self.brep_objs or self.brep_obj or self.bound_mesh):
            self.lbl_status.Text = "Select geometry first, then Fit Grid."
            return
        bb = self._geo_bbox()
        if not bb.IsValid: return
        dx = bb.Max.X - bb.Min.X
        dy = bb.Max.Y - bb.Min.Y
        dz = bb.Max.Z - bb.Min.Z
        # Target step: 3200mm in model units
        target = 3200.0 if self._model_mm else 3.2
        nx = max(2, int(round(dx / target)))
        ny = max(2, int(round(dy / target)))
        nz = max(1, int(round(dz / target)))
        self.tb_fit_nx.Text = str(nx)
        self.tb_fit_ny.Text = str(ny)
        self.tb_fit_nz.Text = str(nz)
        self.lbl_status.Text = "Grid fit: %d×%d×%d cells" % (nx, ny, nz)
        if self.chk_live.Checked and not self._generating:
            self._generate()

    def _update_fit_info(self):
        nx = self._get_fit_count(self.tb_fit_nx, DEFAULT_CELLS)
        ny = self._get_fit_count(self.tb_fit_ny, DEFAULT_CELLS)
        nz = self._get_fit_count(self.tb_fit_nz, DEFAULT_CELLS)
        if self.brep_obj or self.bound_mesh:
            bb = (self.brep_obj.GetBoundingBox(True) if self.brep_obj
                  else self.bound_mesh.GetBoundingBox(True))
            if bb.IsValid:
                dx = bb.Max.X - bb.Min.X
                dy = bb.Max.Y - bb.Min.Y
                dz = bb.Max.Z - bb.Min.Z
                sx = dx / float(nx); sy = dy / float(ny); sz = dz / float(nz)
                unit = "mm" if self._model_mm else "m"
                self.lbl_fit_info.Text = "Step: %.1f×%.1f×%.1f%s" % (sx, sy, sz, unit)
                return
        self.lbl_fit_info.Text = "Step: auto (no geometry)"

    # ── mm / floor helpers ──
    def _get_floor_h_mm(self):
        try:
            return max(100.0, min(30000.0, float(self.tb_floor_h.Text)))
        except:
            return 3200.0

    def _get_floors(self):
        try:
            return max(0, int(float(self.tb_floors.Text)))
        except:
            return 0

    def _world_step(self, mm_val):
        return mm_val if self._model_mm else mm_val / 1000.0

    def _update_z_info(self):
        fh = self._get_floor_h_mm()
        fc = self._get_floors()
        if fc > 0:
            self.lbl_z_info.Text = "= %d mm total  |  %d layers" % (int(fh * fc), fc)
        else:
            self.lbl_z_info.Text = "Z: auto from geometry  |  floor = %d mm" % int(fh)

    def _update_grid_label(self):
        self.lbl_grid_info.Text = "Grid: %d×%d×%d" % (self._gx, self._gy, self._gz)
        total = self._gx * self._gy * self._gz
        warn  = "  ⚠" if total > MAX_VOXELS_WARN else "  ✓"
        self.lbl_vox_count.Text = "Est. cells: %d%s" % (total, warn)

    def _on_z_preset(self, s, e):
        if not self._initialized: return
        idx = int(self.z_preset.SelectedIndex)
        if 0 < idx < len(_Z_PRESETS_M):
            self.tb_floor_h.Text = str(int(_Z_PRESETS_M[idx] * 1000))

    def _on_xy_preset(self, s, e):
        if not self._initialized: return
        idx = int(self.xy_preset.SelectedIndex)
        if 0 < idx < len(_XY_PRESETS_M):
            v_mm = _XY_PRESETS_M[idx] * 1000
            self.arch_x.value_mm = v_mm
            self.arch_y.value_mm = v_mm
            self._on_vox_changed()

    def _on_floor_changed(self, s, e):
        if not self._initialized: return
        if not self.chk_thick.Checked: return
        self._sim_mask = None
        self._update_z_info()
        if self.chk_live.Checked and not self._generating:
            self._generate()

    def _on_vox_changed(self):
        if not self._initialized: return
        self._sim_mask = None
        self._update_z_info()
        self._update_grid_label()
        if self.chk_live.Checked and not self._generating:
            self._generate()

    # ── Solar position ──
    def _on_sun_hour_changed(self, s, e):
        if not self._initialized: return
        self._compute_sun_position()
        if self.chk_live.Checked and not self._generating:
            self._generate()

    def _compute_sun_position(self):
        hour  = float(self.sl_sun_hour.Value)
        h_int = int(hour); h_min = int((hour - h_int) * 60)
        self.lbl_sun_hour.Text = "%02d:%02d" % (h_int, h_min)
        month_idx = int(self.month_combo.SelectedIndex)
        az, alt   = solar_position(month_idx, hour)
        if alt > 0:
            self.sun_vec = sun_vec_from_angles(az, alt)
            self.lbl_sun_pos.Text = "Az: %.1f°  Alt: %.1f°  (above horizon)" % (az, alt)
        else:
            self.sun_vec = None
            self.lbl_sun_pos.Text = "Az: %.1f°  Alt: %.1f°  ⚠ below horizon" % (az, alt)

    def _on_avg_sun(self, s, e):
        """Irradiance-weighted daily average sun vector for the selected month."""
        month_idx = int(self.month_combo.SelectedIndex)
        wx = wy = wz = total_w = 0.0
        valid_hours = []
        for h in range(6, 19):
            az, alt = solar_position(month_idx, float(h))
            if alt <= 0: continue
            w  = math.sin(math.radians(alt))
            sv = sun_vec_from_angles(az, alt)
            wx += sv.X * w; wy += sv.Y * w; wz += sv.Z * w
            total_w += w
            valid_hours.append((h, alt))
        if total_w > 0:
            avg = rg.Vector3d(wx / total_w, wy / total_w, wz / total_w)
            avg.Unitize()
            self.sun_vec = avg
            # avg.Z = sin(altitude) since vector points toward sun
            equiv_alt = math.degrees(math.asin(max(-1.0, min(1.0, avg.Z))))
            self.lbl_sun_hour.Text = "avg"
            self.lbl_sun_pos.Text = (
                "Daily avg  Alt≈%.1f°  (%d valid hours, wt by irradiance)" %
                (equiv_alt, len(valid_hours)))
        else:
            self.sun_vec = None
            self.lbl_sun_hour.Text = "avg"
            self.lbl_sun_pos.Text = "No daylight hours for this month."
        if self.chk_live.Checked and not self._generating:
            self._generate()

    # ── Voxel cell-size detection ──
    def _detect_cell_size_from_sticky(self):
        """Read exact cell size written by a previous voxel script via sc.sticky.
        Tries climate_* keys first, then ccs_* (Climate Comfort Special).
        Returns (sx, sy, sz) floats or None.
        """
        for key_c, key_g in [("climate_cell_size", "climate_grid_size"),
                              ("ccs_cell_size",     "ccs_grid_size")]:
            cs = sc.sticky.get(key_c)
            gs = sc.sticky.get(key_g)
            if cs and gs:
                try:
                    sx, sy, sz = float(cs[0]), float(cs[1]), float(cs[2])
                    if sx > 0 and sy > 0 and sz > 0:
                        return sx, sy, sz
                except Exception:
                    pass
        return None

    def _detect_cell_size_from_mesh(self, mesh, bb):
        """Estimate individual voxel size from the most-common vertex spacing
        along each axis, ignoring mesh-subdivision noise.

        Key insight: only consider gaps >= 2% of the bounding box dimension.
        A 3.2 m voxel in a 64 m site → min_gap = 1.28 m (filters 0.3 m noise).
        A 3200 mm voxel in 64000 mm site → min_gap = 1280 mm (filters 0.3 mm).
        Returns (sx, sy, sz) or None if plausible sizes cannot be found.
        """
        if not bb.IsValid:
            return None
        dx = bb.Max.X - bb.Min.X
        dy = bb.Max.Y - bb.Min.Y
        dz = bb.Max.Z - bb.Min.Z
        if dx <= 0 or dy <= 0 or dz <= 0:
            return None

        # Minimum plausible cell size = 2 % of that axis dimension.
        # This filters mesh-subdivision vertex gaps (which are tiny fractions
        # of the bbox) without affecting real voxel-boundary gaps.
        min_sx = dx * 0.02
        min_sy = dy * 0.02
        min_sz = dz * 0.02

        verts = mesh.Vertices
        total = verts.Count
        if total < 8:
            return None

        stride = max(1, total // 8000)
        xs, ys, zs = [], [], []
        for i in range(0, total, stride):
            v = verts[i]
            xs.append(v.X)
            ys.append(v.Y)
            zs.append(v.Z)

        def best_gap(coords, min_gap):
            prec = max(1, int(-math.log10(min_gap)) + 2) if min_gap > 0 else 3
            prec = min(prec, 6)
            uniq = sorted(set(round(c, prec) for c in coords))
            gap_counts = {}
            for i in range(len(uniq) - 1):
                g = round(uniq[i + 1] - uniq[i], prec)
                if g >= min_gap:
                    gap_counts[g] = gap_counts.get(g, 0) + 1
            if not gap_counts:
                return None
            return max(gap_counts, key=gap_counts.get)

        sx = best_gap(xs, min_sx)
        sy = best_gap(ys, min_sy)
        sz = best_gap(zs, min_sz)
        if not (sx and sy and sz):
            return None

        # Sanity check: detected size must produce a reasonable grid count.
        # If the result would need more than MAX_VOXELS_WARN cells the
        # detection almost certainly found the wrong gap — discard it.
        est = int(dx / sx) * int(dy / sy) * int(dz / sz)
        if est > MAX_VOXELS_WARN:
            return None

        return sx, sy, sz

    # ── Auto-scale after geometry pick ──
    def _auto_suggest_scale(self, bb):
        if not bb.IsValid: return
        dx = bb.Max.X - bb.Min.X
        dy = bb.Max.Y - bb.Min.Y
        dz = bb.Max.Z - bb.Min.Z
        if dx > 5000:
            self._model_mm = True
            self.lbl_unit_detect.Text = "Units: mm (auto-detected, bbox %.0f wide)" % dx
        else:
            self._model_mm = False
            self.lbl_unit_detect.Text = "Units: m (auto-detected, bbox %.1f wide)" % dx

        # Block events while batch-updating textboxes to prevent cascading
        # _generate() calls with partially-updated cell counts.
        was_init = self._initialized
        self._initialized = False
        try:
            if self.chk_thick.Checked:
                fh_mm = self._get_floor_h_mm()
                dz_mm = dz if self._model_mm else dz * 1000
                suggested = max(1, int(round(dz_mm / fh_mm)))
                self.tb_floors.Text = str(suggested)
            else:
                target = 3200.0 if self._model_mm else 3.2
                nx = max(2, int(round(dx / target)))
                ny = max(2, int(round(dy / target)))
                nz = max(1, int(round(dz / target)))
                self.tb_fit_nx.Text = str(nx)
                self.tb_fit_ny.Text = str(ny)
                self.tb_fit_nz.Text = str(nz)
        finally:
            self._initialized = was_init

        # Update info labels (no events)
        if self.chk_thick.Checked:
            self._update_z_info()
        else:
            self._update_fit_info()

        # Warn on large grids
        nx_f = self._get_fit_count(self.tb_fit_nx, DEFAULT_CELLS)
        ny_f = self._get_fit_count(self.tb_fit_ny, DEFAULT_CELLS)
        nz_f = self._get_fit_count(self.tb_fit_nz, DEFAULT_CELLS)
        est  = nx_f * ny_f * nz_f
        if est > MAX_VOXELS:
            self.lbl_status.Text = "WARNING: ~%d cells — too large, reduce counts." % est
        elif est > MAX_VOXELS_WARN:
            self.lbl_status.Text = "Large grid: ~%d cells. Simulation may be slow." % est
        else:
            self.lbl_status.Text = "Geometry picked. Est. %d cells." % est

    def _get_cf(self, sens, month_idx):
        if self.profiles:
            return get_climate_factors(self.profiles, month_idx, sens)
        return {"amplitude": 1.0, "smoothness": 1.0, "height_mult": 1.0,
                "dir_bias": 0.0,  "ghr_n": 0.5,      "dnr_n": 0.5,
                "dhr_n": 0.5,     "tmp_n": 0.5,
                "ghr_raw": 400.0, "dnr_raw": 200.0,
                "dhr_raw": 200.0, "temp_raw": 15.0}

    def _read_params(self):
        freq   = float(self.sl_freq.Value)    / 100.0
        thresh = float(self.sl_thresh.Value)  / 100.0
        sun    = float(self.sl_sun.Value)     / 100.0
        sens   = float(self.sl_climate.Value) / 100.0
        month  = int(self.month_combo.SelectedIndex)
        mode   = int(self.mode_combo.SelectedIndex)
        self.lbl_freq.Text    = "%.2f" % freq
        self.lbl_thresh.Text  = "%.2f" % thresh
        self.lbl_sun.Text     = "%.2f" % sun
        self.lbl_climate.Text = "%.2f" % sens
        return mode, freq, thresh, sun, sens, month

    def _get_bounds(self, mode):
        """Return (min_pt, max_pt, nx, ny, nz, sx, sy, sz) based on current mode."""
        thick = self.chk_thick.Checked

        if thick:
            # ── Manual mm mode ──
            vx = self._world_step(self.arch_x.value_mm)
            vy = self._world_step(self.arch_y.value_mm)
            vz = self._world_step(self._get_floor_h_mm())
            floors = self._get_floors()

            if mode == 1 and (self.brep_objs or self.brep_obj or self.bound_mesh):
                bb = self._geo_bbox()
                if bb.IsValid:
                    nx = max(2, int(round((bb.Max.X - bb.Min.X) / vx)))
                    ny = max(2, int(round((bb.Max.Y - bb.Min.Y) / vy)))
                    nz = floors if floors > 0 else max(1, int(round((bb.Max.Z - bb.Min.Z) / vz)))
                    total = nx * ny * nz
                    if total > MAX_VOXELS_WARN:
                        self.lbl_status.Text = "Large grid: %d cells. Sim may be slow." % total
                    self._gx = nx; self._gy = ny; self._gz = nz
                    self._sx = vx; self._sy = vy; self._sz = vz
                    self._update_grid_label()
                    return bb.Min, bb.Max, nx, ny, nz, vx, vy, vz

            # Unbound
            nx = ny = DEFAULT_CELLS
            nz = floors if floors > 0 else DEFAULT_CELLS
            self._gx = nx; self._gy = ny; self._gz = nz
            self._sx = vx; self._sy = vy; self._sz = vz
            mn = rg.Point3d(0, 0, 0)
            mx = rg.Point3d(nx*vx, ny*vy, nz*vz)
            self._update_grid_label()
            return mn, mx, nx, ny, nz, vx, vy, vz

        else:
            # ── Auto-fit mode ──
            nx = self._get_fit_count(self.tb_fit_nx, DEFAULT_CELLS)
            ny = self._get_fit_count(self.tb_fit_ny, DEFAULT_CELLS)
            nz = self._get_fit_count(self.tb_fit_nz, DEFAULT_CELLS)

            if mode == 1 and (self.brep_objs or self.brep_obj or self.bound_mesh):
                bb = self._geo_bbox()
                if bb.IsValid:
                    dx = bb.Max.X - bb.Min.X
                    dy = bb.Max.Y - bb.Min.Y
                    dz = bb.Max.Z - bb.Min.Z
                    vx = dx / float(nx)
                    vy = dy / float(ny)
                    vz = dz / float(nz)
                    # Guard against zero/flat geometry (e.g. 2-D surface, nz=1 flat plane)
                    vx = max(vx, 1e-4)
                    vy = max(vy, 1e-4)
                    vz = max(vz, 1e-4)
                    total = nx * ny * nz
                    if total > MAX_VOXELS_WARN:
                        self.lbl_status.Text = "Large grid: %d cells. Sim may be slow." % total
                    self._gx = nx; self._gy = ny; self._gz = nz
                    self._sx = vx; self._sy = vy; self._sz = vz
                    self._update_fit_info()
                    self._update_grid_label()
                    return bb.Min, bb.Max, nx, ny, nz, vx, vy, vz

            # Unbound: use 3.2m default steps
            vx = vy = vz = 3.2 if not self._model_mm else 3200.0
            self._gx = nx; self._gy = ny; self._gz = nz
            self._sx = vx; self._sy = vy; self._sz = vz
            mn = rg.Point3d(0, 0, 0)
            mx = rg.Point3d(nx*vx, ny*vy, nz*vz)
            self._update_fit_info()
            self._update_grid_label()
            return mn, mx, nx, ny, nz, vx, vy, vz

    def _update_zone_bars(self, voxels):
        hot_p, mid_p, cool_p = zone_percentages(voxels)
        self.pb_hot.update(hot_p)
        self.pb_mid.update(mid_p)
        self.pb_cool.update(cool_p)
        self.lbl_hot_pct.Text  = "%2d%% Hot " % int(hot_p  * 100)
        self.lbl_mid_pct.Text  = "%2d%% Mid " % int(mid_p  * 100)
        self.lbl_cool_pct.Text = "%2d%% Cool" % int(cool_p * 100)

    # ── Event handlers ──
    def on_changed(self, s, e):
        if not self._initialized: return
        self._compute_sun_position()
        if self.chk_live.Checked and not self._generating:
            self._generate()

    def on_update(self, s, e):
        self._generate()

    def on_pick_brep(self, s, e):
        """Inline geometry pick: hide dialog, pick, show dialog."""
        try:
            self._ensure_geo_visible()
            self._form.Visible = False
            Rhino.RhinoApp.SetFocusToMainWindow()

            go = Rhino.Input.Custom.GetObject()
            go.SetCommandPrompt("Select site geometry (Brep / Mesh / Extrusion, multiple OK)")
            go.GeometryFilter = (Rhino.DocObjects.ObjectType.Brep    |
                                 Rhino.DocObjects.ObjectType.Mesh     |
                                 Rhino.DocObjects.ObjectType.Extrusion|
                                 Rhino.DocObjects.ObjectType.SubD)
            go.EnablePreSelect(True, True)
            go.GetMultiple(1, 0)

            self._show_front()
            if go.CommandResult() != Rhino.Commands.Result.Success:
                return

            # ObjectCount is a PROPERTY (not a method) — no parentheses
            # Guard: go.Object(i) can return None for sub-objects or block refs
            objs = []
            for i in range(go.ObjectCount):
                ref = go.Object(i)
                if ref is not None:
                    objs.append(ref.ObjectId)
            if not objs:
                self.lbl_status.Text = "No valid objects from selection."
                return

            self.brep_id      = objs[0]
            self.brep_obj     = None
            self.brep_objs    = []
            self.bound_mesh   = None
            self._sim_mask    = None
            self.site_obj_ids = list(objs)

            meshes = []; breps = []
            for oid in objs:
                g = rs.coercebrep(oid)
                if g:
                    breps.append(g)
                else:
                    m = rs.coercemesh(oid)
                    if m: meshes.append(m)

            bb_pick = rg.BoundingBox.Empty

            if meshes:
                # Mesh path: combine all meshes + brep-converted meshes
                combined = rg.Mesh()
                for m in meshes: combined.Append(m)
                for b in breps:
                    bm_list = rg.Mesh.CreateFromBrep(b, rg.MeshingParameters.Default)
                    if bm_list:
                        for bm in bm_list: combined.Append(bm)
                self.bound_mesh = combined
                bb_pick = combined.GetBoundingBox(True)
            elif breps:
                # Brep path: keep ALL breps individually for multi-building containment.
                # Do NOT join disconnected breps — JoinBreps only works for adjacent faces.
                # Combined bbox covers all buildings; containment tests each brep.
                self.brep_objs = breps
                if len(breps) == 1:
                    self.brep_obj = breps[0]   # keep single-brep fast path
                for b in breps:
                    bb_pick = rg.BoundingBox.Union(bb_pick, b.GetBoundingBox(True))

            # Fallback for Extrusion / SubD / Block objects that coerce can't handle:
            # rs.BoundingBox works on ANY object type in the document.
            if not bb_pick.IsValid:
                try:
                    corners = rs.BoundingBox(objs)
                    if corners and len(corners) >= 7:
                        bb_pick = rg.BoundingBox(corners[0], corners[6])
                        # Use a mesh-from-box so containment test has geometry
                        bx_mesh = rg.Mesh.CreateFromBox(bb_pick, 1, 1, 1)
                        if bx_mesh:
                            self.bound_mesh = bx_mesh
                        self.lbl_status.Text = ("Extrusion/block objects: using bbox "
                                                "for containment.")
                except Exception as fb_ex:
                    print("Bbox fallback error: %s" % str(fb_ex))

            # ── Detect exact voxel cell size ──────────────────────────────
            # Priority 1: sc.sticky written by previous voxel script (exact).
            # Priority 2: mesh vertex spacing analysis (measured from geometry).
            # Priority 3: fall back to _auto_suggest_scale (3.2 m assumption).
            n_breps = len(self.brep_objs)
            n_meshes = 1 if self.bound_mesh else 0
            self.lbl_status.Text = ("Selected: %d brep(s)  %d mesh(es)" %
                                    (n_breps, n_meshes))

            detected = self._detect_cell_size_from_sticky()
            if not detected and self.bound_mesh:
                self.lbl_status.Text = "Measuring voxel size from mesh..."
                detected = self._detect_cell_size_from_mesh(self.bound_mesh, bb_pick)

            was_init = self._initialized
            self._initialized = False
            try:
                if detected and bb_pick.IsValid:
                    sx_d, sy_d, sz_d = detected
                    dx = bb_pick.Max.X - bb_pick.Min.X
                    dy = bb_pick.Max.Y - bb_pick.Min.Y
                    dz = bb_pick.Max.Z - bb_pick.Min.Z
                    nx = max(1, int(round(dx / sx_d)))
                    ny = max(1, int(round(dy / sy_d)))
                    nz = max(1, int(round(dz / sz_d)))
                    self.tb_fit_nx.Text = str(nx)
                    self.tb_fit_ny.Text = str(ny)
                    self.tb_fit_nz.Text = str(nz)
                    self.lbl_status.Text = ("Voxel size detected: "
                        "%.3f \xd7 %.3f \xd7 %.3f  →  %d\xd7%d\xd7%d cells"
                        % (sx_d, sy_d, sz_d, nx, ny, nz))
                else:
                    self._auto_suggest_scale(bb_pick)
                self.mode_combo.SelectedIndex = 1
            finally:
                self._initialized = was_init

            self._generate()

        except Exception as ex:
            import traceback
            self._show_front()
            self.lbl_status.Text = "Pick error: %s" % str(ex)
            traceback.print_exc()

    def on_pick_line(self, s, e):
        """Inline sun-line pick."""
        self._form.Visible = False
        Rhino.RhinoApp.SetFocusToMainWindow()

        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select a line for sun angle")
        go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
        go.EnablePreSelect(True, True)
        go.Get()

        self._show_front()
        if go.CommandResult() != Rhino.Commands.Result.Success:
            return

        line_id = go.Object(0).ObjectId
        self.line_id = line_id
        p1 = rs.CurveStartPoint(line_id)
        p2 = rs.CurveEndPoint(line_id)
        sv = rg.Vector3d(p1.X - p2.X, p1.Y - p2.Y, p1.Z - p2.Z)
        sv.Unitize()
        self.sun_vec = sv
        self.mode_combo.SelectedIndex = 3
        self.lbl_sun_pos.Text = "Custom line: (%.2f, %.2f, %.2f)" % (sv.X, sv.Y, sv.Z)
        self._generate()

    def on_load_sticky(self, s, e):
        """Load voxel grid dimensions from sc.sticky (written by previous run or upstream script)."""
        try:
            # Accept keys from this script's own export or from Climate Comfort Special V1
            grid_size = (sc.sticky.get("climate_grid_size") or
                         sc.sticky.get("ccs_grid_size"))
            cell_size = (sc.sticky.get("climate_cell_size") or
                         sc.sticky.get("ccs_cell_size"))
            origin    = (sc.sticky.get("climate_origin") or
                         sc.sticky.get("ccs_origin"))

            if not grid_size or not cell_size or not origin:
                self.lbl_status.Text = (
                    "No voxel data in sticky. Run base voxel script first.")
                return

            gx, gy, gz = int(grid_size[0]), int(grid_size[1]), int(grid_size[2])
            sx, sy, sz = float(cell_size[0]), float(cell_size[1]), float(cell_size[2])
            ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])

            if gx < 1 or gy < 1 or gz < 1 or sx <= 0 or sy <= 0 or sz <= 0:
                self.lbl_status.Text = "Sticky data looks invalid (zero/negative dims)."
                return

            # Suppress event cascade while updating textboxes
            was_init = self._initialized
            self._initialized = False
            try:
                self.tb_fit_nx.Text = str(gx)
                self.tb_fit_ny.Text = str(gy)
                self.tb_fit_nz.Text = str(gz)
                self.mode_combo.SelectedIndex = 1   # Brep/Geo mode
            finally:
                self._initialized = was_init

            # Build a bounding-box mesh that _get_bounds will use as containment
            mn = rg.Point3d(ox, oy, oz)
            mx_pt = rg.Point3d(ox + gx * sx, oy + gy * sy, oz + gz * sz)
            bb = rg.BoundingBox(mn, mx_pt)
            bx_mesh = rg.Mesh.CreateFromBox(bb, 1, 1, 1)
            self.bound_mesh = bx_mesh if (bx_mesh and bx_mesh.IsValid) else None
            self.brep_obj   = None      # mesh path only

            self.lbl_status.Text = ("Loaded sticky: %d\xd7%d\xd7%d cells  "
                                    "step %.2f\xd7%.2f\xd7%.2f" % (
                                    gx, gy, gz, sx, sy, sz))
            self._generate()

        except Exception as ex:
            import traceback
            self.lbl_status.Text = "Load sticky error: %s" % str(ex)
            traceback.print_exc()

    def on_bake(self, s, e):
        """Inline bake + close."""
        try:
            if not self.last_voxels:
                self._generate()
            v    = self.last_voxels
            h_p  = self.last_hot_peaks
            m_p  = self.last_mid_peaks
            c_p  = self.last_cool_peaks
            if v:
                self._clear_preview()
                mode, freq, thresh, sun_mult, sens, month_idx = self._read_params()
                mn, mx, nx, ny, nz, sx, sy, sz = self._get_bounds(
                    int(self.mode_combo.SelectedIndex))
                cf = dict(self._cf) if self._cf else self._get_cf(sens, month_idx)
                cf["best_seed"] = str(self._best_seed)
                bake_final(v, h_p, m_p, c_p, sx, sy, sz, mn, cf,
                           MONTH_NAMES[month_idx], nx, ny, nz)
                export_sticky(v, h_p, m_p, c_p, nx, ny, nz, sx, sy, sz, mn, cf)
                sc.doc.Views.Redraw()
                print("Baked %d voxels | attract: %dH %dM %dC" % (
                    len(v), len(h_p), len(m_p), len(c_p)))
            else:
                self.lbl_status.Text = "No voxels — run Generate first."
                return
        except Exception as ex:
            import traceback
            self.lbl_status.Text = "Bake error: %s" % str(ex)
            print("Bake error: %s" % str(ex))
            traceback.print_exc()
            return
        self._baked = True
        self._ensure_geo_visible()
        self._form.Close()

    def on_cancel(self, s, e):
        self._ensure_geo_visible()
        self._clear_preview()
        sc.doc.Views.Redraw()
        self._form.Close()

    def _on_closed(self, s, e):
        """Fired whenever the form is closed (including X button)."""
        self._ensure_geo_visible()
        # Disable conduit so markers disappear after the dialog closes
        try:
            self._attract_conduit.Enabled = False
            self._attract_conduit.clear()
        except: pass
        if not self._baked:
            self._clear_preview()
            sc.doc.Views.Redraw()
        # Release the sticky reference so the object can be GC'd normally
        try:
            if sc.sticky.get("__climate_v7__") is self:
                del sc.sticky["__climate_v7__"]
        except: pass

    def _show_front(self):
        """Make form visible and raise it in front of Rhino's window."""
        self._form.Visible = True
        try:
            self._form.BringToFront()
        except: pass
        try:
            self._form.Focus()
        except: pass

    # ── Geometry visibility ──
    def _ensure_geo_visible(self):
        if self._geo_hidden and self.site_obj_ids:
            try:
                rs.ShowObjects(self.site_obj_ids)
                sc.doc.Views.Redraw()
            except: pass
            self._geo_hidden = False
            self.btn_hide_geo.Text = "Hide Base Geo"

    def _on_toggle_geo(self, s, e):
        if not self.site_obj_ids:
            self.lbl_status.Text = "No geometry selected yet."
            return
        try:
            if self._geo_hidden:
                rs.ShowObjects(self.site_obj_ids)
                self._geo_hidden = False
                self.btn_hide_geo.Text = "Hide Base Geo"
            else:
                rs.HideObjects(self.site_obj_ids)
                self._geo_hidden = True
                self.btn_hide_geo.Text = "Show Base Geo"
            sc.doc.Views.Redraw()
        except Exception as ex:
            self.lbl_status.Text = "Toggle error: %s" % str(ex)

    # ── Preview ──
    def _clear_preview(self):
        """Clear voxel mesh + hide attractor conduit markers."""
        self._attract_conduit.clear()
        sc.doc.Views.Redraw()
        if self.preview_ids:
            try: rs.DeleteObjects(self.preview_ids)
            except: pass
            self.preview_ids = []

    # ── Attractor conduit helpers ──
    def _update_attractor_conduit(self, hot_p, mid_p, cool_p):
        """Push new peak lists into the conduit and request a redraw."""
        self._attract_conduit.update(hot_p, mid_p, cool_p, self._sz)
        sc.doc.Views.Redraw()

    def _rebuild_attractor_preview(self):
        """Recompute peaks from existing voxels, refresh conduit only.
        No voxel regen — instant feedback when density slider moves.
        """
        if not self.last_voxels:
            return
        spacing = int(self.sl_attract.Value)
        hot_p, mid_p, cool_p = find_zoned_peaks(self.last_voxels, spacing)
        self.last_hot_peaks  = hot_p
        self.last_mid_peaks  = mid_p
        self.last_cool_peaks = cool_p
        self.last_peaks      = hot_p + mid_p + cool_p
        self._update_attractor_conduit(hot_p, mid_p, cool_p)
        self.lbl_status.Text = ("Attractors: %dH %dM %dC  (spacing=%d)"
                                % (len(hot_p), len(mid_p), len(cool_p), spacing))

    def _on_attract_changed(self, s, e):
        """Density slider moved — update label and refresh conduit markers."""
        val = int(self.sl_attract.Value)
        self.lbl_attract_val.Text = str(val)
        self._rebuild_attractor_preview()

    # ── Single generation ──
    def _generate(self):
        if self._generating: return
        self._generating = True
        try:
            mode, freq, thresh, sun_mult, sens, month_idx = self._read_params()
            cf = self._get_cf(sens, month_idx)
            mn, mx, nx, ny, nz, sx, sy, sz = self._get_bounds(mode)

            total = nx * ny * nz
            if total > MAX_VOXELS:
                self.lbl_status.Text = "Grid too large (%d cells). Max is %d." % (total, MAX_VOXELS)
                return

            self.lbl_status.Text = "Generating %d×%d×%d..." % (nx, ny, nz)

            voxels = generate_voxels(
                mode, nx, ny, nz, freq, thresh, sun_mult,
                cf, self.perlin,
                brep_obj=self.brep_obj, bound_mesh=self.bound_mesh,
                brep_objs=self.brep_objs if self.brep_objs else None,
                sun_vec=self.sun_vec,
                min_pt=mn, max_pt=mx,
                step_x=sx, step_y=sy, step_z=sz,
                mesh_map_mode=int(self.mesh_mode_combo.SelectedIndex))

            spacing = int(self.sl_attract.Value)
            hot_p, mid_p, cool_p = find_zoned_peaks(voxels, spacing)
            self.last_voxels     = voxels
            self.last_hot_peaks  = hot_p
            self.last_mid_peaks  = mid_p
            self.last_cool_peaks = cool_p
            self.last_peaks      = hot_p + mid_p + cool_p
            self._cf = cf
            self._mn = mn

            # Persist detected step to sticky so next run uses fast sticky detection
            sc.sticky["climate_cell_size"] = (sx, sy, sz)
            sc.sticky["climate_grid_size"] = (nx, ny, nz)
            sc.sticky["climate_origin"]    = (mn.X, mn.Y, mn.Z)

            mesh = build_combined_mesh(voxels, sx, sy, sz)
            rs.EnableRedraw(False)
            self._clear_preview()
            if mesh.Vertices.Count > 0:
                oid = sc.doc.Objects.AddMesh(mesh)
                if oid: self.preview_ids.append(oid)
            self._update_attractor_conduit(hot_p, mid_p, cool_p)
            rs.EnableRedraw(True)
            sc.doc.Views.Redraw()

            self.lbl_status.Text = ("%s | %d voxels | attract: %dH %dM %dC"
                % (MONTH_NAMES[month_idx], len(voxels),
                   len(hot_p), len(mid_p), len(cool_p)))
            self._update_zone_bars(voxels)

        except Exception as ex:
            import traceback
            self.lbl_status.Text = "Error: %s" % str(ex)
            print("Generation error: %s" % str(ex))
            traceback.print_exc()
        finally:
            self._generating = False

    # ── Simulation ──
    def on_start_sim(self, s, e):
        if self._sim_running: return
        self._stop_sim    = False
        self._sim_running = True
        try:
            self._run_simulation()
        except Exception as ex:
            self._sim_guard_cleanup(ex)

    def _run_simulation(self):
        mode, freq, thresh, sun_mult, sens, month_idx = self._read_params()
        mn, mx, nx, ny, nz, sx, sy, sz = self._get_bounds(mode)
        cf  = self._get_cf(sens, month_idx)
        mmm = int(self.mesh_mode_combo.SelectedIndex)

        if nx * ny * nz > MAX_VOXELS:
            self.lbl_status.Text = "Grid too large for simulation (%d cells, max %d)." % (
                nx * ny * nz, MAX_VOXELS)
            self._sim_running = False
            return

        self.lbl_status.Text = "Computing containment mask..."
        Rhino.RhinoApp.Wait()

        self._sim_mask = compute_mask(
            mode, nx, ny, nz,
            self.brep_obj, self.bound_mesh,
            mn, sx, sy, sz, mmm,
            brep_objs=self.brep_objs if self.brep_objs else None)

        try:
            max_iter = max(1, int(self.tb_max_iter.Text))
        except:
            max_iter = 30

        stop_score = self.opt_stop.value
        hot_target = self.opt_hot.value
        mid_target = self.opt_mid.value
        mask       = self._sim_mask
        sweep_time = self.chk_opt_time.Checked
        month_for_sun = int(self.month_combo.SelectedIndex)

        self.btn_start_sim.Enabled = False
        self.btn_stop_sim.Enabled  = True
        self._sim_max_iter = max_iter
        self.pb_progress.update(0.0)
        self.lbl_progress.Text     = "0/%d  |  Best: --" % max_iter
        self.lbl_status.Text       = "Simulating (seed + threshold search)..."
        Rhino.RhinoApp.Wait()

        best_score  = -1.0
        best_voxels = []
        best_seed   = 42
        best_thresh = thresh
        best_hour   = float(self.sl_sun_hour.Value)

        # Threshold variants to try each iteration
        thresh_mults = [0.75, 0.875, 1.0, 1.125, 1.25]

        for idx in range(max_iter):
            if self._stop_sim: break

            seed = random.randint(0, 999999)
            try:
                pn = PerlinNoise(seed=seed)

                test_hours = ([float(h) for h in range(6, 19)]
                              if sweep_time
                              else [float(self.sl_sun_hour.Value)])

                for test_hour in test_hours:
                    if self._stop_sim: break
                    az, alt = solar_position(month_for_sun, test_hour)
                    test_sv = sun_vec_from_angles(az, alt) if alt > 0 else None

                    # Try multiple thresholds for this (seed, hour)
                    for tm in thresh_mults:
                        if self._stop_sim: break
                        test_thresh = max(0.05, min(0.90, thresh * tm))

                        voxels = generate_voxels(
                            mode, nx, ny, nz, freq, test_thresh, sun_mult,
                            cf, pn,
                            brep_obj=None, bound_mesh=None, sun_vec=test_sv,
                            min_pt=mn, max_pt=mx,
                            step_x=sx, step_y=sy, step_z=sz,
                            mesh_map_mode=mmm,
                            precomputed_mask=mask)

                        if not voxels: continue
                        score = compute_score(voxels, hot_target, mid_target)

                        if score > best_score:
                            best_score  = score
                            best_voxels = list(voxels)
                            best_seed   = seed
                            best_thresh = test_thresh
                            best_hour   = test_hour
                            self._update_preview_from_sim(
                                best_voxels, nx, ny, nz, sx, sy, sz)

                self._update_sim_progress(idx + 1, max_iter, best_score)
                Rhino.RhinoApp.Wait()

                if best_score >= stop_score:
                    break

            except Exception as ex:
                print("Sim iter %d error: %s" % (idx, str(ex)))
                continue

        # Apply best found parameters
        if best_thresh != thresh:
            best_thresh_sl = int(best_thresh * 100)
            best_thresh_sl = max(self.sl_thresh.MinValue,
                                 min(self.sl_thresh.MaxValue, best_thresh_sl))
            self.sl_thresh.Value = best_thresh_sl

        if sweep_time and best_score > 0:
            self.sl_sun_hour.Value = int(round(best_hour))
            self._compute_sun_position()

        self._sim_done(best_score, best_seed, best_thresh,
                       best_hour if sweep_time else None)
        self._best_seed   = best_seed
        self._best_thresh = best_thresh
        self.perlin       = PerlinNoise(seed=best_seed)
        self._sim_running = False

    def _sim_guard_cleanup(self, ex):
        """Called when on_start_sim itself throws (outside the per-iter try/except)."""
        import traceback
        self._sim_running = False
        try:
            self.btn_start_sim.Enabled = True
            self.btn_stop_sim.Enabled  = False
            self.lbl_status.Text = "Sim error: %s" % str(ex)
        except: pass
        traceback.print_exc()

    def on_stop_sim(self, s, e):
        self._stop_sim = True
        self.lbl_status.Text = "Stopping..."

    def _update_preview_from_sim(self, voxels, gx, gy, gz, sx, sy, sz):
        try:
            spacing = int(self.sl_attract.Value)
            hot_p, mid_p, cool_p = find_zoned_peaks(voxels, spacing)
            self.last_voxels     = voxels
            self.last_hot_peaks  = hot_p
            self.last_mid_peaks  = mid_p
            self.last_cool_peaks = cool_p
            self.last_peaks      = hot_p + mid_p + cool_p
            self._gx = gx; self._gy = gy; self._gz = gz
            self._sx = sx; self._sy = sy; self._sz = sz
            mesh = build_combined_mesh(voxels, sx, sy, sz)
            rs.EnableRedraw(False)
            self._clear_preview()
            if mesh.Vertices.Count > 0:
                oid = sc.doc.Objects.AddMesh(mesh)
                if oid: self.preview_ids.append(oid)
            self._update_attractor_conduit(hot_p, mid_p, cool_p)
            rs.EnableRedraw(True)
            sc.doc.Views.Redraw()
            self._update_zone_bars(voxels)
        except Exception as ex:
            print("Preview update error: %s" % str(ex))

    def _update_sim_progress(self, prog, max_iter, best_score):
        try:
            frac = prog / float(max_iter) if max_iter > 0 else 0.0
            self.pb_progress.update(frac)
            self.lbl_progress.Text = "%d/%d  |  Best: %.3f" % (prog, max_iter, best_score)
        except: pass

    def _sim_done(self, best_score, best_seed, best_thresh, best_hour=None):
        try:
            self.btn_start_sim.Enabled = True
            self.btn_stop_sim.Enabled  = False
            if best_hour is not None:
                self.lbl_status.Text = (
                    "Done! Seed=%d  Thresh=%.2f  Hour=%02d:00  Score=%.3f" %
                    (best_seed, best_thresh, int(round(best_hour)), best_score))
            else:
                self.lbl_status.Text = (
                    "Done! Seed=%d  Thresh=%.2f  Score=%.3f" %
                    (best_seed, best_thresh, best_score))
        except: pass


# =========================================================================
#  MAIN
# =========================================================================
def main():
    epw_path = find_epw_path()
    profiles = None
    if epw_path:
        profiles = normalise_profiles(parse_epw(epw_path))
        print("Loaded Melbourne EPW climate data.")
    else:
        print("EPW not found at default path. Select manually (optional).")
        fp = rs.OpenFileName("Select EPW file (optional)", "EPW (*.epw)|*.epw")
        if fp:
            profiles = normalise_profiles(parse_epw(fp))
            print("Loaded: " + fp)

    dialog = AttractorGUI(profiles)
    dialog._init_generate()

    # Keep a reference in sc.sticky so IronPython's GC does not collect the
    # Python wrapper after main() returns.  Without this, button-click handlers
    # (which are bound methods on the dialog object) would reference a collected
    # object and crash on first interaction.
    sc.sticky["__climate_v7__"] = dialog

    # Non-modal: Show() on the direct forms.Form() instance — viewport stays live.
    # Set Owner so the form stays above Rhino's main window in z-order,
    # then force it to the front so it doesn't open behind Rhino.
    try:
        dialog._form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    except: pass
    dialog._form.Show()
    try:
        dialog._form.BringToFront()
        dialog._form.Focus()
    except: pass


if __name__ == "__main__":
    main()
