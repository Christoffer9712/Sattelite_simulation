from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel, info
from mininet.cli import CLI
import configNw
import runNw


def run():
    print("Started run")
    # Create a networkx graph annoted with FRR configs
    graph = configNw.create_network()
    configNw.annotate_graph(graph)
    #configNw.dump_graph(graph)

    # Use the networkx graph to build a mininet topology
    topo = configNw.NetxTopo(graph)
    print("generated topo")

    # Run mininet
    net = Mininet(topo=topo, controller=None)
    net.start()

    frrt = configNw.FrrSimRuntime(topo, net)
    print("created runtime")

    frrt.start_routers()

    print(f"\n****Running Network")
    CLI(net)
    
    frrt.stop_routers()

    net.stop()

if __name__ == "__main__":
    run()