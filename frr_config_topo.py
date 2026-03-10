"""
Configure a network topology to function as a set of FRR routers.

Generate IP addresses, interface names, and FRR configurations for a topology
and mark up the topology graph with the information.

Currently assumes all nodes run OSPF in one area.
"""

import ipaddress
import networkx

import torus_topo


def annotate_graph(graph: networkx.Graph):
    """
    Annotate a topology with IP address for each node and IP address and interface names
    for each edge.
    """
    count = 1
    for name in torus_topo.satellites(graph):
        node = graph.nodes[name]
        # Configure node with an ip address
        node["inf_count"] = 0
        node["number"] = count
        ip = 0x0A010000 + count # 10.1.0.0
        count += 2
        node["ip"] = ipaddress.IPv4Interface((ip, 31))

    count = 1
    for name in torus_topo.ground_stations(graph):
        node = graph.nodes[name]
        # Configure node with an ip address
        node["inf_count"] = 0
        node["number"] = count
        ip = 0x0A020000 + count # 10.2.0.0
        count += 2
        node["ip"] = ipaddress.IPv4Interface((ip, 31))

    count = 1
    for name in torus_topo.ground_routers(graph):
        node = graph.nodes[name]
        # Configure node with an ip address
        node["inf_count"] = 0
        node["number"] = count
        ip = 0x0A030000 + count # 10.3.0.0
        count += 2
        node["ip"] = ipaddress.IPv4Interface((ip, 31))

    count = 1
    for name in torus_topo.cores(graph):
        node = graph.nodes[name]
        # Configure node with an ip address
        node["inf_count"] = 0
        node["number"] = count
        ip = 0x0A040000 + count # 10.4.0.0
        count += 2
        node["ip"] = ipaddress.IPv4Interface((ip, 31))

    countOspf = 1
    countBgp = 1
    #for edge in graph.edges.values():
    #    # Configure edge with a subnet
    #    edge["number"] = count
    #    ip = 0x0A0F0000 + count * 4 # 10.15.0.0
    #    count += 1
    #    edge["ip"] = ipaddress.IPv4Network((ip, 30))

    for n1, n2 in graph.edges:
        # Set ip addresses for each end of an edge
        edge = graph.edges[n1, n2]
        if edge["routing"] == "ospf":
            edge["number"] = countOspf
            ip = 0x0A0F0000 + countOspf * 4 # 10.15.0.0
            edge["ip"] = ipaddress.IPv4Network((ip, 30))
            ips = list(edge["ip"].hosts())
            countOspf += 1
        elif edge["routing"] == "bgp":
            edge["number"] = countBgp
            ip = 0xAC100000 + countBgp * 4 # 172.16.0.0
            edge["ip"] = ipaddress.IPv4Network((ip, 30))
            ips = list(edge["ip"].hosts())
            countBgp += 1
        else:
            raise ValueError("Routing not supported")
        graph.adj[n1][n2]["ip"] = {}
        graph.adj[n1][n2]["ip"][n1] = ipaddress.IPv4Interface((ips[0].packed, 30))
        graph.adj[n2][n1]["ip"][n2] = ipaddress.IPv4Interface((ips[1].packed, 30))

        # Set interface names for each end of an edge
        c = graph.nodes[n1]["inf_count"] + 1
        graph.nodes[n1]["inf_count"] = c
        intf1 = f"{n1}-eth{c}"

        c = graph.nodes[n2]["inf_count"] + 1
        graph.nodes[n2]["inf_count"] = c
        intf2 = f"{n2}-eth{c}"

        graph.adj[n1][n2]["intf"] = {}
        graph.adj[n1][n2]["intf"][n1] = intf1
        graph.adj[n2][n1]["intf"][n2] = intf2

    # Generate config information for the satellites
    for name in torus_topo.satellites(graph):
        node = graph.nodes[name]
        node["ospf"] = create_ospf_config(graph, name)
        node["vtysh"] = create_vtysh_config(name)
        node["daemons"] = create_daemons_config(node["type"])

    # Generate config information for the cores
    for name in torus_topo.cores(graph):
        node = graph.nodes[name]
        node["ospf"] = create_ospf_config(graph, name)
        node["vtysh"] = create_vtysh_config(name)
        node["daemons"] = create_daemons_config(node["type"])

    # Generate config information for the ground routers
    for name in torus_topo.ground_routers(graph):
        node = graph.nodes[name]
        node["ospf"] = create_ospf_config(graph, name)
        node["vtysh"] = create_vtysh_config(name)
        node["daemons"] = create_daemons_config(node["type"])

    # Generate ip link pool information for the ground stations
    # Christoffer, I now create OSPF config for the GW towards sat net
    count = 1
    for name in torus_topo.ground_stations(graph):
        node = graph.nodes[name]
        uplinks = []

        for i in range(4):
            ip = 0x0A0E0000 + count * 4 # 10.14.0.0
            count += 1
            nw_link = ipaddress.IPv4Network((ip, 30))
            ips = list(nw_link.hosts())
            uplink = {"nw": nw_link,
                      "ip1": ipaddress.IPv4Interface((ips[0].packed, 30)),
                      "ip2": ipaddress.IPv4Interface((ips[1].packed, 30))}
            uplinks.append(uplink)

        node["uplinks"] = uplinks
        node["ospf"] = create_ospf_config(graph, name)
        node["vtysh"] = create_vtysh_config(name)
        node["daemons"] = create_daemons_config(node["type"])

