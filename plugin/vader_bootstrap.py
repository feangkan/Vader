#! python 3
"""
Vader Rhino Bootstrap (beta)
============================
Run this file in Rhino 8 Script Editor to try Vader without building the C# .rhp.

Prerequisites:
  1. On THIS same PC, start the Vader web app:
       cd web
       cp .env.example .env   # set ADMIN_EMAIL / PLUGIN_API_KEY if needed
       npm install
       npx prisma migrate dev
       npm run db:seed
       npm run dev
  2. Open http://localhost:3000 — register or use seeded admin, approve users in /admin
  3. In Rhino: ScriptEditor → Open this file → Run

This panel lists catalog metadata and runs scripts in memory.
It never shows script source in the UI.
"""

from __future__ import annotations

import json
import traceback
import urllib.error
import urllib.parse
import urllib.request

import Rhino
import scriptcontext as sc
import Eto.Forms as forms
import Eto.Drawing as drawing


PLUGIN_UA = "Vader-Rhino-Plugin/0.1"
DEFAULT_SERVER = "http://localhost:3000"
DEFAULT_API_KEY = "vader-plugin-dev-key-change-me"


def _request(method, url, headers=None, body=None, timeout=60):
    data = None
    hdrs = {"User-Agent": PLUGIN_UA, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            return res.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"error": raw or str(e)}
        return e.code, payload
    except Exception as e:
        return 0, {"error": str(e)}


def run_source_in_memory(source):
    """Execute Python source in Rhino without writing a .py file."""
    code = (source or "").lstrip()
    if not code.startswith("#!"):
        code = "#! python 3\n" + code

    # Prefer Rhino 8 script editor run when available
    try:
        ok = Rhino.RhinoApp.RunScript("_-ScriptEditor _RunScript ", False)
        # Fallback: compile/exec in this CPython host (same process as Rhino)
    except Exception:
        pass

    # In-process exec — keeps source off disk; UI never displays it
    glb = {
        "__name__": "__vader_script__",
        "Rhino": Rhino,
        "sc": sc,
    }
    try:
        import rhinoscriptsyntax as rs

        glb["rs"] = rs
    except Exception:
        pass

    exec(compile(code, "<vader-protected>", "exec"), glb, glb)
    return True


