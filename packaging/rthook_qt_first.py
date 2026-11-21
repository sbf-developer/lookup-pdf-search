# Qt has to load before MuPDF. The frozen app extracts both sets of DLLs
# into one folder, and importing MuPDF first crashes on Windows.
import PySide6  # noqa: F401
