#! python3
"""
Climate Comfort Agent V3
========================
Rhino 8 / CPython 3

Solar-only climate stamper for the Genlap pipeline.

Workflow:
  1. Window-select your voxel field in the viewport
  2. Click "Load Selected Voxels"
  3. Pick EPW month
  4. Click "Run Solar Analysis"
  5. Click "Bake Climate Voxels"

Output:
  New cube meshes on CLIMATE_VOXELS::Passive / Marginal / Overheated layers.
  Each mesh carries Object User Text readable by any downstream script:
    solar_score      (0.0 – 1.0)
    zone             passive | marginal | overheated
    thermal_comfort  (0 – 100, higher = cooler)
    daylight_score   (0 – 100, higher = brighter)
    epw_month        e.g. "January"

Downstream scripts read:
    zone  = rs.GetUserText(guid, "zone")
    score = float(rs.GetUserText(guid, "solar_score") or "0.5")
"""

import math
import os
import threading

import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import System.Drawing as sd

import Eto.Drawing as drawing
import Eto.Forms as forms


# =========================================================================
#  EPW PATH
# =========================================================================
_EPW_CANDIDATES = [
    r"D:\RMIT_SEM1 26_AI Accelerated Agentic Architecture TECTONIC\Week 2\EPW file-Ladybug\AUS_VIC_Melbourne.RO.948680_TMYx.epw",
]


def find_epw_path():
    for p in _EPW_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


# =========================================================================
#  CONSTANTS
# =========================================================================
MEL_LAT_DEG = -37.8136
_MONTH_DOY  = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]

MONTH_NAMES = [
    "January", "February", "March",    "April",   "May",      "June",
    "July",    "August",   "September","October",  "November", "December",
]

ZONE_COLORS = {
    "passive":    (30,  160, 200),   # blue-green  (well shaded)
    "marginal":   (240, 200, 50),    # yellow      (moderate exposure)
    "overheated": (220, 60,  30),    # orange-red  (high solar exposure)
}

_ZONE_LAYER = "CLIMATE_VOXELS"

_ZONE_SUBLAYERS = {
    "passive":    (_ZONE_LAYER + "::Passive",    30,  160, 200),
    "marginal":   (_ZONE_LAYER + "::Marginal",   240, 200, 50),
    "overheated": (_ZONE_LAYER + "::Overheated", 220, 60,  30),
}


# =========================================================================
#  EPW PARSE
# =========================================================================
def parse_epw_solar(filepath):
    monthly = {m: {"ghr": [], "dnr": [], "dhr": [], "temp": []} for m in range(1, 13)}
    try:
        with open(filepath, "r") as f:
            for line in f:
                if not line or not line[0].isdigit():
                    continue
                parts = line.strip().split(",")
                if len(parts) < 16:
                    continue
                try:
                    m = int(parts[1])
                    monthly[m]["temp"].append(float(parts[6]))
                    monthly[m]["ghr"].append(float(parts[13]))
                    monthly[m]["dnr"].append(float(parts[14]))
                    monthly[m]["dhr"].append(float(parts[15]))
                except (ValueError, IndexError):
                    continue
    except Exception:
        return None
    profiles = {}
    for m in range(1, 13):
        d = monthly[m]
        n = max(len(d["ghr"]), 1)
        profiles[m] = {k: sum(d[k]) / n for k in ("ghr", "dnr", "dhr", "temp")}
    return profiles


# =========================================================================
#  SOLAR MATH
# =========================================================================
def solar_position(month_idx, hour_float):
    lat  = math.radians(MEL_LAT_DEG)
    doy  = _MONTH_DOY[month_idx - 1]
    decl = math.radians(23.45 * math.sin(math.radians(360.0 / 365.0 * (doy - 81))))
    ha   = math.radians((hour_float - 12.0) * 15.0)
    sin_alt = max(-1.0, min(1.0,
        math.sin(lat) * math.sin(decl) +
        math.cos(lat) * math.cos(decl) * math.cos(ha)))
    altitude = math.asin(sin_alt)
    cos_az = max(-1.0, min(1.0,
        (math.sin(decl) - math.sin(lat) * math.sin(altitude)) /
        (math.cos(lat) * math.cos(altitude) + 1e-9)))
    azimuth = math.acos(cos_az)
    if ha > 0:
        azimuth = 2.0 * math.pi - azimuth
    return math.degrees(azimuth), math.degrees(altitude)


