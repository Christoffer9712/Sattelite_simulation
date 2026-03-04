"""
Definitions for elements of the Simulator API

The server side of the API is implemented in mnet/driver.py
The client side is implemented in mnet/client.py
"""
import datetime
from pydantic import BaseModel

from dataclasses import dataclass, field


class UpLink(BaseModel):
    sat_node: str
    distance: int

class UpLinks(BaseModel):
    ground_node: str
    uplinks: list[UpLink]

@dataclass
class Satellite:
    """Represents an instance of a satellite"""
    name: str
    position: tuple

@dataclass
class GroundStation:
    """Represents an instance of a ground station"""
    name: str
    position: tuple
    uplinks: UpLinks

class PositionUpdate(BaseModel):
    """Reports new positions for objects."""
    name: str
    position: tuple

#class PositionInit(BaseModel):
#    satellites: list[PositionUpdate]
#    ground_stations: list[PositionUpdate]