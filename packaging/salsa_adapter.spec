# PyInstaller spec for the adapter app: one self-contained executable (SalsaAdapter.exe on Windows).
# Build from the repo root:  pyinstaller packaging/salsa_adapter.spec --noconfirm
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = SPECPATH + "/.."

datas = [
    (ROOT + "/cad/adapter_app/static", "cad/adapter_app/static"),
    (ROOT + "/cad/data", "cad/data"),
]
datas += collect_data_files("trimesh")          # trimesh ships JSON resources it reads at runtime

a = Analysis(
    [ROOT + "/packaging/entry.py"],
    pathex=[ROOT],
    binaries=collect_dynamic_libs("manifold3d"),
    datas=datas,
    # trimesh imports these lazily inside functions, so the analysis can't see them.
    hiddenimports=["manifold3d", "shapely", "mapbox_earcut", "scipy.spatial", "networkx", "rtree",
                   "matplotlib.backends.backend_agg", "lxml.etree"],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "pytest", "requests",
              "meshy3d.client", "meshy3d.pipeline", "meshy3d.cli"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="SalsaAdapter",
    console=True,        # the console window shows the URL; closing it stops the app
    upx=False,
    icon=None,
)
