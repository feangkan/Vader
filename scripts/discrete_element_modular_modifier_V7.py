#! python 2
# Discrete Element Modular Modifier V7
# RhinoCommon + Eto.Forms GUI  —  Dark Gold Theme
# V7 Adds (on top of V6):
#   * Placement Logic Filter  (Interior / All Sides / Facade / Wall / Ceiling / Floor / Shared)
#   * Cap Geometry option     (CapPlanarHoles after sweep)
#   * Independent profile Width + Height  (size_z param)
#   * Random Length           (beams trimmed to random fraction of span)
#   * Noise Mode (Tab 4)      (Flow Field, Stigmergy, Boids, Reaction-Diffusion)
#   Mode 0: Timber Joint    (Orthogonal Grid — attractor, jitter, analytical joints)
#   Mode 1: Discrete Modular (Random Lines)
#   Mode 2: Connected        (tip-to-tip graph)
#   Mode 3: Pipe Facade      (vertical stacked pipes, wander, elbows, brackets)
#   Mode 4: Noise Mode       (agent-based procedural line patterns)

import rhinoscriptsyntax as rs
import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import System
import System.Drawing as sd
import math
import random
import traceback

try:
    import Eto.Forms as ef
    import Eto.Drawing as edraw
except:
    print("Error: Eto.Forms not available")

# =============================================================================
# CONSTANTS
# =============================================================================
PROFILE_NAMES   = ['Square', 'Circle', 'Triangle', 'Hexagon', 'Octagon',
                   'L-shape', 'T-shape', 'I-shape']
GEN_MODES       = ['Orthogonal Grid', 'Random Lines', 'Connected Lines',
                   'Pipe Facade', 'Noise Mode']
PT_SOURCES      = ['U \xd7 V Grid', 'Face Count (QuadRemesh)']
PLACEMENT_MODES = ['Interior (Volume)', 'All Sides', 'Facade (no top/bottom)',
                   'Wall (one side)', 'Ceiling (top)', 'Floor (bottom)', 'Shared Faces']
WALL_FACES      = ['+X face', '-X face', '+Y face', '-Y face']
NOISE_ALGOS     = ['Flow Field (Perlin)', 'Stigmergy (Ant Trails)',
                   'Boids (Flocking)', 'Reaction-Diffusion']
RD_INITS        = ['Centre Seed', 'Random Dots', 'Edges']
LAYER_NAME      = "TECTONIC_Module"
GUIDE_LAYER     = "TECTONIC_Guide"

# Dark Gold palette
C_GOLD    = edraw.Color(212, 175, 55)
C_GOLD_DIM = edraw.Color(160, 130, 40)
C_BG      = edraw.Color(26, 26, 26)
C_FG      = edraw.Color(210, 200, 185)
C_GREEN   = edraw.Color(100, 190, 80)
C_RED     = edraw.Color(220, 80, 60)
C_ORANGE  = edraw.Color(220, 140, 40)

DEFAULTS = {
    # Box
    'width': 20.0, 'height': 20.0, 'depth': 20.0,
    # Tiling
    'tile_x': 3, 'tile_y': 3, 'tile_z': 1,
    # Mode
    'gen_mode': 0,
    # Ortho
    'u_div': 3, 'v_div': 3, 'w_div': 2,
    'num_beams': 30,
    'use_x': True, 'use_y': True, 'use_z': True,
    'hz_bias': 70,
    'enable_attractor': True,
    'attr_x': 0.0, 'attr_y': 0.0, 'attr_z': 30.0,
    'attr_radius': 50.0,
    'attr_min_density': 0,
    'grid_jitter': 30,
    'ortho_seed': 42,
    # Placement filter (mode 0)
    'use_placement':  False,
    'placement_mode': 0,
    'wall_face':      0,
    # Random length (mode 0)
    'random_length':  False,
    'min_length_pct': 50,
    # Random / Connected
    'pt_source': 0,
    'face_count': 64,
    'num_lines': 10,
    'rand_seed': 42,
    'base_angle': 45,
    'angle_range': 20,
    # Profile
    'profile_shape': 0,
    'profile_size':   4.0,
    'profile_size_z': 4.0,
    # Cap
    'cap_geometry': True,
    # Joints
    'enable_joints': True,
    'max_joints': 300,
    # Output
    'union_mesh': False,
    # Guide
    'enable_guide': True,
    'guide_radius': 0.01,
    # Pipe Facade (mode 3)
    'pipe_grid_x':      4,
    'pipe_grid_y':      1,
    'pipe_z_levels':    5,
    'pipe_mod_h':       20.0,
    'pipe_diameter':    2.0,
    'pipe_wander':      70,
    'pipe_conn_prob':   30,
    'pipe_brackets':    True,
    'pipe_bracket_int': 2,
    'pipe_seed':        42,
    # Noise Mode (mode 4)
    'noise_algo':         0,
    'noise_seed':         42,
    'noise_num_agents':   20,
    'noise_steps':        100,
    'noise_step_size':    1.0,
    'noise_scale':        0.15,
    'noise_octaves':      4,
    'noise_persistence':  50,
    'stig_num_agents':    15,
    'stig_steps':         150,
    'stig_step_size':     1.0,
    'stig_evap':          20,
    'stig_deposit':       1.0,
    'stig_sense_dist':    3.0,
    'boids_num':          20,
    'boids_steps':        100,
    'boids_step_size':    1.0,
    'boids_sep_dist':     4.0,
    'boids_sep_w':        1.5,
    'boids_align_w':      1.0,
    'boids_cohesion_w':   1.0,
    'boids_max_speed':    2.0,
    'rd_feed':            0.055,
    'rd_kill':            0.062,
    'rd_steps':           500,
    'rd_init':            0,
}

# =============================================================================
# GEOMETRY ENGINE
# =============================================================================

def create_box(width, height, depth):
    box = rg.Box(
        rg.Plane.WorldXY,
        rg.Interval(-width / 2.0, width / 2.0),
        rg.Interval(-height / 2.0, height / 2.0),
        rg.Interval(-depth / 2.0, depth / 2.0),
    )
    return box.ToBrep()


def box_to_mesh(brep):
    meshes = rg.Mesh.CreateFromBrep(brep, rg.MeshingParameters.Default)
    if not meshes:
        return None
    combined = rg.Mesh()
    for m in meshes:
        combined.Append(m)
    combined.Weld(math.pi)
    combined.Compact()
    return combined


def quadremesh_mesh(mesh, face_count):
    if not hasattr(rg, 'QuadRemeshParameters'):
        raise RuntimeError("QuadRemesh requires Rhino 7+")
    qp = rg.QuadRemeshParameters()
    qp.TargetQuadCount = face_count
    result = mesh.QuadRemesh(qp)
    if result is None:
        raise RuntimeError("QuadRemesh failed.")
    return result


def generate_grid_points_uv(width, height, depth, u_div, v_div, w_div):
    points = []
    hw, hh, hd = width / 2.0, height / 2.0, depth / 2.0
    for i in range(u_div + 1):
        for j in range(v_div + 1):
            for k in range(w_div + 1):
                x = -hw + width  * i / float(u_div)
                y = -hh + height * j / float(v_div)
                z = -hd + depth  * k / float(w_div)
                points.append(rg.Point3d(x, y, z))
    return points


def extract_grid_points(mesh):
    return [rg.Point3d(mesh.Vertices[i].X,
                       mesh.Vertices[i].Y,
                       mesh.Vertices[i].Z)
            for i in range(mesh.Vertices.Count)]


def _get_line_points(params):
    w, h, d = params['width'], params['height'], params['depth']
    if params.get('pt_source', 0) == 1:
        box_brep = create_box(w, h, d)
        mesh     = box_to_mesh(box_brep)
        box_brep.Dispose()
        qmesh    = quadremesh_mesh(mesh, int(params.get('face_count', 64)))
        mesh.Dispose()
        pts = extract_grid_points(qmesh)
        qmesh.Dispose()
        return pts
    else:
        return generate_grid_points_uv(w, h, d,
                                       params['u_div'], params['v_div'], params['w_div'])


def generate_random_lines(points, count, seed, base_angle, angle_range):
    if len(points) < 2:
        return []
    rng   = random.Random(seed)
    lines = []
    a_min = max(0.0, base_angle - angle_range)
    a_max = min(90.0, base_angle + angle_range)
    n     = len(points)
    attempts = 0
    while len(lines) < count and attempts < count * 50:
        attempts += 1
        i = rng.randint(0, n - 1)
        j = rng.randint(0, n - 1)
        if i == j:
            continue
        p1, p2 = points[i], points[j]
        dx, dy, dz = p2.X - p1.X, p2.Y - p1.Y, p2.Z - p1.Z
        length = math.sqrt(dx*dx + dy*dy + dz*dz)
        if length < 1e-6:
            continue
        horiz = math.sqrt(dx*dx + dy*dy)
        angle_deg = math.degrees(math.atan2(abs(dz), horiz))
        if a_min <= angle_deg <= a_max:
            line = rg.Line(p1, p2)
            dup = any(
                (e.From.DistanceTo(p1) < 0.01 and e.To.DistanceTo(p2) < 0.01) or
                (e.From.DistanceTo(p2) < 0.01 and e.To.DistanceTo(p1) < 0.01)
                for e in lines
            )
            if not dup:
                lines.append(line)
    return lines


def generate_connected_lines(points, count, seed, base_angle, angle_range):
    if len(points) < 2:
        return []
    rng = random.Random(seed)
    n   = len(points)
    lines        = []
    endpoint_pts = []

    def _angle_ok(p1, p2, a_min, a_max):
        dx = p2.X - p1.X; dy = p2.Y - p1.Y; dz = p2.Z - p1.Z
        l  = math.sqrt(dx*dx + dy*dy + dz*dz)
        if l < 1e-6: return False
        h = math.sqrt(dx*dx + dy*dy)
        return a_min <= math.degrees(math.atan2(abs(dz), h)) <= a_max

    def _try_end(start, a_min, a_max, tries=40):
        for _ in range(tries):
            ep = points[rng.randint(0, n - 1)]
            if _angle_ok(start, ep, a_min, a_max):
                return ep
        return None

    def _is_dup(p1, p2):
        return any(
            (e.From.DistanceTo(p1) < 0.01 and e.To.DistanceTo(p2) < 0.01) or
            (e.From.DistanceTo(p2) < 0.01 and e.To.DistanceTo(p1) < 0.01)
            for e in lines
        )

    ar = angle_range
    angle_sequences = [
        (max(0.0, base_angle - ar), min(90.0, base_angle + ar)),
        (max(0.0, 45.0 - ar),       min(90.0, 45.0 + ar)),
        (max(0.0, 90.0 - ar),       90.0),
        (0.0,                        90.0),
    ]

    attempts = 0
    while len(lines) < count and attempts < count * 150:
        attempts += 1
        start = rng.choice(endpoint_pts) if endpoint_pts else points[rng.randint(0, n - 1)]
        end   = None
        for a_min, a_max in angle_sequences:
            end = _try_end(start, a_min, a_max)
            if end is not None:
                break
        if end is None or end.DistanceTo(start) < 1e-6:
            continue
        if _is_dup(start, end):
            continue
        lines.append(rg.Line(start, end))
        endpoint_pts.append(start)
        endpoint_pts.append(end)

    return lines


# ── Profile Cross-Section ────────────────────────────────────────────────────

def create_profile(shape_name, size, size_z=None):
    """
    Create a closed profile curve in WorldXY.
    size   = width  (X direction of cross-section)
    size_z = height (Y direction of cross-section); defaults to size if None.
    """
    sz = size_z if (size_z is not None and size_z > 0) else size
    hx = size / 2.0
    hz = sz   / 2.0

    if shape_name == 'Circle':
        crv = rg.Circle(rg.Plane.WorldXY, hx).ToNurbsCurve()
        if abs(sz - size) > 1e-6 and size > 1e-6:
            xf = rg.Transform.Scale(rg.Plane.WorldXY, 1.0, sz / size, 1.0)
            crv.Transform(xf)
        return crv

    if shape_name == 'Square':
        # Rectangle when size_z differs
        pts = [rg.Point3d(-hx, -hz, 0), rg.Point3d(hx, -hz, 0),
               rg.Point3d(hx,   hz, 0), rg.Point3d(-hx, hz, 0),
               rg.Point3d(-hx, -hz, 0)]
    elif shape_name == 'Triangle':
        r   = hx
        pts = [rg.Point3d(r*math.cos(math.radians(90 + k*120)),
                          r*math.sin(math.radians(90 + k*120)), 0) for k in range(3)]
        pts.append(pts[0])
    elif shape_name == 'Hexagon':
        r   = hx
        pts = [rg.Point3d(r*math.cos(math.radians(k*60)),
                          r*math.sin(math.radians(k*60)), 0) for k in range(6)]
        pts.append(pts[0])
    elif shape_name == 'Octagon':
        r   = hx
        pts = [rg.Point3d(r*math.cos(math.radians(k*45)),
                          r*math.sin(math.radians(k*45)), 0) for k in range(8)]
        pts.append(pts[0])
    elif shape_name == 'L-shape':
        s, o = size, size / 2.0
        pts = [rg.Point3d(-o, -o, 0), rg.Point3d(o, -o, 0),
               rg.Point3d(o, -o + s*0.4, 0), rg.Point3d(-o + s*0.4, -o + s*0.4, 0),
               rg.Point3d(-o + s*0.4, o, 0), rg.Point3d(-o, o, 0),
               rg.Point3d(-o, -o, 0)]
    elif shape_name == 'T-shape':
        s, o, w = size, size / 2.0, size * 0.3
        pts = [rg.Point3d(-o, -o, 0), rg.Point3d(o, -o, 0),
               rg.Point3d(o, -o + w, 0), rg.Point3d(w/2.0, -o + w, 0),
               rg.Point3d(w/2.0, o, 0), rg.Point3d(-w/2.0, o, 0),
               rg.Point3d(-w/2.0, -o + w, 0), rg.Point3d(-o, -o + w, 0),
               rg.Point3d(-o, -o, 0)]
    elif shape_name == 'I-shape':
        o  = size / 2.0
        fw = size * 0.2
        ww = size * 0.2
        pts = [
            rg.Point3d(-o,  -o,       0), rg.Point3d( o,  -o,       0),
            rg.Point3d( o,  -o + fw,  0), rg.Point3d( ww, -o + fw,  0),
            rg.Point3d( ww,  o - fw,  0), rg.Point3d( o,   o - fw,  0),
            rg.Point3d( o,   o,       0), rg.Point3d(-o,   o,       0),
            rg.Point3d(-o,   o - fw,  0), rg.Point3d(-ww,  o - fw,  0),
            rg.Point3d(-ww, -o + fw,  0), rg.Point3d(-o,  -o + fw,  0),
            rg.Point3d(-o,  -o,       0),
        ]
    else:
        pts = [rg.Point3d(-hx, -hz, 0), rg.Point3d(hx, -hz, 0),
               rg.Point3d(hx,   hz, 0), rg.Point3d(-hx, hz, 0),
               rg.Point3d(-hx, -hz, 0)]

    crv = rg.Polyline(pts).ToNurbsCurve()
    # Apply non-uniform scale for size_z on polygon shapes
    if shape_name not in ('Square', 'I-shape') and abs(sz - size) > 1e-6 and size > 1e-6:
        xf = rg.Transform.Scale(rg.Plane.WorldXY, 1.0, sz / size, 1.0)
        crv.Transform(xf)
    return crv


