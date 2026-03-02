"""
Load a TLE file and draw the Satellites, updating locations every 5 seconds.

"""

# TODO:
# - consider transforming arrow key input
# - control speed of time


from dataclasses import dataclass
import datetime
from datetime import timezone
import math
import os
import queue
import sys
import time
import threading

import torus_topo

from direct.actor.Actor import Actor
from panda3d.core import TextNode
from panda3d.core import Point3
from panda3d.core import LVecBase3
from panda3d.core import CollisionNode
from panda3d.core import CollisionRay
from panda3d.core import CollisionTraverser
from panda3d.core import CollisionHandlerQueue
from panda3d.core import GeomNode
from direct.gui.DirectGui import OnscreenText
from direct.showbase.ShowBase import ShowBase
from direct.showbase.DirectObject import DirectObject
from direct.task import Task
from direct.interval.Interval import Interval

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import uvicorn
import simapi_vis

@dataclass
class PositionUpdate:
    """Reports new positions for objects."""

    name: str
    position: tuple
    rotation: int
    now: bool
    time: datetime.datetime


done = False
DEFAULT_TIME_RATE = 1  # Default to 10x speed
time_rate = DEFAULT_TIME_RATE


update_q: queue.Queue = queue.Queue()
app = FastAPI()

def run_api():
    """
    Start the control API
    """

    config = uvicorn.Config(
        app, host="0.0.0.0", port=8888, log_level="info", loop="asyncio"
    )
    server = uvicorn.Server(config=config)
    server.run()

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    print(request)
    return {"status": "OK"}

@app.put("/update_node")
def set_link(request: simapi_vis.PositionUpdate):
    """
    Set link up or down
    """
    update_q.put(request)
    print(f"I receive req = {request}")
    return {"status": "OK"}

