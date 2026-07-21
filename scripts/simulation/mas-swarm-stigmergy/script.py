#! python 3
"""
MAS & Swarm (Stigmergy) V8 — Edge Connector Aggregation
Rhino 8 CPython

NEW IN V8 (over V7):
  - Connector Mode (default): places module spanning each history[i]→history[i+1] edge
      · Stable orientation from point-to-point vector — no tangent instability
      · Module auto-scaled to fill the exact segment distance (connector_sf)
      · Density scaling applied as cross-section variation (not length)
      · Produces legible branching topology faithful to swarm paths
  - 4 Aggregation Modes: Trail, Field, Cluster, Connector (default)
  - Multi-geometry selection in all void modes (A and D expanded to multi-select)

References:
  Retsin, G. (2016) Discrete Assembly and Digital Materials. ECAADE.
  Sanchez, J. (2014) Bloom: The Game. FABRICATE.
  Wark, B. — The Architecture of Ecology. barrywark.com
  Ant Simulation   https://github.com/SebLague/Ant-Simulation
  Slime Simulation https://github.com/SebLague/Slime-Simulation
"""

import Rhino
import Rhino.Display
import scriptcontext as sc
import Eto.Forms as forms
import Eto.Drawing as drawing
import rhinoscriptsyntax as rs
import random
import math
import System
import System.Drawing as sd


# ═══════════════════════════════════════════════════════
#  PRESET TEMPLATES  (Phase 5 — unchanged from V6)
# ═══════════════════════════════════════════════════════
PRESETS = [
    None,  # 0 = Custom
    {   # 1 — Radial Cluster
        "name": "Radial Cluster",
        "void_mode": 0, "perf_mode": 3,
        "agents": "60", "steps": "200",
        "jitter": "0.4", "speed": "0.8",
        "evap": "0.03", "phero_w": "0.8",
        "deposit": "1.5", "cellsize": "0.5", "prune": "0.001",
        "perf_w": "0.0", "attr_weight": "0.7",
        "layers": 0, "foraging": False, "branch": False,
        "hint": "Select a void Brep. Add Attractors in a ring for nested cluster rings.",
    },
    {   # 2 — Linear Flow
        "name": "Linear Flow",
        "void_mode": 0, "perf_mode": 2,
        "vx": "1", "vy": "0", "vz": "0",
        "agents": "50", "steps": "200",
        "jitter": "0.15", "speed": "1.5",
        "evap": "0.05", "phero_w": "0.4",
        "deposit": "1.0", "cellsize": "0.5", "prune": "0.001",
        "perf_w": "0.8", "attr_weight": "0.0",
        "layers": 0, "foraging": False, "branch": False,
        "hint": "Select a void Brep. Set Wind X/Y/Z for flow direction.",
    },
    {   # 3 — Shortest Path (Foraging)
        "name": "Shortest Path",
        "void_mode": 0, "perf_mode": 3,
        # More agents + longer life = better probabilistic coverage of space
        "agents": "40", "steps": "500",
        "jitter": "0.4", "speed": "1.5",
        # Fast evap forces agents to keep exploring, not loop locally
        "evap": "0.04", "phero_w": "0.5",
        "deposit": "1.5", "cellsize": "1.0", "prune": "0.002",
        "perf_w": "0.0", "attr_weight": "0.0",
        "layers": 1, "foraging": True,
        # Large detect_radius is critical — agents don't AIM at target,
        # they wander randomly until they enter this bubble
        "return_speed": "1.5", "food_strength": "3.0", "detect_radius": "8.0",
        "branch": False,
        "sense_angle": "0.35", "sense_dist": "3.0",
        "vunit": "3.0",
        "hint": (
            "Agents RANDOMLY WANDER until they enter detect_radius of Target — "
            "they do NOT aim at it. "
            "Source (cyan) = home/spawn. Target (green) = food. "
            "Large detect_radius (8+) is essential. "
            "Place Source and Target far apart. Run until corridor forms."),
    },
    {   # 4 — Dispersed Network
        "name": "Dispersed Network",
        "void_mode": 1, "perf_mode": 3,
        "agents": "40", "steps": "150",
        "jitter": "0.8", "speed": "1.0",
        "evap": "0.03", "phero_w": "0.2",
        "deposit": "0.5", "cellsize": "0.5", "prune": "0.001",
        "perf_w": "0.0", "attr_weight": "0.5",
        "layers": 0, "foraging": False, "branch": False,
        "hint": "Select mass geometry (Mode B). Scatter attractors in void for sparse paths.",
    },
    {   # 5 — Terrain-Sensitive
        "name": "Terrain-Sensitive",
        "void_mode": 3, "perf_mode": 2,
        "vx": "1", "vy": "0", "vz": "0",
        "agents": "40", "steps": "200",
        "jitter": "0.2", "speed": "0.8",
        "evap": "0.02", "phero_w": "0.6",
        "deposit": "1.0", "cellsize": "0.4", "prune": "0.001",
        "perf_w": "0.5", "attr_weight": "0.0",
        "layers": 1, "foraging": False, "branch": False,
        "hint": "Select a surface geometry (Mode D). Trails trace contours with wind influence.",
    },
    {   # 6 — Tectonic 60³ mm  (1:1000 default)
        "name": "Tectonic 60³ mm",
        "void_mode": 1, "perf_mode": 3,
        # Exploration — agents escape spawn fast, then converge on shared trails
        "agents": "20",   "steps": "250",
        "jitter": "0.35", "speed": "1.5",
        # Pheromone — moderate stigmergy: spread first, reinforce second
        "evap": "0.02",   "phero_w": "0.45",
        "deposit": "1.0", "cellsize": "1.0",  "prune": "0.005",
        "perf_w": "0.0",  "attr_weight": "0.5",
        "layers": 0, "foraging": False,
        # Branching — off by default, tuned thresholds for 60 mm
        "branch": False,
        "branch_thresh": "0.4", "branch_prob": "0.04",
        "branch_cooldown": "15", "max_agents": "60",
        # Sensors
        "sense_angle": "0.35", "sense_dist": "3.0",
        # Attractor
        "attr_radius": "8.0",
        # Grid / voxel
        "vunit": "3.0",
        # Aggregation output
        "spacing": "1.5", "adaptive": True,
        "scale_min": "0.6", "scale_max": "1.4",
        "hint": (
            "Mode B: pick your 60 mm box as Container, skip Mass. "
            "Create X Module → Run → Aggregate. "
            "1:1000 scale (1 m = 1 mm). Speed 1.5 keeps agents spreading before stigmergy locks in."),
    },
]


# ═══════════════════════════════════════════════════════
#  HEATMAP COLOUR THEMES  (V7)
#  Each entry: (display_name, [rgb_stop_tuples...])
#  Stops run from low-density (t=0) → high-density (t=1)
# ═══════════════════════════════════════════════════════
HEATMAP_THEMES = [
    ("Classic Heat",    [(0,0,255),(0,255,255),(0,255,0),(255,255,0),(255,0,0)]),
    ("Magma",           [(0,0,0),(80,0,120),(200,50,0),(255,170,0),(255,255,200)]),
    ("Neon Pulse",      [(0,0,20),(110,0,220),(255,0,160),(0,220,255),(255,255,255)]),
    ("Bioluminescence", [(0,0,10),(0,30,90),(0,150,130),(0,255,170),(180,255,240)]),
    ("Lava",            [(0,0,0),(120,0,0),(255,70,0),(255,210,0),(255,255,255)]),
    ("Aurora",          [(0,0,25),(0,90,90),(0,210,110),(130,0,210),(210,210,255)]),
    ("Arctic Ice",      [(0,10,60),(0,80,200),(0,200,255),(200,240,255),(255,255,255)]),
    ("Monochrome",      [(0,0,0),(255,255,255)]),
]


def _theme_color(stops, t, alpha=180):
    """Linear interpolation across RGB colour stops at normalised t ∈ [0,1]."""
    t  = max(0.0, min(1.0, t))
    n  = len(stops) - 1
    sc_ = t * n
    lo = int(sc_); hi = min(lo + 1, n); frac = sc_ - lo
    r = int(stops[lo][0] + frac * (stops[hi][0] - stops[lo][0]))
    g = int(stops[lo][1] + frac * (stops[hi][1] - stops[lo][1]))
    b = int(stops[lo][2] + frac * (stops[hi][2] - stops[lo][2]))
    return sd.Color.FromArgb(alpha, r, g, b)


def _theme_sample(stops, frac):
    """Sample stops at frac ∈ [0,1] — returns (r,g,b) tuple."""
    n  = len(stops) - 1
    sc_ = frac * n
    lo = int(sc_); hi = min(lo + 1, n); f = sc_ - lo
    return (int(stops[lo][0] + f*(stops[hi][0]-stops[lo][0])),
            int(stops[lo][1] + f*(stops[hi][1]-stops[lo][1])),
            int(stops[lo][2] + f*(stops[hi][2]-stops[lo][2])))


# ═══════════════════════════════════════════════════════
#  MODULE KIT  (V7 — Retsin hierarchical switching)
# ═══════════════════════════════════════════════════════
class ModuleKit:
    """Holds up to 3 module Guids and density thresholds for switching between them."""

    def __init__(self):
        self.slots      = [None, None, None]   # Guid | None  (A, B, C)
        self.thresholds = [0.6, 0.3]           # normalised density [A↔B, B↔C]

    def set_slot(self, idx, guid):
        self.slots[idx] = guid

    def select_slot(self, norm_density):
        """Return (slot_index, Guid) for given normalised pheromone density (0–1).
        Falls back to nearest assigned slot when preferred is unassigned."""
        if   norm_density >= self.thresholds[0]: preferred = 0
        elif norm_density >= self.thresholds[1]: preferred = 1
        else:                                    preferred = 2
        for offset in [0, 1, 2, -1, -2]:
            idx = (preferred + offset) % 3
            if self.slots[idx]: return idx, self.slots[idx]
        return None, None

    def any_assigned(self):
        return any(s is not None for s in self.slots)


# ═══════════════════════════════════════════════════════
#  COLLISION GRID  (V7 — Retsin fabrication feasibility)
# ═══════════════════════════════════════════════════════
class CollisionGrid:
    """Lightweight 3-D spatial hash for per-run collision avoidance."""

    def __init__(self, cell_size):
        self._grid = {}
        self._cs   = max(cell_size, 0.001)

    def _key(self, pt):
        return (int(pt.X / self._cs), int(pt.Y / self._cs), int(pt.Z / self._cs))

    def add(self, pt):
        self._grid[self._key(pt)] = True

    def check(self, pt):
        """Return True if any neighbouring cell is already occupied."""
        k = self._key(pt)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    if (k[0]+dx, k[1]+dy, k[2]+dz) in self._grid:
                        return True
        return False


# ═══════════════════════════════════════════════════════
#  SOURCE & TARGET  (Phase 4 — unchanged from V6)
# ═══════════════════════════════════════════════════════
class Source:
    def __init__(self, pos):
        self.pos = Rhino.Geometry.Point3d(pos)


class Target:
    def __init__(self, pos, detect_radius=2.0):
        self.pos = Rhino.Geometry.Point3d(pos)
        self.detect_radius = detect_radius


# ═══════════════════════════════════════════════════════
#  ATTRACTOR  (unchanged from V6)
# ═══════════════════════════════════════════════════════
class Attractor:
    def __init__(self, center, strength=0.8, radius=5.0, decay_rate=0.0):
        self.center     = Rhino.Geometry.Point3d(center)
        self.strength   = strength
        self.radius     = radius
        self.decay_rate = decay_rate
        self.alive      = True
        self.age        = 0

    def get_influence_vector(self, agent_pos):
        to_center = self.center - agent_pos
        dist = to_center.Length
        if dist > self.radius or dist < 0.0001:
            return Rhino.Geometry.Vector3d(0, 0, 0)
        to_center.Unitize()
        return to_center * (self.strength * (1.0 - dist / self.radius))

    def update(self):
        self.age += 1
        self.strength *= (1.0 - self.decay_rate)
        if self.strength < 0.01:
            self.alive = False


# ═══════════════════════════════════════════════════════
#  PHEROMONE GRID  (unchanged from V6)
# ═══════════════════════════════════════════════════════
class PheromoneGrid:
    def __init__(self, cell_size=0.5):
        self.grid      = {}
        self.cell_size = cell_size

    def _key(self, pt):
        cs = self.cell_size
        return (int(math.floor(pt.X / cs)),
                int(math.floor(pt.Y / cs)),
                int(math.floor(pt.Z / cs)))

    def deposit(self, pt, amount):
        k = self._key(pt)
        self.grid[k] = self.grid.get(k, 0.0) + amount

    def evaporate(self, rate):
        for k in list(self.grid.keys()):
            self.grid[k] *= (1.0 - rate)

    def prune(self, threshold=0.001):
        for k in [k for k, v in self.grid.items() if v <= threshold]:
            del self.grid[k]

    def sample_gradient(self, pt):
        ix, iy, iz = self._key(pt)
        grad = Rhino.Geometry.Vector3d(0, 0, 0)
        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            val = self.grid.get((ix+dx, iy+dy, iz+dz), 0.0)
            grad += Rhino.Geometry.Vector3d(dx, dy, dz) * val
        if grad.Length > 0.0001: grad.Unitize()
        return grad

    def get_value(self, pt):
        return self.grid.get(self._key(pt), 0.0)

    def clear(self):
        self.grid = {}


# ═══════════════════════════════════════════════════════
#  PHEROMONE GRID MULTI-LAYER  (unchanged from V6)
# ═══════════════════════════════════════════════════════
class PheromoneGridMultiLayer:
    def __init__(self, num_layers=1, cell_size=0.5):
        self.num_layers = max(1, num_layers)
        self.layers     = [PheromoneGrid(cell_size) for _ in range(self.num_layers)]
        self.cell_size  = cell_size

    def deposit(self, pt, amount, layer_idx=0):
        self.layers[max(0, min(layer_idx, self.num_layers-1))].deposit(pt, amount)

    def deposit_all(self, pt, amount):
        for layer in self.layers: layer.deposit(pt, amount)

    def evaporate(self, rate):
        for layer in self.layers: layer.evaporate(rate)

    def prune(self, threshold=0.001):
        for layer in self.layers: layer.prune(threshold)

    def sample_gradient(self, pt, layer_idx=0):
        return self.layers[max(0, min(layer_idx, self.num_layers-1))].sample_gradient(pt)

    def sample_gradient_blended(self, pt):
        if self.num_layers == 1: return self.layers[0].sample_gradient(pt)
        blend = Rhino.Geometry.Vector3d(0, 0, 0)
        for layer in self.layers: blend += layer.sample_gradient(pt)
        if blend.Length > 0.0001: blend.Unitize()
        return blend

    def get_value(self, pt, layer_idx=0):
        return self.layers[max(0, min(layer_idx, self.num_layers-1))].get_value(pt)

    def clear(self):
        for layer in self.layers: layer.clear()


