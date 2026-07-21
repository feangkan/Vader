using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Vader
{
  public sealed class ScriptMeta
  {
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public string Category { get; set; } = "";
    public string Version { get; set; } = "";
    public string RhinoVersion { get; set; } = "";
  }

  public sealed class VaderApiClient
  {
    private readonly HttpClient _http;
    private string _baseUrl;
    private string _apiKey;
    private string? _sessionToken;

    public VaderApiClient(string baseUrl, string apiKey)
    {
      _baseUrl = baseUrl.TrimEnd('/');
      _apiKey = apiKey;
      _http = new HttpClient();
      _http.DefaultRequestHeaders.UserAgent.ParseAdd("Vader-Rhino-Plugin/0.1");
      _http.Timeout = TimeSpan.FromSeconds(60);
    }

    public void Configure(string baseUrl, string apiKey)
    {
      _baseUrl = baseUrl.TrimEnd('/');
      _apiKey = apiKey;
    }

    public string? SessionToken => _sessionToken;

    public void SetSession(string? token) => _sessionToken = token;

    private void ApplyHeaders(HttpRequestMessage req)
    {
      req.Headers.Remove("X-Vader-Plugin-Key");
      req.Headers.TryAddWithoutValidation("X-Vader-Plugin-Key", _apiKey);
      if (!string.IsNullOrEmpty(_sessionToken))
      {
        req.Headers.Remove("X-Vader-Session");
        req.Headers.TryAddWithoutValidation("X-Vader-Session", _sessionToken);
      }
    }

    public async Task<(bool ok, string message)> LoginAsync(string email, string password)
    {
      var payload = JsonSerializer.Serialize(new { email, password });
      using var req = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}/api/plugin/login")
      {
        Content = new StringContent(payload, Encoding.UTF8, "application/json"),
      };
      ApplyHeaders(req);
      using var res = await _http.SendAsync(req).ConfigureAwait(false);
      var text = await res.Content.ReadAsStringAsync().ConfigureAwait(false);
      if (!res.IsSuccessStatusCode)
      {
        try
        {
          using var doc = JsonDocument.Parse(text);
          if (doc.RootElement.TryGetProperty("error", out var err))
            return (false, err.GetString() ?? "Login failed");
        }
        catch { /* ignore */ }
        return (false, $"Login failed ({(int)res.StatusCode})");
      }

      using (var doc = JsonDocument.Parse(text))
      {
        _sessionToken = doc.RootElement.GetProperty("token").GetString();
      }
      return (true, "Signed in");
    }

    public async Task<List<ScriptMeta>> ListScriptsAsync()
    {
      using var req = new HttpRequestMessage(HttpMethod.Get, $"{_baseUrl}/api/plugin/scripts");
      ApplyHeaders(req);
      using var res = await _http.SendAsync(req).ConfigureAwait(false);
      res.EnsureSuccessStatusCode();
      var text = await res.Content.ReadAsStringAsync().ConfigureAwait(false);
      var list = new List<ScriptMeta>();
      using var doc = JsonDocument.Parse(text);
      foreach (var el in doc.RootElement.GetProperty("scripts").EnumerateArray())
      {
        list.Add(new ScriptMeta
        {
          Id = el.GetProperty("id").GetString() ?? "",
          Name = el.GetProperty("name").GetString() ?? "",
          Description = el.TryGetProperty("description", out var d) ? d.GetString() ?? "" : "",
          Category = el.TryGetProperty("category", out var c) ? c.GetString() ?? "" : "",
          Version = el.TryGetProperty("version", out var v) ? v.GetString() ?? "" : "",
          RhinoVersion = el.TryGetProperty("rhinoVersion", out var r) ? r.GetString() ?? "" : "",
        });
      }
      return list;
    }

    public async Task<string> FetchSourceForRunAsync(string scriptId)
    {
      // 1) short-lived run token
      using (var tokenReq = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}/api/plugin/scripts/{scriptId}/run-token"))
      {
        ApplyHeaders(tokenReq);
        using var tokenRes = await _http.SendAsync(tokenReq).ConfigureAwait(false);
        tokenRes.EnsureSuccessStatusCode();
        var tokenJson = await tokenRes.Content.ReadAsStringAsync().ConfigureAwait(false);
        string runToken;
        using (var doc = JsonDocument.Parse(tokenJson))
          runToken = doc.RootElement.GetProperty("token").GetString() ?? "";

        // 2) payload (plugin only)
        using var payloadReq = new HttpRequestMessage(
          HttpMethod.Get,
          $"{_baseUrl}/api/scripts/{scriptId}/payload?token={Uri.EscapeDataString(runToken)}"
        );
        ApplyHeaders(payloadReq);
        payloadReq.Headers.TryAddWithoutValidation("X-Vader-Run-Token", runToken);
        using var payloadRes = await _http.SendAsync(payloadReq).ConfigureAwait(false);
        payloadRes.EnsureSuccessStatusCode();
        var payloadJson = await payloadRes.Content.ReadAsStringAsync().ConfigureAwait(false);
        using var payloadDoc = JsonDocument.Parse(payloadJson);
        return payloadDoc.RootElement.GetProperty("source").GetString() ?? "";
      }
    }
  }
}
