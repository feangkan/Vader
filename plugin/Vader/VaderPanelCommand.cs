using System;
using Rhino;
using Rhino.Commands;
using Rhino.UI;

namespace Vader
{
  [System.Runtime.InteropServices.Guid("a7c3e9f1-2b4d-4e6a-9c8d-1f0e2d3c4b5a")]
  public class VaderPanelCommand : Command
  {
    public VaderPanelCommand()
    {
      Instance = this;
    }

    public static VaderPanelCommand? Instance { get; private set; }

    public override string EnglishName => "Vader";

    protected override Result RunCommand(RhinoDoc doc, RunMode mode)
    {
      Panels.OpenPanel(VaderPanel.PanelId);
      return Result.Success;
    }
  }
}