# ═══════════════════════════════════════════════════════
#  DISPLAY CONDUIT  (unchanged from V6)
# ═══════════════════════════════════════════════════════
class PheromoneConduit(Rhino.Display.DisplayConduit):
    def __init__(self):
        super().__init__()
        self.pheromone_grid  = None
        self.agents          = []
        self.attractors      = []
        self.sources         = []
        self.targets         = []
        self.show_field      = True
        self.show_attractors = True
        self.foraging_mode   = False
        self.theme_idx       = 0    # index into HEATMAP_THEMES

    def DrawOverlay(self, e):
        if self.show_field and self.pheromone_grid:
            g = self.pheromone_grid
            is_multi = isinstance(g, PheromoneGridMultiLayer)
            # ── resolve theme stops once per draw call ──────
            stops = HEATMAP_THEMES[max(0, min(self.theme_idx, len(HEATMAP_THEMES)-1))][1]

            if is_multi:
                # Foraging: keep fixed blue/red for clarity regardless of theme
                # Normal: sample theme at t=1.0, 0.5, 0.0 for layers 0,1,2
                if self.foraging_mode:
                    lc = [(30,144,255),(255,60,60),(60,255,60)]
                else:
                    lc = [_theme_sample(stops, 1.0),
                          _theme_sample(stops, 0.5),
                          _theme_sample(stops, 0.0)]
                for li, layer in enumerate(g.layers):
                    if not layer.grid: continue
                    cs   = layer.cell_size
                    vals = list(layer.grid.values())
                    mx   = max(vals) if vals else 1.0
                    if mx < 0.001: mx = 1.0
                    rgb  = lc[min(li, len(lc)-1)]
                    for (ix,iy,iz), val in layer.grid.items():
                        if val < 0.01: continue
                        t   = min(val/mx, 1.0)
                        col = sd.Color.FromArgb(int(180*t), rgb[0], rgb[1], rgb[2])
                        pt  = Rhino.Geometry.Point3d((ix+.5)*cs,(iy+.5)*cs,(iz+.5)*cs)
                        e.Display.DrawPoint(pt, Rhino.Display.PointStyle.RoundSimple, 4, col)
            else:
                if g.grid:
                    cs   = g.cell_size
                    vals = list(g.grid.values())
                    mx   = max(vals) if vals else 1.0
                    if mx < 0.001: mx = 1.0
                    for (ix,iy,iz), val in g.grid.items():
                        if val < 0.01: continue
                        t   = min(val/mx, 1.0)
                        col = _theme_color(stops, t)
                        pt  = Rhino.Geometry.Point3d((ix+.5)*cs,(iy+.5)*cs,(iz+.5)*cs)
                        e.Display.DrawPoint(pt, Rhino.Display.PointStyle.RoundSimple, 4, col)

        if self.show_attractors:
            mag = sd.Color.FromArgb(255, 255, 0, 255)
            for a in self.attractors:
                if not a.alive: continue
                e.Display.DrawPoint(a.center, Rhino.Display.PointStyle.RoundControlPoint, 10, mag)
                try:
                    e.Display.DrawCurve(
                        Rhino.Geometry.Circle(a.center, a.radius).ToNurbsCurve(), mag, 2)
                except: pass

        cy = sd.Color.FromArgb(255, 0, 220, 255)
        for src in self.sources:
            e.Display.DrawPoint(src.pos, Rhino.Display.PointStyle.RoundControlPoint, 14, cy)
            try:
                e.Display.DrawCurve(
                    Rhino.Geometry.Circle(src.pos, 0.6).ToNurbsCurve(), cy, 2)
            except: pass

        gn = sd.Color.FromArgb(255, 0, 210, 80)
        for tgt in self.targets:
            e.Display.DrawPoint(tgt.pos, Rhino.Display.PointStyle.RoundControlPoint, 14, gn)
            try:
                e.Display.DrawCurve(
                    Rhino.Geometry.Circle(tgt.pos, tgt.detect_radius).ToNurbsCurve(), gn, 2)
            except: pass

        for a in self.agents:
            if not a.alive: continue
            if self.foraging_mode and a.phase == "returning":
                col = sd.Color.FromArgb(255, 255, 140, 0)
            else:
                col = sd.Color.FromArgb(255, 255, 230, 0)
            e.Display.DrawPoint(a.pos, Rhino.Display.PointStyle.X, 6, col)


# ═══════════════════════════════════════════════════════
#  AGENT  (unchanged from V6)
# ═══════════════════════════════════════════════════════
class Agent:
    def __init__(self, pos, lifetime=150):
        self.pos = Rhino.Geometry.Point3d(pos)
        self.vel = Rhino.Geometry.Vector3d(
            random.uniform(-1,1), random.uniform(-1,1), random.uniform(-1,1))
        if self.vel.Length > 0: self.vel.Unitize()
        self.history          = [Rhino.Geometry.Point3d(pos)]
        self.age              = 0
        self.lifetime         = lifetime
        self.alive            = True
        self.saturation_level = 0.0
        self.branch_id        = 0
        self.phase            = "explore"
        self.source_pos       = None
        self.branch_cooldown  = 0

    def _sense_3way(self, grid, sense_angle, sense_dist):
        rot_ax = Rhino.Geometry.Vector3d.ZAxis
        if abs(self.vel.Z) > 0.9:
            rot_ax = Rhino.Geometry.Vector3d.XAxis
        fwd   = Rhino.Geometry.Vector3d(self.vel)
        left  = Rhino.Geometry.Vector3d(self.vel)
        right = Rhino.Geometry.Vector3d(self.vel)
        left.Rotate( sense_angle, rot_ax)
        right.Rotate(-sense_angle, rot_ax)
        def _v(d):
            sp = self.pos + d * sense_dist
            if isinstance(grid, PheromoneGridMultiLayer): return grid.layers[0].get_value(sp)
            return grid.get_value(sp)
        vf, vl, vr = _v(fwd), _v(left), _v(right)
        if vl > vf and vl > vr: return left
        if vr > vf and vr > vl: return right
        return fwd

    def update(self, jitter, speed, grid, pheromone_weight, evap_rate,
               perf_vector, perf_weight,
               void_mode, void_brep, void_bbox, mass_breps, mass_bboxes,
               voxel_pts, voxel_unit,
               void_breps=None,
               deposit_amount=1.0, attractors=None, attractor_weight=0.0,
               surface_mesh=None,
               foraging_mode=False, targets=None, detect_radius=2.0,
               return_speed_mult=1.2, food_strength=2.0,
               branch_cooldown_max=10,
               use_discrete_sensors=False, sense_angle=0.35, sense_dist=1.5):

        if not self.alive: return
        if self.branch_cooldown > 0: self.branch_cooldown -= 1

        eff_speed   = speed
        eff_deposit = deposit_amount
        dep_layer   = 0

        if foraging_mode:
            if self.phase == "explore":
                if targets:
                    # Guard: agent must travel away from source before target
                    # detection activates — prevents immediate triggering at spawn
                    # when source and target are closer than detect_radius.
                    spawn_dist = (self.pos.DistanceTo(self.source_pos)
                                  if self.source_pos else detect_radius + 1.0)
                    if spawn_dist >= detect_radius * 0.5:
                        for tgt in targets:
                            if self.pos.DistanceTo(tgt.pos) < detect_radius:
                                self.phase = "returning"; break
            else:
                eff_speed   = speed * return_speed_mult
                eff_deposit = deposit_amount * food_strength
                dep_layer   = 1
                if self.source_pos:
                    to_src = self.source_pos - self.pos
                    if to_src.Length > 0.001:
                        to_src.Unitize()
                        self.vel = self.vel * 0.3 + to_src * 0.7
                        if self.vel.Length > 0.0001: self.vel.Unitize()
                if self.source_pos and \
                        self.pos.DistanceTo(self.source_pos) < max(detect_radius * 0.8, 0.5):
                    if isinstance(grid, PheromoneGridMultiLayer):
                        grid.deposit(self.pos, eff_deposit, dep_layer)
                    else:
                        grid.deposit(self.pos, eff_deposit)
                    self.alive = False; return

        self.vel += Rhino.Geometry.Vector3d(
            random.uniform(-jitter, jitter),
            random.uniform(-jitter, jitter),
            random.uniform(-jitter, jitter))

        if pheromone_weight > 0:
            if use_discrete_sensors:
                sd_dir = self._sense_3way(grid, sense_angle, sense_dist)
                self.vel += sd_dir * pheromone_weight
            else:
                if (foraging_mode and isinstance(grid, PheromoneGridMultiLayer)
                        and grid.num_layers > 1 and self.phase == "explore"):
                    grad = grid.sample_gradient(self.pos, layer_idx=1)
                elif isinstance(grid, PheromoneGridMultiLayer):
                    grad = grid.sample_gradient_blended(self.pos)
                else:
                    grad = grid.sample_gradient(self.pos)
                self.vel += grad * pheromone_weight
            if isinstance(grid, PheromoneGridMultiLayer):
                self.saturation_level = grid.layers[0].get_value(self.pos)
            else:
                self.saturation_level = grid.get_value(self.pos)

        if attractors and attractor_weight > 0:
            av = Rhino.Geometry.Vector3d(0, 0, 0)
            for a in attractors:
                if a.alive: av += a.get_influence_vector(self.pos)
            if av.Length > 0.0001:
                av.Unitize(); self.vel += av * attractor_weight

        if perf_vector is not None and perf_weight > 0:
            self.vel += perf_vector * perf_weight

        if self.vel.Length > 0.0001:
            self.vel.Unitize()
        else:
            self.vel = Rhino.Geometry.Vector3d(
                random.uniform(-1,1), random.uniform(-1,1), random.uniform(-1,1))
            self.vel.Unitize()

        candidate = self.pos + self.vel * eff_speed

        if void_mode == 0:
            active_breps = void_breps if void_breps else ([void_brep] if void_brep else [])
            if active_breps:
                candidate = self._confine_breps(candidate, active_breps)
        elif void_mode == 1 and void_bbox is not None:
            candidate = self._confine_bbox(candidate, void_bbox, mass_breps, mass_bboxes)
        elif void_mode == 2 and voxel_pts:
            candidate = self._confine_voxels(candidate, voxel_pts, voxel_unit)
        elif void_mode == 3 and surface_mesh is not None:
            candidate = self._confine_surface(candidate, surface_mesh)

        self.pos = candidate
        self.history.append(Rhino.Geometry.Point3d(self.pos))

        if isinstance(grid, PheromoneGridMultiLayer):
            grid.deposit(self.pos, eff_deposit, dep_layer)
        else:
            grid.deposit(self.pos, eff_deposit)

        self.age += 1
        if self.age >= self.lifetime: self.alive = False

    def _confine_brep(self, new_pos, brep):
        """Single-brep confine — delegates to list version."""
        return self._confine_breps(new_pos, [brep])

    def _confine_breps(self, new_pos, breps):
        """Confine to the union of multiple breps — bounce off nearest surface if outside all."""
        try:
            tol = sc.doc.ModelAbsoluteTolerance
            inside = any(b.IsPointInside(new_pos, tol, False) for b in breps)
            if not inside:
                best_dist = float('inf'); best_closest = None
                for b in breps:
                    cp = b.ClosestPoint(new_pos)
                    d  = new_pos.DistanceTo(cp)
                    if d < best_dist:
                        best_dist = d; best_closest = cp
                if best_closest is not None:
                    out_dir = new_pos - best_closest
                    if out_dir.Length > 0.0001:
                        ov = Rhino.Geometry.Vector3d(out_dir.X, out_dir.Y, out_dir.Z)
                        ov.Unitize()
                        self.vel -= ov * (2.0 * (self.vel * ov))
                        if self.vel.Length > 0.0001: self.vel.Unitize()
                return self.pos
        except: pass
        return new_pos

    def _confine_bbox(self, new_pos, bbox, mass_breps, mass_bboxes):
        x = max(bbox.Min.X, min(bbox.Max.X, new_pos.X))
        y = max(bbox.Min.Y, min(bbox.Max.Y, new_pos.Y))
        z = max(bbox.Min.Z, min(bbox.Max.Z, new_pos.Z))
        if x != new_pos.X: self.vel.X *= -1.0
        if y != new_pos.Y: self.vel.Y *= -1.0
        if z != new_pos.Z: self.vel.Z *= -1.0
        clamped = Rhino.Geometry.Point3d(x, y, z)
        if mass_bboxes:
            for mbb in mass_bboxes:
                if mbb.Contains(clamped):
                    cx=(mbb.Min.X+mbb.Max.X)*.5; cy=(mbb.Min.Y+mbb.Max.Y)*.5
                    cz=(mbb.Min.Z+mbb.Max.Z)*.5
                    ov=Rhino.Geometry.Vector3d(clamped.X-cx,clamped.Y-cy,clamped.Z-cz)
                    if ov.Length<0.0001: ov=Rhino.Geometry.Vector3d(1,0,0)
                    ov.Unitize()
                    self.vel -= ov*(2.0*(self.vel*ov))
                    if self.vel.Length>0.0001: self.vel.Unitize()
                    return self.pos
        if mass_breps:
            for mb in mass_breps:
                try:
                    if mb.IsPointInside(clamped, sc.doc.ModelAbsoluteTolerance, False):
                        closest = mb.ClosestPoint(clamped)
                        od = clamped - closest
                        if od.Length > 0.0001:
                            ov=Rhino.Geometry.Vector3d(od.X,od.Y,od.Z); ov.Unitize()
                            self.vel -= ov*(2.0*(self.vel*ov))
                            if self.vel.Length>0.0001: self.vel.Unitize()
                        return self.pos
                except: pass
        return clamped

    def _confine_voxels(self, new_pos, voxel_pts, voxel_unit):
        min_d = float('inf'); nearest = None
        for vp in voxel_pts:
            d = new_pos.DistanceTo(vp)
            if d < min_d: min_d = d; nearest = vp
        if nearest and min_d > voxel_unit:
            sv = Rhino.Geometry.Vector3d(
                nearest.X-new_pos.X, nearest.Y-new_pos.Y, nearest.Z-new_pos.Z)
            if sv.Length > 0.0001: sv.Unitize(); self.vel = sv
            return self.pos
        return new_pos

    def _confine_surface(self, new_pos, surface_mesh):
        if not surface_mesh or surface_mesh.Vertices.Count == 0: return new_pos
        cp = surface_mesh.ClosestPoint(new_pos)
        return cp if cp is not None else new_pos


# ═══════════════════════════════════════════════════════
#  TOP-LEVEL HELPERS  (V7 new)
# ═══════════════════════════════════════════════════════
def _apply_twist(frame, angle_deg):
    """Rotate a placement frame around its own Z-axis (= curve tangent) by angle_deg."""
    xf = Rhino.Geometry.Transform.Rotation(
        math.radians(angle_deg), frame.ZAxis, frame.Origin)
    f2 = Rhino.Geometry.Plane(frame)
    f2.Transform(xf)
    return f2


def _ensure_layer(full_name, color=None):
    """Get or create a Rhino layer by full path (:: separator). Returns layer index."""
    idx = sc.doc.Layers.FindByFullPath(full_name, -1)
    if idx >= 0:
        return idx
    parts      = full_name.split("::")
    parent_id  = System.Guid.Empty
    built_path = ""
    for i, part in enumerate(parts):
        built_path = (built_path + "::" + part) if built_path else part
        existing   = sc.doc.Layers.FindByFullPath(built_path, -1)
        if existing >= 0:
            parent_id = sc.doc.Layers[existing].Id
        else:
            new_layer = Rhino.DocObjects.Layer()
            new_layer.Name = part
            if parent_id != System.Guid.Empty:
                new_layer.ParentLayerId = parent_id
            if color and i == len(parts) - 1:
                new_layer.Color = color
            new_idx = sc.doc.Layers.Add(new_layer)
            if new_idx >= 0:
                parent_id = sc.doc.Layers[new_idx].Id
    final = sc.doc.Layers.FindByFullPath(full_name, -1)
    return final if final >= 0 else 0