class VaderPanel(forms.Form):
    def __init__(self):
        super().__init__()
        self.Title = "VADER"
        self.ClientSize = drawing.Size(420, 560)
        self.Padding = drawing.Padding(12)
        self.Resizable = True
        self.Topmost = True

        self._session = None
        self._scripts = []

        self.server = forms.TextBox()
        self.server.Text = DEFAULT_SERVER
        self.api_key = forms.TextBox()
        self.api_key.Text = DEFAULT_API_KEY
        self.email = forms.TextBox()
        self.password = forms.PasswordBox()
        self.category = forms.DropDown()
        self.list = forms.ListBox()
        self.list.Size = drawing.Size(-1, 220)
        self.detail = forms.Label()
        self.detail.Text = "Source is never shown — Run executes in memory only."
        self.status = forms.Label()
        self.status.Text = "Sign in with an approved beta account."

        login_btn = forms.Button()
        login_btn.Text = "Sign in"
        login_btn.Click += self.on_login

        refresh_btn = forms.Button()
        refresh_btn.Text = "Refresh"
        refresh_btn.Click += self.on_refresh

        run_btn = forms.Button()
        run_btn.Text = "Run selected"
        run_btn.Click += self.on_run

        self.category.SelectedIndexChanged += self.on_filter
        self.list.SelectedIndexChanged += self.on_select

        layout = forms.DynamicLayout()
        layout.Spacing = drawing.Size(6, 6)
        layout.AddRow(forms.Label(Text="Server"))
        layout.AddRow(self.server)
        layout.AddRow(forms.Label(Text="Plugin API key"))
        layout.AddRow(self.api_key)
        layout.AddRow(forms.Label(Text="Email"))
        layout.AddRow(self.email)
        layout.AddRow(forms.Label(Text="Password"))
        layout.AddRow(self.password)
        layout.AddRow(login_btn, refresh_btn)
        layout.AddRow(forms.Label(Text="Category"))
        layout.AddRow(self.category)
        layout.AddRow(self.list)
        layout.AddRow(self.detail)
        layout.AddRow(run_btn)
        layout.AddRow(self.status)
        self.Content = layout

    def _headers(self, extra=None):
        h = {"X-Vader-Plugin-Key": self.api_key.Text.strip()}
        if self._session:
            h["X-Vader-Session"] = self._session
        if extra:
            h.update(extra)
        return h

    def on_login(self, sender, e):
        base = self.server.Text.strip().rstrip("/")
        code, data = _request(
            "POST",
            base + "/api/plugin/login",
            headers=self._headers(),
            body={"email": self.email.Text.strip(), "password": self.password.Text},
        )
        if code != 200:
            self.status.Text = data.get("error") or ("Login failed (%s)" % code)
            return
        self._session = data.get("token")
        self.status.Text = "Signed in as %s" % data.get("email")
        self.on_refresh(None, None)

    def on_refresh(self, sender, e):
        if not self._session:
            self.status.Text = "Sign in first."
            return
        base = self.server.Text.strip().rstrip("/")
        code, data = _request(
            "GET",
            base + "/api/plugin/scripts",
            headers=self._headers(),
        )
        if code != 200:
            self.status.Text = data.get("error") or ("Refresh failed (%s)" % code)
            return
        self._scripts = data.get("scripts") or []
        cats = sorted({s.get("category") or "uncategorized" for s in self._scripts})
        items = ["(all)"] + cats
        self.category.DataStore = items
        self.category.SelectedIndex = 0
        self._fill_list()
        self.status.Text = "%d scripts loaded (metadata only)" % len(self._scripts)

    def _fill_list(self):
        cat = None
        if self.category.SelectedIndex >= 0 and self.category.SelectedValue:
            cat = str(self.category.SelectedValue)
        rows = []
        for s in self._scripts:
            if cat and cat != "(all)" and s.get("category") != cat:
                continue
            rows.append("%s  ·  %s" % (s.get("name"), s.get("id")))
        self.list.DataStore = rows

    def on_filter(self, sender, e):
        self._fill_list()

    def _selected(self):
        text = self.list.SelectedValue
        if not text:
            return None
        sid = str(text).split("·")[-1].strip()
        for s in self._scripts:
            if s.get("id") == sid:
                return s
        return None

    def on_select(self, sender, e):
        s = self._selected()
        if not s:
            self.detail.Text = ""
            return
        self.detail.Text = "%s\n(v%s · Rhino %s) — source hidden" % (
            s.get("description") or "",
            s.get("version") or "?",
            s.get("rhinoVersion") or "8",
        )

    def on_run(self, sender, e):
        s = self._selected()
        if not s:
            self.status.Text = "Select a script."
            return
        if not self._session:
            self.status.Text = "Sign in first."
            return

        base = self.server.Text.strip().rstrip("/")
        sid = s["id"]
        self.status.Text = "Requesting run token…"

        code, token_data = _request(
            "POST",
            base + "/api/plugin/scripts/%s/run-token" % urllib.parse.quote(sid),
            headers=self._headers(),
        )
        if code != 200:
            self.status.Text = token_data.get("error") or "Run-token failed"
            return

        run_token = token_data.get("token")
        self.status.Text = "Fetching payload…"
        code, payload = _request(
            "GET",
            base
            + "/api/scripts/%s/payload?token=%s"
            % (urllib.parse.quote(sid), urllib.parse.quote(run_token)),
            headers=self._headers({"X-Vader-Run-Token": run_token}),
        )
        if code != 200:
            self.status.Text = payload.get("error") or "Payload failed"
            return

        source = payload.get("source") or ""
        # Never put source into UI labels
        self.status.Text = "Running %s…" % s.get("name")
        try:
            run_source_in_memory(source)
            self.status.Text = "OK — %s" % s.get("name")
            Rhino.RhinoApp.WriteLine("[Vader] Ran %s successfully" % sid)
        except Exception:
            err = traceback.format_exc().splitlines()[-1]
            self.status.Text = "Error: %s" % err
            Rhino.RhinoApp.WriteLine("[Vader] %s" % err)


def show_vader():
    form = VaderPanel()
    form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    form.Show()


if __name__ == "__main__":
    show_vader()
