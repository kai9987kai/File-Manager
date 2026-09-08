"""Generate the application icon and Windows executable version resource."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.version import __version__


def generate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    assets = ROOT / "app" / "assets"
    assets.mkdir(exist_ok=True)
    image = Image.new("RGBA", (1024, 1024))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((32, 32, 992, 992), radius=215, fill="#18253d")
    draw.rounded_rectangle((158, 258, 520, 438), radius=52, fill="#81b5ff")
    draw.rounded_rectangle((158, 335, 866, 775), radius=62, fill="#326bd6")
    draw.rounded_rectangle((554, 199, 785, 465), radius=28, fill="#f3f7ff")
    draw.rounded_rectangle((591, 253, 747, 273), radius=9, fill="#a0bce5")
    draw.rounded_rectangle((591, 305, 712, 325), radius=9, fill="#a0bce5")
    draw.rounded_rectangle((158, 405, 866, 790), radius=62, fill="#4b8ef0")
    draw.rounded_rectangle((224, 467, 420, 494), radius=12, fill="#cfe3ff")
    image = image.resize((256, 256), Image.Resampling.LANCZOS)
    image.save(assets / "file-manager.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    version_tuple = tuple(int(number) for number in __version__.split(".")) + (0,)
    fields = {
        "CompanyName": "File Manager contributors",
        "FileDescription": "File Manager desktop application",
        "FileVersion": __version__,
        "InternalName": "FileManager",
        "LegalCopyright": "GPL-3.0; File Manager contributors",
        "OriginalFilename": "FileManager.exe",
        "ProductName": "File Manager",
        "ProductVersion": __version__,
    }
    strings = ",\n".join(f"                StringStruct({key!r}, {value!r})" for key, value in fields.items())
    resource = f"""VSVersionInfo(
    ffi=FixedFileInfo(filevers={version_tuple!r}, prodvers={version_tuple!r},
        mask=0x3f, flags=0, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
{strings}
    ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"""
    (output / "version-resource.txt").write_text(resource, encoding="utf-8")
    return assets / "file-manager.ico", output / "version-resource.txt"


if __name__ == "__main__":
    generate(sys.argv[1] if len(sys.argv) > 1 else ROOT / "build" / "assets")
