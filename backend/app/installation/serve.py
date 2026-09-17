"""Serve only an initialized managed DB. No migration, seed, or account creation."""
import os

from .maintenance import main


def serve():
    if main(["check-ready"]) != 0:
        return 1
    os.execvp("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"])


if __name__ == "__main__":
    raise SystemExit(serve())
