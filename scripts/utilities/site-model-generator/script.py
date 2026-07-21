"""
Site Model Generator for Rhino 8 (CPython 3) — V.2
=============================================
Generates a 3D site model with real building Brep bounding boxes
from a Google Maps location using OpenStreetMap data.

Usage:
    Open in Rhino 8 ScriptEditor and Run.
    Paste any of these when prompted:
      - Google Maps URL:  https://www.google.com/maps/place/.../@-37.806,144.962,...
      - DMS coordinates:  37°48'24.0"S 144°57'51.6"E
      - Decimal coords:   -37.806678, 144.964323

Data source:
    OpenStreetMap Overpass API (free, no API key needed).
    Building heights come from OSM tags:
      1. 'height' tag       -> exact measured height (best)
      2. 'building:levels'  -> floors * level_height (good estimate)
      3. fallback           -> default_height (rough guess)

Version history:
    V.1  -- Millimeters full-scale (1 m real = 1000 mm model)
    V.2  -- 1:1000 scale (1 m real = 1 mm model, Rhino document in Millimeters)
            Before running: File > Properties > Units > Absolute tolerance = 0.001 mm
"""

import urllib.request
import urllib.parse
import json
import math
import re
import System

import Rhino
import Rhino.Geometry as rg
import Rhino.DocObjects as rd
import scriptcontext as sc

# ---------------------------------------------------------------------------
# CONFIGURATION — edit these or let the dialog override them
# ---------------------------------------------------------------------------
CONFIG = {
    "latitude":        0.0,       # set via dialog
    "longitude":       0.0,       # set via dialog
    "radius_m":        500.0,     # search radius in metres
    "unit":            "Millimeters 1:1000",  # Meters | Feet | Millimeters | Millimeters 1:1000
    # NOTE: For 1:1000 scale set Rhino tolerance to 0.001 mm before running
    "default_height":  10.0,      # fallback building height (m) ~3 stories
    "level_height":    3.2,       # assumed floor-to-floor height (m)
    "min_area":        20.0,      # skip buildings smaller than this (m²)
    "ground_plane":    True,      # generate circular ground surface
}

UNIT_SCALES = {
    "Meters":             1.0,
    "Feet":               3.28084,
    "Millimeters":        1000.0,        # V.1 full scale (kept for compatibility)
    "Millimeters 1:1000": 1.0,           # V.2 default: 1 m real = 1 mm model
}

# ---------------------------------------------------------------------------
# COORDINATE PARSING — DMS, decimal, or Google Maps URL
# ---------------------------------------------------------------------------
def parse_dms(dms_str):
    """Parse a DMS string like 37°48'24.0"S 144°57'51.6"E into (lat, lon).
    Also handles formats like:
      37°48'24.0"S, 144°57'51.6"E
      37 48 24.0 S 144 57 51.6 E
      -37.806678, 144.964323  (decimal passthrough)
    """
    # Try decimal pair first: -37.806678, 144.964323
    decimal_match = re.match(
        r'^[,\s]*(-?\d+\.?\d*)[,\s]+(-?\d+\.?\d*)\s*$', dms_str.strip()
    )
    if decimal_match:
        return float(decimal_match.group(1)), float(decimal_match.group(2))

    # DMS pattern: captures degrees, minutes, seconds, direction
    dms_pattern = r"""(\d+)\s*[°d]\s*(\d+)\s*[\'′']\s*([\d.]+)\s*[\"″"]\s*([NSns])
                      \s*[,\s]\s*
                      (\d+)\s*[°d]\s*(\d+)\s*[\'′']\s*([\d.]+)\s*[\"″"]\s*([EWew])"""

    match = re.match(dms_pattern, dms_str.strip(), re.VERBOSE)
    if match:
        lat_d, lat_m, lat_s, lat_dir = match.groups()[:4]
        lon_d, lon_m, lon_s, lon_dir = match.groups()[4:]

        lat = float(lat_d) + float(lat_m) / 60.0 + float(lat_s) / 3600.0
        lon = float(lon_d) + float(lon_m) / 60.0 + float(lon_s) / 3600.0

        if lat_dir.upper() == 'S':
            lat = -lat
        if lon_dir.upper() == 'W':
            lon = -lon

        return lat, lon

    return None


