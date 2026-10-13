"""Game-owned MG2 companion skeleton; no operators or handlers in G1."""
from . import bootstrap


def register():
    bootstrap.register()


def unregister():
    bootstrap.unregister()