# ── Sweep ─────────────────────────────────────────────────────────────────────

def sweep_along_lines(profile_curve, lines, cap=True):
    """Extrude profile along each line. Returns (breps, directions)."""
    tol        = sc.doc.ModelAbsoluteTolerance
    breps      = []
    directions = []
    for line in lines:
        direction = rg.Vector3d(line.To - line.From)
        if direction.Length < tol:
            continue
        plane = rg.Plane(line.From, direction)
        xform = rg.Transform.PlaneToPlane(rg.Plane.WorldXY, plane)
        profile   = profile_curve.DuplicateCurve()
        start_crv = profile_curve.DuplicateCurve()
        end_crv   = profile_curve.DuplicateCurve()
        move_end  = rg.Transform.Translation(direction)
        end_crv.Transform(move_end)
        profile.Transform(xform)
        start_crv.Transform(xform)
        end_crv.Transform(xform)
        try:
            side_srf  = rg.Surface.CreateExtrusion(profile, direction)
            side_brep = side_srf.ToBrep()
            start_caps = rg.Brep.CreatePlanarBreps([start_crv], tol)
            end_caps   = rg.Brep.CreatePlanarBreps([end_crv],   tol)
            parts = [side_brep]
            if start_caps: parts += list(start_caps)
            if end_caps:   parts += list(end_caps)
            joined = rg.Brep.JoinBreps(parts, tol)
            if joined and len(joined) > 0:
                b = joined[0]
                if cap:
                    try:
                        capped = b.CapPlanarHoles(tol)
                        if capped: b = capped
                    except: pass
                breps.append(b)
                directions.append(direction)
            for p in parts: p.Dispose()
        except: pass
        finally:
            profile.Dispose()
            start_crv.Dispose()
            end_crv.Dispose()
    return breps, directions


# ── V2 Boolean Joint System  (Modes 1 + 2) ───────────────────────────────────

def apply_interlocking_joints(breps, directions, profile_size, max_joints, tol):
    working     = [b.DuplicateBrep() for b in breps]
    n           = len(breps)
    joint_count = 0
    fail_count  = 0
    processed   = 0
    for i in range(n):
        if processed >= max_joints: break
        for j in range(i + 1, n):
            if processed >= max_joints: break
            di = directions[i]; dj = directions[j]
            li = di.Length; lj = dj.Length
            if li < 1e-6 or lj < 1e-6: continue
            cos_angle = abs(di * dj) / (li * lj)
            if cos_angle > 0.94: continue
            try:
                overlap = rg.Brep.CreateBooleanIntersection([working[i]], [working[j]], tol)
                if not overlap or len(overlap) == 0:
                    processed += 1; fail_count += 1; continue
                vol = overlap[0].GetVolume()
                if vol < tol or vol > profile_size ** 3 * 2:
                    for o in overlap: o.Dispose()
                    processed += 1; fail_count += 1; continue
                cut_idx = i if joint_count % 2 == 0 else j
                result = rg.Brep.CreateBooleanDifference([working[cut_idx]], overlap, tol)
                for o in overlap: o.Dispose()
                if result and len(result) > 0:
                    old = working[cut_idx]
                    working[cut_idx] = result[0]
                    for r in result[1:]: r.Dispose()
                    old.Dispose()
                    processed += 1; joint_count += 1
                else:
                    processed += 1; fail_count += 1
            except:
                processed += 1; fail_count += 1
    return working, joint_count, fail_count


# ── Orthogonal Grid System  (Mode 0 — analytical joints) ─────────────────────

def _attractor_weight(pt, attr_pt, radius, min_density):
    d = pt.DistanceTo(attr_pt)
    if radius < 1e-6:
        return 1.0
    t = min(d / radius, 1.0)
    return min_density + (1.0 - min_density) * math.exp(-3.0 * t * t)


def _trim_line(line, ratio):
    """Trim a line to *ratio* of its length, keeping centre fixed."""
    if ratio >= 1.0:
        return line
    fx, fy, fz = line.From.X, line.From.Y, line.From.Z
    tx, ty, tz = line.To.X,   line.To.Y,   line.To.Z
    mx = (fx + tx) * 0.5;  my = (fy + ty) * 0.5;  mz = (fz + tz) * 0.5
    r2 = ratio * 0.5
    return rg.Line(
        rg.Point3d(mx + (fx - mx) * ratio / (ratio if ratio > 0 else 1),
                   my + (fy - my) * ratio / (ratio if ratio > 0 else 1),
                   mz + (fz - mz) * ratio / (ratio if ratio > 0 else 1)),
        rg.Point3d(mx + (tx - mx) * ratio / (ratio if ratio > 0 else 1),
                   my + (ty - my) * ratio / (ratio if ratio > 0 else 1),
                   mz + (tz - mz) * ratio / (ratio if ratio > 0 else 1)))


def _trim_line_centre(line, ratio):
    """Centre-trim a line to *ratio* of its full length."""
    if ratio >= 1.0:
        return line
    fx, fy, fz = line.From.X, line.From.Y, line.From.Z
    tx, ty, tz = line.To.X,   line.To.Y,   line.To.Z
    mx = (fx + tx) * 0.5;  my = (fy + ty) * 0.5;  mz = (fz + tz) * 0.5
    half = ratio * 0.5
    dx = (tx - fx) * half;  dy = (ty - fy) * half;  dz = (tz - fz) * half
    return rg.Line(rg.Point3d(mx - dx, my - dy, mz - dz),
                   rg.Point3d(mx + dx, my + dy, mz + dz))


def generate_ortho_beams_single(params, seed_rng):
    """
    Bernoulli sampling — seed always changes which beams are included.
    Supports random_length: each beam trimmed to a random fraction of its span.
    """
    w, h, d  = params['width'], params['height'], params['depth']
    u, v, ww = params['u_div'], params['v_div'], params['w_div']
    hw, hh, hd = w / 2.0, h / 2.0, d / 2.0

    jt     = params.get('grid_jitter', 0) / 100.0
    cell_w = w / float(u) if u > 0 else w
    cell_h = h / float(v) if v > 0 else h
    cell_d = d / float(ww) if ww > 0 else d

    xs_e = [-hw + w * i / float(u) for i in range(u + 1)]
    ys_e = [-hh + h * j / float(v) for j in range(v + 1)]
    zs_e = [-hd + d * k / float(ww) for k in range(ww + 1)]

    xs = [max(-hw, min(hw, x + seed_rng.uniform(-0.5, 0.5) * cell_w * jt)) for x in xs_e]
    ys = [max(-hh, min(hh, y + seed_rng.uniform(-0.5, 0.5) * cell_h * jt)) for y in ys_e]
    zs = [max(-hd, min(hd, z + seed_rng.uniform(-0.5, 0.5) * cell_d * jt)) for z in zs_e]

    use_att  = params['enable_attractor']
    attr_pt  = rg.Point3d(params['attr_x'], params['attr_y'], params['attr_z'])
    attr_r   = params['attr_radius']
    attr_min = params['attr_min_density'] / 100.0
    hz_scale = 1.0 - params['hz_bias'] / 100.0
    num_beams = max(1, int(params.get('num_beams', 30)))

    rand_len  = params.get('random_length', False)
    min_r     = params.get('min_length_pct', 50) / 100.0

    beams = []

    def _add_beam(axis, a, b, line):
        if rand_len:
            ratio = seed_rng.uniform(min_r, 1.0)
            line  = _trim_line_centre(line, ratio)
        beams.append({'axis': axis, 'a': a, 'b': b, 'line': line, 'brep_idx': -1})

    if params['use_x']:
        for y in ys:
            for z in zs:
                mid  = rg.Point3d(0, y, z)
                prob = _attractor_weight(mid, attr_pt, attr_r, attr_min) if use_att else 1.0
                if seed_rng.random() < prob:
                    _add_beam('X', y, z,
                              rg.Line(rg.Point3d(-hw, y, z), rg.Point3d(hw, y, z)))
    if params['use_y']:
        for x in xs:
            for z in zs:
                mid  = rg.Point3d(x, 0, z)
                prob = _attractor_weight(mid, attr_pt, attr_r, attr_min) if use_att else 1.0
                if seed_rng.random() < prob:
                    _add_beam('Y', x, z,
                              rg.Line(rg.Point3d(x, -hh, z), rg.Point3d(x, hh, z)))
    if params['use_z']:
        for x in xs:
            for y in ys:
                mid  = rg.Point3d(x, y, 0)
                prob = _attractor_weight(mid, attr_pt, attr_r, attr_min) if use_att else 1.0
                prob *= hz_scale
                if seed_rng.random() < prob:
                    _add_beam('Z', x, y,
                              rg.Line(rg.Point3d(x, y, -hd), rg.Point3d(x, y, hd)))

    if len(beams) > num_beams:
        seed_rng.shuffle(beams)
        beams = beams[:num_beams]
    return beams


def tile_beams(single_beams, w, h, d, tile_x, tile_y, tile_z):
    tiled    = []
    offset_x = -w * (tile_x - 1) / 2.0
    offset_y = -h * (tile_y - 1) / 2.0
    offset_z = -d * (tile_z - 1) / 2.0
    for ix in range(tile_x):
        for iy in range(tile_y):
            for iz in range(tile_z):
                dx = offset_x + ix * w
                dy = offset_y + iy * h
                dz = offset_z + iz * d
                vec = rg.Vector3d(dx, dy, dz)
                for b in single_beams:
                    new_line = rg.Line(b['line'].From + vec, b['line'].To + vec)
                    if b['axis'] == 'X':   na, nb = b['a'] + dy, b['b'] + dz
                    elif b['axis'] == 'Y': na, nb = b['a'] + dx, b['b'] + dz
                    else:                  na, nb = b['a'] + dx, b['b'] + dy
                    tiled.append({'axis': b['axis'], 'a': na, 'b': nb,
                                  'line': new_line, 'brep_idx': -1})
    return tiled


def deduplicate_beams(beams):
    seen, unique = set(), []
    for b in beams:
        key = (b['axis'], round(b['a'], 5), round(b['b'], 5))
        if key not in seen:
            seen.add(key)
            unique.append(b)
    return unique


def beams_to_lines(beams):
    return [b['line'] for b in beams]


def _pt_in_span(coord, lo, hi, tol=1e-4):
    return lo - tol <= coord <= hi + tol


def _crossing_XY(bx, by):
    if abs(bx['b'] - by['b']) > 1e-4: return None
    cx = by['a']; cy = bx['a']; cz = bx['b']
    xl = min(bx['line'].From.X, bx['line'].To.X)
    xh = max(bx['line'].From.X, bx['line'].To.X)
    if not _pt_in_span(cx, xl, xh): return None
    yl = min(by['line'].From.Y, by['line'].To.Y)
    yh = max(by['line'].From.Y, by['line'].To.Y)
    if not _pt_in_span(cy, yl, yh): return None
    return rg.Point3d(cx, cy, cz)


def _crossing_XZ(bx, bz):
    if abs(bx['a'] - bz['b']) > 1e-4: return None
    cx = bz['a']; cy = bx['a']; cz = bx['b']
    xl = min(bx['line'].From.X, bx['line'].To.X)
    xh = max(bx['line'].From.X, bx['line'].To.X)
    if not _pt_in_span(cx, xl, xh): return None
    zl = min(bz['line'].From.Z, bz['line'].To.Z)
    zh = max(bz['line'].From.Z, bz['line'].To.Z)
    if not _pt_in_span(cz, zl, zh): return None
    return rg.Point3d(cx, cy, cz)


def _crossing_YZ(by, bz):
    if abs(by['a'] - bz['a']) > 1e-4: return None
    cx = by['a']; cy = bz['b']; cz = by['b']
    yl = min(by['line'].From.Y, by['line'].To.Y)
    yh = max(by['line'].From.Y, by['line'].To.Y)
    if not _pt_in_span(cy, yl, yh): return None
    zl = min(bz['line'].From.Z, bz['line'].To.Z)
    zh = max(bz['line'].From.Z, bz['line'].To.Z)
    if not _pt_in_span(cz, zl, zh): return None
    return rg.Point3d(cx, cy, cz)


def _make_cutter(cross_pt, beam_axis, pair_type, profile_size):
    hp = profile_size / 2.0
    cx, cy, cz = cross_pt.X, cross_pt.Y, cross_pt.Z
    if pair_type == 'XY':
        if beam_axis == 'X':
            bb = rg.BoundingBox(rg.Point3d(cx-hp, cy-hp, cz),    rg.Point3d(cx+hp, cy+hp, cz+hp))
        else:
            bb = rg.BoundingBox(rg.Point3d(cx-hp, cy-hp, cz-hp), rg.Point3d(cx+hp, cy+hp, cz))
    elif pair_type == 'XZ':
        if beam_axis == 'X':
            bb = rg.BoundingBox(rg.Point3d(cx-hp, cy,    cz-hp), rg.Point3d(cx+hp, cy+hp, cz+hp))
        else:
            bb = rg.BoundingBox(rg.Point3d(cx-hp, cy-hp, cz-hp), rg.Point3d(cx+hp, cy,    cz+hp))
    elif pair_type == 'YZ':
        if beam_axis == 'Y':
            bb = rg.BoundingBox(rg.Point3d(cx,    cy-hp, cz-hp), rg.Point3d(cx+hp, cy+hp, cz+hp))
        else:
            bb = rg.BoundingBox(rg.Point3d(cx-hp, cy-hp, cz-hp), rg.Point3d(cx,    cy+hp, cz+hp))
    else:
        return None
    return rg.Brep.CreateFromBox(bb)


def apply_analytical_joints(breps, beams, profile_size, max_joints, tol):
    working     = [b.DuplicateBrep() for b in breps]
    n           = len(beams)
    joint_count = 0
    fail_count  = 0
    processed   = 0
    for i in range(n):
        if processed >= max_joints: break
        bi = beams[i]
        if bi['brep_idx'] < 0: continue
        for j in range(i + 1, n):
            if processed >= max_joints: break
            bj = beams[j]
            if bj['brep_idx'] < 0: continue
            ai, aj = bi['axis'], bj['axis']
            if ai == aj: continue
            pair = ''.join(sorted([ai, aj]))
            if pair == 'XY':
                bx = bi if ai == 'X' else bj; by = bj if ai == 'X' else bi
                pt = _crossing_XY(bx, by)
            elif pair == 'XZ':
                bx = bi if ai == 'X' else bj; bz = bj if ai == 'X' else bi
                pt = _crossing_XZ(bx, bz)
            else:
                by = bi if ai == 'Y' else bj; bz = bj if ai == 'Y' else bi
                pt = _crossing_YZ(by, bz)
            if pt is None: continue
            ci = _make_cutter(pt, ai, pair, profile_size)
            cj = _make_cutter(pt, aj, pair, profile_size)
            bi_idx = bi['brep_idx']; bj_idx = bj['brep_idx']
            success = False
            if ci:
                try:
                    res = rg.Brep.CreateBooleanDifference([working[bi_idx]], [ci], tol)
                    if res and len(res) > 0:
                        old = working[bi_idx]; working[bi_idx] = res[0]
                        for e in res[1:]: e.Dispose()
                        old.Dispose(); success = True
                except: pass
                ci.Dispose()
            if cj:
                try:
                    res = rg.Brep.CreateBooleanDifference([working[bj_idx]], [cj], tol)
                    if res and len(res) > 0:
                        old = working[bj_idx]; working[bj_idx] = res[0]
                        for e in res[1:]: e.Dispose()
                        old.Dispose(); success = True
                except: pass
                cj.Dispose()
            processed += 1
            if success: joint_count += 1
            else:       fail_count  += 1
    return working, joint_count, fail_count