def parse_google_maps_url(url):
    """Extract lat/lon from a Google Maps URL.
    Handles formats like:
      https://www.google.com/maps/place/.../@-37.8064576,144.9622355,...
      https://www.google.com/maps?q=-37.806678,144.964323
      https://maps.google.com/.../@-37.806,144.962,...
      https://goo.gl/maps/...  (won't resolve short links)
    Also extracts DMS from the URL path (e.g. 37%C2%B048'24.0%22S+...)
    """
    # Decode URL-encoded characters
    decoded = urllib.parse.unquote(url)

    # Pattern 1: /@lat,lon in the URL path
    at_match = re.search(r'/@(-?\d+\.?\d+),(-?\d+\.?\d+)', decoded)
    if at_match:
        return float(at_match.group(1)), float(at_match.group(2))

    # Pattern 2: ?q=lat,lon or &ll=lat,lon
    q_match = re.search(r'[?&](?:q|ll|center)=(-?\d+\.?\d+),(-?\d+\.?\d+)', decoded)
    if q_match:
        return float(q_match.group(1)), float(q_match.group(2))

    # Pattern 3: !3d(lat)!4d(lon) in data params
    data_match = re.search(r'!3d(-?\d+\.?\d+)!4d(-?\d+\.?\d+)', decoded)
    if data_match:
        return float(data_match.group(1)), float(data_match.group(2))

    # Pattern 4: DMS in URL path like 37°48'24.0"S+144°57'51.6"E
    dms_in_url = re.search(
        r'(\d+°\d+\'\d+\.?\d*"[NS])\s*\+?\s*(\d+°\d+\'\d+\.?\d*"[EW])',
        decoded
    )
    if dms_in_url:
        combined = f"{dms_in_url.group(1)} {dms_in_url.group(2)}"
        return parse_dms(combined)

    return None


def parse_location_input(text):
    """Parse any location input: DMS, decimal, or Google Maps URL.
    Returns (lat, lon) or None.
    """
    text = text.strip()

    # Check if it's a URL
    if "google.com/maps" in text or "maps.google" in text or "goo.gl/maps" in text:
        result = parse_google_maps_url(text)
        if result:
            return result

    # Try DMS or decimal
    result = parse_dms(text)
    if result:
        return result

    return None


