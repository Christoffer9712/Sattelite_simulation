"""
Definitions for elements of the Simulator API

The server side of the API is implemented in mnet/driver.py
The client side is implemented in mnet/client.py
"""
import datetime
from pydantic import BaseModel

from dataclasses import dataclass, field



@dataclass
class Satellite:
    """Represents an instance of a satellite"""
    name: str
    position: tuple
    rotation: int
    now: bool
    time: datetime.datetime

@dataclass
class GroundStation:
    """Represents an instance of a ground station"""
    name: str
    position: tuple
    rotation: int
    now: bool
    time: datetime.datetime

class PositionUpdate(BaseModel):
    """Reports new positions for objects."""
    name: str
    position: tuple
    rotation: int
    now: bool
    time: datetime.datetime

#class PositionInit(BaseModel):
#    satellites: list[PositionUpdate]
#    ground_stations: list[PositionUpdate]