using System;
using System.Collections.Generic;
using System.Linq;
using Eto.Drawing;
using Eto.Forms;
using Rhino;
using Rhino.UI;

namespace Vader
{
  [System.Runtime.InteropServices.Guid("b8d4f0a2-3c5e-4f7b-8d9e-2a1b0c9d8e7f")]
  public class VaderPanel : Panel, IPanel
  {
    public static readonly Guid PanelId = new Guid("b8d4f0a2-3c5e-4f7b-8d9e-2a1b0c9d8e7f");

    readonly TextBox _serverUrl;
    readonly TextBox _apiKey;
    readonly TextBox _email;
    readonly PasswordBox _password;
    readonly DropDown _category;
    readonly ListBox _scripts;
    readonly Label _status;
    readonly Label _detail;
    readonly Button _loginBtn;
    readonly Button _refreshBtn;
    readonly Button _runBtn;

    VaderApiClient _client;
    List<ScriptMeta> _all = new List<ScriptMeta>();

    public VaderPanel()
    {
      _client = new VaderApiClient("http://localhost:3000", "vader-plugin-dev-key-change-me");

      _serverUrl = new TextBox { Text = "http://localhost:3000", PlaceholderText = "API base URL" };
      _apiKey = new TextBox { Text = "vader-plugin-dev-key-change-me", PlaceholderText = "Plugin API key" };
      _email = new TextBox { PlaceholderText = "Email" };
      _password = new PasswordBox();
      _category = new DropDown();
      _scripts = new ListBox { Size = new Size(-1, 220) };
      _status = new Label { Text = "Sign in to load catalog." };
      _detail = new Label { Text = "", TextColor = Colors.Gray };
      _loginBtn = new Button { Text = "Sign in" };
      _refreshBtn = new Button { Text = "Refresh" };
      _runBtn = new Button { Text = "Run" };

      _loginBtn.Click += async (s, e) => await LoginAsync();
      _refreshBtn.Click += async (s, e) => await RefreshAsync();
      _runBtn.Click += async (s, e) => await RunAsync();
      _category.SelectedIndexChanged += (s, e) => FilterList();
      _scripts.SelectedIndexChanged += (s, e) => ShowDetail();

      var layout = new DynamicLayout { DefaultSpacing = new Size(6, 6), Padding = new Padding(10) };
      layout.AddRow(new Label { Text = "VADER", Font = new Font(SystemFont.Bold, 12) });
      layout.AddRow(new Label { Text = "Server" });
      layout.AddRow(_serverUrl);
      layout.AddRow(new Label { Text = "Plugin API key" });
      layout.AddRow(_apiKey);
      layout.AddRow(new Label { Text = "Email" });
      layout.AddRow(_email);
      layout.AddRow(new Label { Text = "Password" });
      layout.AddRow(_password);
      layout.AddRow(_loginBtn, _refreshBtn);
      layout.AddRow(new Label { Text = "Category" });
      layout.AddRow(_category);
      layout.AddRow(_scripts, yscale: true);
      layout.AddRow(_detail);
      layout.AddRow(_runBtn);
      layout.AddRow(_status);
      Content = layout;
    }

    async System.Threading.Tasks.Task LoginAsync()
    {
      try
      {
        _client.Configure(_serverUrl.Text.Trim(), _apiKey.Text.Trim());
        _status.Text = "Signing in…";
        var (ok, message) = await _client.LoginAsync(_email.Text.Trim(), _password.Text);
        _status.Text = message;
        if (ok) await RefreshAsync();
      }
      catch (Exception ex)
      {
        _status.Text = ex.Message;
      }
    }

    async System.Threading.Tasks.Task RefreshAsync()
    {
      try
      {
        _client.Configure(_serverUrl.Text.Trim(), _apiKey.Text.Trim());
        _status.Text = "Loading catalog…";
        _all = await _client.ListScriptsAsync();
        var cats = _all.Select(s => s.Category).Distinct().OrderBy(c => c).ToList();
        cats.Insert(0, "(all)");
        _category.DataStore = cats;
        _category.SelectedIndex = 0;
        FilterList();
        _status.Text = $"{_all.Count} scripts";
      }
      catch (Exception ex)
      {
        _status.Text = ex.Message;
      }
    }

    void FilterList()
    {
      var cat = _category.SelectedValue as string;
      IEnumerable<ScriptMeta> q = _all;
      if (!string.IsNullOrEmpty(cat) && cat != "(all)")
        q = q.Where(s => s.Category == cat);
      _scripts.DataStore = q.Select(s => $"{s.Name}  ·  {s.Id}").ToList();
    }

    ScriptMeta? SelectedScript()
    {
      var text = _scripts.SelectedValue as string;
      if (string.IsNullOrEmpty(text)) return null;
      var id = text.Split(new[] { "·" }, StringSplitOptions.None).LastOrDefault()?.Trim();
      return _all.FirstOrDefault(s => s.Id == id);
    }

    void ShowDetail()
    {
      var s = SelectedScript();
      _detail.Text = s == null ? "" : $"{s.Description}\n(v{s.Version} · Rhino {s.RhinoVersion}) — source hidden";
    }

    async System.Threading.Tasks.Task RunAsync()
    {
      var s = SelectedScript();
      if (s == null)
      {
        _status.Text = "Select a script";
        return;
      }

      try
      {
        _status.Text = $"Fetching {s.Name}…";
        var source = await _client.FetchSourceForRunAsync(s.Id);
        // Never display or persist source
        _status.Text = "Running…";

        var tcs = new System.Threading.Tasks.TaskCompletionSource<(bool ok, string message)>();
        RhinoApp.InvokeOnUiThread(new Action(() =>
        {
          try
          {
            tcs.SetResult(ScriptRunner.RunInMemory(source));
          }
          catch (Exception ex)
          {
            tcs.SetResult((false, ex.Message));
          }
        }));

        var result = await tcs.Task;
        _status.Text = result.ok ? $"OK — {s.Name}" : $"Error: {result.message}";
        RhinoApp.WriteLine(result.ok
          ? $"[Vader] Ran {s.Id} successfully"
          : $"[Vader] {result.message}");
      }
      catch (Exception ex)
      {
        _status.Text = ex.Message;
      }
    }

    public void PanelShown(uint documentSerialNumber, ShowPanelReason reason) { }
    public void PanelHidden(uint documentSerialNumber, ShowPanelReason reason) { }
    public void PanelClosing(uint documentSerialNumber, bool onCloseDocument) { }
  }
}
