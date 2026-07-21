import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import math
import random
import System
import Eto.Forms as forms
import Eto.Drawing as drawing
import rhinoscriptsyntax as rs

class TopoGeneratorDialog(forms.Form):
    def __init__(self):
        super().__init__()
        self.Title = "Live Topography Generator V5"
        self.Padding = drawing.Padding(10)
        self.Resizable = True
        self.Topmost = True
        self.Size = drawing.Size(560, 820)

        # --- Core Variables ---
        self.current_seed = random.randint(0, 1000)
        self.layout_seed  = random.randint(0, 100000)  # separate seed for auto-gen positions
        self.boundary_curve = None
        self.boundary_centroid = rg.Point3d(0, 0, 0)
        self.seed_points = []
        self.point_variations = []
        self.ctrls = {}
        self.preview_objects = []  # tracked guids for cleanup
        self.preview_layer_idx = None
        self.Closed += self.on_form_closed

        # --- UI Layout ---
        main_layout = forms.DynamicLayout()
        main_layout.Spacing = drawing.Size(5, 8)

        scroll_layout = forms.DynamicLayout()
        scroll_layout.Spacing = drawing.Size(5, 8)

        # ─────────────────────────────────────────
        # SECTION 1: BUILDING MODE
        # ─────────────────────────────────────────
        scroll_layout.AddRow(self.create_label_with_description(
            "Building Mode:",
            "Single building (V4) or multi-building cluster (V5)"
        ))

        mode_lbl = forms.Label()
        mode_lbl.Text = "Mode:"
        mode_lbl.VerticalAlignment = forms.VerticalAlignment.Center
        mode_lbl.Width = 140

        multi_mode_dd = forms.DropDown()
        multi_mode_dd.Items.Add("Single Building")
        multi_mode_dd.Items.Add("Interactive Points")
        multi_mode_dd.Items.Add("Auto Generate")
        multi_mode_dd.SelectedIndex = 0
        multi_mode_dd.Width = 220

        def on_multi_mode_changed(sender, e):
            if sender.SelectedIndex == 0:
                self.seed_points = []
                self.point_variations = []
            self.update_multi_visibility()
            self.update_preview()

        multi_mode_dd.SelectedIndexChanged += on_multi_mode_changed
        self.ctrls["multi_mode"] = multi_mode_dd
        scroll_layout.AddRow(mode_lbl, multi_mode_dd)

        # ─────────────────────────────────────────
        # SECTION 2: AUTO GENERATE SETTINGS (conditional)
        # ─────────────────────────────────────────
        self.auto_gen_label = self.create_label_with_description(
            "Auto Generate Settings:",
            "Spacing distance and number of buildings"
        )
        scroll_layout.AddRow(self.auto_gen_label)

        spacing_lbl, spacing_slider, spacing_stepper = self.create_linked_input("spacing", "Min Spacing:", 2, 100, 15, 0)
        count_lbl, count_slider, count_stepper = self.create_linked_input("bld_count", "Building Count:", 2, 20, 3, 0)
        scroll_layout.AddRow(spacing_lbl, spacing_slider, spacing_stepper)
        scroll_layout.AddRow(count_lbl, count_slider, count_stepper)

        # Layout seed display
        self.layout_seed_lbl = forms.Label()
        self.layout_seed_lbl.Text = "Layout Seed: {}".format(self.layout_seed)
        self.layout_seed_lbl.Font = drawing.Font("Arial", 8, drawing.FontStyle.Italic)
        self.layout_seed_lbl.TextColor = drawing.Color(80, 80, 140)
        scroll_layout.AddRow(self.layout_seed_lbl)

        # Randomize Layout button — only affects point positions, not building form
        self.btn_rand_layout = forms.Button()
        self.btn_rand_layout.Text = "🔀 Randomize Layout Positions"
        self.btn_rand_layout.Click += self.on_rand_layout_click
        scroll_layout.AddRow(self.btn_rand_layout)

        self.auto_gen_ctrls = [
            self.auto_gen_label,
            spacing_lbl, spacing_slider, spacing_stepper,
            count_lbl, count_slider, count_stepper,
            self.layout_seed_lbl, self.btn_rand_layout
        ]

        # ─────────────────────────────────────────
        # SECTION 3: COLLISION MODE (conditional)
        # ─────────────────────────────────────────
        self.collision_label = self.create_label_with_description(
            "Edge Collision Mode:",
            "Repel: buildings push apart | Blend: buildings merge at edges"
        )
        scroll_layout.AddRow(self.collision_label)

        coll_lbl = forms.Label()
        coll_lbl.Text = "Collision:"
        coll_lbl.VerticalAlignment = forms.VerticalAlignment.Center
        coll_lbl.Width = 140

        collision_dd = forms.DropDown()
        collision_dd.Items.Add("Repel (push apart)")
        collision_dd.Items.Add("Blend + Union (merge geometry)")
        collision_dd.SelectedIndex = 0
        collision_dd.Width = 220
        self.ctrls["collision"] = collision_dd
        self.coll_lbl = coll_lbl
        scroll_layout.AddRow(coll_lbl, collision_dd)

        # Repel gap slider (only visible in Repel mode)
        repel_gap_lbl, repel_gap_slider, repel_gap_stepper = self.create_linked_input(
            "repel_gap", "Min Gap Distance:", 0.0, 50.0, 3.0, 1)
        scroll_layout.AddRow(repel_gap_lbl, repel_gap_slider, repel_gap_stepper)
        self.repel_gap_ctrls = [repel_gap_lbl, repel_gap_slider, repel_gap_stepper]

        def on_collision_changed(sender, e):
            is_repel = sender.SelectedIndex == 0
            for c in self.repel_gap_ctrls:
                c.Visible = is_repel
            self.update_preview()

        collision_dd.SelectedIndexChanged += on_collision_changed

        # Point status label
        self.point_status_lbl = forms.Label()
        self.point_status_lbl.Text = "No points placed"
        self.point_status_lbl.Font = drawing.Font("Arial", 8, drawing.FontStyle.Italic)
        self.point_status_lbl.TextColor = drawing.Color(60, 120, 60)
        scroll_layout.AddRow(self.point_status_lbl)

        self.collision_ctrls = [
            self.collision_label, coll_lbl, collision_dd,
            self.point_status_lbl
        ] + self.repel_gap_ctrls

        # ─────────────────────────────────────────
        # SECTION 4: FORM PARAMETERS (always visible)
        # ─────────────────────────────────────────
        scroll_layout.AddRow(self.create_label_with_description(
            "Form Parameters:",
            "Controls for shape generation"
        ))
        scroll_layout.AddRow(*self.create_linked_input("scale", "Base Scale (%):", 10, 1000, 100, 0))
        scroll_layout.AddRow(*self.create_linked_input("layers", "Number of Layers:", 1, 30, 7, 0))
        scroll_layout.AddRow(*self.create_linked_input("height", "Floor Height:", 0.1, 10.0, 2.0, 1))
        scroll_layout.AddRow(*self.create_linked_input("taper", "Step In/Out (Taper %):", -30.0, 30.0, 5.0, 1))
        scroll_layout.AddRow(*self.create_linked_input("amplitude", "Organic Wobble:", 0.0, 10.0, 2.0, 1))
        scroll_layout.AddRow(*self.create_linked_input("complexity", "Complexity:", 1, 10, 3, 0))

        # ─────────────────────────────────────────
        # SECTION 5: SEED
        # ─────────────────────────────────────────
        scroll_layout.AddRow(self.create_label_with_description(
            "Random Seed:",
            "Controls randomization — change to get different forms"
        ))

        seed_lbl = forms.Label()
        seed_lbl.Text = "Seed Value:"
        seed_lbl.VerticalAlignment = forms.VerticalAlignment.Center
        seed_lbl.Width = 140

        seed_stepper = forms.NumericStepper()
        seed_stepper.DecimalPlaces = 0
        seed_stepper.MinValue = 0.0
        seed_stepper.MaxValue = 999999.0
        seed_stepper.Value = float(self.current_seed)
        seed_stepper.Width = 60

        seed_slider = forms.Slider()
        seed_slider.MinValue = 0
        seed_slider.MaxValue = 100000
        seed_slider.Value = min(100000, self.current_seed)
        seed_slider.Width = 200

        def on_seed_slider_changed(sender, e):
            val = sender.Value
            if seed_stepper.Value != val:
                seed_stepper.Value = float(val)
            self.current_seed = int(val)
            self.update_preview()

        def on_seed_stepper_changed(sender, e):
            val = int(sender.Value)
            if seed_slider.Value != val and val <= 100000:
                seed_slider.Value = val
            self.current_seed = val
            self.update_preview()

        seed_slider.ValueChanged += on_seed_slider_changed
        seed_stepper.ValueChanged += on_seed_stepper_changed
        self.ctrls["seed"] = seed_stepper
        self.seed_stepper = seed_stepper
        self.seed_slider = seed_slider
        scroll_layout.AddRow(seed_lbl, seed_slider, seed_stepper)

        # ─────────────────────────────────────────
        # SECTION 6: GROWTH ITERATIONS
        # ─────────────────────────────────────────
        scroll_layout.AddRow(self.create_label_with_description(
            "Growth Iterations:",
            "Number of growth stages shown (evolution from simple to complex)"
        ))
        scroll_layout.AddRow(*self.create_linked_input("iterations", "", 1, 10, 3, 0))

        # ─────────────────────────────────────────
        # SECTION 7: GROWTH RULE MODE
        # ─────────────────────────────────────────
        scroll_layout.AddRow(self.create_label_with_description(
            "Growth Rule Mode:",
            "Wave (organic) | Radial (bulbous) | Voronoi (honeycomb) | Hybrid (blend)"
        ))

        rule_mode_lbl = forms.Label()
        rule_mode_lbl.Text = "Select Mode:"
        rule_mode_lbl.VerticalAlignment = forms.VerticalAlignment.Center
        rule_mode_lbl.Width = 140

        rule_mode_dd = forms.DropDown()
        rule_mode_dd.Items.Add("Wave-based")
        rule_mode_dd.Items.Add("Radial Push")
        rule_mode_dd.Items.Add("Voronoi Subdivision")
        rule_mode_dd.Items.Add("Hybrid")
        rule_mode_dd.SelectedIndex = 0
        rule_mode_dd.Width = 220

        def on_rule_mode_changed(sender, e):
            self.update_hybrid_visibility()
            self.update_preview()

        rule_mode_dd.SelectedIndexChanged += on_rule_mode_changed
        self.ctrls["rule_mode"] = rule_mode_dd
        scroll_layout.AddRow(rule_mode_lbl, rule_mode_dd)

        # ─────────────────────────────────────────
        # SECTION 8: HYBRID BLEND SETTINGS (conditional)
        # ─────────────────────────────────────────
        scroll_layout.AddRow(self.create_label_with_description(
            "Blend Settings (Hybrid Mode):",
            "Choose two rules to blend — only active in Hybrid mode"
        ))

        rule1_lbl = forms.Label()
        rule1_lbl.Text = "Rule 1:"
        rule1_lbl.VerticalAlignment = forms.VerticalAlignment.Center
        rule1_lbl.Width = 140

        rule1_dd = forms.DropDown()
        rule1_dd.Items.Add("Wave-based")
        rule1_dd.Items.Add("Radial Push")
        rule1_dd.Items.Add("Voronoi Subdivision")
        rule1_dd.SelectedIndex = 0
        rule1_dd.Width = 220
        rule1_dd.Visible = False
        rule1_dd.SelectedIndexChanged += lambda s, e: self.update_preview()
        self.ctrls["rule1"] = rule1_dd
        self.rule1_lbl = rule1_lbl
        scroll_layout.AddRow(rule1_lbl, rule1_dd)

        rule2_lbl = forms.Label()
        rule2_lbl.Text = "Rule 2:"
        rule2_lbl.VerticalAlignment = forms.VerticalAlignment.Center
        rule2_lbl.Width = 140

        rule2_dd = forms.DropDown()
        rule2_dd.Items.Add("Wave-based")
        rule2_dd.Items.Add("Radial Push")
        rule2_dd.Items.Add("Voronoi Subdivision")
        rule2_dd.SelectedIndex = 1
        rule2_dd.Width = 220
        rule2_dd.Visible = False
        rule2_dd.SelectedIndexChanged += lambda s, e: self.update_preview()
        self.ctrls["rule2"] = rule2_dd
        self.rule2_lbl = rule2_lbl
        scroll_layout.AddRow(rule2_lbl, rule2_dd)

        blend_lbl, blend_slider, blend_stepper = self.create_linked_input(
            "blend", "Blend Mix (0%=Rule1, 100%=Rule2):", 0.0, 100.0, 50.0, 0
        )
        blend_stepper.Visible = False
        blend_slider.Visible = False
        blend_lbl.Visible = False
        self.blend_lbl = blend_lbl
        self.blend_slider = blend_slider
        scroll_layout.AddRow(blend_lbl, blend_slider, blend_stepper)

        # Wrap in scrollable panel
        scroll_panel = forms.Scrollable()
        scroll_panel.Content = scroll_layout
        scroll_panel.ExpandContentWidth = True
        scroll_panel.ExpandContentHeight = False
        scroll_panel.Size = drawing.Size(-1, 480)
        main_layout.AddRow(scroll_panel)

        # ─────────────────────────────────────────
        # BUTTONS (always visible at bottom)
        # ─────────────────────────────────────────
        main_layout.AddRow(None)

        self.btn_place = forms.Button()
        self.btn_place.Text = "📍 Place Building Points"
        self.btn_place.Click += self.on_place_points_click

        self.btn_autogen = forms.Button()
        self.btn_autogen.Text = "⚡ Auto Generate Layout"
        self.btn_autogen.Click += self.on_autogen_click

        self.btn_clear_pts = forms.Button()
        self.btn_clear_pts.Text = "✖ Clear Points"
        self.btn_clear_pts.Click += self.on_clear_points_click

        self.btn_pick_ref = forms.Button()
        self.btn_pick_ref.Text = "🔵 Pick Ref Points"
        self.btn_pick_ref.Click += self.on_pick_ref_points_click

        self.btn_boundary = forms.Button()
        self.btn_boundary.Text = "⬛ Pick Site Boundary"
        self.btn_boundary.Click += self.on_pick_boundary_click

        self.boundary_status_lbl = forms.Label()
        self.boundary_status_lbl.Text = "No boundary — generating at origin"
        self.boundary_status_lbl.Font = drawing.Font("Arial", 8, drawing.FontStyle.Italic)
        self.boundary_status_lbl.TextColor = drawing.Color(100, 100, 100)

        self.live_preview_cb = forms.CheckBox()
        self.live_preview_cb.Text = "Live Preview  (uncheck to reduce lag)"
        self.live_preview_cb.Checked = False  # default OFF

        def on_live_preview_changed(sender, e):
            if self.live_preview_cb.Checked:
                self._do_preview()   # turned ON  → show preview
            else:
                self.clear_preview() # turned OFF → clear viewport

        self.live_preview_cb.CheckedChanged += on_live_preview_changed

        btn_update = forms.Button()
        btn_update.Text = "🔄 Update Preview"
        btn_update.Click += lambda s, e: self._do_preview()

        btn_seed = forms.Button()
        btn_seed.Text = "🎲 Randomize Seed"
        btn_seed.Click += self.on_seed_click

        btn_bake = forms.Button()
        btn_bake.Text = "✔️ Bake Final"
        btn_bake.Click += self.on_bake_click

        btn_clear_geo = forms.Button()
        btn_clear_geo.Text = "🗑️ Clear Geometry"
        btn_clear_geo.Click += self.on_clear_click

        main_layout.AddRow(self.live_preview_cb)
        main_layout.AddRow(self.btn_boundary)
        main_layout.AddRow(self.boundary_status_lbl)
        main_layout.AddRow(self.btn_place)
        main_layout.AddRow(self.btn_pick_ref)
        main_layout.AddRow(self.btn_autogen)
        main_layout.AddRow(btn_seed)
        main_layout.AddRow(btn_update)
        main_layout.AddRow(btn_bake)
        main_layout.AddRow(self.btn_clear_pts)
        main_layout.AddRow(btn_clear_geo)

        self.Content = main_layout

        self.update_hybrid_visibility()
        self.update_multi_visibility()
        # No auto-preview on startup — Live Preview is off by default

    # ─────────────────────────────────────────
    # UI HELPERS
    # ─────────────────────────────────────────

    def create_label_with_description(self, title, description):
        container = forms.DynamicLayout()
        container.Spacing = drawing.Size(0, 2)
        title_lbl = forms.Label()
        title_lbl.Text = title
        title_lbl.Font = drawing.Font("Arial", 9, drawing.FontStyle.Bold)
        desc_lbl = forms.Label()
        desc_lbl.Text = description
        desc_lbl.Font = drawing.Font("Arial", 8, drawing.FontStyle.Italic)
        desc_lbl.TextColor = drawing.Color(100, 100, 100)
        container.AddRow(title_lbl)
        container.AddRow(desc_lbl)
        return container

    def create_linked_input(self, key, label_text, min_val, max_val, start_val, decimals):
        lbl = forms.Label()
        lbl.Text = label_text
        lbl.VerticalAlignment = forms.VerticalAlignment.Center
        lbl.Width = 140

        stepper = forms.NumericStepper()
        stepper.DecimalPlaces = decimals
        stepper.MinValue = float(min_val)
        stepper.MaxValue = float(max_val)
        stepper.Value = float(start_val)
        stepper.Width = 60

        slider = forms.Slider()
        multiplier = 10 ** decimals
        slider.MinValue = int(min_val * multiplier)
        slider.MaxValue = int(max_val * multiplier)
        slider.Value = int(start_val * multiplier)
        slider.Width = 200

        def on_slider_changed(sender, e):
            val = sender.Value / float(multiplier)
            if abs(stepper.Value - val) > 0.0001:
                stepper.Value = val
            self.update_preview()

        def on_stepper_changed(sender, e):
            val = int(sender.Value * multiplier)
            if slider.Value != val:
                slider.Value = val
            self.update_preview()

        slider.ValueChanged += on_slider_changed
        stepper.ValueChanged += on_stepper_changed
        self.ctrls[key] = stepper
        return [lbl, slider, stepper]

    def update_hybrid_visibility(self):
        is_hybrid = self.ctrls["rule_mode"].SelectedIndex == 3
        self.ctrls["rule1"].Visible = is_hybrid
        self.ctrls["rule2"].Visible = is_hybrid
        self.ctrls["blend"].Visible = is_hybrid
        self.blend_slider.Visible = is_hybrid
        self.blend_lbl.Visible = is_hybrid
        self.rule1_lbl.Visible = is_hybrid
        self.rule2_lbl.Visible = is_hybrid

    def update_multi_visibility(self):
        mode = self.ctrls["multi_mode"].SelectedIndex
        is_single = (mode == 0)
        is_interactive = (mode == 1)
        is_auto = (mode == 2)
        is_multi = (mode > 0)

        # Auto-gen controls
        for ctrl in self.auto_gen_ctrls:
            ctrl.Visible = is_auto

        # Collision controls
        for ctrl in self.collision_ctrls:
            ctrl.Visible = is_multi

        # Buttons
        self.btn_boundary.Visible = True   # boundary available in all modes
        self.btn_place.Visible = is_interactive
        self.btn_pick_ref.Visible = is_interactive
        self.btn_autogen.Visible = is_auto
        self.btn_clear_pts.Visible = is_multi

    def update_point_status(self):
        count = len(self.seed_points)
        if count == 0:
            self.point_status_lbl.Text = "No points placed"
        elif count == 1:
            self.point_status_lbl.Text = "1 building point placed"
        else:
            self.point_status_lbl.Text = "{} building points placed".format(count)

    # ─────────────────────────────────────────
    # EVENTS
    # ─────────────────────────────────────────

    def on_place_points_click(self, sender, e):
        self.clear_preview()
        self.Visible = False

        collected = []
        while True:
            msg = "Click to place building #{} — press Enter to finish".format(len(collected) + 1)
            pt = rs.GetPoint(msg)
            if pt is None:
                break
            collected.append(rg.Point3d(pt.X, pt.Y, 0))

        if collected:
            self.seed_points = collected
            self.regenerate_variations()

        self.Visible = True
        self.update_point_status()
        self.update_preview()

    def on_autogen_click(self, sender, e):
        self.seed_points = []  # force fresh regeneration
        self.update_point_status()
        self.update_preview()

    def on_rand_layout_click(self, sender, e):
        self.layout_seed = random.randint(0, 100000)
        self.layout_seed_lbl.Text = "Layout Seed: {}".format(self.layout_seed)
        self.seed_points = []  # force fresh regeneration with new seed
        self.update_point_status()
        self.update_preview()

    def on_clear_points_click(self, sender, e):
        self.seed_points = []
        self.point_variations = []
        self.update_point_status()
        self.update_preview()

    def on_pick_ref_points_click(self, sender, e):
        self.clear_preview()
        self.Visible = False
        pt_ids = rs.GetObjects("Select point objects to use as building locations", rs.filter.point)
        if pt_ids:
            self.seed_points = []
            for pid in pt_ids:
                coords = rs.PointCoordinates(pid)
                if coords:
                    self.seed_points.append(rg.Point3d(coords.X, coords.Y, 0))
            self.regenerate_variations()
        else:
            print("Selection cancelled. Keeping previous points.")
        self.Visible = True
        self.update_point_status()
        self.update_preview()

    def on_pick_boundary_click(self, sender, e):
        self.clear_preview()
        self.Visible = False
        obj_ids = rs.GetObjects("Select a closed curve as site boundary", rs.filter.curve, maximum_count=1)
        if obj_ids:
            crv = rs.coercecurve(obj_ids[0])
            if crv and crv.IsClosed:
                self.boundary_curve = crv
                amp_prop = rg.AreaMassProperties.Compute(crv)
                self.boundary_centroid = amp_prop.Centroid if amp_prop else rg.Point3d(0, 0, 0)
                self.boundary_status_lbl.Text = "Boundary set — buildings constrained to site"
                self.boundary_status_lbl.TextColor = drawing.Color(30, 120, 30)
            else:
                print("Please select a closed curve.")
        else:
            self.boundary_curve = None
            self.boundary_centroid = rg.Point3d(0, 0, 0)
            self.boundary_status_lbl.Text = "No boundary — generating at origin"
            self.boundary_status_lbl.TextColor = drawing.Color(100, 100, 100)
        self.Visible = True
        self.update_preview()

    def on_seed_click(self, sender, e):
        self.current_seed = random.randint(0, 100000)
        self.seed_stepper.Value = float(self.current_seed)
        if self.current_seed <= 100000:
            self.seed_slider.Value = self.current_seed
        self.regenerate_variations()
        self.update_preview()

    def generate_final_form(self):
        """Return only the final (most evolved) iteration for baking."""
        try:
            mode = self.ctrls["multi_mode"].SelectedIndex

            if mode == 0:
                stages = self.generate_layer_curves()
                return stages[-1] if stages else []

            # Auto mode: derive seed_points from bld_count + layout_seed (same as preview)
            if mode == 2:
                count   = int(self.ctrls["bld_count"].Value)
                spacing = float(self.ctrls["spacing"].Value)
                self.seed_points = self.generate_random_layout(count, spacing)
                self.regenerate_variations()

            if not self.seed_points:
                return []

            collision_mode = self.ctrls["collision"].SelectedIndex
            all_centroids  = list(self.seed_points)
            if len(self.point_variations) != len(self.seed_points):
                self.regenerate_variations()

            # Generate each building and keep only its last stage
            final_per_building = []
            for i, centroid in enumerate(self.seed_points):
                scale_var, amp_var = self.point_variations[i]
                stages = self.generate_building_stages(
                    centroid, scale_var, amp_var, all_centroids, collision_mode)
                if stages:
                    final_per_building.append(stages[-1])

            if collision_mode == 1 and len(final_per_building) > 1:
                # Boolean-union the final floors of all buildings
                tol = sc.doc.ModelAbsoluteTolerance
                all_breps = []
                for stage_exts in final_per_building:
                    for ext in stage_exts:
                        if ext:
                            brep = ext.ToBrep()
                            if brep:
                                all_breps.append(brep)
                unioned = rg.Brep.CreateBooleanUnion(all_breps, tol)
                return unioned if unioned else all_breps
            else:
                result = []
                for stage_exts in final_per_building:
                    result.extend(stage_exts)
                return result
        except Exception as e:
            print("Bake error: {}".format(str(e)))
            import traceback
            traceback.print_exc()
            return []

    def get_or_create_layer(self, layer_name):
        """Return layer index for layer_name, creating it if it doesn't exist."""
        layer_idx = sc.doc.Layers.FindByFullPath(layer_name, -1)
        if layer_idx < 0:
            layer = Rhino.DocObjects.Layer()
            layer.Name = layer_name
            layer.Color = System.Drawing.Color.FromArgb(210, 36, 112)
            layer_idx = sc.doc.Layers.Add(layer)
        return layer_idx

    def on_bake_click(self, sender, e):
        final_objs = self.generate_final_form()
        if not final_objs:
            print("Nothing to bake.")
            return

        layer_idx = self.get_or_create_layer("Mass operation")

        attr = Rhino.DocObjects.ObjectAttributes()
        attr.LayerIndex = layer_idx
        attr.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromLayer

        baked_guids = []
        for obj in final_objs:
            if isinstance(obj, rg.Brep):
                guid = sc.doc.Objects.AddBrep(obj, attr)
            else:
                guid = sc.doc.Objects.AddExtrusion(obj, attr)
            if guid != System.Guid.Empty:
                baked_guids.append(guid)

        if len(baked_guids) > 1:
            group_idx = sc.doc.Groups.Add()
            for guid in baked_guids:
                sc.doc.Groups.AddToGroup(group_idx, guid)

        sc.doc.Views.Redraw()
        print("Baked {} objects to layer 'Mass operation' (grouped).".format(len(baked_guids)))

    def on_clear_click(self, sender, e):
        self.clear_preview()
        sc.doc.Views.Redraw()

    # ─────────────────────────────────────────
    # GEOMETRY HELPERS
    # ─────────────────────────────────────────

    def on_form_closed(self, sender, e):
        self.clear_preview()

    def get_or_create_preview_layer(self):
        """Get or create 'Diff Growth Preview' layer, always visible."""
        layer_name = "Diff Growth Preview"
        layer_idx = sc.doc.Layers.FindByFullPath(layer_name, -1)
        if layer_idx < 0:
            layer = Rhino.DocObjects.Layer()
            layer.Name = layer_name
            layer.Color = System.Drawing.Color.FromArgb(180, 180, 200)
            layer_idx = sc.doc.Layers.Add(layer)
        # Ensure visible and unlocked
        layer = sc.doc.Layers[layer_idx]
        if not layer.IsVisible:
            layer.IsVisible = True
        if layer.IsLocked:
            layer.IsLocked = False
        sc.doc.Layers.Modify(layer, layer_idx, False)
        return layer_idx

    def clear_preview(self):
        """Delete all tracked preview objects."""
        for guid in self.preview_objects:
            try:
                sc.doc.Objects.Delete(guid, True)
            except:
                pass
        self.preview_objects = []
        sc.doc.Views.Redraw()

    def get_stage_color(self, stage_idx, total_stages):
        # Tint from dark (#6B1238) → full hue (#D22470) across stages
        t = stage_idx / max(1, total_stages - 1)
        r = int(40  + t * (210 - 40))
        g = int(10  + t * (36  - 10))
        b = int(50  + t * (112 - 50))
        return System.Drawing.Color.FromArgb(r, g, b)

    def regenerate_variations(self):
        """Generate per-building scale/amplitude variations from seed"""
        rng = random.Random(self.current_seed + 99991)
        self.point_variations = []
        for _ in self.seed_points:
            scale_var = 0.8 + 0.4 * rng.random()   # 0.8 – 1.2x
            amp_var   = 0.7 + 0.6 * rng.random()   # 0.7 – 1.3x
            self.point_variations.append((scale_var, amp_var))

    def generate_random_layout(self, count, spacing):
        """Poisson-disk layout — constrained within boundary curve if set, else open area"""
        rng = random.Random(self.layout_seed)
        points = []
        max_attempts = count * 200
        attempts = 0

        if self.boundary_curve:
            bbox = self.boundary_curve.GetBoundingBox(True)
            min_x, max_x = bbox.Min.X, bbox.Max.X
            min_y, max_y = bbox.Min.Y, bbox.Max.Y
        else:
            bounds = spacing * math.sqrt(count) * 1.1
            min_x, max_x = -bounds / 2.0, bounds / 2.0
            min_y, max_y = -bounds / 2.0, bounds / 2.0

        while len(points) < count and attempts < max_attempts:
            attempts += 1
            x = rng.uniform(min_x, max_x)
            y = rng.uniform(min_y, max_y)
            candidate = rg.Point3d(x, y, 0)
            # Check containment within boundary
            if self.boundary_curve:
                inside = self.boundary_curve.Contains(candidate, rg.Plane.WorldXY, 0.01)
                if inside != rg.PointContainment.Inside:
                    continue
            if all(candidate.DistanceTo(p) >= spacing for p in points):
                points.append(candidate)
        return points

    # ─────────────────────────────────────────
    # GROWTH RULE FUNCTIONS (V4 preserved)
    # ─────────────────────────────────────────

    def apply_wave_offset(self, point, tangent, freqs, phases, amplitude, theta, layer_idx=0):
        normal = rg.Vector3d(-tangent.Y, tangent.X, 0)
        normal.Unitize()
        z_shift = layer_idx * 0.4  # phase shift per layer — makes ridges flow diagonally (V1 key feature)
        offset = sum(math.sin(f * theta + p + z_shift) * (amplitude / len(freqs))
                     for f, p in zip(freqs, phases))
        return point + normal * offset

    def apply_radial_push(self, point, centroid, tangent, freqs, phases,
                          amplitude, iteration_idx, total_iterations):
        to_point = point - centroid
        distance = to_point.Length
        if distance < 0.001:
            return point
        direction = rg.Vector3d(to_point.X, to_point.Y, 0)
        direction.Unitize()
        push_strength = amplitude * (iteration_idx + 1) / float(total_iterations)
        angle = math.atan2(to_point.Y, to_point.X)
        angular_var = sum(math.cos(max(1, f // 2) * angle + p)
                          for f, p in zip(freqs[:2], phases[:2])) / 2.0
        total_push = push_strength * (0.6 + 0.4 * angular_var)
        return point + direction * total_push

    def apply_voronoi_offset(self, point, tangent, pt_idx, num_pts,
                             amplitude, complexity, cell_phases,
                             iteration_idx, total_iterations):
        normal = rg.Vector3d(-tangent.Y, tangent.X, 0)
        normal.Unitize()
        num_cells = max(3, complexity * 2)
        t = pt_idx / float(num_pts)
        min_dist = float('inf')
        closest_cell = 0
        for c in range(num_cells):
            cell_center = (c + 0.5) / float(num_cells)
            dist = abs(t - cell_center)
            if dist > 0.5:
                dist = 1.0 - dist
            if dist < min_dist:
                min_dist = dist
                closest_cell = c
        cell_scale = 0.5 + 0.8 * abs(math.sin(cell_phases[closest_cell % len(cell_phases)]))
        cell_half_width = 0.5 / float(num_cells)
        t_norm = min(1.0, min_dist / cell_half_width)
        bump = (math.cos(t_norm * math.pi) + 1.0) * 0.5
        iter_scale = (iteration_idx + 1) / float(total_iterations)
        return point + normal * (bump * amplitude * cell_scale * iter_scale)

    def blend_offsets(self, offset1, offset2, blend_weight):
        w = blend_weight / 100.0
        return offset1 * (1.0 - w) + offset2 * w

    def get_rule_point(self, rule_idx, pt, tangent, freqs, phases,
                       amplitude, theta, centroid, p_idx, num_pts,
                       complexity, cell_phases, iteration, num_iterations, layer_idx=0):
        if rule_idx == 0:
            return self.apply_wave_offset(pt, tangent, freqs, phases, amplitude, theta, layer_idx)
        elif rule_idx == 1:
            return self.apply_radial_push(pt, centroid, tangent, freqs, phases,
                                          amplitude, iteration, num_iterations)
        else:
            return self.apply_voronoi_offset(pt, tangent, p_idx, num_pts,
                                             amplitude, complexity, cell_phases,
                                             iteration, num_iterations)

    # ─────────────────────────────────────────
    # COLLISION HANDLING (V5 NEW)
    # ─────────────────────────────────────────

    def apply_repel_collision(self, points, my_centroid, all_centroids, base_radius, gap_distance):
        """Push curve points away from neighbours, maintaining user-defined gap between buildings"""
        if len(all_centroids) <= 1:
            return points
        # repel_radius = sum of both building radii + the user gap
        repel_radius = base_radius * 2.0 + gap_distance
        result = []
        for pt in points:
            adj = rg.Point3d(pt.X, pt.Y, pt.Z)
            for nc in all_centroids:
                if (abs(nc.X - my_centroid.X) < 0.001 and
                        abs(nc.Y - my_centroid.Y) < 0.001):
                    continue
                dist = pt.DistanceTo(nc)
                if 0.001 < dist < repel_radius:
                    away = rg.Vector3d(pt.X - nc.X, pt.Y - nc.Y, 0)
                    away.Unitize()
                    force = (repel_radius - dist) / repel_radius
                    push  = force * base_radius * 0.75
                    adj = rg.Point3d(adj.X + away.X * push,
                                     adj.Y + away.Y * push,
                                     adj.Z)
            result.append(adj)
        return result

    def apply_blend_collision(self, points, my_centroid, all_centroids, base_radius):
        """Smoothly merge building boundaries where they overlap (BLEND)"""
        if len(all_centroids) <= 1:
            return points
        blend_zone = base_radius * 2.0
        result = []
        for pt in points:
            min_nd = float('inf')
            closest_nc = None
            for nc in all_centroids:
                if (abs(nc.X - my_centroid.X) < 0.001 and
                        abs(nc.Y - my_centroid.Y) < 0.001):
                    continue
                d = pt.DistanceTo(nc)
                if d < min_nd:
                    min_nd = d
                    closest_nc = nc

            if closest_nc is not None and min_nd < blend_zone:
                # smoothstep 0→1 as point moves away from neighbour
                raw_t = min_nd / blend_zone
                smooth_t = raw_t * raw_t * (3.0 - 2.0 * raw_t)
                # Pull the point gently toward the midpoint between centroids
                mid_x = (my_centroid.X + closest_nc.X) * 0.5
                mid_y = (my_centroid.Y + closest_nc.Y) * 0.5
                pull = 1.0 - smooth_t          # stronger when closer
                blended = rg.Point3d(
                    pt.X + (mid_x - pt.X) * pull * 0.35,
                    pt.Y + (mid_y - pt.Y) * pull * 0.35,
                    pt.Z
                )
                result.append(blended)
            else:
                result.append(pt)
        return result

    # ─────────────────────────────────────────
    # BUILDING GENERATION PER SEED POINT (V5)
    # ─────────────────────────────────────────

    def generate_building_stages(self, centroid, scale_var, amp_var,
                                  all_centroids, collision_mode):
        """Generate all iteration stages for one building at centroid."""
        scale_pct   = float(self.ctrls["scale"].Value) / 100.0
        total_layers = int(self.ctrls["layers"].Value)
        floor_height = float(self.ctrls["height"].Value)
        taper_pct    = float(self.ctrls["taper"].Value) / 100.0
        amplitude    = float(self.ctrls["amplitude"].Value) * amp_var
        complexity   = int(self.ctrls["complexity"].Value)
        num_iters    = int(self.ctrls["iterations"].Value)
        rule_mode    = self.ctrls["rule_mode"].SelectedIndex
        rule1_idx    = self.ctrls["rule1"].SelectedIndex if rule_mode == 3 else 0
        rule2_idx    = self.ctrls["rule2"].SelectedIndex if rule_mode == 3 else 1
        blend_weight = float(self.ctrls["blend"].Value) if rule_mode == 3 else 50.0

        random.seed(self.current_seed)
        freqs       = [random.randint(1, complexity) for _ in range(4)]
        phases      = [random.uniform(0, math.pi * 2) for _ in range(4)]
        cell_phases = [random.uniform(0, math.pi * 2) for _ in range(30)]

        # Build circle from centroid — default radius 20 × scale_pct × per-building var
        base_radius = 6.0 * scale_pct * scale_var
        plane = rg.Plane(centroid, rg.Vector3d.ZAxis)
        base_circle = rg.Circle(plane, base_radius).ToNurbsCurve()
        num_pts = max(80, int(base_circle.GetLength() * 2))

        res_stages = []

        for iteration in range(num_iters):
            stage_extrusions = []
            layers_at_stage = max(1, int((iteration + 1) / float(num_iters) * total_layers))

            for i in range(layers_at_stage):
                layer_scale = 1.0 - (i * taper_pct)
                if layer_scale <= 0.05:
                    break

                layer_crv = base_circle.Duplicate()
                layer_crv.Transform(rg.Transform.Scale(centroid, layer_scale))

                params = layer_crv.DivideByCount(num_pts, True)
                if not params:
                    continue

                new_pts = []
                for p_idx, t in enumerate(params):
                    pt      = layer_crv.PointAt(t)
                    tangent = layer_crv.TangentAt(t)
                    theta   = (p_idx / float(num_pts)) * math.pi * 2

                    if rule_mode == 3:
                        pt1 = self.get_rule_point(rule1_idx, pt, tangent, freqs, phases,
                                                  amplitude, theta, centroid, p_idx,
                                                  num_pts, complexity, cell_phases,
                                                  iteration, num_iters, layer_idx=i)
                        pt2 = self.get_rule_point(rule2_idx, pt, tangent, freqs, phases,
                                                  amplitude, theta, centroid, p_idx,
                                                  num_pts, complexity, cell_phases,
                                                  iteration, num_iters, layer_idx=i)
                        new_pt = pt + self.blend_offsets(pt1 - pt, pt2 - pt, blend_weight)
                    else:
                        new_pt = self.get_rule_point(rule_mode, pt, tangent, freqs, phases,
                                                     amplitude, theta, centroid, p_idx,
                                                     num_pts, complexity, cell_phases,
                                                     iteration, num_iters, layer_idx=i)
                    new_pts.append(new_pt)

                # Apply collision handling AFTER growth offsets
                if len(all_centroids) > 1:
                    if collision_mode == 0:  # Repel: push curves apart with user gap
                        gap_distance = float(self.ctrls["repel_gap"].Value)
                        new_pts = self.apply_repel_collision(
                            new_pts, centroid, all_centroids, base_radius, gap_distance)
                    # Blend mode: no curve-level adjustment — boolean union handles merge later

                # Force all points flat (Z=0) so CreateInterpolatedCurve succeeds
                flat_pts = [rg.Point3d(p.X, p.Y, 0) for p in new_pts]
                flat_pts.append(flat_pts[0])
                interp_crv = rg.Curve.CreateInterpolatedCurve(flat_pts, 3)
                if interp_crv:
                    interp_crv.Translate(0, 0, i * floor_height)
                    extrusion = rg.Extrusion.Create(interp_crv, floor_height, True)
                    if extrusion:
                        stage_extrusions.append(extrusion)

            res_stages.append(stage_extrusions)

        return res_stages

    # ─────────────────────────────────────────
    # SINGLE-BUILDING GENERATION (V4 compatible)
    # ─────────────────────────────────────────

    def generate_layer_curves(self):
        """Single-building generation — always uses organic circle + growth rules.
        If a site boundary is set, the building is centered at the boundary centroid."""
        scale        = float(self.ctrls["scale"].Value) / 100.0
        total_layers = int(self.ctrls["layers"].Value)
        floor_height = float(self.ctrls["height"].Value)
        taper_pct    = float(self.ctrls["taper"].Value) / 100.0
        amplitude    = float(self.ctrls["amplitude"].Value)
        complexity   = int(self.ctrls["complexity"].Value)
        num_iters    = int(self.ctrls["iterations"].Value)
        rule_mode    = self.ctrls["rule_mode"].SelectedIndex
        rule1_idx    = self.ctrls["rule1"].SelectedIndex if rule_mode == 3 else 0
        rule2_idx    = self.ctrls["rule2"].SelectedIndex if rule_mode == 3 else 1
        blend_weight = float(self.ctrls["blend"].Value) if rule_mode == 3 else 50.0

        random.seed(self.current_seed)
        freqs       = [random.randint(1, complexity) for _ in range(4)]
        phases      = [random.uniform(0, math.pi * 2) for _ in range(4)]
        cell_phases = [random.uniform(0, math.pi * 2) for _ in range(30)]

        res_stages = []

        # Always generate from a circle — shape comes entirely from the growth rules
        centroid = self.boundary_centroid
        base_radius = 8.0 * scale
        plane = rg.Plane(centroid, rg.Vector3d.ZAxis)
        master_crv = rg.Circle(plane, base_radius).ToNurbsCurve()
        num_pts = max(100, int(master_crv.GetLength() * 2))

        for iteration in range(num_iters):
            stage_extrusions = []
            layers_at_stage = max(1, int((iteration + 1) / float(num_iters) * total_layers))

            for i in range(layers_at_stage):
                layer_scale = 1.0 - (i * taper_pct)
                if layer_scale <= 0.05:
                    break

                layer_crv = master_crv.Duplicate()
                layer_crv.Transform(rg.Transform.Scale(centroid, layer_scale))
                params = layer_crv.DivideByCount(num_pts, True)
                if not params:
                    continue

                new_pts = []
                for p_idx, t in enumerate(params):
                    pt      = layer_crv.PointAt(t)
                    tangent = layer_crv.TangentAt(t)
                    theta   = (p_idx / float(num_pts)) * math.pi * 2

                    if rule_mode == 3:
                        pt1 = self.get_rule_point(rule1_idx, pt, tangent, freqs, phases,
                                                  amplitude, theta, centroid, p_idx,
                                                  num_pts, complexity, cell_phases,
                                                  iteration, num_iters, layer_idx=i)
                        pt2 = self.get_rule_point(rule2_idx, pt, tangent, freqs, phases,
                                                  amplitude, theta, centroid, p_idx,
                                                  num_pts, complexity, cell_phases,
                                                  iteration, num_iters, layer_idx=i)
                        new_pt = pt + self.blend_offsets(pt1 - pt, pt2 - pt, blend_weight)
                    else:
                        new_pt = self.get_rule_point(rule_mode, pt, tangent, freqs, phases,
                                                     amplitude, theta, centroid, p_idx,
                                                     num_pts, complexity, cell_phases,
                                                     iteration, num_iters, layer_idx=i)
                    new_pts.append(new_pt)

                flat_pts = [rg.Point3d(p.X, p.Y, 0) for p in new_pts]
                flat_pts.append(flat_pts[0])
                interp_crv = rg.Curve.CreateInterpolatedCurve(flat_pts, 3)
                if interp_crv:
                    interp_crv.Translate(0, 0, i * floor_height)
                    extrusion = rg.Extrusion.Create(interp_crv, floor_height, True)
                    if extrusion:
                        stage_extrusions.append(extrusion)

            res_stages.append(stage_extrusions)

        return res_stages

    # ─────────────────────────────────────────
    # MAIN GENERATION DISPATCHER
    # ─────────────────────────────────────────

    def generate_all_buildings(self):
        try:
            mode = self.ctrls["multi_mode"].SelectedIndex

            if mode == 0:
                return self.generate_layer_curves()

            # Auto mode: always derive seed_points from bld_count + layout_seed
            if mode == 2:
                try:
                    count   = int(self.ctrls["bld_count"].Value)
                    spacing = float(self.ctrls["spacing"].Value)
                    self.seed_points = self.generate_random_layout(count, spacing)
                    self.regenerate_variations()
                except Exception as e:
                    print("Auto-gen error: {}".format(str(e)))
                    return []

            if not self.seed_points:
                return []

            collision_mode = self.ctrls["collision"].SelectedIndex
            all_centroids  = list(self.seed_points)

            if len(self.point_variations) != len(self.seed_points):
                self.regenerate_variations()

            # Collect stages per building: [bld_idx][stage_idx] = [Extrusion, ...]
            per_building = []
            for i, centroid in enumerate(self.seed_points):
                scale_var, amp_var = self.point_variations[i]
                stages = self.generate_building_stages(
                    centroid, scale_var, amp_var, all_centroids, collision_mode)
                per_building.append(stages)

            if collision_mode == 1 and len(per_building) > 1:
                # BLEND mode: boolean-union all buildings' extrusions stage-by-stage
                num_stages = max(len(s) for s in per_building)
                tol = sc.doc.ModelAbsoluteTolerance
                all_stages = []
                for stage_idx in range(num_stages):
                    # Gather all extrusions from every building for this stage
                    stage_breps = []
                    for bld_stages in per_building:
                        if stage_idx < len(bld_stages):
                            for ext in bld_stages[stage_idx]:
                                if ext:
                                    brep = ext.ToBrep()
                                    if brep:
                                        stage_breps.append(brep)

                    if len(stage_breps) > 1:
                        unioned = rg.Brep.CreateBooleanUnion(stage_breps, tol)
                        all_stages.append(unioned if unioned else stage_breps)
                    else:
                        all_stages.append(stage_breps)
                return all_stages
            else:
                # REPEL mode (or single building): extend all stages directly
                all_stages = []
                for bld_stages in per_building:
                    all_stages.extend(bld_stages)
                return all_stages
        except Exception as e:
            print("Building generation error: {}".format(str(e)))
            import traceback
            traceback.print_exc()
            return []

    # ─────────────────────────────────────────
    # PREVIEW
    # ─────────────────────────────────────────

    def update_preview(self):
        """Called by sliders/dropdowns — only runs if Live Preview is enabled."""
        if not self.Visible:
            return
        if not self.live_preview_cb.Checked:
            return
        self._do_preview()

    def _do_preview(self):
        """Add preview geometry to dedicated layer."""
        try:
            if not self.Visible:
                return
            self.clear_preview()

            layer_idx = self.get_or_create_preview_layer()
            sc.doc.Views.RedrawEnabled = False

            all_stages = self.generate_all_buildings()
            total = len(all_stages)

            for stage_idx, stage_objs in enumerate(all_stages):
                try:
                    color = self.get_stage_color(stage_idx, total)
                    for obj in stage_objs:
                        if not obj:
                            continue
                        attr = Rhino.DocObjects.ObjectAttributes()
                        attr.LayerIndex = layer_idx
                        attr.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
                        attr.ObjectColor = color
                        try:
                            if isinstance(obj, rg.Brep):
                                guid = sc.doc.Objects.AddBrep(obj, attr)
                            elif isinstance(obj, rg.Extrusion):
                                guid = sc.doc.Objects.AddExtrusion(obj, attr)
                            else:
                                continue
                            if guid != System.Guid.Empty:
                                self.preview_objects.append(guid)
                        except:
                            pass
                except Exception as e:
                    print("Stage error: {}".format(str(e)))
                    continue

            # Boundary curve — blue
            if self.boundary_curve:
                try:
                    attr = Rhino.DocObjects.ObjectAttributes()
                    attr.LayerIndex = layer_idx
                    attr.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
                    attr.ObjectColor = System.Drawing.Color.FromArgb(50, 120, 220)
                    guid = sc.doc.Objects.AddCurve(self.boundary_curve, attr)
                    if guid != System.Guid.Empty:
                        self.preview_objects.append(guid)
                except:
                    pass

            # Seed points — orange
            if self.seed_points:
                try:
                    attr = Rhino.DocObjects.ObjectAttributes()
                    attr.LayerIndex = layer_idx
                    attr.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
                    attr.ObjectColor = System.Drawing.Color.FromArgb(255, 140, 0)
                    for pt in self.seed_points:
                        guid = sc.doc.Objects.AddPoint(pt, attr)
                        if guid != System.Guid.Empty:
                            self.preview_objects.append(guid)
                except:
                    pass

            sc.doc.Views.RedrawEnabled = True
            sc.doc.Views.Redraw()
        except Exception as e:
            print("Preview error: {}".format(str(e)))
            import traceback
            traceback.print_exc()
            sc.doc.Views.RedrawEnabled = True


# --- Run the Script ---
if __name__ == "__main__":
    dialog = TopoGeneratorDialog()
    dialog.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    dialog.Show()