# =============================================================================
# PLACEMENT FILTER  (Mode 0 face-based beam placement)
# =============================================================================

def _faces_for_placement_mode(placement_mode, wall_face, tile_x, tile_y, tile_z):
    all6   = ['+X', '-X', '+Y', '-Y', '+Z', '-Z']
    facade = ['+X', '-X', '+Y', '-Y']
    wall_map = {0: '+X', 1: '-X', 2: '+Y', 3: '-Y'}
    if   placement_mode == 0: return []
    elif placement_mode == 1: return all6
    elif placement_mode == 2: return facade
    elif placement_mode == 3: return [wall_map.get(wall_face, '+X')]
    elif placement_mode == 4: return ['+Z']
    elif placement_mode == 5: return ['-Z']
    elif placement_mode == 6:
        shared = []
        if tile_x > 1: shared += ['+X', '-X']
        if tile_y > 1: shared += ['+Y', '-Y']
        if tile_z > 1: shared += ['+Z', '-Z']
        return shared if shared else all6
    return []


def generate_face_beams(params, face_list, seed_rng):
    """Beams lying ON specific box faces — attractor + jitter + random_length apply."""
    w, h, d  = params['width'], params['height'], params['depth']
    u, v, ww = params['u_div'], params['v_div'], params['w_div']
    hw, hh, hd = w / 2.0, h / 2.0, d / 2.0
    jt     = params.get('grid_jitter', 0) / 100.0
    cell_w = w / float(u)  if u  > 0 else w
    cell_h = h / float(v)  if v  > 0 else h
    cell_d = d / float(ww) if ww > 0 else d
    use_att  = params['enable_attractor']
    attr_pt  = rg.Point3d(params['attr_x'], params['attr_y'], params['attr_z'])
    attr_r   = params['attr_radius']
    attr_min = params['attr_min_density'] / 100.0
    hz_scale = 1.0 - params['hz_bias'] / 100.0
    num_beams = max(1, int(params.get('num_beams', 30)))
    rand_len  = params.get('random_length', False)
    min_r     = params.get('min_length_pct', 50) / 100.0

    xs_e = [-hw + w * i / float(u)  for i in range(u + 1)]
    ys_e = [-hh + h * j / float(v)  for j in range(v + 1)]
    zs_e = [-hd + d * k / float(ww) for k in range(ww + 1)]
    xs = [max(-hw, min(hw, x + seed_rng.uniform(-0.5, 0.5) * cell_w * jt)) for x in xs_e]
    ys = [max(-hh, min(hh, y + seed_rng.uniform(-0.5, 0.5) * cell_h * jt)) for y in ys_e]
    zs = [max(-hd, min(hd, z + seed_rng.uniform(-0.5, 0.5) * cell_d * jt)) for z in zs_e]

    beams = []

    def _try(axis, a, b, line, wt=1.0):
        mid = rg.Point3d((line.From.X+line.To.X)*0.5,
                         (line.From.Y+line.To.Y)*0.5,
                         (line.From.Z+line.To.Z)*0.5)
        prob = (_attractor_weight(mid, attr_pt, attr_r, attr_min) if use_att else 1.0) * wt
        if seed_rng.random() < prob:
            ln = _trim_line_centre(line, seed_rng.uniform(min_r, 1.0)) if rand_len else line
            beams.append({'axis': axis, 'a': a, 'b': b, 'line': ln, 'brep_idx': -1})

    for face in face_list:
        if face == '+X':
            if params['use_y']:
                for z in zs: _try('Y', hw,  z, rg.Line(rg.Point3d(hw,-hh,z), rg.Point3d(hw,hh,z)))
            if params['use_z']:
                for y in ys: _try('Z', hw,  y, rg.Line(rg.Point3d(hw,y,-hd), rg.Point3d(hw,y,hd)), hz_scale)
        elif face == '-X':
            if params['use_y']:
                for z in zs: _try('Y', -hw, z, rg.Line(rg.Point3d(-hw,-hh,z), rg.Point3d(-hw,hh,z)))
            if params['use_z']:
                for y in ys: _try('Z', -hw, y, rg.Line(rg.Point3d(-hw,y,-hd), rg.Point3d(-hw,y,hd)), hz_scale)
        elif face == '+Y':
            if params['use_x']:
                for z in zs: _try('X', hh,  z, rg.Line(rg.Point3d(-hw,hh,z), rg.Point3d(hw,hh,z)))
            if params['use_z']:
                for x in xs: _try('Z', x,  hh, rg.Line(rg.Point3d(x,hh,-hd), rg.Point3d(x,hh,hd)), hz_scale)
        elif face == '-Y':
            if params['use_x']:
                for z in zs: _try('X', -hh, z, rg.Line(rg.Point3d(-hw,-hh,z), rg.Point3d(hw,-hh,z)))
            if params['use_z']:
                for x in xs: _try('Z', x, -hh, rg.Line(rg.Point3d(x,-hh,-hd), rg.Point3d(x,-hh,hd)), hz_scale)
        elif face == '+Z':
            if params['use_x']:
                for y in ys: _try('X', y,  hd, rg.Line(rg.Point3d(-hw,y,hd), rg.Point3d(hw,y,hd)))
            if params['use_y']:
                for x in xs: _try('Y', x,  hd, rg.Line(rg.Point3d(x,-hh,hd), rg.Point3d(x,hh,hd)))
        elif face == '-Z':
            if params['use_x']:
                for y in ys: _try('X', y, -hd, rg.Line(rg.Point3d(-hw,y,-hd), rg.Point3d(hw,y,-hd)))
            if params['use_y']:
                for x in xs: _try('Y', x, -hd, rg.Line(rg.Point3d(x,-hh,-hd), rg.Point3d(x,hh,-hd)))

    if len(beams) > num_beams:
        seed_rng.shuffle(beams)
        beams = beams[:num_beams]
    return beams


# =============================================================================
# NOISE ENGINE  (Mode 4)
# =============================================================================

def _vnoise(ix, iy, iz, seed_val=0):
    """Deterministic hash-based value noise → float [0, 1]."""
    n = (ix * 1619 + iy * 31337 + iz * 6971 + seed_val * 1013) % 1000000007
    n = (n * 1664525 + 1013904223) % 2147483647
    return abs(n) / 2147483647.0


def _fade_n(t):
    return t * t * (3.0 - 2.0 * t)


def _lerp_n(a, b, t):
    return a + (b - a) * t


def value_noise_3d(x, y, z, seed_val=0):
    ix = int(math.floor(x)); iy = int(math.floor(y)); iz = int(math.floor(z))
    fx = x - ix; fy = y - iy; fz = z - iz
    ux = _fade_n(fx); uy = _fade_n(fy); uz = _fade_n(fz)
    v000 = _vnoise(ix,   iy,   iz,   seed_val)
    v100 = _vnoise(ix+1, iy,   iz,   seed_val)
    v010 = _vnoise(ix,   iy+1, iz,   seed_val)
    v110 = _vnoise(ix+1, iy+1, iz,   seed_val)
    v001 = _vnoise(ix,   iy,   iz+1, seed_val)
    v101 = _vnoise(ix+1, iy,   iz+1, seed_val)
    v011 = _vnoise(ix,   iy+1, iz+1, seed_val)
    v111 = _vnoise(ix+1, iy+1, iz+1, seed_val)
    x00 = _lerp_n(v000, v100, ux); x10 = _lerp_n(v010, v110, ux)
    x01 = _lerp_n(v001, v101, ux); x11 = _lerp_n(v011, v111, ux)
    xy0 = _lerp_n(x00, x10, uy);   xy1 = _lerp_n(x01, x11, uy)
    return _lerp_n(xy0, xy1, uz)


def fbm_3d(x, y, z, octaves, persistence, scale, seed_val=0):
    val = 0.0; amp = 1.0; freq = scale; total = 0.0
    for _ in range(octaves):
        val   += value_noise_3d(x*freq, y*freq, z*freq, seed_val) * amp
        total += amp
        amp   *= persistence
        freq  *= 2.0
    return val / total if total > 0 else 0.0


# ── Flow Field ────────────────────────────────────────────────────────────────

def noise_flow_field(params, seed_rng):
    w, h, d = params['width'], params['height'], params['depth']
    hw, hh, hd = w/2.0, h/2.0, d/2.0
    n_ag  = max(1, int(params.get('noise_num_agents', 20)))
    steps = max(1, int(params.get('noise_steps', 100)))
    ss    = max(0.01, float(params.get('noise_step_size', 1.0)))
    scale = max(0.001, float(params.get('noise_scale', 0.15)))
    oct   = max(1, int(params.get('noise_octaves', 4)))
    pers  = params.get('noise_persistence', 50) / 100.0
    sv    = int(seed_rng.random() * 9999)

    polylines = []
    for _ in range(n_ag):
        x = seed_rng.uniform(-hw, hw)
        y = seed_rng.uniform(-hh, hh)
        z = seed_rng.uniform(-hd, hd)
        pts = [rg.Point3d(x, y, z)]
        for _s in range(steps):
            az = fbm_3d(x*scale,       y*scale,       z*scale,       oct, pers, 1.0, sv) * 2*math.pi*2 - math.pi
            el = (fbm_3d(x*scale+5.2,  y*scale+1.3,   z*scale+0.7,   oct, pers, 1.0, sv) - 0.5) * math.pi * 0.5
            cos_el = math.cos(el)
            dx = math.cos(az) * cos_el * ss
            dy = math.sin(az) * cos_el * ss
            dz = math.sin(el) * ss
            nx = x + dx; ny = y + dy; nz = z + dz
            if nx < -hw or nx > hw: dx = -dx; nx = x + dx
            if ny < -hh or ny > hh: dy = -dy; ny = y + dy
            if nz < -hd or nz > hd: dz = -dz; nz = z + dz
            x = max(-hw, min(hw, nx))
            y = max(-hh, min(hh, ny))
            z = max(-hd, min(hd, nz))
            pts.append(rg.Point3d(x, y, z))
        if len(pts) >= 2:
            polylines.append(pts)
    return polylines


# ── Stigmergy ─────────────────────────────────────────────────────────────────

def noise_stigmergy(params, seed_rng):
    w, h, d = params['width'], params['height'], params['depth']
    hw, hh, hd = w/2.0, h/2.0, d/2.0
    n_ag    = max(1, int(params.get('stig_num_agents', 15)))
    steps   = max(1, int(params.get('stig_steps', 150)))
    ss      = max(0.01, float(params.get('stig_step_size', 1.0)))
    evap    = max(0.001, params.get('stig_evap', 20) / 100.0)
    deposit = max(0.0, float(params.get('stig_deposit', 1.0)))
    sense_d = max(0.1, float(params.get('stig_sense_dist', 3.0)))

    phero = {}

    def gk(x, y, z):
        return (int(math.floor(x/ss)), int(math.floor(y/ss)), int(math.floor(z/ss)))

    # init ants: [x, y, z, vx, vy, vz, trail]
    ants = []
    for _ in range(n_ag):
        x = seed_rng.uniform(-hw*0.9, hw*0.9)
        y = seed_rng.uniform(-hh*0.9, hh*0.9)
        z = seed_rng.uniform(-hd*0.9, hd*0.9)
        az = seed_rng.uniform(0, 2*math.pi)
        el = seed_rng.uniform(-math.pi/4, math.pi/4)
        ants.append([x, y, z,
                     math.cos(az)*math.cos(el),
                     math.sin(az)*math.cos(el),
                     math.sin(el),
                     [rg.Point3d(x, y, z)]])

    for _step in range(steps):
        for ant in ants:
            x, y, z, vx, vy, vz, trail = ant[0],ant[1],ant[2],ant[3],ant[4],ant[5],ant[6]
            best = -1.0; bvx, bvy, bvz = vx, vy, vz
            for _ in range(8):
                naz = seed_rng.uniform(-math.pi/3, math.pi/3)
                nel = seed_rng.uniform(-math.pi/6, math.pi/6)
                sx = vx + math.cos(naz)*abs(math.sin(nel))
                sy = vy + math.sin(naz)*abs(math.sin(nel))
                sz = vz + math.cos(nel) * 0.3
                ln = math.sqrt(sx*sx + sy*sy + sz*sz)
                if ln > 1e-6: sx/=ln; sy/=ln; sz/=ln
                pk = gk(x+sx*sense_d, y+sy*sense_d, z+sz*sense_d)
                pv = phero.get(pk, 0.0)
                if pv > best: best = pv; bvx,bvy,bvz = sx,sy,sz
            mix = 0.5 if best > 0 else 0.0
            nvx = vx*(1-mix) + bvx*mix + seed_rng.uniform(-0.15, 0.15)
            nvy = vy*(1-mix) + bvy*mix + seed_rng.uniform(-0.15, 0.15)
            nvz = vz*(1-mix) + bvz*mix + seed_rng.uniform(-0.08, 0.08)
            ln = math.sqrt(nvx*nvx + nvy*nvy + nvz*nvz)
            if ln > 1e-6: nvx/=ln; nvy/=ln; nvz/=ln
            nx = x+nvx*ss; ny = y+nvy*ss; nz = z+nvz*ss
            if nx < -hw or nx > hw: nvx=-nvx; nx=x+nvx*ss
            if ny < -hh or ny > hh: nvy=-nvy; ny=y+nvy*ss
            if nz < -hd or nz > hd: nvz=-nvz; nz=z+nvz*ss
            nx=max(-hw,min(hw,nx)); ny=max(-hh,min(hh,ny)); nz=max(-hd,min(hd,nz))
            k = gk(nx,ny,nz)
            phero[k] = phero.get(k, 0.0) + deposit
            ant[0]=nx; ant[1]=ny; ant[2]=nz
            ant[3]=nvx; ant[4]=nvy; ant[5]=nvz
            trail.append(rg.Point3d(nx,ny,nz))

        for k in list(phero.keys()):
            phero[k] *= (1.0 - evap)
            if phero[k] < 0.001: del phero[k]

    return [ant[6] for ant in ants if len(ant[6]) >= 2]


# ── Boids ─────────────────────────────────────────────────────────────────────

