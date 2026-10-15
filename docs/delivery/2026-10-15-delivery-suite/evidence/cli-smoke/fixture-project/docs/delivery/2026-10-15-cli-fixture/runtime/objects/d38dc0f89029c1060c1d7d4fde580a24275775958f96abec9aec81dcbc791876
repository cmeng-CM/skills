from pathlib import Path
import runpy
root = Path.cwd()
app = runpy.run_path(str(root / "src/app.py"))
actual = app["message"]()
assert actual == "works", repr(actual)
print("fixture actual function behavior: works")
