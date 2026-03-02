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
            print(f"update node")
            url = f"{self.url}/update_node"
            js = data.model_dump(mode="json")
            print(f"I send JSON = {js}")
            r = requests.put(
                url,
                json=data.model_dump(mode="json")
            )
            print(r.text)
        except requests.exceptions.ConnectionError as e:
            print(e)
            pass

#    def init_satellites(self, data: simapi_vis.PositionInit) -> None:
#        try:
#            print(f"init satellites")
#            url = f"{self.url}/init_satellites"
#            js = data.model_dump(mode="json")
#            print(f"I send JSON = {js}")
#            r = requests.put(
#                url,
#                json=data.model_dump(mode="json")
#            )
#            print(r.text)
#        except requests.exceptions.ConnectionError as e:
#            print(e)
#            pass