def noise_boids(params, seed_rng):
    w, h, d = params['width'], params['height'], params['depth']
    hw, hh, hd = w/2.0, h/2.0, d/2.0
    nb     = max(1, int(params.get('boids_num', 20)))
    steps  = max(1, int(params.get('boids_steps', 100)))
    ss     = max(0.01, float(params.get('boids_step_size', 1.0)))
    sep_d  = max(0.1, float(params.get('boids_sep_dist', 4.0)))
    sep_w  = float(params.get('boids_sep_w', 1.5))
    ali_w  = float(params.get('boids_align_w', 1.0))
    coh_w  = float(params.get('boids_cohesion_w', 1.0))
    max_sp = max(0.1, float(params.get('boids_max_speed', 2.0)))

    boids = []
    for _ in range(nb):
        x = seed_rng.uniform(-hw*0.8, hw*0.8)
        y = seed_rng.uniform(-hh*0.8, hh*0.8)
        z = seed_rng.uniform(-hd*0.8, hd*0.8)
        sp = max_sp * 0.5
        az = seed_rng.uniform(0, 2*math.pi)
        vx = math.cos(az)*sp; vy = math.sin(az)*sp
        vz = seed_rng.uniform(-sp*0.2, sp*0.2)
        boids.append([x, y, z, vx, vy, vz, [rg.Point3d(x,y,z)]])

    for _step in range(steps):
        nv = []
        for i, b in enumerate(boids):
            x,y,z,vx,vy,vz = b[0],b[1],b[2],b[3],b[4],b[5]
            sfx=sfy=sfz=0.0; alx=aly=alz=0.0; cx=cy=cz=0.0; nn=0
            for j, o in enumerate(boids):
                if i==j: continue
                dx=o[0]-x; dy=o[1]-y; dz=o[2]-z
                dist=math.sqrt(dx*dx+dy*dy+dz*dz)
                if dist < 1e-6: continue
                if dist < sep_d:
                    sfx -= dx/dist/dist; sfy -= dy/dist/dist; sfz -= dz/dist/dist
                if dist < sep_d*3:
                    alx+=o[3]; aly+=o[4]; alz+=o[5]
                    cx+=o[0]; cy+=o[1]; cz+=o[2]; nn+=1
            nvx=vx+sfx*sep_w; nvy=vy+sfy*sep_w; nvz=vz+sfz*sep_w
            if nn > 0:
                nvx+=(alx/nn-vx)*ali_w*0.1; nvy+=(aly/nn-vy)*ali_w*0.1; nvz+=(alz/nn-vz)*ali_w*0.1
                nvx+=(cx/nn-x)*coh_w*0.01;  nvy+=(cy/nn-y)*coh_w*0.01;  nvz+=(cz/nn-z)*coh_w*0.01
            sp=math.sqrt(nvx*nvx+nvy*nvy+nvz*nvz)
            if sp > max_sp and sp > 1e-6:
                f=max_sp/sp; nvx*=f; nvy*=f; nvz*=f
            elif sp < 1e-6:
                nvx=seed_rng.uniform(-0.1,0.1); nvy=seed_rng.uniform(-0.1,0.1); nvz=0.0
            nv.append((nvx,nvy,nvz))

        for i, b in enumerate(boids):
            nvx,nvy,nvz = nv[i]
            nx=b[0]+nvx*ss; ny=b[1]+nvy*ss; nz=b[2]+nvz*ss
            if nx<-hw or nx>hw: nvx=-nvx; nx=b[0]+nvx*ss
            if ny<-hh or ny>hh: nvy=-nvy; ny=b[1]+nvy*ss
            if nz<-hd or nz>hd: nvz=-nvz; nz=b[2]+nvz*ss
            nx=max(-hw,min(hw,nx)); ny=max(-hh,min(hh,ny)); nz=max(-hd,min(hd,nz))
            b[0]=nx; b[1]=ny; b[2]=nz; b[3]=nvx; b[4]=nvy; b[5]=nvz
            b[6].append(rg.Point3d(nx,ny,nz))

    return [b[6] for b in boids if len(b[6]) >= 2]


# ── Reaction-Diffusion (Gray-Scott on XY face) ───────────────────────────────

