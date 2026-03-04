"""
Client to drive the JSON api implemented in driver.py
"""
import requests
import simapi_vis

class Client:
    def __init__(self, url: str) -> None:
        self.url = url

    def update_node(self, data: simapi_vis.PositionUpdate) -> None:
        try:
            url = f"{self.url}/update_node"
            js = data.model_dump(mode="json")
            r = requests.put(
                url,
                json=data.model_dump(mode="json")
            )
            print(r.text)
        except requests.exceptions.ConnectionError as e:
            print(e)
            pass

    def draw_orbits(self, data: simapi_vis.Orbit) -> None:
        try:
            url = f"{self.url}/draw_orbit"
            js = data.model_dump(mode="json")
            r = requests.put(
                url,
                json=data.model_dump(mode="json")
            )
            print(r.text)
        except requests.exceptions.ConnectionError as e:
            print(e)
            pass
