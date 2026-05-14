using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace HermesLauncher;

internal static class Program
{
    private const string DepsDir = @"D:\HermesDeps";

    // Processus enfants démarrés par ce launcher — seront tués à la fermeture
    // de l'application desktop. On ne tue pas Ollama s'il tournait déjà avant.
    private static Process? _backendProcess;
    private static Process? _ollamaProcess;

    [STAThread]
    private static async Task Main()
    {
        // Garantit que les enfants meurent si le launcher est tué brutalement.
        var jobHandle = JobObject.CreateKillOnCloseJob();

        try
        {
            var root = FindRepositoryRoot();
            var backend = Path.Combine(root, "backend");
            var python = Path.Combine(backend, ".venv", "Scripts", "python.exe");
            var ollama = Path.Combine(DepsDir, "ollama", "bin", "ollama.exe");
            var hermesDesktop = Path.Combine(
                DepsDir,
                "tooling",
                "cargo-target",
                "release",
                "hermes.exe"
            );

            RequireFile(python, "Python backend introuvable");
            RequireFile(ollama, "Ollama/PYTHIA introuvable");
            RequireFile(hermesDesktop, "Application desktop HERMES introuvable");

            // 1. Nettoyage des zombies HERMES (uvicorn / hermes.exe préexistants).
            //    On ne touche pas à Ollama s'il tourne — il peut être partagé.
            KillExisting("uvicorn hermes.main");
            KillExisting("hermes.exe");

            await EnsureOllamaStarted(ollama, jobHandle);
            await EnsureBackendStarted(root, backend, python, jobHandle);

            var desktop = StartProcess(hermesDesktop, "", root, hidden: false, jobHandle: jobHandle);

            // 2. Bloque jusqu'à la fermeture de la fenêtre Tauri.
            desktop.WaitForExit();
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                ex.Message,
                "Erreur de lancement HERMES",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
        }
        finally
        {
            // 3. Kill explicite des enfants démarrés par nous.
            TryKill(_backendProcess, "backend HERMES");
            TryKill(_ollamaProcess, "PYTHIA (démarré par nous)");
            // Si jobHandle est non null et qu'on le ferme, Windows tue tout ce
            // qu'il restait associé. C'est notre filet de sécurité.
            jobHandle?.Dispose();
        }
    }

    private static string FindRepositoryRoot()
    {
        var current = AppContext.BaseDirectory;
        for (var i = 0; i < 6 && current is not null; i++)
        {
            if (
                Directory.Exists(Path.Combine(current, "backend"))
                && Directory.Exists(Path.Combine(current, "frontend"))
            )
            {
                return current.TrimEnd(Path.DirectorySeparatorChar);
            }

            current = Directory.GetParent(current)?.FullName;
        }

        const string fallback = @"E:\Hermes";
        if (Directory.Exists(Path.Combine(fallback, "backend")))
        {
            return fallback;
        }

        throw new InvalidOperationException("Impossible de localiser le dossier du projet HERMES.");
    }

    private static async Task EnsureOllamaStarted(string ollama, JobObject? job)
    {
        if (await IsHealthy("http://127.0.0.1:11434/api/tags"))
        {
            // Ollama tournait déjà → on ne le démarre pas et donc on ne le tuera pas.
            _ollamaProcess = null;
            return;
        }

        _ollamaProcess = StartProcess(ollama, "serve", DepsDir, hidden: true, jobHandle: job);

        if (!await WaitUntilHealthy("http://127.0.0.1:11434/api/tags", TimeSpan.FromSeconds(25)))
        {
            throw new InvalidOperationException("PYTHIA/Ollama n'a pas repondu sur 127.0.0.1:11434.");
        }
    }

    private static async Task EnsureBackendStarted(
        string root,
        string backend,
        string python,
        JobObject? job
    )
    {
        // Toujours partir d'un backend propre : si une ancienne instance tourne,
        // on l'a déjà killée en amont. Ici on redémarre tout pour être sûr
        // d'avoir la dernière version du code.
        _backendProcess = StartProcess(
            python,
            "-m uvicorn hermes.main:app --host 127.0.0.1 --port 8000",
            backend,
            hidden: true,
            environment: BuildEnvironment(root),
            jobHandle: job
        );

        if (!await WaitUntilHealthy("http://127.0.0.1:8000/health", TimeSpan.FromSeconds(35)))
        {
            throw new InvalidOperationException("Le backend HERMES n'a pas repondu sur 127.0.0.1:8000.");
        }
    }