OSPF_TEMPLATE = """
hostname {name}
frr defaults datacenter
log syslog informational
ip forwarding
no ipv6 forwarding
service integrated-vtysh-config
!
router ospf
 ospf router-id {ip}
 {redistribute}
 {networks}
{bgp}
exit
"""

BGP_TEMPLATE = """
!
router bgp {bgpId}
 bgp router-id {routerIP}
 distance bgp 200 200 200
 neighbor {neighborIP} remote-as {remoteId}

 address-family ipv4 unicast
  redistribute ospf
  redistribute connected
  neighbor {neighborIP} activate
 exit-address-family
!
"""

OSPF_NW_TEMPLATE = """network {network} area 0.0.0.0"""

def create_ospf_config(graph: networkx.Graph, name: str) -> str:
    node = graph.nodes[name]
    ip = node.get("ip")  # May be None
    networks = []
    networks_str = []

    if ip is not None:
        # Make loopback a /32
        # TODO: since this is a IPv4Interface, maybe don't change? Try that
        network = ipaddress.IPv4Network((ip.ip, 32))
        networks_str.append(OSPF_NW_TEMPLATE.format(network=format(network)))

    if node["type"] == "satellite":
        #for neighbor in graph.adj[name]:
        #    edge = graph.adj[name][neighbor]
        #    networks.append(edge["ip"][name])
            # Get one of the interface IPs for the router id
        #    if ip is None:
        #        ip = edge["ip"][name]
        # All links between ground GW and sat are in OSPF and are ion 10.14.0.0/16 subnet
        networks.append(ipaddress.IPv4Network(('10.14.0.0', 16)))
        # All links between satellites are in OSPF and are in 10.15.0.0/16 subnet
        networks.append(ipaddress.IPv4Network(('10.15.0.0', 16)))
        redistribute = ""
        bgp = ""

    elif node["type"] == "ground_station":
        networks.append(ipaddress.IPv4Network(('10.14.0.0', 16)))
        redistribute = "redistribute bgp"
        for neighbor in graph.adj[name]: # only 1 neighbor (ground router)
            edge = graph.adj[name][neighbor]
            bgp_ip = edge['ip'][name]
            neighbor_bgp_ip = edge["ip"][neighbor]
            #print(f"Christoffer ground_station node = {name}, neighbor = {neighbor}, neighbor IP = {neighbor_bgp_ip.ip}, current ip = {bgp_ip.ip}") 
        bgp = BGP_TEMPLATE.format(
            bgpId=65001, 
            routerIP=ip.ip,
            neighborIP=neighbor_bgp_ip.ip,
            remoteId=65002
        )

    elif node["type"] == "ground_router":
        for neighbor in graph.adj[name]:
            #print(f'Christoffer neighbor = {neighbor}')
            
            if neighbor[0] == 'G': 
                edge = graph.adj[name][neighbor]
                bgp_ip = edge['ip'][name]
                neighbor_bgp_ip = edge["ip"][neighbor]
            #else: # No OSPF between GW and ground router
            #    #print(f'Christoffer neighbor added as edge = {neighbor}')
            #    edge = graph.adj[name][neighbor]
            #    networks.append(edge["ip"][name])
            #    # Get one of the interface IPs for the router id
            #    if ip is None:
            #        ip = edge["ip"][name]
        # All links within ground network are in 10.15.0.0 range excepth to the GW
        networks.append(ipaddress.IPv4Network(('10.15.0.0', 16)))    
        redistribute = "redistribute bgp"

        bgp = BGP_TEMPLATE.format(
            bgpId=65002, 
            routerIP=ip.ip,
            neighborIP=neighbor_bgp_ip.ip,
            remoteId=65001
        )

    elif node["type"] == "core":
        #for neighbor in graph.adj[name]:
        #    edge = graph.adj[name][neighbor]
        #    networks.append(edge["ip"][name])
        #    # Get one of the interface IPs for the router id
        #    if ip is None:
        #        ip = edge["ip"][name]
        # All links within ground network are in 10.15.0.0 range
        networks.append(ipaddress.IPv4Network(('10.15.0.0', 16)))  
        redistribute = ""
        bgp = ""
    
    for network in networks:
        networks_str.append(OSPF_NW_TEMPLATE.format(network=format(network)))

    # Router ID must be a plain IP, no subnet.
    return OSPF_TEMPLATE.format(
        name=name, ip=format(ip.ip), redistribute=redistribute, networks="\n".join(networks_str), bgp=bgp
    )