# ---------------------------------------------------------------------------
# USER INPUT DIALOG
# ---------------------------------------------------------------------------
def get_user_input():
    """Prompt user for location and configuration via Rhino dialogs."""

    # --- Location (DMS, decimal, or Google Maps URL) ---
    # Use Eto dialog instead of command line because Rhino's command line
    # splits input at spaces, breaking DMS like "37°48'24.0"S 144°57'51.6"E"
    import Eto.Forms as ef
    import Eto.Drawing as ed

    dialog = ef.Dialog()
    dialog.Title = "Site Model Generator — Enter Location"
    dialog.Padding = ed.Padding(20)
    dialog.MinimumSize = ed.Size(560, 200)

    layout = ef.DynamicLayout()
    layout.Spacing = ed.Size(5, 5)

    lbl = ef.Label()
    lbl.Text = "Paste a Google Maps URL, DMS, or decimal coordinates:"
    layout.AddRow(lbl)

    text_box = ef.TextBox()
    text_box.PlaceholderText = '37\u00b048\'24.0"S 144\u00b057\'51.6"E  or  Google Maps URL'
    text_box.Width = 520
    layout.AddRow(text_box)

    hint = ef.Label()
    hint.Text = 'Formats:  37\u00b048\'24.0"S 144\u00b057\'51.6"E  |  -37.806678, 144.964323  |  Google Maps URL'
    hint.TextColor = ed.Colors.Gray
    layout.AddRow(hint)

    ok_btn = ef.Button()
    ok_btn.Text = "OK"
    cancel_btn = ef.Button()
    cancel_btn.Text = "Cancel"

    # Store result in a mutable container since lambdas can't assign outer vars
    dialog_result = [False]
    def on_ok(sender, e):
        dialog_result[0] = True
        dialog.Close()
    def on_cancel(sender, e):
        dialog.Close()
    ok_btn.Click += on_ok
    cancel_btn.Click += on_cancel

    layout.AddRow(None)
    layout.BeginHorizontal()
    layout.AddRow(None, cancel_btn, ok_btn)
    layout.EndHorizontal()

    dialog.Content = layout
    dialog.DefaultButton = ok_btn
    dialog.AbortButton = cancel_btn

    dialog.ShowModal(Rhino.UI.RhinoEtoApp.MainWindow)

    if not dialog_result[0] or not text_box.Text.strip():
        return False

    parsed = parse_location_input(text_box.Text)
    if parsed is None:
        Rhino.RhinoApp.WriteLine("Error: Could not parse location. Accepted formats:")
        Rhino.RhinoApp.WriteLine("  DMS:     37°48'24.0\"S 144°57'51.6\"E")
        Rhino.RhinoApp.WriteLine("  Decimal: -37.806678, 144.964323")
        Rhino.RhinoApp.WriteLine("  URL:     https://www.google.com/maps/place/.../@-37.806,144.962,...")
        return False

    CONFIG["latitude"] = parsed[0]
    CONFIG["longitude"] = parsed[1]
    Rhino.RhinoApp.WriteLine(f"  Parsed location: {parsed[0]:.6f}, {parsed[1]:.6f}")

    # --- Radius ---
    rad = Rhino.Input.RhinoGet.GetNumber(
        "Search radius in metres", False, CONFIG["radius_m"]
    )
    if rad[0] == Rhino.Commands.Result.Success:
        CONFIG["radius_m"] = rad[1]

    # --- Unit system ---
    unit_keys = ["Meters", "Feet", "Millimeters", "Millimeters 1:1000"]
    gi = Rhino.Input.Custom.GetOption()
    gi.SetCommandPrompt("Choose output unit system (Millimeters1to1000 = 1:1000 scale, 1m=1mm)")
    gi.AddOption("Meters")
    gi.AddOption("Feet")
    gi.AddOption("Millimeters")
    gi.AddOption("Millimeters1to1000")
    gi.Get()
    if gi.Result() == Rhino.Input.GetResult.Option:
        CONFIG["unit"] = unit_keys[gi.Option().Index - 1]

    # --- Default building height ---
    dh = Rhino.Input.RhinoGet.GetNumber(
        "Default building height in metres (fallback when OSM has no data)",
        False, CONFIG["default_height"]
    )
    if dh[0] == Rhino.Commands.Result.Success:
        CONFIG["default_height"] = dh[1]

    # --- Level height ---
    lh = Rhino.Input.RhinoGet.GetNumber(
        "Floor-to-floor height in metres (for level-based estimation)",
        False, CONFIG["level_height"]
    )
    if lh[0] == Rhino.Commands.Result.Success:
        CONFIG["level_height"] = lh[1]

    # --- Min area filter ---
    ma = Rhino.Input.RhinoGet.GetNumber(
        "Minimum building footprint area in m² (skip smaller)",
        False, CONFIG["min_area"]
    )
    if ma[0] == Rhino.Commands.Result.Success:
        CONFIG["min_area"] = ma[1]

    return True


# ---------------------------------------------------------------------------
# ROAD WIDTH DEFAULTS (metres, one-side half-width from centreline)
# ---------------------------------------------------------------------------
ROAD_WIDTHS = {
    # Roadways
    "motorway":        8.0,
    "motorway_link":   5.0,
    "trunk":           7.0,
    "trunk_link":      4.5,
    "primary":         6.0,
    "primary_link":    4.0,
    "secondary":       5.5,
    "secondary_link":  3.5,
    "tertiary":        5.0,
    "tertiary_link":   3.0,
    "residential":     4.0,
    "living_street":   3.0,
    "service":         2.5,
    "unclassified":    3.5,
    # Pedestrian / Sidewalk
    "footway":         1.5,
    "pedestrian":      3.0,
    "path":            1.2,
    "cycleway":        1.5,
    "steps":           1.5,
    "sidewalk":        1.8,   # virtual — mapped from sidewalk tags
}

# Layer colour per road category (R, G, B)
ROAD_LAYER_COLORS = {
    "Motorway":     (60,  60,  60),
    "Primary":      (90,  90,  90),
    "Secondary":    (120, 120, 120),
    "Tertiary":     (150, 150, 150),
    "Residential":  (170, 170, 170),
    "Service":      (190, 190, 190),
    "Sidewalk":     (210, 180, 140),
    "Footway":      (200, 170, 120),
    "Cycleway":     (130, 190, 130),
    "Other":        (180, 180, 180),
}

# Map OSM highway values -> layer bucket
def _road_bucket(highway_val):
    """Return the layer sub-name for a highway tag value."""
    mapping = {
        "motorway": "Motorway", "motorway_link": "Motorway",
        "trunk": "Primary", "trunk_link": "Primary",
        "primary": "Primary", "primary_link": "Primary",
        "secondary": "Secondary", "secondary_link": "Secondary",
        "tertiary": "Tertiary", "tertiary_link": "Tertiary",
        "residential": "Residential", "living_street": "Residential",
        "unclassified": "Residential",
        "service": "Service",
        "footway": "Footway", "pedestrian": "Footway", "path": "Footway",
        "steps": "Footway",
        "cycleway": "Cycleway",
    }
    return mapping.get(highway_val, "Other")


