using System;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using LibreHardwareMonitor.Hardware;

namespace HardwareMonitorBridge
{
    public class UpdateVisitor : IVisitor
    {
        public void VisitComputer(IComputer computer)
        {
            try
            {
                computer.Traverse(this);
            }
            catch { }
        }

        public void VisitHardware(IHardware hardware)
        {
            try
            {
                hardware.Update();
                foreach (IHardware subHardware in hardware.SubHardware)
                {
                    try
                    {
                        subHardware.Accept(this);
                    }
                    catch { }
                }
            }
            catch { }
        }

        public void VisitSensor(ISensor sensor) { }
        public void VisitParameter(IParameter parameter) { }
    }

    class Program
    {
        static void Main(string[] args)
        {
            bool daemon = false;
            int intervalMs = 1500;
            string outputPath = null;

            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--daemon")
                {
                    daemon = true;
                }
                else if (args[i] == "--interval" && i + 1 < args.Length)
                {
                    int parsed;
                    if (int.TryParse(args[++i], out parsed) && parsed >= 200)
                    {
                        intervalMs = parsed;
                    }
                }
                else if (args[i] == "--output" && i + 1 < args.Length)
                {
                    outputPath = args[++i];
                }
            }

            if (string.IsNullOrEmpty(outputPath))
            {
                string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                outputPath = System.IO.Path.Combine(localAppData, "WidgetOSD", "telemetry.json");
            }

            // Redirect normal stdout to stderr in daemon mode to prevent buffer bloat
            var originalOut = Console.Out;
            if (daemon)
            {
                Console.SetOut(Console.Error);
            }

            // Guard against unhandled secondary-thread CLR crashes (0xe0434352)
            AppDomain.CurrentDomain.UnhandledException += (sender, e) =>
            {
                try
                {
                    Console.Error.WriteLine("Unhandled CLR Exception: " + e.ExceptionObject);
                    if (!daemon)
                    {
                        originalOut.WriteLine("{\"cpu\":{},\"gpu\":{},\"ram\":{},\"fans\":[]}");
                        originalOut.Flush();
                    }
                }
                catch { }
            };

            Computer computer = null;

