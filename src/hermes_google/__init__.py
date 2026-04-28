from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hermes-google-mcp")
except PackageNotFoundError:
    __version__ = "0.0.0"
