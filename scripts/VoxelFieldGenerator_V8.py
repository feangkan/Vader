"""
VoxelFieldGenerator_V8.py
=========================
Production-quality 3D voxel field generator for Rhino 8 (CPython).
V8: Genuine EPW-hourly climate analysis — each daytime hour uses actual DNI (W/m²)
and dry-bulb temperature (°C) from the EPW file. Solar heat accumulation is
physically weighted by irradiance so June vs January produce meaningfully different
results. Zone classification via operative temperature thresholds in °C (not
percentile ranks). 13 field algorithms, 3 attractors.

Author: Claude / TECTONIC Research
Date: 2026-04-21
"""

import Rhino
import Rhino.Geometry as rg
import Rhino.Display as rd
import scriptcontext as sc
import System
import System.Drawing
import math
import random
import rhinoscriptsyntax as rs

try:
    import Eto.Forms as forms
    import Eto.Drawing as drawing
except:
    import Rhino.UI
    forms = Rhino.UI.EtoExtensions

# =============================================================================
# MATH UTILITIES
# =============================================================================

def clamp(v, lo, hi):
    """Clamp value between lo and hi."""
    if v < lo: return lo
    if v > hi: return hi
    return v

def lerp(a, b, t):
    """Linear interpolation."""
    return a + (b - a) * t

def remap(v, src_lo, src_hi, dst_lo, dst_hi):
    """Remap value from source range to destination range."""
    if abs(src_hi - src_lo) < 1e-12:
        return dst_lo
    t = (v - src_lo) / (src_hi - src_lo)
    return dst_lo + t * (dst_hi - dst_lo)

def smooth_step(e0, e1, x):
    """Hermite smooth step."""
    t = clamp((x - e0) / (e1 - e0 + 1e-12), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)

def falloff_linear(dist, radius):
    """Linear falloff: 1 at center, 0 at radius."""
    if radius < 1e-12: return 0.0
    return clamp(1.0 - dist / radius, 0.0, 1.0)

def falloff_gaussian(dist, radius):
    """Gaussian falloff."""
    if radius < 1e-12: return 0.0
    sigma = radius / 3.0
    return math.exp(-(dist * dist) / (2.0 * sigma * sigma))

def falloff_inverse(dist, radius):
    """Inverse-distance falloff."""
    if radius < 1e-12: return 0.0
    if dist < 1e-12: return 1.0
    return clamp(1.0 / (1.0 + (dist / radius) * 3.0), 0.0, 1.0)

def dist3d(a, b):
    """Euclidean distance between two 3-tuples."""
    dx = a[0] - b[0]; dy = a[1] - b[1]; dz = a[2] - b[2]
    return math.sqrt(dx*dx + dy*dy + dz*dz)

def dist_to_line_segment(pt, a, b):
    """Distance from point (tuple) to line segment a-b (tuples)."""
    abx = b[0]-a[0]; aby = b[1]-a[1]; abz = b[2]-a[2]
    apx = pt[0]-a[0]; apy = pt[1]-a[1]; apz = pt[2]-a[2]
    ab2 = abx*abx + aby*aby + abz*abz
    if ab2 < 1e-12:
        return dist3d(pt, a)
    t = (apx*abx + apy*aby + apz*abz) / ab2
    t = clamp(t, 0.0, 1.0)
    closest = (a[0]+t*abx, a[1]+t*aby, a[2]+t*abz)
    return dist3d(pt, closest)


def dist_to_curve(pt_tuple, curve):
    """Distance from a point (tuple) to a RhinoCommon curve using ClosestPoint."""
    pt3d = rg.Point3d(pt_tuple[0], pt_tuple[1], pt_tuple[2])
    rc, t = curve.ClosestPoint(pt3d)
    if rc:
        cp = curve.PointAt(t)
        return pt3d.DistanceTo(cp)
    return float('inf')


def dist_to_curves(pt_tuple, curves):
    """Minimum distance from a point (tuple) to a list of RhinoCommon curves."""
    min_d = float('inf')
    for crv in curves:
        d = dist_to_curve(pt_tuple, crv)
        if d < min_d:
            min_d = d
    return min_d


def closest_point_on_curves(pt_tuple, curves):
    """Return the closest point (as tuple) on any curve in the list."""
    pt3d = rg.Point3d(pt_tuple[0], pt_tuple[1], pt_tuple[2])
    best_pt = pt_tuple
    best_d = float('inf')
    for crv in curves:
        rc, t = crv.ClosestPoint(pt3d)
        if rc:
            cp = crv.PointAt(t)
            d = pt3d.DistanceTo(cp)
            if d < best_d:
                best_d = d
                best_pt = (cp.X, cp.Y, cp.Z)
    return best_pt

# =============================================================================
# PERLIN NOISE (classic gradient noise, inline implementation)
# =============================================================================

class PerlinNoise(object):
    """3D Perlin noise generator."""

    def __init__(self, seed=0):
        self.seed = seed
        rng = random.Random(seed)
        self.perm = list(range(256))
        rng.shuffle(self.perm)
        self.perm = self.perm + self.perm  # double for wrapping

        # 12 gradient directions
        self.grads = [
            (1,1,0),(-1,1,0),(1,-1,0),(-1,-1,0),
            (1,0,1),(-1,0,1),(1,0,-1),(-1,0,-1),
            (0,1,1),(0,-1,1),(0,1,-1),(0,-1,-1)
        ]

    def _fade(self, t):
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    def _grad(self, h, x, y, z):
        g = self.grads[h % 12]
        return g[0]*x + g[1]*y + g[2]*z

    def noise3d(self, x, y, z):
        """Evaluate 3D Perlin noise at (x,y,z). Returns value in [-1, 1]."""
        xi = int(math.floor(x)) & 255
        yi = int(math.floor(y)) & 255
        zi = int(math.floor(z)) & 255
        xf = x - math.floor(x)
        yf = y - math.floor(y)
        zf = z - math.floor(z)
        u = self._fade(xf)
        v = self._fade(yf)
        w = self._fade(zf)

        p = self.perm
        aaa = p[p[p[xi]+yi]+zi]
        aba = p[p[p[xi]+yi+1]+zi]
        aab = p[p[p[xi]+yi]+zi+1]
        abb = p[p[p[xi]+yi+1]+zi+1]
        baa = p[p[p[xi+1]+yi]+zi]
        bba = p[p[p[xi+1]+yi+1]+zi]
        bab = p[p[p[xi+1]+yi]+zi+1]
        bbb = p[p[p[xi+1]+yi+1]+zi+1]

        x1 = lerp(self._grad(aaa, xf, yf, zf), self._grad(baa, xf-1, yf, zf), u)
        x2 = lerp(self._grad(aba, xf, yf-1, zf), self._grad(bba, xf-1, yf-1, zf), u)
        y1 = lerp(x1, x2, v)
        x1 = lerp(self._grad(aab, xf, yf, zf-1), self._grad(bab, xf-1, yf, zf-1), u)
        x2 = lerp(self._grad(abb, xf, yf-1, zf-1), self._grad(bbb, xf-1, yf-1, zf-1), u)
        y2 = lerp(x1, x2, v)
        return lerp(y1, y2, w)

    def octave_noise(self, x, y, z, octaves=4, lacunarity=2.0, gain=0.5):
        """Fractal Brownian Motion (fBm) summing multiple octaves."""
        total = 0.0
        freq = 1.0
        amp = 1.0
        max_amp = 0.0
        for _ in range(octaves):
            total += self.noise3d(x*freq, y*freq, z*freq) * amp
            max_amp += amp
            freq *= lacunarity
            amp *= gain
        if max_amp > 0:
            total /= max_amp
        return total

# =============================================================================
# VALUE NOISE
# =============================================================================

class ValueNoise3D(object):
    """3D value noise using trilinear interpolation of random lattice values."""

    def __init__(self, seed=0):
        self.seed = seed
        rng = random.Random(seed)
        self.table = [rng.random() for _ in range(512)]

    def _hash(self, x, y, z):
        return (x * 73856093 ^ y * 19349663 ^ z * 83492791) & 511

    def noise3d(self, x, y, z):
        xi = int(math.floor(x)); yi = int(math.floor(y)); zi = int(math.floor(z))
        xf = x - xi; yf = y - yi; zf = z - zi
        u = smooth_step(0, 1, xf)
        v = smooth_step(0, 1, yf)
        w = smooth_step(0, 1, zf)

        t = self.table
        h = self._hash
        c000 = t[h(xi, yi, zi)]; c100 = t[h(xi+1, yi, zi)]
        c010 = t[h(xi, yi+1, zi)]; c110 = t[h(xi+1, yi+1, zi)]
        c001 = t[h(xi, yi, zi+1)]; c101 = t[h(xi+1, yi, zi+1)]
        c011 = t[h(xi, yi+1, zi+1)]; c111 = t[h(xi+1, yi+1, zi+1)]

        x0 = lerp(c000, c100, u); x1 = lerp(c010, c110, u)
        x2 = lerp(c001, c101, u); x3 = lerp(c011, c111, u)
        y0 = lerp(x0, x1, v); y1 = lerp(x2, x3, v)
        return lerp(y0, y1, w)

    def octave_noise(self, x, y, z, octaves=4, lacunarity=2.0, gain=0.5):
        total = 0.0; freq = 1.0; amp = 1.0; max_amp = 0.0
        for _ in range(octaves):
            total += self.noise3d(x*freq, y*freq, z*freq) * amp
            max_amp += amp; freq *= lacunarity; amp *= gain
        return total / max(max_amp, 1e-12)

# =============================================================================
# WORLEY NOISE
# =============================================================================

class WorleyNoise3D(object):
    """3D Worley (cellular) noise."""

    def __init__(self, seed=0, density=1):
        self.seed = seed
        self.density = density

    def _cell_points(self, cx, cy, cz):
        """Generate deterministic random points for a cell."""
        h = (cx * 73856093 ^ cy * 19349663 ^ cz * 83492791 ^ self.seed) & 0x7FFFFFFF
        rng = random.Random(h)
        pts = []
        for _ in range(self.density):
            pts.append((cx + rng.random(), cy + rng.random(), cz + rng.random()))
        return pts

    def noise3d(self, x, y, z, mode="f1"):
        """Evaluate Worley noise. mode: 'f1', 'f2', 'f2f1'."""
        xi = int(math.floor(x)); yi = int(math.floor(y)); zi = int(math.floor(z))
        dists = []
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                for dz in range(-1, 2):
                    for pt in self._cell_points(xi+dx, yi+dy, zi+dz):
                        d = dist3d((x, y, z), pt)
                        dists.append(d)
        dists.sort()
        f1 = dists[0] if len(dists) > 0 else 0.0
        f2 = dists[1] if len(dists) > 1 else 0.0
        if mode == "f1":
            return clamp(f1, 0.0, 1.0)
        elif mode == "f2":
            return clamp(f2, 0.0, 1.0)
        else:  # f2f1
            return clamp(f2 - f1, 0.0, 1.0)

# =============================================================================
# TPMS FUNCTIONS
# =============================================================================

def gyroid(x, y, z, period):
    """Gyroid triply-periodic minimal surface."""
    k = 2.0 * math.pi / period
    return math.sin(k*x) * math.cos(k*y) + math.sin(k*y) * math.cos(k*z) + math.sin(k*z) * math.cos(k*x)

def schwarz_p(x, y, z, period):
    """Schwarz P triply-periodic minimal surface."""
    k = 2.0 * math.pi / period
    return math.cos(k*x) + math.cos(k*y) + math.cos(k*z)

def schwarz_d(x, y, z, period):
    """Schwarz D (diamond) triply-periodic minimal surface."""
    k = 2.0 * math.pi / period
    a = math.sin(k*x) * math.sin(k*y) * math.sin(k*z)
    b = math.sin(k*x) * math.cos(k*y) * math.cos(k*z)
    c = math.cos(k*x) * math.sin(k*y) * math.cos(k*z)
    d = math.cos(k*x) * math.cos(k*y) * math.sin(k*z)
    return a + b + c + d

def lidinoid(x, y, z, period):
    """Lidinoid triply-periodic minimal surface."""
    k = 2.0 * math.pi / period
    s2x = math.sin(2*k*x); s2y = math.sin(2*k*y); s2z = math.sin(2*k*z)
    cx = math.cos(k*x); cy = math.cos(k*y); cz = math.cos(k*z)
    sx = math.sin(k*x); sy = math.sin(k*y); sz = math.sin(k*z)
    t1 = 0.5 * (s2x * cy * sz + s2y * cz * sx + s2z * cx * sy)
    t2 = 0.5 * (cx*cy + cy*cz + cz*cx)  # correction term for Lidinoid iso-surface
    # We use only t1 for a standard Lidinoid approximation
    return t1 - t2

# =============================================================================
# REACTION-DIFFUSION (Gray-Scott 3D)
# =============================================================================

