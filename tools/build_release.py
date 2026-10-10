"""Build the release: the mod as a standalone program, then the installer.

  python tools/build_release.py

1. PyInstaller turns run.py into build/release/MBAccess/MBAccess.exe (Python and every
   library included, so players don't need Python).
2. The speech DLLs and the auto-start loader (loader/dinput8.dll, from
   tools/build_loader.py build) are added next to it.
3. That folder is zipped and packed into the installer, installer/setup.py, which
   PyInstaller turns into dist/MBAccess-Setup.exe: the one file a release carries.
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import openal  # noqa: E402
from mbaccess import VERSION  # noqa: E402

BUILD = os.path.join(ROOT, "build", "release")
APP = os.path.join(BUILD, "MBAccess")
DIST = os.path.join(ROOT, "dist")
SEP = os.pathsep
# Parts of Python neither program uses, left out to keep the download small: web
# encryption (the installer downloads with Windows' own code), windowing toolkits, tests.
UNUSED = ["ssl", "_ssl", "tkinter", "_tkinter", "unittest", "pydoc", "doctest", "bz2", "_bz2",
          "regex", "yaml", "PIL", "http", "xml", "html", "numpy.f2py", "numpy.distutils"]
SKIP = [a for name in UNUSED for a in ("--exclude-module", name)]


def pyinstaller(*args):
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--workpath", os.path.join(BUILD, "work"),
                    "--specpath", os.path.join(BUILD, "spec"), *args], check=True, cwd=ROOT)


def build_app():
    shutil.rmtree(APP, ignore_errors=True)
    sound = os.path.join(os.path.dirname(openal.__file__), "soft_oal_64.dll")
    # Files the code opens by path, which PyInstaller can't see by itself: where they
    # are now -> the folder they must sit in inside the program (see mbaccess/paths.py).
    data = [(os.path.join(ROOT, "profiles"), "profiles"),
            (os.path.join(ROOT, "mbaccess", "message_categories.json"), "mbaccess")]
    pyinstaller("--name", "MBAccess", "--noconsole", "--onedir", "--distpath", BUILD,
                "--add-binary", f"{sound}{SEP}openal", *SKIP,
                *[a for src, dst in data for a in ("--add-data", f"{src}{SEP}{dst}")],
                os.path.join(ROOT, "run.py"))
    for dll in os.listdir(os.path.join(ROOT, "native")):
        shutil.copy2(os.path.join(ROOT, "native", dll), APP)
    shutil.copy2(os.path.join(ROOT, "loader", "dinput8.dll"), APP)
    shutil.copy2(os.path.join(ROOT, "README.md"), os.path.join(APP, "README.md"))


def build_installer():
    payload = os.path.join(BUILD, "payload.zip")
    # LZMA (the 7-Zip method) packs program files about a third smaller than plain zip.
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_LZMA) as z:
        for folder, _, files in os.walk(APP):
            for name in files:
                full = os.path.join(folder, name)
                z.write(full, os.path.relpath(full, APP))
    pyinstaller("--name", "MBAccess-Setup", "--onefile", "--noconsole", "--uac-admin", *SKIP,
                "--distpath", DIST, "--paths", ROOT, "--add-data", f"{payload}{SEP}.",
                "--add-data", f"{os.path.join(ROOT, 'installer', 'controls.dat')}{SEP}.",
                os.path.join(ROOT, "installer", "setup.py"))
    print("built", os.path.join(DIST, "MBAccess-Setup.exe"), "version", VERSION)


if __name__ == "__main__":
    build_app()
    build_installer()
