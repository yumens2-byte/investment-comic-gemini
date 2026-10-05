"""SIDESTORY track — New Network side-canon comics (Phase-1: main→side echo only).

Boundary rules (enforced by sidestory/tests/test_boundary.py):
  DR-1  engine/ and scripts/ never import ``sidestory``.
  DR-2  sidestory.core / ports / app never import ``engine``.
  DR-3  ``engine`` imports live only in sidestory/adapters/icg/ (whitelisted symbols).
  DR-4  main (icg.*) tables are read only through the icg_side.main_feed_*_v1 views.

This package is designed to be split into its own repository with
``git subtree split --prefix=sidestory`` once stable.
"""

__version__ = "0.1.0"
