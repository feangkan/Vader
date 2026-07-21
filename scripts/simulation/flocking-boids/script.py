#! python 3
"""
Flocking Boids V3 — Reynolds Flocking Simulation for Architecture
Rhino 8 CPython

V3 NEW: SCA-grade Aggregation System (ported from Space_Colonization_Algorithm_V4)
  - _auto_ref_pts      : auto-detects module primary axis from longest bbox dimension
  - _build_orient_xform: proper axis-aligned rotation + non-uniform scale + translation
                         (replaces naive PlaneToPlane/Z-up transform from V2)
  - Scale Mode         : Fit (stretch module to fill spacing) / Repeat (tile at natural size)
  - Module Gap         : pullback from trail ends before placing modules
  - Module Scale       : cross-section (radial) multiplier independent of trail length
  - Manual Axis        : pick Start/End reference points on module geometry
  - JOINT System       : connection geometry at trail endpoints + crossings
                         Node geo at joint positions; Arm geo along incoming trail tangents

V2 carried over: Surface 3D Offset Modes (Off / Offset Shell / Soft Attract / Variable Layer)
V1 carried over: Reynolds 3-rule flocking, 4 attractor modes, 3 module slots, 5 aggregation logics

Output:
  - Trail curves  → Boids::Trails         (#CD2990 magenta)
  - Modules M1    → Boids::Modules::M1   (deep violet)
  - Modules M2    → Boids::Modules::M2   (electric cyan)
  - Modules M3    → Boids::Modules::M3   (pale ice-white)
  - Joint Nodes   → Boids::Joints::Node  (amber)
  - Joint Arms    → Boids::Joints::Arm   (orange)
  - Mesh skin     → Boids::Mesh

References:
  Reynolds, C. (1987) Flocks, Herds and Schools. SIGGRAPH.
  veltman — https://gist.github.com/veltman/995d3a677418100ac43877f3ed1cc728
  SCA V4 aggregation system (Space_Colonization_Algorithm_V4.py) — same author
  Framework and UI patterns adapted from MAS & Swarm (Stigmergy) V8 by the author.
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
#  PRESETS
# ═══════════════════════════════════════════════════════
PRESETS = [
    None,  # 0 = Custom
    # ── Classic Flock ─────────────────────────────────────
    {   # 1 — Flock on Surface
        # Original organic flocking: cohesion pulls boids into groups,
        # separation prevents crowding, alignment steers them together.
        # Produces natural branching / converging trail networks on surface.
        "name": "⬡ Flock — Surface",
        "void_mode": 2,
        "n_boids": "60", "steps": "250",
        "neighbor_radius": "5.0", "separation_dist": "1.8",
        "sep_w": "2.0", "ali_w": "1.0", "coh_w": "1.0",
        "max_speed": "1.5", "max_force": "0.15",
        "jitter": "0.05", "seed": "0",
        "attr_weight": "0.5", "wind_weight": "0.0",
        "hint": "⬡ Classic flock on surface. Boids cluster organically. Add Converge attractors to route trails toward zones.",
    },
    {   # 2 — Flock in Volume
        # Classic 3D volumetric flock inside a Brep void.
        "name": "⬡ Flock — Volume",
        "void_mode": 0,
        "n_boids": "80", "steps": "300",
        "neighbor_radius": "6.0", "separation_dist": "1.8",
        "sep_w": "2.0", "ali_w": "1.0", "coh_w": "1.0",
        "max_speed": "1.5", "max_force": "0.15",
        "jitter": "0.08", "seed": "0",
        "attr_weight": "0.5", "wind_weight": "0.0",
        "hint": "⬡ Classic 3D flock inside a Brep (Mode A). Boids fill volume with organic trails. Add Converge attractors to shape.",
    },
    # ── Facade Wrap ───────────────────────────────────────
    {   # 3 — Facade Wrap
        # High separation + alignment, near-zero cohesion = evenly-spaced
        # parallel flow lines wrapping across the surface.
        # Wind drives the dominant sweep direction.
        "name": "≋ Facade Wrap",
        "void_mode": 2,
        "n_boids": "80", "steps": "300",
        "neighbor_radius": "7.0", "separation_dist": "3.0",
        "sep_w": "2.5", "ali_w": "2.0", "coh_w": "0.1",
        "max_speed": "0.8", "max_force": "0.18",
        "jitter": "0.03", "seed": "0",
        "attr_weight": "0.4", "wind_weight": "0.6",
        "hint": "≋ Facade parallel lines. High sep+align, near-zero cohesion. Set Wind X/Y/Z across surface. SlowField attractors = denser bands at light zones.",
    },
    {   # 4 — Strong Sweep
        # Maximum parallel: very high alignment + wind, minimal cohesion.
        # Closest to contour/isocurve wrapping of the surface.
        "name": "≋ Strong Sweep",
        "void_mode": 2,
        "n_boids": "100", "steps": "400",
        "neighbor_radius": "8.0", "separation_dist": "3.5",
        "sep_w": "3.0", "ali_w": "2.5", "coh_w": "0.05",
        "max_speed": "1.0", "max_force": "0.20",
        "jitter": "0.02", "seed": "0",
        "attr_weight": "0.3", "wind_weight": "0.9",
        "hint": "≋ Maximum parallel sweep. Set Wind direction first. SlowField attractors create dense bands. Produces contour-like wrapping curves for geometry.",
    },
]


# ═══════════════════════════════════════════════════════
#  HEATMAP COLOUR THEMES  (from V8)
# ═══════════════════════════════════════════════════════
HEATMAP_THEMES = [
    # ★ default — deep space: black → indigo → violet → cyan → white star
    ("Galaxy",          [(0,0,0),(20,0,60),(90,0,180),(200,0,255),(0,180,255),(180,255,255),(255,255,255)]),
    ("Classic Heat",    [(0,0,255),(0,255,255),(0,255,0),(255,255,0),(255,0,0)]),
    ("Magma",           [(0,0,0),(80,0,120),(200,50,0),(255,170,0),(255,255,200)]),
    ("Neon Pulse",      [(0,0,20),(110,0,220),(255,0,160),(0,220,255),(255,255,255)]),
    ("Bioluminescence", [(0,0,10),(0,30,90),(0,150,130),(0,255,170),(180,255,240)]),
    ("Lava",            [(0,0,0),(120,0,0),(255,70,0),(255,210,0),(255,255,255)]),
    ("Aurora",          [(0,0,25),(0,90,90),(0,210,110),(130,0,210),(210,210,255)]),
    ("Arctic Ice",      [(0,10,60),(0,80,200),(0,200,255),(200,240,255),(255,255,255)]),
    ("Monochrome",      [(0,0,0),(255,255,255)]),
]


def _theme_color(stops, t, alpha=200):
    t   = max(0.0, min(1.0, t))
    n   = len(stops) - 1
    sc_ = t * n
    lo  = int(sc_); hi = min(lo + 1, n); frac = sc_ - lo
    r = int(stops[lo][0] + frac * (stops[hi][0] - stops[lo][0]))
    g = int(stops[lo][1] + frac * (stops[hi][1] - stops[lo][1]))
    b = int(stops[lo][2] + frac * (stops[hi][2] - stops[lo][2]))
    return sd.Color.FromArgb(alpha, r, g, b)


def _theme_sample(stops, frac):
    n   = len(stops) - 1
    sc_ = frac * n
    lo  = int(sc_); hi = min(lo + 1, n); f = sc_ - lo
    return (int(stops[lo][0] + f*(stops[hi][0]-stops[lo][0])),
            int(stops[lo][1] + f*(stops[hi][1]-stops[lo][1])),
            int(stops[lo][2] + f*(stops[hi][2]-stops[lo][2])))


# ═══════════════════════════════════════════════════════
#  ATTRACTOR  (4 modes — designed for facade/light use)
# ═══════════════════════════════════════════════════════
class Attractor:
    """
    4 attractor modes:
      Converge  — pull boids toward point (trail density = more material / light-zone detail)
      Orbit     — spiral boids around point using tangential cross-product force
      Repulse   — push boids away  (openings / light-permeable voids)
      SlowField — boids slow inside radius, dwell → trail clusters → fine detail density
    """
    MODES = ["SlowField", "Orbit", "Repulse", "Converge"]

    def __init__(self, center, strength=1.0, radius=5.0,
                 decay_rate=0.0, mode="SlowField", slow_speed=0.3):
        self.center     = Rhino.Geometry.Point3d(center)
        self.strength   = strength
        self.radius     = radius
        self.decay_rate = decay_rate
        self.mode       = mode
        self.slow_speed = slow_speed   # fraction of max_speed inside SlowField
        self.alive      = True
        self.age        = 0

    def get_force(self, agent_pos, agent_vel, surface_mesh=None):
        """Returns (force_vector, speed_multiplier).
        speed_multiplier is 1.0 for all modes except SlowField."""
        to_center = self.center - agent_pos
        dist = to_center.Length

        if dist > self.radius or dist < 0.0001:
            return Rhino.Geometry.Vector3d(0, 0, 0), 1.0

        falloff = 1.0 - (dist / self.radius)   # 1.0 at centre, 0.0 at edge

        if self.mode == "Converge":
            to_center.Unitize()
            return to_center * (self.strength * falloff), 1.0

        elif self.mode == "Repulse":
            away = Rhino.Geometry.Vector3d(agent_pos - self.center)
            if away.Length < 0.0001:
                away = Rhino.Geometry.Vector3d(1, 0, 0)
            away.Unitize()
            return away * (self.strength * falloff), 1.0

        elif self.mode == "Orbit":
            to_center.Unitize()
            # Tangential direction stays on surface when in Surface mode
            if surface_mesh is not None:
                mp = surface_mesh.ClosestMeshPoint(agent_pos, 0.0)
                if mp is not None:
                    n = surface_mesh.NormalAt(mp)
                    if n.Length > 0.001:
                        n.Unitize()
                        tangent = Rhino.Geometry.Vector3d.CrossProduct(to_center, n)
                    else:
                        tangent = Rhino.Geometry.Vector3d.CrossProduct(
                            to_center, Rhino.Geometry.Vector3d.ZAxis)
                else:
                    tangent = Rhino.Geometry.Vector3d.CrossProduct(
                        to_center, Rhino.Geometry.Vector3d.ZAxis)
            else:
                tangent = Rhino.Geometry.Vector3d.CrossProduct(
                    to_center, Rhino.Geometry.Vector3d.ZAxis)
                if tangent.Length < 0.001:
                    tangent = Rhino.Geometry.Vector3d.CrossProduct(
                        to_center, Rhino.Geometry.Vector3d.XAxis)
            if tangent.Length > 0.001:
                tangent.Unitize()
                return tangent * (self.strength * falloff), 1.0
            return Rhino.Geometry.Vector3d(0, 0, 0), 1.0

        elif self.mode == "SlowField":
            # No steering force — reduce speed proportionally to proximity
            speed_mult = self.slow_speed + (1.0 - self.slow_speed) * (dist / self.radius)
            return Rhino.Geometry.Vector3d(0, 0, 0), speed_mult

        return Rhino.Geometry.Vector3d(0, 0, 0), 1.0

    def update(self):
        self.age += 1
        self.strength *= (1.0 - self.decay_rate)
        if self.strength < 0.01:
            self.alive = False


# ═══════════════════════════════════════════════════════
#  BOID
# ═══════════════════════════════════════════════════════
class Boid:
    def __init__(self, pos, lifetime=200):
        self.pos      = Rhino.Geometry.Point3d(pos)
        self.vel      = Rhino.Geometry.Vector3d(
            random.uniform(-1, 1),
            random.uniform(-1, 1),
            random.uniform(-1, 1))
        if self.vel.Length > 0.0001: self.vel.Unitize()
        self.acc      = Rhino.Geometry.Vector3d(0, 0, 0)
        self.history       = [Rhino.Geometry.Point3d(pos)]
        self.alive         = True
        self.age           = 0
        self.lifetime      = lifetime
        self.speed         = 0.0   # updated each step; used for viewport colour mapping
        self.target_offset = 0.0   # V2: per-boid target offset distance (Variable Layer mode)

    # ── Reynolds flocking forces ─────────────────────────
    def _separation(self, neighbors, sep_dist, max_force):
        """Steer away from neighbors closer than sep_dist, weighted by 1/distance."""
        steer = Rhino.Geometry.Vector3d(0, 0, 0)
        count = 0
        for other in neighbors:
            d = self.pos.DistanceTo(other.pos)
            if d < sep_dist and d > 0.0001:
                diff = Rhino.Geometry.Vector3d(self.pos - other.pos)
                diff.Unitize()
                diff *= (1.0 / d)   # closer = stronger push
                steer += diff
                count += 1
        if count > 0:
            steer *= (1.0 / count)
            l = steer.Length
            if l > max_force: steer *= (max_force / l)
        return steer

    def _alignment(self, neighbors, max_force):
        """Steer toward average velocity of all neighbours."""
        if not neighbors:
            return Rhino.Geometry.Vector3d(0, 0, 0)
        avg = Rhino.Geometry.Vector3d(0, 0, 0)
        for other in neighbors:
            avg += other.vel
        avg *= (1.0 / len(neighbors))
        l = avg.Length
        if l > max_force: avg *= (max_force / l)
        return avg

    def _cohesion(self, neighbors, max_force):
        """Steer toward centre of mass of all neighbours."""
        if not neighbors:
            return Rhino.Geometry.Vector3d(0, 0, 0)
        cx = sum(b.pos.X for b in neighbors) / len(neighbors)
        cy = sum(b.pos.Y for b in neighbors) / len(neighbors)
        cz = sum(b.pos.Z for b in neighbors) / len(neighbors)
        steer = Rhino.Geometry.Vector3d(
            Rhino.Geometry.Point3d(cx, cy, cz) - self.pos)
        l = steer.Length
        if l > max_force: steer *= (max_force / l)
        return steer

    # ── Confine helpers (from V8) ────────────────────────
    def _confine_breps(self, new_pos, breps):
        try:
            tol    = sc.doc.ModelAbsoluteTolerance
            inside = any(b.IsPointInside(new_pos, tol, False) for b in breps)
            if not inside:
                best_dist = float('inf'); best_closest = None
                for b in breps:
                    cp = b.ClosestPoint(new_pos)
                    d  = new_pos.DistanceTo(cp)
                    if d < best_dist:
                        best_dist = d; best_closest = cp
                if best_closest is not None:
                    ov = Rhino.Geometry.Vector3d(new_pos - best_closest)
                    if ov.Length > 0.0001:
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
                    cx = (mbb.Min.X + mbb.Max.X) * 0.5
                    cy = (mbb.Min.Y + mbb.Max.Y) * 0.5
                    cz = (mbb.Min.Z + mbb.Max.Z) * 0.5
                    ov = Rhino.Geometry.Vector3d(clamped.X-cx, clamped.Y-cy, clamped.Z-cz)
                    if ov.Length < 0.0001: ov = Rhino.Geometry.Vector3d(1, 0, 0)
                    ov.Unitize()
                    self.vel -= ov * (2.0 * (self.vel * ov))
                    if self.vel.Length > 0.0001: self.vel.Unitize()
                    return self.pos
        if mass_breps:
            for mb in mass_breps:
                try:
                    if mb.IsPointInside(clamped, sc.doc.ModelAbsoluteTolerance, False):
                        od = Rhino.Geometry.Vector3d(clamped - mb.ClosestPoint(clamped))
                        if od.Length > 0.0001:
                            od.Unitize()
                            self.vel -= od * (2.0 * (self.vel * od))
                            if self.vel.Length > 0.0001: self.vel.Unitize()
                        return self.pos
                except: pass
        return clamped

    def _snap_surface(self, new_pos, surface_mesh):
        """Snap to closest point on mesh; return (snapped_pt, surface_normal)."""
        if not surface_mesh or surface_mesh.Vertices.Count == 0:
            return new_pos, None
        try:
            mp = surface_mesh.ClosestMeshPoint(new_pos, 0.0)
            if mp is not None:
                cp     = surface_mesh.PointAt(mp)
                normal = surface_mesh.NormalAt(mp)
                return cp, normal
            cp = surface_mesh.ClosestPoint(new_pos)
            return (cp if cp is not None else new_pos), None
        except:
            return new_pos, None

    def _surface_info(self, pos, surface_mesh):
        """V2: Returns (closest_pt, unit_normal, signed_dist_along_normal).
        signed_dist > 0  → boid is on the outward side of the surface.
        signed_dist < 0  → boid has gone through the surface (clamp back).
        """
        if not surface_mesh or surface_mesh.Vertices.Count == 0:
            return pos, None, 0.0
        try:
            mp = surface_mesh.ClosestMeshPoint(pos, 0.0)
            if mp is None:
                cp = surface_mesh.ClosestPoint(pos)
                return (cp if cp else pos), None, 0.0
            cp     = surface_mesh.PointAt(mp)
            normal = surface_mesh.NormalAt(mp)
            if normal is None or normal.Length < 0.0001:
                return cp, None, 0.0
            normal.Unitize()
            signed_dist = Rhino.Geometry.Vector3d(pos - cp) * normal
            return cp, normal, signed_dist
        except:
            return pos, None, 0.0

    # ── Main update ──────────────────────────────────────
    def update(self, neighbors,
               sep_dist, sep_w, ali_w, coh_w,
               max_speed, max_force, jitter,
               void_mode, void_brep, void_breps, void_bbox,
               mass_breps, mass_bboxes, surface_mesh,
               attractors, attr_weight,
               wind_vector, wind_weight,
               flock_centroid=None,
               # V2 surface offset params
               offset_mode=0, offset_inner=0.0, offset_outer=5.0, spring_k=0.3,
               # V3 surface interior pull
               surface_centroid=None):

        if not self.alive: return

        # ── 1. Reynolds flocking forces ──────────────────
        self.acc = Rhino.Geometry.Vector3d(0, 0, 0)
        if neighbors:
            self.acc += self._separation(neighbors, sep_dist, max_force) * sep_w
            self.acc += self._alignment(neighbors, max_force)             * ali_w
            self.acc += self._cohesion(neighbors, max_force)              * coh_w
        else:
            # No local neighbours — apply weak pull toward the global flock centroid
            # so lone boids don't escape entirely to attractor positions.
            if flock_centroid is not None:
                steer = Rhino.Geometry.Vector3d(flock_centroid - self.pos)
                d = steer.Length
                if d > sep_dist:          # only pull if not already at centre
                    if d > max_force: steer *= (max_force / d)
                    self.acc += steer * coh_w * 0.4   # 40 % strength — gentle

        # ── 2. Attractor forces ──────────────────────────
        speed_mult = 1.0
        if attractors and attr_weight > 0:
            av = Rhino.Geometry.Vector3d(0, 0, 0)
            for a in attractors:
                if not a.alive: continue
                f, sm = a.get_force(self.pos, self.vel, surface_mesh)
                av        += f
                speed_mult = min(speed_mult, sm)
            if av.Length > 0.0001:
                l = av.Length
                if l > max_force: av *= (max_force / l)
                self.acc += av * attr_weight

        # ── 3. Wind bias ─────────────────────────────────
        if wind_vector is not None and wind_weight > 0:
            self.acc += wind_vector * wind_weight

        # ── 3.5 Surface offset spring force (V2 — modes 2 & 3) ──────────
        # Applied BEFORE velocity integration so it flows naturally.
        if void_mode == 2 and offset_mode in (2, 3) and surface_mesh:
            cp, n, sd = self._surface_info(self.pos, surface_mesh)
            if n is not None:
                target = (self.target_offset if offset_mode == 3
                          else (offset_inner + offset_outer) * 0.5)
                error  = target - sd                    # positive → pull outward
                spring = Rhino.Geometry.Vector3d(n)
                spring *= (error * spring_k)
                self.acc += spring

        # ── 3.6 Surface interior pull — keeps boids away from boundary edges ──
        # A gentle force toward the mesh face-centre centroid projected onto
        # the local tangent plane.  Strength is proportional to how far the
        # boid is from the centroid so it fades to zero at the centre.
        # Very small magnitude — just enough to counteract edge drift without
        # overriding flocking or wind.
        if void_mode == 2 and surface_centroid is not None and surface_mesh is not None:
            cp_i, n_i, _ = self._surface_info(self.pos, surface_mesh)
            if n_i is not None:
                n_iu = Rhino.Geometry.Vector3d(n_i); n_iu.Unitize()
                to_ctr = Rhino.Geometry.Vector3d(surface_centroid - self.pos)
                # Project to tangent plane — keep only the in-surface component
                to_ctr -= n_iu * (to_ctr * n_iu)
                dist = to_ctr.Length
                if dist > 0.5:
                    to_ctr.Unitize()
                    # Force: 3 % of max_force — gentle background inward drift
                    self.acc += to_ctr * (max_force * 0.03)


        # ── 4. Jitter ────────────────────────────────────
        self.acc += Rhino.Geometry.Vector3d(
            random.uniform(-jitter, jitter),
            random.uniform(-jitter, jitter),
            random.uniform(-jitter, jitter))

        # ── 5. Integrate velocity ────────────────────────
        self.vel += self.acc
        eff_speed = max_speed * speed_mult
        spd = self.vel.Length
        if spd > eff_speed + 0.0001:
            self.vel *= (eff_speed / spd)
        elif spd < 0.001:
            # Random kick to prevent stalling
            self.vel = Rhino.Geometry.Vector3d(
                random.uniform(-1, 1),
                random.uniform(-1, 1),
                random.uniform(-1, 1))
            self.vel.Unitize()
            self.vel *= eff_speed * 0.5
        self.speed = self.vel.Length

        # ── 6. Candidate position ────────────────────────
        candidate = self.pos + self.vel

        # ── 7. Confine to void mode ──────────────────────
        if void_mode == 0:   # A: Brep
            active = void_breps if void_breps else ([void_brep] if void_brep else [])
            if active:
                candidate = self._confine_breps(candidate, active)

        elif void_mode == 1:   # B: BBox − Mass
            if void_bbox is not None:
                candidate = self._confine_bbox(candidate, void_bbox, mass_breps, mass_bboxes)

        elif void_mode == 2:   # D: Surface — behaviour depends on V2 offset mode
            if offset_mode == 0:
                # ── Off: V1 flat snap + tangent projection ──────────────
                candidate, normal = self._snap_surface(candidate, surface_mesh)
                if normal is not None and normal.Length > 0.0001:
                    n = Rhino.Geometry.Vector3d(normal); n.Unitize()
                    dot = self.vel * n
                    self.vel -= n * dot
                    vl = self.vel.Length
                    if vl > 0.0001:
                        self.vel *= (self.speed / vl)
                    else:
                        t = Rhino.Geometry.Vector3d(
                            random.uniform(-1,1), random.uniform(-1,1), random.uniform(-1,1))
                        t -= n * (t * n)
                        if t.Length > 0.0001:
                            t.Unitize(); self.vel = t * (self.speed * 0.5)

            elif offset_mode == 1:
                # ── Offset Shell: hard [inner, outer] band ──────────────
                cp, n, sd = self._surface_info(candidate, surface_mesh)
                if n is not None:
                    if sd < offset_inner:          # below inner wall → push out
                        candidate = cp + n * offset_inner
                        dot = self.vel * n
                        if dot < 0: self.vel -= n * (2.0 * dot)   # reflect outward
                    elif sd > offset_outer:        # above outer wall → push back
                        candidate = cp + n * offset_outer
                        dot = self.vel * n
                        if dot > 0: self.vel -= n * (2.0 * dot)   # reflect inward

            elif offset_mode in (2, 3):
                # ── Soft Attract / Variable Layer: spring-controlled ─────
                # Spring force already added to acc in step 3.5.
                # Here just prevent going through the surface.
                cp, n, sd = self._surface_info(candidate, surface_mesh)
                if n is not None and sd < offset_inner:
                    candidate = cp + n * max(offset_inner, 0.01)
                    dot = self.vel * n
                    if dot < 0: self.vel -= n * dot   # kill inward component

            # ── Universal surface boundary clamp (offset_mode > 0) ───────
            if surface_mesh is not None and offset_mode > 0:
                cp_b, n_b, sd_b = self._surface_info(candidate, surface_mesh)
                if n_b is not None:
                    n_bu   = Rhino.Geometry.Vector3d(n_b); n_bu.Unitize()
                    off_cl = max(offset_inner, min(offset_outer, sd_b))
                    ideal  = cp_b + n_bu * off_cl
                    err    = ideal.DistanceTo(candidate)
                    thresh = max(1.0, offset_outer * 0.4)
                    if err > thresh:
                        escape_dir = Rhino.Geometry.Vector3d(candidate - ideal)
                        escape_dir.Unitize()
                        candidate  = ideal
                        # Full elastic reflection — reverse outward component so
                        # boid bounces inward instead of sliding along the edge
                        out_spd = self.vel * escape_dir
                        if out_spd > 0:
                            self.vel -= escape_dir * (out_spd * 2.0)

        self.pos = candidate
        self.history.append(Rhino.Geometry.Point3d(self.pos))
        self.age += 1
        if self.age >= self.lifetime:
            self.alive = False


# ═══════════════════════════════════════════════════════
#  DISPLAY CONDUIT
# ═══════════════════════════════════════════════════════
class BoidConduit(Rhino.Display.DisplayConduit):
    def __init__(self):
        super().__init__()
        self.boids       = []
        self.attractors  = []
        self.show_tails  = True
        self.theme_idx   = 0
        self.color_mode  = 0    # 0=By Speed, 1=By Age, 2=Solid
        self.max_speed   = 1.0
        self.tail_length = 30   # max history steps shown in viewport

    def DrawOverlay(self, e):
        stops = HEATMAP_THEMES[max(0, min(self.theme_idx, len(HEATMAP_THEMES)-1))][1]

        for boid in self.boids:
            if not boid.alive: continue

            # Colour T value
            if self.color_mode == 0:   # By Speed
                t = min(boid.speed / max(self.max_speed, 0.001), 1.0)
            elif self.color_mode == 1:  # By Age
                t = min(boid.age / max(boid.lifetime, 1), 1.0)
            else:
                t = 0.75
            col = _theme_color(stops, t, 230)

            # Boid dot
            e.Display.DrawPoint(boid.pos, Rhino.Display.PointStyle.X, 6, col)

            # Tail (last N history points)
            if self.show_tails and len(boid.history) >= 2:
                n = min(len(boid.history), self.tail_length)
                pts = boid.history[-n:]
                seg_count = len(pts) - 1
                for i in range(seg_count):
                    alpha = int(200 * (i / max(seg_count - 1, 1)))
                    c = _theme_color(stops, t, alpha)
                    e.Display.DrawLine(pts[i], pts[i+1], c, 1)

        # Attractor indicators — colour-coded by mode
        MODE_COLS = {
            "Converge":  sd.Color.FromArgb(255, 255, 100, 255),
            "Orbit":     sd.Color.FromArgb(255, 100, 180, 255),
            "Repulse":   sd.Color.FromArgb(255, 255,  80,  80),
            "SlowField": sd.Color.FromArgb(255,  60, 255, 180),
        }
        for a in self.attractors:
            if not a.alive: continue
            ac = MODE_COLS.get(a.mode, sd.Color.FromArgb(255, 200, 200, 200))
            # Inner white dot at 2.5 pt
            e.Display.DrawPoint(a.center,
                                Rhino.Display.PointStyle.RoundSimple, 2.5,
                                sd.Color.FromArgb(255, 255, 255, 255))
            # Outer ring in mode colour at 3 pt
            e.Display.DrawPoint(a.center,
                                Rhino.Display.PointStyle.RoundControlPoint, 3, ac)
            pass  # radius circle removed — kept for reference only


# ═══════════════════════════════════════════════════════
#  HELPERS  (from V8)
# ═══════════════════════════════════════════════════════
def _ensure_layer(full_name, color=None):
    idx = sc.doc.Layers.FindByFullPath(full_name, -1)
    if idx >= 0: return idx
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


def _apply_twist(frame, angle_deg):
    xf = Rhino.Geometry.Transform.Rotation(
        math.radians(angle_deg), frame.ZAxis, frame.Origin)
    f2 = Rhino.Geometry.Plane(frame)
    f2.Transform(xf)
    return f2


def _add_geo(ng, attr=None):
    if hasattr(ng, 'ToBrep') and not isinstance(ng, Rhino.Geometry.Brep):
        converted = ng.ToBrep()
        if converted is not None: ng = converted
    if isinstance(ng, Rhino.Geometry.Brep):
        return sc.doc.Objects.AddBrep(ng, attr) if attr else sc.doc.Objects.AddBrep(ng)
    if isinstance(ng, Rhino.Geometry.Mesh):
        return sc.doc.Objects.AddMesh(ng, attr) if attr else sc.doc.Objects.AddMesh(ng)
    try:
        return sc.doc.Objects.Add(ng, attr) if attr else sc.doc.Objects.Add(ng)
    except:
        return System.Guid.Empty


# ═══════════════════════════════════════════════════════
#  V3 AGGREGATION HELPERS  (ported from SCA V4)
# ═══════════════════════════════════════════════════════

def _auto_ref_pts(geo):
    """Detect geometry's primary axis from longest bbox dimension.
    Returns (start_pt, end_pt) at the bbox extent along that axis.
    Used when the user has not manually set Start/End reference points.
    Ported from Space_Colonization_Algorithm_V4._auto_ref_pts — accepts geo object."""
    bb = geo.GetBoundingBox(True)
    if not bb.IsValid:
        return None, None
    dx = bb.Max.X - bb.Min.X
    dy = bb.Max.Y - bb.Min.Y
    dz = bb.Max.Z - bb.Min.Z
    cx = (bb.Min.X + bb.Max.X) * 0.5
    cy = (bb.Min.Y + bb.Max.Y) * 0.5
    cz = (bb.Min.Z + bb.Max.Z) * 0.5
    if dx >= dy and dx >= dz:      # X is longest
        return (Rhino.Geometry.Point3d(bb.Min.X, cy, cz),
                Rhino.Geometry.Point3d(bb.Max.X, cy, cz))
    elif dy >= dz:                 # Y is longest
        return (Rhino.Geometry.Point3d(cx, bb.Min.Y, cz),
                Rhino.Geometry.Point3d(cx, bb.Max.Y, cz))
    else:                          # Z is longest
        return (Rhino.Geometry.Point3d(cx, cy, bb.Min.Z),
                Rhino.Geometry.Point3d(cx, cy, bb.Max.Z))


def _auto_short_ref_pts(geo):
    """Detect geometry's SHORTEST bbox axis — for node joints so they sit flat
    (perpendicular) at the junction. E.g. a flat disc: short axis = height → face
    perpendicular to the trail direction.
    Ported from Space_Colonization_Algorithm_V4._auto_short_ref_pts."""
    bb = geo.GetBoundingBox(True)
    if not bb.IsValid:
        return None, None
    dx = bb.Max.X - bb.Min.X
    dy = bb.Max.Y - bb.Min.Y
    dz = bb.Max.Z - bb.Min.Z
    cx = (bb.Min.X + bb.Max.X) * 0.5
    cy = (bb.Min.Y + bb.Max.Y) * 0.5
    cz = (bb.Min.Z + bb.Max.Z) * 0.5
    if dx <= dy and dx <= dz:      # X is shortest
        return (Rhino.Geometry.Point3d(bb.Min.X, cy, cz),
                Rhino.Geometry.Point3d(bb.Max.X, cy, cz))
    elif dy <= dz:                 # Y is shortest
        return (Rhino.Geometry.Point3d(cx, bb.Min.Y, cz),
                Rhino.Geometry.Point3d(cx, bb.Max.Y, cz))
    else:                          # Z is shortest
        return (Rhino.Geometry.Point3d(cx, cy, bb.Min.Z),
                Rhino.Geometry.Point3d(cx, cy, bb.Max.Z))


def _cross_section_size(geo, ref_s, ref_e):
    """Return max bbox dimension PERPENDICULAR to ref axis (ref_s→ref_e).
    Used to match node disc diameter to module cross-section.
    Ported from Space_Colonization_Algorithm_V4._cross_section_size."""
    bb  = geo.GetBoundingBox(True)
    dx  = bb.Max.X - bb.Min.X
    dy  = bb.Max.Y - bb.Min.Y
    dz  = bb.Max.Z - bb.Min.Z
    ax  = abs(ref_e.X - ref_s.X)
    ay  = abs(ref_e.Y - ref_s.Y)
    az  = abs(ref_e.Z - ref_s.Z)
    if ax >= ay and ax >= az:      # X is primary axis
        return max(dy, dz)
    elif ay >= az:                 # Y is primary axis
        return max(dx, dz)
    else:                          # Z is primary axis
        return max(dx, dy)


def _perp_to(axis, up_ref):
    """Return up_ref projected perpendicular to axis, normalised.
    Falls back to YAxis if up_ref is parallel to axis."""
    v = Rhino.Geometry.Vector3d(up_ref)
    v -= axis * (v * axis)          # subtract component along axis
    if v.Length < 1e-6:             # axis ≈ parallel to up_ref — use Y
        v = Rhino.Geometry.Vector3d.YAxis
        v -= axis * (v * axis)
    v.Unitize()
    return v


def _build_orient_xform(seg_start, seg_end, ref_s_pt, ref_e_pt,
                        scale_factor=1.0, radial_scale=None):
    """Build a Rhino Transform that maps module axis (ref_s→ref_e) onto segment
    axis (seg_start→seg_end), applies non-uniform scale, and positions the result.

    Uses PlaneToPlane with world-Z as the roll reference so flat strips, planks, and
    asymmetric cross-sections always face the same way regardless of trail direction.
    (The original Transform.Rotation approach left roll undefined → random spin per sample.)

    Source plane  : origin=ref_s_pt,  X=geo primary axis,  Y=worldZ ⊥ geo axis
    Target plane  : origin=seg_start, X=seg direction,     Y=worldZ ⊥ seg direction
    Roll is therefore always governed by world-Z → strips stand vertical by default.

    scale_factor  : axial (length) scale  — Fit = seg_len/ref_len,  Repeat = 1.0
    radial_scale  : cross-section scale  — 1.0 = natural width/thickness
    """
    geo_vec = Rhino.Geometry.Vector3d(ref_e_pt.X - ref_s_pt.X,
                                      ref_e_pt.Y - ref_s_pt.Y,
                                      ref_e_pt.Z - ref_s_pt.Z)
    seg_vec = Rhino.Geometry.Vector3d(seg_end.X - seg_start.X,
                                      seg_end.Y - seg_start.Y,
                                      seg_end.Z - seg_start.Z)
    if geo_vec.Length < 1e-10 or seg_vec.Length < 1e-10:
        return Rhino.Geometry.Transform.Identity

    geo_unit = Rhino.Geometry.Vector3d(geo_vec); geo_unit.Unitize()
    seg_unit = Rhino.Geometry.Vector3d(seg_vec); seg_unit.Unitize()

    # ── Source plane (module's natural orientation) ─────────
    # X = module primary axis, Y = world-Z projected ⊥ to X
    src_y     = _perp_to(geo_unit, Rhino.Geometry.Vector3d.ZAxis)
    src_plane = Rhino.Geometry.Plane(ref_s_pt, geo_unit, src_y)

    # ── Target plane (on the curve) ─────────────────────────
    # X = segment tangent,    Y = world-Z projected ⊥ to X
    # This locks the roll: strips always face "vertical" (world-Z side)
    tgt_y     = _perp_to(seg_unit, Rhino.Geometry.Vector3d.ZAxis)
    tgt_plane = Rhino.Geometry.Plane(seg_start, seg_unit, tgt_y)

    # ── Step 1: orient module from src_plane → tgt_plane ────
    orient = Rhino.Geometry.Transform.PlaneToPlane(src_plane, tgt_plane)

    # ── Step 2: non-uniform scale at tgt_plane ───────────────
    # X (axial) = scale_factor,  Y/Z (radial) = radial_scale
    rs = radial_scale if radial_scale is not None else 1.0
    if abs(scale_factor - 1.0) < 1e-8 and abs(rs - 1.0) < 1e-8:
        return orient
    scale = Rhino.Geometry.Transform.Scale(tgt_plane, scale_factor, rs, rs)
    return scale * orient


def _duplicate_geo(gid):
    """Duplicate a Rhino geometry object from its GUID. Returns geometry or None."""
    obj = sc.doc.Objects.Find(gid)
    if not obj or obj.IsDeleted:
        return None
    return obj.Geometry.Duplicate()


def _safe_float(text, default=0.0):
    """Parse float from string, returning `default` on failure."""
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


# ═══════════════════════════════════════════════════════
#  STEAM WOOD PLANK HELPERS
# ═══════════════════════════════════════════════════════
def _make_plank_profile(plane, ptype, width, height, shape_param=0.3):
    """
    Build a closed 2D profile curve on `plane`.
      plane.PointAt(u, v): u = width dir (X), v = height/normal dir (Y)

    ptype 0 – Flat Plank   : solid rectangle  width × height
    ptype 1 – Bent Rib     : flat bottom, arc-bowed top face.
                             shape_param = bow as fraction of width (0=flat, 0.5=deep arc)
    ptype 2 – Tapered      : trapezoid, base=width, top=width*(1-shape_param).
                             shape_param 0=rectangle, 1=spike/triangle
    Returns PolylineCurve or NurbsCurve, or None on failure.
    """
    hw = width * 0.5
    P = plane.PointAt  # shorthand

    if ptype == 0:
        # ── Flat Plank ─────────────────────────────────
        pts = [P(-hw, 0), P(hw, 0), P(hw, height), P(-hw, height), P(-hw, 0)]
        return Rhino.Geometry.PolylineCurve(pts)

    elif ptype == 1:
        # ── Bent Rib ───────────────────────────────────
        # Closed polyline approximating an arc crown — never fails.
        # mid_top is the crown; q1/q2 are quarter-arc helper points.
        bl = P(-hw, 0);  br = P(hw, 0)
        tl = P(-hw, height);  tr = P(hw, height)
        bow = max(0.0, shape_param) * width    # upward bulge at crown
        mid_top = P(0.0, height + bow)
        q1 = P(-hw * 0.55, height + bow * 0.65)   # left quarter
        q2 = P( hw * 0.55, height + bow * 0.65)   # right quarter
        pts = [bl, br, tr, q2, mid_top, q1, tl, bl]
        return Rhino.Geometry.PolylineCurve(pts)

    else:
        # ── Tapered ────────────────────────────────────
        sp = max(0.0, min(0.99, shape_param))
        top_hw = hw * (1.0 - sp)
        pts = [P(-hw, 0), P(hw, 0), P(top_hw, height), P(-top_hw, height), P(-hw, 0)]
        return Rhino.Geometry.PolylineCurve(pts)


def _profile_plane_at(pt, tang):
    """
    Build a profile plane at `pt` for a given tangent direction (Z-locked roll).
    Returns (plane, ok).  ok=False if tangent is degenerate.
    """
    t = Rhino.Geometry.Vector3d(tang)
    if not t.Unitize():
        return Rhino.Geometry.Plane.WorldXY, False
    x_ax = _perp_to(t, Rhino.Geometry.Vector3d.ZAxis)
    if x_ax.Length < 1e-8:
        return Rhino.Geometry.Plane.WorldXY, False
    y_ax = Rhino.Geometry.Vector3d.CrossProduct(t, x_ax)
    if not y_ax.Unitize():
        return Rhino.Geometry.Plane.WorldXY, False
    return Rhino.Geometry.Plane(pt, x_ax, y_ax), True


def _sweep_plank(rail, ptype, width, height, shape_param):
    """
    Generate a plank Brep by building the cross-section profile at every sample
    point along `rail` and lofting through them.
    Uses Brep.CreateFromLoft — no SweepOneRail dependency.
    Returns a list of valid Brep, or None.
    """
    if rail is None:
        return None
    try:
        crv_len = rail.GetLength()
    except Exception:
        return None
    if crv_len < 0.5:          # minimum viable plank length
        return None

    # ~3 profiles per unit length for smooth bends; capped at 200
    n_samples = max(4, min(200, int(crv_len * 3) + 1))
    dom = rail.Domain
    profiles = []

    for i in range(n_samples):
        t_norm = i / (n_samples - 1)
        t      = dom.ParameterAt(t_norm)
        try:
            pt   = rail.PointAt(t)
            tang = rail.TangentAt(t)
            pln, ok = _profile_plane_at(pt, tang)
            if not ok:
                continue
            prof = _make_plank_profile(pln, ptype, width, height, shape_param)
            if prof is not None:
                profiles.append(prof)
        except Exception:
            continue   # skip bad sample, keep going

    if len(profiles) < 2:
        return None

    # Try Normal loft first; fall back to Loose if it returns nothing
    for loft_type in (Rhino.Geometry.LoftType.Normal, Rhino.Geometry.LoftType.Loose):
        try:
            breps = Rhino.Geometry.Brep.CreateFromLoft(
                profiles,
                Rhino.Geometry.Point3d.Unset,
                Rhino.Geometry.Point3d.Unset,
                loft_type,
                False)
            if breps:
                valid = [b for b in breps if b is not None and b.IsValid]
                if valid:
                    return valid
        except Exception:
            continue
    return None


def _subdivide_curve_by_length(crv, max_len, joint_gap=0.3):
    """
    Split `crv` into sequential sub-curves each of arc-length ≤ max_len.
    `joint_gap` is removed from BOTH ends of every piece, leaving a physical
    gap between consecutive planks (like real steam-bent joinery).
    Returns a list of trimmed NurbsCurve / Curve segments.
    """
    if crv is None:
        return []
    try:
        total = crv.GetLength()
    except Exception:
        return [crv]
    if total < 0.01:
        return []

    min_piece = max(0.5, joint_gap * 2 + 0.1)   # ignore slivers

    # ── No subdivision: whole curve is one plank ──────────
    if max_len <= 0 or total <= max_len + 1e-6:
        if joint_gap > 1e-6 and total > min_piece:
            ok0, t0 = crv.LengthParameter(joint_gap)
            ok1, t1 = crv.LengthParameter(total - joint_gap)
            if ok0 and ok1 and t1 > t0:
                sub = crv.Trim(t0, t1)
                if sub and sub.IsValid:
                    return [sub]
        return [crv]

    # ── Walk the curve in max_len chunks ──────────────────
    segs = []
    start_len = 0.0
    while start_len < total - 1e-6:
        end_len = min(start_len + max_len, total)
        # Inner extents after gap removal
        inner_s = start_len + joint_gap
        inner_e = end_len   - joint_gap
        if inner_e - inner_s >= min_piece:
            ok0, t0 = crv.LengthParameter(inner_s)
            ok1, t1 = crv.LengthParameter(inner_e)
            if ok0 and ok1 and t1 > t0:
                sub = crv.Trim(t0, t1)
                if sub and sub.IsValid:
                    segs.append(sub)
        start_len = end_len

    return segs if segs else [crv]


# ═══════════════════════════════════════════════════════
#  MAIN FORM
# ═══════════════════════════════════════════════════════
class FlockingBoids_V1(forms.Form):

    def __init__(self):
        super().__init__()
        self.Title      = "Flocking Boids V3 — Reynolds Flocking + SCA Aggregation"
        self.Padding    = drawing.Padding(10)
        self.Resizable  = True
        self.Topmost    = True
        self.ClientSize = drawing.Size(420, 960)

        # ── Simulation state ──────────────────────────────
        self.boids          = []
        self.attractors     = []
        self.is_running     = False
        self.void_brep      = None
        self.void_breps     = []
        self.void_bbox      = None
        self.mass_breps     = []
        self.mass_bboxes    = []
        self.surface_mesh     = None
        self.surface_centroid = None   # average face-centre of surface mesh (for interior pull)
        self.base_geo_id    = None   # M1
        self.base_geo_id_2  = None   # M2
        self.base_geo_id_3  = None   # M3
        self.aggregated_ids    = []
        self.trail_ids         = []
        self.picked_curve_ids  = []   # curves picked from doc for aggregation
        # V3: SCA aggregation extras
        self.man_ref_start        = None   # manual axis start point
        self.man_ref_end          = None   # manual axis end point
        self.node_geo_id          = None   # joint node geometry GUID
        self.arm_geo_id           = None   # joint arm geometry GUID
        self.aggregated_joint_ids = []     # GUIDs of joint geometry for clear
        # V3: steam wood planks
        self.plank_ids            = []     # GUIDs of generated plank geometry

        self.conduit            = BoidConduit()
        self.conduit.boids      = self.boids
        self.conduit.attractors = self.attractors

        self._build_ui()
        self._wire_events()
        self._update_void_ui(2)      # default to Surface mode
        self._update_attr_mode_ui(0) # idx 0 = SlowField → slow speed field visible

    # ── Static geometry helpers (from V8) ─────────────────
    @staticmethod
    def _try_get_brep(geo):
        if geo is None: return None
        if isinstance(geo, Rhino.Geometry.Brep): return geo
        for conv in [
            lambda g: g.ToBrep(True) if isinstance(g, Rhino.Geometry.Extrusion) else None,
            lambda g: Rhino.Geometry.Brep.CreateFromMesh(g, True) if isinstance(g, Rhino.Geometry.Mesh) else None,
            lambda g: Rhino.Geometry.Brep.CreateFromSubD(g, 0) if isinstance(g, Rhino.Geometry.SubD) else None,
            lambda g: g.ToBrep() if hasattr(g, 'ToBrep') else None,
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
        for attempt in [
            lambda: Rhino.Geometry.Mesh.CreateFromSurface(geo)
                    if isinstance(geo, Rhino.Geometry.Surface) else None,
            lambda: _from_brep(geo)
                    if isinstance(geo, Rhino.Geometry.Brep) else None,
            lambda: _from_brep(geo.ToBrep(True))
                    if isinstance(geo, Rhino.Geometry.Extrusion) else None,
            lambda: Rhino.Geometry.Mesh.CreateFromSubD(geo, 0)
                    if isinstance(geo, Rhino.Geometry.SubD) else None,
        ]:
            try:
                m = attempt()
                if m: return m
            except: pass
        return None

    # ── Collapsible section factory (from V8) ─────────────
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

    # ── Build UI ──────────────────────────────────────────
    def _build_ui(self):
        bold  = drawing.Font("Segoe UI", 9, drawing.FontStyle.Bold)
        GD    = drawing.Color.FromArgb(15,  10,  35)
        GPURP = drawing.Color.FromArgb(120,  40, 200)
        GCYAN = drawing.Color.FromArgb(0,   210, 230)
        GPINK = drawing.Color.FromArgb(220,  20, 130)
        GBLUE = drawing.Color.FromArgb(30,  130, 240)
        GTEXT = drawing.Color.FromArgb(210, 210, 240)
        GACC  = drawing.Color.FromArgb(100, 190, 255)
        GGRN  = drawing.Color.FromArgb(0,   180, 100)
        GTEAL = drawing.Color.FromArgb(0,   140, 160)
        GDARK = drawing.Color.FromArgb(60,   60,  90)
        GDIM  = drawing.Color.FromArgb(130, 130, 155)
        self.BackgroundColor = GD

        def lbl(text, color=GTEXT):
            l = forms.Label(); l.Text = text; l.TextColor = color; return l
        def d(text):
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
        self.dd_preset        = dd("Custom (manual)",
                                   "1 ⬡ Flock — Surface",
                                   "2 ⬡ Flock — Volume",
                                   "3 ≋ Facade Wrap",
                                   "4 ≋ Strong Sweep")
        self.dd_preset.SelectedIndex = 1
        self.btn_apply_preset = B("Apply Preset", GPURP)
        self.lbl_preset_hint  = lbl("", GGRN)

        # ── VOID MODE ─────────────────────────────────────
        lbl_vh = lbl("◈  VOID MODE  — Step 1", GCYAN); lbl_vh.Font = bold
        self.dd_void            = dd("A: Brep (void container)",
                                     "B: BBox − Mass geometry",
                                     "D: Surface-Based")
        self.dd_void.SelectedIndex = 2
        self.btn_void_input     = B("Select Surface Geometry", GBLUE)
        self.btn_bbox_container = B("1. Select Container Box", GBLUE)
        self.btn_bbox_mass      = B("2. Select Mass to Exclude", GPURP)
        self.lbl_bbox_container = lbl("— no container set", GDIM)
        self.lbl_void_status    = lbl("No void defined", GCYAN)

        # ── V2: Surface 3D Offset ─────────────────────────
        self.dd_offset_mode   = dd("Off — Flat (V1)",
                                   "Offset Shell  [inner ↔ outer band]",
                                   "Soft Attract  [spring to target]",
                                   "Variable Layer  [per-boid random target]")
        self.txt_offset_inner = T("0.0")
        self.txt_offset_outer = T("5.0")
        self.txt_spring_k     = T("0.3")
        self.lbl_offset_status = lbl("", GDIM)

        # ── FLOCKING ──────────────────────────────────────
        # Behavior style quick-switch buttons
        self.btn_style_flock = B("⬡  Classic Flock", GPURP)
        self.btn_style_wrap  = B("≋  Facade Wrap", GTEAL)

        # Default = Classic Flock weights (organic, cohesion-driven)
        self.txt_nbr_radius = T("5.0")
        self.txt_sep_dist   = T("1.8")
        self.txt_sep_w      = T("2.0")
        self.txt_ali_w      = T("1.0")
        self.txt_coh_w      = T("1.0")
        self.txt_max_speed  = T("1.5")
        self.txt_max_force  = T("0.15")
        hdr_flock, self.pnl_flock = self._make_section("FLOCKING  (Reynolds Rules)", GPURP, [
            [d("─ Behavior Style — instant weight switch ─")],
            [self.btn_style_flock, self.btn_style_wrap],
            [d("⬡ Organic clusters / branching trails (high cohesion)")],
            [d("≋ Parallel wrap lines on surface (high sep+align, low cohesion + Wind)")],
            [d("How far each boid can see its neighbours")],
            [lbl("Neighbour Radius:", GTEXT), self.txt_nbr_radius],
            [d("Separation threshold — boids closer than this actively push apart")],
            [lbl("Separation Dist:",  GTEXT), self.txt_sep_dist],
            [d("Sep / Align / Cohesion weights")],
            [lbl("Separation W:",     GTEXT), self.txt_sep_w],
            [lbl("Alignment W:",      GTEXT), self.txt_ali_w],
            [lbl("Cohesion W:",       GTEXT), self.txt_coh_w],
            [d("Speed cap per step.  Force cap per steering impulse")],
            [lbl("Max Speed:",        GTEXT), self.txt_max_speed],
            [lbl("Max Force:",        GTEXT), self.txt_max_force],
        ], collapsed=False)

        # ── EXPLORATION ───────────────────────────────────
        self.txt_n_boids = T("60")
        self.txt_steps   = T("200")
        self.txt_jitter  = T("0.05")
        self.txt_seed    = T("0")
        hdr_exp, self.pnl_exp = self._make_section("EXPLORATION", GBLUE, [
            [d("Total boids spawned per run")],
            [lbl("Boids:",            GTEXT), self.txt_n_boids],
            [d("Max lifespan — steps each boid lives")],
            [lbl("Steps:",            GTEXT), self.txt_steps],
            [d("Random noise added each step  (0=smooth paths, 0.2=chaotic)")],
            [lbl("Jitter:",           GTEXT), self.txt_jitter],
            [d("Seed 0 = random each run.  Non-zero = reproducible")],
            [lbl("Seed (0=random):",  GTEXT), self.txt_seed],
        ], collapsed=False)

        # ── STEERING  (Attractors) ─────────────────────────
        self.btn_add_attractors        = B("Click-to-Place Attractors  (loop, Esc stops)", GPINK)
        self.btn_add_from_objects      = B("◈ Pick Climate Data Points / Objects  (multi-select)", GPINK)
        self.btn_add_single_attractor  = B("Add Single Attractor", GPINK)
        self.btn_clear_attractors      = B("Clear Attractors", GPURP)
        self.lbl_attractors            = lbl("0 attractors", GACC)
        self.dd_attr_mode              = dd("SlowField", "Orbit", "Repulse", "Converge")
        self.txt_attr_strength         = T("1.0")
        self.txt_attr_radius           = T("5.0")
        self.txt_attr_decay            = T("0.0")
        self.lbl_slow_speed            = lbl("Slow Speed (0–1):", GTEXT)
        self.txt_slow_speed            = T("0.3")
        self.txt_attr_weight           = T("0.4")
        self.lbl_mode_hint             = lbl("", GACC)   # V3: climate mode hint, updated on mode change
        hdr_steer, self.pnl_steer = self._make_section("STEERING  (Attractors)", GPINK, [
            [d("── Climate Data workflow ──────────────────────────────────────")],
            [d("1. Set mode below  →  2. Set Radius + Strength  →  3. Pick Climate Data Points")],
            [d("Hot zone modes:  SlowField (dense trails=shade)  |  Converge (route toward)")],
            [d("              Orbit (swirl pattern)  |  Repulse (ventilation opening)")],
            [d("─────────────────────────────────────────────────────────────")],
            [self.btn_add_attractors],
            [d("Click in viewport to place attractors one by one — Esc to stop")],
            [self.btn_add_from_objects],
            [d("Select any objects — points, voxels, breps (uses bbox centre as attractor position)")],
            [d("⟶  Climate use: select hot-zone voxels from CCS data.  Set mode below before picking")],
            [self.btn_add_single_attractor, self.btn_clear_attractors],
            [self.lbl_attractors],
            [lbl("Attractor Mode:",   GTEXT), self.dd_attr_mode],
            [self.lbl_mode_hint],
            [lbl("Strength:",         GTEXT), self.txt_attr_strength],
            [d("Pull/push intensity (Converge/Repulse/Orbit only)")],
            [lbl("Radius:",           GTEXT), self.txt_attr_radius],
            [d("Influence distance — boids outside this radius are unaffected")],
            [lbl("Decay:",            GTEXT), self.txt_attr_decay],
            [d("Rate attractor fades per step  (0 = permanent)")],
            [self.lbl_slow_speed,             self.txt_slow_speed],
            [d("SlowField only: fraction of max speed inside radius  (0.1=very slow)")],
            [lbl("Attr Weight:",      GTEXT), self.txt_attr_weight],
            [d("Overall attractor influence on boid steering  (0 = off,  2 = strong)")],
        ], collapsed=False)

        # ── WIND BIAS  (collapsible) ──────────────────────
        self.txt_wx          = T("1")
        self.txt_wy          = T("0")
        self.txt_wz          = T("0")
        self.txt_wind_weight = T("0.0")
        hdr_wind, self.pnl_wind = self._make_section("WIND BIAS  (expand for facade wrap)", GTEAL, [
            [d("Dominant flow direction — drives parallel wrapping on surface")],
            [d("★ Facade Wrap style: set Wind X/Y/Z across your surface + weight 0.5–0.9")],
            [lbl("Wind  X / Y / Z:",  GTEXT)],
            [self.txt_wx, self.txt_wy, self.txt_wz],
            [lbl("Wind Weight:",      GTEXT), self.txt_wind_weight],
            [d("0=off  0.5=moderate drift  0.9=strong sweep  (Facade Wrap auto-sets 0.6)")],
        ], collapsed=True)

        # ── Run controls ──────────────────────────────────
        self.btn_start       = B("▶  Initialize & Run", GBLUE)
        self.btn_stop        = B("■  Stop", GPINK)
        self.lbl_boid_count  = lbl("", GACC)
        self.lbl_status      = lbl("Status: Ready", GACC)

        # ── VISUALIZATION  (collapsible) ──────────────────
        self.chk_show_tails  = chk("Show Tails in Viewport", True)
        self.txt_tail_length = T("30")
        self.dd_color_mode   = dd("By Speed", "By Age", "Solid Theme")
        self.dd_theme        = dd(*[name for name, _ in HEATMAP_THEMES])
        self.dd_theme.SelectedIndex = 0   # default: Galaxy
        hdr_viz, self.pnl_viz = self._make_section("VISUALIZATION", GDARK, [
            [self.chk_show_tails],
            [d("Live polyline tails per boid in viewport  (uncheck for performance)")],
            [lbl("Tail Length (steps):", GTEXT), self.txt_tail_length],
            [d("How many history steps shown as tail  (viewport only, full history baked)")],
            [lbl("Color Mode:",       GTEXT), self.dd_color_mode],
            [d("By Speed: fast=warm end  By Age: young=cool, old=warm")],
            [lbl("Color Theme:",      GTEXT), self.dd_theme],
        ], collapsed=True)

        # ── OUTPUT ────────────────────────────────────────
        lbl_out = lbl("─── Output ───", GPINK); lbl_out.Font = bold
        self.chk_bake_tails   = chk("Bake Tails on Complete  (→ Boids::Trails)", True)
        self.btn_bake_now     = B("Bake Trails Now", GGRN)
        self.btn_pick_curves  = B("Pick Existing Curves for Aggregation", GTEAL)
        self.lbl_picked       = lbl("— no curves picked  (uses live simulation data)", GDIM)

        # 3 module slots
        self.btn_create_x     = B("Create X  (→ M1)", GPURP)
        self.btn_select_m1    = B("M1  Select Geometry", GPURP)
        self.btn_select_m2    = B("M2  Select Geometry", GPURP)
        self.btn_select_m3    = B("M3  Select Geometry", GPURP)
        self.lbl_m1           = lbl("M1: — not assigned", GDIM)
        self.lbl_m2           = lbl("M2: — not assigned  (falls back to M1)", GDIM)
        self.lbl_m3           = lbl("M3: — not assigned  (falls back to M1)", GDIM)

        # Aggregation logic
        self.dd_agg_logic     = dd(
            "Sequential       (Gramazio & Kohler)",
            "Speed-Based      (Neri Oxman)",
            "Curvature        (ICD Stuttgart)",
            "Density Field    (ZHA)",
            "Layer Stack      (Snøhetta)",
        )
        self.txt_spacing      = T("1.5")
        self.chk_adaptive     = chk("Adaptive Spacing  (from M1 bbox)", True)

        # Mode-specific params
        # Speed-Based thresholds (normalised 0–1 fraction of max_speed)
        self.txt_speed_t1     = T("0.4")   # slow / mid boundary
        self.txt_speed_t2     = T("0.7")   # mid / fast boundary
        # Curvature thresholds (normalised 0–1)
        self.txt_curv_t1      = T("0.4")
        self.txt_curv_t2      = T("0.7")
        # Density Field radius + thresholds (normalised 0–1)
        self.txt_density_r    = T("3.0")
        self.txt_dens_t1      = T("0.4")
        self.txt_dens_t2      = T("0.7")
        # Layer Stack offsets along surface / curve normal
        self.txt_layer_off1   = T("1.0")   # M2 offset
        self.txt_layer_off2   = T("2.0")   # M3 offset

        # V3: MODULAR precision controls
        self.chk_manual_axis  = chk("Manual Axis  (pick Start / End ref pts on module)", False)
        self.btn_set_ref      = B("Set Ref Pts", GBLUE)
        self.lbl_ref_status   = lbl("— auto-detect from bbox longest axis", GDIM)
        self.dd_scale_mode    = dd("Fit  (stretch module to fill spacing)",
                                   "Repeat  (tile at module natural size)")
        self.txt_mod_scale    = T("1.0")
        self.txt_mod_gap      = T("0.0")

        # V3: JOINT system
        self.chk_joints       = chk("Enable Joints  (endpoints + crossings)", False)
        self.btn_sel_node     = B("Node Geo  Select", GPURP)
        self.lbl_node         = lbl("— not assigned", GDIM)
        self.txt_node_scale   = T("1.0")
        self.btn_sel_arm      = B("Arm Geo  Select", GPURP)
        self.lbl_arm          = lbl("— not assigned", GDIM)
        self.txt_arm_offset   = T("1.0")
        self.txt_arm_scale    = T("1.0")
        self.txt_cross_thresh = T("2.0")

        # V3: aggregation seed (for reproducibility when randomness is used)
        self.txt_agg_seed     = T("42")

        self.btn_aggregate    = B("Aggregate Modules", GPURP)
        self.btn_gen_mesh     = B("Generate Mesh Skin", GPURP)
        self.btn_clear_trails = B("Clear Baked Trails", GCYAN)
        self.btn_clear_agg    = B("Clear Aggregated", GGRN)
        self.btn_clear_all    = B("Clear All Geometry", GCYAN)

        # V3: STEAM WOOD PLANKS controls ──────────────────
        _ptypes = ("Flat Plank  (rectangle)", "Bent Rib  (arc top face)", "Tapered  (trapezoid)")

        # Profile 1
        # P1 — Flat Plank   2.0 × 0.5  (steam-bent plank reference proportion)
        self.dd_p1_type   = dd(*_ptypes); self.dd_p1_type.SelectedIndex = 0
        self.txt_p1_width = T("2.0")
        self.txt_p1_height= T("0.5")
        self.txt_p1_shape = T("0.1")

        # P2 — Bent Rib     2.5 × 0.4  (slightly wider, slight crown bow)
        self.dd_p2_type   = dd(*_ptypes); self.dd_p2_type.SelectedIndex = 1
        self.txt_p2_width = T("2.5")
        self.txt_p2_height= T("0.4")
        self.txt_p2_shape = T("0.15")

        # P3 — Tapered      1.8 × 0.6  (narrower at top — wedge/edge plank)
        self.dd_p3_type   = dd(*_ptypes); self.dd_p3_type.SelectedIndex = 2
        self.txt_p3_width = T("1.8")
        self.txt_p3_height= T("0.6")
        self.txt_p3_shape = T("0.25")

        # Plank logic
        self.dd_plank_logic = dd(
            "P1 Only          — single profile on every trail",
            "Alternate         — P1 / P2 / P3 cycle by trail index",
            "By Speed          — slow trail→P1  mid→P2  fast→P3",
            "By Curvature      — high curve→P1  mid→P2  straight→P3",
            "Layer Stack       — all 3 at every trail (offsets below)",
        )

        # Layer Stack plank offsets (along normal/Z)
        self.txt_plank_off1 = T("0.5")    # P2 offset
        self.txt_plank_off2 = T("1.0")    # P3 offset

        # Plank segmentation (physical piece length + joint gap)
        self.txt_plank_max_len = T("40.0")   # max arc-length per plank piece (0 = no limit)
        self.txt_plank_gap     = T("0.5")    # physical gap removed from each joint end

        # Buttons
        self.btn_gen_planks   = B("Generate Steam Wood Planks", drawing.Color.FromArgb(255, 200, 100, 40))
        self.btn_clear_planks = B("Clear Planks", GCYAN)
        self.lbl_plank_status = lbl("● Ready — Bake Trails (or Pick Curves) then click Generate", GDIM)

        # ── Assemble main layout ───────────────────────────
        L = forms.DynamicLayout()
        L.Spacing = drawing.Size(4, 3)

        # ── HOW TO USE ────────────────────────────────────────
        lbl_how = lbl("◈  HOW TO USE", GCYAN); lbl_how.Font = bold
        L.AddRow(lbl_how)
        L.AddRow(d("─────────────────────────────────────────────────"))
        L.AddRow(d("ORGANIC FLOCKING (branching / converging trails):"))
        L.AddRow(d("  1. Select void geometry  →  Mode A (Brep) or D (Surface)"))
        L.AddRow(d("  2. Preset: ⬡ Flock — Surface / Volume   or   click ⬡ Classic Flock"))
        L.AddRow(d("  3. (Optional) Add Converge attractors to route trails toward zones"))
        L.AddRow(d("  4. ▶ Initialize & Run"))
        L.AddRow(d("─────────────────────────────────────────────────"))
        L.AddRow(d("FACADE WRAP (parallel lines wrapping surface):"))
        L.AddRow(d("  1. Select surface  →  Mode D"))
        L.AddRow(d("  2. Preset: ≋ Facade Wrap / Strong Sweep   or   click ≋ Facade Wrap"))
        L.AddRow(d("  3. Set Wind X/Y/Z direction across your surface  (weight 0.5–0.9)"))
        L.AddRow(d("  4. (Optional) Add SlowField attractors at light-priority zones"))
        L.AddRow(d("     → boids linger → denser trail bands at those zones"))
        L.AddRow(d("  5. ▶ Initialize & Run   →   Bake Tails → apply geometry"))
        L.AddRow(d("─────────────────────────────────────────────────"))

        lbl_ph = lbl("◈  PRESETS", GCYAN); lbl_ph.Font = bold
        L.AddRow(lbl_ph)
        L.AddRow(d("Quick-start templates — auto-fills all parameters"))
        L.AddRow(self.dd_preset, self.btn_apply_preset)
        L.AddRow(self.lbl_preset_hint)

        L.AddRow(lbl_vh)
        L.AddRow(d("Defines the space where boids move"))
        L.AddRow(self.dd_void)
        L.AddRow(d("A=Brep interior  B=BBox−Mass  D=Surface (velocity projected to tangent plane)"))
        L.AddRow(self.btn_void_input)
        L.AddRow(self.btn_bbox_container)
        L.AddRow(self.lbl_bbox_container)
        L.AddRow(d("Mode B step 1 — pick any box/brep as outer simulation boundary"))
        L.AddRow(self.btn_bbox_mass)
        L.AddRow(d("Mode B step 2 — pick solid masses to exclude (optional)"))
        L.AddRow(self.lbl_void_status)

        # ── V2 Surface 3D Offset (shown always; only active in Mode D) ──
        lbl_off = lbl("◈  SURFACE 3D OFFSET  (Mode D only)", GTEAL); lbl_off.Font = bold
        L.AddRow(lbl_off)
        L.AddRow(self.dd_offset_mode)
        L.AddRow(d("Off:      flat on surface (V1 behaviour)"))
        L.AddRow(d("Shell:    boids in 3D band [inner → outer] — facade depth layer"))
        L.AddRow(d("Soft:     spring pulls boid to mid-offset — organic hover + weave"))
        L.AddRow(d("Variable: each boid has own random target — volumetric flock cloud"))
        L.AddRow(lbl("Offset Inner (min dist):", GTEXT), self.txt_offset_inner)
        L.AddRow(lbl("Offset Outer (max dist):", GTEXT), self.txt_offset_outer)
        L.AddRow(d("Inner 0 = on surface.  Outer = thickness of the 3D volume above surface"))
        L.AddRow(lbl("Spring Strength:", GTEXT), self.txt_spring_k)
        L.AddRow(d("Soft / Variable only: how strongly boids are pulled to target offset"))
        L.AddRow(self.lbl_offset_status)

        L.AddRow(hdr_flock);  L.AddRow(self.pnl_flock)
        L.AddRow(hdr_exp);    L.AddRow(self.pnl_exp)
        L.AddRow(hdr_steer);  L.AddRow(self.pnl_steer)
        L.AddRow(hdr_wind);   L.AddRow(self.pnl_wind)

        L.AddRow(self.btn_start, self.btn_stop)
        L.AddRow(self.lbl_boid_count)
        L.AddRow(self.lbl_status)

        L.AddRow(hdr_viz);    L.AddRow(self.pnl_viz)

        L.AddRow(lbl_out)
        L.AddRow(self.chk_bake_tails)
        L.AddRow(d("Degree-3 interpolated NURBS curve per boid → Boids::Trails layer"))
        L.AddRow(self.btn_bake_now)
        L.AddRow(self.btn_pick_curves)
        L.AddRow(self.lbl_picked)
        L.AddRow(d("Pick baked curves from scene to aggregate on — works after GUI reopen"))

        L.AddRow(lbl("─── MODULAR  (3 Module Slots) ───", GPINK))
        L.AddRow(d("Assign up to 3 geometries — aggregation logic selects which to place where"))
        L.AddRow(self.btn_create_x)
        L.AddRow(self.btn_select_m1); L.AddRow(self.lbl_m1)
        L.AddRow(self.btn_select_m2); L.AddRow(self.lbl_m2)
        L.AddRow(self.btn_select_m3); L.AddRow(self.lbl_m3)

        L.AddRow(lbl("─── V3: Placement Precision ───", GACC))
        L.AddRow(self.chk_manual_axis)
        L.AddRow(d("OFF = auto-detect primary axis from bbox longest dimension (recommended)"))
        L.AddRow(d("ON  = pick Start / End reference points on your module geometry manually"))
        L.AddRow(self.btn_set_ref, self.lbl_ref_status)
        L.AddRow(lbl("Scale Mode:", GTEXT), self.dd_scale_mode)
        L.AddRow(d("Fit:    modules stretch axially to fill each spacing interval (default)"))
        L.AddRow(d("Repeat: modules tile at their natural size — no axial stretching"))
        L.AddRow(lbl("Module Scale (radial):", GTEXT), self.txt_mod_scale)
        L.AddRow(d("Cross-section multiplier — 1.0=natural  0.5=half-width  2.0=double-wide"))
        L.AddRow(lbl("Module Gap:", GTEXT), self.txt_mod_gap)
        L.AddRow(d("Pullback from each trail end before placing modules  (0=fill whole trail)"))

        L.AddRow(lbl("─── V3: JOINT System ───", GACC))
        L.AddRow(self.chk_joints)
        L.AddRow(d("Places connection geometry at trail endpoints and crossing points"))
        L.AddRow(d("Node geo: disc/hub at joint position.  Arm geo: directed along trail tangent"))
        L.AddRow(self.btn_sel_node, self.lbl_node)
        L.AddRow(lbl("Node Scale:", GTEXT), self.txt_node_scale)
        L.AddRow(d("Uniform scale of node geometry  (1.0 = natural size)"))
        L.AddRow(self.btn_sel_arm, self.lbl_arm)
        L.AddRow(lbl("Arm Offset:", GTEXT), self.txt_arm_offset,
                 lbl("  Arm Scale:", GTEXT), self.txt_arm_scale)
        L.AddRow(d("Arm offset: distance from joint along trail tangent  |  Arm scale: length multiplier"))
        L.AddRow(lbl("Crossing Threshold:", GTEXT), self.txt_cross_thresh)
        L.AddRow(d("Max distance between two trails to be considered crossing  (Rhino units)"))

        L.AddRow(lbl("─── Aggregation Logic ───", GPINK))
        L.AddRow(self.dd_agg_logic)
        L.AddRow(d("Sequential  (Gramazio & Kohler):  M1=trail start  M2=mid  M3=end"))
        L.AddRow(d("Speed-Based (Neri Oxman):  slow boid→M1(dense)  mid→M2  fast→M3"))
        L.AddRow(d("Curvature   (ICD Stuttgart): high curve→M1(joint) mid→M2  straight→M3"))
        L.AddRow(d("Density     (ZHA): dense trail zone→M1  medium→M2  sparse→M3"))
        L.AddRow(d("Layer Stack (Snøhetta): all 3 at every point, offset along normal"))

        L.AddRow(lbl("Speed thresholds (Speed-Based):", GTEXT))
        L.AddRow(lbl("  slow/mid:", GTEXT), self.txt_speed_t1,
                 lbl("  mid/fast:", GTEXT), self.txt_speed_t2)
        L.AddRow(lbl("Curvature thresholds (Curvature):", GTEXT))
        L.AddRow(lbl("  low/mid:", GTEXT),  self.txt_curv_t1,
                 lbl("  mid/high:", GTEXT), self.txt_curv_t2)
        L.AddRow(lbl("Density radius + thresholds (Density):", GTEXT))
        L.AddRow(lbl("  radius:", GTEXT),   self.txt_density_r,
                 lbl("  lo/mid:", GTEXT),   self.txt_dens_t1,
                 lbl("  mid/hi:", GTEXT),   self.txt_dens_t2)
        L.AddRow(lbl("Layer offsets along normal (Layer Stack):", GTEXT))
        L.AddRow(lbl("  M2 offset:", GTEXT), self.txt_layer_off1,
                 lbl("  M3 offset:", GTEXT), self.txt_layer_off2)

        L.AddRow(lbl("Spacing:", GTEXT), self.txt_spacing)
        L.AddRow(self.chk_adaptive)
        L.AddRow(d("Auto-sets spacing = M1 bbox max extent (Fit) or axis length (Repeat)"))
        L.AddRow(lbl("Aggregation Seed:", GTEXT), self.txt_agg_seed)
        L.AddRow(d("Seed for any random variation in aggregation  (0 = random each run)"))
        L.AddRow(self.btn_aggregate)
        L.AddRow(self.btn_gen_mesh)
        L.AddRow(d("Proximity-triangulated mesh skin from all trail points"))
        L.AddRow(self.btn_clear_trails, self.btn_clear_agg)
        L.AddRow(self.btn_clear_all)
        L.AddRow(d("Clear All: removes curves, breps, meshes (preserves module geometry)"))

        # ── STEAM WOOD PLANKS ─────────────────────────────
        lbl_plk = lbl("◈  STEAM WOOD PLANKS", drawing.Color.FromArgb(255, 200, 100, 40))
        lbl_plk.Font = bold
        L.AddRow(lbl_plk)
        L.AddRow(d("Sweep 3 cross-section profiles along boid trails to generate"))
        L.AddRow(d("steam-bent wood plank geometry  →  Boids::WoodPlanks::P1/P2/P3"))

        L.AddRow(lbl("── Profile 1  (P1) ──", GACC))
        L.AddRow(lbl("Type:", GTEXT), self.dd_p1_type)
        L.AddRow(lbl("Width (X):", GTEXT), self.txt_p1_width,
                 lbl("  Height (Y):", GTEXT), self.txt_p1_height)
        L.AddRow(lbl("Shape (0–1):", GTEXT), self.txt_p1_shape)
        L.AddRow(d("Shape: Flat=unused  BentRib=arc bow factor  Tapered=taper ratio"))

        L.AddRow(lbl("── Profile 2  (P2) ──", GACC))
        L.AddRow(lbl("Type:", GTEXT), self.dd_p2_type)
        L.AddRow(lbl("Width (X):", GTEXT), self.txt_p2_width,
                 lbl("  Height (Y):", GTEXT), self.txt_p2_height)
        L.AddRow(lbl("Shape (0–1):", GTEXT), self.txt_p2_shape)

        L.AddRow(lbl("── Profile 3  (P3) ──", GACC))
        L.AddRow(lbl("Type:", GTEXT), self.dd_p3_type)
        L.AddRow(lbl("Width (X):", GTEXT), self.txt_p3_width,
                 lbl("  Height (Y):", GTEXT), self.txt_p3_height)
        L.AddRow(lbl("Shape (0–1):", GTEXT), self.txt_p3_shape)

        L.AddRow(lbl("── Plank Logic ──", GACC))
        L.AddRow(self.dd_plank_logic)
        L.AddRow(d("P1 Only:     one plank per trail"))
        L.AddRow(d("Alternate:   cycles P1→P2→P3 across trails"))
        L.AddRow(d("By Speed:    maps boid average speed to profile index"))
        L.AddRow(d("By Curvature:maps average trail curvature to profile index"))
        L.AddRow(d("Layer Stack: all 3 profiles at every trail, offset along normal"))
        L.AddRow(lbl("Layer Stack P2 offset:", GTEXT), self.txt_plank_off1)
        L.AddRow(lbl("Layer Stack P3 offset:", GTEXT), self.txt_plank_off2)
        L.AddRow(d("Offset = push plank outward along surface normal  (Rhino units)"))

        L.AddRow(lbl("── Segmentation ──", GACC))
        L.AddRow(lbl("Max Plank Length:", GTEXT), self.txt_plank_max_len)
        L.AddRow(d("Max arc-length per plank piece  (0 = one piece per trail)  |  Rhino units"))
        L.AddRow(lbl("Joint Gap:", GTEXT), self.txt_plank_gap)
        L.AddRow(d("Physical gap cut at every joint end  (e.g. 0.5 = 0.5 unit gap between pieces)"))

        L.AddRow(self.btn_gen_planks)
        L.AddRow(self.lbl_plank_status)
        L.AddRow(self.btn_clear_planks)

        scrl = forms.Scrollable()
        scrl.Content = L
        self.Content = scrl

    # ── Wire events ───────────────────────────────────────
    def _wire_events(self):
        self.dd_void.SelectedIndexChanged          += self.OnVoidModeChanged
        self.btn_void_input.Click                  += self.OnVoidInput
        self.btn_bbox_container.Click              += self.OnPickBBoxContainer
        self.btn_bbox_mass.Click                   += self.OnPickBBoxMass
        self.btn_apply_preset.Click                += self.OnApplyPreset
        self.btn_style_flock.Click                 += self.OnStyleFlock
        self.btn_style_wrap.Click                  += self.OnStyleWrap
        self.btn_add_attractors.Click              += self.OnAddAttractors
        self.btn_add_from_objects.Click            += self.OnAddAttractorsFromObjects
        self.btn_add_single_attractor.Click        += self.OnAddSingleAttractor
        self.btn_clear_attractors.Click            += self.OnClearAttractors
        self.dd_attr_mode.SelectedIndexChanged     += self.OnAttrModeChanged
        self.chk_show_tails.CheckedChanged         += self.OnShowTailsChanged
        self.dd_color_mode.SelectedIndexChanged    += self.OnColorModeChanged
        self.dd_theme.SelectedIndexChanged         += self.OnThemeChanged
        self.btn_start.Click                       += self.OnStartClick
        self.btn_stop.Click                        += self.OnStopClick
        self.btn_bake_now.Click                    += self.OnBakeTrails
        self.btn_pick_curves.Click                 += self.OnPickCurves
        self.btn_create_x.Click                    += self.OnCreateX
        self.btn_select_m1.Click                   += self.OnSelectM1
        self.btn_select_m2.Click                   += self.OnSelectM2
        self.btn_select_m3.Click                   += self.OnSelectM3
        self.chk_adaptive.CheckedChanged           += self.OnAdaptiveToggle
        self.btn_aggregate.Click                   += self.OnAggregate
        self.btn_gen_mesh.Click                    += self.OnGenerateMesh
        self.btn_clear_trails.Click                += self.OnClearTrails
        self.btn_clear_agg.Click                   += self.OnClearAggregated
        self.btn_clear_all.Click                   += self.OnClearAll
        self.btn_gen_planks.Click                  += self.OnGeneratePlanks
        self.btn_clear_planks.Click                += self.OnClearPlanks
        self.Closed                                += self.OnFormClosed
        # V3 new events
        self.btn_set_ref.Click                     += self.OnSetRefPts
        self.btn_sel_node.Click                    += self.OnSelectNode
        self.btn_sel_arm.Click                     += self.OnSelectArm

    # ── UI state helpers ──────────────────────────────────
    def _update_void_ui(self, idx):
        labels = ["Select Void Brep",
                  "Select Mass Geometry",
                  "Select Surface Geometry"]
        self.btn_void_input.Text    = labels[idx] if idx < len(labels) else "Select Geometry"
        show_bbox = (idx == 1)
        self.btn_bbox_container.Visible = show_bbox
        self.lbl_bbox_container.Visible = show_bbox
        self.btn_bbox_mass.Visible      = show_bbox

    # V3: climate mode hints
    _MODE_HINTS = [
        "★ Hot zone → SlowField:  boids decelerate inside radius → linger → dense trail cluster → more geometry coverage → shading",
        "★ Hot zone → Orbit:  boids spiral around each hot point → swirling facade pattern → ventilation-stack aesthetic",
        "★ Hot zone → Repulse:  boids flee hot zone → sparse/void area → perforation / convective opening strategy",
        "★ Hot zone → Converge:  boids route toward point → structural ribs / force-lines aimed at thermal stress zones",
    ]

    def _update_attr_mode_ui(self, idx):
        is_slow = (idx == 0)   # SlowField is index 0
        self.lbl_slow_speed.Visible = is_slow
        self.txt_slow_speed.Visible = is_slow
        # V3: update climate hint label
        hints = self._MODE_HINTS
        self.lbl_mode_hint.Text = hints[min(idx, len(hints)-1)]

    # ── Event handlers ────────────────────────────────────
    def OnVoidModeChanged(self, s, e):
        self._update_void_ui(self.dd_void.SelectedIndex)

    def OnAttrModeChanged(self, s, e):
        self._update_attr_mode_ui(self.dd_attr_mode.SelectedIndex)

    def OnShowTailsChanged(self, s, e):
        self.conduit.show_tails = bool(self.chk_show_tails.Checked)
        sc.doc.Views.Redraw()

    def OnColorModeChanged(self, s, e):
        self.conduit.color_mode = self.dd_color_mode.SelectedIndex
        sc.doc.Views.Redraw()

    def OnThemeChanged(self, s, e):
        self.conduit.theme_idx = self.dd_theme.SelectedIndex
        sc.doc.Views.Redraw()

    def OnVoidInput(self, s, e):
        mode = self.dd_void.SelectedIndex
        if mode == 0:   # A: Brep
            self.lbl_status.Text = "Status: Select void container(s)..."
            oids = rs.GetObjects("Select void container geometry (multiple allowed)", 0)
            if oids:
                self.void_breps = []
                for oid in oids:
                    obj = sc.doc.Objects.Find(oid)
                    if not obj: continue
                    brep = self._try_get_brep(obj.Geometry)
                    if brep: self.void_breps.append(brep)
                if self.void_breps:
                    self.void_brep = self.void_breps[0]
                    n_closed = sum(1 for b in self.void_breps if b.IsSolid)
                    self.lbl_void_status.Text = (
                        f"Void: {len(self.void_breps)} brep(s)  ({n_closed} closed)")
                    self.lbl_void_status.TextColor = drawing.Colors.Green
                else:
                    self.lbl_void_status.Text = "Could not read geometry"
                    self.lbl_void_status.TextColor = drawing.Colors.Red
        elif mode == 1:  # B: BBox
            self.lbl_void_status.Text = (
                "Mode B: use '1. Select Container Box' then '2. Select Mass to Exclude'")
            self.lbl_void_status.TextColor = drawing.Color.FromArgb(255, 200, 0)
        elif mode == 2:  # D: Surface
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
                    merged = Rhino.Geometry.Mesh()
                    for m in meshes: merged.Append(m)
                    merged.Normals.ComputeNormals(); merged.Compact()
                    self.surface_mesh = merged
                    # Precompute face-centre average — used as interior pull target
                    fc = merged.Faces.Count
                    if fc > 0:
                        sx = sy = sz = 0.0
                        for fi in range(fc):
                            c = merged.Faces.GetFaceCenter(fi)
                            sx += c.X; sy += c.Y; sz += c.Z
                        self.surface_centroid = Rhino.Geometry.Point3d(sx/fc, sy/fc, sz/fc)
                    else:
                        self.surface_centroid = None
                    self.lbl_void_status.Text = (
                        f"Surface: {len(meshes)} object(s) — "
                        f"{merged.Vertices.Count} verts, {merged.Faces.Count} faces")
                    self.lbl_void_status.TextColor = drawing.Colors.Green
                else:
                    self.lbl_void_status.Text = "Mesh conversion failed"
                    self.lbl_void_status.TextColor = drawing.Colors.Red

    def OnPickBBoxContainer(self, s, e):
        self.lbl_status.Text = "Status: Pick container box..."
        oid = rs.GetObject("Select container box / brep for outer simulation boundary", 0)
        if not oid: return
        obj = sc.doc.Objects.Find(oid)
        if not obj: return
        bb = obj.Geometry.GetBoundingBox(True)
        if not bb.IsValid:
            self.lbl_void_status.Text = "Container: invalid bbox"
            self.lbl_void_status.TextColor = drawing.Colors.Red; return
        self.void_bbox = bb
        w = bb.Max.X - bb.Min.X; d_ = bb.Max.Y - bb.Min.Y; h = bb.Max.Z - bb.Min.Z
        self.lbl_bbox_container.Text      = f"✓ container  {w:.1f} × {d_:.1f} × {h:.1f}"
        self.lbl_bbox_container.TextColor = drawing.Color.FromArgb(0, 210, 80)
        self.lbl_void_status.Text         = "Container set"
        self.lbl_void_status.TextColor    = drawing.Colors.Green

    def OnPickBBoxMass(self, s, e):
        self.lbl_status.Text = "Status: Select masses to exclude..."
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
        self.lbl_void_status.Text = (
            f"Masses: {len(self.mass_bboxes)} bbox(s), {len(self.mass_breps)} brep(s)")
        self.lbl_void_status.TextColor = drawing.Colors.Green

    # ── Attractor helpers ─────────────────────────────────
    def _read_attr_params(self):
        try: strength   = float(self.txt_attr_strength.Text)
        except: strength = 1.0
        try: radius     = float(self.txt_attr_radius.Text)
        except: radius   = 5.0
        try: decay      = float(self.txt_attr_decay.Text)
        except: decay    = 0.0
        try: slow_speed = float(self.txt_slow_speed.Text)
        except: slow_speed = 0.3
        modes = ["SlowField", "Orbit", "Repulse", "Converge"]
        mode  = modes[min(self.dd_attr_mode.SelectedIndex, len(modes)-1)]
        return strength, radius, decay, mode, slow_speed

    def OnAddAttractors(self, s, e):
        """Loop rs.GetPoint() — reliable in Eto context. Esc exits the loop."""
        strength, radius, decay, mode, slow_speed = self._read_attr_params()
        added = 0
        while True:
            self.lbl_status.Text = (
                f"Status: Click to place {mode} attractor {added+1}  (Esc to stop)")
            pt = rs.GetPoint(
                f"Place {mode} attractor {added+1}  (Esc to stop)")
            if pt is None:
                break
            self.attractors.append(
                Attractor(pt, strength, radius, decay, mode, slow_speed))
            added += 1
            n = len(self.attractors)
            self.lbl_attractors.Text = f"{n} attractor{'s' if n != 1 else ''}"
            sc.doc.Views.Redraw()
        self.lbl_status.Text = (
            f"Status: {added} {mode} attractor(s) added  "
            f"({len(self.attractors)} total)")

    def OnAddAttractorsFromObjects(self, s, e):
        """Pick any Rhino objects as attractors — uses bbox centre as position.
        Accepts points, voxel boxes, breps, meshes — anything from climate data.
        Mode is read from dd_attr_mode (set it BEFORE picking)."""
        strength, radius, decay, mode, slow_speed = self._read_attr_params()
        self.lbl_status.Text = (
            f"Status: Select objects for [{mode}] attractors  "
            f"(any geometry — voxels, points, breps, meshes)...")
        # filter=0 → accept all selectable geometry types
        oids = rs.GetObjects(
            f"Select objects as [{mode}] attractors  "
            f"(tip: window-select hot voxels from climate data)", 0)
        if not oids:
            self.lbl_status.Text = "Status: No objects selected"; return
        added = 0
        for oid in oids:
            obj = sc.doc.Objects.Find(oid)
            if not obj: continue
            geo = obj.Geometry
            # Point objects: use exact location
            if isinstance(geo, Rhino.Geometry.Point):
                pt = geo.Location
            # All other geometry: use bounding box centre
            elif hasattr(geo, 'GetBoundingBox'):
                try:
                    bb = geo.GetBoundingBox(True)
                    pt = bb.Center if bb.IsValid else None
                except:
                    pt = None
            else:
                continue
            if pt is None: continue
            self.attractors.append(
                Attractor(pt, strength, radius, decay, mode, slow_speed))
            added += 1
        n = len(self.attractors)
        self.lbl_attractors.Text = f"{n} attractor{'s' if n != 1 else ''}"
        self.lbl_status.Text = (
            f"Status: {added} [{mode}] attractor(s) added from objects  "
            f"({n} total)  — radius {radius:.1f}  strength {strength:.1f}")
        sc.doc.Views.Redraw()

    def OnAddSingleAttractor(self, s, e):
        pt = rs.GetPoint("Pick attractor centre")
        if not pt: return
        strength, radius, decay, mode, slow_speed = self._read_attr_params()
        self.attractors.append(Attractor(pt, strength, radius, decay, mode, slow_speed))
        n = len(self.attractors)
        self.lbl_attractors.Text = f"{n} attractor{'s' if n != 1 else ''}"
        self.lbl_status.Text = f"Status: {mode} attractor added  ({n} total)"
        sc.doc.Views.Redraw()

    def OnClearAttractors(self, s, e):
        self.attractors.clear()
        self.lbl_attractors.Text = "0 attractors"
        sc.doc.Views.Redraw()

    def OnApplyPreset(self, s, e):
        idx = self.dd_preset.SelectedIndex
        if idx == 0 or idx >= len(PRESETS):
            self.lbl_preset_hint.Text = "Custom — no changes made."; return
        p = PRESETS[idx]
        vm = p["void_mode"]
        self.dd_void.SelectedIndex = vm; self._update_void_ui(vm)
        self.txt_n_boids.Text      = p["n_boids"]
        self.txt_steps.Text        = p["steps"]
        self.txt_nbr_radius.Text   = p["neighbor_radius"]
        self.txt_sep_dist.Text     = p["separation_dist"]
        self.txt_sep_w.Text        = p["sep_w"]
        self.txt_ali_w.Text        = p["ali_w"]
        self.txt_coh_w.Text        = p["coh_w"]
        self.txt_max_speed.Text    = p["max_speed"]
        self.txt_max_force.Text    = p["max_force"]
        self.txt_jitter.Text       = p["jitter"]
        self.txt_seed.Text         = p["seed"]
        self.txt_attr_weight.Text  = p["attr_weight"]
        self.txt_wind_weight.Text  = p["wind_weight"]
        self.lbl_preset_hint.Text  = f"Preset '{p['name']}' applied.  {p['hint']}"
        self.lbl_status.Text       = f"Status: Preset '{p['name']}' applied"

    # ── Behavior style quick-fill ─────────────────────────
    def OnStyleFlock(self, s, e):
        """Classic Flock weights — organic cohesion-driven flocking."""
        self.txt_nbr_radius.Text  = "5.0"
        self.txt_sep_dist.Text    = "1.8"
        self.txt_sep_w.Text       = "2.0"
        self.txt_ali_w.Text       = "1.0"
        self.txt_coh_w.Text       = "1.0"
        self.txt_max_speed.Text   = "1.5"
        self.txt_max_force.Text   = "0.15"
        self.txt_wind_weight.Text = "0.0"
        self.txt_attr_weight.Text = "0.5"
        self.lbl_status.Text = (
            "Status: ⬡ Classic Flock weights applied — "
            "organic cohesion. Add Converge attractors to route trails.")

    def OnStyleWrap(self, s, e):
        """Facade Wrap weights — parallel flow lines on surface."""
        self.txt_nbr_radius.Text = "7.0"
        self.txt_sep_dist.Text   = "3.0"
        self.txt_sep_w.Text      = "2.5"
        self.txt_ali_w.Text      = "2.0"
        self.txt_coh_w.Text      = "0.1"
        self.txt_max_speed.Text  = "0.8"
        self.txt_max_force.Text  = "0.18"
        self.txt_wind_weight.Text = "0.6"
        self.txt_attr_weight.Text = "0.4"
        self.lbl_status.Text = (
            "Status: ≋ Facade Wrap weights applied — "
            "set Wind X/Y/Z direction, then add SlowField attractors at light zones.")

    # ── Spawn helpers ─────────────────────────────────────
    def _get_spawn_point(self, void_mode,
                         offset_mode=0, offset_inner=0.0, offset_outer=5.0):
        for _ in range(60):
            if void_mode == 0 and (self.void_breps or self.void_brep):
                active = self.void_breps if self.void_breps else [self.void_brep]
                b  = random.choice(active)
                bb = b.GetBoundingBox(True)
                pt = Rhino.Geometry.Point3d(
                    random.uniform(bb.Min.X, bb.Max.X),
                    random.uniform(bb.Min.Y, bb.Max.Y),
                    random.uniform(bb.Min.Z, bb.Max.Z))
                tol = sc.doc.ModelAbsoluteTolerance
                if any(br.IsPointInside(pt, tol, False) for br in active):
                    return pt
            elif void_mode == 1 and self.void_bbox:
                bb = self.void_bbox
                pt = Rhino.Geometry.Point3d(
                    random.uniform(bb.Min.X, bb.Max.X),
                    random.uniform(bb.Min.Y, bb.Max.Y),
                    random.uniform(bb.Min.Z, bb.Max.Z))
                if not any(mbb.Contains(pt) for mbb in self.mass_bboxes):
                    return pt
                return bb.Center
            elif void_mode == 2 and self.surface_mesh and self.surface_mesh.Vertices.Count > 0:
                v_idx = random.randint(0, self.surface_mesh.Vertices.Count - 1)
                pt    = Rhino.Geometry.Point3d(self.surface_mesh.Vertices[v_idx])
                if offset_mode > 0:
                    # Spawn at the offset distance above the surface vertex
                    mp = self.surface_mesh.ClosestMeshPoint(pt, 0.0)
                    if mp is not None:
                        nrm = self.surface_mesh.NormalAt(mp)
                        if nrm is not None and nrm.Length > 0.0001:
                            nrm.Unitize()
                            off = (random.uniform(offset_inner, offset_outer)
                                   if offset_mode == 3          # Variable Layer
                                   else (offset_inner + offset_outer) * 0.5)
                            pt = pt + nrm * off
                return pt
            else:
                return Rhino.Geometry.Point3d(
                    random.uniform(-5, 5), random.uniform(-5, 5), random.uniform(-5, 5))
        # Fallback
        if void_mode == 0 and self.void_brep:
            return self.void_brep.GetBoundingBox(True).Center
        if void_mode == 1 and self.void_bbox:
            return self.void_bbox.Center
        if void_mode == 2 and self.surface_mesh and self.surface_mesh.Vertices.Count > 0:
            pt = Rhino.Geometry.Point3d(self.surface_mesh.Vertices[0])
            if offset_mode > 0:
                mp = self.surface_mesh.ClosestMeshPoint(pt, 0.0)
                if mp is not None:
                    nrm = self.surface_mesh.NormalAt(mp)
                    if nrm is not None and nrm.Length > 0.0001:
                        nrm.Unitize()
                        pt = pt + nrm * ((offset_inner + offset_outer) * 0.5)
            return pt
        return Rhino.Geometry.Point3d(0, 0, 0)

    # ── Run / Stop ────────────────────────────────────────
    def OnStartClick(self, s, e):
        if self.is_running: return

        # ── Validate void geometry before spawning ──────
        void_mode = self.dd_void.SelectedIndex
        if void_mode == 0 and not self.void_breps and not self.void_brep:
            self.lbl_status.Text = (
                "Status: ⚠  Mode A — no Brep selected! "
                "Click 'Select Void Brep' first, or switch mode.")
            self.lbl_void_status.TextColor = drawing.Color.FromArgb(255, 200, 0)
            return
        if void_mode == 1 and self.void_bbox is None:
            self.lbl_status.Text = (
                "Status: ⚠  Mode B — no container box! "
                "Click '1. Select Container Box' first.")
            self.lbl_void_status.TextColor = drawing.Color.FromArgb(255, 200, 0)
            return
        if void_mode == 2 and self.surface_mesh is None:
            self.lbl_status.Text = (
                "Status: ⚠  Mode D — no surface selected! "
                "Click 'Select Surface Geometry' first.")
            self.lbl_void_status.TextColor = drawing.Color.FromArgb(255, 200, 0)
            return

        try: n_boids   = int(self.txt_n_boids.Text)
        except: n_boids = 40
        try: lifetime  = int(self.txt_steps.Text)
        except: lifetime = 200
        try: seed_val  = int(self.txt_seed.Text)
        except: seed_val = 0
        try: tail_len  = int(self.txt_tail_length.Text)
        except: tail_len = 30
        try: max_speed = float(self.txt_max_speed.Text)
        except: max_speed = 0.8

        # ── V2: read offset params ──────────────────────────
        offset_mode  = self.dd_offset_mode.SelectedIndex
        try: offset_inner = float(self.txt_offset_inner.Text)
        except: offset_inner = 0.0
        try: offset_outer = float(self.txt_offset_outer.Text)
        except: offset_outer = 5.0
        try: spring_k = float(self.txt_spring_k.Text)
        except: spring_k = 0.3
        # clamp
        offset_inner = max(0.0, offset_inner)
        offset_outer = max(offset_inner + 0.1, offset_outer)
        # Only apply offset in Surface mode
        if void_mode != 2: offset_mode = 0

        if offset_mode > 0:
            mode_names = ["", "Offset Shell", "Soft Attract", "Variable Layer"]
            self.lbl_offset_status.Text = (
                f"3D Offset: {mode_names[offset_mode]}  "
                f"[{offset_inner:.1f} → {offset_outer:.1f}]")
            self.lbl_offset_status.TextColor = drawing.Color.FromArgb(0, 220, 180)

        random.seed(seed_val if seed_val > 0 else None)

        self.boids.clear()
        for _ in range(n_boids):
            pos = self._get_spawn_point(void_mode, offset_mode, offset_inner, offset_outer)
            b   = Boid(pos, lifetime=lifetime)
            # Variable Layer: assign random target offset per boid
            if offset_mode == 3:
                b.target_offset = random.uniform(offset_inner, offset_outer)
            else:
                b.target_offset = (offset_inner + offset_outer) * 0.5
            self.boids.append(b)

        self.conduit.boids      = self.boids
        self.conduit.attractors = self.attractors
        self.conduit.show_tails = bool(self.chk_show_tails.Checked)
        self.conduit.tail_length = tail_len
        self.conduit.max_speed  = max_speed
        self.conduit.color_mode = self.dd_color_mode.SelectedIndex
        self.conduit.theme_idx  = self.dd_theme.SelectedIndex
        self.conduit.Enabled    = True
        self.is_running         = True
        self.lbl_status.Text    = "Status: Simulating..."
        self.RunSimulation()

    def OnStopClick(self, s, e):
        self.is_running = False
        self.lbl_status.Text = "Status: Stopped"

    # ── Simulation loop ───────────────────────────────────
    def RunSimulation(self):
        def _f(txt, default):
            try: return float(txt.Text)
            except: return default

        nbr_r     = _f(self.txt_nbr_radius,  5.0)
        sep_dist  = _f(self.txt_sep_dist,    2.0)
        sep_w     = _f(self.txt_sep_w,       1.5)
        ali_w     = _f(self.txt_ali_w,       1.0)
        coh_w     = _f(self.txt_coh_w,       0.8)
        max_speed = _f(self.txt_max_speed,   0.8)
        max_force = _f(self.txt_max_force,   0.15)
        jitter    = _f(self.txt_jitter,      0.05)
        attr_w    = _f(self.txt_attr_weight, 0.6)
        wind_w    = _f(self.txt_wind_weight, 0.0)
        void_mode    = self.dd_void.SelectedIndex
        # V2: offset params (fixed for the run — not live tweakable)
        off_mode  = self.dd_offset_mode.SelectedIndex if void_mode == 2 else 0
        try: off_inner = float(self.txt_offset_inner.Text)
        except: off_inner = 0.0
        try: off_outer = float(self.txt_offset_outer.Text)
        except: off_outer = 5.0
        try: sp_k = float(self.txt_spring_k.Text)
        except: sp_k = 0.3
        off_inner = max(0.0, off_inner)
        off_outer = max(off_inner + 0.1, off_outer)

        # Build wind vector once (re-read each step for live tweaking)
        def _wind_vec():
            if wind_w <= 0: return None
            try:
                wv = Rhino.Geometry.Vector3d(
                    float(self.txt_wx.Text),
                    float(self.txt_wy.Text),
                    float(self.txt_wz.Text))
                if wv.Length > 0.0001:
                    wv.Unitize(); return wv
            except: pass
            return None

        max_steps = max((b.lifetime for b in self.boids), default=200)
        step = 0

        while self.is_running and step < max_steps:
            # Allow live parameter tweaking
            nbr_r     = _f(self.txt_nbr_radius,  nbr_r)
            sep_dist  = _f(self.txt_sep_dist,    sep_dist)
            sep_w     = _f(self.txt_sep_w,       sep_w)
            ali_w     = _f(self.txt_ali_w,       ali_w)
            coh_w     = _f(self.txt_coh_w,       coh_w)
            max_speed = _f(self.txt_max_speed,   max_speed)
            max_force = _f(self.txt_max_force,   max_force)
            jitter    = _f(self.txt_jitter,      jitter)
            attr_w    = _f(self.txt_attr_weight, attr_w)
            wind_w    = _f(self.txt_wind_weight, wind_w)
            self.conduit.max_speed = max_speed

            wv = _wind_vec()
            alive = [b for b in self.boids if b.alive]
            if not alive: break

            # Global flock centroid — used as fallback cohesion for lone boids
            n_alive = len(alive)
            cx = sum(b.pos.X for b in alive) / n_alive
            cy = sum(b.pos.Y for b in alive) / n_alive
            cz = sum(b.pos.Z for b in alive) / n_alive
            flock_centroid = Rhino.Geometry.Point3d(cx, cy, cz)

            for boid in alive:
                neighbors = [
                    b for b in alive
                    if b is not boid and boid.pos.DistanceTo(b.pos) < nbr_r
                ]
                boid.update(
                    neighbors,
                    sep_dist, sep_w, ali_w, coh_w,
                    max_speed, max_force, jitter,
                    void_mode,
                    self.void_brep, self.void_breps,
                    self.void_bbox,
                    self.mass_breps, self.mass_bboxes,
                    self.surface_mesh,
                    self.attractors, attr_w,
                    wv, wind_w,
                    flock_centroid=flock_centroid,
                    # V2 offset params
                    offset_mode=off_mode,
                    offset_inner=off_inner,
                    offset_outer=off_outer,
                    spring_k=sp_k,
                    # V3 interior pull
                    surface_centroid=self.surface_centroid,
                )

            for a in self.attractors: a.update()

            alive_c = sum(1 for b in self.boids if b.alive)
            self.lbl_boid_count.Text = f"Boids: {alive_c}/{len(self.boids)} alive"
            sc.doc.Views.Redraw()
            Rhino.RhinoApp.Wait()
            step += 1

        self.is_running = False
        self.lbl_status.Text = (
            f"Status: Complete — {len(self.boids)} boids, {step} steps")

        if bool(self.chk_bake_tails.Checked):
            self._do_bake_trails()

    # ── Trail baking ──────────────────────────────────────
    def OnBakeTrails(self, s, e):
        self._do_bake_trails()

    def _do_bake_trails(self):
        if not self.boids:
            self.lbl_status.Text = "Status: No boids — run simulation first"; return
        layer_idx = _ensure_layer("Boids::Trails", sd.Color.FromArgb(0xCD, 0x29, 0x90))
        attr      = Rhino.DocObjects.ObjectAttributes()
        attr.LayerIndex = layer_idx
        count = 0
        for boid in self.boids:
            if len(boid.history) < 4: continue
            crv = Rhino.Geometry.Curve.CreateInterpolatedCurve(boid.history, 3)
            if crv is not None:
                oid = sc.doc.Objects.AddCurve(crv, attr)
                if oid != System.Guid.Empty:
                    self.trail_ids.append(oid); count += 1
        sc.doc.Views.Redraw()
        self.lbl_status.Text = (
            f"Status: {count} trail curves baked → Boids::Trails")

    # ── Module & Aggregation ──────────────────────────────
    def OnCreateX(self, s, e):
        t, L = 0.08, 0.4
        breps = []
        for dims in [
            ((-L, L), (-t, t), (-t, t)),
            ((-t, t), (-L, L), (-t, t)),
            ((-t, t), (-t, t), (-L, L)),
        ]:
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
            self.base_geo_id  = oid
            self.lbl_m1.Text      = "M1: ✓ X module created"
            self.lbl_m1.TextColor = drawing.Color.FromArgb(0, 210, 80)
            self.lbl_status.Text = "Status: 3D X module created → assigned to M1"
            sc.doc.Views.Redraw()

    def _select_module(self, slot):
        """Shared helper — pick geometry and assign to M1/M2/M3."""
        oid = rs.GetObject(f"Select geometry for Module {slot}", 0)
        if not oid: return
        GRN = drawing.Color.FromArgb(0, 210, 80)
        if slot == 1:
            self.base_geo_id  = oid
            self.lbl_m1.Text      = "M1: ✓ assigned"
            self.lbl_m1.TextColor = GRN
        elif slot == 2:
            self.base_geo_id_2 = oid
            self.lbl_m2.Text      = "M2: ✓ assigned"
            self.lbl_m2.TextColor = GRN
        else:
            self.base_geo_id_3 = oid
            self.lbl_m3.Text      = "M3: ✓ assigned"
            self.lbl_m3.TextColor = GRN
        self.lbl_status.Text = f"Status: Module {slot} assigned"

    def OnSelectM1(self, s, e): self._select_module(1)
    def OnSelectM2(self, s, e): self._select_module(2)
    def OnSelectM3(self, s, e): self._select_module(3)

    def OnAdaptiveToggle(self, s, e):
        is_adaptive = bool(self.chk_adaptive.Checked)
        self.txt_spacing.Enabled = not is_adaptive
        if is_adaptive and self.base_geo_id:
            # V3: Repeat mode → use module axis length; Fit mode → use max bbox extent
            scale_mode = 'Repeat' if self.dd_scale_mode.SelectedIndex == 1 else 'Fit'
            if scale_mode == 'Repeat':
                gid1, rs1, re1, _ = self._get_module_info(1)
                if rs1 and re1:
                    step = rs1.DistanceTo(re1)
                    if step > 0.001:
                        self.txt_spacing.Text = f"{step:.4f}"
                        self.lbl_status.Text  = (
                            f"Status: Adaptive spacing (Repeat) = {step:.4f}  "
                            f"(module natural axis length)")
            else:
                obj = sc.doc.Objects.Find(self.base_geo_id)
                if obj:
                    bb   = obj.Geometry.GetBoundingBox(True)
                    step = max(bb.Max.X-bb.Min.X, bb.Max.Y-bb.Min.Y, bb.Max.Z-bb.Min.Z)
                    if step > 0.001:
                        self.txt_spacing.Text = f"{step:.4f}"
                        self.lbl_status.Text  = (
                            f"Status: Adaptive spacing (Fit) = {step:.4f}")

    # ── V3 Aggregation helpers ────────────────────────────
    def _get_module_info(self, slot):
        """Return (gid, ref_s, ref_e, cross_size) for slot 1/2/3.
        ref_s/e: primary-axis endpoints on the geometry bbox (for _build_orient_xform).
        cross_size: perpendicular dimension (for radial scale reference).
        Falls back to M1 if slot not assigned.
        Manual axis: uses self.man_ref_start/end when chk_manual_axis is checked."""
        gid = (self.base_geo_id   if slot == 1 else
               self.base_geo_id_2 if slot == 2 else
               self.base_geo_id_3)
        if not gid:
            gid = self.base_geo_id          # fallback to M1
        if not gid: return None, None, None, None
        obj = sc.doc.Objects.Find(gid)
        if not obj: return None, None, None, None
        geo = obj.Geometry
        # Manual axis override
        if (self.chk_manual_axis.Checked and
                self.man_ref_start is not None and self.man_ref_end is not None):
            ref_s, ref_e = self.man_ref_start, self.man_ref_end
        else:
            ref_s, ref_e = _auto_ref_pts(geo)
        if ref_s is None:
            return gid, None, None, 1.0
        cross = _cross_section_size(geo, ref_s, ref_e)
        return gid, ref_s, ref_e, cross

    def _place(self, gid, seg_start, seg_end, attr, ref_s, ref_e,
               radial_scale=1.0, scale_mode='Fit'):
        """Place one instance of module geometry aligned to a trail segment.

        Uses _build_orient_xform (SCA V4 ported):
          - Rotates module so its primary axis aligns to seg direction
          - Scales: axial=scale_factor (Fit=stretch, Repeat=1.0), radial=radial_scale
          - Translates: module ref_s → seg_start

        gid         : GUID of source geometry (duplicated for each placement)
        seg_start   : curve point at this placement sample
        seg_end     : seg_start + tangent * spacing (defines segment direction + length)
        ref_s/ref_e : module's primary-axis endpoints (from _get_module_info)
        radial_scale: cross-section multiplier (Module Scale UI field)
        scale_mode  : 'Fit' (stretch axially) or 'Repeat' (natural size, scale_factor=1)
        """
        if ref_s is None or ref_e is None: return None
        ref_len = ref_s.DistanceTo(ref_e)
        seg_len = seg_start.DistanceTo(seg_end)
        if ref_len < 1e-10 or seg_len < 1e-10: return None
        scale_factor = (seg_len / ref_len) if scale_mode == 'Fit' else 1.0
        geo = _duplicate_geo(gid)
        if geo is None: return None
        try:
            xf  = _build_orient_xform(seg_start, seg_end, ref_s, ref_e,
                                      scale_factor, radial_scale)
            geo.Transform(xf)
            oid = _add_geo(geo, attr)
            return oid if oid != System.Guid.Empty else None
        except:
            return None

    def _boid_speeds(self, boid):
        """Per-step speed list (distance between consecutive history points)."""
        h = boid.history
        if len(h) < 2: return [0.0]
        return [h[i].DistanceTo(h[i-1]) for i in range(1, len(h))]

    def OnPickCurves(self, s, e):
        """Pick multiple existing curves from the doc for aggregation."""
        oids = rs.GetObjects("Select curves to aggregate on",
                             filter=rs.filter.curve, preselect=True)
        if not oids:
            return
        self.picked_curve_ids = list(oids)
        n = len(self.picked_curve_ids)
        self.lbl_picked.Text      = f"✓ {n} curve{'s' if n != 1 else ''} picked — ready for aggregation"
        self.lbl_picked.TextColor = drawing.Color.FromArgb(0, 210, 80)
        self.lbl_status.Text      = f"Status: {n} curve(s) picked for aggregation"

    def OnAggregate(self, s, e):
        self.is_running = False
        if not self.base_geo_id:
            self.lbl_status.Text = "Status: Assign at least M1 first"; return
        # ── Resolve curve source: live boids OR picked curves ─
        use_boids  = self.boids and any(len(b.history) >= 4 for b in self.boids)
        use_picked = bool(self.picked_curve_ids)
        if not use_boids and not use_picked:
            self.lbl_status.Text = (
                "Status: No trails — run simulation or pick existing curves first"); return

        # ── Helper ────────────────────────────────────────
        def _f(t, d):
            try: return float(t.Text)
            except: return d

        # ── V3: read precision controls ───────────────────
        scale_mode  = 'Repeat' if self.dd_scale_mode.SelectedIndex == 1 else 'Fit'
        mod_scale   = max(0.001, _f(self.txt_mod_scale,    1.0))
        mod_gap     = max(0.0,   _f(self.txt_mod_gap,      0.0))
        try: agg_seed = int(self.txt_agg_seed.Text)
        except: agg_seed = 42
        if agg_seed > 0: random.seed(agg_seed)

        # ── Pre-compute module info (gid, ref_s, ref_e, cross) per slot ──
        gid1, rs1, re1, cx1 = self._get_module_info(1)
        gid2, rs2, re2, cx2 = self._get_module_info(2)
        gid3, rs3, re3, cx3 = self._get_module_info(3)

        # ── Spacing ───────────────────────────────────────
        try: spacing = max(0.05, float(self.txt_spacing.Text))
        except: spacing = 1.5
        if bool(self.chk_adaptive.Checked):
            if scale_mode == 'Repeat' and rs1 and re1:
                spacing = max(rs1.DistanceTo(re1), 0.05)
            elif gid1:
                obj1 = sc.doc.Objects.Find(gid1)
                if obj1:
                    bb1  = obj1.Geometry.GetBoundingBox(True)
                    spacing = max(bb1.Max.X-bb1.Min.X,
                                  bb1.Max.Y-bb1.Min.Y,
                                  bb1.Max.Z-bb1.Min.Z, 0.05)

        # ── Read logic thresholds ──────────────────────────
        sp_t1 = _f(self.txt_speed_t1, 0.4);  sp_t2 = _f(self.txt_speed_t2, 0.7)
        cu_t1 = _f(self.txt_curv_t1,  0.4);  cu_t2 = _f(self.txt_curv_t2,  0.7)
        de_r  = _f(self.txt_density_r, 3.0)
        de_t1 = _f(self.txt_dens_t1,  0.4);  de_t2 = _f(self.txt_dens_t2,  0.7)
        lo1   = _f(self.txt_layer_off1, 1.0); lo2  = _f(self.txt_layer_off2, 2.0)
        logic = self.dd_agg_logic.SelectedIndex  # 0–4

        # ── 3 module layers ────────────────────────────────
        def _ma(slot):
            colors = {
                1: sd.Color.FromArgb(100,   0, 200),
                2: sd.Color.FromArgb(  0, 170, 255),
                3: sd.Color.FromArgb(190, 235, 255),
            }
            li = _ensure_layer(f"Boids::Modules::M{slot}", colors[slot])
            a  = Rhino.DocObjects.ObjectAttributes()
            a.LayerIndex = li
            return a
        attr1 = _ma(1); attr2 = _ma(2); attr3 = _ma(3)
        _slot_attr = {1: attr1, 2: attr2, 3: attr3}
        _slot_info = {
            1: (gid1, rs1, re1),
            2: (gid2, rs2, re2),
            3: (gid3, rs3, re3),
        }
        self.aggregated_ids = []
        count = 0

        # ── Build (curve, boid_or_None) list ──────────────
        crv_pairs = []
        if use_boids:
            for b in self.boids:
                if len(b.history) < 4: continue
                c = Rhino.Geometry.Curve.CreateInterpolatedCurve(b.history, 3)
                if c: crv_pairs.append((c, b))
        else:
            for gid in self.picked_curve_ids:
                obj = sc.doc.Objects.Find(gid)
                if obj and isinstance(obj.Geometry, Rhino.Geometry.Curve):
                    crv_pairs.append((obj.Geometry, None))

        if not crv_pairs:
            self.lbl_status.Text = "Status: No valid curves found"; return

        # ── Pre-compute density field (mode 3) ─────────────
        all_hist_pts = []
        if logic == 3:
            if use_boids:
                for b in self.boids: all_hist_pts.extend(b.history)
            else:
                for c, _ in crv_pairs:
                    pts = c.DivideByLength(spacing * 0.5, True)
                    if pts:
                        all_hist_pts.extend([c.PointAt(t) for t in pts])

        self.lbl_status.Text = "Status: Aggregating..."; Rhino.RhinoApp.Wait()

        # ── Main modular placement loop ────────────────────
        for crv, boid in crv_pairs:
            crv_len = crv.GetLength()
            if crv_len < 0.001: continue

            # ── V3: Apply module gap — trim curve ends ─────
            crv_to_div = crv
            if mod_gap > 0 and crv_len > 2 * mod_gap + 0.001:
                ok_s, t_s = crv.LengthParameter(mod_gap)
                ok_e, t_e = crv.LengthParameter(crv_len - mod_gap)
                if ok_s and ok_e:
                    sub = crv.Trim(t_s, t_e)
                    if sub: crv_to_div = sub

            # ── Divide by spacing (Fit) or by ref_len (Repeat) ─
            div_spacing = spacing
            if scale_mode == 'Repeat' and rs1 and re1:
                # In Repeat mode, tile modules at their natural axis length
                ref_len_m1 = rs1.DistanceTo(re1)
                if ref_len_m1 > 0.001:
                    div_spacing = ref_len_m1

            params = crv_to_div.DivideByLength(div_spacing, True)
            if not params: continue
            n_params = len(params)

            # ── Per-curve prep for Speed-Based (logic 1) ───
            if logic == 1:
                if boid is not None:
                    speeds = self._boid_speeds(boid)
                else:
                    pts    = [crv_to_div.PointAt(t) for t in params]
                    speeds = [pts[i].DistanceTo(pts[i-1]) for i in range(1, len(pts))] or [1.0]
                sp_max = max(speeds) if speeds else 1.0
            else:
                speeds = []; sp_max = 1.0

            # ── Per-curve curvature values (logic 2) ───────
            curv_vals = []
            if logic == 2:
                for tp in params:
                    cv = crv_to_div.CurvatureAt(tp)
                    curv_vals.append(cv.Length if cv is not None else 0.0)
                cv_max = max(curv_vals) if curv_vals else 1.0
                if cv_max < 0.0001: cv_max = 1.0

            for idx, tp in enumerate(params):
                # ── V3: compute seg_start, seg_end from tangent ─
                seg_start = crv_to_div.PointAt(tp)
                tang      = crv_to_div.TangentAt(tp)
                if tang is None or tang.Length < 1e-8: continue
                tang.Unitize()
                seg_end   = Rhino.Geometry.Point3d(
                    seg_start.X + tang.X * div_spacing,
                    seg_start.Y + tang.Y * div_spacing,
                    seg_start.Z + tang.Z * div_spacing)

                # ── Select slot by logic ────────────────────
                slot = 1

                if logic == 0:
                    t    = idx / max(n_params - 1, 1)
                    slot = 1 if t < 0.3 else (3 if t > 0.7 else 2)

                elif logic == 1:
                    domain_len = crv_to_div.Domain.Length
                    hi = min(int((tp - crv_to_div.Domain.Min) / domain_len * len(speeds)),
                             len(speeds) - 1)
                    ns = speeds[max(hi, 0)] / sp_max
                    slot = 1 if ns < sp_t1 else (3 if ns > sp_t2 else 2)

                elif logic == 2:
                    nc   = curv_vals[idx] / cv_max if idx < len(curv_vals) else 0
                    slot = 1 if nc > cu_t2 else (3 if nc < cu_t1 else 2)

                elif logic == 3:
                    pt   = seg_start
                    cnt  = sum(1 for p in all_hist_pts if pt.DistanceTo(p) < de_r)
                    nd   = min(cnt / max(len(all_hist_pts) * 0.05, 1), 1.0)
                    slot = 1 if nd > de_t2 else (3 if nd < de_t1 else 2)

                # ── V3: Place with axis-aware _place ────────
                if logic == 4:
                    # Layer Stack (Snøhetta) — all 3 at each point, offset along curve normal
                    ok, frame = crv_to_div.FrameAt(tp)
                    nrm = frame.ZAxis if ok else Rhino.Geometry.Vector3d.ZAxis
                    for sl, offset in ((1, 0.0), (2, lo1), (3, lo2)):
                        gid_sl, ref_s_sl, ref_e_sl = _slot_info[sl]
                        if not gid_sl or not ref_s_sl: continue
                        off_v = Rhino.Geometry.Vector3d(nrm) * offset
                        ss = Rhino.Geometry.Point3d(
                            seg_start.X + off_v.X,
                            seg_start.Y + off_v.Y,
                            seg_start.Z + off_v.Z)
                        se = Rhino.Geometry.Point3d(
                            seg_end.X + off_v.X,
                            seg_end.Y + off_v.Y,
                            seg_end.Z + off_v.Z)
                        oid = self._place(gid_sl, ss, se, _slot_attr[sl],
                                          ref_s_sl, ref_e_sl, mod_scale, scale_mode)
                        if oid:
                            self.aggregated_ids.append(oid); count += 1
                else:
                    gid_sl, ref_s_sl, ref_e_sl = _slot_info[slot]
                    if not gid_sl or not ref_s_sl: continue
                    oid = self._place(gid_sl, seg_start, seg_end, _slot_attr[slot],
                                      ref_s_sl, ref_e_sl, mod_scale, scale_mode)
                    if oid:
                        self.aggregated_ids.append(oid); count += 1

        # ── V3: JOINT placement ────────────────────────────
        joint_count = 0
        if bool(self.chk_joints.Checked) and (self.node_geo_id or self.arm_geo_id):
            joint_count = self._place_joints(crv_pairs, _f)

        LOGIC_NAMES = ["Sequential", "Speed-Based", "Curvature",
                       "Density Field", "Layer Stack"]
        src = "live boids" if use_boids else f"{len(crv_pairs)} picked curves"
        sc.doc.Views.Redraw()
        jstr = f"  +{joint_count} joints" if joint_count else ""
        self.lbl_status.Text = (
            f"Status: {count} modules{jstr}  [{LOGIC_NAMES[logic]}]  "
            f"source: {src}  scale: {scale_mode}")

    # ── V3: Joint placement helper ────────────────────────
    def _place_joints(self, crv_pairs, _f):
        """Place Node and Arm geometry at trail endpoints and crossings.

        Node geo: placed at each joint point, oriented along the trail tangent
                  using the node geometry's SHORT axis (_auto_short_ref_pts).
        Arm geo:  one instance per trail arriving at a joint, oriented along
                  the trail tangent using the arm geometry's PRIMARY axis.

        Returns total joint geometry count placed.
        """
        def _fv(t, d):
            try: return float(t.Text)
            except: return d

        node_scale     = max(0.001, _fv(self.txt_node_scale,   1.0))
        arm_offset     = max(0.0,   _fv(self.txt_arm_offset,   1.0))
        arm_scale_mult = max(0.001, _fv(self.txt_arm_scale,    1.0))
        cross_thresh   = max(0.001, _fv(self.txt_cross_thresh, 2.0))

        layer_node_idx = _ensure_layer("Boids::Joints::Node", sd.Color.FromArgb(255, 200,   0))
        layer_arm_idx  = _ensure_layer("Boids::Joints::Arm",  sd.Color.FromArgb(255, 140,   0))
        attr_node = Rhino.DocObjects.ObjectAttributes(); attr_node.LayerIndex = layer_node_idx
        attr_arm  = Rhino.DocObjects.ObjectAttributes(); attr_arm.LayerIndex  = layer_arm_idx

        # ── Collect joint data ─────────────────────────────
        # joint_map: rounded key → {'pt': Point3d, 'tangents': [(Vector3d, crv), ...]}
        PREC = 2  # decimal places for key rounding
        joint_map = {}

        def _add_joint(pt, tang, crv_ref):
            key = (round(pt.X, PREC), round(pt.Y, PREC), round(pt.Z, PREC))
            if key not in joint_map:
                joint_map[key] = {'pt': pt, 'tangents': []}
            joint_map[key]['tangents'].append((Rhino.Geometry.Vector3d(tang), crv_ref))

        # Trail endpoints
        for crv, _ in crv_pairs:
            t_start = crv.Domain.Min
            t_end   = crv.Domain.Max
            tang_s  = crv.TangentAt(t_start)
            tang_e  = crv.TangentAt(t_end)
            if tang_s is not None: tang_s.Unitize()
            if tang_e is not None: tang_e.Unitize()
            if tang_s is not None:
                _add_joint(crv.PointAt(t_start), tang_s, crv)
            if tang_e is not None:
                rev = Rhino.Geometry.Vector3d(-tang_e.X, -tang_e.Y, -tang_e.Z)
                _add_joint(crv.PointAt(t_end), rev, crv)

        # Trail crossings — O(n²), bbox pre-filter for performance
        crvs = [c for c, _ in crv_pairs]
        crv_bbs = [c.GetBoundingBox(False) for c in crvs]
        tol = sc.doc.ModelAbsoluteTolerance
        for i in range(len(crvs)):
            for j in range(i + 1, len(crvs)):
                # BBox pre-filter — inflate by cross_thresh
                bbi = crv_bbs[i]; bbj = crv_bbs[j]
                overlap = (bbi.Min.X - cross_thresh <= bbj.Max.X and
                           bbj.Min.X - cross_thresh <= bbi.Max.X and
                           bbi.Min.Y - cross_thresh <= bbj.Max.Y and
                           bbj.Min.Y - cross_thresh <= bbi.Max.Y and
                           bbi.Min.Z - cross_thresh <= bbj.Max.Z and
                           bbj.Min.Z - cross_thresh <= bbi.Max.Z)
                if not overlap: continue
                try:
                    ok, dist, tA, tB, _, _ = \
                        Rhino.Geometry.Curve.GetDistancesBetweenCurves(
                            crvs[i], crvs[j], tol)
                    if not ok or dist > cross_thresh: continue
                    ptA  = crvs[i].PointAt(tA)
                    ptB  = crvs[j].PointAt(tB)
                    mid  = Rhino.Geometry.Point3d(
                        (ptA.X+ptB.X)*0.5, (ptA.Y+ptB.Y)*0.5, (ptA.Z+ptB.Z)*0.5)
                    tgA  = crvs[i].TangentAt(tA)
                    tgB  = crvs[j].TangentAt(tB)
                    if tgA is not None:
                        tgA.Unitize()
                        _add_joint(mid, tgA, crvs[i])
                    if tgB is not None:
                        tgB.Unitize()
                        _add_joint(mid, tgB, crvs[j])
                except: pass

        # ── Place geometry at each joint ───────────────────
        placed = 0
        for jdata in joint_map.values():
            pt       = jdata['pt']
            tangents = jdata['tangents']
            if not tangents: continue

            # Node geometry
            if self.node_geo_id:
                node_geo = _duplicate_geo(self.node_geo_id)
                if node_geo:
                    n_ref_s, n_ref_e = _auto_short_ref_pts(node_geo)
                    if n_ref_s is not None and n_ref_e is not None:
                        # Align node's short axis to first arriving trail tangent
                        tang0  = tangents[0][0]
                        tang0.Unitize()
                        t_end_pt = Rhino.Geometry.Point3d(
                            pt.X + tang0.X, pt.Y + tang0.Y, pt.Z + tang0.Z)
                        xf = _build_orient_xform(
                            pt, t_end_pt, n_ref_s, n_ref_e, node_scale, node_scale)
                    else:
                        # Fallback: uniform scale in place
                        xf = Rhino.Geometry.Transform.Scale(
                            Rhino.Geometry.Plane(pt, Rhino.Geometry.Vector3d.ZAxis),
                            node_scale, node_scale, node_scale)
                    node_geo.Transform(xf)
                    oid = _add_geo(node_geo, attr_node)
                    if oid != System.Guid.Empty:
                        self.aggregated_joint_ids.append(oid); placed += 1

            # Arm geometry — one per arriving tangent direction
            if self.arm_geo_id:
                for tang, _ in tangents:
                    arm_geo = _duplicate_geo(self.arm_geo_id)
                    if not arm_geo: continue
                    a_ref_s, a_ref_e = _auto_ref_pts(arm_geo)
                    if a_ref_s is None or a_ref_e is None: continue
                    tang.Unitize()
                    # Arm starts at joint + offset along tangent
                    arm_start = Rhino.Geometry.Point3d(
                        pt.X + tang.X * arm_offset,
                        pt.Y + tang.Y * arm_offset,
                        pt.Z + tang.Z * arm_offset)
                    arm_end = Rhino.Geometry.Point3d(
                        arm_start.X + tang.X,
                        arm_start.Y + tang.Y,
                        arm_start.Z + tang.Z)
                    # arm_scale_mult applied uniformly (axial + radial) → scales arm length + girth
                    xf = _build_orient_xform(
                        arm_start, arm_end, a_ref_s, a_ref_e, arm_scale_mult, arm_scale_mult)
                    arm_geo.Transform(xf)
                    oid = _add_geo(arm_geo, attr_arm)
                    if oid != System.Guid.Empty:
                        self.aggregated_joint_ids.append(oid); placed += 1

        return placed

    # ── V3: New button handlers ────────────────────────────
    def OnSetRefPts(self, s, e):
        """Pick two points to define the module axis manually."""
        self.lbl_status.Text = "Status: Click start of module axis..."
        pt_s = rs.GetPoint("Click start of module axis (e.g. bottom/left end of geometry)")
        if pt_s is None:
            self.lbl_status.Text = "Status: Axis set cancelled"; return
        self.lbl_status.Text = "Status: Click end of module axis..."
        pt_e = rs.GetPoint("Click end of module axis (e.g. top/right end of geometry)")
        if pt_e is None:
            self.lbl_status.Text = "Status: Axis set cancelled"; return
        self.man_ref_start = Rhino.Geometry.Point3d(pt_s)
        self.man_ref_end   = Rhino.Geometry.Point3d(pt_e)
        length = pt_s.DistanceTo(pt_e)
        self.lbl_ref_status.Text      = f"✓ Manual axis set  |  length = {length:.3f}"
        self.lbl_ref_status.TextColor = drawing.Color.FromArgb(0, 210, 80)
        self.lbl_status.Text = (
            f"Status: Manual axis defined — {length:.3f} units.  "
            f"Uncheck 'Manual Axis' to revert to auto-detect.")

    def OnSelectNode(self, s, e):
        """Pick geometry to use as joint node (disc/hub at joint positions)."""
        oid = rs.GetObject("Select node geometry (tip: use a flat disc or sphere)", 0)
        if not oid: return
        self.node_geo_id        = oid
        self.lbl_node.Text      = "✓ node geo assigned"
        self.lbl_node.TextColor = drawing.Color.FromArgb(0, 210, 80)
        self.lbl_status.Text    = "Status: Joint node geometry assigned"

    def OnSelectArm(self, s, e):
        """Pick geometry to use as joint arm (placed along trail tangent)."""
        oid = rs.GetObject("Select arm geometry (tip: use a short rod/tube)", 0)
        if not oid: return
        self.arm_geo_id        = oid
        self.lbl_arm.Text      = "✓ arm geo assigned"
        self.lbl_arm.TextColor = drawing.Color.FromArgb(0, 210, 80)
        self.lbl_status.Text   = "Status: Joint arm geometry assigned"

    # ── Mesh skin ─────────────────────────────────────────
    def OnGenerateMesh(self, s, e):
        all_pts = []
        for b in self.boids: all_pts.extend(b.history)
        if len(all_pts) < 3:
            self.lbl_status.Text = "Status: Not enough points for mesh"; return
        try: spacing = max(0.1, float(self.txt_spacing.Text))
        except: spacing = 1.5
        self.lbl_status.Text = "Status: Building mesh skin..."; Rhino.RhinoApp.Wait()
        thr2 = (spacing * 0.5) ** 2
        upts = []
        for pt in all_pts:
            if not any((pt.X-u.X)**2+(pt.Y-u.Y)**2+(pt.Z-u.Z)**2 < thr2 for u in upts):
                upts.append(pt)
        n = len(upts)
        if n < 3:
            self.lbl_status.Text = "Status: Not enough unique points"; return
        mesh = Rhino.Geometry.Mesh()
        for pt in upts: mesh.Vertices.Add(pt)
        k = min(6, n-1); max_edge = spacing * 3.0; used = set()
        for i in range(n):
            dists = sorted(
                [(upts[i].DistanceTo(upts[j]), j) for j in range(n) if j != i])[:k]
            nbrs = [d[1] for d in dists]
            for ni in range(len(nbrs)):
                for nj in range(ni+1, len(nbrs)):
                    j1, j2 = nbrs[ni], nbrs[nj]
                    if upts[j1].DistanceTo(upts[j2]) > max_edge: continue
                    key = tuple(sorted([i, j1, j2]))
                    if key not in used:
                        used.add(key); mesh.Faces.AddFace(i, j1, j2)
        mesh.Normals.ComputeNormals(); mesh.Compact()
        if mesh.Faces.Count > 0:
            layer_idx = _ensure_layer("Boids::Mesh", sd.Color.FromArgb(180, 255, 160))
            mattr = Rhino.DocObjects.ObjectAttributes()
            mattr.LayerIndex = layer_idx
            sc.doc.Objects.AddMesh(mesh, mattr)
            self.lbl_status.Text = (
                f"Status: Mesh — {mesh.Faces.Count} faces, {n} pts → Boids::Mesh")
        else:
            self.lbl_status.Text = "Status: Mesh failed — try larger spacing"
        sc.doc.Views.Redraw()

    # ── Clear helpers ─────────────────────────────────────
    def OnClearTrails(self, s, e):
        count = 0
        for oid in self.trail_ids:
            obj = sc.doc.Objects.Find(oid)
            if obj and not obj.IsDeleted:
                sc.doc.Objects.Delete(obj, True); count += 1
        self.trail_ids.clear()
        sc.doc.Views.Redraw()
        self.lbl_status.Text = f"Status: Cleared {count} trail curve(s)"

    def OnClearAggregated(self, s, e):
        count = 0
        # V3: also clear joint geometry
        for oid in self.aggregated_ids + self.aggregated_joint_ids:
            obj = sc.doc.Objects.Find(oid)
            if obj and not obj.IsDeleted:
                sc.doc.Objects.Delete(obj, True); count += 1
        self.aggregated_ids.clear()
        self.aggregated_joint_ids.clear()
        sc.doc.Views.Redraw()
        self.lbl_status.Text = f"Status: Cleared {count} aggregated module(s) + joints"

    def OnClearAll(self, s, e):
        preserved = {g for g in (
            self.base_geo_id, self.base_geo_id_2, self.base_geo_id_3,
            self.node_geo_id, self.arm_geo_id) if g}
        to_del = [
            o for o in sc.doc.Objects
            if o.Id not in preserved and
            isinstance(o.Geometry, (Rhino.Geometry.Curve,
                                    Rhino.Geometry.Brep,
                                    Rhino.Geometry.Mesh,
                                    Rhino.Geometry.Extrusion))
        ]
        for o in to_del: sc.doc.Objects.Delete(o, True)
        self.aggregated_ids.clear()
        self.aggregated_joint_ids.clear()
        self.plank_ids.clear()
        sc.doc.Views.Redraw()
        self.lbl_status.Text = f"Status: Cleared {len(to_del)} objects"

    # ─────────────────────────────────────────────────────
    #  STEAM WOOD PLANKS
    # ─────────────────────────────────────────────────────
    def _get_plank_curves(self):
        """
        Return (curves, source_label) for plank generation.
        Priority: picked curves → baked trail_ids → live boid history.
        """
        # 1. User-picked curves
        if self.picked_curve_ids:
            crvs = []
            for cid in self.picked_curve_ids:
                obj = sc.doc.Objects.Find(cid)
                if obj and not obj.IsDeleted and isinstance(obj.Geometry, Rhino.Geometry.Curve):
                    crvs.append(obj.Geometry.Duplicate())
            if crvs:
                return crvs, f"picked curves ({len(crvs)})"

        # 2. Baked trail GUIDs
        crvs = []
        for cid in self.trail_ids:
            obj = sc.doc.Objects.Find(cid)
            if obj and not obj.IsDeleted and isinstance(obj.Geometry, Rhino.Geometry.Curve):
                crvs.append(obj.Geometry.Duplicate())
        if crvs:
            return crvs, f"baked trails ({len(crvs)})"

        # 3. Live boid history — interpolate directly from history points
        crvs = []
        for boid in self.boids:
            if len(boid.history) >= 4:
                try:
                    crv = Rhino.Geometry.Curve.CreateInterpolatedCurve(boid.history, 3)
                    if crv and crv.IsValid:
                        crvs.append(crv)
                except Exception:
                    pass
        if crvs:
            return crvs, f"live boid history ({len(crvs)})"

        return [], "none"

    def _read_plank_profile_params(self, slot):
        """Return (ptype, width, height, shape) for slot 1/2/3."""
        if slot == 1:
            ptype  = self.dd_p1_type.SelectedIndex
            width  = _safe_float(self.txt_p1_width.Text,  2.0)
            height = _safe_float(self.txt_p1_height.Text, 0.5)
            shape  = _safe_float(self.txt_p1_shape.Text,  0.1)
        elif slot == 2:
            ptype  = self.dd_p2_type.SelectedIndex
            width  = _safe_float(self.txt_p2_width.Text,  2.5)
            height = _safe_float(self.txt_p2_height.Text, 0.4)
            shape  = _safe_float(self.txt_p2_shape.Text,  0.15)
        else:
            ptype  = self.dd_p3_type.SelectedIndex
            width  = _safe_float(self.txt_p3_width.Text,  1.8)
            height = _safe_float(self.txt_p3_height.Text, 0.6)
            shape  = _safe_float(self.txt_p3_shape.Text,  0.25)
        return ptype, max(0.01, width), max(0.01, height), max(0.0, min(0.99, shape))

    def _ensure_plank_layers(self):
        """Create Boids::WoodPlanks sub-layers if they don't exist. Returns [p1_idx, p2_idx, p3_idx]."""
        return [
            _ensure_layer("Boids::WoodPlanks::P1", sd.Color.FromArgb(210, 170, 100)),
            _ensure_layer("Boids::WoodPlanks::P2", sd.Color.FromArgb(160, 115,  60)),
            _ensure_layer("Boids::WoodPlanks::P3", sd.Color.FromArgb(100,  65,  25)),
        ]

    def _add_plank_brep(self, brep, layer_idx):
        """Add a Brep to the document on layer_idx. Returns GUID."""
        attr = Rhino.DocObjects.ObjectAttributes()
        attr.LayerIndex = layer_idx
        attr.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromLayer
        oid = sc.doc.Objects.AddBrep(brep, attr)
        return oid if oid != System.Guid.Empty else None

    def _trail_avg_speed(self, crv_idx):
        """Return average speed recorded for boid trail at crv_idx, or 0 if unavailable."""
        if crv_idx < len(self.boids):
            hist = self.boids[crv_idx].history
            if len(hist) > 1:
                speeds = [v.Length for v in (
                    hist[i] - hist[i-1] for i in range(1, len(hist)))]
                return sum(speeds) / len(speeds)
        return 0.0

    def _trail_avg_curvature(self, crv):
        """Return average curvature of `crv` sampled at 10 points."""
        dom     = crv.Domain
        samples = 10
        total   = 0.0
        for i in range(samples):
            t = dom.ParameterAt(i / (samples - 1))
            k = crv.CurvatureAt(t)
            total += k.Length if k and k.Length > 0 else 0.0
        return total / samples

    def _plank_msg(self, text, color=None):
        """Write to the dedicated plank status label (and also the main status bar)."""
        self.lbl_plank_status.Text = text
        if color:
            self.lbl_plank_status.TextColor = color
        self.lbl_status.Text = "Planks: " + text

    def OnGeneratePlanks(self, s, e):
        try:
            self._run_generate_planks()
        except Exception as ex:
            self._plank_msg(f"✖ Error — {ex}", drawing.Color.FromArgb(255, 255, 80, 80))

    def _run_generate_planks(self):
        _DIM = drawing.Color.FromArgb(130, 130, 155)
        self._plank_msg("● Collecting curves…", _DIM)
        crvs, src_label = self._get_plank_curves()
        if not crvs:
            self._plank_msg(
                "✖ No curves found.\n"
                "  → Run simulation then click  Bake Trails Now\n"
                "  → or click  Pick Existing Curves for Aggregation",
                drawing.Color.FromArgb(255, 255, 160, 60))
            return
        self._plank_msg(f"● Source: {src_label}  — building profiles…", _DIM)

        layer_idxs  = self._ensure_plank_layers()   # [p1_idx, p2_idx, p3_idx]
        logic_idx   = self.dd_plank_logic.SelectedIndex
        off1        = _safe_float(self.txt_plank_off1.Text, 0.5)
        off2        = _safe_float(self.txt_plank_off2.Text, 1.0)
        placed      = 0
        failed      = 0

        # Pre-read all profile params
        p_params = [self._read_plank_profile_params(slot) for slot in (1, 2, 3)]

        # Collect speed / curvature data for all trails (needed for logic modes 2 & 3)
        if logic_idx in (2, 3):
            trail_data = []
            for ci, crv in enumerate(crvs):
                if logic_idx == 2:
                    trail_data.append(self._trail_avg_speed(ci))
                else:
                    trail_data.append(self._trail_avg_curvature(crv))
            if trail_data:
                dmin = min(trail_data); dmax = max(trail_data)
                drange = max(dmax - dmin, 1e-8)
                trail_norm = [(v - dmin) / drange for v in trail_data]
            else:
                trail_norm = [0.0] * len(crvs)
        else:
            trail_norm = [0.0] * len(crvs)

        max_plank_len = _safe_float(self.txt_plank_max_len.Text, 40.0)
        joint_gap     = max(0.0, _safe_float(self.txt_plank_gap.Text, 0.5))

        def _place_one_plank(crv, slot, normal_offset=0.0):
            """
            Subdivide crv into physical plank pieces (max_plank_len each, joint_gap
            removed at both ends of every piece), then loft-sweep each segment.
            Returns list of GUIDs, or None if nothing placed.
            """
            ptype, width, height, shape = p_params[slot - 1]
            layer_idx = layer_idxs[slot - 1]

            # Apply normal offset (Layer Stack) — push plank along world Z
            work_crv = crv
            if abs(normal_offset) > 1e-6:
                xf = Rhino.Geometry.Transform.Translation(
                    Rhino.Geometry.Vector3d.ZAxis * normal_offset)
                work_crv = crv.Duplicate()
                work_crv.Transform(xf)

            # ── Subdivide into physical plank segments ────────────
            segments = _subdivide_curve_by_length(work_crv, max_plank_len, joint_gap)

            oids = []
            for seg in segments:
                # Loft-based sweep (no SweepOneRail — more robust across Rhino versions)
                breps = _sweep_plank(seg, ptype, width, height, shape)
                if not breps:
                    continue
                for brep in breps:
                    oid = self._add_plank_brep(brep, layer_idx)
                    if oid:
                        oids.append(oid)
            return oids if oids else None

        for ci, crv in enumerate(crvs):
            # Determine which profile slot(s) to use
            if logic_idx == 0:
                # P1 Only
                slots_offsets = [(1, 0.0)]
            elif logic_idx == 1:
                # Alternate by trail index
                slot = (ci % 3) + 1
                slots_offsets = [(slot, 0.0)]
            elif logic_idx == 2:
                # By Speed (normalised 0–1)
                nv = trail_norm[ci]
                slot = 1 if nv < 0.4 else (2 if nv < 0.75 else 3)
                slots_offsets = [(slot, 0.0)]
            elif logic_idx == 3:
                # By Curvature (normalised 0–1)
                nv = trail_norm[ci]
                slot = 1 if nv > 0.6 else (2 if nv > 0.3 else 3)
                slots_offsets = [(slot, 0.0)]
            else:
                # Layer Stack — all 3 at successive offsets
                slots_offsets = [(1, 0.0), (2, off1), (3, off2)]

            for slot, offset in slots_offsets:
                result = _place_one_plank(crv, slot, offset)
                if result:
                    self.plank_ids.extend(result)
                    placed += len(result)
                else:
                    failed += 1

        sc.doc.Views.Redraw()
        if placed > 0:
            msg = f"✔ Generated {placed} plank brep(s) from {src_label}"
            if failed:
                msg += f"  ({failed} trail(s) failed)"
            self._plank_msg(msg, drawing.Color.FromArgb(255, 120, 220, 120))
        else:
            self._plank_msg(
                f"✖ 0 breps generated from {src_label}  ({failed} failed).\n"
                "  → Try increasing Width or Height values\n"
                "  → Or check that trail curves are not too short",
                drawing.Color.FromArgb(255, 255, 160, 60))

    def OnClearPlanks(self, s, e):
        count = 0
        for oid in self.plank_ids:
            obj = sc.doc.Objects.Find(oid)
            if obj and not obj.IsDeleted:
                sc.doc.Objects.Delete(obj, True); count += 1
        self.plank_ids.clear()
        sc.doc.Views.Redraw()
        self.lbl_status.Text = f"Status: Cleared {count} plank brep(s)"

    def OnFormClosed(self, s, e):
        self.is_running = False
        self.conduit.Enabled = False
        sc.doc.Views.Redraw()


# ═══════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════
def RunFlockingBoidsV3():
    form = FlockingBoids_V1()
    form.Show()


if __name__ == "__main__":
    RunFlockingBoidsV3()