def compute_reaction_diffusion(nx, ny, nz, feed, kill, steps, seed):
    """
    Compute 3D Gray-Scott reaction-diffusion.
    Returns a 3D list [ix][iy][iz] of float values (chemical B concentration).
    Capped at 20x20x20 for performance.
    """
    nx = min(nx, 20); ny = min(ny, 20); nz = min(nz, 20)

    rng = random.Random(seed)
    # Initialize grids A and B
    A = [[[1.0 for _ in range(nz)] for _ in range(ny)] for _ in range(nx)]
    B = [[[0.0 for _ in range(nz)] for _ in range(ny)] for _ in range(nx)]

    # Seed B with random patches
    num_seeds = max(1, (nx * ny * nz) // 50)
    for _ in range(num_seeds):
        sx = rng.randint(1, nx-2)
        sy = rng.randint(1, ny-2)
        sz = rng.randint(1, nz-2)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                for dz in range(-1, 2):
                    xi = clamp(sx+dx, 0, nx-1)
                    yi = clamp(sy+dy, 0, ny-1)
                    zi = clamp(sz+dz, 0, nz-1)
                    B[int(xi)][int(yi)][int(zi)] = 1.0

    dA = 1.0; dB = 0.5  # diffusion rates
    dt = 1.0

    for step in range(steps):
        newA = [[[0.0]*nz for _ in range(ny)] for _ in range(nx)]
        newB = [[[0.0]*nz for _ in range(ny)] for _ in range(nx)]
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    a = A[i][j][k]; b = B[i][j][k]
                    # 6-neighbor Laplacian
                    lapA = 0.0; lapB = 0.0
                    for di, dj, dk in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                        ni = (i+di) % nx; nj = (j+dj) % ny; nk = (k+dk) % nz
                        lapA += A[ni][nj][nk] - a
                        lapB += B[ni][nj][nk] - b
                    lapA /= 6.0; lapB /= 6.0
                    abb = a * b * b
                    newA[i][j][k] = a + (dA * lapA - abb + feed * (1.0 - a)) * dt
                    newB[i][j][k] = b + (dB * lapB + abb - (kill + feed) * b) * dt
                    newA[i][j][k] = clamp(newA[i][j][k], 0.0, 1.0)
                    newB[i][j][k] = clamp(newB[i][j][k], 0.0, 1.0)
        A = newA; B = newB

    return B

# =============================================================================
# CELLULAR AUTOMATA ENGINE
# =============================================================================

# --- CA PRESETS ---
# Each preset: {"family": str, "birth": set, "survival": set, "states": int,
#               "neighborhood": "moore"|"vn", "wrap": bool, ...}

CA_PRESETS = {
    # --- Life-like (2-state) ---
    "3D Life (5766)":       {"family": "life", "birth": {6}, "survival": {5,6,7}, "states": 2, "neighborhood": "moore"},
    "Life 4555":            {"family": "life", "birth": {4,5}, "survival": {5}, "states": 2, "neighborhood": "moore"},
    "Architecture (B3/S46)":{"family": "life", "birth": {3}, "survival": {4,6}, "states": 2, "neighborhood": "moore"},
    "Diamoeba 3D":          {"family": "life", "birth": {5,6,7,8}, "survival": {5,6,7,8}, "states": 2, "neighborhood": "moore"},
    "Sparse Life":          {"family": "life", "birth": {2}, "survival": {4,5}, "states": 2, "neighborhood": "moore"},

    # --- Generations (multi-state decay) ---
    "445":                  {"family": "generations", "birth": {4}, "survival": {4}, "states": 5, "neighborhood": "moore"},
    "Clouds":               {"family": "generations", "birth": {13,14,17,18,19}, "survival": set(range(13,27)), "states": 2, "neighborhood": "moore"},
    "Coral":                {"family": "generations", "birth": {6,7,9,12}, "survival": {5,6,7,8}, "states": 4, "neighborhood": "moore"},
    "Pyroclastic":          {"family": "generations", "birth": {6,7,8}, "survival": {4,5,6,7}, "states": 10, "neighborhood": "moore"},
    "Shells":               {"family": "generations", "birth": {3,6,8,9,11,14,15,16,17,19,24}, "survival": {3,5,7,9,11,15,17,19,21,23,24,26}, "states": 7, "neighborhood": "moore"},
    "Builder":              {"family": "generations", "birth": {4,6,8,9}, "survival": {2,6,9}, "states": 10, "neighborhood": "moore"},
    "Amoeba":               {"family": "generations", "birth": {5,6,7,12,13,15}, "survival": set(range(9,27)), "states": 5, "neighborhood": "moore"},
    "Slow Decay":           {"family": "generations", "birth": set(range(10,27)), "survival": set(range(13,27)), "states": 3, "neighborhood": "moore"},
    "Pulse Waves":          {"family": "generations", "birth": {1,2,3}, "survival": {3}, "states": 10, "neighborhood": "moore"},
    "Spiky Growth":         {"family": "generations", "birth": {4,6,8,9,10}, "survival": {5,6,7,8,9}, "states": 6, "neighborhood": "moore"},

    # --- Crystal Growth (Von Neumann) ---
    "Crystal Growth 1":     {"family": "generations", "birth": {1,3}, "survival": {0,1,2,3,4,5,6}, "states": 2, "neighborhood": "vn"},
    "Crystal Growth 2":     {"family": "generations", "birth": {1,3}, "survival": {1,2}, "states": 5, "neighborhood": "vn"},
    "Diamond Growth":       {"family": "generations", "birth": {1,2,3}, "survival": {5,6}, "states": 7, "neighborhood": "vn"},

    # --- Cyclic CA ---
    "Spiral-14 (VN)":      {"family": "cyclic", "range": 1, "threshold": 3, "colors": 14, "neighborhood": "vn"},
    "Spiral-86 (Edge)":    {"family": "cyclic", "range": 1, "threshold": 5, "colors": 86, "neighborhood": "moore"},
    "Spiral-128":          {"family": "cyclic", "range": 1, "threshold": 3, "colors": 128, "neighborhood": "moore"},
    "GH Waves":            {"family": "cyclic", "range": 1, "threshold": 2, "colors": 8, "neighborhood": "moore", "greenberg_hastings": True},

    # --- Stochastic ---
    "Eroded Life":         {"family": "stochastic", "birth": {6}, "survival": {5,6,7}, "states": 2, "neighborhood": "moore", "probability": 0.7},
    "Organic Growth":      {"family": "stochastic", "birth": {5,6,7}, "survival": {4,5,6,7,8}, "states": 3, "neighborhood": "moore", "probability": 0.85},
    "Porous Mass":         {"family": "stochastic", "birth": {4,5,6}, "survival": {3,4,5,6,7}, "states": 2, "neighborhood": "moore", "probability": 0.6},

    # --- DLA ---
    "Tree":                {"family": "dla", "particles": 5000, "stick_prob": 1.0},
    "Lightning":           {"family": "dla", "particles": 8000, "stick_prob": 0.6},
    "Dense Branch":        {"family": "dla", "particles": 12000, "stick_prob": 0.9},

    # --- Accretor ---
    "Mineral":             {"family": "accretor", "accretor_states": 3, "accretor_seed": 42},
    "Coral Mass":          {"family": "accretor", "accretor_states": 4, "accretor_seed": 137},
    "Pillar":              {"family": "accretor", "accretor_states": 2, "accretor_seed": 7},
}

CA_PRESET_NAMES = list(CA_PRESETS.keys())


class CellularAutomataEngine(object):
    """Runs 3D cellular automata on a voxel grid. Returns normalized float grid."""

    def __init__(self):
        self.preset_name = "445"
        self.steps = 15
        self.init_density = 0.3
        self.seed = 42
        self.wrap = True
        # Override params (used when user edits fields manually)
        self.birth = {4}
        self.survival = {4}
        self.states = 5
        self.neighborhood = "moore"
        self.probability = 1.0
        # Cyclic params
        self.ca_range = 1
        self.threshold = 3
        self.colors = 14
        self.greenberg_hastings = False
        # DLA params
        self.particles = 5000
        self.stick_prob = 1.0
        # Accretor params
        self.accretor_states = 3
        self.accretor_seed = 42

    def apply_preset(self, name):
        """Load a named preset into the engine parameters."""
        if name not in CA_PRESETS:
            return
        p = CA_PRESETS[name]
        self.preset_name = name
        fam = p.get("family", "life")
        self.neighborhood = p.get("neighborhood", "moore")
        self.birth = p.get("birth", set())
        self.survival = p.get("survival", set())
        self.states = p.get("states", 2)
        self.probability = p.get("probability", 1.0)
        self.ca_range = p.get("range", 1)
        self.threshold = p.get("threshold", 3)
        self.colors = p.get("colors", 14)
        self.greenberg_hastings = p.get("greenberg_hastings", False)
        self.particles = p.get("particles", 5000)
        self.stick_prob = p.get("stick_prob", 1.0)
        self.accretor_states = p.get("accretor_states", 3)
        self.accretor_seed = p.get("accretor_seed", 42)

    def get_family(self):
        if self.preset_name in CA_PRESETS:
            return CA_PRESETS[self.preset_name].get("family", "life")
        return "life"

    def _neighbors_moore(self, grid, i, j, k, nx, ny, nz):
        """Count state-1 neighbors in Moore neighborhood (26)."""
        count = 0
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for dk in (-1, 0, 1):
                    if di == 0 and dj == 0 and dk == 0:
                        continue
                    if self.wrap:
                        ni = (i + di) % nx; nj = (j + dj) % ny; nk = (k + dk) % nz
                    else:
                        ni = i + di; nj = j + dj; nk = k + dk
                        if ni < 0 or ni >= nx or nj < 0 or nj >= ny or nk < 0 or nk >= nz:
                            continue
                    if grid[ni][nj][nk] == 1:
                        count += 1
        return count

    def _neighbors_vn(self, grid, i, j, k, nx, ny, nz):
        """Count state-1 neighbors in Von Neumann neighborhood (6)."""
        count = 0
        for di, dj, dk in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            if self.wrap:
                ni = (i + di) % nx; nj = (j + dj) % ny; nk = (k + dk) % nz
            else:
                ni = i + di; nj = j + dj; nk = k + dk
                if ni < 0 or ni >= nx or nj < 0 or nj >= ny or nk < 0 or nk >= nz:
                    continue
            if grid[ni][nj][nk] == 1:
                count += 1
        return count

    def _count_alive(self, grid, i, j, k, nx, ny, nz):
        """Count alive (state==1) neighbors using current neighborhood setting."""
        if self.neighborhood == "vn":
            return self._neighbors_vn(grid, i, j, k, nx, ny, nz)
        return self._neighbors_moore(grid, i, j, k, nx, ny, nz)

    # --- LIFE-LIKE ---
    def _run_life(self, nx, ny, nz):
        rng = random.Random(self.seed)
        grid = [[[1 if rng.random() < self.init_density else 0
                   for _ in range(nz)] for _ in range(ny)] for _ in range(nx)]
        for step in range(self.steps):
            new = [[[0]*nz for _ in range(ny)] for _ in range(nx)]
            for i in range(nx):
                for j in range(ny):
                    for k in range(nz):
                        n = self._count_alive(grid, i, j, k, nx, ny, nz)
                        if grid[i][j][k] == 1:
                            new[i][j][k] = 1 if n in self.survival else 0
                        else:
                            new[i][j][k] = 1 if n in self.birth else 0
            grid = new
        return [[[float(grid[i][j][k]) for k in range(nz)]
                 for j in range(ny)] for i in range(nx)]

    # --- GENERATIONS ---
    def _run_generations(self, nx, ny, nz):
        rng = random.Random(self.seed)
        max_s = self.states
        grid = [[[1 if rng.random() < self.init_density else 0
                   for _ in range(nz)] for _ in range(ny)] for _ in range(nx)]
        for step in range(self.steps):
            new = [[[0]*nz for _ in range(ny)] for _ in range(nx)]
            for i in range(nx):
                for j in range(ny):
                    for k in range(nz):
                        cell = grid[i][j][k]
                        if cell == 0:
                            # Dead cell — check birth
                            n = self._count_alive(grid, i, j, k, nx, ny, nz)
                            if n in self.birth:
                                new[i][j][k] = 1
                            else:
                                new[i][j][k] = 0
                        elif cell == 1:
                            # Alive — check survival
                            n = self._count_alive(grid, i, j, k, nx, ny, nz)
                            if n in self.survival:
                                new[i][j][k] = 1
                            else:
                                new[i][j][k] = min(2, max_s - 1) if max_s > 2 else 0
                        else:
                            # Dying — advance toward death
                            new[i][j][k] = (cell + 1) % max_s
            grid = new
        # Normalize: state 1 = alive = 1.0, state 0 = dead = 0.0, dying = partial
        return [[[1.0 if grid[i][j][k] == 1 else
                  (0.3 if grid[i][j][k] > 1 else 0.0)
                  for k in range(nz)] for j in range(ny)] for i in range(nx)]

    # --- CYCLIC CA ---
    def _run_cyclic(self, nx, ny, nz):
        rng = random.Random(self.seed)
        c = self.colors
        grid = [[[rng.randint(0, c-1) for _ in range(nz)]
                 for _ in range(ny)] for _ in range(nx)]
        for step in range(self.steps):
            new = [[[0]*nz for _ in range(ny)] for _ in range(nx)]
            for i in range(nx):
                for j in range(ny):
                    for k in range(nz):
                        cur = grid[i][j][k]
                        successor = (cur + 1) % c
                        count = 0
                        # Count neighbors in successor state
                        for di in range(-self.ca_range, self.ca_range+1):
                            for dj in range(-self.ca_range, self.ca_range+1):
                                for dk in range(-self.ca_range, self.ca_range+1):
                                    if di == 0 and dj == 0 and dk == 0:
                                        continue
                                    if self.neighborhood == "vn":
                                        if abs(di) + abs(dj) + abs(dk) > self.ca_range:
                                            continue
                                    if self.wrap:
                                        ni = (i+di)%nx; nj = (j+dj)%ny; nk = (k+dk)%nz
                                    else:
                                        ni = i+di; nj = j+dj; nk = k+dk
                                        if ni<0 or ni>=nx or nj<0 or nj>=ny or nk<0 or nk>=nz:
                                            continue
                                    if grid[ni][nj][nk] == successor:
                                        count += 1
                        if self.greenberg_hastings:
                            if cur == 0:
                                new[i][j][k] = successor if count >= self.threshold else cur
                            else:
                                new[i][j][k] = successor
                        else:
                            new[i][j][k] = successor if count >= self.threshold else cur
            grid = new
        # Normalize to 0..1
        return [[[grid[i][j][k] / max(c - 1.0, 1.0) for k in range(nz)]
                 for j in range(ny)] for i in range(nx)]

    # --- STOCHASTIC ---
    def _run_stochastic(self, nx, ny, nz):
        rng = random.Random(self.seed)
        max_s = self.states
        prob = self.probability
        grid = [[[1 if rng.random() < self.init_density else 0
                   for _ in range(nz)] for _ in range(ny)] for _ in range(nx)]
        for step in range(self.steps):
            new = [[[0]*nz for _ in range(ny)] for _ in range(nx)]
            for i in range(nx):
                for j in range(ny):
                    for k in range(nz):
                        cell = grid[i][j][k]
                        n = self._count_alive(grid, i, j, k, nx, ny, nz)
                        if cell == 0:
                            if n in self.birth and rng.random() < prob:
                                new[i][j][k] = 1
                        elif cell == 1:
                            if n in self.survival and rng.random() < prob:
                                new[i][j][k] = 1
                            else:
                                new[i][j][k] = min(2, max_s-1) if max_s > 2 else 0
                        else:
                            new[i][j][k] = (cell + 1) % max_s
            grid = new
        return [[[1.0 if grid[i][j][k] == 1 else
                  (0.3 if grid[i][j][k] > 1 else 0.0)
                  for k in range(nz)] for j in range(ny)] for i in range(nx)]

    # --- DLA ---
    def _run_dla(self, nx, ny, nz):
        rng = random.Random(self.seed)
        grid = [[[0]*nz for _ in range(ny)] for _ in range(nx)]
        # Seed at center
        cx, cy, cz = nx//2, ny//2, nz//2
        grid[cx][cy][cz] = 1
        placed = 1
        max_particles = min(self.particles, nx*ny*nz // 2)
        attempts = 0
        max_attempts = max_particles * 200
        while placed < max_particles and attempts < max_attempts:
            attempts += 1
            # Launch particle from random edge
            face = rng.randint(0, 5)
            if face == 0: px, py, pz = 0, rng.randint(0,ny-1), rng.randint(0,nz-1)
            elif face == 1: px, py, pz = nx-1, rng.randint(0,ny-1), rng.randint(0,nz-1)
            elif face == 2: px, py, pz = rng.randint(0,nx-1), 0, rng.randint(0,nz-1)
            elif face == 3: px, py, pz = rng.randint(0,nx-1), ny-1, rng.randint(0,nz-1)
            elif face == 4: px, py, pz = rng.randint(0,nx-1), rng.randint(0,ny-1), 0
            else: px, py, pz = rng.randint(0,nx-1), rng.randint(0,ny-1), nz-1
            # Random walk
            for walk in range(nx + ny + nz):
                d = rng.randint(0, 5)
                if d == 0: px = min(px+1, nx-1)
                elif d == 1: px = max(px-1, 0)
                elif d == 2: py = min(py+1, ny-1)
                elif d == 3: py = max(py-1, 0)
                elif d == 4: pz = min(pz+1, nz-1)
                else: pz = max(pz-1, 0)
                # Check neighbors for attached cells
                has_neighbor = False
                for di,dj,dk in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                    ni,nj,nk = px+di, py+dj, pz+dk
                    if 0 <= ni < nx and 0 <= nj < ny and 0 <= nk < nz:
                        if grid[ni][nj][nk] == 1:
                            has_neighbor = True
                            break
                if has_neighbor and grid[px][py][pz] == 0:
                    if rng.random() < self.stick_prob:
                        grid[px][py][pz] = 1
                        placed += 1
                    break
        return [[[float(grid[i][j][k]) for k in range(nz)]
                 for j in range(ny)] for i in range(nx)]

    # --- ACCRETOR ---
    def _run_accretor(self, nx, ny, nz):
        rng = random.Random(self.accretor_seed)
        ns = self.accretor_states
        # Build rule table: for each state and neighbor-count → next state
        # 27 possible neighbor configs per state (0-26 alive neighbors)
        rule = [[rng.randint(0, ns-1) for _ in range(27)] for _ in range(ns)]
        grid = [[[0]*nz for _ in range(ny)] for _ in range(nx)]
        # Seed a small 3x3x3 block at center
        cx, cy, cz = nx//2, ny//2, nz//2
        for di in range(-1, 2):
            for dj in range(-1, 2):
                for dk in range(-1, 2):
                    si = cx+di; sj = cy+dj; sk = cz+dk
                    if 0 <= si < nx and 0 <= sj < ny and 0 <= sk < nz:
                        grid[si][sj][sk] = rng.randint(1, ns-1)
        for step in range(self.steps):
            new = [[[grid[i][j][k] for k in range(nz)] for j in range(ny)] for i in range(nx)]
            for i in range(nx):
                for j in range(ny):
                    for k in range(nz):
                        if grid[i][j][k] != 0:
                            continue
                        # Only grow at boundary (empty cell next to non-empty)
                        alive_count = 0
                        has_neighbor = False
                        for di in (-1, 0, 1):
                            for dj in (-1, 0, 1):
                                for dk in (-1, 0, 1):
                                    if di == 0 and dj == 0 and dk == 0:
                                        continue
                                    ni = i+di; nj = j+dj; nk = k+dk
                                    if 0 <= ni < nx and 0 <= nj < ny and 0 <= nk < nz:
                                        if grid[ni][nj][nk] > 0:
                                            alive_count += 1
                                            has_neighbor = True
                        if has_neighbor:
                            cur_state = 0
                            new[i][j][k] = rule[cur_state][min(alive_count, 26)]
            grid = new
        # Normalize: 0 = dead, any > 0 = alive (scaled by state)
        return [[[grid[i][j][k] / max(ns - 1.0, 1.0) for k in range(nz)]
                 for j in range(ny)] for i in range(nx)]

    def run(self, nx, ny, nz):
        """Run the CA and return 3D list of float values [0..1]."""
        nx = min(nx, 40); ny = min(ny, 40); nz = min(nz, 40)
        fam = self.get_family()
        if fam == "life":
            return self._run_life(nx, ny, nz)
        elif fam == "generations":
            return self._run_generations(nx, ny, nz)
        elif fam == "cyclic":
            return self._run_cyclic(nx, ny, nz)
        elif fam == "stochastic":
            return self._run_stochastic(nx, ny, nz)
        elif fam == "dla":
            return self._run_dla(nx, ny, nz)
        elif fam == "accretor":
            return self._run_accretor(nx, ny, nz)
        return self._run_life(nx, ny, nz)


# =============================================================================
# CLIMATE UTILITIES  (ported from melbourne_climate_voxel_attractor_V5.py)
# =============================================================================

SCA_LAYER_ROOT = "SCA_Branches"
DEFAULT_EPW = r"D:\RMIT_SEM1 26_AI Accelerated Agentic Architecture TECTONIC\Week 2\EPW file-Ladybug\AUS_VIC_Melbourne.RO.948680_TMYx.epw"


def parse_epw(filepath):
    """Parse EPW file → dict with hourly records per month + monthly summaries.

    Each hourly record: {"month": m, "hour": 0-23, "temp": °C,
                         "ghr": W/m², "dni": W/m², "dhi": W/m²}

    profiles[m] keys:
        "hourly"  — list of raw hourly records (month=m)
        "ghr"     — mean GHR W/m²       "ghr_n" — normalised 0-1
        "dnr"     — mean DNI W/m²       "dnr_n" — normalised 0-1
        "dhr"     — mean DHI W/m²       "dhr_n" — normalised 0-1
        "temp"    — mean dry-bulb °C    "temp_n" — normalised 0-1
    """
    monthly_hourly = {m: [] for m in range(1, 13)}
    try:
        with open(filepath, "r") as f:
            for line in f:
                if not line[0].isdigit():
                    continue
                parts = line.strip().split(",")
                if len(parts) < 35:
                    continue
                try:
                    m    = int(parts[1])
                    hour = int(parts[3]) - 1        # EPW 1-24 → 0-23
                    temp = float(parts[6])           # dry-bulb °C
                    ghr  = float(parts[13])          # GHR  W/m²
                    dni  = float(parts[14])          # DNI  W/m²
                    dhi  = float(parts[15])          # DHI  W/m²
                    monthly_hourly[m].append({
                        "month": m, "hour": hour,
                        "temp": temp, "ghr": ghr, "dni": dni, "dhi": dhi,
                    })
                except (ValueError, IndexError):
                    continue
    except IOError:
        return None

    profiles = {}
    all_ghr = []; all_dnr = []; all_dhr = []; all_tmp = []
    for m in range(1, 13):
        h = monthly_hourly[m]
        if not h:
            profiles[m] = {
                "hourly": [],
                "ghr": 0.0, "dnr": 0.0, "dhr": 0.0, "temp": 15.0,
                "ghr_n": 0.0, "dnr_n": 0.0, "dhr_n": 0.0, "temp_n": 0.5,
            }
            all_ghr.append(0.0); all_dnr.append(0.0)
            all_dhr.append(0.0); all_tmp.append(15.0)
            continue
        n = float(len(h))
        avg_ghr  = sum(r["ghr"]  for r in h) / n
        avg_dni  = sum(r["dni"]  for r in h) / n
        avg_dhi  = sum(r["dhi"]  for r in h) / n
        avg_temp = sum(r["temp"] for r in h) / n
        all_ghr.append(avg_ghr); all_dnr.append(avg_dni)
        all_dhr.append(avg_dhi); all_tmp.append(avg_temp)
        profiles[m] = {
            "hourly": h,
            "ghr": avg_ghr, "dnr": avg_dni, "dhr": avg_dhi, "temp": avg_temp,
        }

    # Normalise across months (kept for legacy algorithms that use ghr_n / temp_n)
    max_ghr = max(max(all_ghr), 1.0)
    max_dnr = max(max(all_dnr), 1.0)
    max_dhr = max(max(all_dhr), 1.0)
    tmp_lo  = min(all_tmp); tmp_hi = max(max(all_tmp), tmp_lo + 1.0)
    for m in range(1, 13):
        profiles[m]["ghr_n"]  = profiles[m]["ghr"]  / max_ghr
        profiles[m]["dnr_n"]  = profiles[m]["dnr"]  / max_dnr
        profiles[m]["dhr_n"]  = profiles[m]["dhr"]  / max_dhr
        profiles[m]["temp_n"] = (profiles[m]["temp"] - tmp_lo) / (tmp_hi - tmp_lo)

    return profiles


def get_climate_factors(profiles, month_index):
    """Compute amplitude/smoothness/height/dir_bias from parsed EPW profiles."""
    if month_index == 0:
        ghr = sum(profiles[m]["ghr_n"] for m in range(1, 13)) / 12.0
        dnr = sum(profiles[m]["dnr_n"] for m in range(1, 13)) / 12.0
        dhr = sum(profiles[m]["dhr_n"] for m in range(1, 13)) / 12.0
        tmp = sum(profiles[m]["temp_n"] for m in range(1, 13)) / 12.0
    else:
        p = profiles[month_index]
        ghr, dnr, dhr, tmp = p["ghr_n"], p["dnr_n"], p["dhr_n"], p["temp_n"]
    return {
        "amplitude":   0.3 + 0.7 * ghr,
        "smoothness":  1.0 - 0.5 * dhr,
        "height_mult": 0.3 + 0.7 * tmp,
        "dir_bias":    dnr * 0.3,
        "ghr_n": ghr, "dnr_n": dnr, "dhr_n": dhr, "tmp_n": tmp,
    }


def density_color(val):
    """Blue (cool) → Teal (mid) → Red (hot) gradient for climate density."""
    if val < 0.5:
        t = val / 0.5
        r = int(30 + t * 30); g = int(60 + t * 120); b = int(150 - t * 90)
    elif val < 0.75:
        t = (val - 0.5) / 0.25
        r = int(60 + t * 180); g = int(180 - t * 40); b = int(60 - t * 30)
    else:
        t = (val - 0.75) / 0.25
        r = int(240 - t * 20); g = int(140 - t * 90); b = int(30)
    return (max(30, min(255, r)), max(30, min(255, g)), max(30, min(255, b)))


def comfort_zone_color(zone):
    """Color per comfort zone classification (from Climate_Comfort_Agent_V2)."""
    return {
        "passive":     (60, 200, 80),
        "marginal":    (240, 200, 50),
        "hot_stagnant":(220, 50,  30),
        "overheated":  (200, 80,  20),
        "tunnel":      (255, 140,  0),
    }.get(zone, (180, 180, 180))


def load_comfort_json(filepath, metric="combined"):
    """Load comfort_field.json → (scores_dict, zones_dict).
    scores: {(ix,iy,iz): float 0..1}
    zones:  {(ix,iy,iz): str zone_name}
    """
    try:
        import json
        with open(filepath, "r") as f:
            data = json.load(f)
    except Exception:
        return {}, {}
    scores = {}
    zones = {}
    key_map = {
        "combined": "combined_score",
        "thermal":  "thermal_comfort",
        "daylight": "daylight_comfort",
        "airflow":  "airflow_comfort",
    }
    score_key = key_map.get(metric, "combined_score")
    for entry in data.get("comfort_grid", []):
        idx = entry.get("voxel_index", None)
        if idx and len(idx) == 3:
            key = tuple(idx)
            raw = entry.get(score_key, 50.0)
            scores[key] = clamp(raw / 100.0, 0.0, 1.0)
            zones[key] = entry.get("zone", None)
    return scores, zones


def collect_sca_curves():
    """Auto-scan SCA_Branches layers and return list of rg.NurbsCurve.
    Ported from Voxel_SCA_Integrator_V1.py."""
    curves = []
    for obj in sc.doc.Objects:
        if obj.IsDeleted:
            continue
        ln = sc.doc.Layers[obj.Attributes.LayerIndex].FullPath
        if SCA_LAYER_ROOT not in ln:
            continue
        geo = obj.Geometry
        if isinstance(geo, rg.Curve):
            nc = geo.ToNurbsCurve()
            if nc:
                curves.append(nc)
    return curves


# =============================================================================
# REAL SOLAR POSITION  (Spencer formula — ported from Climate_Comfort_Special_V1)
# =============================================================================

# Melbourne latitude & day-of-year table (mid-month representative days)
_MEL_LAT    = math.radians(-37.8136)   # South → negative
_MONTH_DOY  = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]

# Comfort zone appearance colours (RGB)
ZONE_RGB = {
    "passive":      (60,  200,  80),
    "marginal":     (240, 200,  50),
    "hot_stagnant": (220,  50,  30),
    "overheated":   (200,  80,  20),
    "tunnel":       (255, 140,   0),
}
ZONE_LABEL = {
    "passive":      "Passive  (good ventilation)",
    "marginal":     "Marginal (needs improvement)",
    "hot_stagnant": "Hot + Stagnant",
    "overheated":   "Overheated",
    "tunnel":       "Wind Tunnel",
}
ZONE_ORDER = ["passive", "marginal", "hot_stagnant", "overheated", "tunnel"]


def solar_position(month_idx, hour_float):
    """Return (azimuth_deg, altitude_deg) for Melbourne using Spencer declination.

    month_idx : 1-12 (1=Jan). 0 treated as June (peak summer).
    hour_float: solar time (12.0 = solar noon).
    Returns (azimuth_deg, altitude_deg) where azimuth 0°=North, clockwise.
    altitude_deg < 0 means sun below horizon.
    """
    if not (1 <= month_idx <= 12):
        month_idx = 6
    doy  = _MONTH_DOY[month_idx - 1]
    # Solar declination (Spencer 1971)
    decl = math.radians(23.45 * math.sin(math.radians(360.0 / 365.0 * (doy - 81))))
    # Hour angle: 15°/hour, negative in AM
    ha   = math.radians((hour_float - 12.0) * 15.0)
    lat  = _MEL_LAT
    sin_alt = (math.sin(lat) * math.sin(decl) +
               math.cos(lat) * math.cos(decl) * math.cos(ha))
    sin_alt = clamp(sin_alt, -1.0, 1.0)
    alt_rad = math.asin(sin_alt)
    cos_alt = math.cos(alt_rad)
    if abs(cos_alt) < 1e-9:
        return 180.0, math.degrees(alt_rad)
    cos_az = clamp(
        (math.sin(decl) - math.sin(lat) * math.sin(alt_rad)) / (math.cos(lat) * cos_alt),
        -1.0, 1.0)
    az_rad = math.acos(cos_az)
    if ha > 0:                       # Afternoon → west half
        az_rad = 2.0 * math.pi - az_rad
    return math.degrees(az_rad), math.degrees(alt_rad)


def sun_vec_from_angles(az_deg, alt_deg):
    """Unit vector pointing FROM scene TOWARD the sun.
    az_deg : 0=North, clockwise.  alt_deg : elevation above horizon.
    """
    az  = math.radians(az_deg)
    alt = math.radians(alt_deg)
    v = rg.Vector3d(
        math.sin(az) * math.cos(alt),   # East component
        math.cos(az) * math.cos(alt),   # North component
        math.sin(alt))                   # Up component
    v.Unitize()
    return v


# =============================================================================
# FIELD ENGINE
# =============================================================================

class FieldEngine(object):
    """Evaluates scalar fields for the voxel grid."""

    ALGORITHMS = [
        "perlin", "value_noise", "worley_f1", "worley_f2f1",
        "domain_warp", "gyroid", "schwarz_p", "schwarz_d",
        "lidinoid", "reaction_diff", "cellular_automata",
        "climate_epw", "comfort_json"
    ]

    def __init__(self):
        self.algorithm = "climate_epw"
        self.threshold = 0.0
        self.invert = False
        self.seed = 42
        self.octaves = 4
        self.frequency = 0.3
        self.lacunarity = 2.0
        self.gain = 0.5
        self.period = 8.0
        self.rd_feed = 0.055
        self.rd_kill = 0.062
        self.rd_steps = 20
        self._perlin = None
        self._value = None
        self._worley = None
        self._rd_grid = None
        self._ca_grid = None
        self.ca_engine = CellularAutomataEngine()
        # Climate EPW
        self.epw_path = DEFAULT_EPW
        self.epw_month = 0          # 0 = annual average
        self.sun_mult = 0.3
        self.z_decay_on = True
        self._epw_profiles = None
        self._epw_factors = None
        # Comfort JSON
        self.json_path = ""
        self.comfort_metric = "combined"
        self._comfort_field = {}    # (ix,iy,iz) → score 0..1
        self._comfort_zones = {}    # (ix,iy,iz) → zone name str
        self._nx = 0; self._ny = 0; self._nz = 0

    def rebuild(self, nx, ny, nz):
        """Reinitialize noise generators and precompute RD grid."""
        self._nx = nx; self._ny = ny; self._nz = nz
        self._perlin = PerlinNoise(self.seed)
        self._value = ValueNoise3D(self.seed)
        self._worley = WorleyNoise3D(self.seed)
        if self.algorithm == "reaction_diff":
            self._rd_grid = compute_reaction_diffusion(
                min(nx, 20), min(ny, 20), min(nz, 20),
                self.rd_feed, self.rd_kill, self.rd_steps, self.seed
            )
        else:
            self._rd_grid = None
        if self.algorithm == "cellular_automata":
            self.ca_engine.seed = self.seed
            self._ca_grid = self.ca_engine.run(nx, ny, nz)
        else:
            self._ca_grid = None
        if self.algorithm == "climate_epw":
            self._epw_profiles = parse_epw(self.epw_path)
            if self._epw_profiles:
                self._epw_factors = get_climate_factors(self._epw_profiles, self.epw_month)
                self._perlin = PerlinNoise(self.seed)
        if self.algorithm == "comfort_json":
            self._comfort_field, self._comfort_zones = load_comfort_json(self.json_path, self.comfort_metric)

    def evaluate(self, x, y, z, ix, iy, iz):
        """Evaluate the field at world coordinates (x,y,z) and grid indices (ix,iy,iz).
        Returns a float in [0, 1]."""
        alg = self.algorithm
        freq = self.frequency

        if alg == "perlin":
            raw = self._perlin.octave_noise(x*freq, y*freq, z*freq,
                                            self.octaves, self.lacunarity, self.gain)
            return clamp((raw + 1.0) * 0.5, 0.0, 1.0)

        elif alg == "value_noise":
            raw = self._value.octave_noise(x*freq, y*freq, z*freq,
                                           self.octaves, self.lacunarity, self.gain)
            return clamp(raw, 0.0, 1.0)

        elif alg == "worley_f1":
            return self._worley.noise3d(x*freq, y*freq, z*freq, mode="f1")

        elif alg == "worley_f2f1":
            return self._worley.noise3d(x*freq, y*freq, z*freq, mode="f2f1")

        elif alg == "domain_warp":
            warp_str = 2.0
            wx = self._perlin.noise3d(x*freq, y*freq, z*freq) * warp_str
            wy = self._perlin.noise3d(x*freq+5.2, y*freq+1.3, z*freq+7.1) * warp_str
            wz = self._perlin.noise3d(x*freq+9.7, y*freq+3.5, z*freq+2.8) * warp_str
            raw = self._perlin.octave_noise((x+wx)*freq, (y+wy)*freq, (z+wz)*freq,
                                            self.octaves, self.lacunarity, self.gain)
            return clamp((raw + 1.0) * 0.5, 0.0, 1.0)

        elif alg == "gyroid":
            raw = gyroid(x, y, z, self.period)
            return clamp(remap(raw, -3.0, 3.0, 0.0, 1.0), 0.0, 1.0)

        elif alg == "schwarz_p":
            raw = schwarz_p(x, y, z, self.period)
            return clamp(remap(raw, -3.0, 3.0, 0.0, 1.0), 0.0, 1.0)

        elif alg == "schwarz_d":
            raw = schwarz_d(x, y, z, self.period)
            return clamp(remap(raw, -4.0, 4.0, 0.0, 1.0), 0.0, 1.0)

        elif alg == "lidinoid":
            raw = lidinoid(x, y, z, self.period)
            return clamp(remap(raw, -2.0, 2.0, 0.0, 1.0), 0.0, 1.0)

        elif alg == "reaction_diff":
            if self._rd_grid is None:
                return 0.5
            rnx = min(self._nx, 20); rny = min(self._ny, 20); rnz = min(self._nz, 20)
            ri = clamp(ix, 0, rnx-1)
            rj = clamp(iy, 0, rny-1)
            rk = clamp(iz, 0, rnz-1)
            return clamp(self._rd_grid[ri][rj][rk], 0.0, 1.0)

        elif alg == "cellular_automata":
            if self._ca_grid is None:
                return 0.5
            ca_nx = len(self._ca_grid)
            ca_ny = len(self._ca_grid[0]) if ca_nx > 0 else 0
            ca_nz = len(self._ca_grid[0][0]) if ca_ny > 0 else 0
            ri = int(clamp(ix, 0, ca_nx - 1))
            rj = int(clamp(iy, 0, ca_ny - 1))
            rk = int(clamp(iz, 0, ca_nz - 1))
            return clamp(self._ca_grid[ri][rj][rk], 0.0, 1.0)

        elif alg == "climate_epw":
            if self._epw_factors is None or self._perlin is None:
                return 0.5
            f = self._epw_factors
            amp = f["amplitude"]
            dnr_n = f["dnr_n"]
            dir_bias = f["dir_bias"]
            freq = self.frequency
            gz_inv = 1.0 / max(self._nz - 1, 1)
            z_ratio = iz * gz_inv
            layer_amp = amp * (1.0 - z_ratio) + (0.5 + 0.5 * dnr_n) * z_ratio
            z_decay = (1.0 - z_ratio * 0.4) if self.z_decay_on else 1.0
            n_val = self._perlin.octave_noise(
                x * freq + dir_bias * y * 0.05,
                y * freq, z * freq, 4)
            n_val = (n_val + 1.0) * 0.5
            # Solar exposure: simple vertical + depth gradient
            gy_inv = 1.0 / max(self._ny - 1, 1)
            y_norm = iy * gy_inv
            exposure = y_norm * 0.5 + z_ratio * 0.5
            combined = n_val * layer_amp * z_decay + exposure * self.sun_mult
            return clamp(combined, 0.0, 1.0)

        elif alg == "comfort_json":
            if not self._comfort_field:
                return 0.5
            return self._comfort_field.get((ix, iy, iz), 0.0)

        return 0.5

    def is_alive(self, v):
        """Determine if a voxel is alive based on field value and threshold."""
        if self.invert:
            return v < self.threshold
        return v >= self.threshold

# =============================================================================
# VOXEL DATA
# =============================================================================

class Voxel(object):
    """Lightweight voxel data container."""
    __slots__ = ['index', 'center', 'scale', 'rotation_z', 'alive',
                 'field_value', 'attractor_influence', 'subdivided', '_was_alive',
                 'climate_zone']

    def __init__(self, index, center):
        self.index = index          # (i, j, k)
        self.center = center        # (x, y, z) world coords
        self.scale = 1.0
        self.rotation_z = 0.0
        self.alive = True
        self.field_value = 0.5
        self.attractor_influence = 0.0
        self.subdivided = False
        self._was_alive = True
        self.climate_zone = None    # set by comfort_json algorithm

# =============================================================================
# ATTRACTOR DATA
# =============================================================================

class AttractorData(object):
    """Stores parameters for one attractor.
    V2: 'curve' type uses a list of RhinoCommon Curve objects instead of line_start/end."""

    BEHAVIORS = ["remove", "scale", "rotate", "twist", "gravity", "noise_amplify"]
    FALLOFFS = ["linear", "gaussian", "inverse"]

    def __init__(self, label):
        self.label = label
        self.enabled = False
        self.type = "point"         # "point" or "curve"
        self.position = (0.0, 0.0, 0.0)
        self.curves = []            # list of rg.Curve objects
        self.radius = 5.0
        self.behavior = "remove"
        self.strength = 0.8
        self.falloff_type = "linear"
        self.invert = False  # False=affect inside radius, True=affect outside radius

    def get_distance(self, pt_tuple):
        """Distance from a point to this attractor."""
        if self.type == "point":
            return dist3d(pt_tuple, self.position)
        else:
            if self.curves:
                return dist_to_curves(pt_tuple, self.curves)
            return float('inf')

    def get_influence(self, pt_tuple):
        """Influence 0..1 based on distance and falloff.
        Always computes normal (inside-radius) influence.
        Invert is handled as a post-process swap in apply_attractors."""
        d = self.get_distance(pt_tuple)
        if d > self.radius:
            return 0.0
        if self.falloff_type == "linear":
            return falloff_linear(d, self.radius) * self.strength
        elif self.falloff_type == "gaussian":
            return falloff_gaussian(d, self.radius) * self.strength
        else:
            return falloff_inverse(d, self.radius) * self.strength

    def apply(self, voxel):
        """Apply attractor behavior to a voxel in-place."""
        inf = self.get_influence(voxel.center)
        if inf < 1e-6:
            return
        voxel.attractor_influence = max(voxel.attractor_influence, inf)

        if self.behavior == "remove":
            if inf > 0.5:
                voxel.alive = False

        elif self.behavior == "scale":
            voxel.scale = lerp(voxel.scale, 0.3, inf)
            if voxel.scale < 0.55:
                voxel.subdivided = True

        elif self.behavior == "rotate":
            voxel.rotation_z += inf * math.pi * 0.5

        elif self.behavior == "twist":
            height_factor = voxel.center[2] * 0.1
            voxel.rotation_z += inf * height_factor * math.pi * 0.25

        elif self.behavior == "gravity":
            # Pull voxel center toward attractor
            cx, cy, cz = voxel.center
            if self.type == "point":
                tx, ty, tz = self.position
            else:
                # Pull toward closest point on curves
                tx, ty, tz = closest_point_on_curves(voxel.center, self.curves) if self.curves else (cx, cy, cz)
            dx = tx - cx; dy = ty - cy; dz = tz - cz
            pull = inf * 0.3
            voxel.center = (cx + dx*pull, cy + dy*pull, cz + dz*pull)

        elif self.behavior == "noise_amplify":
            voxel.field_value = clamp(voxel.field_value * (1.0 + inf), 0.0, 1.0)

# =============================================================================
# ORIENTED BOUNDING BOX
# =============================================================================

def _compute_obb_plane(geom):
    """Find the Z-rotation that gives the tightest bounding box for geometry.
    Returns (plane, bbox_in_plane_coords).
    Tests rotations around Z every 2 degrees to minimize XY footprint."""
    aabb = geom.GetBoundingBox(True)
    centroid = aabb.Center
    best_plane = None
    best_vol = float('inf')
    best_bbox = None

    for deg in range(0, 180, 2):
        angle = math.radians(deg)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        plane = rg.Plane(centroid,
                         rg.Vector3d(cos_a, sin_a, 0),
                         rg.Vector3d(-sin_a, cos_a, 0))
        bbox = geom.GetBoundingBox(plane)
        dx = bbox.Max.X - bbox.Min.X
        dy = bbox.Max.Y - bbox.Min.Y
        dz = bbox.Max.Z - bbox.Min.Z
        vol = dx * dy * dz
        if vol < best_vol:
            best_vol = vol
            best_plane = plane
            best_bbox = bbox

    return best_plane, best_bbox


def _compute_obb_plane_multi(geom_list):
    """Find the Z-rotation that gives the tightest combined bounding box for
    a list of geometries. Returns (plane, combined_bbox_in_plane_coords)."""
    if len(geom_list) == 1:
        return _compute_obb_plane(geom_list[0])

    # Combined centroid from all geometries
    all_min = rg.Point3d(float('inf'), float('inf'), float('inf'))
    all_max = rg.Point3d(float('-inf'), float('-inf'), float('-inf'))
    for g in geom_list:
        bb = g.GetBoundingBox(True)
        all_min.X = min(all_min.X, bb.Min.X)
        all_min.Y = min(all_min.Y, bb.Min.Y)
        all_min.Z = min(all_min.Z, bb.Min.Z)
        all_max.X = max(all_max.X, bb.Max.X)
        all_max.Y = max(all_max.Y, bb.Max.Y)
        all_max.Z = max(all_max.Z, bb.Max.Z)
    centroid = rg.Point3d((all_min.X + all_max.X) * 0.5,
                          (all_min.Y + all_max.Y) * 0.5,
                          (all_min.Z + all_max.Z) * 0.5)

    best_plane = None
    best_vol = float('inf')
    best_bbox_min = None
    best_bbox_max = None

    for deg in range(0, 180, 2):
        angle = math.radians(deg)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        plane = rg.Plane(centroid,
                         rg.Vector3d(cos_a, sin_a, 0),
                         rg.Vector3d(-sin_a, cos_a, 0))
        # Union all local bboxes
        cmin_x = float('inf'); cmin_y = float('inf'); cmin_z = float('inf')
        cmax_x = float('-inf'); cmax_y = float('-inf'); cmax_z = float('-inf')
        for g in geom_list:
            bb = g.GetBoundingBox(plane)
            cmin_x = min(cmin_x, bb.Min.X); cmin_y = min(cmin_y, bb.Min.Y); cmin_z = min(cmin_z, bb.Min.Z)
            cmax_x = max(cmax_x, bb.Max.X); cmax_y = max(cmax_y, bb.Max.Y); cmax_z = max(cmax_z, bb.Max.Z)
        vol = (cmax_x - cmin_x) * (cmax_y - cmin_y) * (cmax_z - cmin_z)
        if vol < best_vol:
            best_vol = vol
            best_plane = plane
            best_bbox_min = (cmin_x, cmin_y, cmin_z)
            best_bbox_max = (cmax_x, cmax_y, cmax_z)

    # Build a BoundingBox from the best result
    combined = rg.BoundingBox(rg.Point3d(*best_bbox_min), rg.Point3d(*best_bbox_max))
    return best_plane, combined


def _plane_point_at_3d(plane, u, v, w):
    """Compute world point from local (u,v,w) coordinates in a plane frame."""
    o = plane.Origin
    xa = plane.XAxis
    ya = plane.YAxis
    za = plane.ZAxis
    return (o.X + u * xa.X + v * ya.X + w * za.X,
            o.Y + u * xa.Y + v * ya.Y + w * za.Y,
            o.Z + u * xa.Z + v * ya.Z + w * za.Z)


# =============================================================================
# VOXEL GRID
# =============================================================================

class VoxelGrid(object):
    """3D grid of voxels with field evaluation and mesh building."""

    def __init__(self, origin_tuple, voxel_size, nx, ny, nz, plane=None):
        self.origin = origin_tuple  # local-space origin offset (bbox min in plane coords)
        self.voxel_size = voxel_size
        self.nx = nx; self.ny = ny; self.nz = nz
        self.voxels = []
        self.plane = plane  # rg.Plane for oriented grids; None = world-axis-aligned

    def voxel_center(self, i, j, k):
        """World-space center of voxel at grid indices (i,j,k)."""
        ox, oy, oz = self.origin
        h = self.voxel_size * 0.5
        lx = ox + i * self.voxel_size + h
        ly = oy + j * self.voxel_size + h
        lz = oz + k * self.voxel_size + h

        if self.plane is not None:
            return _plane_point_at_3d(self.plane, lx, ly, lz)
        else:
            return (lx, ly, lz)

    def populate_full(self):
        """Fill the entire grid with voxels."""
        self.voxels = []
        for i in range(self.nx):
            for j in range(self.ny):
                for k in range(self.nz):
                    c = self.voxel_center(i, j, k)
                    self.voxels.append(Voxel((i, j, k), c))

    def populate_from_brep(self, brep):
        """Only create voxels whose centers lie inside the Brep."""
        self.populate_from_breps([brep])

    def populate_from_breps(self, brep_list):
        """Only create voxels whose centers lie inside ANY of the Breps."""
        self.voxels = []
        tol = sc.doc.ModelAbsoluteTolerance
        for i in range(self.nx):
            for j in range(self.ny):
                for k in range(self.nz):
                    c = self.voxel_center(i, j, k)
                    pt = rg.Point3d(c[0], c[1], c[2])
                    for brep in brep_list:
                        if brep.IsPointInside(pt, tol, False):
                            self.voxels.append(Voxel((i, j, k), c))
                            break

    def populate_from_mesh(self, mesh):
        """Only create voxels whose centers lie inside the Mesh."""
        self.populate_from_meshes([mesh])

    def populate_from_meshes(self, mesh_list):
        """Only create voxels whose centers lie inside ANY of the Meshes."""
        self.voxels = []
        for i in range(self.nx):
            for j in range(self.ny):
                for k in range(self.nz):
                    c = self.voxel_center(i, j, k)
                    pt = rg.Point3d(c[0], c[1], c[2])
                    for mesh in mesh_list:
                        if mesh.IsPointInside(pt, 0.001, False):
                            self.voxels.append(Voxel((i, j, k), c))
                            break

    def apply_field(self, engine):
        """Evaluate field for each voxel and cull by threshold."""
        engine.rebuild(self.nx, self.ny, self.nz)
        # climate_epw uses a real per-voxel solar analysis — bypass evaluate()
        if engine.algorithm == "climate_epw":
            self.apply_climate_field(engine)
            return
        is_comfort = (engine.algorithm == "comfort_json")
        for v in self.voxels:
            cx, cy, cz = v.center
            ix, iy, iz = v.index
            v.field_value = engine.evaluate(cx, cy, cz, ix, iy, iz)
            v.alive = engine.is_alive(v.field_value)
            if is_comfort:
                v.climate_zone = engine._comfort_zones.get(v.index, None)
        # Remove dead voxels
        self.voxels = [v for v in self.voxels if v.alive]

    def apply_climate_field(self, engine):
        """Genuine EPW-hourly climate analysis: per-voxel solar ray marching
        weighted by real DNI (W/m²) and dry-bulb temperature (°C) from the
        EPW file.

        METHODOLOGY
        ───────────
        1. Load actual hourly EPW records for the selected month (or full year).
           Each record carries real DNI (W/m²) and dry-bulb temp (°C).
        2. For each daytime hour (alt > 5°), compute a sun vector via Spencer
           algorithm and ray-march through the voxel grid.
           Solar gain accumulates as:  gain += DNI_i × exposed_i × sin(alt_i)
           (the sin(alt) factor approximates cosine of incidence on a flat roof).
        3. Per-voxel operative temperature (°C):
               op_temp = mean_ambient_temp
                       + (avg_solar_gain_W/m²) × SOLAR_TO_TEMP
                       + height_factor × HEIGHT_BOOST
        4. Heat-source diffusion: solar-exposed voxels lock their value;
           shaded/interior voxels absorb from warmer neighbours (5 iterations).
        5. Zone classification by operative temperature in °C — absolute thresholds
           so monthly differences are genuine (not just percentile re-scaling):
               < 26°C  → passive   (comfortable)
               26-30°C → marginal  (warm, needs ventilation)
               30-34°C → hot_stagnant (overheated + poor air movement)
               34-38°C → overheated
               > 38°C  → tunnel    (extreme solar exposure)
        6. field_value normalised to [0,1] for threshold/colour display.

        Melbourne (lat -37.8°): north-facing exterior voxels receive the most
        direct radiation and will always show as the hottest zone.

        Stores sc.sticky["vfg_climate_data"] for downstream scripts.
        """
        if not self.voxels:
            return

        profiles = engine._epw_profiles
        month    = engine.epw_month        # 0=annual, 1-12

        # ── Collect EPW hourly records for the analysis period ────────────────
        if not profiles:
            # No EPW file — fall back to synthetic vectors
            all_recs = []
        elif month == 0:
            all_recs = []
            for m in range(1, 13):
                all_recs.extend(profiles[m].get("hourly", []))
        else:
            all_recs = profiles[month].get("hourly", [])

        # ── Build sun_samples: (svx,svy,svz, dni, temp, sin_alt) ─────────────
        # Only daytime hours with sun above 5° AND meaningful DNI.
        # Downsample annual data by 3× to keep compute time <10 s.
        step = 3 if month == 0 else 1
        sun_samples = []
        for rec in all_recs[::step]:
            m_idx = rec.get("month", month if month > 0 else 6)
            hour  = float(rec["hour"]) + 0.5      # use mid-hour
            az, alt = solar_position(m_idx, hour)
            if alt <= 5.0:
                continue
            dni  = float(rec.get("dni", 0.0))
            temp = float(rec.get("temp", 15.0))
            sv   = sun_vec_from_angles(az, alt)
            sin_alt = max(0.05, math.sin(math.radians(alt)))
            sun_samples.append((sv.X, sv.Y, sv.Z, dni, temp, sin_alt))

        # Fallback if EPW has no valid daytime records
        if not sun_samples:
            # Use geometric sun vectors for Melbourne January (peak summer)
            for hour in range(7, 18):
                az, alt = solar_position(1, float(hour))
                if alt > 5.0:
                    sv = sun_vec_from_angles(az, alt)
                    sin_alt = max(0.05, math.sin(math.radians(alt)))
                    sun_samples.append((sv.X, sv.Y, sv.Z, 500.0, 26.0, sin_alt))

        # ── EPW statistics for the analysis period ────────────────────────────
        daytime_temps = [s[4] for s in sun_samples if s[3] > 50.0]
        mean_ambient  = (sum(daytime_temps) / len(daytime_temps)
                         if daytime_temps else 20.0)
        n_samples     = float(len(sun_samples)) if sun_samples else 1.0

        # ── Grid helpers ──────────────────────────────────────────────────────
        occupied = {v.index for v in self.voxels}
        iz_min = min(v.index[2] for v in self.voxels)
        iz_max = max(v.index[2] for v in self.voxels)
        iz_rng = float(max(1, iz_max - iz_min))

        # Physical constants
        # SOLAR_TO_TEMP: average W/m² of accumulated gain → °C rise above ambient.
        #   Melbourne north face January: avg DNI ~450 W/m², exposure ~0.7,
        #   sin(alt) ~0.5 → avg gain ~157 W/m² → ~+8°C rise → SOLAR_TO_TEMP=0.05
        SOLAR_TO_TEMP = 0.05
        HEIGHT_BOOST  = 2.0   # °C extra per full height span (warm air rises)

        # ── PASS 1: per-voxel solar gain + sky-view ───────────────────────────
        _solar_gain = {}   # index → average solar gain W/m²  (DNI-weighted)
        _solar_frac = {}   # index → fraction of sun-hours exposed (0-1)
        _skyview    = {}   # index → sky-view factor (0-1)

        for v in self.voxels:
            ix, iy, iz = v.index

            # Sky-view factor: fraction of 26 Moore neighbours that are empty
            empty_n = 0
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for dk in (-1, 0, 1):
                        if di == 0 and dj == 0 and dk == 0:
                            continue
                        if (ix + di, iy + dj, iz + dk) not in occupied:
                            empty_n += 1
            sv_frac = empty_n / 26.0

            # Ray march for each sun sample; accumulate DNI-weighted gain
            total_gain   = 0.0
            exposed_cnt  = 0
            for (svx, svy, svz, dni_i, _temp_i, sin_alt_i) in sun_samples:
                mag = math.sqrt(svx*svx + svy*svy + svz*svz) + 1e-9
                dx = svx / mag;  dy = svy / mag;  dz = svz / mag
                rx = float(ix) + dx * 0.6
                ry = float(iy) + dy * 0.6
                rz = float(iz) + dz * 0.6
                in_sun = True
                for _ in range(25):
                    ci = int(round(rx)); cj = int(round(ry)); ck = int(round(rz))
                    if (ci, cj, ck) in occupied:
                        in_sun = False
                        break
                    rx += dx;  ry += dy;  rz += dz
                if in_sun:
                    # Weight gain by actual DNI × sin(altitude)
                    total_gain  += dni_i * sin_alt_i
                    exposed_cnt += 1

            # Average gain per time step (W/m²)
            avg_gain     = total_gain  / n_samples
            exposure_frac = exposed_cnt / n_samples

            height_f = (iz - iz_min) / iz_rng

            # Operative temperature (°C) = ambient + solar heat + height boost
            op_temp = (mean_ambient
                       + avg_gain * SOLAR_TO_TEMP
                       + height_f * HEIGHT_BOOST)

            # Z-decay: optionally cool upper voxels (structural density bias)
            if engine.z_decay_on:
                op_temp -= height_f * 5.0

            _solar_gain[v.index] = avg_gain
            _solar_frac[v.index] = exposure_frac
            _skyview[v.index]    = sv_frac
            v.field_value        = op_temp   # °C at this stage

        # ── PASS 2: heat-source diffusion (same model as V7, now in °C) ───────
        # Voxels with meaningful solar gain are HEAT SOURCES — they keep their
        # temperature. Shaded interior voxels warm up from warmer neighbours.
        # This creates a physically correct gradient through building depth.
        SOLAR_SRC_THR  = 20.0   # W/m² avg gain → voxel is a solar source
        DIFFUSE_ITER   = 5
        DIFFUSE_WEIGHT = 0.35

        heat = {v.index: v.field_value for v in self.voxels}

        for _iter in range(DIFFUSE_ITER):
            new_heat = {}
            for v in self.voxels:
                ix, iy, iz = v.index
                is_source  = _solar_gain.get(v.index, 0.0) >= SOLAR_SRC_THR

                if is_source:
                    new_heat[v.index] = heat[v.index]   # lock temperature
                else:
                    nb_sum = 0.0; nb_cnt = 0
                    for di in (-1, 0, 1):
                        for dj in (-1, 0, 1):
                            for dk in (-1, 0, 1):
                                if di == 0 and dj == 0 and dk == 0:
                                    continue
                                nb = (ix + di, iy + dj, iz + dk)
                                if nb in heat:
                                    nb_sum += heat[nb]; nb_cnt += 1
                    nb_avg = nb_sum / nb_cnt if nb_cnt > 0 else 0.0
                    # Interior voxels can only warm up, never cool down
                    new_heat[v.index] = max(
                        heat[v.index],
                        heat[v.index] * (1.0 - DIFFUSE_WEIGHT) + nb_avg * DIFFUSE_WEIGHT)
            heat = new_heat

        for v in self.voxels:
            v.field_value = heat.get(v.index, v.field_value)

        # ── PASS 3: zone assignment (absolute °C thresholds) ──────────────────
        # Thresholds derived from Melbourne thermal comfort research.
        # They are ABSOLUTE, so summer (January) analysis will show more red than
        # winter (July) with the same geometry — the EPW data drives the result.
        #
        #   < 26°C             → passive      (comfort zone)
        #   26 - 30°C          → marginal     (warm, needs ventilation)
        #   30 - 34°C          → hot_stagnant (overheated + enclosed)
        #   34 - 38°C          → overheated
        #   > 38°C             → tunnel       (extreme solar exposure)
        ZONE_THRESHOLDS = [
            (38.0, "tunnel"),
            (34.0, "overheated"),
            (30.0, "hot_stagnant"),
            (26.0, "marginal"),
        ]

        for v in self.voxels:
            op_t = v.field_value
            sv   = _skyview.get(v.index, 0.5)

            zone = "passive"
            for thresh, z in ZONE_THRESHOLDS:
                if op_t >= thresh:
                    zone = z
                    break

            # Tunnel requires high sky_view (exposed corner, not enclosed)
            if zone == "tunnel" and sv < 0.50:
                zone = "overheated"

            v.climate_zone = zone

        # ── Normalise field_value to [0,1] for display / threshold slider ─────
        op_vals = [v.field_value for v in self.voxels]
        op_min  = min(op_vals);  op_max = max(op_vals)
        op_rng  = op_max - op_min if op_max > op_min else 1.0
        for v in self.voxels:
            v.field_value = (v.field_value - op_min) / op_rng

        # ── Threshold cull (by normalised field_value) ────────────────────────
        thr = engine.threshold
        self.voxels = [v for v in self.voxels if v.field_value >= thr]

        # ── Sticky export for downstream scripts ──────────────────────────────
        sticky_voxels = []
        for v in self.voxels:
            op_t_abs = op_min + v.field_value * op_rng   # back to °C
            sticky_voxels.append({
                "index":           list(v.index),
                "center":          [round(c, 3) for c in v.center],
                "heat_index":      round(v.field_value, 3),
                "operative_temp":  round(op_t_abs, 1),
                "zone":            v.climate_zone,
                "solar_gain_W":    round(_solar_gain.get(v.index, 0.0), 1),
                "exposure_frac":   round(_solar_frac.get(v.index, 0.0), 3),
                "sky_view":        round(_skyview.get(v.index, 0.0), 3),
            })
        sc.sticky["vfg_climate_data"] = {
            "algorithm":    "climate_epw",
            "month":        engine.epw_month,
            "mean_ambient": round(mean_ambient, 1),
            "n_sun_samples": len(sun_samples),
            "op_temp_min":  round(op_min, 1),
            "op_temp_max":  round(op_max, 1),
            "voxel_size":   self.voxel_size,
            "origin":       list(self.origin),
            "voxels":       sticky_voxels,
        }

    def apply_attractors(self, attractors_list):
        """Apply each enabled attractor to all living voxels.

        Invert logic (for 'remove' behavior):
            Normal:  attractor kills voxels inside radius  → positive space remains
            Invert:  SWAP — voxels that were killed become alive,
                     voxels that survived get killed → negative space remains
                     (the carved-out void becomes the solid)
        """
        for att in attractors_list:
            if not att.enabled:
                continue

            if att.invert and att.behavior == "remove":
                # Snapshot alive state before this attractor
                for v in self.voxels:
                    v._was_alive = v.alive
                # Apply normal remove
                for v in self.voxels:
                    att.apply(v)
                # Swap: killed ↔ survived
                for v in self.voxels:
                    if v._was_alive:
                        # Was alive before: if attractor killed it → revive (negative space)
                        # If attractor left it alive → kill it (was positive space)
                        v.alive = not v.alive
                    # voxels that were already dead stay dead

            elif att.invert and att.behavior != "remove":
                # For non-remove behaviors with invert: apply to voxels OUTSIDE radius
                for v in self.voxels:
                    d = att.get_distance(v.center)
                    if d > att.radius:
                        # Outside radius — apply behavior with uniform strength
                        old_inf_fn = att.get_influence
                        v.attractor_influence = max(v.attractor_influence, att.strength)
                        # Directly apply the behavior effect
                        if att.behavior == "scale":
                            v.scale = lerp(v.scale, 0.3, att.strength)
                            if v.scale < 0.55:
                                v.subdivided = True
                        elif att.behavior == "rotate":
                            v.rotation_z += att.strength * math.pi * 0.5
                        elif att.behavior == "twist":
                            height_factor = v.center[2] * 0.1
                            v.rotation_z += att.strength * height_factor * math.pi * 0.25
                        elif att.behavior == "gravity":
                            cx, cy, cz = v.center
                            if att.type == "point":
                                tx, ty, tz = att.position
                            else:
                                tx, ty, tz = closest_point_on_curves(v.center, att.curves) if att.curves else (cx, cy, cz)
                            dx = tx - cx; dy = ty - cy; dz = tz - cz
                            pull = att.strength * 0.3
                            v.center = (cx + dx*pull, cy + dy*pull, cz + dz*pull)
                        elif att.behavior == "noise_amplify":
                            v.field_value = clamp(v.field_value * (1.0 + att.strength), 0.0, 1.0)
            else:
                # Normal (no invert)
                for v in self.voxels:
                    att.apply(v)

        # Remove any killed voxels
        self.voxels = [v for v in self.voxels if v.alive]

    def build_mesh(self, color_mode, show_edges=True):
        """Build a single combined mesh from all living voxels with vertex colors."""
        mesh = rg.Mesh()

        # Pre-compute axes from plane (if oriented grid)
        axes = None
        if self.plane is not None:
            xa = self.plane.XAxis
            ya = self.plane.YAxis
            za = self.plane.ZAxis
            axes = ((xa.X, xa.Y, xa.Z), (ya.X, ya.Y, ya.Z), (za.X, za.Y, za.Z))

        # Precompute height range for "height" color mode
        if self.voxels:
            min_z = min(v.center[2] for v in self.voxels)
            max_z = max(v.center[2] for v in self.voxels)
            z_range = max_z - min_z if abs(max_z - min_z) > 1e-6 else 1.0
        else:
            min_z = 0.0; z_range = 1.0

        for v in self.voxels:
            half = self.voxel_size * 0.5 * v.scale

            # Determine color
            if color_mode == "climate_zone":
                zone = v.climate_zone   # set by climate_epw / comfort_json
                if zone is None:
                    # No climate data — fall back to field-value gradient
                    rgb = density_color(v.field_value)
                else:
                    rgb = ZONE_RGB.get(zone, (180, 180, 180))
                r_col, g_col, b_col = rgb[0], rgb[1], rgb[2]
            else:
                if color_mode == "field":
                    t = v.field_value
                elif color_mode == "influence":
                    t = v.attractor_influence
                elif color_mode == "height":
                    t = (v.center[2] - min_z) / z_range
                else:  # solid
                    t = 0.5
                rgb = density_color(t)
                r_col, g_col, b_col = rgb[0], rgb[1], rgb[2]

            _add_box(mesh, v.center[0], v.center[1], v.center[2],
                     half, v.rotation_z, r_col, g_col, b_col, axes)

            # Subdivided voxels: 8 children at half size
            if v.subdivided:
                sub_half = half * 0.5
                off = half * 0.5
                for dx in (-1, 1):
                    for dy in (-1, 1):
                        for dz in (-1, 1):
                            sx = v.center[0] + dx * off
                            sy = v.center[1] + dy * off
                            sz = v.center[2] + dz * off
                            _add_box(mesh, sx, sy, sz, sub_half,
                                     v.rotation_z, r_col, g_col, b_col, axes)

        mesh.Normals.ComputeNormals()
        mesh.Compact()
        return mesh

    def bake(self, color_mode, bake_legend=True, algorithm=None, voxel_count=0):
        """Bake voxel mesh + score legend + metadata into layered Rhino doc.

        For climate_epw / comfort_json algorithms:
          • VoxelField::Zone::<ZoneName>  — one mesh per comfort zone (zone colour)
          • VoxelField::Mesh              — full combined mesh (colour_mode colours)
          • VoxelField::ScoreLegend       — gradient/zone legend bar
          • VoxelField::Metadata          — text dot summary

        For all other algorithms:
          • VoxelField::Mesh, ScoreLegend, Metadata  (same as before)
        """
        if not self.voxels:
            return

        is_climate = algorithm in ("climate_epw", "comfort_json")

        # ── Layer hierarchy helper ────────────────────────────────────────────
        def _ensure_layer(full_path, color):
            idx = sc.doc.Layers.FindByFullPath(full_path, -1)
            if idx >= 0:
                return idx
            parts = full_path.split("::")
            parent_idx = -1
            for i, part in enumerate(parts):
                path = "::".join(parts[:i + 1])
                idx2 = sc.doc.Layers.FindByFullPath(path, -1)
                if idx2 < 0:
                    layer = Rhino.DocObjects.Layer()
                    layer.Name = part
                    layer.Color = color
                    if parent_idx >= 0:
                        layer.ParentLayerId = sc.doc.Layers[parent_idx].Id
                    idx2 = sc.doc.Layers.Add(layer)
                parent_idx = idx2
            return parent_idx

        gray   = System.Drawing.Color.FromArgb(200, 200, 200)
        yellow = System.Drawing.Color.FromArgb(220, 200,  50)
        teal   = System.Drawing.Color.FromArgb( 60, 180, 160)

        mesh_layer_idx   = _ensure_layer("VoxelField::Mesh",        gray)
        legend_layer_idx = _ensure_layer("VoxelField::ScoreLegend", teal)
        meta_layer_idx   = _ensure_layer("VoxelField::Metadata",    yellow)

        # ── Climate zone-separated layers ─────────────────────────────────────
        if is_climate:
            # Group voxels by zone
            zone_groups = {}
            for v in self.voxels:
                z = v.climate_zone or "marginal"
                zone_groups.setdefault(z, []).append(v)

            axes = None
            if self.plane is not None:
                xax = self.plane.XAxis
                yax = self.plane.YAxis
                zax = self.plane.ZAxis
                axes = ((xax.X, xax.Y, xax.Z), (yax.X, yax.Y, yax.Z), (zax.X, zax.Y, zax.Z))

            for zone_name in ZONE_ORDER:
                zvoxels = zone_groups.get(zone_name, [])
                if not zvoxels:
                    continue
                r_z, g_z, b_z = ZONE_RGB[zone_name]
                z_sys = System.Drawing.Color.FromArgb(r_z, g_z, b_z)
                safe_name = zone_name.replace("_", "").title()
                zone_layer_idx = _ensure_layer("VoxelField::Zone::{}".format(safe_name), z_sys)

                zmesh = rg.Mesh()
                for v in zvoxels:
                    half = self.voxel_size * 0.5 * v.scale
                    _add_box(zmesh, v.center[0], v.center[1], v.center[2],
                             half, v.rotation_z, r_z, g_z, b_z, axes)
                    if v.subdivided:
                        sub_half = half * 0.5; off = half * 0.5
                        for ddx in (-1, 1):
                            for ddy in (-1, 1):
                                for ddz in (-1, 1):
                                    _add_box(zmesh,
                                             v.center[0] + ddx * off,
                                             v.center[1] + ddy * off,
                                             v.center[2] + ddz * off,
                                             sub_half, v.rotation_z, r_z, g_z, b_z, axes)
                zmesh.Normals.ComputeNormals()
                zmesh.Compact()
                if zmesh.Vertices.Count > 0:
                    za = Rhino.DocObjects.ObjectAttributes()
                    za.LayerIndex = zone_layer_idx
                    sc.doc.Objects.AddMesh(zmesh, za)

        # ── Combined full mesh (colour_mode colours) ──────────────────────────
        mesh = self.build_mesh(color_mode)
        if mesh.Vertices.Count > 0:
            attr_mesh = Rhino.DocObjects.ObjectAttributes()
            attr_mesh.LayerIndex = mesh_layer_idx
            sc.doc.Objects.AddMesh(mesh, attr_mesh)

        # ── Score legend ─────────────────────────────────────────────────────
        if bake_legend and self.voxels:
            legend_mesh = rg.Mesh()
            lv = legend_mesh.Vertices; lf = legend_mesh.Faces; lc = legend_mesh.VertexColors
            # Bounding box of voxels for legend placement
            all_x = [v.center[0] for v in self.voxels]
            all_z = [v.center[2] for v in self.voxels]
            min_x = min(all_x); max_x = max(all_x)
            min_z = min(all_z); max_z = max(all_z)
            lx = min_x - self.voxel_size * 3.5
            by = (sum(v.center[1] for v in self.voxels) / len(self.voxels))
            oz = min_z
            lw = self.voxel_size * 0.8
            lh = (max_z - min_z) / 19.0 if max_z > min_z else self.voxel_size

            STEPS = 20
            alg = algorithm or ""
            # Both climate algorithms use zone-colour legend
            is_comfort = (alg in ("comfort_json", "climate_epw"))

            if is_comfort:
                zone_keys = ZONE_ORDER
                def step_color(v):
                    zi = min(int(v * len(zone_keys)), len(zone_keys) - 1)
                    return ZONE_RGB[zone_keys[zi]]
                label_entries = [
                    (0.00, "Passive  (good ventilation)"),
                    (0.20, "Marginal (needs improvement)"),
                    (0.40, "Hot + Stagnant"),
                    (0.60, "Overheated"),
                    (0.80, "Wind Tunnel"),
                    (1.00, "-- heat index scale 0\u21921 --"),
                ]
            else:
                def step_color(v):
                    return density_color(v)
                label_entries = [
                    (0.00, "0.00  Cool Zone"),
                    (0.25, "0.25  Low density"),
                    (0.50, "0.50  Mid Zone"),
                    (0.75, "0.75  Hot Zone"),
                    (1.00, "1.00  Peak"),
                ]

            for si in range(STEPS):
                val = float(si) / float(STEPS - 1)
                cr, cg, cb = step_color(val)
                col = System.Drawing.Color.FromArgb(cr, cg, cb)
                bz = oz + si * lh
                base = lv.Count
                lv.Add(lx,      by - lw * 0.5, bz)
                lv.Add(lx + lw, by - lw * 0.5, bz)
                lv.Add(lx + lw, by - lw * 0.5, bz + lh)
                lv.Add(lx,      by - lw * 0.5, bz + lh)
                for _ in range(4): lc.Add(col)
                lf.AddFace(base, base+1, base+2, base+3)

            legend_mesh.Normals.ComputeNormals()
            if legend_mesh.Vertices.Count > 0:
                attr_leg = Rhino.DocObjects.ObjectAttributes()
                attr_leg.LayerIndex = legend_layer_idx
                sc.doc.Objects.AddMesh(legend_mesh, attr_leg)

            # Text labels
            for val, txt in label_entries:
                tz = oz + val * (STEPS - 1) * lh
                td = rg.TextDot(txt, rg.Point3d(lx + lw * 1.3, by, tz))
                attr_td = Rhino.DocObjects.ObjectAttributes()
                attr_td.LayerIndex = legend_layer_idx
                sc.doc.Objects.AddTextDot(td, attr_td)

            if is_comfort:
                title = "CLIMATE ZONES\n{}\ngreen=passive  yellow=marginal\ndarkred=hot  orange=tunnel".format(alg)
            else:
                title = "SCORE BAR\n{}\nblue=low  teal=mid  red=high".format(alg)
            td_title = rg.TextDot(title, rg.Point3d(lx, by - self.voxel_size * 1.5, oz))
            attr_t = Rhino.DocObjects.ObjectAttributes(); attr_t.LayerIndex = legend_layer_idx
            sc.doc.Objects.AddTextDot(td_title, attr_t)

        # ── Metadata dot ─────────────────────────────────────────────────────
        if self.voxels:
            all_x2 = [v.center[0] for v in self.voxels]
            all_y2 = [v.center[1] for v in self.voxels]
            all_z2 = [v.center[2] for v in self.voxels]
            meta_pt = rg.Point3d(
                (min(all_x2) + max(all_x2)) * 0.5,
                (min(all_y2) + max(all_y2)) * 0.5,
                max(all_z2) + self.voxel_size * 1.5)
            import datetime
            meta_txt = "Algorithm: {}\nVoxels: {}\nGenerated: {}".format(
                algorithm or "unknown", voxel_count,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
            td_meta = rg.TextDot(meta_txt, meta_pt)
            attr_m = Rhino.DocObjects.ObjectAttributes(); attr_m.LayerIndex = meta_layer_idx
            sc.doc.Objects.AddTextDot(td_meta, attr_m)

        sc.doc.Views.Redraw()


def _add_box(mesh, cx, cy, cz, half_size, rot_z, r, g, b, axes=None):
    """Add an oriented box (8 verts, 6 quad faces) to the mesh.
    axes: tuple of ((xx,xy,xz), (yx,yy,yz), (zx,zy,zz)) grid orientation.
    If None, uses world-aligned with rot_z around Z."""
    h = half_size
    if axes is not None:
        xa, ya, za = axes
        # Apply attractor rot_z as additional rotation around the local Z axis
        if abs(rot_z) > 1e-9:
            cos_r = math.cos(rot_z); sin_r = math.sin(rot_z)
            rxa = (xa[0]*cos_r + ya[0]*sin_r, xa[1]*cos_r + ya[1]*sin_r, xa[2]*cos_r + ya[2]*sin_r)
            rya = (-xa[0]*sin_r + ya[0]*cos_r, -xa[1]*sin_r + ya[1]*cos_r, -xa[2]*sin_r + ya[2]*cos_r)
            xa = rxa; ya = rya
    else:
        cos_r = math.cos(rot_z); sin_r = math.sin(rot_z)
        xa = (cos_r, sin_r, 0.0)
        ya = (-sin_r, cos_r, 0.0)
        za = (0.0, 0.0, 1.0)

    corners_local = [
        (-h, -h, -h), (h, -h, -h), (h, h, -h), (-h, h, -h),
        (-h, -h,  h), (h, -h,  h), (h, h,  h), (-h, h,  h)
    ]
    base = mesh.Vertices.Count
    for lx, ly, lz in corners_local:
        wx = cx + lx*xa[0] + ly*ya[0] + lz*za[0]
        wy = cy + lx*xa[1] + ly*ya[1] + lz*za[1]
        wz = cz + lx*xa[2] + ly*ya[2] + lz*za[2]
        mesh.Vertices.Add(rg.Point3d(wx, wy, wz))
    # 6 quad faces
    for f in [(0,1,2,3), (4,7,6,5), (0,4,5,1), (1,5,6,2), (2,6,7,3), (3,7,4,0)]:
        mesh.Faces.AddFace(base+f[0], base+f[1], base+f[2], base+f[3])
    for _ in range(8):
        mesh.VertexColors.Add(r, g, b)

# =============================================================================
# DISPLAY CONDUIT
# =============================================================================

class VoxelConduit(rd.DisplayConduit):
    """Real-time display conduit for voxel preview."""

    def __init__(self):
        super(VoxelConduit, self).__init__()
        self.mesh = None
        self.show_edges = True
        self.edge_color = System.Drawing.Color.FromArgb(40, 40, 40)
        self.use_vertex_colors = True
        self.shaded_material = rd.DisplayMaterial()
        self.attractor_spheres = []    # list of (rg.Sphere, color)
        self.attractor_curves = []     # list of (rg.Curve, color) for V2
        self.bound_lines = []
        self.bound_color = System.Drawing.Color.FromArgb(80, 80, 80)
        self.show_bounds = True

    def CalculateBoundingBox(self, e):
        if self.mesh and self.mesh.Vertices.Count > 0:
            e.IncludeBoundingBox(self.mesh.GetBoundingBox(False))
        for ln in self.bound_lines:
            bb = ln.BoundingBox
            e.IncludeBoundingBox(bb)
        for (sp, col) in self.attractor_spheres:
            e.IncludeBoundingBox(sp.BoundingBox)

    def PostDrawObjects(self, e):
        if self.mesh and self.mesh.Vertices.Count > 0:
            if self.use_vertex_colors:
                e.Display.DrawMeshFalseColors(self.mesh)
            else:
                e.Display.DrawMeshShaded(self.mesh, self.shaded_material)
            if self.show_edges:
                e.Display.DrawMeshWires(self.mesh, self.edge_color)
        if self.show_bounds:
            for ln in self.bound_lines:
                e.Display.DrawLine(ln, self.bound_color, 1)
        for (sp, col) in self.attractor_spheres:
            e.Display.DrawSphere(sp, col, 1)
        for (crv, col) in self.attractor_curves:
            e.Display.DrawCurve(crv, col, 3)

# =============================================================================
# DIALOG
# =============================================================================

class VoxelFieldDialog(forms.Form):
    """Main 4-tab dialog for the Voxel Field Generator."""

    def __init__(self):
        super(VoxelFieldDialog, self).__init__()
        self.Title = "Voxel Field Generator V7"
        self.Padding = drawing.Padding(8)
        self.Resizable = True
        self.MinimumSize = drawing.Size(520, 620)
        self.Size = drawing.Size(540, 680)

        # State
        self.engine = FieldEngine()
        self.attractors = [AttractorData("A"), AttractorData("B"), AttractorData("C")]
        self.conduit = VoxelConduit()
        self.conduit.Enabled = True
        self._grid = None
        self._picked_breps = []
        self._picked_meshes = []
        self._attractor_pts = [None, None, None]
        self._attractor_curves = [[], [], []]  # V2: list of rg.Curve per attractor
        self.color_mode = "field"

        self._compute_dirty = False
        self._display_dirty = False
        self._live_preview = True

        # Build UI
        self._build_ui()

        # Timer
        self._timer = forms.UITimer()
        self._timer.Interval = 0.12
        self._timer.Elapsed += self._on_timer_tick
        self._timer.Start()

        self.Closed += self._on_closed

    # -------------------------------------------------------------------------
    # UI HELPERS
    # -------------------------------------------------------------------------

    def _float_slider(self, layout, name, lo, hi, default, on_change):
        lbl = forms.Label(); lbl.Text = name; lbl.Width = 105
        sld = forms.Slider()
        sld.MinValue = 0; sld.MaxValue = 1000
        sld.Value = int((default - lo) / (hi - lo) * 1000)
        txt = forms.TextBox(); txt.Text = "{:.3f}".format(default); txt.Width = 50
        guard = {"u": False}

        def _sld(s, e):
            if guard["u"]: return
            guard["u"] = True
            fv = lo + (sld.Value / 1000.0) * (hi - lo)
            txt.Text = "{:.3f}".format(fv)
            guard["u"] = False
            on_change()

        def _txt(s, e):
            if guard["u"]: return
            guard["u"] = True
            try:
                fv = float(txt.Text)
                clamped = max(lo, min(hi, fv))
                sld.Value = int((clamped - lo) / (hi - lo) * 1000)
            except:
                pass
            guard["u"] = False
            on_change()

        sld.ValueChanged += _sld
        txt.TextChanged += _txt
        row = forms.TableLayout()
        row.Spacing = drawing.Size(4, 0)
        row.Rows.Add(forms.TableRow(
            forms.TableCell(lbl, False),
            forms.TableCell(sld, True),
            forms.TableCell(txt, False)
        ))
        layout.AddRow(row)
        sld.Tag = row   # store row so _update_field_visibility can hide label+slider together
        return sld, txt

    def _int_slider(self, layout, name, lo, hi, default, on_change):
        lbl = forms.Label(); lbl.Text = name; lbl.Width = 105
        sld = forms.Slider(); sld.MinValue = lo; sld.MaxValue = hi; sld.Value = default
        txt = forms.TextBox(); txt.Text = str(default); txt.Width = 50
        guard = {"u": False}

        def _sld(s, e):
            if guard["u"]: return
            guard["u"] = True
            txt.Text = str(sld.Value)
            guard["u"] = False
            on_change()

        def _txt(s, e):
            if guard["u"]: return
            guard["u"] = True
            try:
                v = int(txt.Text)
                if lo <= v <= hi:
                    sld.Value = v
            except:
                pass
            guard["u"] = False
            on_change()

        sld.ValueChanged += _sld
        txt.TextChanged += _txt
        row = forms.TableLayout()
        row.Spacing = drawing.Size(4, 0)
        row.Rows.Add(forms.TableRow(
            forms.TableCell(lbl, False),
            forms.TableCell(sld, True),
            forms.TableCell(txt, False)
        ))
        layout.AddRow(row)
        sld.Tag = row   # store row so _update_field_visibility can hide label+slider together
        return sld, txt

    # -------------------------------------------------------------------------
    # BUILD UI
    # -------------------------------------------------------------------------

    def _build_ui(self):
        main_layout = forms.DynamicLayout()
        main_layout.DefaultSpacing = drawing.Size(4, 4)
        main_layout.Padding = drawing.Padding(4)

        tabs = forms.TabControl()

        # --- TAB 1: GRID ---
        tab_grid = forms.TabPage(); tab_grid.Text = "Grid"
        gl = forms.DynamicLayout()
        gl.DefaultSpacing = drawing.Size(4, 4)
        gl.Padding = drawing.Padding(6)

        # Mode — use DropDown (CPython Eto RadioButton grouping is unreliable)
        _lbl_mode = forms.Label(); _lbl_mode.Text = "Populate Mode:"
        gl.AddRow(_lbl_mode)
        self.dd_mode = forms.DropDown()
        self.dd_mode.Items.Add("Standalone")
        self.dd_mode.Items.Add("From Brep")
        self.dd_mode.Items.Add("From Mesh")
        self.dd_mode.SelectedIndex = 0
        self.dd_mode.SelectedIndexChanged += lambda s, e: self._mark_compute()
        gl.AddRow(self.dd_mode)

        # Pick buttons
        pick_row = forms.DynamicLayout()
        pick_row.DefaultSpacing = drawing.Size(4, 0)
        self.btn_pick_brep = forms.Button(); self.btn_pick_brep.Text = "Pick Breps"
        self.btn_pick_brep.Click += self._on_pick_brep
        self.btn_pick_mesh = forms.Button(); self.btn_pick_mesh.Text = "Pick Meshes"
        self.btn_pick_mesh.Click += self._on_pick_mesh
        self.btn_clear_geom = forms.Button(); self.btn_clear_geom.Text = "Clear"
        self.btn_clear_geom.Click += self._on_clear_geometry
        pick_row.AddRow(self.btn_pick_brep, self.btn_pick_mesh, self.btn_clear_geom, None)
        gl.AddRow(pick_row)
        self.lbl_picked = forms.Label(); self.lbl_picked.Text = "No geometry picked"
        gl.AddRow(self.lbl_picked)

        _lbl_sp = forms.Label(); _lbl_sp.Text = ""
        gl.AddRow(_lbl_sp)  # spacer

        # Grid size sliders
        self.sld_nx, self.txt_nx = self._int_slider(gl, "Grid X", 2, 30, 10, self._mark_compute)
        self.sld_ny, self.txt_ny = self._int_slider(gl, "Grid Y", 2, 30, 10, self._mark_compute)
        self.sld_nz, self.txt_nz = self._int_slider(gl, "Grid Z", 2, 20, 8, self._mark_compute)
        self.sld_vsize, self.txt_vsize = self._float_slider(gl, "Voxel Size", 0.1, 5.0, 2.0, self._mark_compute)

        _lbl_origin = forms.Label(); _lbl_origin.Text = "Origin: world 0, 0, 0"
        gl.AddRow(_lbl_origin)
        gl.AddRow(None)  # spacer to push content up
        tab_grid.Content = gl
        tabs.Pages.Add(tab_grid)

        # --- TAB 2: FIELD ---
        tab_field = forms.TabPage(); tab_field.Text = "Field"
        fl = forms.DynamicLayout()
        fl.DefaultSpacing = drawing.Size(4, 4)
        fl.Padding = drawing.Padding(6)

        _lbl_alg = forms.Label(); _lbl_alg.Text = "Algorithm:"
        fl.AddRow(_lbl_alg)
        self.dd_algorithm = forms.DropDown()
        for a in FieldEngine.ALGORITHMS:
            self.dd_algorithm.Items.Add(a)
        # Default to climate_epw
        _default_alg = "climate_epw"
        _alg_idx = FieldEngine.ALGORITHMS.index(_default_alg) if _default_alg in FieldEngine.ALGORITHMS else 0
        self.dd_algorithm.SelectedIndex = _alg_idx
        self.dd_algorithm.SelectedIndexChanged += self._on_algorithm_changed
        fl.AddRow(self.dd_algorithm)

        self.sld_threshold, self.txt_threshold = self._float_slider(fl, "Threshold", 0.0, 1.0, 0.0, self._mark_compute)

        self.chk_invert = forms.CheckBox(); self.chk_invert.Text = "Invert"
        self.chk_invert.CheckedChanged += lambda s, e: self._mark_compute()
        fl.AddRow(self.chk_invert)

        # Octaves (for perlin/value_noise/domain_warp)
        self.lbl_octaves_header = forms.Label(); self.lbl_octaves_header.Text = "Noise Parameters:"
        fl.AddRow(self.lbl_octaves_header)
        self.sld_octaves, self.txt_octaves = self._int_slider(fl, "Octaves", 1, 8, 4, self._mark_compute)
        self.sld_freq, self.txt_freq = self._float_slider(fl, "Frequency", 0.01, 2.0, 0.3, self._mark_compute)

        # Period (for TPMS)
        self.lbl_period_header = forms.Label(); self.lbl_period_header.Text = "TPMS Period:"
        fl.AddRow(self.lbl_period_header)
        self.sld_period, self.txt_period = self._float_slider(fl, "Period", 1.0, 20.0, 8.0, self._mark_compute)

        # RD params
        self.lbl_rd_header = forms.Label(); self.lbl_rd_header.Text = "Reaction-Diffusion:"
        fl.AddRow(self.lbl_rd_header)
        self.sld_rd_feed, self.txt_rd_feed = self._float_slider(fl, "RD Feed", 0.01, 0.1, 0.055, self._mark_compute)
        self.sld_rd_kill, self.txt_rd_kill = self._float_slider(fl, "RD Kill", 0.01, 0.1, 0.062, self._mark_compute)
        self.sld_rd_steps, self.txt_rd_steps = self._int_slider(fl, "RD Steps", 5, 50, 20, self._mark_compute)

        # Seed
        seed_row = forms.DynamicLayout()
        seed_row.DefaultSpacing = drawing.Size(4, 0)
        seed_lbl = forms.Label(); seed_lbl.Text = "Seed:"; seed_lbl.Width = 105
        self.txt_seed = forms.TextBox(); self.txt_seed.Text = "42"; self.txt_seed.Width = 60
        self.txt_seed.TextChanged += lambda s, e: self._mark_compute()
        seed_row.AddRow(seed_lbl, self.txt_seed, None)
        fl.AddRow(seed_row)

        # ── Climate EPW controls ─────────────────────────────────────────────
        self.lbl_epw_header = forms.Label(); self.lbl_epw_header.Text = "Climate EPW Settings:"
        fl.AddRow(self.lbl_epw_header)

        epw_row = forms.DynamicLayout(); epw_row.DefaultSpacing = drawing.Size(4, 0)
        self.txt_epw_path = forms.TextBox(); self.txt_epw_path.Text = DEFAULT_EPW; self.txt_epw_path.Width = 200
        self.txt_epw_path.TextChanged += lambda s, e: self._mark_compute()
        self.btn_epw_browse = forms.Button(); self.btn_epw_browse.Text = "Browse…"
        self.btn_epw_browse.Click += self._on_epw_browse
        epw_row.AddRow(self.txt_epw_path, self.btn_epw_browse, None)
        fl.AddRow(epw_row)

        month_row = forms.DynamicLayout(); month_row.DefaultSpacing = drawing.Size(4, 0)
        self.lbl_epw_month = forms.Label(); self.lbl_epw_month.Text = "Month:"; self.lbl_epw_month.Width = 50
        self.dd_epw_month = forms.DropDown()
        for m in ["Annual Avg", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]:
            self.dd_epw_month.Items.Add(m)
        self.dd_epw_month.SelectedIndex = 0
        self.dd_epw_month.SelectedIndexChanged += lambda s, e: self._mark_compute()
        month_row.AddRow(self.lbl_epw_month, self.dd_epw_month, None)
        fl.AddRow(month_row)

        self.sld_sun_weight, self.txt_sun_weight = self._float_slider(
            fl, "Sun Weight", 0.0, 1.0, 0.3, self._mark_compute)

        self.chk_z_decay = forms.CheckBox(); self.chk_z_decay.Text = "Z Decay (denser at base)"
        self.chk_z_decay.Checked = True
        self.chk_z_decay.CheckedChanged += lambda s, e: self._mark_compute()
        fl.AddRow(self.chk_z_decay)

        # ── Comfort JSON controls ────────────────────────────────────────────
        self.lbl_json_header = forms.Label(); self.lbl_json_header.Text = "Comfort JSON Settings:"
        fl.AddRow(self.lbl_json_header)

        json_row = forms.DynamicLayout(); json_row.DefaultSpacing = drawing.Size(4, 0)
        self.txt_json_path = forms.TextBox(); self.txt_json_path.Text = ""; self.txt_json_path.Width = 200
        self.txt_json_path.TextChanged += lambda s, e: self._mark_compute()
        self.btn_json_browse = forms.Button(); self.btn_json_browse.Text = "Browse…"
        self.btn_json_browse.Click += self._on_json_browse
        json_row.AddRow(self.txt_json_path, self.btn_json_browse, None)
        fl.AddRow(json_row)

        metric_row = forms.DynamicLayout(); metric_row.DefaultSpacing = drawing.Size(4, 0)
        self.lbl_json_metric = forms.Label(); self.lbl_json_metric.Text = "Metric:"; self.lbl_json_metric.Width = 50
        self.dd_json_metric = forms.DropDown()
        for m in ["combined", "thermal", "daylight", "airflow"]:
            self.dd_json_metric.Items.Add(m)
        self.dd_json_metric.SelectedIndex = 0
        self.dd_json_metric.SelectedIndexChanged += lambda s, e: self._mark_compute()
        metric_row.AddRow(self.lbl_json_metric, self.dd_json_metric, None)
        fl.AddRow(metric_row)

        fl.AddRow(None)
        tab_field.Content = fl
        tabs.Pages.Add(tab_field)

        self._update_field_visibility()

        # --- TAB 3: CA RULES ---
        tab_ca = forms.TabPage(); tab_ca.Text = "CA Rules"
        cal = forms.DynamicLayout()
        cal.DefaultSpacing = drawing.Size(4, 4)
        cal.Padding = drawing.Padding(6)

        _lbl_ca_info = forms.Label(); _lbl_ca_info.Text = "Select 'cellular_automata' in Field tab to use"
        cal.AddRow(_lbl_ca_info)

        # Preset dropdown
        _lbl_preset = forms.Label(); _lbl_preset.Text = "Preset:"
        cal.AddRow(_lbl_preset)
        self.dd_ca_preset = forms.DropDown()
        for pn in CA_PRESET_NAMES:
            self.dd_ca_preset.Items.Add(pn)
        self.dd_ca_preset.SelectedIndex = 1  # "445" default
        self.dd_ca_preset.SelectedIndexChanged += self._on_ca_preset_changed
        cal.AddRow(self.dd_ca_preset)

        # Family label (read-only, updated by preset)
        self.lbl_ca_family = forms.Label(); self.lbl_ca_family.Text = "Family: generations"
        cal.AddRow(self.lbl_ca_family)

        # Birth / Survival text fields
        birth_row = forms.DynamicLayout(); birth_row.DefaultSpacing = drawing.Size(4, 0)
        _lbl_b = forms.Label(); _lbl_b.Text = "Birth:"; _lbl_b.Width = 60
        self.txt_ca_birth = forms.TextBox(); self.txt_ca_birth.Text = "4"
        self.txt_ca_birth.TextChanged += lambda s, e: self._mark_compute()
        birth_row.AddRow(_lbl_b, self.txt_ca_birth, None)
        cal.AddRow(birth_row)

        surv_row = forms.DynamicLayout(); surv_row.DefaultSpacing = drawing.Size(4, 0)
        _lbl_s = forms.Label(); _lbl_s.Text = "Survival:"; _lbl_s.Width = 60
        self.txt_ca_survival = forms.TextBox(); self.txt_ca_survival.Text = "4"
        self.txt_ca_survival.TextChanged += lambda s, e: self._mark_compute()
        surv_row.AddRow(_lbl_s, self.txt_ca_survival, None)
        cal.AddRow(surv_row)

        # States, Steps, Init Density
        self.sld_ca_states, self.txt_ca_states = self._int_slider(cal, "States", 2, 20, 5, self._mark_compute)
        self.sld_ca_steps, self.txt_ca_steps = self._int_slider(cal, "Steps", 1, 60, 15, self._mark_compute)
        self.sld_ca_density, self.txt_ca_density = self._float_slider(cal, "Init Density", 0.01, 0.8, 0.3, self._mark_compute)

        # Neighborhood
        nb_row = forms.DynamicLayout(); nb_row.DefaultSpacing = drawing.Size(4, 0)
        _lbl_nb = forms.Label(); _lbl_nb.Text = "Neighborhood:"; _lbl_nb.Width = 90
        self.dd_ca_neighborhood = forms.DropDown()
        self.dd_ca_neighborhood.Items.Add("Moore (26)")
        self.dd_ca_neighborhood.Items.Add("Von Neumann (6)")
        self.dd_ca_neighborhood.SelectedIndex = 0
        self.dd_ca_neighborhood.SelectedIndexChanged += lambda s, e: self._mark_compute()
        nb_row.AddRow(_lbl_nb, self.dd_ca_neighborhood, None)
        cal.AddRow(nb_row)

        # Wrap edges
        self.chk_ca_wrap = forms.CheckBox(); self.chk_ca_wrap.Text = "Wrap Edges"
        self.chk_ca_wrap.Checked = True
        self.chk_ca_wrap.CheckedChanged += lambda s, e: self._mark_compute()
        cal.AddRow(self.chk_ca_wrap)

        # --- Cyclic CA params ---
        self.lbl_ca_cyclic = forms.Label(); self.lbl_ca_cyclic.Text = "--- Cyclic CA ---"
        cal.AddRow(self.lbl_ca_cyclic)
        self.sld_ca_range, self.txt_ca_range = self._int_slider(cal, "Range", 1, 3, 1, self._mark_compute)
        self.sld_ca_threshold, self.txt_ca_threshold = self._int_slider(cal, "Threshold", 1, 10, 3, self._mark_compute)
        self.sld_ca_colors, self.txt_ca_colors = self._int_slider(cal, "Colors", 3, 128, 14, self._mark_compute)
        self.chk_ca_gh = forms.CheckBox(); self.chk_ca_gh.Text = "Greenberg-Hastings"
        self.chk_ca_gh.Checked = False
        self.chk_ca_gh.CheckedChanged += lambda s, e: self._mark_compute()
        cal.AddRow(self.chk_ca_gh)

        # --- DLA params ---
        self.lbl_ca_dla = forms.Label(); self.lbl_ca_dla.Text = "--- DLA ---"
        cal.AddRow(self.lbl_ca_dla)
        self.sld_ca_particles, self.txt_ca_particles = self._int_slider(cal, "Particles", 100, 15000, 5000, self._mark_compute)
        self.sld_ca_stick, self.txt_ca_stick = self._float_slider(cal, "Stick Prob", 0.1, 1.0, 1.0, self._mark_compute)

        # --- Stochastic params ---
        self.lbl_ca_stoch = forms.Label(); self.lbl_ca_stoch.Text = "--- Stochastic ---"
        cal.AddRow(self.lbl_ca_stoch)
        self.sld_ca_prob, self.txt_ca_prob = self._float_slider(cal, "Probability", 0.1, 1.0, 0.8, self._mark_compute)

        # --- Accretor params ---
        self.lbl_ca_accretor = forms.Label(); self.lbl_ca_accretor.Text = "--- Accretor ---"
        cal.AddRow(self.lbl_ca_accretor)
        self.sld_ca_acc_states, self.txt_ca_acc_states = self._int_slider(cal, "Acc States", 2, 5, 3, self._mark_compute)

        cal.AddRow(None)
        tab_ca.Content = cal
        tabs.Pages.Add(tab_ca)

        self._update_ca_visibility()

        # --- TAB 4: ATTRACTORS ---
        tab_att = forms.TabPage(); tab_att.Text = "Attractors"
        al = forms.DynamicLayout()
        al.DefaultSpacing = drawing.Size(4, 4)
        al.Padding = drawing.Padding(6)

        # Store UI widgets per attractor
        self._att_widgets = []
        for idx in range(3):
            self._build_attractor_panel(al, idx)
            if idx < 2:
                _sep = forms.Label(); _sep.Text = "---"
                al.AddRow(_sep)  # separator

        al.AddRow(None)
        tab_att.Content = al
        tabs.Pages.Add(tab_att)

        # --- TAB 4: DISPLAY ---
        tab_disp = forms.TabPage(); tab_disp.Text = "Display"
        dl = forms.DynamicLayout()
        dl.DefaultSpacing = drawing.Size(4, 4)
        dl.Padding = drawing.Padding(6)

        _lbl_cm = forms.Label(); _lbl_cm.Text = "Color Mode:"
        dl.AddRow(_lbl_cm)
        self.dd_color = forms.DropDown()
        for cm in ["field", "influence", "height", "solid", "climate_zone"]:
            self.dd_color.Items.Add(cm)
        self.dd_color.SelectedIndex = 4  # default: climate_zone
        self.dd_color.SelectedIndexChanged += lambda s, e: self._mark_display()
        dl.AddRow(self.dd_color)

        self.chk_bake_legend = forms.CheckBox(); self.chk_bake_legend.Text = "Bake Score Legend"
        self.chk_bake_legend.Checked = True
        dl.AddRow(self.chk_bake_legend)

        self.chk_edges = forms.CheckBox(); self.chk_edges.Text = "Show Edges"
        self.chk_edges.Checked = True
        self.chk_edges.CheckedChanged += lambda s, e: self._mark_display()
        dl.AddRow(self.chk_edges)

        self.chk_bounds = forms.CheckBox(); self.chk_bounds.Text = "Show Bounding Box"
        self.chk_bounds.Checked = True
        self.chk_bounds.CheckedChanged += lambda s, e: self._mark_display()
        dl.AddRow(self.chk_bounds)

        self.chk_att_radii = forms.CheckBox(); self.chk_att_radii.Text = "Show Attractor Radii"
        self.chk_att_radii.Checked = True
        self.chk_att_radii.CheckedChanged += lambda s, e: self._mark_display()
        dl.AddRow(self.chk_att_radii)

        self.chk_live = forms.CheckBox(); self.chk_live.Text = "Live Preview"
        self.chk_live.Checked = True
        self.chk_live.CheckedChanged += lambda s, e: self._on_live_toggle()
        dl.AddRow(self.chk_live)

        # Edge color picker
        edge_row = forms.DynamicLayout()
        edge_row.DefaultSpacing = drawing.Size(4, 0)
        self.btn_edge_color = forms.Button(); self.btn_edge_color.Text = "Edge Color"
        self.btn_edge_color.Click += self._on_pick_edge_color
        self.lbl_edge_color = forms.Label(); self.lbl_edge_color.Text = "(40, 40, 40)"
        edge_row.AddRow(self.btn_edge_color, self.lbl_edge_color, None)
        dl.AddRow(edge_row)

        self.lbl_disp_status = forms.Label(); self.lbl_disp_status.Text = ""
        dl.AddRow(self.lbl_disp_status)
        dl.AddRow(None)
        tab_disp.Content = dl
        tabs.Pages.Add(tab_disp)

        main_layout.AddRow(tabs)

        # --- BOTTOM BAR ---
        btn_row = forms.DynamicLayout()
        btn_row.DefaultSpacing = drawing.Size(6, 0)
        self.btn_update = forms.Button(); self.btn_update.Text = "UPDATE PREVIEW"
        self.btn_update.Click += lambda s, e: self._full_regenerate()
        self.btn_bake = forms.Button(); self.btn_bake.Text = "BAKE TO RHINO"
        self.btn_bake.Click += lambda s, e: self._bake()
        # Live toggle always visible in bottom bar
        self.chk_live_bar = forms.CheckBox(); self.chk_live_bar.Text = "Live"
        self.chk_live_bar.Checked = True
        self.chk_live_bar.CheckedChanged += lambda s, e: self._on_live_bar_toggle()
        btn_row.AddRow(self.btn_update, self.btn_bake, self.chk_live_bar, None)
        main_layout.AddRow(btn_row)

        self.lbl_status = forms.Label(); self.lbl_status.Text = "Ready. Press UPDATE PREVIEW to begin."
        main_layout.AddRow(self.lbl_status)

        self.Content = main_layout

    # -------------------------------------------------------------------------
    # ATTRACTOR PANEL BUILDER
    # -------------------------------------------------------------------------

    def _build_attractor_panel(self, layout, idx):
        """Build UI for one attractor (A, B, or C)."""
        label = ["A", "B", "C"][idx]
        w = {}

        header = forms.Label(); header.Text = "Attractor {}".format(label)
        header.Font = drawing.Font(header.Font.Family, header.Font.Size, drawing.FontStyle.Bold)
        layout.AddRow(header)

        chk_row = forms.DynamicLayout(); chk_row.DefaultSpacing = drawing.Size(12, 0)
        w["chk_enabled"] = forms.CheckBox(); w["chk_enabled"].Text = "Enabled"
        w["chk_enabled"].Checked = False
        w["chk_enabled"].CheckedChanged += lambda s, e: self._mark_compute()
        w["chk_invert"] = forms.CheckBox(); w["chk_invert"].Text = "Invert (negative space)"
        w["chk_invert"].Checked = False
        w["chk_invert"].CheckedChanged += lambda s, e: self._mark_compute()
        chk_row.AddRow(w["chk_enabled"], w["chk_invert"], None)
        layout.AddRow(chk_row)

        # Type dropdown
        type_row = forms.DynamicLayout()
        type_row.DefaultSpacing = drawing.Size(4, 0)
        type_lbl = forms.Label(); type_lbl.Text = "Type:"; type_lbl.Width = 50
        w["dd_type"] = forms.DropDown()
        w["dd_type"].Items.Add("Point")
        w["dd_type"].Items.Add("Curve")
        w["dd_type"].SelectedIndex = 0
        w["dd_type"].SelectedIndexChanged += lambda s, e: self._mark_compute()
        type_row.AddRow(type_lbl, w["dd_type"], None)
        layout.AddRow(type_row)

        # Pick buttons
        pick_row = forms.DynamicLayout()
        pick_row.DefaultSpacing = drawing.Size(4, 0)
        _idx = idx  # capture
        w["btn_pick_pt"] = forms.Button(); w["btn_pick_pt"].Text = "Pick Point"
        w["btn_pick_pt"].Click += lambda s, e, i=_idx: self._on_pick_attractor_pt(i)
        w["btn_pick_curves"] = forms.Button(); w["btn_pick_curves"].Text = "Pick Curves"
        w["btn_pick_curves"].Click += lambda s, e, i=_idx: self._on_pick_attractor_curves(i)
        w["btn_clear_curves"] = forms.Button(); w["btn_clear_curves"].Text = "Clear"
        w["btn_clear_curves"].Click += lambda s, e, i=_idx: self._on_clear_attractor_curves(i)
        pick_row.AddRow(w["btn_pick_pt"], w["btn_pick_curves"], w["btn_clear_curves"], None)
        layout.AddRow(pick_row)

        sca_row = forms.DynamicLayout(); sca_row.DefaultSpacing = drawing.Size(4, 0)
        w["btn_auto_sca"] = forms.Button(); w["btn_auto_sca"].Text = "Auto-pick SCA"
        w["btn_auto_sca"].Click += lambda s, e, i=_idx: self._on_auto_sca(i)
        sca_row.AddRow(w["btn_auto_sca"], None)
        layout.AddRow(sca_row)

        w["lbl_pos"] = forms.Label(); w["lbl_pos"].Text = "Position: not set"
        layout.AddRow(w["lbl_pos"])

        # Radius
        w["sld_radius"], w["txt_radius"] = self._float_slider(layout, "Radius", 0.1, 20.0, 5.0, self._mark_compute)

        # Behavior
        beh_row = forms.DynamicLayout()
        beh_row.DefaultSpacing = drawing.Size(4, 0)
        beh_lbl = forms.Label(); beh_lbl.Text = "Behavior:"; beh_lbl.Width = 60
        w["dd_behavior"] = forms.DropDown()
        for b in AttractorData.BEHAVIORS:
            w["dd_behavior"].Items.Add(b)
        w["dd_behavior"].SelectedIndex = 0
        w["dd_behavior"].SelectedIndexChanged += lambda s, e: self._mark_compute()
        beh_row.AddRow(beh_lbl, w["dd_behavior"], None)
        layout.AddRow(beh_row)

        # Strength
        w["sld_strength"], w["txt_strength"] = self._float_slider(layout, "Strength", 0.0, 10.0, 0.8, self._mark_compute)

        # Falloff
        fal_row = forms.DynamicLayout()
        fal_row.DefaultSpacing = drawing.Size(4, 0)
        fal_lbl = forms.Label(); fal_lbl.Text = "Falloff:"; fal_lbl.Width = 60
        w["dd_falloff"] = forms.DropDown()
        for f in AttractorData.FALLOFFS:
            w["dd_falloff"].Items.Add(f)
        w["dd_falloff"].SelectedIndex = 0
        w["dd_falloff"].SelectedIndexChanged += lambda s, e: self._mark_compute()
        fal_row.AddRow(fal_lbl, w["dd_falloff"], None)
        layout.AddRow(fal_row)

        self._att_widgets.append(w)

    # -------------------------------------------------------------------------
    # FIELD VISIBILITY
    # -------------------------------------------------------------------------

    def _update_field_visibility(self):
        """Show/hide field parameters based on selected algorithm.

        Sliders created by _float_slider / _int_slider store their entire row
        (label + slider + textbox) in sld.Tag — hiding sld.Tag hides the whole
        row including the label, avoiding 'floating text' artefacts.
        """
        alg = FieldEngine.ALGORITHMS[self.dd_algorithm.SelectedIndex]
        noise_algs = {"perlin", "value_noise", "domain_warp"}
        tpms_algs = {"gyroid", "schwarz_p", "schwarz_d", "lidinoid"}
        rd_alg = {"reaction_diff"}

        show_noise = alg in noise_algs or alg in {"worley_f1", "worley_f2f1"}
        show_tpms  = alg in tpms_algs
        show_rd    = alg in rd_alg
        show_oct   = alg in noise_algs

        def _row_vis(sld, visible):
            """Hide/show the entire row (label + slider + textbox) via sld.Tag."""
            if sld.Tag is not None:
                sld.Tag.Visible = visible
            else:
                sld.Visible = visible

        # Octaves + frequency header
        self.lbl_octaves_header.Visible = show_noise
        _row_vis(self.sld_octaves, show_oct)
        _row_vis(self.sld_freq,    show_noise)

        # Period (TPMS)
        self.lbl_period_header.Visible = show_tpms
        _row_vis(self.sld_period, show_tpms)

        # Reaction-diffusion
        self.lbl_rd_header.Visible = show_rd
        _row_vis(self.sld_rd_feed,  show_rd)
        _row_vis(self.sld_rd_kill,  show_rd)
        _row_vis(self.sld_rd_steps, show_rd)

        # EPW climate controls
        show_epw = (alg == "climate_epw")
        self.lbl_epw_header.Visible = show_epw
        self.txt_epw_path.Visible   = show_epw
        self.btn_epw_browse.Visible = show_epw
        self.lbl_epw_month.Visible  = show_epw
        self.dd_epw_month.Visible   = show_epw
        _row_vis(self.sld_sun_weight, show_epw)
        self.chk_z_decay.Visible    = show_epw

        # Comfort JSON controls
        show_json = (alg == "comfort_json")
        self.lbl_json_header.Visible  = show_json
        self.txt_json_path.Visible    = show_json
        self.btn_json_browse.Visible  = show_json
        self.lbl_json_metric.Visible  = show_json
        self.dd_json_metric.Visible   = show_json

    # -------------------------------------------------------------------------
    # CA HELPERS
    # -------------------------------------------------------------------------

    def _update_ca_visibility(self):
        """Show/hide CA-family-specific parameters based on current preset."""
        preset_idx = self.dd_ca_preset.SelectedIndex
        if preset_idx < 0 or preset_idx >= len(CA_PRESET_NAMES):
            return
        name = CA_PRESET_NAMES[preset_idx]
        fam = CA_PRESETS[name].get("family", "life")
        self.lbl_ca_family.Text = "Family: {}".format(fam)

        is_cyclic = (fam == "cyclic")
        is_dla = (fam == "dla")
        is_stoch = (fam == "stochastic")
        is_accretor = (fam == "accretor")
        has_bs = fam in ("life", "generations", "stochastic")

        # B/S fields
        self.txt_ca_birth.Visible = has_bs
        self.txt_ca_survival.Visible = has_bs

        # General params
        self.sld_ca_states.Visible = has_bs
        self.txt_ca_states.Visible = has_bs
        self.sld_ca_density.Visible = not is_dla and not is_accretor
        self.txt_ca_density.Visible = not is_dla and not is_accretor
        self.dd_ca_neighborhood.Visible = not is_dla and not is_accretor

        # Cyclic
        self.lbl_ca_cyclic.Visible = is_cyclic
        self.sld_ca_range.Visible = is_cyclic
        self.txt_ca_range.Visible = is_cyclic
        self.sld_ca_threshold.Visible = is_cyclic
        self.txt_ca_threshold.Visible = is_cyclic
        self.sld_ca_colors.Visible = is_cyclic
        self.txt_ca_colors.Visible = is_cyclic
        self.chk_ca_gh.Visible = is_cyclic

        # DLA
        self.lbl_ca_dla.Visible = is_dla
        self.sld_ca_particles.Visible = is_dla
        self.txt_ca_particles.Visible = is_dla
        self.sld_ca_stick.Visible = is_dla
        self.txt_ca_stick.Visible = is_dla

        # Stochastic
        self.lbl_ca_stoch.Visible = is_stoch
        self.sld_ca_prob.Visible = is_stoch
        self.txt_ca_prob.Visible = is_stoch

        # Accretor
        self.lbl_ca_accretor.Visible = is_accretor
        self.sld_ca_acc_states.Visible = is_accretor
        self.txt_ca_acc_states.Visible = is_accretor

    def _on_ca_preset_changed(self, sender, e):
        """When user changes CA preset dropdown, update all CA fields."""
        idx = self.dd_ca_preset.SelectedIndex
        if idx < 0 or idx >= len(CA_PRESET_NAMES):
            return
        name = CA_PRESET_NAMES[idx]
        p = CA_PRESETS[name]
        # Update text fields
        if "birth" in p:
            self.txt_ca_birth.Text = ",".join(str(x) for x in sorted(p["birth"]))
        if "survival" in p:
            self.txt_ca_survival.Text = ",".join(str(x) for x in sorted(p["survival"]))
        if "states" in p:
            st = p["states"]
            self.sld_ca_states.Value = clamp(st, 2, 20)
            self.txt_ca_states.Text = str(st)
        if "neighborhood" in p:
            self.dd_ca_neighborhood.SelectedIndex = 0 if p["neighborhood"] == "moore" else 1
        # Cyclic
        if "range" in p:
            self.sld_ca_range.Value = clamp(p["range"], 1, 3)
            self.txt_ca_range.Text = str(p["range"])
        if "threshold" in p:
            self.sld_ca_threshold.Value = clamp(p["threshold"], 1, 10)
            self.txt_ca_threshold.Text = str(p["threshold"])
        if "colors" in p:
            self.sld_ca_colors.Value = clamp(p["colors"], 3, 128)
            self.txt_ca_colors.Text = str(p["colors"])
        if "greenberg_hastings" in p:
            self.chk_ca_gh.Checked = p["greenberg_hastings"]
        # DLA
        if "particles" in p:
            self.sld_ca_particles.Value = clamp(p["particles"], 100, 15000)
            self.txt_ca_particles.Text = str(p["particles"])
        if "stick_prob" in p:
            sv = int((p["stick_prob"] - 0.1) / (1.0 - 0.1) * 1000)
            self.sld_ca_stick.Value = clamp(sv, 0, 1000)
            self.txt_ca_stick.Text = "{:.2f}".format(p["stick_prob"])
        # Stochastic
        if "probability" in p:
            sv = int((p["probability"] - 0.1) / (1.0 - 0.1) * 1000)
            self.sld_ca_prob.Value = clamp(sv, 0, 1000)
            self.txt_ca_prob.Text = "{:.2f}".format(p["probability"])
        # Accretor
        if "accretor_states" in p:
            self.sld_ca_acc_states.Value = clamp(p["accretor_states"], 2, 5)
            self.txt_ca_acc_states.Text = str(p["accretor_states"])

        self._update_ca_visibility()
        self._mark_compute()

    def _parse_int_set(self, text):
        """Parse comma-separated ints like '4,5,6' or ranges like '5-8,12' into a set."""
        result = set()
        for part in text.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    lo, hi = part.split("-", 1)
                    for v in range(int(lo), int(hi) + 1):
                        result.add(v)
                except:
                    pass
            else:
                try:
                    result.add(int(part))
                except:
                    pass
        return result

    def _read_ca_engine(self):
        """Read CA tab widgets into self.engine.ca_engine."""
        ce = self.engine.ca_engine
        # Preset
        idx = self.dd_ca_preset.SelectedIndex
        if 0 <= idx < len(CA_PRESET_NAMES):
            ce.apply_preset(CA_PRESET_NAMES[idx])
        # Override with user edits
        ce.birth = self._parse_int_set(self.txt_ca_birth.Text)
        ce.survival = self._parse_int_set(self.txt_ca_survival.Text)
        ce.states = self.sld_ca_states.Value
        ce.steps = self.sld_ca_steps.Value
        # Init density
        d_raw = self.sld_ca_density.Value / 1000.0
        ce.init_density = 0.01 + d_raw * (0.8 - 0.01)
        ce.neighborhood = "moore" if self.dd_ca_neighborhood.SelectedIndex == 0 else "vn"
        ce.wrap = bool(self.chk_ca_wrap.Checked)
        # Cyclic
        ce.ca_range = self.sld_ca_range.Value
        ce.threshold = self.sld_ca_threshold.Value
        ce.colors = self.sld_ca_colors.Value
        ce.greenberg_hastings = bool(self.chk_ca_gh.Checked)
        # DLA
        ce.particles = self.sld_ca_particles.Value
        stick_raw = self.sld_ca_stick.Value / 1000.0
        ce.stick_prob = 0.1 + stick_raw * (1.0 - 0.1)
        # Stochastic
        prob_raw = self.sld_ca_prob.Value / 1000.0
        ce.probability = 0.1 + prob_raw * (1.0 - 0.1)
        # Accretor
        ce.accretor_states = self.sld_ca_acc_states.Value
        ce.accretor_seed = self.engine.seed

    # -------------------------------------------------------------------------
    # EVENT HANDLERS
    # -------------------------------------------------------------------------

    def _on_algorithm_changed(self, sender, e):
        self._update_field_visibility()
        self._mark_compute()

    def _on_live_toggle(self):
        """Called from Display-tab checkbox — syncs to bottom bar."""
        self._live_preview = bool(self.chk_live.Checked)
        self.chk_live_bar.Checked = self._live_preview
        self._update_live_status()

    def _on_live_bar_toggle(self):
        """Called from bottom-bar Live checkbox — syncs to Display tab."""
        self._live_preview = bool(self.chk_live_bar.Checked)
        self.chk_live.Checked = self._live_preview
        self._update_live_status()

    def _update_live_status(self):
        if self._live_preview:
            self.btn_update.Text = "UPDATE PREVIEW"
            self.lbl_status.Text = "Live ON — sliders auto-update"
        else:
            self.btn_update.Text = "▶ UPDATE PREVIEW"
            self.lbl_status.Text = "Live OFF — press UPDATE PREVIEW to refresh"

    def _on_pick_brep(self, sender, e):
        self.Visible = False
        obj_ids = rs.GetObjects("Pick base Breps (select multiple)", rs.filter.polysurface | rs.filter.surface)
        self.Visible = True
        if obj_ids:
            breps = []
            for oid in obj_ids:
                b = rs.coercebrep(oid)
                if b:
                    breps.append(b)
            if breps:
                self._picked_breps = breps
                self.lbl_picked.Text = "{} Brep{} picked".format(len(breps), "s" if len(breps) > 1 else "")
                self._mark_compute()
            else:
                self.lbl_picked.Text = "Failed to coerce Breps"
        else:
            self.lbl_picked.Text = "No geometry picked"

    def _on_pick_mesh(self, sender, e):
        self.Visible = False
        obj_ids = rs.GetObjects("Pick base Meshes (select multiple)", rs.filter.mesh)
        self.Visible = True
        if obj_ids:
            meshes = []
            for oid in obj_ids:
                m = rs.coercemesh(oid)
                if m:
                    meshes.append(m)
            if meshes:
                self._picked_meshes = meshes
                self.lbl_picked.Text = "{} Mesh{} picked".format(len(meshes), "es" if len(meshes) > 1 else "")
                self._mark_compute()
            else:
                self.lbl_picked.Text = "Failed to coerce Meshes"
        else:
            self.lbl_picked.Text = "No geometry picked"

    def _on_clear_geometry(self, sender, e):
        self._picked_breps = []
        self._picked_meshes = []
        self.lbl_picked.Text = "No geometry picked"
        self._mark_compute()

    def _on_pick_attractor_pt(self, idx):
        self.Visible = False
        pt = rs.GetPoint("Pick attractor {} point".format(self.attractors[idx].label))
        self.Visible = True
        if pt is not None:
            self._attractor_pts[idx] = (pt.X, pt.Y, pt.Z)
            w = self._att_widgets[idx]
            w["lbl_pos"].Text = "Point: ({:.1f}, {:.1f}, {:.1f})".format(pt.X, pt.Y, pt.Z)
            self._mark_compute()

    def _on_pick_attractor_curves(self, idx):
        """Pick multiple curves from the viewport for curve-type attractor."""
        self.Visible = False
        obj_ids = rs.GetObjects("Pick curves for attractor {}".format(self.attractors[idx].label),
                                rs.filter.curve, preselect=True)
        self.Visible = True
        if obj_ids:
            curves = []
            for oid in obj_ids:
                crv = rs.coercecurve(oid)
                if crv:
                    curves.append(crv)
            if curves:
                self._attractor_curves[idx] = curves
                w = self._att_widgets[idx]
                w["lbl_pos"].Text = "{} curve(s) picked".format(len(curves))
                self._mark_compute()

    def _on_clear_attractor_curves(self, idx):
        """Clear picked curves for an attractor."""
        self._attractor_curves[idx] = []
        w = self._att_widgets[idx]
        w["lbl_pos"].Text = "Curves: cleared"
        self._mark_compute()

    def _on_pick_edge_color(self, sender, e):
        dlg = forms.ColorDialog()
        dlg.Color = drawing.Color.FromArgb(40, 40, 40)
        if dlg.ShowDialog(self) == forms.DialogResult.Ok:
            c = dlg.Color
            self.conduit.edge_color = System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb)
            self.lbl_edge_color.Text = "({}, {}, {})".format(c.Rb, c.Gb, c.Bb)
            sc.doc.Views.Redraw()

    def _on_epw_browse(self, sender, e):
        """Browse for EPW climate file."""
        dlg = forms.OpenFileDialog()
        dlg.Title = "Select EPW Climate File"
        dlg.Filters.Add(forms.FileFilter("EPW Files", ".epw"))
        dlg.Filters.Add(forms.FileFilter("All Files", ".*"))
        if dlg.ShowDialog(self) == forms.DialogResult.Ok:
            self.txt_epw_path.Text = dlg.FileName
            self._mark_compute()

    def _on_json_browse(self, sender, e):
        """Browse for comfort_field.json file."""
        dlg = forms.OpenFileDialog()
        dlg.Title = "Select comfort_field.json"
        dlg.Filters.Add(forms.FileFilter("JSON Files", ".json"))
        dlg.Filters.Add(forms.FileFilter("All Files", ".*"))
        if dlg.ShowDialog(self) == forms.DialogResult.Ok:
            self.txt_json_path.Text = dlg.FileName
            self._mark_compute()

    def _on_auto_sca(self, idx):
        """Auto-scan SCA_Branches layers and load all curves as attractor."""
        curves = collect_sca_curves()
        w = self._att_widgets[idx]
        if curves:
            self._attractor_curves[idx] = curves
            w["dd_type"].SelectedIndex = 1  # switch to Curve mode
            w["lbl_pos"].Text = "{} SCA curves loaded from SCA_Branches".format(len(curves))
            self._mark_compute()
        else:
            w["lbl_pos"].Text = "No SCA curves found (run SCA script first)"

    # -------------------------------------------------------------------------
    # DIRTY FLAGS
    # -------------------------------------------------------------------------

    def _mark_compute(self):
        if self._live_preview:
            self._compute_dirty = True

    def _mark_display(self):
        if self._live_preview:
            self._display_dirty = True

    def _on_timer_tick(self, sender, e):
        if self._compute_dirty:
            self._compute_dirty = False
            self._display_dirty = False
            self._full_regenerate()
        elif self._display_dirty:
            self._display_dirty = False
            self._display_only()

    # -------------------------------------------------------------------------
    # READ UI STATE
    # -------------------------------------------------------------------------

    def _read_grid_params(self):
        """Read grid tab widgets. Returns (mode, nx, ny, nz, voxel_size)."""
        mode = self.dd_mode.SelectedIndex  # 0=Standalone, 1=From Brep, 2=From Mesh

        nx = self.sld_nx.Value
        ny = self.sld_ny.Value
        nz = self.sld_nz.Value
        # Read voxel size from float slider
        vsize_raw = self.sld_vsize.Value / 1000.0
        vsize = 0.1 + vsize_raw * (5.0 - 0.1)
        return (mode, nx, ny, nz, vsize)

    def _read_engine(self):
        """Read field tab widgets into self.engine."""
        self.engine.algorithm = FieldEngine.ALGORITHMS[self.dd_algorithm.SelectedIndex]

        # Threshold
        thr_raw = self.sld_threshold.Value / 1000.0
        self.engine.threshold = 0.0 + thr_raw * (1.0 - 0.0)

        self.engine.invert = bool(self.chk_invert.Checked)
        self.engine.octaves = self.sld_octaves.Value

        # Frequency
        freq_raw = self.sld_freq.Value / 1000.0
        self.engine.frequency = 0.01 + freq_raw * (2.0 - 0.01)

        # Period
        per_raw = self.sld_period.Value / 1000.0
        self.engine.period = 1.0 + per_raw * (20.0 - 1.0)

        # RD params
        rdf_raw = self.sld_rd_feed.Value / 1000.0
        self.engine.rd_feed = 0.01 + rdf_raw * (0.1 - 0.01)
        rdk_raw = self.sld_rd_kill.Value / 1000.0
        self.engine.rd_kill = 0.01 + rdk_raw * (0.1 - 0.01)
        self.engine.rd_steps = self.sld_rd_steps.Value

        # Seed
        try:
            self.engine.seed = int(self.txt_seed.Text)
        except:
            self.engine.seed = 42

        # Climate EPW
        self.engine.epw_path = str(self.txt_epw_path.Text).strip()
        self.engine.epw_month = self.dd_epw_month.SelectedIndex  # 0=annual, 1-12=month
        sw_raw = self.sld_sun_weight.Value / 1000.0
        self.engine.sun_mult = sw_raw
        self.engine.z_decay_on = bool(self.chk_z_decay.Checked)

        # Comfort JSON
        self.engine.json_path = str(self.txt_json_path.Text).strip()
        metric_items = ["combined", "thermal", "daylight", "airflow"]
        idx_m = self.dd_json_metric.SelectedIndex
        self.engine.comfort_metric = metric_items[idx_m] if 0 <= idx_m < len(metric_items) else "combined"

    def _read_attractor(self, idx):
        """Read attractor widgets into self.attractors[idx]."""
        w = self._att_widgets[idx]
        att = self.attractors[idx]

        att.enabled = bool(w["chk_enabled"].Checked)
        att.invert = bool(w["chk_invert"].Checked)

        type_idx = w["dd_type"].SelectedIndex
        att.type = "point" if type_idx == 0 else "curve"

        if self._attractor_pts[idx] is not None:
            att.position = self._attractor_pts[idx]
        att.curves = self._attractor_curves[idx]

        # Radius
        rad_raw = w["sld_radius"].Value / 1000.0
        att.radius = 0.1 + rad_raw * (20.0 - 0.1)

        att.behavior = AttractorData.BEHAVIORS[w["dd_behavior"].SelectedIndex]

        # Strength
        str_raw = w["sld_strength"].Value / 1000.0
        att.strength = 0.0 + str_raw * (10.0 - 0.0)

        att.falloff_type = AttractorData.FALLOFFS[w["dd_falloff"].SelectedIndex]

    # -------------------------------------------------------------------------
    # REGENERATION
    # -------------------------------------------------------------------------

    def _full_regenerate(self):
        """Full pipeline: populate grid, apply field, apply attractors, build mesh."""
        try:
            self.lbl_status.Text = "Computing..."
            mode, nx, ny, nz, vsize = self._read_grid_params()
            origin = (0.0, 0.0, 0.0)
            self._grid = VoxelGrid(origin, vsize, nx, ny, nz)

            if mode == 0:
                self._grid.populate_full()
            elif mode == 1 and self._picked_breps:
                # World-axis aligned bounding box — no rotation, grid matches world X/Y/Z
                world_bb = self._picked_breps[0].GetBoundingBox(True)
                for _g in self._picked_breps[1:]:
                    world_bb.Union(_g.GetBoundingBox(True))
                local_origin = (world_bb.Min.X, world_bb.Min.Y, world_bb.Min.Z)
                nx = max(2, int(math.ceil((world_bb.Max.X - world_bb.Min.X) / vsize)))
                ny = max(2, int(math.ceil((world_bb.Max.Y - world_bb.Min.Y) / vsize)))
                nz = max(2, int(math.ceil((world_bb.Max.Z - world_bb.Min.Z) / vsize)))
                self._grid = VoxelGrid(local_origin, vsize, nx, ny, nz)
                self._grid.populate_from_breps(self._picked_breps)
            elif mode == 2 and self._picked_meshes:
                # World-axis aligned bounding box — no rotation, grid matches world X/Y/Z
                world_bb = self._picked_meshes[0].GetBoundingBox(True)
                for _g in self._picked_meshes[1:]:
                    world_bb.Union(_g.GetBoundingBox(True))
                local_origin = (world_bb.Min.X, world_bb.Min.Y, world_bb.Min.Z)
                nx = max(2, int(math.ceil((world_bb.Max.X - world_bb.Min.X) / vsize)))
                ny = max(2, int(math.ceil((world_bb.Max.Y - world_bb.Min.Y) / vsize)))
                nz = max(2, int(math.ceil((world_bb.Max.Z - world_bb.Min.Z) / vsize)))
                self._grid = VoxelGrid(local_origin, vsize, nx, ny, nz)
                self._grid.populate_from_meshes(self._picked_meshes)
            else:
                self._grid.populate_full()

            self._read_engine()
            self._read_ca_engine()
            self._grid.apply_field(self.engine)

            for i in range(3):
                self._read_attractor(i)

            self._grid.apply_attractors(self.attractors)

            # Read display settings
            self.color_mode = str(self.dd_color.Items[self.dd_color.SelectedIndex])
            show_edges = bool(self.chk_edges.Checked)

            mesh = self._grid.build_mesh(self.color_mode, show_edges)
            self.conduit.mesh = mesh
            self.conduit.show_edges = show_edges
            self.conduit.show_bounds = bool(self.chk_bounds.Checked)

            self._update_bound_lines()
            self._update_attractor_visuals()

            sc.doc.Views.Redraw()
            ox, oy, oz = self._grid.origin
            n_vox = len(self._grid.voxels)
            alg_now = self.engine.algorithm
            # Hint when color mode needs climate algorithm
            if self.color_mode == "climate_zone" and alg_now not in ("climate_epw", "comfort_json"):
                self.lbl_status.Text = (
                    "Voxels: {} | TIP: Set Algorithm = climate_epw in Field tab "
                    "then UPDATE to see real climate zones".format(n_vox))
            else:
                self.lbl_status.Text = "Voxels: {}  |  Vertices: {}  |  Origin: ({:.1f},{:.1f},{:.1f})".format(
                    n_vox, mesh.Vertices.Count, ox, oy, oz)

        except Exception as ex:
            self.lbl_status.Text = "Error: {}".format(str(ex))

    def _display_only(self):
        """Rebuild mesh from existing voxels (no recomputation)."""
        if self._grid is None or len(self._grid.voxels) == 0:
            return
        try:
            self.color_mode = str(self.dd_color.Items[self.dd_color.SelectedIndex])
            show_edges = bool(self.chk_edges.Checked)

            mesh = self._grid.build_mesh(self.color_mode, show_edges)
            self.conduit.mesh = mesh
            self.conduit.show_edges = show_edges
            self.conduit.show_bounds = bool(self.chk_bounds.Checked)

            self._update_bound_lines()
            self._update_attractor_visuals()

            sc.doc.Views.Redraw()
            self.lbl_status.Text = "Voxels: {}  |  Display updated".format(len(self._grid.voxels))
        except Exception as ex:
            self.lbl_status.Text = "Display error: {}".format(str(ex))

    def _update_bound_lines(self):
        """Update bounding box wireframe lines in the conduit (supports oriented grids)."""
        if self._grid is None:
            return
        g = self._grid
        ox, oy, oz = g.origin
        sx = g.nx * g.voxel_size
        sy = g.ny * g.voxel_size
        sz = g.nz * g.voxel_size
        # 8 local corners
        local_corners = [(ox + dx * sx, oy + dy * sy, oz + dz * sz)
                         for dx in (0, 1) for dy in (0, 1) for dz in (0, 1)]
        # Transform to world if oriented
        if g.plane is not None:
            c = [_plane_point_at_3d(g.plane, lx, ly, lz) for lx, ly, lz in local_corners]
        else:
            c = local_corners
        # 12 edges
        edges = [(0,1),(2,3),(4,5),(6,7),(0,2),(1,3),(4,6),(5,7),(0,4),(1,5),(2,6),(3,7)]
        self.conduit.bound_lines = [
            rg.Line(rg.Point3d(*c[a]), rg.Point3d(*c[b])) for a, b in edges
        ]

    def _update_attractor_visuals(self):
        """Update attractor sphere and curve visualizations in the conduit."""
        if not bool(self.chk_att_radii.Checked):
            self.conduit.attractor_spheres = []
            self.conduit.attractor_curves = []
            return
        self.conduit.attractor_spheres = []
        self.conduit.attractor_curves = []
        for att in self.attractors:
            if att.enabled and att.type == "point" and att.position != (0, 0, 0):
                sp = rg.Sphere(rg.Point3d(*att.position), att.radius)
                col = System.Drawing.Color.FromArgb(80, 255, 100, 50)
                self.conduit.attractor_spheres.append((sp, col))
            elif att.enabled and att.type == "curve" and att.curves:
                crv_col = System.Drawing.Color.FromArgb(255, 255, 120, 30)
                for crv in att.curves:
                    self.conduit.attractor_curves.append((crv, crv_col))

    def _bake(self):
        """Bake current voxel mesh to Rhino document."""
        if self._grid is None:
            self.lbl_status.Text = "Nothing to bake. Run UPDATE PREVIEW first."
            return
        self.color_mode = str(self.dd_color.Items[self.dd_color.SelectedIndex])
        bake_legend = bool(self.chk_bake_legend.Checked)
        alg = self.engine.algorithm
        n_vox = len(self._grid.voxels)
        self._grid.bake(self.color_mode, bake_legend=bake_legend, algorithm=alg, voxel_count=n_vox)
        self.lbl_status.Text = "Baked {} voxels to VoxelField layers.".format(n_vox)

    # -------------------------------------------------------------------------
    # CLEANUP
    # -------------------------------------------------------------------------

    def _on_closed(self, sender, e):
        """Clean up on dialog close."""
        try:
            self._timer.Stop()
        except:
            pass
        try:
            self.conduit.Enabled = False
        except:
            pass
        sc.doc.Views.Redraw()

# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    dlg = VoxelFieldDialog()
    dlg.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    dlg.Show()

if __name__ == "__main__":
    main()