    private static Dictionary<string, string> BuildEnvironment(string root)
    {
        var ollamaBin = Path.Combine(DepsDir, "ollama", "bin");
        var envPath = Environment.GetEnvironmentVariable("PATH") ?? "";

        return new Dictionary<string, string>
        {
            ["HERMES_DB_PATH"] = Path.Combine(root, "data", "hermes.db"),
            ["HERMES_STORAGE_PATH"] = Path.Combine(root, "data", "storage"),
            ["HERMES_LOG_PATH"] = Path.Combine(root, "data", "logs"),
            ["PIP_CACHE_DIR"] = Path.Combine(DepsDir, "install-cache", "pip"),
            ["PLAYWRIGHT_BROWSERS_PATH"] = Path.Combine(DepsDir, "tooling", "ms-playwright"),
            ["OLLAMA_MODELS"] = Path.Combine(DepsDir, "ollama", "models"),
            ["PATH"] = ollamaBin + ";" + envPath,
        };
    }

    private static Process StartProcess(
        string fileName,
        string arguments,
        string workingDirectory,
        bool hidden,
        Dictionary<string, string>? environment = null,
        JobObject? jobHandle = null
    )
    {
        var info = new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = hidden,
            WindowStyle = hidden ? ProcessWindowStyle.Hidden : ProcessWindowStyle.Normal,
        };

        if (environment is not null)
        {
            foreach (var item in environment)
            {
                info.Environment[item.Key] = item.Value;
            }
        }

        var proc = Process.Start(info)
            ?? throw new InvalidOperationException($"Impossible de demarrer: {fileName}");

        // Associe au job pour que le processus soit tué automatiquement si
        // le launcher meurt brutalement (kill task manager, plantage…).
        jobHandle?.AssignProcess(proc);
        return proc;
    }

    private static async Task<bool> WaitUntilHealthy(string url, TimeSpan timeout)
    {
        var until = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < until)
        {
            if (await IsHealthy(url))
            {
                return true;
            }

            await Task.Delay(700);
        }

        return false;
    }

    private static async Task<bool> IsHealthy(string url)
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
            using var response = await client.GetAsync(url);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private static void RequireFile(string path, string label)
    {
        if (!File.Exists(path))
        {
            throw new FileNotFoundException($"{label}: {path}");
        }
    }

    private static void KillExisting(string commandLinePattern)
    {
        try
        {
            using var searcher = new System.Management.ManagementObjectSearcher(
                $"SELECT ProcessId FROM Win32_Process WHERE CommandLine LIKE '%{commandLinePattern}%'"
            );
            foreach (var obj in searcher.Get())
            {
                try
                {
                    var pid = Convert.ToInt32(obj["ProcessId"]);
                    using var proc = Process.GetProcessById(pid);
                    proc.Kill(entireProcessTree: true);
                }
                catch
                {
                    // Best effort
                }
            }
        }
        catch
        {
            // System.Management peut manquer dans certains profils — on tolère.
        }
    }

    private static void TryKill(Process? proc, string label)
    {
        if (proc is null) return;
        try
        {
            if (!proc.HasExited)
            {
                proc.Kill(entireProcessTree: true);
                proc.WaitForExit(2000);
            }
        }
        catch
        {
            // Ignore — c'est du best effort à la fermeture.
        }
    }
}

// --------------------------------------------------------------------------- //
// Job Object Windows — tue automatiquement les processus enfants si le parent
// disparaît (utile en cas de crash du launcher ou de kill via le gestionnaire
// de tâches). Plus robuste qu'un simple finally.
// --------------------------------------------------------------------------- //

internal sealed class JobObject : IDisposable
{
    private IntPtr _handle;

    private JobObject(IntPtr handle) { _handle = handle; }

    public static JobObject? CreateKillOnCloseJob()
    {
        var handle = CreateJobObject(IntPtr.Zero, null);
        if (handle == IntPtr.Zero) return null;

        var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            BasicLimitInformation = new JOBOBJECT_BASIC_LIMIT_INFORMATION
            {
                LimitFlags = 0x2000 // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            }
        };
        var size = Marshal.SizeOf(info);
        var ptr = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(info, ptr, false);
            SetInformationJobObject(handle, JobObjectInfoType.ExtendedLimitInformation, ptr, (uint)size);
        }
        finally
        {
            Marshal.FreeHGlobal(ptr);
        }
        return new JobObject(handle);
    }

    public void AssignProcess(Process process)
    {
        if (_handle == IntPtr.Zero) return;
        try { AssignProcessToJobObject(_handle, process.Handle); }
        catch { }
    }

    public void Dispose()
    {
        if (_handle != IntPtr.Zero)
        {
            CloseHandle(_handle);
            _handle = IntPtr.Zero;
        }
    }

    private enum JobObjectInfoType { ExtendedLimitInformation = 9 }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string? name);

    [DllImport("kernel32.dll")]
    private static extern bool SetInformationJobObject(IntPtr hJob, JobObjectInfoType infoType, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll")]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);
}