# ---------------------------------------------------------------------------
# OVERPASS API — fetch road & sidewalk data from OpenStreetMap
# ---------------------------------------------------------------------------
def fetch_roads(lat, lon, radius_m):
    """Query OSM Overpass API for roads and sidewalks within radius.
    Returns a list of dicts: nodes, highway_type, name, width, etc.
    """
    overpass_url = "https://overpass-api.de/api/interpreter"

    query = f"""
    [out:json][timeout:60];
    (
      way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|living_street|service|unclassified|footway|pedestrian|path|cycleway|steps)$"](around:{radius_m},{lat},{lon});
    );
    out body;
    >;
    out skel qt;
    """

    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(overpass_url, data=data, method="POST")
    req.add_header("User-Agent", "RhinoSiteModelGenerator/1.0")

    Rhino.RhinoApp.WriteLine("Fetching road/path data from OpenStreetMap...")

    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    node_lookup = {}
    for el in result.get("elements", []):
        if el["type"] == "node":
            node_lookup[el["id"]] = (el["lat"], el["lon"])

    roads = []
    for el in result.get("elements", []):
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        if "highway" not in tags:
            continue

        nodes = el.get("nodes", [])
        coords = []
        for nid in nodes:
            if nid in node_lookup:
                coords.append(node_lookup[nid])

        if len(coords) < 2:
            continue

        highway_val = tags["highway"]

        # Parse explicit width from OSM if available
        width = None
        if "width" in tags:
            try:
                width = float(tags["width"].replace("m", "").strip())
            except ValueError:
                pass

        if width is None:
            width = ROAD_WIDTHS.get(highway_val, 3.0) * 2  # full width

        roads.append({
            "coords":       coords,
            "highway":      highway_val,
            "name":         tags.get("name", ""),
            "width":        width,
            "osm_id":       el["id"],
            "bucket":       _road_bucket(highway_val),
        })

    Rhino.RhinoApp.WriteLine(f"  Found {len(roads)} roads/paths.")
    return roads


# ---------------------------------------------------------------------------
# ROAD GEOMETRY — build closed outline curve per road strip,
#   then CurveBooleanUnion all overlapping outlines, then make planar srf.
# ---------------------------------------------------------------------------
def _road_outline_curve(coords, width_m, origin_lat, origin_lon, scale):
    """Turn a list of (lat,lon) into a closed planar outline curve
    representing the road strip of the given width.
    Returns a closed Curve or None.
    """
    half_w = (width_m / 2.0) * scale
    tol = sc.doc.ModelAbsoluteTolerance

    # Build centreline points
    cpts = []
    for lat, lon in coords:
        x, y = latlon_to_xy(lat, lon, origin_lat, origin_lon)
        cpts.append(rg.Point3d(x * scale, y * scale, 0.0))

    if len(cpts) < 2:
        return None

    # Remove duplicate consecutive points
    clean = [cpts[0]]
    for p in cpts[1:]:
        if p.DistanceTo(clean[-1]) > tol * 2:
            clean.append(p)
    if len(clean) < 2:
        return None

    centreline = rg.Polyline(clean).ToNurbsCurve()
    if centreline is None:
        return None

    # Offset both sides (in the XY plane) using Round corners
    # Round avoids self-intersecting kinks that Sharp creates on tight bends,
    # which break CurveBooleanUnion downstream.
    plane = rg.Plane.WorldXY
    left = centreline.Offset(plane, half_w, tol, rg.CurveOffsetCornerStyle.Round)
    right = centreline.Offset(plane, -half_w, tol, rg.CurveOffsetCornerStyle.Round)

    if not left or not right:
        return None

    left_crv = left[0]
    right_crv = right[0]

    # Reverse the right curve so it runs opposite direction
    right_crv.Reverse()

    # Connect end-caps with arcs for cleaner geometry
    cap1 = rg.LineCurve(left_crv.PointAtEnd, right_crv.PointAtStart)
    cap2 = rg.LineCurve(right_crv.PointAtEnd, left_crv.PointAtStart)

    # Join into one closed curve
    segments = [left_crv, cap1, right_crv, cap2]
    joined = rg.Curve.JoinCurves(segments, tol * 5)

    if joined and len(joined) > 0 and joined[0].IsClosed:
        # Simplify curve to remove micro-segments that cause boolean issues
        out = joined[0]
        simplified = out.Simplify(
            rg.CurveSimplifyOptions.All, tol, math.radians(5.0)
        )
        if simplified and simplified.IsClosed:
            return simplified
        return out

    # Fallback: try force-closing with a larger tolerance
    if joined and len(joined) > 0:
        crv = joined[0]
        gap = crv.PointAtStart.DistanceTo(crv.PointAtEnd)
        if gap < half_w:  # gap smaller than road width = safe to close
            crv.MakeClosed(gap + tol)
            if crv.IsClosed:
                return crv

    return None


