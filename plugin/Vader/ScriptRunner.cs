using System;
using Rhino;
using Rhino.Runtime;

namespace Vader
{
  /// <summary>
  /// Executes Python source in memory — never writes .py to disk, never shows source in UI.
  /// Prefers IronPython host via PythonScript; Rhino 8 CPython can be swapped via RhinoCode when available.
  /// </summary>
  public static class ScriptRunner
  {
    public static (bool ok, string message) RunInMemory(string source)
    {
      if (string.IsNullOrWhiteSpace(source))
        return (false, "Empty script");

      try
      {
        // Ensure language directive for Rhino 8 script editor / engines that expect it
        var code = source.TrimStart();
        if (!code.StartsWith("#!", StringComparison.Ordinal))
          code = "#! python 3\n" + code;

        // Try RhinoCode reflection first (Rhino 8+)
        if (TryRhinoCode(code, out var rhinoCodeMsg))
          return (true, rhinoCodeMsg);

        var py = PythonScript.Create();
        if (py == null)
          return (false, "Could not create Python engine");

        py.ScriptContextDoc = RhinoDoc.ActiveDoc;
        py.ExecuteScript(code);
        return (true, "Script finished");
      }
      catch (Exception ex)
      {
        return (false, ex.Message);
      }
    }

    static bool TryRhinoCode(string code, out string message)
    {
      message = "";
      try
      {
        var rhinoCodeType = Type.GetType("Rhino.Runtime.Code.RhinoCode, RhinoCommon");
        if (rhinoCodeType == null)
          return false;

        var runMethod = rhinoCodeType.GetMethod("RunScript", new[] { typeof(string) });
        if (runMethod == null)
        {
          // Overload with context may exist — fall back
          return false;
        }

        runMethod.Invoke(null, new object[] { code });
        message = "Script finished (RhinoCode)";
        return true;
      }
      catch
      {
        return false;
      }
    }
  }
}