def create_daemons_config(type: str) -> str:
    msg = """#
ospfd=yes
bgpd={}
vtysh_enable=yes
zebra_options="  -A 127.0.0.1 -s 90000000"
mgmtd_options="  -A 127.0.0.1"
ospfd_options="  -A 127.0.0.1"
staticd_options="  -A 127.0.0.1"
    """
    return msg.format("yes" if type in ["ground_station", "ground_router"] else "no")

def create_vtysh_config(name: str) -> str:
    return """service integrated-vtysh-config
hostname {name}""".format(
        name=name
    )

def dump_graph(graph: networkx.Graph):
    for name, node in graph.nodes.items():
        ip = node.get("ip")
        if ip is not None:
            ip = format(ip)
        else:
            ip = ""

        print(f"node: {name} - {ip}")
        for neighbor in graph.adj[name]:
            edge = graph.adj[name][neighbor]
            print(
                f'\t{format(edge["ip"][name])}  : {edge["intf"][name]} to {neighbor} ({format(edge["ip"][neighbor])})'
            )

    print()
    for n, edge in graph.edges.items():
        print(f'edge: {n} - {format(edge["ip"])}')


def gen_test_graph() -> networkx.Graph:
    graph = networkx.Graph()

    graph.add_node("R1")
    graph.nodes["R1"][torus_topo.TYPE] = torus_topo.TYPE_SAT
    graph.add_node("R2")
    graph.nodes["R2"][torus_topo.TYPE] = torus_topo.TYPE_SAT
    graph.add_node("R3")
    graph.nodes["R3"][torus_topo.TYPE] = torus_topo.TYPE_SAT
    graph.add_node("R4")
    graph.nodes["R4"][torus_topo.TYPE] = torus_topo.TYPE_SAT

    graph.add_edge("R1", "R2")
    graph.add_edge("R2", "R3")
    graph.add_edge("R3", "R4")
    graph.add_edge("R4", "R1")
    return graph

def test_config_graph() -> bool:
    g = gen_test_graph()
    annotate_graph(g)
    dump_graph(g)
    return True


if __name__ == "__main__":
    # Run a simple test
    test_config_graph()
