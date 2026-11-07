"""Restore only SiteWatch's isolated dependencies and pinned upstream model."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import urllib.request
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--torch-site", type=Path, default=Path("/home/meg/venvs/qyx_patent/lib/python3.12/site-packages"))
    args = parser.parse_args()
    root = args.project_root.resolve()
    vision_site = root / "vision/.venv/lib/python3.12/site-packages"
    if not (args.torch_site / "torch").is_dir() or not (vision_site / "torchvision").is_dir():
        parser.error("Read-only Torch/Torchvision sites are unavailable; restore the documented base environments first.")
    env = root / ".runtime/sitewatch-env"
    venv.EnvBuilder(with_pip=True).create(env)
    (env / "lib/python3.12/site-packages/existing_runtime_readonly.pth").write_text(str(vision_site) + "\n" + str(args.torch_site) + "\n")
    subprocess.run([str(env / "bin/python"), "-m", "pip", "install", "--cache-dir", str(env / "pip-cache"),
                    "-r", str(Path(__file__).resolve().parent / "requirements-lock.txt")], check=True)
    model = root / "downloads/sitewatch/repository/models/sitewatch_best.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    expected = "c2db52b9be8ccd5bcc09d6e0f9498a6e442e47eb6f6b62850db11530b77651ab"
    if not model.is_file():
        target = model.with_suffix(".pt.partial")
        urllib.request.urlretrieve("https://raw.githubusercontent.com/AitchEm-bot/sitewatch/72c4d18135fd07afd188fecaac37c5b90ec674b4/models/sitewatch_best.pt", target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError("Downloaded SiteWatch model SHA256 mismatch; partial file retained for diagnosis")
        target.rename(model)
    if hashlib.sha256(model.read_bytes()).hexdigest() != expected:
        raise ValueError("Existing SiteWatch model SHA256 mismatch; no model was loaded")
    print(f"SiteWatch runtime ready: {env}; verified model: {model}")


if __name__ == "__main__":
    main()