# ═══════════════════════════════════════════════════════
#  MAIN FORM  (V7)
# ═══════════════════════════════════════════════════════
class MAS_Simulation_V8(forms.Form):

    def __init__(self):
        super().__init__()
        self.Title      = "MAS Stigmergy V8 — Edge Connector Aggregation"
        self.Padding    = drawing.Padding(10)
        self.Resizable  = True
        self.Topmost    = True
        self.ClientSize = drawing.Size(420, 900)

        # ── Simulation state ──────────────────────────────
        self.agents       = []
        self.attractors   = []
        self.sources      = []
        self.targets      = []
        self.is_running   = False
        self.void_brep    = None        # first brep (backward compat)
        self.void_breps   = []          # ALL picked breps for Mode 0 (multi-select)
        self.void_bbox    = None
        self.mass_breps   = []
        self.mass_bboxes  = []
        self.void_cells   = []
        self.voxel_pts    = []
        self.voxel_unit   = 1.0
        self.aggregated_ids      = []
        self.joint_ids           = []       # V8 — placed joint geometry ids
        self.noise_sources       = []
        self.surface_geo         = None
        self.surface_mesh        = None
        self.base_geo_id         = None     # V6 compat
        self.module_kit          = ModuleKit()   # V7
        self.joint_node_geo_id   = None     # V8 — end-cap node geometry (degree 1)
        self.joint_step_geo_id   = None     # V8 — step/pass-through joint (degree 2)
        self.joint_branch_geo_id = None     # V8 — branching hub geometry (degree 3+)

        self.pheromone_grid        = PheromoneGrid(cell_size=0.5)
        self.conduit               = PheromoneConduit()
        self.conduit.pheromone_grid = self.pheromone_grid
        self.conduit.agents        = self.agents
        self.conduit.attractors    = self.attractors
        self.conduit.sources       = self.sources
        self.conduit.targets       = self.targets

        self._build_ui()
        self._wire_events()
        self._update_void_ui(0)
        self._update_perf_ui(3)

    # ── Static geometry helpers (unchanged) ───────────────
    @staticmethod
    def _try_get_brep(geo):
        if geo is None: return None
        if isinstance(geo, Rhino.Geometry.Brep): return geo
        for conv in [
            lambda g: g.ToBrep(True) if isinstance(g, Rhino.Geometry.Extrusion) else None,
            lambda g: Rhino.Geometry.Brep.CreateFromMesh(g, True) if isinstance(g, Rhino.Geometry.Mesh) else None,
            lambda g: Rhino.Geometry.Brep.CreateFromSubD(g, 0) if isinstance(g, Rhino.Geometry.SubD) else None,
            lambda g: g.ToBrep() if hasattr(g,'ToBrep') else None,
        ]:
            try:
                b = conv(geo)
                if b: return b
            except: pass
        return None

    @staticmethod
    def _geo_to_mesh(geo):
        if geo is None: return None
        if isinstance(geo, Rhino.Geometry.Mesh): return geo
        mp = Rhino.Geometry.MeshingParameters.Default
        def _from_brep(b):
            meshes = Rhino.Geometry.Mesh.CreateFromBrep(b, mp)
            if meshes and len(meshes) > 0:
                m = Rhino.Geometry.Mesh()
                for x in meshes: m.Append(x)
                return m
            return None
        try:
            if isinstance(geo, Rhino.Geometry.Surface):
                m = Rhino.Geometry.Mesh.CreateFromSurface(geo)
                if m: return m
        except: pass
        try:
            if isinstance(geo, Rhino.Geometry.Brep):
                m = _from_brep(geo)
                if m: return m
        except: pass
        try:
            if isinstance(geo, Rhino.Geometry.Extrusion):
                b = geo.ToBrep(True)
                if b:
                    m = _from_brep(b)
                    if m: return m
        except: pass
        try:
            if isinstance(geo, Rhino.Geometry.SubD):
                m = Rhino.Geometry.Mesh.CreateFromSubD(geo, 0)
                if m: return m
        except: pass
        try:
            if isinstance(geo, Rhino.Geometry.Curve):
                mesh = Rhino.Geometry.Mesh()
                pts  = geo.DivideByCount(20, True)
                for t in pts: mesh.Vertices.Add(geo.PointAt(t))
                return mesh if mesh.Vertices.Count > 0 else None
        except: pass
        try:
            if isinstance(geo, Rhino.Geometry.Point):
                mesh = Rhino.Geometry.Mesh()
                mesh.Vertices.Add(geo.Location)
                return mesh
        except: pass
        return None

    @staticmethod
    def _centers_from_geo(geo):
        if geo is None: return []
        if isinstance(geo, Rhino.Geometry.Point): return [geo.Location]
        if isinstance(geo, Rhino.Geometry.Mesh):
            pts = []
            for i in range(geo.Faces.Count):
                f = geo.Faces[i]; v = geo.Vertices
                if f.IsQuad:
                    cx=(v[f.A].X+v[f.B].X+v[f.C].X+v[f.D].X)/4.0
                    cy=(v[f.A].Y+v[f.B].Y+v[f.C].Y+v[f.D].Y)/4.0
                    cz=(v[f.A].Z+v[f.B].Z+v[f.C].Z+v[f.D].Z)/4.0
                else:
                    cx=(v[f.A].X+v[f.B].X+v[f.C].X)/3.0
                    cy=(v[f.A].Y+v[f.B].Y+v[f.C].Y)/3.0
                    cz=(v[f.A].Z+v[f.B].Z+v[f.C].Z)/3.0
                pts.append(Rhino.Geometry.Point3d(cx,cy,cz))
            if pts: return pts
        try:
            bb = geo.GetBoundingBox(True)
            if bb.IsValid: return [bb.Center]
        except: pass
        return []

    def _voxelize_void(self):
        try: vsize = max(0.001, float(self.txt_vunit.Text))
        except: vsize = 1.0
        self.voxel_unit = vsize
        if not self.void_bbox or not self.void_bbox.IsValid: return []
        bb = self.void_bbox; cells = []
        x = bb.Min.X + vsize*0.5
        while x < bb.Max.X:
            y = bb.Min.Y + vsize*0.5
            while y < bb.Max.Y:
                z = bb.Min.Z + vsize*0.5
                while z < bb.Max.Z:
                    pt = Rhino.Geometry.Point3d(x,y,z)
                    in_mass = any(mbb.Contains(pt) for mbb in self.mass_bboxes)
                    if not in_mass and self.mass_breps:
                        in_mass = any(
                            mb.IsPointInside(pt, sc.doc.ModelAbsoluteTolerance, False)
                            for mb in self.mass_breps)
                    if not in_mass: cells.append(pt)
                    z += vsize
                y += vsize
            x += vsize
        return cells

    # ── Collapsible section factory ────────────────────────
    def _make_section(self, title, bg_color, rows, collapsed=False):
        hdr = forms.Button()
        hdr.Text = ("▶  " if collapsed else "▼  ") + title
        hdr.BackgroundColor = bg_color
        hdr.TextColor = drawing.Colors.White
        inner = forms.DynamicLayout()
        inner.Spacing = drawing.Size(5, 3)
        inner.Padding = drawing.Padding(6, 3, 6, 6)
        for row in rows:
            r = [c for c in row if c is not None]
            if r: inner.AddRow(*r)
        pnl = forms.Panel()
        pnl.Content = inner
        pnl.Visible = not collapsed
        _t = title
        def _toggle(s, e, _b=hdr, _p=pnl, _title=_t):
            _p.Visible = not _p.Visible
            _b.Text = ("▼  " if _p.Visible else "▶  ") + _title
        hdr.Click += _toggle
        return hdr, pnl

    # ── Build UI ───────────────────────────────────────────
    def _build_ui(self):
        bold  = drawing.Font("Segoe UI", 9, drawing.FontStyle.Bold)
        GD    = drawing.Color.FromArgb(15,  10,  35)
        GPURP = drawing.Color.FromArgb(120, 40, 200)
        GCYAN = drawing.Color.FromArgb(0,  210, 230)
        GPINK = drawing.Color.FromArgb(220, 20, 130)
        GBLUE = drawing.Color.FromArgb(30, 130, 240)
        GTEXT = drawing.Color.FromArgb(210,210,240)
        GACC  = drawing.Color.FromArgb(100,190,255)
        GGRN  = drawing.Color.FromArgb(0,  180,100)
        GTEAL = drawing.Color.FromArgb(0,  140,160)
        GDARK = drawing.Color.FromArgb(60,  60,  90)
        GDIM  = drawing.Color.FromArgb(130,130,155)   # description hint colour
        self.BackgroundColor = GD

        def lbl(text, color=GTEXT):
            l = forms.Label(); l.Text = text; l.TextColor = color; return l
        def d(text):   # inline description helper
            return lbl(f"  ↳ {text}", GDIM)
        def T(v):
            t = forms.TextBox(); t.Text = v; return t
        def B(text, color):
            b = forms.Button(); b.Text = text; b.BackgroundColor = color; return b
        def chk(text, checked=False):
            c = forms.CheckBox(); c.Text = text; c.TextColor = GACC
            c.Checked = checked; return c
        def dd(*items):
            dr = forms.DropDown()
            for i in items: dr.Items.Add(i)
            dr.SelectedIndex = 0; return dr

        # ── PRESETS ───────────────────────────────────────
        lbl_ph = lbl("◈  PRESET TEMPLATES", GCYAN); lbl_ph.Font = bold
        self.dd_preset = dd(
            "Custom (manual)",
            "1 — Radial Cluster",
            "2 — Linear Flow",
            "3 — Shortest Path (Foraging)",
            "4 — Dispersed Network",
            "5 — Terrain-Sensitive",
            "6 — Tectonic 60³ mm  (1:1000 ★)")
        self.dd_preset.SelectedIndex = 6   # default to Tectonic preset
        self.btn_apply_preset = B("Apply Preset", GPURP)
        self.lbl_preset_hint  = lbl("", GGRN)

        # ── VOID MODE ──────────────────────────────────────
        lbl_vh = lbl("◈  VOID MODE  — Step 1", GCYAN); lbl_vh.Font = bold
        self.dd_void = dd("A: Brep (void container)",
                          "B: BBox − Mass geometry",
                          "C: Voxel layer points",
                          "D: Surface-Based")
        self.btn_void_input       = B("Select Void Brep", GBLUE)
        self.btn_bbox_container   = B("1. Select Container Box (outer boundary)", GBLUE)
        self.btn_bbox_mass        = B("2. Select Mass to Exclude (inside box)", GPURP)
        self.lbl_bbox_container   = lbl("— no container set", GDIM)
        self.lbl_layer_row        = lbl("Layer (partial name):", GTEXT)
        self.txt_layer            = T("Corridor_Void")
        self.btn_pick_voxels      = B("OR: Select Voxel Objects", GPURP)
        self.lbl_vunit_row        = lbl("Grid Size:", GTEXT)
        self.txt_vunit            = T("3.0")
        self.lbl_void_cells       = lbl("", GACC)
        self.lbl_void_status      = lbl("No void defined", GCYAN)

        # ── PERFORMANCE MODE ───────────────────────────────
        lbl_perf_h = lbl("◈  PERFORMANCE MODE", GPINK); lbl_perf_h.Font = bold
        self.dd_perf = dd("Light Filter",
                          "Acoustic (noise source)",
                          "Wind Break",
                          "Stigmergy Only")
        self.dd_perf.SelectedIndex = 3
        self.lbl_vec  = lbl("Vector X / Y / Z:", GTEXT)
        self.txt_vx = T("0"); self.txt_vy = T("0"); self.txt_vz = T("-1")
        self.btn_pick_src   = B("Add Noise Source", GPINK)
        self.btn_clear_srcs = B("Clear Sources",    GPINK)
        self.lbl_src        = lbl("0 source points", GACC)
        self.lbl_pw = lbl("Perf Weight:", GTEXT)
        self.txt_perf_w = T("0.4")

        # ── EXPLORATION (collapsible) ──────────────────────
        self.txt_agents = T("20");   self.txt_steps  = T("250")
        self.txt_jitter = T("0.35"); self.txt_speed  = T("1.5")
        self.txt_seed   = T("0")
        hdr_exp, self.pnl_exp = self._make_section("EXPLORATION", GBLUE, [
            [d("Controls how agents move and explore the simulation space")],
            [lbl("Agents:",GTEXT), self.txt_agents],
            [d("Total agents spawned per run")],
            [lbl("Steps:",GTEXT), self.txt_steps],
            [d("Max lifespan — steps each agent lives")],
            [lbl("Jitter:",GTEXT), self.txt_jitter],
            [d("Random noise (0=straight, 1=fully chaotic)")],
            [lbl("Speed:",GTEXT), self.txt_speed],
            [d("Distance moved per simulation step")],
            [lbl("Seed (0=random):",GTEXT), self.txt_seed],
            [d("Same seed = identical output every run")],
        ], collapsed=False)

        # ── TRAIL (collapsible) ────────────────────────────
        self.txt_evap     = T("0.02"); self.txt_phero_w  = T("0.45")
        self.txt_deposit  = T("1.0");  self.txt_cellsize = T("1.0")
        self.txt_prune    = T("0.005")
        self.dd_layers    = dd("1 Layer (default)", "2 Layers", "3 Layers")
        hdr_trail, self.pnl_trail = self._make_section("TRAIL", GPURP, [
            [d("Pheromone accumulation and decay settings")],
            [lbl("Evaporation:",GTEXT), self.txt_evap],
            [d("Fade rate per step — higher = trails disappear faster")],
            [lbl("Phero Weight:",GTEXT), self.txt_phero_w],
            [d("How strongly agents follow existing trails (0=ignore)")],
            [lbl("Deposit Amount:",GTEXT), self.txt_deposit],
            [d("Pheromone added per step — higher = stronger trails")],
            [lbl("Cell Size:",GTEXT), self.txt_cellsize],
            [d("Pheromone grid resolution (smaller = finer, more memory)")],
            [lbl("Prune Threshold:",GTEXT), self.txt_prune],
            [d("Cells below this value are removed to save memory")],
            [lbl("Pheromone Layers:",GTEXT), self.dd_layers],
            [d("Independent scent channels — Foraging: L0=outbound, L1=return")],
        ], collapsed=False)

        # ── STEERING (collapsible, starts collapsed) ───────
        self.btn_add_attractor    = B("Add Attractor",    GPINK)
        self.btn_clear_attractors = B("Clear Attractors", GPINK)
        self.lbl_attractors       = lbl("0 attractors", GACC)
        self.txt_attr_strength    = T("0.8"); self.txt_attr_radius = T("8.0")
        self.txt_attr_decay       = T("0.0"); self.txt_attr_weight = T("0.5")
        hdr_steer, self.pnl_steer = self._make_section("STEERING", GPINK, [
            [d("Attractor points pull agents toward specific zones")],
            [self.btn_add_attractor, self.btn_clear_attractors],
            [d("Pick point in viewport — renders as magenta sphere")],
            [self.lbl_attractors],
            [lbl("Attr Strength:",GTEXT), self.txt_attr_strength],
            [d("Pull intensity 0–1")],
            [lbl("Attr Radius:",GTEXT),   self.txt_attr_radius],
            [d("Influence distance — agents outside are unaffected")],
            [lbl("Attr Decay:",GTEXT),    self.txt_attr_decay],
            [d("Rate attractor fades per step (0 = permanent)")],
            [lbl("Attr Weight:",GTEXT),   self.txt_attr_weight],
            [d("How strongly agents veer toward attractors (0–1)")],
        ], collapsed=True)

        # ── FORAGING (collapsible, starts collapsed) ───────
        self.chk_foraging_mode = chk("Enable Source Foraging Mode (ant/slime)", False)
        self.btn_add_source    = B("Add Source (cyan)",       GCYAN)
        self.btn_add_target    = B("Add Target (green)",      GGRN)
        self.btn_clear_src_tgt = B("Clear Sources & Targets", GPURP)
        self.lbl_src_tgt_count = lbl("0 sources  |  0 targets", GACC)
        self.txt_detect_radius = T("8.0")
        self.txt_return_speed  = T("1.5")
        self.txt_food_strength = T("3.0")
        hdr_forage, self.pnl_forage = self._make_section("FORAGING  (Phase 4)", GTEAL, [
            [self.chk_foraging_mode],
            [d("Ant/slime mode — spawn at Sources, find Targets, return with trail")],
            [self.btn_add_source, self.btn_add_target],
            [d("Source (cyan): spawn point.  Target (green): food zone")],
            [self.btn_clear_src_tgt],
            [self.lbl_src_tgt_count],
            [lbl("Detect Radius:",GTEXT), self.txt_detect_radius],
            [d("Distance to detect a Target as 'reached' and begin return")],
            [lbl("Return Speed ×:",GTEXT), self.txt_return_speed],
            [d("Speed multiplier for agents heading home")],
            [lbl("Food Strength ×:",GTEXT), self.txt_food_strength],
            [d("Pheromone multiplier on return path — reinforces shortest route")],
        ], collapsed=True)

        # ── BRANCHING (collapsible, starts collapsed) ──────
        self.chk_branch          = chk("Enable Agent Branching", False)
        self.txt_branch_thresh   = T("0.4"); self.txt_branch_prob     = T("0.04")
        self.txt_branch_cooldown = T("15");  self.txt_max_agents      = T("60")
        hdr_branch, self.pnl_branch = self._make_section("BRANCHING  (Phase 3)", GPURP, [
            [self.chk_branch],
            [d("Agents split when local pheromone exceeds threshold")],
            [lbl("Threshold:",GTEXT),   self.txt_branch_thresh],
            [d("Min saturation before branching is allowed")],
            [lbl("Probability:",GTEXT), self.txt_branch_prob],
            [d("Chance of splitting per step (0.05 = 5%)")],
            [lbl("Cooldown (steps):",GTEXT), self.txt_branch_cooldown],
            [d("Min steps between splits for same agent")],
            [lbl("Max Agents:",GTEXT),  self.txt_max_agents],
            [d("Hard population cap — prevents runaway growth")],
        ], collapsed=True)

        # ── SENSORS (collapsible, starts collapsed) ────────
        self.chk_discrete_sensors = chk("3-Sensor Mode (Physarum/Lague style)", False)
        self.txt_sense_angle = T("0.35"); self.txt_sense_dist = T("3.0")
        hdr_sens, self.pnl_sens = self._make_section("SENSORS  (Physarum bonus)", GDARK, [
            [self.chk_discrete_sensors],
            [d("3-sensor steering — left/fwd/right — steers to highest concentration")],
            [lbl("Sense Angle (rad):",GTEXT), self.txt_sense_angle],
            [d("Radians between sensors and forward (0.35 ≈ 20°)")],
            [lbl("Sense Distance:",GTEXT),    self.txt_sense_dist],
            [d("How far ahead each sensor samples the pheromone field")],
        ], collapsed=True)

        # ── Run controls ───────────────────────────────────
        self.chk_show        = chk("Show Pheromone Heatmap", True)
        self.dd_heatmap_theme = dd(*[name for name, _ in HEATMAP_THEMES])
        self.btn_start       = B("▶  Initialize & Run", GBLUE)
        self.btn_stop        = B("■  Stop", GPINK)
        self.lbl_agent_count = lbl("", GACC)
        self.lbl_status      = lbl("Status: Ready", GACC)

        # ── Step 2 — Module Kit ────────────────────────────
        lbl_s2 = lbl("─── Step 2: Module Kit ───", GBLUE); lbl_s2.Font = bold
        self.btn_create_x   = B("Option A: Create 3D X Module",    GPURP)
        self.btn_select_geo = B("Option B: Select Custom Geometry", GPURP)
        # V7 slot buttons
        self.btn_slot_a  = B("Assign Module A", GPURP)
        self.btn_slot_b  = B("Assign Module B", GPURP)
        self.btn_slot_c  = B("Assign Module C", GPURP)
        self.lbl_slot_a  = lbl("— empty", GDIM)
        self.lbl_slot_b  = lbl("— empty", GDIM)
        self.lbl_slot_c  = lbl("— empty", GDIM)
        self.txt_thresh_ab = T("0.6")
        self.txt_thresh_bc = T("0.3")

        # ── Step 3 — Output ────────────────────────────────
        lbl_s3 = lbl("─── Step 3: Output ───", GPINK); lbl_s3.Font = bold
        self.dd_agg_mode = dd(
            "Trail",
            "Field",
            "Cluster",
            "Connector")
        self.dd_agg_mode.SelectedIndex = 3   # Connector is default
        self.dd_rotation_mode = dd(
            "None",
            "Random  (0/90/180/270°)",
            "Alternating  (0°/180° zigzag)",
            "Phase-Based  (explore=0° / return=180°)",
            "Pheromone-Driven  (density × 360°)")
        self.txt_spacing   = T("1.5")
        self.chk_adaptive  = chk("Adaptive Fit  (auto-space from bbox)", True)
        self.chk_density   = chk("Scale by pheromone density", True)
        self.txt_scale_min = T("0.6"); self.txt_scale_max = T("1.4")
        self.chk_collision = chk("Avoid collisions", False)
        self.dd_collision_response = dd(
            "Skip",
            "Jitter (offset + retry)")
        self.chk_use_layers = chk("Bake to Layers  (A / B / C)", False)
        self.btn_aggregate        = B("Aggregate Modules",        GPURP)
        self.btn_gen_mesh         = B("Generate Mesh Skin",       GPURP)
        self.btn_clear_aggregated = B("Clear Aggregated Modules", GGRN)
        self.btn_clear            = B("Clear Trails",             GCYAN)
        self.btn_clear_geo        = B("Clear All Geometry",       GCYAN)

        # ── Joint Generation (V8) ─────────────────────────
        lbl_joint_h = lbl("─── Joint Generation ───", GCYAN); lbl_joint_h.Font = bold
        self.chk_joint_mode    = chk("Generate Joints at nodes", False)
        self.btn_joint_node    = B("Pick Node Geometry  (end caps)", GPURP)
        self.lbl_joint_node    = lbl("— empty", GDIM)
        self.txt_node_scale    = T("1.0")
        self.lbl_node_autofit  = lbl("Auto: —", GDIM)
        self.btn_joint_step    = B("Pick Step Geometry  (mid-connectors)", GPURP)
        self.lbl_joint_step    = lbl("— empty", GDIM)
        self.txt_step_scale    = T("1.0")
        self.lbl_step_autofit  = lbl("Auto: —", GDIM)
        self.btn_joint_branch  = B("Pick Branch Geometry  (hubs)", GPURP)
        self.lbl_joint_branch  = lbl("— empty", GDIM)
        self.txt_branch_scale  = T("1.0")
        self.lbl_branch_autofit = lbl("Auto: —", GDIM)
        self.btn_autofit_joints = B("Auto-Fit All Scales", GTEAL)
        self.btn_clear_joints   = B("Clear Joints", GGRN)
        self.lbl_joint_h_ref   = lbl_joint_h

        # ── helper: two equal columns ──────────────────────
        def row2(la, ca, lb, cb):
            """Return a panel with two label+control pairs side by side."""
            p = forms.DynamicLayout(); p.Spacing = drawing.Size(4, 2)
            p.BeginHorizontal()
            inner_a = forms.DynamicLayout(); inner_a.Spacing = drawing.Size(2, 2)
            inner_a.AddRow(la); inner_a.AddRow(ca)
            inner_b = forms.DynamicLayout(); inner_b.Spacing = drawing.Size(2, 2)
            inner_b.AddRow(lb); inner_b.AddRow(cb)
            p.Add(inner_a); p.Add(inner_b)
            p.EndHorizontal()
            return p

        # ── Assemble main layout ───────────────────────────
        L = forms.DynamicLayout()
        L.Spacing = drawing.Size(4, 3)

        # PRESETS
        L.AddRow(lbl_ph)
        L.AddRow(d("Quick-start templates — auto-fills all parameters"))
        L.AddRow(self.dd_preset, self.btn_apply_preset)
        L.AddRow(self.lbl_preset_hint)

        # VOID MODE
        L.AddRow(lbl_vh)
        L.AddRow(d("Defines the simulation space where agents move"))
        L.AddRow(self.dd_void)
        L.AddRow(d("A=Brep interior  B=BBox−mass  C=Voxel layer  D=Surface"))
        # Mode A / C / D button
        L.AddRow(self.btn_void_input)
        # Mode B — two-step: pick container box, then pick masses to exclude
        L.AddRow(self.btn_bbox_container)
        L.AddRow(self.lbl_bbox_container)
        L.AddRow(d("Mode B step 1 — pick any box/brep as the outer simulation boundary"))
        L.AddRow(self.btn_bbox_mass)
        L.AddRow(d("Mode B step 2 — pick solid geometry inside the box to exclude (optional)"))
        L.AddRow(self.lbl_layer_row, self.txt_layer)
        L.AddRow(self.btn_pick_voxels)
        L.AddRow(self.lbl_vunit_row, self.txt_vunit)
        L.AddRow(d("Grid Size: voxel resolution for Mode B/C"))
        L.AddRow(self.lbl_void_status)
        L.AddRow(self.lbl_void_cells)

        # PERFORMANCE MODE
        L.AddRow(lbl_perf_h)
        L.AddRow(d("Optional global bias force added to agent steering"))
        L.AddRow(self.dd_perf)
        L.AddRow(d("Light: perpendicular to sun.  Acoustic: away from source.  Wind: along vector"))
        L.AddRow(lbl("Vector  X / Y / Z:", GTEXT))
        L.AddRow(self.txt_vx, self.txt_vy, self.txt_vz)
        L.AddRow(d("Direction for sun / wind — normalised automatically"))
        L.AddRow(self.btn_pick_src, self.btn_clear_srcs)
        L.AddRow(self.lbl_src)
        L.AddRow(lbl("Perf Weight:", GTEXT), self.txt_perf_w)
        L.AddRow(d("0 = ignore, 1 = agents fully driven by performance force"))

        # Collapsible sections
        L.AddRow(hdr_exp);    L.AddRow(self.pnl_exp)
        L.AddRow(hdr_trail);  L.AddRow(self.pnl_trail)
        L.AddRow(hdr_steer);  L.AddRow(self.pnl_steer)
        L.AddRow(hdr_forage); L.AddRow(self.pnl_forage)
        L.AddRow(hdr_branch); L.AddRow(self.pnl_branch)
        L.AddRow(hdr_sens);   L.AddRow(self.pnl_sens)

        # Run
        L.AddRow(self.chk_show)
        L.AddRow(d("Pheromone heatmap overlay in viewport (blue=low, red=high)"))
        L.AddRow(lbl("Heatmap Theme:", GTEXT))
        L.AddRow(self.dd_heatmap_theme)
        L.AddRow(d("Colour palette — low density = first colour, high density = last colour"))
        L.AddRow(self.btn_start, self.btn_stop)
        L.AddRow(self.lbl_agent_count)
        L.AddRow(self.lbl_status)

        # STEP 2 — Module Kit
        L.AddRow(lbl_s2)
        L.AddRow(d("Up to 3 module types — density decides which is placed"))
        L.AddRow(self.btn_create_x, self.btn_select_geo)
        L.AddRow(d("Option A: built-in X module.  Option B: pick Rhino geometry (→ Slot A)"))

        # Slot rows: button + status on same line, description below
        L.AddRow(lbl("Module A — Primary:", GTEXT))
        L.AddRow(self.btn_slot_a, self.lbl_slot_a)
        L.AddRow(d("HIGH density zones — structural / main elements"))

        L.AddRow(lbl("Module B — Secondary:", GTEXT))
        L.AddRow(self.btn_slot_b, self.lbl_slot_b)
        L.AddRow(d("MEDIUM density — infill / transitional elements"))

        L.AddRow(lbl("Module C — Accent:", GTEXT))
        L.AddRow(self.btn_slot_c, self.lbl_slot_c)
        L.AddRow(d("LOW density — edge caps / terminal / accent elements"))

        L.AddRow(row2(lbl("Thresh A→B:", GTEXT), self.txt_thresh_ab,
                      lbl("Thresh B→C:", GTEXT), self.txt_thresh_bc))
        L.AddRow(d("Normalised density (0–1) cutoffs for module type switching"))

        # STEP 3 — Output
        L.AddRow(lbl_s3)
        L.AddRow(d("Configure geometry placement from simulation results"))

        L.AddRow(lbl("Aggregation Mode:", GTEXT))
        L.AddRow(self.dd_agg_mode)
        L.AddRow(d("Trail: along curves.  Field: volumetric fill.  Cluster: rings at attractors.  Connector: spans history point pairs (default — stable orientation)"))

        L.AddRow(lbl("Rotation Mode:", GTEXT))
        L.AddRow(self.dd_rotation_mode)
        L.AddRow(d("Twist around curve-tangent axis — combinatorial variety (Sanchez)"))

        L.AddRow(lbl("Spacing / Field Threshold:", GTEXT), self.txt_spacing)
        L.AddRow(d("Trail: arc-length gap.  Field: min pheromone floor (0–1 normalised)"))

        L.AddRow(self.chk_adaptive)
        L.AddRow(d("Auto-sets spacing = module bbox length → zero-gap tiling"))

        L.AddRow(self.chk_density)
        L.AddRow(d("Larger modules at dense trails, smaller at low-density edges"))

        L.AddRow(row2(lbl("Scale Min:", GTEXT), self.txt_scale_min,
                      lbl("Scale Max:", GTEXT), self.txt_scale_max))
        L.AddRow(d("Scale range applied by density.  1.0 = original size"))

        L.AddRow(self.chk_collision)
        L.AddRow(d("Spatial overlap check before placing (Retsin fabrication logic)"))
        L.AddRow(lbl("Collision Response:", GTEXT))
        L.AddRow(self.dd_collision_response)
        L.AddRow(d("Skip = don't place.  Jitter = offset slightly and retry once"))

        L.AddRow(self.chk_use_layers)
        L.AddRow(d("A/B/C onto SWM_Agg::Primary / Secondary / Accent layers"))

        L.AddRow(self.btn_aggregate)
        L.AddRow(self.btn_gen_mesh)
        L.AddRow(self.btn_clear_aggregated)
        L.AddRow(d("Removes last Aggregate run only — trails and other geometry stay"))
        L.AddRow(self.btn_clear, self.btn_clear_geo)
        L.AddRow(d("Clear Trails: curves only.  Clear All: curves + breps + meshes"))

        # ── JOINT GENERATION ──────────────────────────────
        L.AddRow(self.lbl_joint_h_ref)
        L.AddRow(self.chk_joint_mode)
        L.AddRow(d("Offsets connectors + places geometry at endpoints (Node) and branch hubs"))

        L.AddRow(lbl("Node  (degree 1 — end cap):", GTEXT))
        L.AddRow(self.btn_joint_node, self.lbl_joint_node)
        L.AddRow(d("Placed at trail endpoints — oriented toward its one connecting branch"))
        L.AddRow(row2(lbl("Scale:", GTEXT), self.txt_node_scale,
                      lbl("", GTEXT), self.lbl_node_autofit))
        L.AddRow(d("1.0 = auto-fit from connector bbox.  Increase to enlarge joint"))

        L.AddRow(lbl("Step Joint  (degree 2 — mid-connection):", GTEXT))
        L.AddRow(self.btn_joint_step, self.lbl_joint_step)
        L.AddRow(d("Placed at every pass-through node — where one segment meets the next"))
        L.AddRow(row2(lbl("Scale:", GTEXT), self.txt_step_scale,
                      lbl("", GTEXT), self.lbl_step_autofit))
        L.AddRow(d("1.0 = auto-fit.  Oriented along the bisector of the two connecting segments"))

        L.AddRow(lbl("Branch Joint  (degree 3+ — hub):", GTEXT))
        L.AddRow(self.btn_joint_branch, self.lbl_joint_branch)
        L.AddRow(d("Placed at branching hubs — degree detected from agent history graph"))
        L.AddRow(row2(lbl("Scale:", GTEXT), self.txt_branch_scale,
                      lbl("", GTEXT), self.lbl_branch_autofit))
        L.AddRow(d("1.0 = auto-fit.  Branch count determines how many connectors offset from here"))

        L.AddRow(self.btn_autofit_joints)
        L.AddRow(d("Recomputes auto-fit scale from current connector module bbox"))
        L.AddRow(self.btn_clear_joints)
        L.AddRow(d("Removes only the joint geometry — connectors stay intact"))

        scrl = forms.Scrollable()
        scrl.Content = L
        self.Content = scrl

    # ── Wire events ────────────────────────────────────────
    def _wire_events(self):
        self.dd_void.SelectedIndexChanged   += self.OnVoidModeChanged
        self.btn_void_input.Click           += self.OnVoidInput
        self.btn_bbox_container.Click       += self.OnPickBBoxContainer
        self.btn_bbox_mass.Click            += self.OnPickBBoxMass
        self.dd_perf.SelectedIndexChanged   += self.OnPerfModeChanged
        self.btn_pick_src.Click             += self.OnPickNoiseSource
        self.btn_clear_srcs.Click           += self.OnClearNoiseSources
        self.btn_pick_voxels.Click          += self.OnPickVoxelObjects
        self.chk_show.CheckedChanged        += self.OnShowFieldChanged
        self.dd_heatmap_theme.SelectedIndexChanged += self.OnThemeChanged
        self.btn_start.Click                += self.OnStartClick
        self.btn_stop.Click                 += self.OnStopClick
        self.btn_add_attractor.Click        += self.OnAddAttractor
        self.btn_clear_attractors.Click     += self.OnClearAttractors
        self.btn_add_source.Click           += self.OnAddSource
        self.btn_add_target.Click           += self.OnAddTarget
        self.btn_clear_src_tgt.Click        += self.OnClearSrcTgt
        self.btn_apply_preset.Click         += self.OnApplyPreset
        self.btn_create_x.Click             += self.OnCreateX
        self.btn_select_geo.Click           += self.OnSelectGeo
        self.btn_slot_a.Click               += self.OnSelectSlotA
        self.btn_slot_b.Click               += self.OnSelectSlotB
        self.btn_slot_c.Click               += self.OnSelectSlotC
        self.chk_adaptive.CheckedChanged    += self.OnAdaptiveToggle
        self.btn_aggregate.Click            += self.OnAggregate
        self.btn_gen_mesh.Click             += self.OnGenerateMesh
        self.btn_clear_aggregated.Click     += self.OnClearAggregated
        self.btn_clear.Click                += self.OnClearClick
        self.btn_joint_node.Click           += self.OnPickJointNode
        self.btn_joint_step.Click           += self.OnPickJointStep
        self.btn_joint_branch.Click         += self.OnPickJointBranch
        self.btn_autofit_joints.Click       += self.OnAutoFitJoints
        self.btn_clear_joints.Click         += self.OnClearJoints
        self.btn_clear_geo.Click            += self.OnClearGeoClick
        self.Closed                         += self.OnFormClosed

    # ── UI helpers ─────────────────────────────────────────
    def _update_void_ui(self, idx):
        is_layer  = idx == 2
        need_grid = idx in (1, 2)
        self.lbl_layer_row.Visible   = is_layer
        self.txt_layer.Visible       = is_layer
        self.btn_pick_voxels.Visible = is_layer
        self.lbl_vunit_row.Visible   = need_grid
        self.txt_vunit.Visible       = need_grid
        self.lbl_void_cells.Visible  = (idx == 1)
        labels = ["Select Void Brep","Select Mass Geometry",
                  "Load Voxel Layer","Select Surface Geometry"]
        self.btn_void_input.Text = labels[idx] if idx < len(labels) else "Select Geometry"

    def _update_perf_ui(self, idx):
        show_vec = idx in (0, 2); show_ac = idx == 1
        self.lbl_vec.Visible        = show_vec
        self.txt_vx.Visible         = show_vec
        self.txt_vy.Visible         = show_vec
        self.txt_vz.Visible         = show_vec
        self.btn_pick_src.Visible   = show_ac
        self.btn_clear_srcs.Visible = show_ac
        self.lbl_src.Visible        = show_ac

    # ── Event handlers ─────────────────────────────────────
    def OnVoidModeChanged(self, s, e):
        self._update_void_ui(self.dd_void.SelectedIndex)

    def OnPerfModeChanged(self, s, e):
        self._update_perf_ui(self.dd_perf.SelectedIndex)

    def OnShowFieldChanged(self, s, e):
        self.conduit.show_field = bool(self.chk_show.Checked)
        sc.doc.Views.Redraw()

    def OnThemeChanged(self, s, e):
        self.conduit.theme_idx = self.dd_heatmap_theme.SelectedIndex
        sc.doc.Views.Redraw()

    def OnVoidInput(self, s, e):
        mode = self.dd_void.SelectedIndex
        if mode == 0:
            self.lbl_status.Text = "Status: Select void container(s) — Shift/Ctrl to multi-select..."
            oids = rs.GetObjects("Select void container geometry (multiple allowed)", 0)
            if oids:
                self.void_breps = []; fallback_bbs = []
                for oid in oids:
                    obj = sc.doc.Objects.Find(oid)
                    if not obj: continue
                    brep = self._try_get_brep(obj.Geometry)
                    if brep:
                        self.void_breps.append(brep)
                    else:
                        bb = obj.Geometry.GetBoundingBox(True)
                        if bb.IsValid: fallback_bbs.append(bb)
                if self.void_breps:
                    self.void_brep = self.void_breps[0]   # backward compat
                    n_closed = sum(1 for b in self.void_breps if b.IsSolid)
                    self.lbl_void_status.Text = (
                        f"Void: {len(self.void_breps)} brep(s)  ({n_closed} closed)")
                    self.lbl_void_status.TextColor = drawing.Colors.Green
                elif fallback_bbs:
                    combined = fallback_bbs[0]
                    for bb in fallback_bbs[1:]:
                        combined = Rhino.Geometry.BoundingBox.Union(combined, bb)
                    self.void_bbox = combined
                    self.dd_void.SelectedIndex = 1
                    self.lbl_void_status.Text = f"Converted {len(fallback_bbs)} to BBox mode"
                else:
                    self.lbl_void_status.Text = "Could not read geometry"
                    self.lbl_void_status.TextColor = drawing.Colors.Red
        elif mode == 1:
            # Mode B uses the two dedicated buttons: OnPickBBoxContainer + OnPickBBoxMass
            # This fallback triggers if user clicks the old "Select Void Brep" button on Mode B
            self.lbl_void_status.Text = (
                "Mode B: use '1. Select Container Box' then '2. Select Mass to Exclude'")
            self.lbl_void_status.TextColor = drawing.Color.FromArgb(255, 200, 0)
        elif mode == 2:
            self._load_voxels_from_layer()
        elif mode == 3:
            self.lbl_status.Text = "Status: Select surface geometry (multiple allowed)..."
            oids = rs.GetObjects("Select surface geometry (multiple allowed)", 0)
            if oids:
                meshes = []
                for oid in oids:
                    obj = sc.doc.Objects.Find(oid)
                    if not obj: continue
                    m = self._geo_to_mesh(obj.Geometry)
                    if m and m.Vertices.Count > 0:
                        meshes.append(m)
                if meshes:
                    # Merge all surfaces into one mesh so downstream code is unchanged
                    merged = Rhino.Geometry.Mesh()
                    for m in meshes: merged.Append(m)
                    merged.Normals.ComputeNormals(); merged.Compact()
                    self.surface_mesh = merged
                    self.lbl_void_status.Text = (
                        f"Surface: {len(meshes)} object(s) — "
                        f"{merged.Vertices.Count} verts, {merged.Faces.Count} faces")
                    self.lbl_void_status.TextColor = drawing.Colors.Green
                else:
                    self.lbl_void_status.Text = "Conversion to mesh failed"
                    self.lbl_void_status.TextColor = drawing.Colors.Red

    def OnPickBBoxContainer(self, s, e):
        """Mode B step 1 — pick ANY geometry as the outer simulation boundary box."""
        self.lbl_status.Text = "Status: Pick container box (outer boundary)..."
        oid = rs.GetObject("Select container box / brep for outer simulation boundary", 0)
        if not oid: return
        obj = sc.doc.Objects.Find(oid)
        if not obj: return
        bb = obj.Geometry.GetBoundingBox(True)
        if not bb.IsValid:
            self.lbl_void_status.Text = "Container: invalid bbox"
            self.lbl_void_status.TextColor = drawing.Colors.Red
            return
        self.void_bbox = bb
        w = bb.Max.X - bb.Min.X
        d_ = bb.Max.Y - bb.Min.Y
        h  = bb.Max.Z - bb.Min.Z
        self.lbl_bbox_container.Text = f"✓ container  {w:.1f} × {d_:.1f} × {h:.1f}"
        self.lbl_bbox_container.TextColor = drawing.Color.FromArgb(0, 210, 80)
        # Re-voxelize with the new outer boundary
        self.lbl_status.Text = "Status: Voxelizing void..."
        Rhino.RhinoApp.Wait()
        self.void_cells = self._voxelize_void()
        n = len(self.void_cells)
        self.lbl_void_cells.Text = (
            f"→ {n} void cells" if n > 0 else "→ 0 cells — no mass selected yet or try larger Grid Size")
        self.lbl_void_cells.TextColor = drawing.Colors.Green if n > 0 else drawing.Colors.Yellow
        self.lbl_void_status.Text = f"Container set — {n} void cells"
        self.lbl_void_status.TextColor = drawing.Colors.Green
        sc.doc.Views.Redraw()

    def OnPickBBoxMass(self, s, e):
        """Mode B step 2 — pick solid mass geometry to exclude from the container."""
        self.lbl_status.Text = "Status: Select mass geometry to exclude..."
        oids = rs.GetObjects("Select solid mass geometry to exclude from container", 0)
        if not oids: return
        self.mass_breps = []; self.mass_bboxes = []
        for oid in oids:
            obj = sc.doc.Objects.Find(oid)
            if not obj: continue
            bb = obj.Geometry.GetBoundingBox(True)
            if bb.IsValid: self.mass_bboxes.append(bb)
            brep = self._try_get_brep(obj.Geometry)
            if brep and brep.IsSolid: self.mass_breps.append(brep)
        n_b = len(self.mass_breps); n_bb = len(self.mass_bboxes)
        self.lbl_void_status.Text = f"Masses: {n_bb} bbox(s), {n_b} precise brep(s)"
        self.lbl_void_status.TextColor = drawing.Colors.Green
        # Re-voxelize with updated mass exclusions
        self.lbl_status.Text = "Status: Re-voxelizing void..."
        Rhino.RhinoApp.Wait()
        self.void_cells = self._voxelize_void()
        n = len(self.void_cells)
        self.lbl_void_cells.Text = (
            f"→ {n} void cells" if n > 0 else "→ 0 cells — try larger Grid Size")
        self.lbl_void_cells.TextColor = drawing.Colors.Green if n > 0 else drawing.Colors.Red
        sc.doc.Views.Redraw()

    def _load_voxels_from_layer(self):
        try: self.voxel_unit = max(0.001, float(self.txt_vunit.Text))
        except: self.voxel_unit = 1.0
        search = self.txt_layer.Text.strip()
        self.voxel_pts = []
        idxs = {i for i in range(sc.doc.Layers.Count)
                if search.lower() in sc.doc.Layers[i].FullPath.lower()}
        if not idxs:
            self.lbl_void_status.Text = f"No layer matching '{search}'"
            self.lbl_void_status.TextColor = drawing.Colors.Red; return
        for obj in sc.doc.Objects:
            if obj.IsDeleted or obj.Attributes.LayerIndex not in idxs: continue
            for pt in self._centers_from_geo(obj.Geometry):
                self.voxel_pts.append(pt)
        n = len(self.voxel_pts)
        self.lbl_void_status.Text = f"{n} voxel centres from {len(idxs)} layer(s)"
        self.lbl_void_status.TextColor = drawing.Colors.Green if n > 0 else drawing.Colors.Red

    def OnPickVoxelObjects(self, s, e):
        oids = rs.GetObjects("Select voxel field objects", 0, group=True, preselect=False)
        if not oids: return
        try: self.voxel_unit = max(0.001, float(self.txt_vunit.Text))
        except: self.voxel_unit = 1.0
        self.voxel_pts = []
        for oid in oids:
            obj = sc.doc.Objects.Find(oid)
            if obj and not obj.IsDeleted:
                for pt in self._centers_from_geo(obj.Geometry):
                    self.voxel_pts.append(pt)
        n = len(self.voxel_pts)
        self.lbl_void_status.Text = f"{n} voxel centres from {len(oids)} objects"
        self.lbl_void_status.TextColor = drawing.Colors.Green if n > 0 else drawing.Colors.Red

    def OnPickNoiseSource(self, s, e):
        pt = rs.GetPoint("Pick acoustic noise source point")
        if pt:
            self.noise_sources.append(Rhino.Geometry.Point3d(pt.X, pt.Y, pt.Z))
            n = len(self.noise_sources)
            self.lbl_src.Text = f"{n} source point{'s' if n!=1 else ''}"

    def OnClearNoiseSources(self, s, e):
        self.noise_sources = []; self.lbl_src.Text = "0 source points"

    def OnAddAttractor(self, s, e):
        pt = rs.GetPoint("Pick attractor centre")
        if pt:
            try: strength = float(self.txt_attr_strength.Text)
            except: strength = 0.8
            try: radius   = float(self.txt_attr_radius.Text)
            except: radius   = 5.0
            try: decay    = float(self.txt_attr_decay.Text)
            except: decay    = 0.0
            self.attractors.append(Attractor(pt, strength, radius, decay))
            n = len(self.attractors)
            self.lbl_attractors.Text = f"{n} attractor{'s' if n!=1 else ''}"
            self.lbl_status.Text = f"Status: Attractor added ({n} total)"
            sc.doc.Views.Redraw()

    def OnClearAttractors(self, s, e):
        self.attractors.clear()
        self.lbl_attractors.Text = "0 attractors"
        sc.doc.Views.Redraw()

    def OnAddSource(self, s, e):
        pt = rs.GetPoint("Pick Source point (agents spawn here — cyan)")
        if pt:
            self.sources.append(Source(pt))
            self._update_src_tgt_lbl()
            sc.doc.Views.Redraw()
            self.lbl_status.Text = f"Status: Source added ({len(self.sources)} total)"

    def OnAddTarget(self, s, e):
        pt = rs.GetPoint("Pick Target/food zone (green — agents return from here)")
        if pt:
            try: dr = float(self.txt_detect_radius.Text)
            except: dr = 2.0
            self.targets.append(Target(pt, detect_radius=dr))
            self._update_src_tgt_lbl()
            sc.doc.Views.Redraw()
            self.lbl_status.Text = f"Status: Target added ({len(self.targets)} total)"

    def OnClearSrcTgt(self, s, e):
        self.sources.clear(); self.targets.clear()
        self._update_src_tgt_lbl()
        sc.doc.Views.Redraw()
        self.lbl_status.Text = "Status: Sources & Targets cleared"

    def _update_src_tgt_lbl(self):
        ns = len(self.sources); nt = len(self.targets)
        self.lbl_src_tgt_count.Text = (
            f"{ns} source{'s' if ns!=1 else ''}  |  {nt} target{'s' if nt!=1 else ''}")

    def OnApplyPreset(self, s, e):
        idx = self.dd_preset.SelectedIndex
        if idx == 0 or idx >= len(PRESETS):
            self.lbl_preset_hint.Text = "Custom — no changes made."; return
        p = PRESETS[idx]
        self.dd_void.SelectedIndex = p["void_mode"]; self._update_void_ui(p["void_mode"])
        self.dd_perf.SelectedIndex = p["perf_mode"]; self._update_perf_ui(p["perf_mode"])
        if "vx" in p: self.txt_vx.Text = p["vx"]
        if "vy" in p: self.txt_vy.Text = p["vy"]
        if "vz" in p: self.txt_vz.Text = p["vz"]
        self.txt_agents.Text  = p["agents"]; self.txt_steps.Text    = p["steps"]
        self.txt_jitter.Text  = p["jitter"]; self.txt_speed.Text    = p["speed"]
        self.txt_evap.Text    = p["evap"];   self.txt_phero_w.Text  = p["phero_w"]
        self.txt_deposit.Text = p["deposit"];self.txt_cellsize.Text = p["cellsize"]
        self.txt_prune.Text   = p["prune"]
        self.dd_layers.SelectedIndex   = p["layers"]
        self.txt_perf_w.Text           = p["perf_w"]
        self.txt_attr_weight.Text      = p["attr_weight"]
        self.chk_foraging_mode.Checked = p.get("foraging", False)
        self.chk_branch.Checked        = p.get("branch",   False)
        if "return_speed"    in p: self.txt_return_speed.Text    = p["return_speed"]
        if "food_strength"   in p: self.txt_food_strength.Text   = p["food_strength"]
        if "detect_radius"   in p: self.txt_detect_radius.Text   = p["detect_radius"]
        # Branching detail params
        if "branch_thresh"   in p: self.txt_branch_thresh.Text   = p["branch_thresh"]
        if "branch_prob"     in p: self.txt_branch_prob.Text     = p["branch_prob"]
        if "branch_cooldown" in p: self.txt_branch_cooldown.Text = p["branch_cooldown"]
        if "max_agents"      in p: self.txt_max_agents.Text      = p["max_agents"]
        # Sensor params
        if "sense_angle"     in p: self.txt_sense_angle.Text     = p["sense_angle"]
        if "sense_dist"      in p: self.txt_sense_dist.Text      = p["sense_dist"]
        # Attractor params
        if "attr_radius"     in p: self.txt_attr_radius.Text     = p["attr_radius"]
        # Grid / voxel
        if "vunit"           in p: self.txt_vunit.Text           = p["vunit"]
        # Aggregation output
        if "spacing"         in p: self.txt_spacing.Text         = p["spacing"]
        if "adaptive"        in p: self.chk_adaptive.Checked     = p["adaptive"]
        if "scale_min"       in p: self.txt_scale_min.Text       = p["scale_min"]
        if "scale_max"       in p: self.txt_scale_max.Text       = p["scale_max"]
        if p.get("foraging", False): self.pnl_forage.Visible = True
        if p.get("branch",   False): self.pnl_branch.Visible = True
        self.lbl_preset_hint.Text = f"Preset '{p['name']}' applied.  {p['hint']}"
        self.lbl_status.Text      = f"Status: Preset '{p['name']}' applied"

    def _compute_perf_vector(self, agent_pos):
        mode = self.dd_perf.SelectedIndex
        try:
            if mode == 0:
                v = Rhino.Geometry.Vector3d(float(self.txt_vx.Text),
                                            float(self.txt_vy.Text),
                                            float(self.txt_vz.Text))
                if v.Length > 0.0001:
                    v.Unitize()
                    perp = Rhino.Geometry.Vector3d(-v.Y, v.X, 0.0)
                    if perp.Length > 0.0001: perp.Unitize(); return perp
            elif mode == 1:
                if not self.noise_sources: return None
                blend = Rhino.Geometry.Vector3d(0,0,0)
                for src in self.noise_sources:
                    to_a = Rhino.Geometry.Vector3d(agent_pos - src)
                    dist = to_a.Length
                    if dist < 0.0001: continue
                    tang = Rhino.Geometry.Vector3d.CrossProduct(to_a, Rhino.Geometry.Vector3d.ZAxis)
                    if tang.Length > 0.0001:
                        tang.Unitize(); blend += tang * (1.0/dist)
                if blend.Length > 0.0001: blend.Unitize(); return blend
            elif mode == 2:
                v = Rhino.Geometry.Vector3d(float(self.txt_vx.Text),
                                            float(self.txt_vy.Text),
                                            float(self.txt_vz.Text))
                if v.Length > 0.0001:
                    v.Unitize()
                    perp = Rhino.Geometry.Vector3d.CrossProduct(v, Rhino.Geometry.Vector3d.ZAxis)
                    if perp.Length < 0.0001:
                        perp = Rhino.Geometry.Vector3d.CrossProduct(v, Rhino.Geometry.Vector3d.XAxis)
                    if perp.Length > 0.0001: perp.Unitize(); return perp
        except: pass
        return None

    def _get_spawn_point(self, void_mode, foraging_mode=False, src_index=0):
        if foraging_mode and self.sources:
            src = self.sources[src_index % len(self.sources)]
            return Rhino.Geometry.Point3d(src.pos)
        active_breps = self.void_breps if self.void_breps else \
                       ([self.void_brep] if self.void_brep else [])
        for _ in range(60):
            if void_mode == 0 and active_breps:
                # Pick a random brep from the set and sample inside its bbox
                b  = random.choice(active_breps)
                bb = b.GetBoundingBox(True)
                pt = Rhino.Geometry.Point3d(
                    random.uniform(bb.Min.X, bb.Max.X),
                    random.uniform(bb.Min.Y, bb.Max.Y),
                    random.uniform(bb.Min.Z, bb.Max.Z))
                tol = sc.doc.ModelAbsoluteTolerance
                if any(br.IsPointInside(pt, tol, False) for br in active_breps):
                    return pt
            elif void_mode == 1:
                if self.void_cells:
                    vp=random.choice(self.void_cells); hs=self.voxel_unit*0.4
                    return Rhino.Geometry.Point3d(
                        vp.X+random.uniform(-hs,hs),
                        vp.Y+random.uniform(-hs,hs),
                        vp.Z+random.uniform(-hs,hs))
                elif self.void_bbox:
                    bb=self.void_bbox
                    pt=Rhino.Geometry.Point3d(
                        random.uniform(bb.Min.X,bb.Max.X),
                        random.uniform(bb.Min.Y,bb.Max.Y),
                        random.uniform(bb.Min.Z,bb.Max.Z))
                    # Accept point if it's inside the container AND not inside any mass
                    in_mass = any(mbb.Contains(pt) for mbb in self.mass_bboxes)
                    if not in_mass: return pt
                    # If all bbox space is covered by masses (common when user selects
                    # the building as mass), fall back to bbox center — agents will
                    # navigate via _confine_bbox once simulation starts
                    return bb.Center
            elif void_mode == 2 and self.voxel_pts:
                vp=random.choice(self.voxel_pts); hs=self.voxel_unit*0.4
                return Rhino.Geometry.Point3d(
                    vp.X+random.uniform(-hs,hs),
                    vp.Y+random.uniform(-hs,hs),
                    vp.Z+random.uniform(-hs,hs))
            elif void_mode == 3 and self.surface_mesh:
                if self.surface_mesh.Vertices.Count > 0:
                    v = self.surface_mesh.Vertices[
                        random.randint(0, self.surface_mesh.Vertices.Count-1)]
                    return Rhino.Geometry.Point3d(v)
            else:
                return Rhino.Geometry.Point3d(
                    random.uniform(-2,2), random.uniform(-2,2), random.uniform(-2,2))
        if void_mode==0 and active_breps: return active_breps[0].GetBoundingBox(True).Center
        if void_mode==1:
            if self.void_cells: return random.choice(self.void_cells)
            if self.void_bbox:  return self.void_bbox.Center
        if void_mode==2 and self.voxel_pts: return self.voxel_pts[0]
        if void_mode==3 and self.surface_mesh and self.surface_mesh.Vertices.Count>0:
            return Rhino.Geometry.Point3d(self.surface_mesh.Vertices[0])
        return Rhino.Geometry.Point3d(0,0,0)

    def OnStartClick(self, s, e):
        if self.is_running: return
        try: n_agents  = int(self.txt_agents.Text)
        except: n_agents = 40
        try: lifetime  = int(self.txt_steps.Text)
        except: lifetime = 150
        try: cell_size = max(0.01, float(self.txt_cellsize.Text))
        except: cell_size = 0.5
        try: seed_val  = int(self.txt_seed.Text)
        except: seed_val = 0
        random.seed(seed_val if seed_val > 0 else None)
        layer_count = self.dd_layers.SelectedIndex + 1
        self.pheromone_grid        = PheromoneGridMultiLayer(num_layers=layer_count, cell_size=cell_size)
        self.conduit.pheromone_grid = self.pheromone_grid
        self.agents.clear()
        void_mode     = self.dd_void.SelectedIndex
        foraging_mode = bool(self.chk_foraging_mode.Checked)
        if foraging_mode and not self.sources:
            self.lbl_status.Text = (
                "Status: Foraging needs at least 1 Source! "
                "Open FORAGING section and Add Source first.")
            return
        try: dr = float(self.txt_detect_radius.Text)
        except: dr = 2.0
        for tgt in self.targets: tgt.detect_radius = dr
        for i in range(n_agents):
            pos   = self._get_spawn_point(void_mode, foraging_mode=foraging_mode, src_index=i)
            agent = Agent(pos, lifetime=lifetime)
            if foraging_mode and self.sources:
                src = self.sources[i % len(self.sources)]
                agent.source_pos = Rhino.Geometry.Point3d(src.pos)
            self.agents.append(agent)
        self.conduit.agents        = self.agents
        self.conduit.sources       = self.sources
        self.conduit.targets       = self.targets
        self.conduit.foraging_mode = foraging_mode
        self.conduit.Enabled       = True
        self.is_running            = True
        self.lbl_status.Text       = "Status: Simulating..."
        self.RunSimulation()

    def OnStopClick(self, s, e):
        self.is_running = False
        self.lbl_status.Text = "Status: Stopped"

    def RunSimulation(self):
        def _f(txt, default):
            try: return float(txt.Text)
            except: return default
        def _i(txt, default):
            try: return int(txt.Text)
            except: return default
        jitter      = _f(self.txt_jitter,    0.3)
        speed       = _f(self.txt_speed,     1.0)
        evap_rate   = _f(self.txt_evap,      0.02)
        phero_w     = _f(self.txt_phero_w,   0.6)
        perf_w      = _f(self.txt_perf_w,    0.4)
        deposit_amt = _f(self.txt_deposit,   1.0)
        prune_thr   = _f(self.txt_prune,     0.001)
        attr_weight = _f(self.txt_attr_weight, 0.5)
        foraging_mode = bool(self.chk_foraging_mode.Checked)
        detect_r   = _f(self.txt_detect_radius, 2.0)
        ret_speed  = _f(self.txt_return_speed,  1.2)
        food_str   = _f(self.txt_food_strength, 2.0)
        do_branch  = bool(self.chk_branch.Checked)
        b_thresh   = _f(self.txt_branch_thresh,    0.5)
        b_prob     = _f(self.txt_branch_prob,       0.05)
        b_cool     = _i(self.txt_branch_cooldown,   10)
        max_cap    = _i(self.txt_max_agents,         200)
        use_disc   = bool(self.chk_discrete_sensors.Checked)
        s_ang      = _f(self.txt_sense_angle, 0.35)
        s_dist     = _f(self.txt_sense_dist,  1.5)
        void_mode   = self.dd_void.SelectedIndex
        eff_mode    = void_mode
        eff_vox_pts = self.voxel_pts
        if void_mode == 1 and self.void_cells:
            eff_mode = 2; eff_vox_pts = self.void_cells
        max_steps = max((a.lifetime for a in self.agents), default=150)
        step = 0
        while self.is_running and step < max_steps:
            jitter      = _f(self.txt_jitter,      jitter)
            speed       = _f(self.txt_speed,       speed)
            evap_rate   = _f(self.txt_evap,        evap_rate)
            phero_w     = _f(self.txt_phero_w,     phero_w)
            perf_w      = _f(self.txt_perf_w,      perf_w)
            deposit_amt = _f(self.txt_deposit,     deposit_amt)
            attr_weight = _f(self.txt_attr_weight, attr_weight)
            any_alive  = False
            new_agents = []
            for a in self.agents:
                if not a.alive: continue
                any_alive = True
                pv = self._compute_perf_vector(a.pos)
                a.update(
                    jitter, speed, self.pheromone_grid, phero_w, evap_rate,
                    pv, perf_w, eff_mode,
                    self.void_brep, self.void_bbox,
                    self.mass_breps, self.mass_bboxes,
                    eff_vox_pts, self.voxel_unit,
                    void_breps = self.void_breps,
                    deposit_amount       = deposit_amt,
                    attractors           = self.attractors,
                    attractor_weight     = attr_weight,
                    surface_mesh         = self.surface_mesh,
                    foraging_mode        = foraging_mode,
                    targets              = self.targets,
                    detect_radius        = detect_r,
                    return_speed_mult    = ret_speed,
                    food_strength        = food_str,
                    branch_cooldown_max  = b_cool,
                    use_discrete_sensors = use_disc,
                    sense_angle          = s_ang,
                    sense_dist           = s_dist,
                )
                if (do_branch and a.saturation_level > b_thresh
                        and a.branch_cooldown == 0
                        and len(self.agents) + len(new_agents) < max_cap
                        and random.random() < b_prob):
                    child = Agent(a.pos, lifetime=int(a.lifetime * 0.7))
                    child.branch_id       = a.branch_id + 1
                    child.branch_cooldown = b_cool
                    child.source_pos      = a.source_pos
                    child.phase           = a.phase
                    a.branch_cooldown     = b_cool
                    new_agents.append(child)
                if len(a.history) > 1:
                    sc.doc.Objects.AddLine(
                        Rhino.Geometry.Line(a.history[-2], a.history[-1]))
            if new_agents:
                self.agents.extend(new_agents)
                self.conduit.agents = self.agents
            for attr in self.attractors: attr.update()
            self.pheromone_grid.evaporate(evap_rate)
            self.pheromone_grid.prune(threshold=prune_thr)
            alive_c = sum(1 for a in self.agents if a.alive)
            if foraging_mode:
                ret_c = sum(1 for a in self.agents if a.alive and a.phase=="returning")
                self.lbl_agent_count.Text = (
                    f"Agents: {alive_c}/{len(self.agents)}  |  {ret_c} returning")
            else:
                self.lbl_agent_count.Text = f"Agents: {alive_c}/{len(self.agents)} alive"
            sc.doc.Views.Redraw()
            Rhino.RhinoApp.Wait()
            step += 1
            if not any_alive: break
        self.is_running = False
        self.lbl_status.Text = (
            f"Status: Complete — {len(self.agents)} agents, {step} steps")

    # ── Module selection ───────────────────────────────────
    def OnCreateX(self, s, e):
        t, L = 0.08, 0.4
        breps = []
        for dims in [((-L,L),(-t,t),(-t,t)),((-t,t),(-L,L),(-t,t)),((-t,t),(-t,t),(-L,L))]:
            box = Rhino.Geometry.Box(
                Rhino.Geometry.Plane.WorldXY,
                Rhino.Geometry.Interval(*dims[0]),
                Rhino.Geometry.Interval(*dims[1]),
                Rhino.Geometry.Interval(*dims[2]))
            breps.append(Rhino.Geometry.Brep.CreateFromBox(box))
        union = Rhino.Geometry.Brep.CreateBooleanUnion(breps, sc.doc.ModelAbsoluteTolerance)
        if union:
            union[0].Translate(Rhino.Geometry.Vector3d(30, 30, 5))
            oid = sc.doc.Objects.AddBrep(union[0])
            self.base_geo_id = oid
            self.module_kit.set_slot(0, oid)
            self.lbl_slot_a.Text      = "✓ assigned"
            self.lbl_slot_a.TextColor = drawing.Color.FromArgb(0, 210, 80)
            self.lbl_status.Text = "Status: 3D X Module created and assigned to Slot A"
            sc.doc.Views.Redraw()

    def OnSelectGeo(self, s, e):
        oid = rs.GetObject("Select base geometry for aggregation", 0)
        if oid:
            self.base_geo_id = oid
            self.module_kit.set_slot(0, oid)
            self.lbl_slot_a.Text      = "✓ assigned"
            self.lbl_slot_a.TextColor = drawing.Color.FromArgb(0, 210, 80)
            self.lbl_status.Text = "Status: Custom geometry selected and assigned to Slot A"

    def _select_module_slot(self, idx):
        names = ["A — Primary", "B — Secondary", "C — Accent"]
        lbls  = [self.lbl_slot_a, self.lbl_slot_b, self.lbl_slot_c]
        oid   = rs.GetObject(f"Select geometry for Module {names[idx]}", 0)
        if oid:
            self.module_kit.set_slot(idx, oid)
            if idx == 0: self.base_geo_id = oid   # keep compat
            lbls[idx].Text      = "✓ assigned"
            lbls[idx].TextColor = drawing.Color.FromArgb(0, 210, 80)
            self.lbl_status.Text = f"Status: Module {names[idx]} assigned"

    def OnSelectSlotA(self, s, e): self._select_module_slot(0)
    def OnSelectSlotB(self, s, e): self._select_module_slot(1)
    def OnSelectSlotC(self, s, e): self._select_module_slot(2)

    def OnAdaptiveToggle(self, s, e):
        is_adaptive = bool(self.chk_adaptive.Checked)
        self.txt_spacing.Enabled = not is_adaptive
        if is_adaptive:
            geo_id = self.module_kit.slots[0] or self.base_geo_id
            if geo_id:
                obj = sc.doc.Objects.Find(geo_id)
                if obj:
                    bb = obj.Geometry.GetBoundingBox(True)
                    dx = bb.Max.X - bb.Min.X
                    dy = bb.Max.Y - bb.Min.Y
                    dz = bb.Max.Z - bb.Min.Z
                    step = max(dx, dy, dz)
                    if step > 0.001:
                        self.txt_spacing.Text = f"{step:.4f}"
                        self.lbl_status.Text = f"Status: Adaptive step = {step:.4f} (bbox max extent)"

    # ── V7 Aggregation ─────────────────────────────────────
    def OnAggregate(self, s, e):
        self.is_running = False

        # Backward-compat: if old workflow used base_geo_id, sync to slot A
        if self.base_geo_id and not self.module_kit.slots[0]:
            self.module_kit.set_slot(0, self.base_geo_id)

        if not self.module_kit.any_assigned():
            self.lbl_status.Text = "Status: ERROR — assign at least Module A first!"; return

        if not self.agents or all(len(a.history) < 2 for a in self.agents):
            self.lbl_status.Text = "Status: No trails — run simulation first!"; return

        # ── Read parameters ────────────────────────────────
        agg_mode  = self.dd_agg_mode.SelectedIndex          # 0=Trail, 1=Field, 2=Cluster, 3=Connector
        rot_mode  = self.dd_rotation_mode.SelectedIndex     # 0-4
        use_adaptive = bool(self.chk_adaptive.Checked)
        use_density  = bool(self.chk_density.Checked)
        do_collide   = bool(self.chk_collision.Checked)
        col_resp     = self.dd_collision_response.SelectedIndex  # 0=Skip, 1=Jitter
        use_layers   = bool(self.chk_use_layers.Checked)

        try: scale_min = float(self.txt_scale_min.Text)
        except: scale_min = 0.4
        try: scale_max = float(self.txt_scale_max.Text)
        except: scale_max = 1.2
        try: spacing = max(0.05, float(self.txt_spacing.Text))
        except: spacing = 0.5

        # Joint mode parameters
        use_joints    = bool(self.chk_joint_mode.Checked) and agg_mode == 3
        try: node_scale   = max(0.01, float(self.txt_node_scale.Text))
        except: node_scale = 1.0
        try: step_scale   = max(0.01, float(self.txt_step_scale.Text))
        except: step_scale = 1.0
        try: branch_scale = max(0.01, float(self.txt_branch_scale.Text))
        except: branch_scale = 1.0

        # Update kit thresholds from UI
        try: self.module_kit.thresholds[0] = float(self.txt_thresh_ab.Text)
        except: pass
        try: self.module_kit.thresholds[1] = float(self.txt_thresh_bc.Text)
        except: pass

        # ── Build per-slot geo / base plane ───────────────
        slot_geos   = [None, None, None]
        slot_planes = [None, None, None]
        for si in range(3):
            guid = self.module_kit.slots[si]
            if not guid: continue
            obj = sc.doc.Objects.Find(guid)
            if not obj: continue
            geo = obj.Geometry
            bb  = geo.GetBoundingBox(True)
            slot_geos[si]   = geo
            slot_planes[si] = Rhino.Geometry.Plane(bb.Center, Rhino.Geometry.Vector3d.ZAxis)

        # ── Adaptive spacing from Slot A ──────────────────
        if use_adaptive and slot_geos[0]:
            bb = slot_geos[0].GetBoundingBox(True)
            dx = bb.Max.X - bb.Min.X
            dy = bb.Max.Y - bb.Min.Y
            dz = bb.Max.Z - bb.Min.Z
            spacing = max(dx, dy, dz, 0.05)

        # ── Pheromone normalisation ────────────────────────
        if isinstance(self.pheromone_grid, PheromoneGridMultiLayer):
            gv = list(self.pheromone_grid.layers[0].grid.values())
        else:
            gv = list(self.pheromone_grid.grid.values())
        max_phero = max(gv) if gv else 1.0
        if max_phero < 0.001: max_phero = 1.0

        # ── Layer indices ──────────────────────────────────
        LAYER_NAMES  = ["SWM_Agg::Primary", "SWM_Agg::Secondary", "SWM_Agg::Accent"]
        LAYER_COLORS = [sd.Color.FromArgb(60,120,255),
                        sd.Color.FromArgb(60,220,120),
                        sd.Color.FromArgb(255,140,60)]
        layer_idxs = [None, None, None]
        if use_layers:
            for li in range(3):
                if slot_geos[li] is not None:
                    layer_idxs[li] = _ensure_layer(LAYER_NAMES[li], LAYER_COLORS[li])

        # ── Collision grid ─────────────────────────────────
        col_grid = CollisionGrid(spacing * 2.0) if do_collide else None

        # ── Inner helpers ──────────────────────────────────
        def _phero_val(pt3d):
            if isinstance(self.pheromone_grid, PheromoneGridMultiLayer):
                return self.pheromone_grid.layers[0].get_value(pt3d)
            return self.pheromone_grid.get_value(pt3d)

        def _phero_sf(val):
            if not use_density: return 1.0
            return scale_min + min(val / max_phero, 1.0) * (scale_max - scale_min)

        def _twist_angle(norm_density, agent_phase, arc_idx):
            if rot_mode == 0: return 0.0
            if rot_mode == 1: return random.choice([0.0, 90.0, 180.0, 270.0])
            if rot_mode == 2: return 0.0 if arc_idx % 2 == 0 else 180.0
            if rot_mode == 3: return 0.0 if agent_phase == "explore" else 180.0
            if rot_mode == 4: return norm_density * 360.0
            return 0.0

        def _place_module(frame, agent_phase, norm_density, arc_idx):
            slot_idx, slot_guid = self.module_kit.select_slot(norm_density)
            if slot_idx is None: return False
            geo  = slot_geos[slot_idx]
            bpln = slot_planes[slot_idx]
            if geo is None or bpln is None: return False

            val = norm_density * max_phero
            sf  = _phero_sf(val)

            angle = _twist_angle(norm_density, agent_phase, arc_idx)
            if angle != 0.0:
                frame = _apply_twist(frame, angle)

            if col_grid:
                if col_grid.check(frame.Origin):
                    if col_resp == 1:   # Jitter
                        jv = Rhino.Geometry.Vector3d(
                            random.uniform(-0.1, 0.1) * spacing,
                            random.uniform(-0.1, 0.1) * spacing,
                            random.uniform(-0.1, 0.1) * spacing)
                        jpt = frame.Origin + jv
                        if col_grid.check(jpt):
                            return False   # Still collides → skip
                        frame = Rhino.Geometry.Plane(frame)
                        frame.Origin = jpt
                    else:
                        return False   # Skip

            try:
                ng = geo.Duplicate()
                if ng is None: return False
                ng.Transform(Rhino.Geometry.Transform.Scale(bpln.Origin, sf))
                ng.Transform(Rhino.Geometry.Transform.PlaneToPlane(bpln, frame))

                attr = None
                if use_layers and layer_idxs[slot_idx] is not None:
                    attr = Rhino.DocObjects.ObjectAttributes()
                    attr.LayerIndex = layer_idxs[slot_idx]

                oid = _add_geo(ng, attr)
            except Exception as ex:
                if _agg_error[0] is None: _agg_error[0] = str(ex)
                return False

            if oid != System.Guid.Empty:
                self.aggregated_ids.append(oid)
                if col_grid: col_grid.add(frame.Origin)
                return True
            return False

        # ── Begin aggregation ──────────────────────────────
        self.aggregated_ids = []
        self.lbl_status.Text = "Status: Aggregating..."; Rhino.RhinoApp.Wait()
        count = 0
        _agg_error = [None]   # capture first exception inside closures
        MODE_TAGS = ["[Trail]", "[Field]", "[Cluster]", "[Connector]"]

        # ── Geometry add helper — handles Brep/Mesh/Extrusion/Surface ──
        def _add_geo(ng, attr):
            """Add any geometry type to the doc. Returns Guid or Empty."""
            # Extrusion / Surface → convert to Brep first
            if hasattr(ng, 'ToBrep') and not isinstance(ng, Rhino.Geometry.Brep):
                converted = ng.ToBrep()
                if converted is not None:
                    ng = converted
            if isinstance(ng, Rhino.Geometry.Brep):
                return sc.doc.Objects.AddBrep(ng, attr) if attr else sc.doc.Objects.AddBrep(ng)
            if isinstance(ng, Rhino.Geometry.Mesh):
                return sc.doc.Objects.AddMesh(ng, attr) if attr else sc.doc.Objects.AddMesh(ng)
            # Last resort: try generic Object add
            try:
                return sc.doc.Objects.Add(ng, attr) if attr else sc.doc.Objects.Add(ng)
            except Exception:
                return System.Guid.Empty

        # ── Connector placement closure ────────────────────
        def _place_connector(pt_a, pt_b, agent_phase, arc_idx):
            """Span one module between two consecutive history points."""
            seg_vec = pt_b - pt_a
            dist    = seg_vec.Length
            if dist < 0.001: return False          # degenerate segment — skip

            seg_vec.Unitize()
            mid = Rhino.Geometry.Point3d(
                (pt_a.X + pt_b.X) * 0.5,
                (pt_a.Y + pt_b.Y) * 0.5,
                (pt_a.Z + pt_b.Z) * 0.5)

            # Stable perpendicular — avoids tangent instability entirely
            perp = Rhino.Geometry.Vector3d.CrossProduct(
                seg_vec, Rhino.Geometry.Vector3d.ZAxis)
            if perp.Length < 0.001:
                perp = Rhino.Geometry.Vector3d.CrossProduct(
                    seg_vec, Rhino.Geometry.Vector3d.XAxis)
            perp.Unitize()
            # frame.XAxis = segment direction → module long axis aligns to edge
            frame = Rhino.Geometry.Plane(mid, seg_vec, perp)

            val  = _phero_val(mid)
            norm = min(val / max_phero, 1.0)

            angle = _twist_angle(norm, agent_phase, arc_idx)
            if angle != 0.0:
                frame = _apply_twist(frame, angle)

            # Slot selection by density
            slot_idx, slot_guid = self.module_kit.select_slot(norm)
            if slot_idx is None: return False
            geo  = slot_geos[slot_idx]
            bpln = slot_planes[slot_idx]
            if geo is None or bpln is None: return False

            # connector_sf: stretch module along its X-axis to fill segment
            bbox    = geo.GetBoundingBox(True)
            bbox_dx = bbox.Max.X - bbox.Min.X
            if bbox_dx < 0.001:
                bbox_dx = max(bbox.Max.X - bbox.Min.X,
                              bbox.Max.Y - bbox.Min.Y,
                              bbox.Max.Z - bbox.Min.Z)
            connector_sf = dist / bbox_dx if bbox_dx > 0.001 else 1.0

            # density_sf: cross-section thickness variation
            density_sf = _phero_sf(val) if use_density else 1.0

            # Collision check on midpoint
            if col_grid:
                if col_grid.check(mid):
                    if col_resp == 1:
                        jv = Rhino.Geometry.Vector3d(
                            random.uniform(-0.1, 0.1) * dist,
                            random.uniform(-0.1, 0.1) * dist, 0.0)
                        jpt = mid + jv
                        if col_grid.check(jpt): return False
                        frame = Rhino.Geometry.Plane(frame); frame.Origin = jpt
                    else:
                        return False

            try:
                ng = geo.Duplicate()
                if ng is None: return False
                # Scale: X = stretch to span gap, Y/Z = cross-section by density
                ng.Transform(Rhino.Geometry.Transform.Scale(
                    bpln, connector_sf, density_sf, density_sf))
                # Orient module to frame (XAxis → segment direction)
                ng.Transform(Rhino.Geometry.Transform.PlaneToPlane(bpln, frame))

                attr = None
                if use_layers and layer_idxs[slot_idx] is not None:
                    attr = Rhino.DocObjects.ObjectAttributes()
                    attr.LayerIndex = layer_idxs[slot_idx]

                oid = _add_geo(ng, attr)
            except Exception as ex:
                if _agg_error[0] is None: _agg_error[0] = str(ex)
                return False

            if oid != System.Guid.Empty:
                self.aggregated_ids.append(oid)
                if col_grid: col_grid.add(mid)
                return True
            return False

        # ── MODE 0: TRAIL ──────────────────────────────────
        if agg_mode == 0:
            for a in self.agents:
                if len(a.history) < 4: continue
                crv = Rhino.Geometry.Curve.CreateInterpolatedCurve(a.history, 3)
                if not crv: continue
                crv_len = crv.GetLength()
                if crv_len < 0.001: continue

                if use_adaptive and use_density:
                    arc_pos = 0.0; arc_idx = 0
                    while arc_pos <= crv_len + 1e-6:
                        ok, tp = crv.LengthParameter(arc_pos)
                        if not ok: break
                        rc, frame = crv.FrameAt(tp)
                        if not rc: break
                        pt3d = crv.PointAt(tp)
                        val  = _phero_val(pt3d)
                        norm = min(val / max_phero, 1.0)
                        sf   = _phero_sf(val)
                        if _place_module(frame, a.phase, norm, arc_idx): count += 1
                        arc_pos += spacing * sf; arc_idx += 1
                else:
                    params = crv.DivideByLength(spacing, True)
                    if not params: continue
                    for arc_idx, tp in enumerate(params):
                        rc, frame = crv.FrameAt(tp)
                        if not rc: continue
                        pt3d = crv.PointAt(tp)
                        val  = _phero_val(pt3d)
                        norm = min(val / max_phero, 1.0)
                        if _place_module(frame, a.phase, norm, arc_idx): count += 1

        # ── MODE 1: FIELD ──────────────────────────────────
        elif agg_mode == 1:
            floor_thresh = spacing * max_phero   # txt_spacing used as 0–1 normalised floor
            if isinstance(self.pheromone_grid, PheromoneGridMultiLayer):
                grid_dict = self.pheromone_grid.layers[0].grid
                cs = self.pheromone_grid.layers[0].cell_size
            else:
                grid_dict = self.pheromone_grid.grid
                cs = self.pheromone_grid.cell_size
            for (ix, iy, iz), val in grid_dict.items():
                if val < floor_thresh: continue
                norm = min(val / max_phero, 1.0)
                cell_center = Rhino.Geometry.Point3d(
                    (ix + 0.5) * cs, (iy + 0.5) * cs, (iz + 0.5) * cs)
                if isinstance(self.pheromone_grid, PheromoneGridMultiLayer):
                    grad = self.pheromone_grid.layers[0].sample_gradient(cell_center)
                else:
                    grad = self.pheromone_grid.sample_gradient(cell_center)
                if grad.Length > 0.001:
                    grad.Unitize()
                    frame = Rhino.Geometry.Plane(cell_center, grad)
                else:
                    frame = Rhino.Geometry.Plane(cell_center, Rhino.Geometry.Vector3d.ZAxis)
                if _place_module(frame, "explore", norm, 0): count += 1

        # ── MODE 2: CLUSTER ────────────────────────────────
        elif agg_mode == 2:
            if not self.attractors:
                self.lbl_status.Text = (
                    "Status: Cluster mode needs Attractors — add some in STEERING section.")
                return
            for attr_obj in self.attractors:
                if not attr_obj.alive: continue
                attr_val  = _phero_val(attr_obj.center)
                attr_norm = min(attr_val / max_phero, 1.0)
                ring_count = max(1, int(attr_norm * 9) + 1)
                arc_idx = 0
                for r in range(1, ring_count + 1):
                    circumference = 2.0 * math.pi * r * spacing
                    n_pts = max(3, int(circumference / spacing))
                    for i in range(n_pts):
                        ang   = 2.0 * math.pi * i / n_pts
                        cos_a = math.cos(ang); sin_a = math.sin(ang)
                        pt = Rhino.Geometry.Point3d(
                            attr_obj.center.X + cos_a * r * spacing,
                            attr_obj.center.Y + sin_a * r * spacing,
                            attr_obj.center.Z)
                        radial = Rhino.Geometry.Vector3d(
                            pt.X - attr_obj.center.X,
                            pt.Y - attr_obj.center.Y, 0.0)
                        if radial.Length > 0.0001: radial.Unitize()
                        else: radial = Rhino.Geometry.Vector3d.XAxis
                        frame = Rhino.Geometry.Plane(pt, radial)
                        val  = _phero_val(pt)
                        norm = min(val / max_phero, 1.0)
                        if _place_module(frame, "explore", norm, arc_idx): count += 1
                        arc_idx += 1

        # ── MODE 3: CONNECTOR ─────────────────────────────────
        elif agg_mode == 3:
            # ── Build node degree map ──────────────────────
            # node_map: snap_key → [Point3d, set_of_connected_keys]
            def _snap(pt):
                return (round(pt.X, 1), round(pt.Y, 1), round(pt.Z, 1))

            node_map = {}
            for a in self.agents:
                if len(a.history) < 2: continue
                for i in range(len(a.history) - 1):
                    ka = _snap(a.history[i]); kb = _snap(a.history[i + 1])
                    if ka not in node_map: node_map[ka] = [a.history[i], set()]
                    if kb not in node_map: node_map[kb] = [a.history[i + 1], set()]
                    node_map[ka][1].add(kb)
                    node_map[kb][1].add(ka)

            # ── Compute joint offset distance ──────────────
            # Derived from the JOINT geometry half-extents (not the connector).
            # joint_offset = how much space each joint needs at a connector endpoint.
            # If no joint geometry is assigned, offset = 0 → normal placement.
            joint_offset = 0.0
            if use_joints:
                def _geo_half_extent(geo_id):
                    if not geo_id: return 0.0
                    obj = sc.doc.Objects.Find(geo_id)
                    if not obj: return 0.0
                    bb = obj.Geometry.GetBoundingBox(True)
                    return max(bb.Max.X - bb.Min.X,
                               bb.Max.Y - bb.Min.Y,
                               bb.Max.Z - bb.Min.Z) * 0.5
                he_node   = _geo_half_extent(self.joint_node_geo_id)
                he_step   = _geo_half_extent(self.joint_step_geo_id)
                he_branch = _geo_half_extent(self.joint_branch_geo_id)
                # Use the largest assigned joint half-extent so all joints fit
                joint_offset = max(he_node, he_step, he_branch)
                # No joints assigned → no offset, no segment skipping
                if joint_offset < 0.001:
                    joint_offset = 0.0

            # ── Place connectors (offset endpoints if joints) ──
            seen_edges = set()
            for a in self.agents:
                if len(a.history) < 2: continue
                for arc_idx in range(len(a.history) - 1):
                    pt_a = a.history[arc_idx]
                    pt_b = a.history[arc_idx + 1]
                    if do_collide:
                        ea = _snap(pt_a); eb = _snap(pt_b)
                        key = (min(ea, eb), max(ea, eb))
                        if key in seen_edges: continue
                        seen_edges.add(key)
                    if use_joints and joint_offset > 0.001:
                        seg = pt_b - pt_a; dist = seg.Length
                        # Only offset if segment is long enough to leave room for connector
                        if dist > joint_offset * 2.5:
                            seg.Unitize()
                            pt_a_off = Rhino.Geometry.Point3d(
                                pt_a.X + seg.X * joint_offset,
                                pt_a.Y + seg.Y * joint_offset,
                                pt_a.Z + seg.Z * joint_offset)
                            pt_b_off = Rhino.Geometry.Point3d(
                                pt_b.X - seg.X * joint_offset,
                                pt_b.Y - seg.Y * joint_offset,
                                pt_b.Z - seg.Z * joint_offset)
                            if _place_connector(pt_a_off, pt_b_off, a.phase, arc_idx):
                                count += 1
                        # Too short to offset — skip (joint will cover the gap)
                    else:
                        if _place_connector(pt_a, pt_b, a.phase, arc_idx): count += 1

            # ── Place joints at nodes ──────────────────────
            if use_joints:
                self.joint_ids = []
                jnt_node_lyr   = _ensure_layer("SWM_Agg::Joints::Node",
                                               sd.Color.FromArgb(255, 220, 60))
                jnt_step_lyr   = _ensure_layer("SWM_Agg::Joints::Step",
                                               sd.Color.FromArgb(60, 200, 255))
                jnt_branch_lyr = _ensure_layer("SWM_Agg::Joints::Branch",
                                               sd.Color.FromArgb(255, 100, 200))
                auto_size = self._compute_joint_autofit_size()

                def _place_joint(pt, degree, geo_id, user_scale, layer_idx):
                    if not geo_id: return
                    obj = sc.doc.Objects.Find(geo_id)
                    if not obj: return
                    geo = obj.Geometry
                    if geo is None: return
                    # Auto-fit: scale so joint fills the offset gap
                    bb = geo.GetBoundingBox(True)
                    geo_ext = max(bb.Max.X - bb.Min.X,
                                  bb.Max.Y - bb.Min.Y,
                                  bb.Max.Z - bb.Min.Z)
                    if geo_ext < 0.001: geo_ext = 1.0
                    target = auto_size * 2.0 if auto_size > 0.001 else geo_ext
                    sf = (target / geo_ext) * user_scale

                    # Orientation: end-nodes face branch; step joints align to bisector; hubs use ZAxis
                    connections = node_map.get(_snap(pt), [None, set()])[1]
                    if degree == 1 and connections:
                        # Point toward the one neighbour
                        nb_key = next(iter(connections))
                        nb_pt  = node_map[nb_key][0]
                        dir_v  = Rhino.Geometry.Vector3d(
                            nb_pt.X - pt.X, nb_pt.Y - pt.Y, nb_pt.Z - pt.Z)
                        if dir_v.Length > 0.001: dir_v.Unitize()
                        else: dir_v = Rhino.Geometry.Vector3d.ZAxis
                        perp = Rhino.Geometry.Vector3d.CrossProduct(
                            dir_v, Rhino.Geometry.Vector3d.ZAxis)
                        if perp.Length < 0.001:
                            perp = Rhino.Geometry.Vector3d.CrossProduct(
                                dir_v, Rhino.Geometry.Vector3d.XAxis)
                        perp.Unitize()
                        frame = Rhino.Geometry.Plane(pt, dir_v, perp)
                    elif degree == 2 and len(connections) == 2:
                        # Align to bisector of the two connecting segments
                        nb_keys = list(connections)
                        nb0 = node_map[nb_keys[0]][0]
                        nb1 = node_map[nb_keys[1]][0]
                        v0 = Rhino.Geometry.Vector3d(
                            nb0.X - pt.X, nb0.Y - pt.Y, nb0.Z - pt.Z)
                        v1 = Rhino.Geometry.Vector3d(
                            nb1.X - pt.X, nb1.Y - pt.Y, nb1.Z - pt.Z)
                        if v0.Length > 0.001: v0.Unitize()
                        else: v0 = Rhino.Geometry.Vector3d.ZAxis
                        if v1.Length > 0.001: v1.Unitize()
                        else: v1 = Rhino.Geometry.Vector3d.ZAxis
                        bisect = Rhino.Geometry.Vector3d(
                            v0.X + v1.X, v0.Y + v1.Y, v0.Z + v1.Z)
                        if bisect.Length < 0.001:
                            # Straight-through — use segment direction itself
                            bisect = v0
                        bisect.Unitize()
                        perp = Rhino.Geometry.Vector3d.CrossProduct(
                            bisect, Rhino.Geometry.Vector3d.ZAxis)
                        if perp.Length < 0.001:
                            perp = Rhino.Geometry.Vector3d.CrossProduct(
                                bisect, Rhino.Geometry.Vector3d.XAxis)
                        perp.Unitize()
                        frame = Rhino.Geometry.Plane(pt, bisect, perp)
                    else:
                        frame = Rhino.Geometry.Plane(pt, Rhino.Geometry.Vector3d.ZAxis)

                    bpln = Rhino.Geometry.Plane(
                        geo.GetBoundingBox(True).Center,
                        Rhino.Geometry.Vector3d.ZAxis)
                    ng = geo.Duplicate()
                    ng.Transform(Rhino.Geometry.Transform.Scale(bpln, sf, sf, sf))
                    ng.Transform(Rhino.Geometry.Transform.PlaneToPlane(bpln, frame))
                    attr = Rhino.DocObjects.ObjectAttributes()
                    attr.LayerIndex = layer_idx
                    if isinstance(ng, Rhino.Geometry.Brep):
                        oid = sc.doc.Objects.AddBrep(ng, attr)
                    elif isinstance(ng, Rhino.Geometry.Mesh):
                        oid = sc.doc.Objects.AddMesh(ng, attr)
                    else: return
                    if oid != System.Guid.Empty:
                        self.joint_ids.append(oid)

                joint_count = 0
                for key, (pt, connections) in node_map.items():
                    degree = len(connections)
                    if degree == 1:
                        _place_joint(pt, degree,
                                     self.joint_node_geo_id, node_scale, jnt_node_lyr)
                        joint_count += 1
                    elif degree == 2:
                        _place_joint(pt, degree,
                                     self.joint_step_geo_id, step_scale, jnt_step_lyr)
                        joint_count += 1
                    elif degree >= 3:
                        _place_joint(pt, degree,
                                     self.joint_branch_geo_id, branch_scale, jnt_branch_lyr)
                        joint_count += 1
                self.lbl_status.Text = (
                    f"Status: Connector+Joints — {count} connectors, {joint_count} joints")
                sc.doc.Views.Redraw()
                return

        tag = MODE_TAGS[min(agg_mode, len(MODE_TAGS) - 1)]
        if _agg_error[0]:
            self.lbl_status.Text = (
                f"Status: {count} placed but ERROR → {_agg_error[0][:120]}")
        else:
            self.lbl_status.Text = (
                f"Status: Aggregation complete — {count} modules {tag}"
                + (" [Adaptive]" if use_adaptive else "")
                + (" [Layers]"   if use_layers   else "")
            )
        sc.doc.Views.Redraw()

    # ── Clear / mesh ───────────────────────────────────────
    def OnClearAggregated(self, s, e):
        count = 0
        for oid in self.aggregated_ids:
            obj = sc.doc.Objects.Find(oid)
            if obj and not obj.IsDeleted:
                sc.doc.Objects.Delete(obj, True); count += 1
        self.aggregated_ids.clear()
        sc.doc.Views.Redraw()
        self.lbl_status.Text = f"Status: Cleared {count} aggregated module(s)"

    # ── Joint handlers (V8) ────────────────────────────────
    def OnPickJointNode(self, s, e):
        self.lbl_status.Text = "Status: Pick Node geometry (end cap)..."
        oid = rs.GetObject("Select Node geometry — placed at trail endpoints", 0)
        if not oid: return
        obj = sc.doc.Objects.Find(oid)
        if not obj: return
        self.joint_node_geo_id = oid
        self.lbl_joint_node.Text = "✓ assigned"
        self.lbl_joint_node.TextColor = drawing.Color.FromArgb(0, 210, 80)
        self._update_joint_autofit_labels()
        self.lbl_status.Text = "Status: Node geometry assigned"

    def OnPickJointStep(self, s, e):
        self.lbl_status.Text = "Status: Pick Step geometry (mid-connection)..."
        oid = rs.GetObject("Select Step Joint geometry — placed at degree-2 pass-through nodes", 0)
        if not oid: return
        obj = sc.doc.Objects.Find(oid)
        if not obj: return
        self.joint_step_geo_id = oid
        self.lbl_joint_step.Text = "✓ assigned"
        self.lbl_joint_step.TextColor = drawing.Color.FromArgb(0, 210, 80)
        self._update_joint_autofit_labels()
        self.lbl_status.Text = "Status: Step Joint geometry assigned"

    def OnPickJointBranch(self, s, e):
        self.lbl_status.Text = "Status: Pick Branch Joint geometry (hub)..."
        oid = rs.GetObject("Select Branch Joint geometry — placed at branching hubs", 0)
        if not oid: return
        obj = sc.doc.Objects.Find(oid)
        if not obj: return
        self.joint_branch_geo_id = oid
        self.lbl_joint_branch.Text = "✓ assigned"
        self.lbl_joint_branch.TextColor = drawing.Color.FromArgb(0, 210, 80)
        self._update_joint_autofit_labels()
        self.lbl_status.Text = "Status: Branch Joint geometry assigned"

    def OnAutoFitJoints(self, s, e):
        self._update_joint_autofit_labels(apply_to_fields=True)
        self.lbl_status.Text = "Status: Joint scales auto-fitted from connector bbox"

    def _update_joint_autofit_labels(self, apply_to_fields=False):
        """Compute auto-fit scale from connector module bbox and update hint labels."""
        auto_size = self._compute_joint_autofit_size()
        if auto_size > 0.001:
            txt = f"Auto: {auto_size:.3f} units"
            self.lbl_node_autofit.Text   = txt
            self.lbl_step_autofit.Text   = txt
            self.lbl_branch_autofit.Text = txt
            if apply_to_fields:
                self.txt_node_scale.Text   = "1.0"
                self.txt_step_scale.Text   = "1.0"
                self.txt_branch_scale.Text = "1.0"
        else:
            self.lbl_node_autofit.Text   = "Auto: assign connector first"
            self.lbl_step_autofit.Text   = "Auto: assign connector first"
            self.lbl_branch_autofit.Text = "Auto: assign connector first"

    def _compute_joint_autofit_size(self):
        """Return the auto-fit joint size based on the connector module's bbox max extent."""
        geo_id = self.module_kit.slots[0] or self.base_geo_id
        if not geo_id: return 0.0
        obj = sc.doc.Objects.Find(geo_id)
        if not obj: return 0.0
        bb = obj.Geometry.GetBoundingBox(True)
        dx = bb.Max.X - bb.Min.X
        dy = bb.Max.Y - bb.Min.Y
        dz = bb.Max.Z - bb.Min.Z
        return max(dx, dy, dz) * 0.5   # half-extent = joint occupies half the connector space

    def OnClearJoints(self, s, e):
        count = 0
        for oid in self.joint_ids:
            obj = sc.doc.Objects.Find(oid)
            if obj and not obj.IsDeleted:
                sc.doc.Objects.Delete(obj, True); count += 1
        self.joint_ids.clear()
        sc.doc.Views.Redraw()
        self.lbl_status.Text = f"Status: Cleared {count} joint(s)"

    def OnGenerateMesh(self, s, e):
        self.is_running = False
        all_pts = []
        for a in self.agents: all_pts.extend(a.history)
        if len(all_pts) < 3:
            self.lbl_status.Text = "Status: Not enough points for mesh"; return
        try: spacing = max(0.1, float(self.txt_spacing.Text))
        except: spacing = 0.5
        self.lbl_status.Text = "Status: Building mesh skin..."; Rhino.RhinoApp.Wait()
        thr2 = (spacing*0.5)**2
        upts = []
        for pt in all_pts:
            if not any((pt.X-u.X)**2+(pt.Y-u.Y)**2+(pt.Z-u.Z)**2<thr2 for u in upts):
                upts.append(pt)
        n = len(upts)
        if n < 3:
            self.lbl_status.Text = "Status: Not enough unique points"; return
        mesh = Rhino.Geometry.Mesh()
        for pt in upts: mesh.Vertices.Add(pt)
        k = min(6, n-1); max_edge = spacing*3.0; used = set()
        for i in range(n):
            dists = sorted([(upts[i].DistanceTo(upts[j]),j) for j in range(n) if j!=i])[:k]
            nbrs  = [d[1] for d in dists]
            for ni in range(len(nbrs)):
                for nj in range(ni+1, len(nbrs)):
                    j1,j2 = nbrs[ni], nbrs[nj]
                    if upts[j1].DistanceTo(upts[j2]) > max_edge: continue
                    key = tuple(sorted([i,j1,j2]))
                    if key not in used:
                        used.add(key); mesh.Faces.AddFace(i,j1,j2)
        mesh.Normals.ComputeNormals(); mesh.Compact()
        if mesh.Faces.Count > 0:
            sc.doc.Objects.AddMesh(mesh)
            self.lbl_status.Text = f"Status: Mesh — {mesh.Faces.Count} faces, {n} pts"
        else:
            self.lbl_status.Text = "Status: Mesh failed — try larger spacing"
        sc.doc.Views.Redraw()

    def OnClearClick(self, s, e):
        to_del = [o for o in sc.doc.Objects
                  if isinstance(o.Geometry, Rhino.Geometry.Curve)]
        for o in to_del: sc.doc.Objects.Delete(o, True)
        sc.doc.Views.Redraw()
        self.lbl_status.Text = "Status: Trails cleared"

    def OnClearGeoClick(self, s, e):
        preserved = set(filter(None, self.module_kit.slots))
        if self.base_geo_id: preserved.add(self.base_geo_id)
        to_del = [o for o in sc.doc.Objects
                  if o.Id not in preserved and
                  isinstance(o.Geometry, (Rhino.Geometry.Curve, Rhino.Geometry.Brep,
                                          Rhino.Geometry.Mesh, Rhino.Geometry.Extrusion))]
        for o in to_del: sc.doc.Objects.Delete(o, True)
        sc.doc.Views.Redraw()
        self.lbl_status.Text = f"Status: Cleared {len(to_del)} objects"

    def OnFormClosed(self, s, e):
        self.is_running = False
        self.conduit.Enabled = False
        sc.doc.Views.Redraw()


# ═══════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════
def RunMASV8():
    form = MAS_Simulation_V8()
    form.Show()


if __name__ == "__main__":
    RunMASV8()