            try
            {
                try
                {
                    computer = new Computer
                    {
                        IsCpuEnabled = true,
                        IsGpuEnabled = true,
                        IsMotherboardEnabled = true,
                        IsControllerEnabled = true,
                        IsMemoryEnabled = true,
                        IsStorageEnabled = false,
                        IsNetworkEnabled = false
                    };
                    computer.Open();
                }
                catch (Exception initEx)
                {
                    Console.Error.WriteLine("Warning: Initial Computer.Open failed (" + initEx.Message + "). Retrying with safe non-kernel sensors...");
                    try { if (computer != null) computer.Close(); } catch { }
                    computer = new Computer
                    {
                        IsCpuEnabled = true,
                        IsGpuEnabled = true,
                        IsMotherboardEnabled = false,
                        IsControllerEnabled = false,
                        IsMemoryEnabled = true,
                        IsStorageEnabled = false,
                        IsNetworkEnabled = false
                    };
                    computer.Open();
                }

                UpdateVisitor visitor = new UpdateVisitor();

                do
                {
                    try
                    {
                        computer.Accept(visitor);

                        double? cpuUsage = null;
                        double? cpuTempTdie = null;
                        double? cpuTempPackage = null;
                        double? cpuPower = null;

                        double? gpuUsage = null;
                        double? gpuTempCore = null;
                        double? gpuTempHotspot = null;
                        double? gpuTempMem = null;
                        double? vramUsedMb = null;
                        double? vramTotalMb = null;
                        double? vramUsagePercent = null;

                        double? ramTotalGb = null;
                        double? ramUsedGb = null;
                        double? ramUsagePercent = null;

                        var fanList = new List<Dictionary<string, object>>();

                        foreach (IHardware hardware in computer.Hardware)
                        {
                            try
                            {
                                CollectHardware(hardware, ref cpuUsage, ref cpuTempTdie, ref cpuTempPackage, ref cpuPower,
                                                ref gpuUsage, ref gpuTempCore, ref gpuTempHotspot, ref gpuTempMem,
                                                ref vramUsedMb, ref vramTotalMb, ref vramUsagePercent,
                                                ref ramTotalGb, ref ramUsedGb, ref ramUsagePercent, fanList);
                            }
                            catch { }
                        }

                        var data = new Dictionary<string, object>
                        {
                            { "cpu", new Dictionary<string, object> {
                                { "usage_percent", SafeDouble(cpuUsage) },
                                { "temp_tctl_tdie", SafeDouble(cpuTempTdie) },
                                { "temp_package", SafeDouble(cpuTempPackage) },
                                { "power_watts", SafeDouble(cpuPower) }
                            }},
                            { "gpu", new Dictionary<string, object> {
                                { "usage_percent", SafeDouble(gpuUsage) },
                                { "temp_core_edge", SafeDouble(gpuTempCore) },
                                { "temp_hotspot", SafeDouble(gpuTempHotspot) },
                                { "temp_memory", SafeDouble(gpuTempMem) },
                                { "vram_used_mb", SafeDouble(vramUsedMb) },
                                { "vram_total_mb", SafeDouble(vramTotalMb) },
                                { "vram_usage_percent", SafeDouble(vramUsagePercent) }
                            }},
                            { "ram", new Dictionary<string, object> {
                                { "used_gb", SafeDouble(ramUsedGb) },
                                { "total_gb", SafeDouble(ramTotalGb) },
                                { "usage_percent", SafeDouble(ramUsagePercent) }
                            }},
                            { "fans", fanList },
                            { "timestamp", DateTime.UtcNow.ToString("o") }
                        };

                        var serializer = new JavaScriptSerializer();
                        string json = serializer.Serialize(data);

                        // Escribir archivo de telemetría atómico para consumo por LHMProvider
                        if (!string.IsNullOrEmpty(outputPath))
                        {
                            try
                            {
                                string dir = System.IO.Path.GetDirectoryName(outputPath);
                                if (!string.IsNullOrEmpty(dir) && !System.IO.Directory.Exists(dir))
                                {
                                    System.IO.Directory.CreateDirectory(dir);
                                }
                                string tmpPath = outputPath + ".tmp";
                                System.IO.File.WriteAllText(tmpPath, json);
                                if (System.IO.File.Exists(outputPath))
                                {
                                    System.IO.File.Delete(outputPath);
                                }
                                System.IO.File.Move(tmpPath, outputPath);
                            }
                            catch { }
                        }

                        if (!daemon)
                        {
                            originalOut.WriteLine(json);
                            originalOut.Flush();
                        }
                    }
                    catch (Exception loopEx)
                    {
                        Console.Error.WriteLine("Error in sampling loop: " + loopEx.Message);
                    }

                    if (daemon)
                    {
                        System.Threading.Thread.Sleep(intervalMs);
                    }
                } while (daemon);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("Error: " + ex.Message);
                try
                {
                    if (!daemon)
                    {
                        originalOut.WriteLine("{\"cpu\":{},\"gpu\":{},\"ram\":{},\"fans\":[]}");
                        originalOut.Flush();
                    }
                }
                catch { }
            }
            finally
            {
                if (computer != null)
                {
                    try
                    {
                        computer.Close();
                    }
                    catch { }
                }
            }
        }

        static double? SafeDouble(double? val)
        {
            if (!val.HasValue || double.IsNaN(val.Value) || double.IsInfinity(val.Value)) return null;
            return Math.Round(val.Value, 2);
        }

