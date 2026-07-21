using System;
using Rhino.PlugIns;
using Rhino.UI;

namespace Vader
{
  public class VaderPlugIn : PlugIn
  {
    public VaderPlugIn()
    {
      Instance = this;
    }

    public static VaderPlugIn? Instance { get; private set; }

    public override PlugInLoadTime LoadTime => PlugInLoadTime.AtStartup;

    protected override LoadReturnCode OnLoad(ref string errorMessage)
    {
      Panels.RegisterPanel(this, typeof(VaderPanel), "Vader", System.Drawing.SystemIcons.Application);
      return LoadReturnCode.Success;
    }
  }
}