# =========================================================================
#  VOXEL LOADING
# =========================================================================
def load_voxels(guids):
    """
    Build voxel list from selected GUIDs.
    Returns (voxel_list, voxel_size):
      voxel_list : [(guid, center Point3d, (ix, iy, iz)), ...]
      voxel_size : median bounding-box edge length
    """
    candidates = []
    for guid in guids:
        obj = sc.doc.Objects.FindId(guid)
        if not obj or obj.IsDeleted:
            continue
        bb = obj.Geometry.GetBoundingBox(True)
        if not bb.IsValid:
            continue
        sx  = bb.Max.X - bb.Min.X
        sy  = bb.Max.Y - bb.Min.Y
        sz  = bb.Max.Z - bb.Min.Z
        avg = (sx + sy + sz) / 3.0
        if avg < 1e-6:
            continue
        candidates.append((guid, bb.Center, avg))

    if not candidates:
        return [], 0.0

    sizes      = sorted(c[2] for c in candidates)
    voxel_size = sizes[len(sizes) // 2]

    voxel_list = []
    for (guid, center, _) in candidates:
        ix = int(round(center.X / voxel_size))
        iy = int(round(center.Y / voxel_size))
        iz = int(round(center.Z / voxel_size))
        voxel_list.append((guid, center, (ix, iy, iz)))

    return voxel_list, voxel_size


# =========================================================================
#  SOLAR SCORING  (3-D ray-march, EPW-weighted, 30-min samples)
# =========================================================================
def _build_sun_samples(month_idx, solar_profile=None, intensity=1.0):
    """
    Build weighted sun-direction samples at 30-min intervals (8:00–16:30).

    Weighting per sample:
      w = (DNR * sin(alt) + DHR * 0.5) * intensity   if EPW data available
      w = sin(alt) * intensity                         fallback (altitude only)

    intensity : float multiplier (0.1 = overcast/weak, 1.0 = EPW default, 2.0 = very intense)
    Returns list of (dx, dy, dz, weight) — weights normalised to sum=1.
    The intensity scales the raw radiation before normalisation, so it affects
    zone thresholds (high intensity → more voxels flip to overheated).
    """
    samples = []
    dnr = (solar_profile["dnr"] if solar_profile else 500.0) * max(intensity, 0.01)
    dhr = (solar_profile["dhr"] if solar_profile else 150.0) * max(intensity, 0.01)

    for hh in range(16, 34):           # 8.0, 8.5 … 16.5
        hour = hh * 0.5
        az, alt = solar_position(month_idx, hour)
        if alt <= 5.0:
            continue
        az_r  = math.radians(az)
        alt_r = math.radians(alt)
        dx = math.sin(az_r) * math.cos(alt_r)
        dy = math.cos(az_r) * math.cos(alt_r)
        dz = math.sin(alt_r)
        h_len = math.sqrt(dx * dx + dy * dy) + 1e-9
        w = dnr * math.sin(alt_r) + dhr * 0.5
        samples.append((dx / h_len, dy / h_len, dz / h_len, max(w, 1e-6)))

    if not samples:
        return []

    total = sum(s[3] for s in samples)
    return [(dx, dy, dz, w / total) for (dx, dy, dz, w) in samples]


def compute_solar_scores(voxel_list, month_idx,
                         solar_profiles=None, intensity=1.0, stop_check=None):
    """
    3-D ray-march solar analysis.

    Improvements over V3.0:
      - 30-min time samples (up to 17 per day vs 9)
      - EPW radiation weighting: each direction weighted by
        DNR × sin(alt) + DHR × 0.5  (beam + diffuse contribution)
      - Altitude weighting fallback when no EPW data

    voxel_list    : [(guid, center Point3d, (ix, iy, iz)), ...]
    month_idx     : 1–12
    solar_profiles: dict from parse_epw_solar(), or None
    stop_check    : callable () -> bool

    Returns {guid: solar_score 0-1}
            where 1.0 = maximum possible radiation for this month
    """
    occupancy = set(ijk for (_, _, ijk) in voxel_list)

    sp      = solar_profiles.get(month_idx) if solar_profiles else None
    samples = _build_sun_samples(month_idx, sp, intensity)

    if not samples:
        return {guid: 0.5 for (guid, _, _) in voxel_list}

    max_steps = 80

    scores = {}
    for (guid, _, (ix, iy, iz)) in voxel_list:
        if stop_check and stop_check():
            break
        weighted_exposed = 0.0
        for (dx, dy, dz, w) in samples:
            rx = ix + dx * 0.55
            ry = iy + dy * 0.55
            rz = iz + dz * 0.55
            shaded = False
            for _ in range(max_steps):
                tix = int(round(rx))
                tiy = int(round(ry))
                tiz = int(round(rz))
                if (tix, tiy, tiz) in occupancy:
                    shaded = True
                    break
                if (abs(tix - ix) > max_steps or
                        abs(tiy - iy) > max_steps or
                        abs(tiz - iz) > max_steps):
                    break
                rx += dx; ry += dy; rz += dz
            if not shaded:
                weighted_exposed += w
        scores[guid] = weighted_exposed   # already 0–1 (weights sum to 1)

    return scores


def compute_seasonal_scores(voxel_list, solar_profiles, intensity=1.0, stop_check=None):
    """
    Run scoring for January (peak summer) and July (mid-winter).
    Returns {guid: {"summer": s, "winter": w, "score": weighted avg}}
    where score = summer×0.6 + winter×0.4.
    """
    summer = compute_solar_scores(voxel_list, 1, solar_profiles, intensity, stop_check)
    if stop_check and stop_check():
        return {}
    winter = compute_solar_scores(voxel_list, 7, solar_profiles, intensity, stop_check)

    combined = {}
    for (guid, _, _) in voxel_list:
        s = summer.get(guid, 0.5)
        w = winter.get(guid, 0.5)
        combined[guid] = {"summer": s, "winter": w, "score": s * 0.6 + w * 0.4}
    return combined


def compute_annual_scores(voxel_list, solar_profiles, intensity=1.0, stop_check=None):
    """
    Run scoring for all 12 months and return the average per voxel.
    Returns {guid: score 0-1}
    """
    accumulator = {}
    for month in range(1, 13):
        if stop_check and stop_check():
            return {}
        month_scores = compute_solar_scores(
            voxel_list, month, solar_profiles, intensity, stop_check)
        for guid, s in month_scores.items():
            accumulator[guid] = accumulator.get(guid, 0.0) + s
    return {guid: total / 12.0 for guid, total in accumulator.items()}


# =========================================================================
#  ZONE CLASSIFICATION
# =========================================================================
def zone_from_solar(solar_score):
    """
    Returns (zone, thermal_comfort, daylight_score).
    All scores are 0–100.
    """
    thermal  = round((1.0 - solar_score) * 100.0, 1)
    daylight = round(solar_score          * 100.0, 1)
    if solar_score > 0.65:
        zone = "overheated"
    elif solar_score > 0.35:
        zone = "marginal"
    else:
        zone = "passive"
    return zone, thermal, daylight


def zone_stats(zone_map):
    counts = {"passive": 0, "marginal": 0, "overheated": 0}
    for z in zone_map.values():
        counts[z] = counts.get(z, 0) + 1
    total = max(sum(counts.values()), 1)
    return {k: v / total for k, v in counts.items()}


# =========================================================================
#  CUBE MESH
# =========================================================================
def build_cube_mesh(cx, cy, cz, size):
    h = size * 0.48
    m = rg.Mesh()
    verts = [
        (cx-h, cy-h, cz-h), (cx+h, cy-h, cz-h),
        (cx+h, cy+h, cz-h), (cx-h, cy+h, cz-h),
        (cx-h, cy-h, cz+h), (cx+h, cy-h, cz+h),
        (cx+h, cy+h, cz+h), (cx-h, cy+h, cz+h),
    ]
    for (x, y, z) in verts:
        m.Vertices.Add(x, y, z)
    for face in [(0,1,2,3),(4,5,6,7),(0,1,5,4),(2,3,7,6),(0,3,7,4),(1,2,6,5)]:
        m.Faces.AddFace(*face)
    m.Normals.ComputeNormals()
    return m


# =========================================================================
#  SLIDER WIDGET
# =========================================================================
class SliderNumPair(object):
    def __init__(self, lo, hi, default, scale=10, decimals=1):
        self._scale    = scale
        self._decimals = decimals
        self._lo = lo; self._hi = hi
        self.slider          = forms.Slider()
        self.slider.MinValue = int(lo * scale)
        self.slider.MaxValue = int(hi * scale)
        self.slider.Value    = int(default * scale)
        self.textbox         = forms.TextBox()
        self.textbox.Width   = 52
        self.textbox.Text    = ("%%.%df" % decimals) % default
        self.slider.ValueChanged += self._on_slide
        self.textbox.TextChanged += self._on_type

    def _on_slide(self, s, e):
        self.textbox.Text = ("%%.%df" % self._decimals) % (self.slider.Value / float(self._scale))

    def _on_type(self, s, e):
        try:
            v = max(self._lo, min(self._hi, float(self.textbox.Text)))
            self.slider.Value = int(v * self._scale)
        except ValueError:
            pass

    @property
    def value(self):
        return self.slider.Value / float(self._scale)


# =========================================================================
#  GUI
# =========================================================================
class ClimateV3GUI(forms.Form):

    def __init__(self, solar_profiles):
        super().__init__()
        self.Title      = u"Climate Comfort  V3  \u2014  Solar"
        self.ClientSize = drawing.Size(440, 520)
        self.Padding    = drawing.Padding(10)
        self.Resizable  = True

        self._solar_profiles  = solar_profiles

        # ── State ─────────────────────────────────────────────────────────
        self._voxel_list      = []   # [(guid, center Point3d, (ix,iy,iz)), ...]
        self._voxel_size      = 0.0
        self._solar_scores    = {}   # {guid: float 0-1}
        self._zone_map        = {}   # {guid: zone_str}
        self._baked_ids       = []   # GUIDs added by last Bake

        self._running         = False
        self._stop_requested  = False
        self._thread_done     = False
        self._thread_status   = u""
        self._thread_error    = None
        self._poll_timer      = None

        # ── Widgets ───────────────────────────────────────────────────────
        self.btn_load = forms.Button()
        self.btn_load.Text = u"Load Selected Voxels"
        self.btn_load.Click += self._on_load

        self.lbl_voxels = forms.Label()
        self.lbl_voxels.Text = u"Voxels: none"

        self.month_combo = forms.ComboBox()
        self.month_combo.DataStore = MONTH_NAMES
        self.month_combo.SelectedIndex = 0
        self.month_combo.SelectedIndexChanged += self._on_month_changed

        self.mode_combo = forms.ComboBox()
        self.mode_combo.DataStore = [u"Single month",
                                     u"Summer + Winter  (Jan & Jul avg)",
                                     u"Annual Average  (all 12 months)"]
        self.mode_combo.SelectedIndex = 0
        self.mode_combo.SelectedIndexChanged += self._on_mode_changed

        self.lbl_epw = forms.Label()
        self.lbl_epw.Text = u"EPW: loading..."

        self._seasonal_scores = {}   # {guid: {"summer":, "winter":, "score":}}

        self.sl_intensity = SliderNumPair(0.1, 3.0, 1.0, scale=10, decimals=1)

        self.btn_run = forms.Button()
        self.btn_run.Text = u"\u25b6 Run Solar Analysis"
        self.btn_run.Click += self._on_run

        self.btn_stop = forms.Button()
        self.btn_stop.Text = u"\u25a0 Stop"
        self.btn_stop.Click += self._on_stop

        self.lbl_result = forms.Label()
        self.lbl_result.Text = u""

        self.btn_bake = forms.Button()
        self.btn_bake.Text = u"Bake Climate Voxels"
        self.btn_bake.Click += self._on_bake

        self.btn_close = forms.Button()
        self.btn_close.Text = u"Close"
        self.btn_close.Click += lambda s, e: self.Close()

        self.lbl_stat = forms.Label()
        self.lbl_stat.Text = u"Window-select voxels in viewport, then click Load."

        self._build_layout()
        self._update_epw_label()

    # ── Layout ───────────────────────────────────────────────────────────────
    def _build_layout(self):
        lay = forms.DynamicLayout()
        lay.Spacing = drawing.Size(4, 5)

        def sep(txt=""):
            lbl = forms.Label()
            lbl.Text = (u"-- " + txt + u" --") if txt else u"--"
            lay.AddRow(lbl)

        def note(txt):
            lbl = forms.Label()
            lbl.Text = txt
            lbl.TextColor = drawing.Color.FromArgb(110, 110, 110)
            lay.AddRow(lbl)

        # 1 — Input
        sep(u"1 \u2014 Voxel Input")
        note(u"Window-select your voxel field in the viewport, then click Load.")
        lay.AddRow(self.btn_load)
        lay.AddRow(self.lbl_voxels)

        # 2 — EPW
        sep(u"2 \u2014 EPW Climate  (Melbourne)")
        mrow = forms.DynamicLayout()
        mrow.Spacing = drawing.Size(4, 0)
        lm = forms.Label(); lm.Text = u"Month:"
        mrow.AddRow(lm, self.month_combo)
        lay.AddRow(mrow)
        lay.AddRow(self.lbl_epw)
        mdrow = forms.DynamicLayout()
        mdrow.Spacing = drawing.Size(4, 0)
        lmd = forms.Label(); lmd.Text = u"Mode:"
        mdrow.AddRow(lmd, self.mode_combo)
        lay.AddRow(mdrow)
        note(u"Summer+Winter: Jan+Jul (60/40 weight).  Annual: all 12 months averaged.")

        # 3 — Run
        sep(u"3 \u2014 Solar Analysis")
        note(u"EPW-weighted, 30-min samples, 3-D ray-march.  Voxels shadow each other.")
        irow = forms.DynamicLayout(); irow.Spacing = drawing.Size(4, 0)
        li = forms.Label(); li.Text = u"Sun intensity:"
        irow.AddRow(li, self.sl_intensity.slider, self.sl_intensity.textbox)
        lay.AddRow(irow)
        note(u"1.0 = EPW default.  <1.0 = overcast / cloudy.  >1.0 = harsh / desert sun.")
        rrow = forms.DynamicLayout()
        rrow.Spacing = drawing.Size(4, 0)
        rrow.AddRow(self.btn_run, self.btn_stop)
        lay.AddRow(rrow)
        lay.AddRow(self.lbl_result)

        # 4 — Output
        sep(u"4 \u2014 Output")
        note(u"Adds CLIMATE_VOXELS::Passive / Marginal / Overheated alongside originals.")
        note(u"Each voxel tagged: solar_score, zone, thermal_comfort, daylight_score.")
        orow = forms.DynamicLayout()
        orow.Spacing = drawing.Size(4, 0)
        orow.AddRow(self.btn_bake, self.btn_close)
        lay.AddRow(orow)

        lay.AddRow(None)
        lay.AddRow(self.lbl_stat)

        scroll = forms.Scrollable()
        scroll.Content = lay
        scroll.ExpandContentWidth = True
        self.Content = scroll

    # ── EPW / Mode ───────────────────────────────────────────────────────────
    def _on_month_changed(self, s, e):
        self._update_epw_label()

    def _on_mode_changed(self, s, e):
        single = self.mode_combo.SelectedIndex == 0
        self.month_combo.Enabled = single

    def _update_epw_label(self):
        mi = self.month_combo.SelectedIndex + 1
        if self._solar_profiles and mi in self._solar_profiles:
            sp = self._solar_profiles[mi]
            self.lbl_epw.Text = (u"EPW \u2014 Temp %.1f\u00b0C  |  GHR %d W/m\u00b2  |  DNR %d W/m\u00b2"
                                 % (sp["temp"], int(sp["ghr"]), int(sp["dnr"])))
        else:
            self.lbl_epw.Text = u"EPW \u2014 no data  (solar position from Melbourne latitude)"

    # ── Load ─────────────────────────────────────────────────────────────────
    def _on_load(self, s, e):
        guids = rs.SelectedObjects()
        if not guids:
            self.lbl_stat.Text = u"No selection. Window-select voxels first, then click Load."
            return

        voxel_list, voxel_size = load_voxels(guids)
        if not voxel_list:
            self.lbl_stat.Text = u"No valid geometry in selection."; return

        self._voxel_list   = voxel_list
        self._voxel_size   = voxel_size
        self._solar_scores = {}
        self._zone_map     = {}

        # Summarise which layers are loaded
        layer_names = set()
        for (guid, _, _) in voxel_list:
            obj = sc.doc.Objects.FindId(guid)
            if obj:
                layer_names.add(sc.doc.Layers[obj.Attributes.LayerIndex].Name)

        self.lbl_voxels.Text = (u"%d voxels  |  size \u2248 %.2f m  |  %s"
                                % (len(voxel_list), voxel_size,
                                   u", ".join(sorted(layer_names)[:5])))
        self.lbl_stat.Text = u"Loaded. Pick month and click Run Solar Analysis."

    # ── Run ──────────────────────────────────────────────────────────────────
    def _on_run(self, s, e):
        if not self._voxel_list:
            self.lbl_stat.Text = u"Load voxels first."; return
        if self._running:
            self.lbl_stat.Text = u"Already running \u2014 press Stop first."; return

        month      = self.month_combo.SelectedIndex + 1
        mode_idx   = self.mode_combo.SelectedIndex
        seasonal   = mode_idx == 1
        annual     = mode_idx == 2
        intensity  = float(self.sl_intensity.value)
        voxel_list = list(self._voxel_list)
        profiles   = self._solar_profiles

        # Count how many 30-min samples will be used (for status message)
        sp = profiles.get(month) if profiles else None
        n_samples = len(_build_sun_samples(month, sp, intensity))

        self._running         = True
        self._stop_requested  = False
        self._thread_done     = False
        self._thread_error    = None
        self._seasonal_scores = {}
        self._thread_status   = u"Preparing\u2026"
        self.btn_run.Enabled  = False
        self.lbl_result.Text  = u""
        self.lbl_stat.Text    = u"Solar analysis running \u2014 viewport is free."
        Rhino.RhinoApp.Wait()

        me = self

        def _run():
            try:
                n = len(voxel_list)
                if seasonal:
                    me._thread_status = (
                        u"Seasonal: ray-marching %d voxels \u00d7 2 months  (intensity %.1f)\u2026"
                        % (n, intensity))
                    seas = compute_seasonal_scores(
                        voxel_list, profiles or {}, intensity,
                        stop_check=lambda: me._stop_requested)
                    if not me._stop_requested:
                        me._seasonal_scores = seas
                        me._solar_scores = {g: v["score"] for g, v in seas.items()}
                        me._zone_map = {g: zone_from_solar(v["score"])[0]
                                        for g, v in seas.items()}
                elif annual:
                    me._thread_status = (
                        u"Annual: ray-marching %d voxels \u00d7 12 months  (intensity %.1f)\u2026"
                        % (n, intensity))
                    scores = compute_annual_scores(
                        voxel_list, profiles or {}, intensity,
                        stop_check=lambda: me._stop_requested)
                    if not me._stop_requested:
                        me._solar_scores = scores
                        me._zone_map = {g: zone_from_solar(s)[0]
                                        for g, s in scores.items()}
                else:
                    me._thread_status = (
                        u"Ray-marching %d voxels \u00d7 %d directions  (intensity %.1f)\u2026"
                        % (n, n_samples, intensity))
                    scores = compute_solar_scores(
                        voxel_list, month, profiles, intensity,
                        stop_check=lambda: me._stop_requested)
                    if not me._stop_requested:
                        me._solar_scores = scores
                        me._zone_map = {g: zone_from_solar(s)[0]
                                        for g, s in scores.items()}
            except Exception as ex:
                me._thread_error = str(ex)
            finally:
                me._thread_done = True

        t = threading.Thread(target=_run)
        t.daemon = True
        t.start()

        if self._poll_timer:
            try: self._poll_timer.Stop()
            except Exception: pass
        self._poll_timer = forms.UITimer()
        self._poll_timer.Interval = 0.2
        self._poll_timer.Elapsed += self._on_poll
        self._poll_timer.Start()

    def _on_stop(self, s, e):
        self._stop_requested = True

    def _on_poll(self, s, e):
        self.lbl_stat.Text = self._thread_status
        if not self._thread_done:
            return
        self._poll_timer.Stop()
        self._poll_timer  = None
        self._running     = False
        self.btn_run.Enabled = True

        if self._thread_error:
            self.lbl_stat.Text = u"Error: " + self._thread_error; return
        if self._stop_requested:
            self.lbl_stat.Text = u"Stopped."; return

        st       = zone_stats(self._zone_map)
        mode_idx = self.mode_combo.SelectedIndex
        if mode_idx == 1:   mode_lbl = u"Summer+Winter"
        elif mode_idx == 2: mode_lbl = u"Annual Average"
        else:               mode_lbl = MONTH_NAMES[self.month_combo.SelectedIndex]
        self.lbl_result.Text = (
            u"%s \u2014  Passive %d%%  |  Marginal %d%%  |  Overheated %d%%" % (
            mode_lbl,
            int(st["passive"]    * 100),
            int(st["marginal"]   * 100),
            int(st["overheated"] * 100)))
        self.lbl_stat.Text = u"Done. Click 'Bake Climate Voxels' to write to document."

    # ── Bake ─────────────────────────────────────────────────────────────────
    def _on_bake(self, s, e):
        if not self._solar_scores:
            self.lbl_stat.Text = u"Run Solar Analysis first."; return

        seasonal   = self.mode_combo.SelectedIndex == 1
        annual     = self.mode_combo.SelectedIndex == 2
        if seasonal:
            month_name = u"Summer+Winter"
        elif annual:
            month_name = u"Annual Average"
        else:
            month_name = MONTH_NAMES[self.month_combo.SelectedIndex]

        # Approximate peak daily radiation for reference (Wh/m²)
        sp = (self._solar_profiles.get(self.month_combo.SelectedIndex + 1)
              if self._solar_profiles and not seasonal and not annual else None)
        ghr_ref = sp["ghr"] if sp else 300.0   # W/m² monthly avg GHR

        # Remove previous bake
        if self._baked_ids:
            try: rs.DeleteObjects(self._baked_ids)
            except Exception: pass
            self._baked_ids = []

        # Ensure layers exist
        if not rs.IsLayer(_ZONE_LAYER):
            rs.AddLayer(_ZONE_LAYER)
        for zone, (ln, r, g, b) in _ZONE_SUBLAYERS.items():
            if not rs.IsLayer(ln):
                rs.AddLayer(ln, sd.Color.FromArgb(r, g, b))

        rs.EnableRedraw(False)
        baked = 0

        for (guid, center, _) in self._voxel_list:
            score            = self._solar_scores.get(guid, 0.5)
            zone, thermal, daylight = zone_from_solar(score)
            ln               = _ZONE_SUBLAYERS[zone][0]
            li               = sc.doc.Layers.FindByFullPath(ln, -1)
            rgb              = ZONE_COLORS[zone]

            m   = build_cube_mesh(center.X, center.Y, center.Z, self._voxel_size)
            oid = sc.doc.Objects.AddMesh(m)
            if not oid:
                continue

            # Colour + layer
            rs.ObjectColor(oid, rgb)
            obj = sc.doc.Objects.Find(oid)
            if obj and li >= 0:
                attr            = obj.Attributes.Duplicate()
                attr.LayerIndex = li
                sc.doc.Objects.ModifyAttributes(obj, attr, True)

            # Embed climate data as Object User Text
            rs.SetUserText(oid, "solar_score",      str(round(score, 4)))
            rs.SetUserText(oid, "zone",              zone)
            rs.SetUserText(oid, "thermal_comfort",   str(thermal))
            rs.SetUserText(oid, "daylight_score",    str(daylight))
            rs.SetUserText(oid, "epw_month",         month_name)
            rs.SetUserText(oid, "sun_intensity",     str(round(
                float(self.sl_intensity.value), 2)))
            # Approximate daily radiation exposure (Wh/m²)
            radiation_wh = round(score * ghr_ref * 8.0, 0)
            rs.SetUserText(oid, "radiation_wh",      str(radiation_wh))
            # Seasonal breakdown (only when seasonal mode was used)
            seas = self._seasonal_scores.get(guid)
            if seas:
                rs.SetUserText(oid, "solar_score_summer", str(round(seas["summer"], 4)))
                rs.SetUserText(oid, "solar_score_winter", str(round(seas["winter"], 4)))

            self._baked_ids.append(oid)
            baked += 1

        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()
        self.lbl_stat.Text = (
            u"Baked %d voxels \u2192 %s::  (originals unchanged)" % (baked, _ZONE_LAYER))


# =========================================================================
#  MAIN
# =========================================================================
def main():
    epw_path       = find_epw_path()
    solar_profiles = parse_epw_solar(epw_path) if epw_path else None

    dialog = ClimateV3GUI(solar_profiles)
    dialog.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    dialog.Show()

    while not dialog.IsDisposed:
        Rhino.RhinoApp.Wait()

    sc.doc.Views.Redraw()
    print(u"Climate Comfort Agent V3 \u2014 done.")


if __name__ == "__main__":
    main()