def _curves_to_individual_surfaces(curve_list):
    """Create a planar Brep surface from each individual closed curve.
    No boolean union — every road gets its own surface. 100% reliable.
    Returns list of (brep, curve_index) tuples.
    """
    tol = sc.doc.ModelAbsoluteTolerance
    results = []

    for i, crv in enumerate(curve_list):
        if crv is None or not crv.IsClosed:
            continue
        try:
            srf = rg.Brep.CreatePlanarBreps([crv], tol)
            if srf and len(srf) > 0:
                results.append((srf[0], i))
        except Exception:
            pass

    return results


# ---------------------------------------------------------------------------
# OVERPASS API — fetch building data from OpenStreetMap
# ---------------------------------------------------------------------------
def fetch_buildings(lat, lon, radius_m):
    """Query OSM Overpass API for buildings within radius of (lat, lon).
    Returns a list of dicts with keys: nodes, height, levels, name, osm_id.
    """
    overpass_url = "https://overpass-api.de/api/interpreter"

    query = f"""
    [out:json][timeout:60];
    (
      way["building"](around:{radius_m},{lat},{lon});
      relation["building"](around:{radius_m},{lat},{lon});
    );
    out body;
    >;
    out skel qt;
    """

    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(overpass_url, data=data, method="POST")
    req.add_header("User-Agent", "RhinoSiteModelGenerator/1.0")

    Rhino.RhinoApp.WriteLine("Fetching building data from OpenStreetMap...")

    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    # Build a lookup of node id -> (lat, lon)
    node_lookup = {}
    for el in result.get("elements", []):
        if el["type"] == "node":
            node_lookup[el["id"]] = (el["lat"], el["lon"])

    # Extract buildings
    buildings = []
    for el in result.get("elements", []):
        if el["type"] not in ("way", "relation"):
            continue
        tags = el.get("tags", {})
        if "building" not in tags:
            continue

        # Collect footprint nodes
        nodes = el.get("nodes", [])
        coords = []
        for nid in nodes:
            if nid in node_lookup:
                coords.append(node_lookup[nid])

        if len(coords) < 3:
            continue

        # Parse height info
        height = None
        if "height" in tags:
            try:
                height = float(tags["height"].replace("m", "").strip())
            except ValueError:
                pass

        levels = None
        if "building:levels" in tags:
            try:
                levels = int(tags["building:levels"])
            except ValueError:
                pass

        min_level = 0
        if "building:min_level" in tags:
            try:
                min_level = int(tags["building:min_level"])
            except ValueError:
                pass

        buildings.append({
            "coords":    coords,       # list of (lat, lon)
            "height":    height,        # metres or None
            "levels":    levels,        # int or None
            "min_level": min_level,
            "name":      tags.get("name", ""),
            "addr":      tags.get("addr:street", ""),
            "addr_num":  tags.get("addr:housenumber", ""),
            "osm_id":    el["id"],
            "bld_type":  tags.get("building", "yes"),
        })

    Rhino.RhinoApp.WriteLine(f"  Found {len(buildings)} buildings.")
    return buildings


# ---------------------------------------------------------------------------
# COORDINATE TRANSFORM — lat/lon to local XY (metres from origin)
# ---------------------------------------------------------------------------
def latlon_to_xy(lat, lon, origin_lat, origin_lon):
    """Equirectangular projection: convert (lat, lon) to (x, y) in metres
    relative to (origin_lat, origin_lon) which maps to (0, 0).
    Accurate within ~1-2 km radius.
    """
    R = 6_378_137.0  # Earth radius in metres (WGS84 semi-major axis)
    lat_rad = math.radians(origin_lat)

    dx = math.radians(lon - origin_lon) * R * math.cos(lat_rad)
    dy = math.radians(lat - origin_lat) * R

    return (dx, dy)


