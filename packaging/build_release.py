"""Build and verify the Windows portable EXE and per-user Inno installer.

Run with the isolated environment created by build_release.ps1.
Outputs are staged per run; release artifacts are copied only after validation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.version import __version__
from generate_assets import generate


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(command, log, timeout=600):
    with Path(log).open("w", encoding="utf-8") as stream:
        result = subprocess.run([os.fspath(value) for value in command], cwd=ROOT,
            stdout=stream, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    if result.returncode:
        tail = Path(log).read_text(encoding="utf-8", errors="replace")[-7000:]
        raise RuntimeError(f"Command failed ({result.returncode}). Log: {log}\n{tail}")


def compiler_path(override):
    candidates = [override, shutil.which("ISCC.exe")]
    for environment in ("LOCALAPPDATA", "ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(environment):
            base = Path(os.environ[environment])
            if environment == "LOCALAPPDATA":
                base /= "Programs"
            candidates.append(base / "Inno Setup 6" / "ISCC.exe")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise RuntimeError("Install Inno Setup 6 or supply --iscc with the ISCC.exe path.")


def source_snapshot():
    paths = {ROOT / name for name in (
        "main.py", "README.md", "LICENSE", "requirements.txt", ".gitignore",
        "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
    )}
    for directory in ("app", "packaging", "tests", ".github"):
        paths.update(path for path in (ROOT / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in sorted(paths) if path.is_file()}


def collect_licenses(destination):
    destination.mkdir(parents=True, exist_ok=True)
    distributions = {"Pillow": metadata.distribution("Pillow"), "Send2Trash": metadata.distribution("Send2Trash")}
    for name, distribution in distributions.items():
        for entry in distribution.files or []:
            if any(part.lower() in {"license", "license.txt", "license.md", "licenses", "copying"} for part in entry.parts):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    output = destination / name / Path(*entry.parts[1:])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, output)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, destination / "Python-LICENSE.txt")
    tcl_root = Path(sys.base_prefix) / "tcl"
    for library in ("tcl8.6", "tk8.6"):
        license_path = tcl_root / library / "license.terms"
        if license_path.is_file():
            shutil.copy2(license_path, destination / f"{library}-license.terms")
    (destination / "NOTICE.txt").write_text(
        "File Manager is GPL-3.0. Corresponding application source is supplied in the release source ZIP.\n"
        "The distribution includes CPython, Tcl/Tk, Pillow, Send2Trash, and the PyInstaller bootloader.\n"
        "PyInstaller's bootloader exception permits distribution under the application's own license.\n"
        "https://pyinstaller.org/en/stable/license.html\n", encoding="utf-8")


def inspect_pe(path, application=True):
    import pefile
    with pefile.PE(str(path)) as pe:
        if application and pe.FILE_HEADER.Machine != 0x8664:
            raise RuntimeError(f"Expected an x64 executable: {path}")
        if pe.OPTIONAL_HEADER.Subsystem != 2:
            raise RuntimeError(f"Expected a windowed executable: {path}")
        strings = {}
        for group in pe.FileInfo:
            for info in group:
                for table in getattr(info, "StringTable", []):
                    strings.update({key.decode(): value.decode() for key, value in table.entries.items()})
        if not strings.get("FileVersion", "").startswith(__version__):
            raise RuntimeError(f"Wrong executable version: {strings}")
        if not any(entry.id == 14 for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries):
            raise RuntimeError(f"Application icon missing: {path}")
        return {"machine": hex(pe.FILE_HEADER.Machine), "subsystem": "Windows GUI", "version_strings": strings,
            "authenticode_signature_present": bool(pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size)}


def smoke(executable, report, log):
    run([executable, "--smoke-test", report], log, timeout=90)
    result = json.loads(report.read_text(encoding="utf-8"))
    if not result.get("passed") or result.get("version") != __version__ or not result.get("frozen"):
        raise RuntimeError(f"Packaged smoke check failed: {report}")
    return result


def build(iscc):
    if sys.platform != "win32" or sysconfig.get_platform() != "win-amd64":
        raise RuntimeError("Build using 64-bit x64 Python on Windows.")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = ROOT / "build" / "windows" / run_id
    work.mkdir(parents=True, exist_ok=False)
    logs = work / "logs"
    logs.mkdir()
    staged = work / "release"
    staged.mkdir()
    icon, version_resource = generate(work / "assets")
    sources = source_snapshot()
    print("Validating source tests and compilation…", flush=True)
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], logs / "tests.log", timeout=180)
    run([sys.executable, "-m", "compileall", "-q", "app", "main.py", "packaging"], logs / "compile.log")
    run(["git", "diff", "--check"], logs / "whitespace.log")
    run([sys.executable, "main.py", "--smoke-test", work / "source-smoke.json"], logs / "source-smoke.log", timeout=90)
    source_smoke = json.loads((work / "source-smoke.json").read_text(encoding="utf-8"))
    if not source_smoke.get("passed"):
        raise RuntimeError("Source smoke test failed")

    third_party = work / "third_party"
    collect_licenses(third_party)
    portable_name = f"FileManager-{__version__}-Windows-x64"
    datas = [(str(ROOT / "LICENSE"), "."), (str(ROOT / "README.md"), "."),
             (str(icon.parent), "app/assets"), (str(third_party), "third_party")]
    spec = f"""# Generated by packaging/build_release.py; do not edit.
