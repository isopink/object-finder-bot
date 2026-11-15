"""Toy world for running the objmem pipeline without the robot.

- ``world``: ToyWorld (room, desks, ten objects, synthetic CLIP-like embeddings), patrol_path
- ``sensors``: SimCamera (fake detector, depth and nodepth), SimNavigator, SimVerifier, LabelVerifier
- ``baseline``: BaselineMemory (no probability, no fusion), LabelQueryMemory (label-match search)
- ``runner``: Sim, which wires the real ObjectMemory, geometry.observe and search.find to the toy world
"""
from objmem.sim.world import MOVE_SPOTS, EmbeddingSpace, SimEmbedder, SimObject, ToyWorld, patrol_path
from objmem.sim.sensors import LabelVerifier, SimCamera, SimNavigator, SimVerifier, query_label
from objmem.sim.baseline import BaselineMemory, LabelQueryMemory

__all__ = ["MOVE_SPOTS", "EmbeddingSpace", "SimEmbedder", "SimObject", "ToyWorld", "patrol_path",
           "LabelVerifier", "SimCamera", "SimNavigator", "SimVerifier", "query_label",
           "BaselineMemory", "LabelQueryMemory"]