def polygon_area_m2(coords, origin_lat, origin_lon):
    """Compute area of a polygon given as [(lat,lon),...] in m².
    Uses the shoelace formula on projected coordinates.
    """
    pts = [latlon_to_xy(c[0], c[1], origin_lat, origin_lon) for c in coords]
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2.0


# ---------------------------------------------------------------------------
# RHINO GEOMETRY — create layers, Breps, ground plane
# ---------------------------------------------------------------------------
def get_or_create_layer(name, color=None, parent=None):
    """Get existing layer or create it. Supports parent::child notation."""
    doc = sc.doc
    idx = doc.Layers.FindByFullPath(name, -1)
    if idx >= 0:
        return idx

    layer = rd.Layer()
    layer.Name = name.split("::")[-1]
    if color:
        layer.Color = System.Drawing.Color.FromArgb(color[0], color[1], color[2])
    if parent is not None:
        layer.ParentLayerId = doc.Layers[parent].Id
    return doc.Layers.Add(layer)


def setup_layers():
    """Create layer hierarchy:
       SiteModel::Buildings
       SiteModel::Ground
       SiteModel::Roads::<sub-type>
       SiteModel::Paths::<sub-type>
    """
    parent_idx = get_or_create_layer("SiteModel", color=(100, 100, 100))
    bld_idx = get_or_create_layer(
        "SiteModel::Buildings", color=(180, 130, 80), parent=parent_idx
    )
    gnd_idx = get_or_create_layer(
        "SiteModel::Ground", color=(140, 180, 100), parent=parent_idx
    )

    # --- Road parent layers ---
    roads_parent = get_or_create_layer(
        "SiteModel::Roads", color=(130, 130, 130), parent=parent_idx
    )
    paths_parent = get_or_create_layer(
        "SiteModel::Paths", color=(190, 160, 120), parent=parent_idx
    )

    # --- Road sub-layers ---
    road_layers = {}
    road_buckets = ["Motorway", "Primary", "Secondary", "Tertiary",
                    "Residential", "Service", "Other"]
    path_buckets = ["Footway", "Sidewalk", "Cycleway"]

    for bucket in road_buckets:
        col = ROAD_LAYER_COLORS.get(bucket, (180, 180, 180))
        idx = get_or_create_layer(
            f"SiteModel::Roads::{bucket}", color=col, parent=roads_parent
        )
        road_layers[bucket] = idx

    for bucket in path_buckets:
        col = ROAD_LAYER_COLORS.get(bucket, (200, 170, 120))
        idx = get_or_create_layer(
            f"SiteModel::Paths::{bucket}", color=col, parent=paths_parent
        )
        road_layers[bucket] = idx

    return bld_idx, gnd_idx, road_layers


def compute_building_height(bld, default_h, level_h):
    """Determine building height using the priority chain:
    1. OSM 'height' tag (exact measured value)
    2. 'building:levels' * level_height (estimated)
    3. default_height (fallback)
    Returns (height_m, source_str).
    """
    if bld["height"] is not None:
        return bld["height"], "measured"

    if bld["levels"] is not None:
        effective_levels = bld["levels"] - bld["min_level"]
        if effective_levels < 1:
            effective_levels = 1
        return effective_levels * level_h, f"{bld['levels']}levels"

    return default_h, "default"


def create_building_brep(bld, origin_lat, origin_lon, scale, default_h, level_h):
    """Create an extruded Brep from a building footprint.
    Returns (brep, height_m, height_source) or (None, 0, '') if failed.
    """
    height_m, hsource = compute_building_height(bld, default_h, level_h)
    height = height_m * scale

    # Build footprint polyline in XY plane
    pts = []
    for lat, lon in bld["coords"]:
        x, y = latlon_to_xy(lat, lon, origin_lat, origin_lon)
        pts.append(rg.Point3d(x * scale, y * scale, 0.0))

    if len(pts) < 3:
        return None, 0, ""

    # Close the polyline if not already closed
    close_tol = max(sc.doc.ModelAbsoluteTolerance * 10, 0.01 * scale)
    if pts[0].DistanceTo(pts[-1]) > close_tol:
        pts.append(pts[0])

    polyline = rg.Polyline(pts)
    curve = polyline.ToNurbsCurve()

    if curve is None or not curve.IsClosed:
        return None, 0, ""

    # Extrude upward
    extrusion_vec = rg.Vector3d(0, 0, height)
    surface = rg.Surface.CreateExtrusion(curve, extrusion_vec)
    if surface is None:
        return None, 0, ""

    brep = surface.ToBrep()

    # Cap the top and bottom
    brep = brep.CapPlanarHoles(sc.doc.ModelAbsoluteTolerance)
    if brep is None:
        # Fallback: try creating a box from bounding box
        return None, 0, ""

    return brep, height_m, hsource


