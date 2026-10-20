"""API route registry."""
from __future__ import annotations


def routes():
    from . import auth
    modules = [auth]
    for name in ("profile", "reviews", "readiness", "interviews", "jobs", "applications",
                 "notifications", "chat", "settings", "privacy", "admin", "tasks_api"):
        try:
            modules.append(__import__(f"{__name__}.{name}", fromlist=["router"]))
        except ModuleNotFoundError as exc:  # module not written yet
            if exc.name and exc.name.endswith(name):
                continue
            raise
    out = []
    for module in modules:
        out.extend(module.router.routes)
    return out
