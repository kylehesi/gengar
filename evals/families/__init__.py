"""Ölçüm v2 görev aileleri."""

from . import code, compound, files, live


def all_families():
    return [*files.FAMILIES, *code.FAMILIES, *live.FAMILIES, *compound.FAMILIES]
