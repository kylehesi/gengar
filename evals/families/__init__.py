"""Ölçüm v2 görev aileleri."""

from . import code, compound, files, live, notool


def all_families():
    return [*files.FAMILIES, *code.FAMILIES, *live.FAMILIES, *compound.FAMILIES, *notool.FAMILIES]
