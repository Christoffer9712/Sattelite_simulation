from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel, info
from mininet.cli import CLI
import configNwIpv4
import configNwIpv6
import runNw


def run(ipVersion=4):
    ipVersion = 6
    if ipVersion == 4:
        print("Started run with IPv4")
        configNw = configNwIpv4
    elif ipVersion == 6:
        print("Started run with IPv6")
        configNw = configNwIpv6
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