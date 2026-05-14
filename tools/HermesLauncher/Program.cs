using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace HermesLauncher;

internal static class Program
{
    private const string DepsDir = @"D:\HermesDeps";

    [STAThread]
    private static async Task Main()
    {
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

            await EnsureOllamaStarted(ollama);
            await EnsureBackendStarted(root, backend, python);

            StartProcess(hermesDesktop, "", root, hidden: false);
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

    private static async Task EnsureOllamaStarted(string ollama)
    {
        if (await IsHealthy("http://127.0.0.1:11434/api/tags"))
        {
            return;
        }

        StartProcess(ollama, "serve", DepsDir, hidden: true);

        if (!await WaitUntilHealthy("http://127.0.0.1:11434/api/tags", TimeSpan.FromSeconds(25)))
        {
            throw new InvalidOperationException("PYTHIA/Ollama n'a pas repondu sur 127.0.0.1:11434.");
        }
    }

    private static async Task EnsureBackendStarted(string root, string backend, string python)
    {
        if (await IsHealthy("http://127.0.0.1:8000/health"))
        {
            return;
        }

        StartProcess(
            python,
            "-m uvicorn hermes.main:app --host 127.0.0.1 --port 8000",
            backend,
            hidden: true,
            environment: BuildEnvironment(root)
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
        Dictionary<string, string>? environment = null
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

        return Process.Start(info)
            ?? throw new InvalidOperationException($"Impossible de demarrer: {fileName}");
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
}