a = Analysis([{str(ROOT / 'main.py')!r}], pathex=[{str(ROOT)!r}], binaries=[],
    datas={datas!r}, hiddenimports=['PIL.ImageTk', 'send2trash', 'send2trash.win.legacy'],
    hookspath=[], hooksconfig={{}}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
portable = EXE(pyz, a.scripts, a.binaries, a.datas, [], name={portable_name!r},
    debug=False, strip=False, upx=False, console=False,
    icon={str(icon)!r}, version={str(version_resource)!r})
installed = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FileManager',
    debug=False, strip=False, upx=False, console=False,
    icon={str(icon)!r}, version={str(version_resource)!r})
collection = COLLECT(installed, a.binaries, a.datas, strip=False, upx=False, name='FileManager')
"""
    spec_path = work / "file-manager.spec"
    spec_path.write_text(spec, encoding="utf-8")
    dist = work / "dist"
    print("Building portable and installed application bundles…", flush=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", dist,
         "--workpath", work / "pyinstaller", spec_path], logs / "pyinstaller.log", timeout=900)
    bundle = dist / "FileManager"
    for name in ("LICENSE", "README.md"):
        shutil.copy2(ROOT / name, bundle / name)
    portable = dist / f"{portable_name}.exe"
    app_exe = bundle / "FileManager.exe"
    binaries = {"portable": inspect_pe(portable), "installed": inspect_pe(app_exe)}
    print("Running smoke tests against both packaged executables…", flush=True)
    portable_smoke = smoke(portable, work / "portable-smoke.json", logs / "portable-smoke.log")
    bundle_smoke = smoke(app_exe, work / "bundle-smoke.json", logs / "bundle-smoke.log")

    print("Compiling the per-user installer…", flush=True)
    run([iscc, "/Qp", f"/DAppVersion={__version__}", f"/DBundleDir={bundle}",
         f"/DReleaseDir={staged}", f"/DProjectDir={ROOT}", ROOT / "packaging" / "file-manager.iss"],
        logs / "installer-build.log", timeout=600)
    installer = staged / f"{portable_name}-Setup.exe"
    binaries["installer"] = inspect_pe(installer, application=False)

    print("Testing the exact installer and uninstaller in an isolated folder…", flush=True)
    installation = work / "installer-smoke"
    if installation.exists():
        raise RuntimeError("Installer smoke path must be new")
    run([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/PACKAGINGSMOKE=1",
         f"/DIR={installation}", f"/LOG={logs / 'installation.log'}"], logs / "installer-launch.log", timeout=180)
    payload = {path.relative_to(bundle).as_posix(): sha256(path) for path in bundle.rglob("*") if path.is_file()}
    try:
        for relative, expected in payload.items():
            if sha256(installation / relative) != expected:
                raise RuntimeError(f"Installed file differs from packaged payload: {relative}")
        installed_smoke = smoke(installation / "FileManager.exe", work / "installed-smoke.json", logs / "installed-smoke.log")
    finally:
        uninstaller = installation / "unins000.exe"
        if uninstaller.is_file():
            run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                 f"/LOG={logs / 'uninstallation.log'}"], logs / "uninstaller-launch.log", timeout=120)
    deadline = time.monotonic() + 10
    while (installation / "FileManager.exe").exists() and time.monotonic() < deadline:
        time.sleep(.1)
    if any((installation / relative).exists() for relative in payload):
        raise RuntimeError("Uninstaller left application payload files behind")
    if sources != source_snapshot():
        raise RuntimeError("Application/build sources changed during packaging; rebuild required")

    source_zip = staged / f"FileManager-{__version__}-Source.zip"
    with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sources:
            archive.write(ROOT / relative, arcname=f"FileManager-{__version__}/{relative}")
    shutil.copy2(portable, staged / portable.name)
    for name in ("source-smoke.json", "portable-smoke.json", "bundle-smoke.json", "installed-smoke.json"):
        shutil.copy2(work / name, staged / name)
    write_json(staged / "source-manifest.json", sources)
    write_json(staged / "installed-payload-sha256.json", payload)
    dependencies = {distribution.metadata["Name"]: distribution.version for distribution in metadata.distributions()}
    write_json(staged / "dependencies.json", dependencies)
    manifest = {"version": __version__, "build_utc": run_id, "python": sys.version,
        "python_platform": sysconfig.get_platform(), "host_machine": platform.machine(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree_changes_included": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "checks": {"tests": "passed", "compilation": "passed", "whitespace": "passed",
            "source_smoke": source_smoke["passed"], "portable_smoke": portable_smoke["passed"],
            "bundle_smoke": bundle_smoke["passed"], "installed_smoke": installed_smoke["passed"],
            "installer_payload_hashes": "passed", "uninstaller": "passed"},
        "binaries": binaries,
        "artifacts": {path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(staged.iterdir()) if path.suffix.lower() in {".exe", ".zip"}}}
    write_json(staged / "build-manifest.json", manifest)
    artifacts = sorted(path for path in staged.iterdir() if path.is_file())
    (staged / "SHA256SUMS.txt").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in artifacts), encoding="utf-8")
    release = ROOT / "release" / __version__
    release.mkdir(parents=True, exist_ok=True)
    for artifact in staged.iterdir():
        shutil.copy2(artifact, release / artifact.name)
    for line in (release / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if sha256(release / name) != digest:
            raise RuntimeError(f"Final release copy failed checksum verification: {name}")
    print(f"Release ready: {release}", flush=True)
    print(f"Build logs: {logs}", flush=True)
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", help="Path to the Inno Setup 6 compiler")
    arguments = parser.parse_args()
    build(compiler_path(arguments.iscc))