        static void CollectHardware(IHardware hw,
            ref double? cpuUsage, ref double? cpuTempTdie, ref double? cpuTempPackage, ref double? cpuPower,
            ref double? gpuUsage, ref double? gpuTempCore, ref double? gpuTempHotspot, ref double? gpuTempMem,
            ref double? vramUsedMb, ref double? vramTotalMb, ref double? vramUsagePercent,
            ref double? ramTotalGb, ref double? ramUsedGb, ref double? ramUsagePercent,
            List<Dictionary<string, object>> fans)
        {
            if (hw == null) return;
            bool isCpu = hw.HardwareType == HardwareType.Cpu;
            bool isGpu = hw.HardwareType == HardwareType.GpuNvidia || hw.HardwareType == HardwareType.GpuAmd || hw.HardwareType == HardwareType.GpuIntel;
            bool isMem = hw.HardwareType == HardwareType.Memory;

            foreach (ISensor sensor in hw.Sensors)
            {
                try
                {
                    if (sensor == null || !sensor.Value.HasValue) continue;
                    double val = sensor.Value.Value;
                    string name = (sensor.Name ?? string.Empty).ToLowerInvariant();

                    if (isCpu)
                    {
                        if (sensor.SensorType == SensorType.Load && name.Contains("total") && !cpuUsage.HasValue)
                            cpuUsage = val;
                        else if (sensor.SensorType == SensorType.Temperature)
                        {
                            if ((name.Contains("tctl") || name.Contains("tdie")) && val > 0)
                                cpuTempTdie = val;
                            else if ((name.Contains("package") || name.Contains("core max")) && val > 0)
                                cpuTempPackage = val;
                            else if (!cpuTempPackage.HasValue && val > 0 && (name.Contains("cpu") || name.Contains("ccd") || name.Contains("core")))
                                cpuTempPackage = val;
                        }
                        else if (sensor.SensorType == SensorType.Power && (name.Contains("package") || name.Contains("ppt") || name.Contains("total") || name.Contains("cores")))
                        {
                            if (!cpuPower.HasValue || name.Contains("package") || name.Contains("ppt"))
                                cpuPower = val;
                        }
                    }
                    else if (isGpu)
                    {
                        if (sensor.SensorType == SensorType.Load && (name.Contains("core") || name.Contains("gpu core")))
                            gpuUsage = val;
                        else if (sensor.SensorType == SensorType.Load && (name.Contains("memory") || name.Contains("vram")))
                            vramUsagePercent = val;
                        else if (sensor.SensorType == SensorType.Temperature)
                        {
                            if (name.Contains("hot spot") || name.Contains("hotspot"))
                                gpuTempHotspot = val;
                            else if (name.Contains("memory"))
                                gpuTempMem = val;
                            else if (name.Contains("core") || name.Contains("gpu"))
                                gpuTempCore = val;
                        }
                        else if (sensor.SensorType == SensorType.SmallData || sensor.SensorType == SensorType.Data)
                        {
                            if (name.Contains("memory used")) vramUsedMb = val;
                            else if (name.Contains("memory total") || name.Contains("memory free")) {
                                if (name.Contains("memory total")) vramTotalMb = val;
                            }
                        }
                    }
                    else if (isMem)
                    {
                        if (sensor.SensorType == SensorType.Load && name.Contains("memory"))
                            ramUsagePercent = val;
                        else if (sensor.SensorType == SensorType.Data)
                        {
                            if (name.Contains("memory used")) ramUsedGb = val;
                        }
                    }

                    if (sensor.SensorType == SensorType.Fan && val >= 0)
                    {
                        fans.Add(new Dictionary<string, object> {
                            { "hardware", hw.Name ?? "Hardware" },
                            { "name", sensor.Name ?? "Fan" },
                            { "rpm", val }
                        });
                    }
                    else if (!isCpu && !isGpu && sensor.SensorType == SensorType.Temperature && val > 0 && val < 115)
                    {
                        // Motherboard / SuperIO thermal sensors for CPU
                        if ((name.Contains("cpu") || name.Contains("core") || name.Contains("processor")) && !cpuTempPackage.HasValue && !cpuTempTdie.HasValue)
                        {
                            cpuTempPackage = val;
                        }
                    }
                }
                catch { }
            }

            if (isMem && ramUsedGb.HasValue && ramUsagePercent.HasValue && ramUsagePercent.Value > 0)
            {
                ramTotalGb = (ramUsedGb.Value / (ramUsagePercent.Value / 100.0));
            }

            // Recursively collect all sub-hardware (SuperIO chips, embedded controllers, etc.)
            foreach (IHardware sub in hw.SubHardware)
            {
                try
                {
                    CollectHardware(sub, ref cpuUsage, ref cpuTempTdie, ref cpuTempPackage, ref cpuPower,
                                    ref gpuUsage, ref gpuTempCore, ref gpuTempHotspot, ref gpuTempMem,
                                    ref vramUsedMb, ref vramTotalMb, ref vramUsagePercent,
                                    ref ramTotalGb, ref ramUsedGb, ref ramUsagePercent, fans);
                }
                catch { }
            }
        }
    }
}