def create_ground_plane(radius_m, scale, layer_idx):
    """Create a circular ground plane at Z=0."""
    r = radius_m * scale
    circle = rg.Circle(rg.Plane.WorldXY, r)
    circle_curve = rg.ArcCurve(circle)
    breps = rg.Brep.CreatePlanarBreps([circle_curve], sc.doc.ModelAbsoluteTolerance)

    if breps and len(breps) > 0:
        attrs = rd.ObjectAttributes()
        attrs.LayerIndex = layer_idx
        attrs.Name = "Ground Plane"
        sc.doc.Objects.AddBrep(breps[0], attrs)
        Rhino.RhinoApp.WriteLine("  Ground plane created.")
    else:
        Rhino.RhinoApp.WriteLine("  Warning: could not create ground plane.")


def height_color(height_m):
    """Map building height to a color gradient (low=light, tall=dark)."""
    t = min(height_m / 150.0, 1.0)  # normalize: 0..150m -> 0..1
    r = int(220 - 140 * t)
    g = int(200 - 150 * t)
    b = int(160 - 100 * t)
    return System.Drawing.Color.FromArgb(r, g, b)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    # Get user input
    if not get_user_input():
        Rhino.RhinoApp.WriteLine("Cancelled.")
        return

    lat = CONFIG["latitude"]
    lon = CONFIG["longitude"]
    radius = CONFIG["radius_m"]
    scale = UNIT_SCALES[CONFIG["unit"]]
    default_h = CONFIG["default_height"]
    level_h = CONFIG["level_height"]
    min_area = CONFIG["min_area"]

    Rhino.RhinoApp.WriteLine(f"\nSite Model Generator")
    Rhino.RhinoApp.WriteLine(f"  Location: {lat}, {lon}")
    Rhino.RhinoApp.WriteLine(f"  Radius:   {radius} m")
    Rhino.RhinoApp.WriteLine(f"  Units:    {CONFIG['unit']} (scale factor: {scale})")
    Rhino.RhinoApp.WriteLine(f"  Default height: {default_h} m")
    Rhino.RhinoApp.WriteLine(f"  Level height:   {level_h} m")

    # Fetch building data from OpenStreetMap
    try:
        buildings = fetch_buildings(lat, lon, radius)
    except Exception as e:
        Rhino.RhinoApp.WriteLine(f"Error fetching data: {e}")
        return

    if not buildings:
        Rhino.RhinoApp.WriteLine("No buildings found in the area.")
        return

    # Fetch road/path data from OpenStreetMap
    try:
        roads = fetch_roads(lat, lon, radius)
    except Exception as e:
        Rhino.RhinoApp.WriteLine(f"Warning: could not fetch roads: {e}")
        roads = []

    # Setup layers
    bld_layer, gnd_layer, road_layers = setup_layers()

    # ----- Create road / sidewalk surfaces (individual per road) -----
    road_created = 0
    road_failed = 0
    road_bucket_counts = {}

    Rhino.RhinoApp.WriteLine("Building road surfaces...")
    for rd_item in roads:
        bucket = rd_item["bucket"]
        layer_idx = road_layers.get(bucket, road_layers.get("Other", bld_layer))
        col = ROAD_LAYER_COLORS.get(bucket, (180, 180, 180))

        # Build closed outline curve
        crv = _road_outline_curve(
            rd_item["coords"], rd_item["width"],
            lat, lon, scale
        )
        if crv is None:
            road_failed += 1
            continue

        # Create planar surface directly from the closed curve
        tol = sc.doc.ModelAbsoluteTolerance
        try:
            srf = rg.Brep.CreatePlanarBreps([crv], tol)
        except Exception:
            srf = None

        if not srf or len(srf) == 0:
            road_failed += 1
            continue

        # Bake
        attrs = rd.ObjectAttributes()
        attrs.LayerIndex = layer_idx
        attrs.ObjectColor = System.Drawing.Color.FromArgb(col[0], col[1], col[2])
        attrs.ColorSource = rd.ObjectColorSource.ColorFromObject

        name = rd_item["name"] if rd_item["name"] else f"{rd_item['highway']}_{rd_item['osm_id']}"
        attrs.Name = name

        guid = sc.doc.Objects.AddBrep(srf[0], attrs)

        if guid != System.Guid.Empty:
            obj = sc.doc.Objects.FindId(guid)
            if obj:
                obj.Attributes.SetUserString("OSM_ID", str(rd_item["osm_id"]))
                obj.Attributes.SetUserString("Highway", rd_item["highway"])
                obj.Attributes.SetUserString("Width_m", f"{rd_item['width']:.1f}")
                obj.Attributes.SetUserString("Category", bucket)
                if rd_item["name"]:
                    obj.Attributes.SetUserString("Name", rd_item["name"])
                obj.CommitChanges()
            road_created += 1
            road_bucket_counts[bucket] = road_bucket_counts.get(bucket, 0) + 1

    Rhino.RhinoApp.WriteLine(
        f"  Roads/paths created: {road_created}  (failed: {road_failed})"
    )

    # ----- Create buildings -----
    created = 0
    skipped_small = 0
    skipped_fail = 0
    height_sources = {"measured": 0, "default": 0}

    for bld in buildings:
        # Filter by area
        area = polygon_area_m2(bld["coords"], lat, lon)
        if area < min_area:
            skipped_small += 1
            continue

        brep, height_m, hsource = create_building_brep(
            bld, lat, lon, scale, default_h, level_h
        )

        if brep is None:
            skipped_fail += 1
            continue

        # Count height sources
        if hsource == "measured":
            height_sources["measured"] += 1
        elif "levels" in hsource:
            height_sources.setdefault("levels", 0)
            height_sources["levels"] = height_sources.get("levels", 0) + 1
        else:
            height_sources["default"] += 1

        # Set object attributes
        attrs = rd.ObjectAttributes()
        attrs.LayerIndex = bld_layer
        attrs.ObjectColor = height_color(height_m)
        attrs.ColorSource = rd.ObjectColorSource.ColorFromObject

        # Build display name
        name = bld["name"] if bld["name"] else f"Building_{bld['osm_id']}"
        attrs.Name = name

        guid = sc.doc.Objects.AddBrep(brep, attrs)

        if guid != System.Guid.Empty:
            # Attach metadata as user text
            obj = sc.doc.Objects.FindId(guid)
            if obj:
                obj.Attributes.SetUserString("OSM_ID", str(bld["osm_id"]))
                obj.Attributes.SetUserString("Height_m", f"{height_m:.1f}")
                obj.Attributes.SetUserString("Height_source", hsource)
                obj.Attributes.SetUserString("Building_type", bld["bld_type"])
                obj.Attributes.SetUserString("Name", bld["name"])
                addr = f"{bld['addr_num']} {bld['addr']}".strip()
                if addr:
                    obj.Attributes.SetUserString("Address", addr)
                obj.Attributes.SetUserString("Footprint_area_m2", f"{area:.1f}")
                obj.CommitChanges()

            created += 1

    # Ground plane
    if CONFIG["ground_plane"]:
        create_ground_plane(radius, scale, gnd_layer)

    # Zoom to extents
    sc.doc.Views.Redraw()
    Rhino.RhinoApp.RunScript("_Zoom _All _Extents", False)

    # Summary
    Rhino.RhinoApp.WriteLine(f"\n--- Summary ---")
    Rhino.RhinoApp.WriteLine(f"  Buildings created:    {created}")
    Rhino.RhinoApp.WriteLine(f"  Skipped (too small):  {skipped_small}")
    Rhino.RhinoApp.WriteLine(f"  Skipped (geometry):   {skipped_fail}")
    Rhino.RhinoApp.WriteLine(f"  Height sources:")
    Rhino.RhinoApp.WriteLine(f"    Measured (exact):   {height_sources.get('measured', 0)}")
    Rhino.RhinoApp.WriteLine(f"    From levels:        {height_sources.get('levels', 0)}")
    Rhino.RhinoApp.WriteLine(f"    Default fallback:   {height_sources.get('default', 0)}")
    Rhino.RhinoApp.WriteLine(f"  Roads & Paths:")
    Rhino.RhinoApp.WriteLine(f"    Total created:      {road_created}")
    for bkt, cnt in sorted(road_bucket_counts.items()):
        Rhino.RhinoApp.WriteLine(f"    {bkt:20s}: {cnt}")
    Rhino.RhinoApp.WriteLine(f"    Failed:             {road_failed}")
    Rhino.RhinoApp.WriteLine(f"  Unit: {CONFIG['unit']}")
    Rhino.RhinoApp.WriteLine(f"Done.")


if __name__ == "__main__":
    main()