class World(DirectObject):

    def setup_elements(self):
        self.loadEarth()
        self.accept("q", sys.exit)
        self.accept("arrow_up", self.moveUp)
        self.accept("arrow_down", self.moveDown)
        self.accept("arrow_right", self.moveRight)
        self.accept("arrow_left", self.moveLeft)
        self.accept("=", self.zoomIn)
        self.accept("-", self.zoomOut)
        self.heading = 0
        self.pitch = 0
        self.t = threading.Thread(
            target=run_api,
            daemon=True,
        )
        self.t.start()
        base.taskMgr.add(self.gLoop, "gloop")

    def __init__(self) -> None:
        base = ShowBase()
        
        base.disableMouse()  # disable mouse control of the camera
        base.camera.setHpr(0, 0, 0)  # Set the camera orientation

        # Setup collision detection for mouse clicks
        pickerNode = CollisionNode("mouseRay")
        pickerNP = base.camera.attachNewNode(pickerNode)
        pickerNode.setFromCollideMask(GeomNode.getDefaultCollideMask())
        self.pickerRay = CollisionRay()
        pickerNode.addSolid(self.pickerRay)
        self.collisionHandler = CollisionHandlerQueue()
        self.collisionTraverser = CollisionTraverser("mouseTraverser")
        base.cTrav = self.collisionTraverser
        self.collisionTraverser.addCollider(pickerNP, self.collisionHandler)

        # Time speed up factor for animation.
        self.speed = 1
        self.zoom = 8

        # Scale earth, satellites, and orbit
        self.sat_size_scale = 0.1
        self.earth_size_scale = 10

        # Radius of earth 6373km
        # Orbit height above earch 500km
        # Scale orbit above the earth
        self.pos_scale = self.earth_size_scale / 6373
        self.satellites: dict[str, Actor] = {}
        self.ground_stations: dict[str, Actor] = {}
        self.sat_intervals: dict[str, Interval] = {}
        print(self.satellites)

        self.selected_sat = None
        self.setCameraPos()

        # Virtual current time
        self.time = OnscreenText(
            text="time",
            parent=base.a2dTopLeft,
            align=TextNode.A_left,
            fg=(0, 0, 0, 1),
            pos=(0.1, -0.1),
            scale=0.07,
            style=1,
            mayChange=True,
        )
        # Currently selected satellite
        self.info = OnscreenText(
            text="",
            parent=base.a2dTopLeft,
            align=TextNode.A_left,
            fg=(0, 0, 0, 1),
            pos=(0.1, -0.2),
            scale=0.07,
            style=1,
            mayChange=True,
        )
        self.setup_elements()
        base.run()

    def setCameraPos(self):
        altitude = 6373 + self.zoom**2 * 500
        zoom = -altitude * self.pos_scale
        #print(f"set camera y = {zoom}")
        if zoom > -self.earth_size_scale - 1:
            zoom = -self.earth_size_scale - 1
        base.camera.setPos(0, zoom, 0)  # Set the camera position (X, Y, Z)
        for name in self.satellites:
            self.satellites[name].setScale(self.get_sat_size_scale())

    def setView(self):
        self.base.setHpr(self.heading, self.pitch, 0)

    def zoomIn(self):
        if self.zoom > 1:
            self.zoom -= 1
            self.setCameraPos()

    def zoomOut(self):
        self.zoom += 1
        self.setCameraPos()

    def moveUp(self):
        self.pitch -= 30
        self.setView()

    def moveDown(self):
        self.pitch += 30
        self.setView()

    def moveLeft(self):
        self.heading -= 30
        self.setView()

    def moveRight(self):
        self.heading += 30
        self.setView()


    def get_sat_size_scale(self) -> float:
        # Increase scale with farther zoom settings.
        # zoom 8 : multiplier = 1
        return self.sat_size_scale * (self.zoom / 8)

    def loadEarth(self):
        """
        Create all of the nodes for the animation.
        """

        # Create nodes used to incline the orbit and rotate.
        # Pivots are nodes that change heading for rotation.
        # 40 orbits of 40 satellites
        self.base = base.render.attachNewNode("base")

        # Load the Earth
        self.earth = base.loader.loadModel("models/planet_sphere")
        earth_tex = base.loader.loadTexture("models/earth_1k_tex.jpg")
        self.earth.setTexture(earth_tex, 1)
        self.earth.reparentTo(self.base)
        self.earth.setScale(self.earth_size_scale)
        self.earth.setHpr(240, 0, 0)

    def processPositionUpdate(self, update: PositionUpdate):
        time_now = datetime.datetime.now(tz=timezone.utc)
        self.time.setText(time_now.isoformat(sep=" ", timespec="seconds"))
        #if update.name == "earth":
        #    #print("rotate earth: %d degrees" % update.rotation)
        #    if update.now:
        #        # This is an initial value for time now
        #        self.earth.setHpr(update.rotation, 0, 0)

        if update.name[0] == "R":
            if update.name not in self.satellites:
                sat = base.loader.loadModel("models/planet_sphere")
                sat.reparentTo(self.base)
                sat.setScale(self.get_sat_size_scale())
                sat.setTag("nametag", update.name)
                sat.setColor(1, 1, 0, 1.0)
                self.satellites[update.name] = sat 

            satellite = self.satellites[update.name]
            x = update.position[0] * self.pos_scale
            y = update.position[1] * self.pos_scale
            z = update.position[2] * self.pos_scale
            print(f"satelite pos: x={x}, y={y}, z={z}")
            satellite.setPos(x, y, z)
        
        elif update.name[0] == "G":
            print("Update Ground station")
            if update.name not in self.ground_stations:
                gs = base.loader.loadModel("models/planet_sphere")
                gs.reparentTo(self.base)
                gs.setScale(self.get_sat_size_scale()*4)
                gs.setTag("nametag", update.name)
                gs.setColor(1, 0, 1, 1.0)
                self.ground_stations[update.name] = gs 

            gs = self.ground_stations[update.name]
            x = update.position[0] * self.pos_scale
            y = update.position[1] * self.pos_scale
            z = update.position[2] * self.pos_scale
            gs.setPos(x, y, z)
        
        
        else:
            print(update.name)
        
    def gLoop(self, task):
        while not update_q.empty():
            self.processPositionUpdate(update_q.get())
        return Task.cont


if __name__ == "__main__":
    print("orbit set: [ <satellite set>  [ <time_factor> ]]")
    print()
    print(f"\tRunning set at {time_rate}X speed")
    print("\tUse arrow keys to move the view")
    print("\tUse + and - to zoom in and out")
    print("\tq to quit")
    print("\nClick on a satellite for more information")
    print()


    # Panda3D facility for manipulating image
    #threading.Thread(target=run_api(), daemon=True).start()
    w = World()