def noise_reaction_diffusion(params, seed_rng):
    """
    Gray-Scott reaction-diffusion on a 2D grid mapped to the box XY face.
    Returns line segments tracing the pattern boundary as polyline pairs.
    """
    w, h, d = params['width'], params['height'], params['depth']
    hw, hh  = w/2.0, h/2.0
    feed    = float(params.get('rd_feed', 0.055))
    kill    = float(params.get('rd_kill', 0.062))
    steps   = max(50, int(params.get('rd_steps', 500)))
    init    = int(params.get('rd_init', 0))
    N       = 24   # grid size (kept small for performance)

    cell_x = w / float(N)
    cell_y = h / float(N)
    dU = 0.2097; dV = 0.105; dt = 1.0

    # Flat arrays: index = i*N + j
    size2 = N * N
    U = [1.0] * size2
    V = [0.0] * size2

    def idx(i, j): return (i % N) * N + (j % N)

    # Seed initial activator
    if init == 0:  # Centre
        c = N // 2
        for ii in range(c-3, c+4):
            for jj in range(c-3, c+4):
                if 0 <= ii < N and 0 <= jj < N:
                    U[ii*N+jj] = 0.5 + seed_rng.uniform(-0.05, 0.05)
                    V[ii*N+jj] = 0.25 + seed_rng.uniform(-0.05, 0.05)
    elif init == 1:  # Random dots
        for _ in range(max(3, N//4)):
            ii = seed_rng.randint(0, N-1); jj = seed_rng.randint(0, N-1)
            r  = seed_rng.randint(1, 3)
            for di in range(-r, r+1):
                for dj in range(-r, r+1):
                    ni = ii+di; nj = jj+dj
                    if 0 <= ni < N and 0 <= nj < N:
                        U[ni*N+nj] = 0.5; V[ni*N+nj] = 0.25
    else:  # Edges
        for i in range(N):
            for e in [0, 1, N-2, N-1]:
                U[i*N+e] = 0.5; V[i*N+e] = 0.25
                U[e*N+i] = 0.5; V[e*N+i] = 0.25

    nU = U[:]
    nV = V[:]

    for _s in range(steps):
        for i in range(N):
            for j in range(N):
                im = (i-1) % N; ip = (i+1) % N
                jm = (j-1) % N; jp = (j+1) % N
                u = U[i*N+j]; v = V[i*N+j]
                lapU = U[im*N+j]+U[ip*N+j]+U[i*N+jm]+U[i*N+jp] - 4*u
                lapV = V[im*N+j]+V[ip*N+j]+V[i*N+jm]+V[i*N+jp] - 4*v
                uvv  = u*v*v
                nU[i*N+j] = max(0.0, min(1.0, u + dt*(dU*lapU - uvv + feed*(1-u))))
                nV[i*N+j] = max(0.0, min(1.0, v + dt*(dV*lapV + uvv - (feed+kill)*v)))
        U, nU = nU, U
        V, nV = nV, V

    # Extract boundary segments: where V crosses 0.2
    threshold = 0.2
    polylines = []
    z_val = 0.0  # place pattern at z=0 (middle of box depth)
    for i in range(N):
        for j in range(N):
            va = V[i*N+j]
            # horizontal edge (right neighbour)
            if j+1 < N:
                vb = V[i*N+j+1]
                if (va < threshold) != (vb < threshold):
                    t  = (threshold - va) / (vb - va + 1e-12)
                    xc = -hw + (j + t) * cell_x
                    yc = -hh + i * cell_y + cell_y * 0.5
                    polylines.append([rg.Point3d(xc, yc - cell_y*0.4, z_val),
                                       rg.Point3d(xc, yc + cell_y*0.4, z_val)])
            # vertical edge (bottom neighbour)
            if i+1 < N:
                vb = V[(i+1)*N+j]
                if (va < threshold) != (vb < threshold):
                    t  = (threshold - va) / (vb - va + 1e-12)
                    yc = -hh + (i + t) * cell_y
                    xc = -hw + j * cell_x + cell_x * 0.5
                    polylines.append([rg.Point3d(xc - cell_x*0.4, yc, z_val),
                                       rg.Point3d(xc + cell_x*0.4, yc, z_val)])

    return polylines


# =============================================================================
# PIPE FACADE ENGINE  (Mode 3 — unchanged from V6)
# =============================================================================

def _pipe_brep_to_mesh(brep):
    mp = rg.MeshingParameters.FastRenderMesh
    meshes = rg.Mesh.CreateFromBrep(brep, mp)
    brep.Dispose()
    if not meshes: return None
    m = rg.Mesh()
    for mi in meshes: m.Append(mi)
    m.Weld(math.pi); m.Compact()
    return m


def make_pipe_segment_mesh(p1, p2, radius, tol, ang_tol):
    direction = rg.Vector3d(p2 - p1)
    if direction.Length < tol: return None
    plane  = rg.Plane(p1, direction)
    circle = rg.Circle(plane, radius)
    crv    = circle.ToNurbsCurve()
    end_crv = crv.DuplicateCurve()
    end_crv.Transform(rg.Transform.Translation(direction))
    try:
        side   = rg.Surface.CreateExtrusion(crv, direction)
        if side is None: crv.Dispose(); end_crv.Dispose(); return None
        s_brep = side.ToBrep()
        caps_s = rg.Brep.CreatePlanarBreps([crv],     tol) or []
        caps_e = rg.Brep.CreatePlanarBreps([end_crv], tol) or []
        parts  = [s_brep] + list(caps_s) + list(caps_e)
        joined = rg.Brep.JoinBreps(parts, tol)
        for p in parts: p.Dispose()
        if not joined or not joined[0]: crv.Dispose(); end_crv.Dispose(); return None
        return _pipe_brep_to_mesh(joined[0])
    except: return None
    finally: crv.Dispose(); end_crv.Dispose()


def make_elbow_mesh(pt, radius):
    thickness = radius * 0.6; collar_r = radius * 1.35
    plane = rg.Plane(rg.Point3d(pt.X, pt.Y, pt.Z - thickness*0.5), rg.Vector3d.ZAxis)
    circle = rg.Circle(plane, collar_r)
    crv = circle.ToNurbsCurve()
    direction = rg.Vector3d(0, 0, thickness)
    end_crv = crv.DuplicateCurve()
    end_crv.Transform(rg.Transform.Translation(direction))
    try:
        side = rg.Surface.CreateExtrusion(crv, direction)
        if side is None: crv.Dispose(); end_crv.Dispose(); return None
        s_brep = side.ToBrep(); tol2 = 0.01
        caps_s = rg.Brep.CreatePlanarBreps([crv],     tol2) or []
        caps_e = rg.Brep.CreatePlanarBreps([end_crv], tol2) or []
        parts  = [s_brep] + list(caps_s) + list(caps_e)
        joined = rg.Brep.JoinBreps(parts, tol2)
        for p in parts: p.Dispose()
        if not joined or not joined[0]: return None
        return _pipe_brep_to_mesh(joined[0])
    except: return None
    finally: crv.Dispose(); end_crv.Dispose()


def make_bracket_mesh(mid_pt, pipe_dir, pipe_r):
    pd = rg.Vector3d(pipe_dir); pd.Unitize()
    wall = rg.Vector3d(0, -1, 0)
    if abs(pd * wall) > 0.85: wall = rg.Vector3d(-1, 0, 0)
    lat = rg.Vector3d.CrossProduct(pd, wall); lat.Unitize()
    arm_reach = pipe_r * 2.8; plate_w = pipe_r * 1.4; plate_h = pipe_r * 0.5
    back_ctr = rg.Point3d(mid_pt.X + wall.X*(pipe_r+arm_reach),
                          mid_pt.Y + wall.Y*(pipe_r+arm_reach),
                          mid_pt.Z + wall.Z*(pipe_r+arm_reach))
    lo = rg.Point3d(back_ctr.X+lat.X*(-plate_w)+wall.X*(-plate_h*0.5),
                    back_ctr.Y+lat.Y*(-plate_w)+wall.Y*(-plate_h*0.5),
                    back_ctr.Z - pipe_r*1.2)
    hi = rg.Point3d(back_ctr.X+lat.X*(plate_w)+wall.X*(plate_h*0.5),
                    back_ctr.Y+lat.Y*(plate_w)+wall.Y*(plate_h*0.5),
                    back_ctr.Z + pipe_r*1.2)
    meshes = []
    brep = rg.Brep.CreateFromBox(rg.BoundingBox(lo, hi))
    m = _pipe_brep_to_mesh(brep)
    if m: meshes.append(m)
    for sign in (-1, 1):
        a_st = rg.Point3d(mid_pt.X+lat.X*sign*pipe_r*1.2,
                          mid_pt.Y+lat.Y*sign*pipe_r*1.2, mid_pt.Z)
        a_en = rg.Point3d(a_st.X+wall.X*arm_reach, a_st.Y+wall.Y*arm_reach, a_st.Z)
        seg = make_pipe_segment_mesh(a_st, a_en, pipe_r*0.35, 0.01, 0.01)
        if seg: meshes.append(seg)
    if not meshes: return None
    combined = rg.Mesh()
    for m in meshes: combined.Append(m); m.Dispose()
    combined.Compact(); return combined


def make_connector_mesh(p1, p2, radius, tol, ang_tol):
    return make_pipe_segment_mesh(p1, p2, radius*0.75, tol, ang_tol)


def build_pipe_facade(params, seed_rng, tol, ang_tol):
    w = params['width']; h = params['height']; d = params['depth']
    grid_x   = max(1, int(params['pipe_grid_x']))
    grid_y   = max(1, int(params['pipe_grid_y']))
    z_levels = max(1, int(params['pipe_z_levels']))
    mod_h    = d / float(z_levels)
    z_start  = -d / 2.0
    pipe_r   = params['pipe_diameter'] / 2.0
    wander   = params['pipe_wander']   / 100.0
    conn_p   = params['pipe_conn_prob'] / 100.0
    brackets = params['pipe_brackets']
    bkt_int  = max(1, int(params['pipe_bracket_int']))
    sx = w / float(grid_x + 1); sy = h / float(grid_y + 1)
    max_dx = sx * 0.46; max_dy = sy * 0.46
    x_min = -w/2.0+pipe_r; x_max = w/2.0-pipe_r
    y_min = -h/2.0+pipe_r; y_max = h/2.0-pipe_r
    stacks = {}
    for ix in range(grid_x):
        for iy in range(grid_y):
            x0 = -w/2.0 + sx*(ix+1); y0 = -h/2.0 + sy*(iy+1)
            nodes = []
            for iz in range(z_levels + 1):
                z  = z_start + iz * mod_h
                dx = seed_rng.uniform(-max_dx, max_dx) * wander
                dy = seed_rng.uniform(-max_dy, max_dy) * wander
                nodes.append(rg.Point3d(max(x_min,min(x_max,x0+dx)),
                                        max(y_min,min(y_max,y0+dy)), z))
            stacks[(ix,iy)] = nodes
    out = []
    for (ix,iy), nodes in stacks.items():
        for iz in range(z_levels):
            p1=nodes[iz]; p2=nodes[iz+1]
            seg=make_pipe_segment_mesh(p1,p2,pipe_r,tol,ang_tol)
            if seg: out.append(seg)
            if iz > 0:
                elb=make_elbow_mesh(p1,pipe_r)
                if elb: out.append(elb)
            if brackets and (iz % bkt_int == 0):
                mid=rg.Point3d((p1.X+p2.X)*0.5,(p1.Y+p2.Y)*0.5,(p1.Z+p2.Z)*0.5)
                brk=make_bracket_mesh(mid,rg.Vector3d(p2-p1),pipe_r)
                if brk: out.append(brk)
        elb=make_elbow_mesh(nodes[-1],pipe_r)
        if elb: out.append(elb)
        for nb in [(ix+1,iy),(ix,iy+1)]:
            nb_nodes=stacks.get(nb)
            if nb_nodes is None: continue
            for iz in range(z_levels+1):
                if seed_rng.random() < conn_p:
                    conn=make_connector_mesh(nodes[iz],nb_nodes[iz],pipe_r,tol,ang_tol)
                    if conn: out.append(conn)
    return out, len(stacks)


# =============================================================================
# GUIDE GEOMETRY
# =============================================================================

def create_guide_curves_tiled(params):
    w  = params['width']  * params['tile_x']
    h  = params['height'] * params['tile_y']
    d  = params['depth']  * params['tile_z']
    hw,hh,hd = w/2.0, h/2.0, d/2.0
    curves = []
    C = [rg.Point3d(-hw,-hh,-hd), rg.Point3d(hw,-hh,-hd),
         rg.Point3d( hw, hh,-hd), rg.Point3d(-hw, hh,-hd),
         rg.Point3d(-hw,-hh, hd), rg.Point3d(hw,-hh, hd),
         rg.Point3d( hw, hh, hd), rg.Point3d(-hw, hh, hd)]
    EDGES = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    for a, b in EDGES:
        curves.append(rg.Line(C[a], C[b]).ToNurbsCurve())
    u=params['tile_x']; v=params['tile_y']; ww=params['tile_z']
    for i in range(u+1):
        x = -hw + w*i/float(u)
        for j in range(v+1):
            y = -hh + h*j/float(v)
            curves.append(rg.Line(rg.Point3d(x,y,-hd), rg.Point3d(x,y,hd)).ToNurbsCurve())
        for k in range(ww+1):
            z = -hd + d*k/float(ww)
            curves.append(rg.Line(rg.Point3d(x,-hh,z), rg.Point3d(x,hh,z)).ToNurbsCurve())
    for j in range(v+1):
        y = -hh + h*j/float(v)
        for k in range(ww+1):
            z = -hd + d*k/float(ww)
            curves.append(rg.Line(rg.Point3d(-hw,y,z), rg.Point3d(hw,y,z)).ToNurbsCurve())
    return curves


# =============================================================================
# LAYER MANAGEMENT
# =============================================================================

def _get_or_create_layer(name, color, locked=False):
    if not rs.IsLayer(name): rs.AddLayer(name, color)
    idx = sc.doc.Layers.FindByFullPath(name, -1)
    if idx < 0: idx = sc.doc.Layers.FindByFullPath(name, 0)
    if locked and idx >= 0: sc.doc.Layers[idx].IsLocked = locked
    return name, idx


def ensure_tectonic_layer():
    return _get_or_create_layer(LAYER_NAME, sd.Color.FromArgb(212, 175, 55))


def ensure_guide_layer():
    return _get_or_create_layer(GUIDE_LAYER, sd.Color.FromArgb(0, 200, 220), locked=True)


def clear_previous():
    for lname in [LAYER_NAME, GUIDE_LAYER]:
        if rs.IsLayer(lname):
            rs.LayerLocked(lname, False)
            objs = rs.ObjectsByLayer(lname)
            if objs: rs.DeleteObjects(objs)


# =============================================================================
# BAKE HELPERS
# =============================================================================

def _bake_meshes(brep_list, layer_idx, group_seed, union=False):
    meshes = []
    for b in brep_list:
        if b is None: continue
        mesh = box_to_mesh(b); b.Dispose()
        if mesh is not None: meshes.append(mesh)
    if not meshes: return []
    if union:
        try:
            result = rg.Mesh.CreateBooleanUnion(meshes)
            if result and len(result) > 0:
                for m in meshes: m.Dispose()
                meshes = list(result)
        except: pass
    ids = []
    for mesh in meshes:
        oid = sc.doc.Objects.AddMesh(mesh); mesh.Dispose()
        if oid != System.Guid.Empty:
            obj = sc.doc.Objects.Find(oid)
            if obj:
                obj.Attributes.LayerIndex = layer_idx
                obj.CommitChanges()
            ids.append(oid)
    if ids:
        gname = rs.AddGroup("TECTONIC_V7_" + str(group_seed))
        if gname: rs.AddObjectsToGroup([str(g) for g in ids], gname)
    return ids


def _bake_guide(params):
    tol = sc.doc.ModelAbsoluteTolerance
    ang_tol = sc.doc.ModelAngleToleranceRadians
    _, guide_idx = ensure_guide_layer()
    r = params['guide_radius']; r_grid = r * 0.4
    curves = create_guide_curves_tiled(params)
    for ci, crv in enumerate(curves):
        radius = r if ci < 12 else r_grid
        added  = False
        try:
            pipes = rg.Brep.CreatePipe(crv, radius, False,
                                       rg.PipeCapMode.Flat, True, tol, ang_tol)
            if pipes:
                for p in pipes:
                    oid = sc.doc.Objects.AddBrep(p)
                    if oid != System.Guid.Empty:
                        obj = sc.doc.Objects.Find(oid)
                        if obj:
                            obj.Attributes.LayerIndex = guide_idx
                            obj.CommitChanges()
                    p.Dispose()
                added = True
        except: pass
        if not added:
            oid = sc.doc.Objects.AddCurve(crv)
            if oid != System.Guid.Empty:
                obj = sc.doc.Objects.Find(oid)
                if obj:
                    obj.Attributes.LayerIndex = guide_idx
                    obj.CommitChanges()
        crv.Dispose()
    g_idx = sc.doc.Layers.FindByFullPath(GUIDE_LAYER, -1)
    if g_idx >= 0: sc.doc.Layers[g_idx].IsLocked = True


# =============================================================================
# ORCHESTRATOR
# =============================================================================

def _tile_lines(single_lines, w, h, d, tile_x, tile_y, tile_z):
    off_x=-w*(tile_x-1)/2.0; off_y=-h*(tile_y-1)/2.0; off_z=-d*(tile_z-1)/2.0
    lines = []
    for ix in range(tile_x):
        for iy in range(tile_y):
            for iz in range(tile_z):
                vec = rg.Vector3d(off_x+ix*w, off_y+iy*h, off_z+iz*d)
                for ln in single_lines:
                    lines.append(rg.Line(ln.From+vec, ln.To+vec))
    return lines


def build_module(params):
    rs.EnableRedraw(False)
    undo_id = sc.doc.BeginUndoRecord("TECTONIC Generate V7")
    try:
        tol     = sc.doc.ModelAbsoluteTolerance
        ang_tol = sc.doc.ModelAngleToleranceRadians
        mode = params['gen_mode']
        w, h, d = params['width'], params['height'], params['depth']
        seed = params['seed']
        cap  = params.get('cap_geometry', True)

        profile = create_profile(params['profile_shape'],
                                 params['profile_size'],
                                 params.get('profile_size_z'))

        # ── MODE 0: ORTHOGONAL GRID ─────────────────────────────────────────
        if mode == 0:
            seed_rng = random.Random(seed)
            use_plc  = params.get('use_placement', False)
            plc_mode = params.get('placement_mode', 0)

            if use_plc and plc_mode != 0:
                face_list = _faces_for_placement_mode(
                    plc_mode, params.get('wall_face', 0),
                    params['tile_x'], params['tile_y'], params['tile_z'])
                single = generate_face_beams(params, face_list, seed_rng)
            else:
                single = generate_ortho_beams_single(params, seed_rng)

            if not single:
                raise RuntimeError("No beams generated — loosen attractor or enable more axes.")

            tiled = tile_beams(single, w, h, d,
                               params['tile_x'], params['tile_y'], params['tile_z'])
            tiled = deduplicate_beams(tiled)
            lines = beams_to_lines(tiled)
            raw_breps, _ = sweep_along_lines(profile, lines, cap)
            profile.Dispose()
            if not raw_breps:
                raise RuntimeError("Sweep produced no geometry — check profile size.")

            swept_count = 0
            for beam in tiled:
                if swept_count < len(raw_breps):
                    beam['brep_idx'] = swept_count; swept_count += 1

            joint_count = fail_count = 0
            if params['enable_joints']:
                working, joint_count, fail_count = apply_analytical_joints(
                    raw_breps, tiled, params['profile_size'], params['max_joints'], tol)
                for b in raw_breps: b.Dispose()
            else:
                working = raw_breps

            _, mod_idx = ensure_tectonic_layer()
            ids = _bake_meshes(working, mod_idx, seed, params.get('union_mesh', False))
            if params['enable_guide']: _bake_guide(params)
            plc_label = (" [" + PLACEMENT_MODES[plc_mode] + "]") if use_plc else ""
            msg = ("V7 Ortho{} | {} beams | {} objects | joints:{}/{} | "
                   "tiles:{}x{}x{}").format(
                plc_label, len(tiled), len(ids), joint_count, joint_count+fail_count,
                params['tile_x'], params['tile_y'], params['tile_z'])

        # ── MODE 1: RANDOM LINES ────────────────────────────────────────────
        elif mode == 1:
            points = _get_line_points(params)
            if len(points) < 2: raise RuntimeError("Not enough grid points.")
            single_lines = generate_random_lines(
                points, params['num_lines'], seed,
                params['base_angle'], params['angle_range'])
            if not single_lines:
                raise RuntimeError("No valid lines — widen angle range.")
            lines = _tile_lines(single_lines, w, h, d,
                                params['tile_x'], params['tile_y'], params['tile_z'])
            raw_breps, directions = sweep_along_lines(profile, lines, cap)
            profile.Dispose()
            if not raw_breps: raise RuntimeError("Sweep produced no geometry.")
            joint_count = fail_count = 0
            if params['enable_joints']:
                working, joint_count, fail_count = apply_interlocking_joints(
                    raw_breps, directions, params['profile_size'], params['max_joints'], tol)
                for b in raw_breps: b.Dispose()
            else:
                working = raw_breps
            _, mod_idx = ensure_tectonic_layer()
            ids = _bake_meshes(working, mod_idx, seed, params.get('union_mesh', False))
            if params['enable_guide']: _bake_guide(params)
            msg = ("V7 Random | {} objects | {} lines | joints:{}/{} | "
                   "tiles:{}x{}x{}").format(
                len(ids), len(lines), joint_count, joint_count+fail_count,
                params['tile_x'], params['tile_y'], params['tile_z'])

        # ── MODE 2: CONNECTED LINES ─────────────────────────────────────────
        elif mode == 2:
            points = _get_line_points(params)
            if len(points) < 2: raise RuntimeError("Not enough grid points.")
            single_lines = generate_connected_lines(
                points, params['num_lines'], seed,
                params['base_angle'], params['angle_range'])
            if not single_lines:
                raise RuntimeError("No connected lines found — widen angle range.")
            lines = _tile_lines(single_lines, w, h, d,
                                params['tile_x'], params['tile_y'], params['tile_z'])
            raw_breps, directions = sweep_along_lines(profile, lines, cap)
            profile.Dispose()
            if not raw_breps: raise RuntimeError("Sweep produced no geometry.")
            joint_count = fail_count = 0
            if params['enable_joints']:
                working, joint_count, fail_count = apply_interlocking_joints(
                    raw_breps, directions, params['profile_size'], params['max_joints'], tol)
                for b in raw_breps: b.Dispose()
            else:
                working = raw_breps
            _, mod_idx = ensure_tectonic_layer()
            ids = _bake_meshes(working, mod_idx, seed, params.get('union_mesh', False))
            if params['enable_guide']: _bake_guide(params)
            msg = ("V7 Connected | {} objects | {} lines | joints:{}/{} | "
                   "tiles:{}x{}x{}").format(
                len(ids), len(lines), joint_count, joint_count+fail_count,
                params['tile_x'], params['tile_y'], params['tile_z'])

        # ── MODE 3: PIPE FACADE ─────────────────────────────────────────────
        elif mode == 3:
            profile.Dispose()
            seed_rng = random.Random(params['seed'])
            pipe_meshes, stack_count = build_pipe_facade(params, seed_rng, tol, ang_tol)
            if not pipe_meshes:
                raise RuntimeError("No pipe geometry — check grid/diameter settings.")
            total_h = params['depth']
            tile_x=params['tile_x']; tile_y=params['tile_y']; tile_z=params['tile_z']
            off_x=-w*(tile_x-1)/2.0; off_y=-h*(tile_y-1)/2.0; off_z=-total_h*(tile_z-1)/2.0
            tiled = []
            for tx in range(tile_x):
                for ty in range(tile_y):
                    for tz in range(tile_z):
                        vec = rg.Vector3d(off_x+tx*w, off_y+ty*h, off_z+tz*total_h)
                        xf  = rg.Transform.Translation(vec)
                        for m in pipe_meshes:
                            mc=m.DuplicateMesh(); mc.Transform(xf); tiled.append(mc)
            for m in pipe_meshes: m.Dispose()
            if params.get('union_mesh', False):
                try:
                    result = rg.Mesh.CreateBooleanUnion(tiled)
                    if result and len(result) > 0:
                        for m in tiled: m.Dispose()
                        tiled = list(result)
                except: pass
            _, mod_idx = ensure_tectonic_layer()
            ids = []
            for mesh in tiled:
                oid = sc.doc.Objects.AddMesh(mesh); mesh.Dispose()
                if oid != System.Guid.Empty:
                    obj = sc.doc.Objects.Find(oid)
                    if obj:
                        obj.Attributes.LayerIndex = mod_idx; obj.CommitChanges()
                    ids.append(oid)
            if ids:
                gname = rs.AddGroup("TECTONIC_V7_Pipe_" + str(params['seed']))
                if gname: rs.AddObjectsToGroup([str(g) for g in ids], gname)
            if params['enable_guide']: _bake_guide(params)
            msg = ("V7 Pipe | {} stacks | {} objects | tiles:{}x{}x{}").format(
                stack_count*tile_x*tile_y*tile_z, len(ids), tile_x, tile_y, tile_z)

        # ── MODE 4: NOISE MODE ──────────────────────────────────────────────
        elif mode == 4:
            algo     = int(params.get('noise_algo', 0))
            seed_rng = random.Random(seed)
            if   algo == 0: polylines = noise_flow_field(params, seed_rng)
            elif algo == 1: polylines = noise_stigmergy(params, seed_rng)
            elif algo == 2: polylines = noise_boids(params, seed_rng)
            else:           polylines = noise_reaction_diffusion(params, seed_rng)

            if not polylines:
                raise RuntimeError("No noise paths generated — try increasing agents/steps.")

            single_lines = []
            for pl in polylines:
                for i in range(len(pl) - 1):
                    single_lines.append(rg.Line(pl[i], pl[i+1]))

            if not single_lines:
                raise RuntimeError("No line segments from noise paths.")

            lines = _tile_lines(single_lines, w, h, d,
                                params['tile_x'], params['tile_y'], params['tile_z'])
            raw_breps, directions = sweep_along_lines(profile, lines, cap)
            profile.Dispose()
            if not raw_breps: raise RuntimeError("Sweep produced no geometry.")

            joint_count = fail_count = 0
            if params['enable_joints']:
                working, joint_count, fail_count = apply_interlocking_joints(
                    raw_breps, directions, params['profile_size'], params['max_joints'], tol)
                for b in raw_breps: b.Dispose()
            else:
                working = raw_breps

            _, mod_idx = ensure_tectonic_layer()
            ids = _bake_meshes(working, mod_idx, seed, params.get('union_mesh', False))
            if params['enable_guide']: _bake_guide(params)
            algo_name = NOISE_ALGOS[algo] if algo < len(NOISE_ALGOS) else "Noise"
            msg = ("V7 Noise [{0}] | {1} objects | {2} segments | "
                   "tiles:{3}x{4}x{5}").format(
                algo_name, len(ids), len(lines),
                params['tile_x'], params['tile_y'], params['tile_z'])

        else:
            profile.Dispose()
            raise RuntimeError("Unknown mode: " + str(mode))

        return {'success': True, 'message': msg}

    except Exception as ex:
        return {'success': False, 'message': "Error: " + str(ex) + "\n" + traceback.format_exc()}

    finally:
        sc.doc.EndUndoRecord(undo_id)
        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()


# =============================================================================
# ETO GUI  —  Dark Gold Theme
# =============================================================================

class TectonicModifierV7(ef.Form):

    def __init__(self):
        self.Title        = "Discrete Element Modular Modifier V7"
        self.Resizable    = True
        self.MinimumSize  = edraw.Size(560, 980)
        self.Padding      = edraw.Padding(12)
        self.BackgroundColor = C_BG
        self._rand_tabs   = {}
        self._build_ui()

    # =========================================================================
    # UI helpers
    # =========================================================================

    def _lbl(self, text, bold=False, width=None, color=None):
        lb = ef.Label(); lb.Text = text
        lb.TextColor = color if color else C_FG
        if bold:
            lb.Font = edraw.Font(lb.Font.Family, lb.Font.Size, edraw.FontStyle.Bold)
        if width is not None:
            lb.Width = width
        lb.VerticalAlignment = ef.VerticalAlignment.Center
        return lb

    def _section(self, title):
        lb = self._lbl("  " + title, bold=True, color=C_GOLD)
        return lb

    def _divider(self):
        lb = ef.Label(); lb.Text = ""
        lb.Height = 2
        return lb

    def _num(self, value, lo, hi, dec=0, inc=1):
        ns = ef.NumericStepper()
        ns.Value = value; ns.MinValue = lo; ns.MaxValue = hi
        ns.DecimalPlaces = dec; ns.Increment = inc; ns.Width = 100
        return ns

    def _slider(self, value, lo, hi, width=175):
        sl = ef.Slider(); sl.MinValue = lo; sl.MaxValue = hi
        sl.Value = value; sl.Width = width
        return sl

    def _row(self, label, ctrl, lbl_w=145):
        tl = ef.TableLayout(); tl.Spacing = edraw.Size(8, 0)
        lb = self._lbl(label, width=lbl_w)
        tl.Rows.Add(ef.TableRow(ef.TableCell(lb), ef.TableCell(ctrl)))
        return tl

    def _slider_row(self, label, slider, val_lbl, lbl_w=145):
        tl = ef.TableLayout(); tl.Spacing = edraw.Size(8, 0)
        lb = self._lbl(label, width=lbl_w)
        val_lbl.Width = 55; val_lbl.VerticalAlignment = ef.VerticalAlignment.Center
        tl.Rows.Add(ef.TableRow(
            ef.TableCell(lb),
            ef.TableCell(ef.TableLayout.AutoSized(slider)),
            ef.TableCell(val_lbl)))
        return tl

    # =========================================================================
    # Rand/Connected tab factory
    # =========================================================================

    def _build_rand_tab(self, pfx):
        ctrl = {}
        self._rand_tabs[pfx] = ctrl
        rp = ef.DynamicLayout()
        rp.DefaultSpacing = edraw.Size(6, 4)
        rp.Padding = edraw.Padding(8)

        rp.AddRow(self._section("POINT SOURCE"))
        pt_src = ef.DropDown()
        for s in PT_SOURCES: pt_src.Items.Add(ef.ListItem(Text=s))
        pt_src.SelectedIndex = DEFAULTS['pt_source']
        ctrl['pt_src'] = pt_src
        rp.AddRow(self._row("Source:", pt_src))

        uv_p = ef.Panel()
        uvp  = ef.DynamicLayout(); uvp.DefaultSpacing = edraw.Size(6, 4)
        uvw_tl = ef.TableLayout(); uvw_tl.Spacing = edraw.Size(6, 0)
        ru = self._num(DEFAULTS['u_div'], 1, 32, 0, 1)
        rv = self._num(DEFAULTS['v_div'], 1, 32, 0, 1)
        rw = self._num(DEFAULTS['w_div'], 1, 32, 0, 1)
        ru.Width = rv.Width = rw.Width = 62
        ctrl['u_div'] = ru; ctrl['v_div'] = rv; ctrl['w_div'] = rw
        uvw_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("U:", width=28)), ef.TableCell(ru),
            ef.TableCell(self._lbl("V:", width=18)), ef.TableCell(rv),
            ef.TableCell(self._lbl("W:", width=18)), ef.TableCell(rw)))
        uvp.AddRow(uvw_tl); uv_p.Content = uvp

        fc_p = ef.Panel()
        fcp  = ef.DynamicLayout(); fcp.DefaultSpacing = edraw.Size(6, 4)
        fc   = self._num(DEFAULTS['face_count'], 16, 2000, 0, 16)
        ctrl['face_count'] = fc
        fcp.AddRow(self._row("Face Count:", fc))
        fc_p.Content = fcp; fc_p.Visible = False

        def _on_src(s, e, uv=uv_p, fcp=fc_p, dd=pt_src):
            uv.Visible  = (dd.SelectedIndex == 0)
            fcp.Visible = (dd.SelectedIndex != 0)
        pt_src.SelectedIndexChanged += _on_src
        rp.AddRow(uv_p); rp.AddRow(fc_p)

        rp.AddRow(self._section("LINE GENERATION"))
        nl = self._num(DEFAULTS['num_lines'], 1, 500, 0, 1)
        ctrl['num_lines'] = nl
        rp.AddRow(self._row("Number of Lines:", nl))

        seed_tl = ef.TableLayout(); seed_tl.Spacing = edraw.Size(6, 0)
        sd_ns   = self._num(DEFAULTS['rand_seed'], 0, 99999, 0, 1)
        ctrl['seed'] = sd_ns
        btn_r = ef.Button(Text="Randomize")
        def _on_rnd(s, e, sn=sd_ns): sn.Value = random.randint(0, 99999)
        btn_r.Click += _on_rnd
        seed_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("Seed:", width=145)),
            ef.TableCell(sd_ns), ef.TableCell(btn_r)))
        rp.AddRow(seed_tl)

        rp.AddRow(self._section("TECTONIC ANGLE"))
        ang_sl = self._slider(DEFAULTS['base_angle'], 0, 90)
        ang_lb = self._lbl(str(DEFAULTS['base_angle']) + u"°", color=C_GOLD_DIM)
        ctrl['base_angle_sl'] = ang_sl
        def _on_ang(s, e, sl=ang_sl, lb=ang_lb):
            lb.Text = str(int(sl.Value)) + u"°"
        ang_sl.ValueChanged += _on_ang
        rp.AddRow(self._slider_row("Base Angle:", ang_sl, ang_lb))

        rng_sl = self._slider(DEFAULTS['angle_range'], 0, 45)
        rng_lb = self._lbl(u"±" + str(DEFAULTS['angle_range']) + u"°", color=C_GOLD_DIM)
        ctrl['angle_range_sl'] = rng_sl
        def _on_rng(s, e, sl=rng_sl, lb=rng_lb):
            lb.Text = u"±" + str(int(sl.Value)) + u"°"
        rng_sl.ValueChanged += _on_rng
        rp.AddRow(self._slider_row("Angle Range:", rng_sl, rng_lb))
        return rp

    # =========================================================================
    # Pipe Facade tab
    # =========================================================================

    def _build_pipe_tab(self):
        pp = ef.DynamicLayout()
        pp.DefaultSpacing = edraw.Size(6, 4)
        pp.Padding = edraw.Padding(8)

        pp.AddRow(self._section("STACK GRID"))
        grid_tl = ef.TableLayout(); grid_tl.Spacing = edraw.Size(6, 0)
        self._pipe_gx = self._num(DEFAULTS['pipe_grid_x'], 1, 40, 0, 1)
        self._pipe_gy = self._num(DEFAULTS['pipe_grid_y'], 1, 40, 0, 1)
        self._pipe_gx.Width = self._pipe_gy.Width = 78
        grid_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("Pipes X:", width=145)), ef.TableCell(self._pipe_gx),
            ef.TableCell(self._lbl("Y:", width=20)),        ef.TableCell(self._pipe_gy)))
        pp.AddRow(grid_tl)
        self._pipe_zl = self._num(DEFAULTS['pipe_z_levels'], 1, 40, 0, 1)
        pp.AddRow(self._row("Z Levels (stacks):", self._pipe_zl))

        pp.AddRow(self._section("PIPE SIZE"))
        self._pipe_diam = self._num(DEFAULTS['pipe_diameter'], 0.1, 200.0, 2, 0.5)
        pp.AddRow(self._row("Diameter:", self._pipe_diam))

        pp.AddRow(self._section("VOXEL WANDER"))
        self._pipe_wander_sl = self._slider(DEFAULTS['pipe_wander'], 0, 100)
        self._pipe_wander_lb = self._lbl(str(DEFAULTS['pipe_wander']) + "%", color=C_GOLD_DIM)
        def _on_pw(s, e, sl=self._pipe_wander_sl, lb=self._pipe_wander_lb):
            lb.Text = str(int(sl.Value)) + "%"
        self._pipe_wander_sl.ValueChanged += _on_pw
        pp.AddRow(self._slider_row("Wander Amount:", self._pipe_wander_sl, self._pipe_wander_lb))
        pp.AddRow(self._lbl("  0%=straight  |  100%=full diagonal", width=300))

        pp.AddRow(self._section("HORIZONTAL CONNECTORS"))
        self._pipe_conn_sl = self._slider(DEFAULTS['pipe_conn_prob'], 0, 100)
        self._pipe_conn_lb = self._lbl(str(DEFAULTS['pipe_conn_prob']) + "%", color=C_GOLD_DIM)
        def _on_pc(s, e, sl=self._pipe_conn_sl, lb=self._pipe_conn_lb):
            lb.Text = str(int(sl.Value)) + "%"
        self._pipe_conn_sl.ValueChanged += _on_pc
        pp.AddRow(self._slider_row("Connector Prob:", self._pipe_conn_sl, self._pipe_conn_lb))

        pp.AddRow(self._section("BRACKETS"))
        self._pipe_bkt = ef.CheckBox()
        self._pipe_bkt.Text = "Add wall brackets"
        self._pipe_bkt.Checked = DEFAULTS['pipe_brackets']
        self._pipe_bkt.CheckedChanged += self._on_pipe_bracket_toggle
        pp.AddRow(self._pipe_bkt)
        self._pipe_bkt_int     = self._num(DEFAULTS['pipe_bracket_int'], 1, 20, 0, 1)
        self._pipe_bkt_int_row = self._row("Bracket every N levels:", self._pipe_bkt_int)
        pp.AddRow(self._pipe_bkt_int_row)

        pp.AddRow(self._section("SEED"))
        pseed_tl = ef.TableLayout(); pseed_tl.Spacing = edraw.Size(6, 0)
        self._pipe_seed = self._num(DEFAULTS['pipe_seed'], 0, 99999, 0, 1)
        btn_ps = ef.Button(Text="Randomize")
        def _on_ps(s, e, sn=self._pipe_seed): sn.Value = random.randint(0, 99999)
        btn_ps.Click += _on_ps
        pseed_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("Seed:", width=145)),
            ef.TableCell(self._pipe_seed), ef.TableCell(btn_ps)))
        pp.AddRow(pseed_tl)
        return pp

    # =========================================================================
    # Noise Mode tab  (Tab 4)
    # =========================================================================

    def _build_noise_tab(self):
        np_ = ef.DynamicLayout()
        np_.DefaultSpacing = edraw.Size(6, 4)
        np_.Padding = edraw.Padding(8)

        # Algorithm selector
        np_.AddRow(self._section("ALGORITHM"))
        self._noise_algo = ef.DropDown()
        for a in NOISE_ALGOS: self._noise_algo.Items.Add(ef.ListItem(Text=a))
        self._noise_algo.SelectedIndex = DEFAULTS['noise_algo']
        np_.AddRow(self._row("Algorithm:", self._noise_algo))

        # Shared seed
        np_.AddRow(self._section("SEED"))
        nseed_tl = ef.TableLayout(); nseed_tl.Spacing = edraw.Size(6, 0)
        self._noise_seed = self._num(DEFAULTS['noise_seed'], 0, 99999, 0, 1)
        btn_ns = ef.Button(Text="Randomize")
        def _on_nsr(s, e, sn=self._noise_seed): sn.Value = random.randint(0, 99999)
        btn_ns.Click += _on_nsr
        nseed_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("Seed:", width=145)),
            ef.TableCell(self._noise_seed), ef.TableCell(btn_ns)))
        np_.AddRow(nseed_tl)

        # ── Panel 0: Flow Field ──────────────────────────────────────────────
        self._noise_p0 = ef.Panel()
        p0 = ef.DynamicLayout(); p0.DefaultSpacing = edraw.Size(6, 4)
        p0.AddRow(self._section("FLOW FIELD  (Perlin fBm)"))
        self._noise_n_agents = self._num(DEFAULTS['noise_num_agents'], 1, 500, 0, 1)
        self._noise_steps    = self._num(DEFAULTS['noise_steps'], 5, 1000, 0, 10)
        self._noise_step_sz  = self._num(DEFAULTS['noise_step_size'], 0.01, 50.0, 2, 0.5)
        self._noise_scale    = self._num(DEFAULTS['noise_scale'], 0.001, 5.0, 3, 0.01)
        self._noise_octaves  = self._num(DEFAULTS['noise_octaves'], 1, 8, 0, 1)
        self._noise_persist_sl = self._slider(DEFAULTS['noise_persistence'], 0, 100)
        self._noise_persist_lb = self._lbl(str(DEFAULTS['noise_persistence']) + "%", color=C_GOLD_DIM)
        def _on_npers(s, e, sl=self._noise_persist_sl, lb=self._noise_persist_lb):
            lb.Text = str(int(sl.Value)) + "%"
        self._noise_persist_sl.ValueChanged += _on_npers
        p0.AddRow(self._row("Streams:", self._noise_n_agents))
        p0.AddRow(self._row("Steps per Stream:", self._noise_steps))
        p0.AddRow(self._row("Step Size:", self._noise_step_sz))
        p0.AddRow(self._row("Noise Scale:", self._noise_scale))
        p0.AddRow(self._row("Octaves:", self._noise_octaves))
        p0.AddRow(self._slider_row("Persistence:", self._noise_persist_sl, self._noise_persist_lb))
        self._noise_p0.Content = p0

        # ── Panel 1: Stigmergy ───────────────────────────────────────────────
        self._noise_p1 = ef.Panel()
        p1 = ef.DynamicLayout(); p1.DefaultSpacing = edraw.Size(6, 4)
        p1.AddRow(self._section("STIGMERGY  (Ant Pheromone Trails)"))
        self._stig_n_agents = self._num(DEFAULTS['stig_num_agents'], 1, 200, 0, 1)
        self._stig_steps    = self._num(DEFAULTS['stig_steps'], 5, 1000, 0, 10)
        self._stig_step_sz  = self._num(DEFAULTS['stig_step_size'], 0.01, 50.0, 2, 0.5)
        self._stig_evap_sl  = self._slider(DEFAULTS['stig_evap'], 0, 100)
        self._stig_evap_lb  = self._lbl(str(DEFAULTS['stig_evap']) + "%", color=C_GOLD_DIM)
        self._stig_deposit  = self._num(DEFAULTS['stig_deposit'], 0.01, 20.0, 2, 0.5)
        self._stig_sense    = self._num(DEFAULTS['stig_sense_dist'], 0.1, 50.0, 1, 1.0)
        def _on_sevap(s, e, sl=self._stig_evap_sl, lb=self._stig_evap_lb):
            lb.Text = str(int(sl.Value)) + "%"
        self._stig_evap_sl.ValueChanged += _on_sevap
        p1.AddRow(self._row("Num Agents:", self._stig_n_agents))
        p1.AddRow(self._row("Steps per Agent:", self._stig_steps))
        p1.AddRow(self._row("Step Size:", self._stig_step_sz))
        p1.AddRow(self._slider_row("Evaporation:", self._stig_evap_sl, self._stig_evap_lb))
        p1.AddRow(self._row("Deposition:", self._stig_deposit))
        p1.AddRow(self._row("Sense Distance:", self._stig_sense))
        self._noise_p1.Content = p1
        self._noise_p1.Visible = False

        # ── Panel 2: Boids ───────────────────────────────────────────────────
        self._noise_p2 = ef.Panel()
        p2 = ef.DynamicLayout(); p2.DefaultSpacing = edraw.Size(6, 4)
        p2.AddRow(self._section("BOIDS  (Flocking)"))
        self._boids_num      = self._num(DEFAULTS['boids_num'], 1, 500, 0, 1)
        self._boids_steps    = self._num(DEFAULTS['boids_steps'], 5, 1000, 0, 10)
        self._boids_step_sz  = self._num(DEFAULTS['boids_step_size'], 0.01, 50.0, 2, 0.5)
        self._boids_sep_dist = self._num(DEFAULTS['boids_sep_dist'], 0.1, 100.0, 1, 0.5)
        self._boids_sep_w    = self._num(DEFAULTS['boids_sep_w'], 0.0, 10.0, 2, 0.1)
        self._boids_align_w  = self._num(DEFAULTS['boids_align_w'], 0.0, 10.0, 2, 0.1)
        self._boids_coh_w    = self._num(DEFAULTS['boids_cohesion_w'], 0.0, 10.0, 2, 0.1)
        self._boids_max_spd  = self._num(DEFAULTS['boids_max_speed'], 0.1, 50.0, 1, 0.5)
        p2.AddRow(self._row("Num Boids:", self._boids_num))
        p2.AddRow(self._row("Steps per Boid:", self._boids_steps))
        p2.AddRow(self._row("Step Size:", self._boids_step_sz))
        p2.AddRow(self._row("Separation Dist:", self._boids_sep_dist))
        p2.AddRow(self._row("Sep Weight:", self._boids_sep_w))
        p2.AddRow(self._row("Align Weight:", self._boids_align_w))
        p2.AddRow(self._row("Cohesion Weight:", self._boids_coh_w))
        p2.AddRow(self._row("Max Speed:", self._boids_max_spd))
        self._noise_p2.Content = p2
        self._noise_p2.Visible = False

        # ── Panel 3: Reaction-Diffusion ──────────────────────────────────────
        self._noise_p3 = ef.Panel()
        p3 = ef.DynamicLayout(); p3.DefaultSpacing = edraw.Size(6, 4)
        p3.AddRow(self._section("REACTION-DIFFUSION  (Gray-Scott)"))
        self._rd_feed  = self._num(DEFAULTS['rd_feed'], 0.001, 0.2, 3, 0.001)
        self._rd_kill  = self._num(DEFAULTS['rd_kill'], 0.001, 0.2, 3, 0.001)
        self._rd_steps = self._num(DEFAULTS['rd_steps'], 50, 5000, 0, 50)
        self._rd_init  = ef.DropDown()
        for ri in RD_INITS: self._rd_init.Items.Add(ef.ListItem(Text=ri))
        self._rd_init.SelectedIndex = DEFAULTS['rd_init']
        p3.AddRow(self._row("Feed Rate:", self._rd_feed))
        p3.AddRow(self._row("Kill Rate:", self._rd_kill))
        p3.AddRow(self._row("Sim Steps:", self._rd_steps))
        p3.AddRow(self._row("Init Pattern:", self._rd_init))
        p3.AddRow(self._lbl("  Spots: feed~0.037 kill~0.06", color=C_GOLD_DIM))
        p3.AddRow(self._lbl("  Maze:  feed~0.029 kill~0.057", color=C_GOLD_DIM))
        p3.AddRow(self._lbl("  Coral: feed~0.055 kill~0.062", color=C_GOLD_DIM))
        self._noise_p3.Content = p3
        self._noise_p3.Visible = False

        # Wire algo selector
        noise_panels = [self._noise_p0, self._noise_p1, self._noise_p2, self._noise_p3]
        def _on_nalgo(s, e, dd=self._noise_algo, pnls=noise_panels):
            for i, pn in enumerate(pnls):
                pn.Visible = (i == dd.SelectedIndex)
        self._noise_algo.SelectedIndexChanged += _on_nalgo

        np_.AddRow(self._noise_p0)
        np_.AddRow(self._noise_p1)
        np_.AddRow(self._noise_p2)
        np_.AddRow(self._noise_p3)
        return np_

    # =========================================================================
    # Main UI builder
    # =========================================================================

    def _build_ui(self):
        layout = ef.DynamicLayout()
        layout.DefaultSpacing = edraw.Size(6, 5)
        layout.Padding        = edraw.Padding(8)

        # BOX DIMENSIONS
        layout.AddRow(self._section("BOX DIMENSIONS"))
        self._width  = self._num(DEFAULTS['width'],  0.1, 10000, 1, 1.0)
        self._height = self._num(DEFAULTS['height'], 0.1, 10000, 1, 1.0)
        self._depth  = self._num(DEFAULTS['depth'],  0.1, 10000, 1, 1.0)
        dim_tl = ef.TableLayout(); dim_tl.Spacing = edraw.Size(6, 0)
        self._width.Width = self._height.Width = self._depth.Width = 90
        dim_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("W:", width=28)), ef.TableCell(self._width),
            ef.TableCell(self._lbl("H:", width=22)), ef.TableCell(self._height),
            ef.TableCell(self._lbl("D:", width=22)), ef.TableCell(self._depth)))
        layout.AddRow(dim_tl)
        layout.AddRow(None)

        # TILING
        layout.AddRow(self._section("TILING"))
        tile_tl = ef.TableLayout(); tile_tl.Spacing = edraw.Size(6, 0)
        self._tile_x = self._num(DEFAULTS['tile_x'], 1, 20, 0, 1)
        self._tile_y = self._num(DEFAULTS['tile_y'], 1, 20, 0, 1)
        self._tile_z = self._num(DEFAULTS['tile_z'], 1, 20, 0, 1)
        self._tile_x.Width = self._tile_y.Width = self._tile_z.Width = 62
        tile_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("X:", width=28)), ef.TableCell(self._tile_x),
            ef.TableCell(self._lbl("Y:", width=22)), ef.TableCell(self._tile_y),
            ef.TableCell(self._lbl("Z:", width=22)), ef.TableCell(self._tile_z)))
        layout.AddRow(tile_tl)
        layout.AddRow(None)

        # ── MODE TABS ─────────────────────────────────────────────────────────
        self._tabs = ef.TabControl()

        # ── TAB 0: TIMBER JOINT (Orthogonal Grid) ────────────────────────────
        tab_tj = ef.TabPage(); tab_tj.Text = "Timber Joint"
        op = ef.DynamicLayout(); op.DefaultSpacing = edraw.Size(6, 4)
        op.Padding = edraw.Padding(8)

        op.AddRow(self._section("ACTIVE AXES"))
        axes_tl = ef.TableLayout(); axes_tl.Spacing = edraw.Size(10, 0)
        self._use_x = ef.CheckBox(); self._use_x.Text = "X"; self._use_x.Checked = DEFAULTS['use_x']
        self._use_y = ef.CheckBox(); self._use_y.Text = "Y"; self._use_y.Checked = DEFAULTS['use_y']
        self._use_z = ef.CheckBox(); self._use_z.Text = "Z"; self._use_z.Checked = DEFAULTS['use_z']
        axes_tl.Rows.Add(ef.TableRow(ef.TableCell(self._use_x),
                                     ef.TableCell(self._use_y),
                                     ef.TableCell(self._use_z)))
        op.AddRow(axes_tl)

        op.AddRow(self._section("BEAM DENSITY  (Grid Divisions)"))
        uvw_tl = ef.TableLayout(); uvw_tl.Spacing = edraw.Size(6, 0)
        self._u_div = self._num(DEFAULTS['u_div'], 1, 32, 0, 1)
        self._v_div = self._num(DEFAULTS['v_div'], 1, 32, 0, 1)
        self._w_div = self._num(DEFAULTS['w_div'], 1, 32, 0, 1)
        self._u_div.Width = self._v_div.Width = self._w_div.Width = 62
        uvw_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("U:", width=28)), ef.TableCell(self._u_div),
            ef.TableCell(self._lbl("V:", width=18)), ef.TableCell(self._v_div),
            ef.TableCell(self._lbl("W:", width=18)), ef.TableCell(self._w_div)))
        op.AddRow(uvw_tl)
        self._num_beams = self._num(DEFAULTS['num_beams'], 1, 500, 0, 1)
        op.AddRow(self._row("Beam Count:", self._num_beams))

        self._hz_sl = self._slider(DEFAULTS['hz_bias'], 0, 100)
        self._hz_lb = self._lbl(str(DEFAULTS['hz_bias']) + "%", color=C_GOLD_DIM)
        self._hz_sl.ValueChanged += self._on_hz_changed
        op.AddRow(self._slider_row("Horizontal Bias:", self._hz_sl, self._hz_lb))

        op.AddRow(self._section("ATTRACTOR  (Density Control)"))
        self._enable_attractor = ef.CheckBox()
        self._enable_attractor.Text    = "Enable attractor density field"
        self._enable_attractor.Checked = DEFAULTS['enable_attractor']
        self._enable_attractor.CheckedChanged += self._on_attractor_toggle
        op.AddRow(self._enable_attractor)

        self._attr_panel = ef.Panel()
        ap = ef.DynamicLayout(); ap.DefaultSpacing = edraw.Size(6, 4)
        attr_xyz = ef.TableLayout(); attr_xyz.Spacing = edraw.Size(6, 0)
        self._attr_x = self._num(DEFAULTS['attr_x'], -9999, 9999, 1, 1.0)
        self._attr_y = self._num(DEFAULTS['attr_y'], -9999, 9999, 1, 1.0)
        self._attr_z = self._num(DEFAULTS['attr_z'], -9999, 9999, 1, 1.0)
        self._attr_x.Width = self._attr_y.Width = self._attr_z.Width = 72
        attr_xyz.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("X:", width=22)), ef.TableCell(self._attr_x),
            ef.TableCell(self._lbl("Y:", width=18)), ef.TableCell(self._attr_y),
            ef.TableCell(self._lbl("Z:", width=18)), ef.TableCell(self._attr_z)))
        ap.AddRow(self._row("Attractor Pos:", attr_xyz))
        self._attr_radius = self._num(DEFAULTS['attr_radius'], 0.1, 9999, 1, 5.0)
        ap.AddRow(self._row("Falloff Radius:", self._attr_radius))
        self._min_sl = self._slider(DEFAULTS['attr_min_density'], 0, 100)
        self._min_lb = self._lbl(str(DEFAULTS['attr_min_density']) + "%", color=C_GOLD_DIM)
        self._min_sl.ValueChanged += self._on_min_changed
        ap.AddRow(self._slider_row("Min Density:", self._min_sl, self._min_lb))
        self._attr_panel.Content = ap
        op.AddRow(self._attr_panel)

        # ── PLACEMENT FILTER ─────────────────────────────────────────────────
        op.AddRow(self._section("PLACEMENT FILTER"))
        self._use_placement_cb = ef.CheckBox()
        self._use_placement_cb.Text    = "Enable placement filter"
        self._use_placement_cb.Checked = DEFAULTS['use_placement']
        self._use_placement_cb.CheckedChanged += self._on_placement_toggle
        op.AddRow(self._use_placement_cb)

        self._placement_panel = ef.Panel()
        plp = ef.DynamicLayout(); plp.DefaultSpacing = edraw.Size(6, 4)
        self._placement_mode_dd = ef.DropDown()
        for pm in PLACEMENT_MODES: self._placement_mode_dd.Items.Add(ef.ListItem(Text=pm))
        self._placement_mode_dd.SelectedIndex = DEFAULTS['placement_mode']
        self._placement_mode_dd.SelectedIndexChanged += self._on_placement_mode_changed
        plp.AddRow(self._row("Mode:", self._placement_mode_dd))

        self._wall_face_panel = ef.Panel()
        wfp = ef.DynamicLayout(); wfp.DefaultSpacing = edraw.Size(6, 4)
        self._wall_face_dd = ef.DropDown()
        for wf in WALL_FACES: self._wall_face_dd.Items.Add(ef.ListItem(Text=wf))
        self._wall_face_dd.SelectedIndex = DEFAULTS['wall_face']
        wfp.AddRow(self._row("Wall Face:", self._wall_face_dd))
        self._wall_face_panel.Content = wfp
        self._wall_face_panel.Visible = False
        plp.AddRow(self._wall_face_panel)
        self._placement_panel.Content = plp
        self._placement_panel.Visible = False
        op.AddRow(self._placement_panel)

        # ── SEED + JITTER ────────────────────────────────────────────────────
        op.AddRow(self._section("SEED"))
        oseed_tl = ef.TableLayout(); oseed_tl.Spacing = edraw.Size(6, 0)
        self._ortho_seed = self._num(DEFAULTS['ortho_seed'], 0, 99999, 0, 1)
        btn_os = ef.Button(Text="Randomize"); btn_os.Click += self._on_ortho_randomize
        oseed_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("Seed:", width=145)),
            ef.TableCell(self._ortho_seed), ef.TableCell(btn_os)))
        op.AddRow(oseed_tl)
        self._jitter_sl = self._slider(DEFAULTS['grid_jitter'], 0, 100)
        self._jitter_lb = self._lbl(str(DEFAULTS['grid_jitter']) + "%", color=C_GOLD_DIM)
        self._jitter_sl.ValueChanged += self._on_jitter_changed
        op.AddRow(self._slider_row("Grid Jitter:", self._jitter_sl, self._jitter_lb))

        # ── RANDOM LENGTH ────────────────────────────────────────────────────
        op.AddRow(self._section("RANDOM LENGTH"))
        self._rand_len_cb = ef.CheckBox()
        self._rand_len_cb.Text    = "Enable random beam length"
        self._rand_len_cb.Checked = DEFAULTS['random_length']
        self._rand_len_cb.CheckedChanged += self._on_rand_len_toggle
        op.AddRow(self._rand_len_cb)
        self._rand_len_panel = ef.Panel()
        rlp = ef.DynamicLayout(); rlp.DefaultSpacing = edraw.Size(6, 4)
        self._rand_len_sl = self._slider(DEFAULTS['min_length_pct'], 10, 100)
        self._rand_len_lb = self._lbl(str(DEFAULTS['min_length_pct']) + "%", color=C_GOLD_DIM)
        def _on_rlen(s, e, sl=self._rand_len_sl, lb=self._rand_len_lb):
            lb.Text = str(int(sl.Value)) + "%"
        self._rand_len_sl.ValueChanged += _on_rlen
        rlp.AddRow(self._slider_row("Min Length:", self._rand_len_sl, self._rand_len_lb))
        self._rand_len_panel.Content = rlp
        self._rand_len_panel.Visible = False
        op.AddRow(self._rand_len_panel)

        tab_tj.Content = op
        self._tabs.Pages.Add(tab_tj)

        # ── TAB 1: DISCRETE MODULAR ──────────────────────────────────────────
        tab_dm = ef.TabPage(); tab_dm.Text = "Discrete Modular"
        tab_dm.Content = self._build_rand_tab('dm')
        self._tabs.Pages.Add(tab_dm)

        # ── TAB 2: CONNECTED ─────────────────────────────────────────────────
        tab_cn = ef.TabPage(); tab_cn.Text = "Connected"
        tab_cn.Content = self._build_rand_tab('cn')
        self._tabs.Pages.Add(tab_cn)

        # ── TAB 3: PIPE FACADE ───────────────────────────────────────────────
        tab_pf = ef.TabPage(); tab_pf.Text = "Pipe Facade"
        tab_pf.Content = self._build_pipe_tab()
        self._tabs.Pages.Add(tab_pf)

        # ── TAB 4: NOISE MODE ────────────────────────────────────────────────
        tab_nm = ef.TabPage(); tab_nm.Text = "Noise Mode"
        tab_nm.Content = self._build_noise_tab()
        self._tabs.Pages.Add(tab_nm)

        layout.AddRow(self._tabs)
        layout.AddRow(None)

        # PROFILE SHAPE
        layout.AddRow(self._section("PROFILE SHAPE"))
        self._profile_dd = ef.DropDown()
        for name in PROFILE_NAMES: self._profile_dd.Items.Add(ef.ListItem(Text=name))
        self._profile_dd.SelectedIndex = DEFAULTS['profile_shape']
        layout.AddRow(self._row("Shape:", self._profile_dd))
        prof_sz_tl = ef.TableLayout(); prof_sz_tl.Spacing = edraw.Size(6, 0)
        self._profile_size   = self._num(DEFAULTS['profile_size'],   0.05, 500.0, 2, 0.5)
        self._profile_size_z = self._num(DEFAULTS['profile_size_z'], 0.05, 500.0, 2, 0.5)
        self._profile_size.Width = self._profile_size_z.Width = 95
        prof_sz_tl.Rows.Add(ef.TableRow(
            ef.TableCell(self._lbl("Width:", width=60)), ef.TableCell(self._profile_size),
            ef.TableCell(self._lbl("Height:", width=55)), ef.TableCell(self._profile_size_z)))
        layout.AddRow(prof_sz_tl)
        layout.AddRow(None)

        # JOINTS
        layout.AddRow(self._section("JOINTS"))
        self._enable_joints = ef.CheckBox()
        self._enable_joints.Text    = "Enable interlocking joints"
        self._enable_joints.Checked = DEFAULTS['enable_joints']
        self._enable_joints.CheckedChanged += self._on_joints_toggle
        layout.AddRow(self._enable_joints)
        self._max_joints     = self._num(DEFAULTS['max_joints'], 1, 2000, 0, 10)
        self._max_joints_row = self._row("Max Joint Pairs:", self._max_joints)
        layout.AddRow(self._max_joints_row)
        layout.AddRow(None)

        # MESH OUTPUT
        layout.AddRow(self._section("MESH OUTPUT"))
        self._union_mesh = ef.CheckBox()
        self._union_mesh.Text    = "Boolean union mesh after bake"
        self._union_mesh.Checked = DEFAULTS['union_mesh']
        layout.AddRow(self._union_mesh)
        self._cap_geo = ef.CheckBox()
        self._cap_geo.Text    = "Cap beam ends (CapPlanarHoles)"
        self._cap_geo.Checked = DEFAULTS['cap_geometry']
        layout.AddRow(self._cap_geo)
        layout.AddRow(None)

        # GUIDE
        layout.AddRow(self._section("GUIDE  (locked preview)"))
        self._enable_guide = ef.CheckBox()
        self._enable_guide.Text    = "Enable guide layer (locked)"
        self._enable_guide.Checked = DEFAULTS['enable_guide']
        self._enable_guide.CheckedChanged += self._on_guide_toggle
        layout.AddRow(self._enable_guide)
        self._guide_radius     = self._num(DEFAULTS['guide_radius'], 0.001, 10.0, 3, 0.05)
        self._guide_radius_row = self._row("Box Edge Radius:", self._guide_radius)
        layout.AddRow(self._guide_radius_row)
        layout.AddRow(None)

        # BUTTONS
        btn_tl = ef.TableLayout(); btn_tl.Spacing = edraw.Size(8, 0)
        btn_gen   = ef.Button(Text="Generate")
        btn_clear = ef.Button(Text="Clear Previous")
        btn_close = ef.Button(Text="Close")
        btn_gen.Click   += self._on_generate
        btn_clear.Click += self._on_clear
        btn_close.Click += self._on_close_click
        btn_gen.Width = 120; btn_clear.Width = 120; btn_close.Width = 80
        btn_tl.Rows.Add(ef.TableRow(ef.TableCell(btn_gen),
                                    ef.TableCell(btn_clear),
                                    ef.TableCell(btn_close)))
        layout.AddRow(btn_tl)
        layout.AddRow(None)

        self._status = ef.Label()
        self._status.Text      = "Ready"
        self._status.TextColor = C_GOLD
        self._status.Wrap      = ef.WrapMode.Word
        layout.AddRow(self._status)

        scroll = ef.Scrollable()
        scroll.Content             = layout
        scroll.Border              = ef.BorderType.None
        scroll.ExpandContentWidth  = True
        scroll.ExpandContentHeight = False
        self.Content = scroll

    # =========================================================================
    # Events
    # =========================================================================

    def _on_pipe_bracket_toggle(self, s, e):
        self._pipe_bkt_int_row.Enabled = bool(self._pipe_bkt.Checked)

    def _on_attractor_toggle(self, s, e):
        self._attr_panel.Visible = bool(self._enable_attractor.Checked)

    def _on_placement_toggle(self, s, e):
        self._placement_panel.Visible = bool(self._use_placement_cb.Checked)

    def _on_placement_mode_changed(self, s, e):
        self._wall_face_panel.Visible = (self._placement_mode_dd.SelectedIndex == 3)

    def _on_rand_len_toggle(self, s, e):
        self._rand_len_panel.Visible = bool(self._rand_len_cb.Checked)

    def _on_hz_changed(self, s, e):
        self._hz_lb.Text = str(int(self._hz_sl.Value)) + "%"

    def _on_min_changed(self, s, e):
        self._min_lb.Text = str(int(self._min_sl.Value)) + "%"

    def _on_jitter_changed(self, s, e):
        self._jitter_lb.Text = str(int(self._jitter_sl.Value)) + "%"

    def _on_ortho_randomize(self, s, e):
        self._ortho_seed.Value = random.randint(0, 99999)

    def _on_joints_toggle(self, s, e):
        self._max_joints_row.Enabled = bool(self._enable_joints.Checked)

    def _on_guide_toggle(self, s, e):
        self._guide_radius_row.Enabled = bool(self._enable_guide.Checked)

    def _on_generate(self, s, e):
        self._status.Text      = "Generating..."
        self._status.TextColor = C_ORANGE
        try:
            result = build_module(self._get_params())
            if result['success']:
                self._status.Text      = result['message']
                self._status.TextColor = C_GREEN
            else:
                self._status.Text      = result['message']
                self._status.TextColor = C_RED
        except Exception as ex:
            self._status.Text      = "Error: " + str(ex)
            self._status.TextColor = C_RED

    def _on_clear(self, s, e):
        try:
            clear_previous()
            sc.doc.Views.Redraw()
            self._status.Text      = "Cleared all TECTONIC layers"
            self._status.TextColor = C_GOLD
        except Exception as ex:
            self._status.Text      = "Clear error: " + str(ex)
            self._status.TextColor = C_RED

    def _on_close_click(self, s, e):
        self.Close()

    # =========================================================================
    # Collect parameters
    # =========================================================================

    def _get_params(self):
        idx = self._tabs.SelectedIndex
        p = {
            'width':          self._width.Value,
            'height':         self._height.Value,
            'depth':          self._depth.Value,
            'tile_x':         int(self._tile_x.Value),
            'tile_y':         int(self._tile_y.Value),
            'tile_z':         int(self._tile_z.Value),
            'gen_mode':       idx,
            'profile_shape':  PROFILE_NAMES[self._profile_dd.SelectedIndex],
            'profile_size':   self._profile_size.Value,
            'profile_size_z': self._profile_size_z.Value,
            'cap_geometry':   bool(self._cap_geo.Checked),
            'enable_joints':  bool(self._enable_joints.Checked),
            'max_joints':     int(self._max_joints.Value),
            'union_mesh':     bool(self._union_mesh.Checked),
            'enable_guide':   bool(self._enable_guide.Checked),
            'guide_radius':   self._guide_radius.Value,
        }

        if idx == 0:   # Timber Joint
            p.update({
                'seed':             int(self._ortho_seed.Value),
                'u_div':            int(self._u_div.Value),
                'v_div':            int(self._v_div.Value),
                'w_div':            int(self._w_div.Value),
                'num_beams':        int(self._num_beams.Value),
                'use_x':            bool(self._use_x.Checked),
                'use_y':            bool(self._use_y.Checked),
                'use_z':            bool(self._use_z.Checked),
                'hz_bias':          int(self._hz_sl.Value),
                'grid_jitter':      int(self._jitter_sl.Value),
                'enable_attractor': bool(self._enable_attractor.Checked),
                'attr_x':           self._attr_x.Value,
                'attr_y':           self._attr_y.Value,
                'attr_z':           self._attr_z.Value,
                'attr_radius':      self._attr_radius.Value,
                'attr_min_density': int(self._min_sl.Value),
                'use_placement':    bool(self._use_placement_cb.Checked),
                'placement_mode':   int(self._placement_mode_dd.SelectedIndex),
                'wall_face':        int(self._wall_face_dd.SelectedIndex),
                'random_length':    bool(self._rand_len_cb.Checked),
                'min_length_pct':   int(self._rand_len_sl.Value),
            })

        elif idx in (1, 2):   # Discrete Modular / Connected
            pfx  = 'dm' if idx == 1 else 'cn'
            ctrl = self._rand_tabs[pfx]
            p.update({
                'seed':             int(ctrl['seed'].Value),
                'pt_source':        ctrl['pt_src'].SelectedIndex,
                'u_div':            int(ctrl['u_div'].Value),
                'v_div':            int(ctrl['v_div'].Value),
                'w_div':            int(ctrl['w_div'].Value),
                'face_count':       int(ctrl['face_count'].Value),
                'num_lines':        int(ctrl['num_lines'].Value),
                'base_angle':       ctrl['base_angle_sl'].Value,
                'angle_range':      ctrl['angle_range_sl'].Value,
                'num_beams':        DEFAULTS['num_beams'],
                'use_x': True, 'use_y': True, 'use_z': True,
                'hz_bias':          DEFAULTS['hz_bias'],
                'grid_jitter':      DEFAULTS['grid_jitter'],
                'enable_attractor': False,
                'attr_x': 0.0, 'attr_y': 0.0, 'attr_z': 0.0,
                'attr_radius': 50.0, 'attr_min_density': 0,
                'use_placement': False, 'placement_mode': 0, 'wall_face': 0,
                'random_length': False, 'min_length_pct': 50,
            })

        elif idx == 3:   # Pipe Facade
            p.update({
                'seed':             int(self._pipe_seed.Value),
                'pipe_grid_x':      int(self._pipe_gx.Value),
                'pipe_grid_y':      int(self._pipe_gy.Value),
                'pipe_z_levels':    int(self._pipe_zl.Value),
                'pipe_mod_h':       20.0,
                'pipe_diameter':    self._pipe_diam.Value,
                'pipe_wander':      int(self._pipe_wander_sl.Value),
                'pipe_conn_prob':   int(self._pipe_conn_sl.Value),
                'pipe_brackets':    bool(self._pipe_bkt.Checked),
                'pipe_bracket_int': int(self._pipe_bkt_int.Value),
                'u_div': 1, 'v_div': 1, 'w_div': 1,
                'use_placement': False, 'placement_mode': 0, 'wall_face': 0,
                'random_length': False, 'min_length_pct': 50,
            })

        else:   # idx == 4 — Noise Mode
            p.update({
                'seed':             int(self._noise_seed.Value),
                'noise_algo':       int(self._noise_algo.SelectedIndex),
                'noise_num_agents': int(self._noise_n_agents.Value),
                'noise_steps':      int(self._noise_steps.Value),
                'noise_step_size':  self._noise_step_sz.Value,
                'noise_scale':      self._noise_scale.Value,
                'noise_octaves':    int(self._noise_octaves.Value),
                'noise_persistence': int(self._noise_persist_sl.Value),
                'stig_num_agents':  int(self._stig_n_agents.Value),
                'stig_steps':       int(self._stig_steps.Value),
                'stig_step_size':   self._stig_step_sz.Value,
                'stig_evap':        int(self._stig_evap_sl.Value),
                'stig_deposit':     self._stig_deposit.Value,
                'stig_sense_dist':  self._stig_sense.Value,
                'boids_num':        int(self._boids_num.Value),
                'boids_steps':      int(self._boids_steps.Value),
                'boids_step_size':  self._boids_step_sz.Value,
                'boids_sep_dist':   self._boids_sep_dist.Value,
                'boids_sep_w':      self._boids_sep_w.Value,
                'boids_align_w':    self._boids_align_w.Value,
                'boids_cohesion_w': self._boids_coh_w.Value,
                'boids_max_speed':  self._boids_max_spd.Value,
                'rd_feed':          self._rd_feed.Value,
                'rd_kill':          self._rd_kill.Value,
                'rd_steps':         int(self._rd_steps.Value),
                'rd_init':          int(self._rd_init.SelectedIndex),
                # Defaults for unused keys
                'u_div': 3, 'v_div': 3, 'w_div': 2,
                'num_beams': 30,
                'use_x': True, 'use_y': True, 'use_z': True,
                'hz_bias': 70, 'grid_jitter': 0,
                'enable_attractor': False,
                'attr_x': 0.0, 'attr_y': 0.0, 'attr_z': 0.0,
                'attr_radius': 50.0, 'attr_min_density': 0,
                'use_placement': False, 'placement_mode': 0, 'wall_face': 0,
                'random_length': False, 'min_length_pct': 50,
            })
        return p


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("Discrete Element Modular Modifier V7: Starting...")
    try:
        form = TectonicModifierV7()
        form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
        form.Show()
        print("V7: Form launched successfully")
    except Exception as ex:
        print("V7: Launch error — " + str(ex))
        print(traceback.format_exc())
