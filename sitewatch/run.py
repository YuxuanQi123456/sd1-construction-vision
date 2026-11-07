"""Launch the adapted native SiteWatch Streamlit app with isolated CPU assets."""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--background", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    env_root = project_root / ".runtime/sitewatch-env"
    python = env_root / "bin/python"
    model = project_root / "downloads/sitewatch/repository/models/sitewatch_best.pt"
    if not python.is_file() or not model.is_file():
        parser.error("SiteWatch runtime/model missing. See sitewatch/OPERATIONS.md; use --project-root for worktree execution.")
    runtime = env_root / "runtime"
    for path in [runtime, runtime / "tmp", runtime / "cache", runtime / "ultralytics", runtime / "matplotlib"]:
        path.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="", SITEWATCH_MODEL_PATH=str(model),
               SITEWATCH_PROJECT_ROOT=str(project_root),
               SITEWATCH_RUNTIME_DIR=str(runtime), YOLO_CONFIG_DIR=str(runtime / "ultralytics"),
               MPLCONFIGDIR=str(runtime / "matplotlib"), XDG_CACHE_HOME=str(runtime / "cache"),
               TMPDIR=str(runtime / "tmp"), SITEWATCH_ENABLE_LIVE="0",
               GRADIO_ANALYTICS_ENABLED="False", HF_HUB_DISABLE_TELEMETRY="1",
               STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    command = [str(python), "-m", "streamlit", "run", str(Path(__file__).resolve().parent / "app/app.py"),
               "--server.address", "127.0.0.1", "--server.port", str(args.port),
               "--server.headless", "true", "--server.fileWatcherType", "none",
               "--server.maxUploadSize", "100", "--server.disconnectedSessionTTL", "60",
               "--browser.gatherUsageStats", "false",
               "--theme.base", "light", "--theme.primaryColor", "#01539f",
               "--theme.backgroundColor", "#f4f7fb", "--theme.secondaryBackgroundColor", "#ffffff",
               "--theme.textColor", "#183650", "--theme.font", "sans serif"]
    if args.background:
        with (runtime / "streamlit.log").open("ab") as log:
            process = subprocess.Popen(command, env=env, cwd=runtime, stdout=log, stderr=log, start_new_session=True)
        (runtime / "streamlit.pid").write_text(str(process.pid) + "\n")
        print(f"SiteWatch PID {process.pid}; http://127.0.0.1:{args.port}; log: {runtime / 'streamlit.log'}")
    else:
        raise SystemExit(subprocess.call(command, env=env, cwd=runtime))


if __name__ == "__main__":
    main()
