import networkx
import mininet.topo
import mininet.node
import mininet.net
import mininet.link
import mininet.util
import ipaddress
import pwd
import os
import grp

def create_network() -> networkx.Graph:
    """
    Create a simple network for test of OSPF + BGP
    """
    
    graph: networkx.Graph = networkx.Graph()
    
    # Network 0 -- 3 routers in mesh topology
    graph.add_node("R0_0")
    graph.nodes["R0_0"]["bgp_edge"] = False
    
    graph.add_node("R0_1")
    graph.nodes["R0_1"]["bgp_edge"] = False

    graph.add_node("R0_2")
    graph.nodes["R0_2"]["bgp_edge"] = True

    graph.add_edge("R0_0", "R0_1")
    graph.edges["R0_0", "R0_1"]["routing"] = "ospf"

    graph.add_edge("R0_0", "R0_2")
    graph.edges["R0_0", "R0_2"]["routing"] = "ospf"

    graph.add_edge("R0_1", "R0_2")
    graph.edges["R0_1", "R0_2"]["routing"] = "ospf"


    # Network 1 -- 4 routers in 'link' topology
    graph.add_node("R1_0")
    graph.nodes["R1_0"]["bgp_edge"] = True

    graph.add_node("R1_1")
    graph.nodes["R1_1"]["bgp_edge"] = False

#    graph.add_node("R1_2")
#    graph.nodes["R1_2"]["bgp_edge"] = False

#    graph.add_node("R1_3")
#    graph.nodes["R1_3"]["bgp_edge"] = False

    graph.add_edge("R1_0", "R1_1")
    graph.edges["R1_0", "R1_1"]["routing"] = "ospf"

#    graph.add_edge("R1_1", "R1_2")
#    graph.edges["R1_1", "R1_2"]["routing"] = "ospf"

#    graph.add_edge("R1_2", "R1_3")
#    graph.edges["R1_2", "R1_3"]["routing"] = "ospf"

    # Connect the networks
    graph.add_edge("R0_2", "R1_0")
    graph.edges["R0_2", "R1_0"]["routing"] = "bgp"

    return graph

def annotate_graph(graph: networkx.Graph) -> networkx.Graph:
    """
    Add IP addresses to nodes
    """
    # Add loop-back IP
    count1 = 1
    count2 = 1
    for name in graph.nodes():
        node = graph.nodes[name]
        if name[1] == "0":
            ip = 0xFC0010000000000000000000000000 + count1 # fc00:1::/128 range for nw1
            count1 += 1 #2?
            node["ip"] = ipaddress.IPv6Interface((ip, 128)) 
            node['defaultGateway'] = format(ipaddress.IPv6Address(0xFC0010000000000000000000000003)) # IP of R0_2

        elif name[1] == "1":
            ip = 0xFC0020000000000000000000000000 + count2 # fc00:2::/128 range for nw2
            count2 += 1
            node["ip"] = ipaddress.IPv6Interface((ip, 128))
            node['defaultGateway'] = format(ipaddress.IPv6Address(0xFC0020000000000000000000000002)) # IP of R1_0

    countOspf = 1
    countBgp = 1

    for n1, n2 in graph.edges:
        # Set ip addresses for each end of an edge
        edge = graph.edges[n1, n2]
        if edge["routing"] == "ospf":
            ip = 0xFB0010000000000000000000000000 + countOspf * 4 # fb00:1::/126 range for OSPF links
            edge["ip"] = ipaddress.IPv6Network((ip, 126))
            ips = list(edge["ip"].hosts())
            countOspf += 1
        elif edge["routing"] == "bgp":
            ip =  0xFB0020000000000000000000000000 + countBgp * 4 # fb00:2::/126 range for BGP links
            edge["ip"] = ipaddress.IPv6Network((ip, 126))
            ips = list(edge["ip"].hosts())
            countBgp += 1
        else:
            raise ValueError("Routing not supported")

        graph.adj[n1][n2]["ip"] = {}
        graph.adj[n1][n2]["ip"][n1] = ipaddress.IPv6Interface((ips[0].packed, 126))
        graph.adj[n2][n1]["ip"][n2] = ipaddress.IPv6Interface((ips[1].packed, 126))

        # Set interface names for each end of an edge
        intf1 = f"{n1}-eth{n2}"
        intf2 = f"{n2}-eth{n1}"

        graph.adj[n1][n2]["intf"] = {}
        graph.adj[n1][n2]["intf"][n1] = intf1
        graph.adj[n2][n1]["intf"][n2] = intf2

    # Generate config information for the satellites
    for name in graph:
        node = graph.nodes[name]
        node["ospf"] = create_ospf_config(graph, name)
        node["vtysh"] = create_vtysh_config(name)
        node["daemons"] = create_daemons_config()
    
    return graph

OSPF_TEMPLATE = """
hostname {name}
frr defaults datacenter
log syslog informational
ip forwarding
service integrated-vtysh-config
{addDefaultGateway} 
!
router ospf
 ospf router-id {ip}
 {redistribute}
{networks}

{bgp}
"""

BGP_TEMPLATE = """
!
router bgp {bgpId}
 bgp router-id {routerIP}
 distance bgp 200 200 200
 neighbor {neighborIP} remote-as {remoteId}

 address-family ipv6 unicast
  redistribute connected
  redistribute ospf
  neighbor {neighborIP} next-hop-self
 exit-address-family
!
"""

OSPF_NW_TEMPLATE = """ network {network} area 0.0.0.0"""

def create_ospf_config(graph: networkx.Graph, name: str) -> str:
    node = graph.nodes[name]
    ip = node.get("ip")
    networks = []
    networks_str = []

    if ip is not None:
        network = ipaddress.IPv6Network((ip.ip, 128))
        networks_str.append(OSPF_NW_TEMPLATE.format(network=format(network)))

        # All links between satellites are in OSPF and are in fb00:1::/64 subnet
        networks_str.append(OSPF_NW_TEMPLATE.format(network=ipaddress.IPv6Network(('fb00:1::', 64))))
        redistribute = ""
        bgp = ""

    if node["bgp_edge"]:
        redistribute = "" #"redistribute bgp" Not needed if setting BGP as default GW

        for neighbor in graph.adj[name]:
            ip_net = graph.edges[name, neighbor]["ip"][name]
            print(f'Chris ip_net = {ip_net}, ip_net in fb:20::/64 = {ip_net in ipaddress.IPv6Network("fb:20::/64")}')
            if ip_net in ipaddress.IPv6Network("fb:20::/64"):
                edge = graph.adj[name][neighbor]
                bgp_ip = edge['ip'][name]
                neighbor_bgp_ip = edge["ip"][neighbor]
                #print(f'Chris ip = {bgp_ip} neighbor_bgp_ip = {neighbor_bgp_ip}')
                break

        if name[1] == "0":
            bgpId = 65001
            remoteId = 65002
        elif name[1] == "1":
            bgpId = 65002
            remoteId = 65001

        bgp = BGP_TEMPLATE.format(
            bgpId=bgpId, 
            routerIP=ip.ip,
            neighborIP=neighbor_bgp_ip.ip,
            remoteId=remoteId
        )
        addDefaultGateway = ""
    else:
        addDefaultGateway = f"ip route 0::/0 {format(node['defaultGateway'])}"
    # Router ID must be a plain IP, no subnet.
    return OSPF_TEMPLATE.format(
        name=name,addDefaultGateway = addDefaultGateway, ip=format(ip.ip), 
        redistribute=redistribute, networks="\n".join(networks_str), bgp=bgp
    )


def create_daemons_config() -> str:
    return """#
ospfd=yes
bgpd=yes
vtysh_enable=yes
zebra_options="  -A 127.0.0.1 -s 90000000"
mgmtd_options="  -A 127.0.0.1"
ospfd_options="  -A 127.0.0.1"
staticd_options="  -A 127.0.0.1"
    """


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



class RouteNode(mininet.node.Node):
    """
    Mininet node with a loopback.
    Supports FrrRouters and ground sations.

    Includes an optional loopback interface with a /31 subnet mask
    """

    def __init__(self, name, **params):
        print("Chris Route node init")
        mininet.node.Node.__init__(self, name, **params)

        # Optional loopback interface
        self.loopIntf = None

    def defaultIntf(self):
        # If we have a loopback, that is the default interface.
        # Otherwise use mininet default behavior.
        if self.loopIntf is not None:
            return self.loopIntf
        return super().defaultIntf()

    def config(self, **params):
        # If we have a default IP and it is not an existing interface, create a
        # loopback.
        if params.get("ip") is not None:
            match_found = False
            ip = format(ipaddress.IPv6Interface(params.get("ip")).ip)
            for intf in self.intfs.values():
                if intf.ip == ip:
                    match_found = True
            if not match_found:
                # Make a default interface
                mininet.util.quietRun("ip link add name loop type dummy")
                self.loopIntf = mininet.link.Intf(name="loop", node=self)

        super().config(**params)

    def setIP(self, ip):
        # What is this for?
        mininet.node.Node.setIP(self, ip)



class MNetNodeWrap:
    """
    """

    def __init__(self, name : str, default_ip: str) -> None:
        self.name : str = name
        self.default_ip : str = default_ip
        self.node : mininet.node.Node = None
 
    def sendCmd(self, command :str):
        if self.node is not None:
            self.node.sendCmd(command)

    def start(self, net: mininet.net.Mininet) -> None:
        """
        Will be called after the mininet node has started
        """
        self.node = net.getNodeByName(self.name)

    def waitOutput(self) -> None:
        if self.node is not None:
            self.node.waitOutput()

    def stop(self) -> None:
        """
        Will be called before the mininet node has stoped
        """
        pass

    def defaultIP(self) -> str:
        """
        Return the default interface
        """
        if self.node is not None and self.node.defaultIntf() is not None:
            return self.node.defaultIntf().ip
        return self.default_ip



class FrrRouter(MNetNodeWrap):
    """
    Support an FRR router under mininet.
    - handles the the FRR config files, starting and stopping FRR.
    Does not cleanup config files.
    """

    CFG_DIR = "/etc/frr/{node}"
    VTY_DIR = "/var/run/frr/{node}/{daemon}.vty"
    LOG_DIR = "/var/log/frr/{node}"

    def __init__(self, name: str, default_ip: str):
        super().__init__(name, default_ip)
        self.no_frr = False
        self.vtysh = None
        self.daemons = None
        self.ospf = None

    def configure(self, vtysh: str, daemons: str, ospf: str) -> None:
        self.vtysh = vtysh
        self.daemons = daemons
        self.ospf = ospf

    def write_configs(self) -> None:
        # Get frr config and save to frr config directory
        cfg_dir = FrrRouter.CFG_DIR.format(node=self.name)
        log_dir = FrrRouter.LOG_DIR.format(node=self.name)

        # Suport this for running without mininet / FRR
        if self.no_frr:
            print("Warning: not running FRR")
            return

        uinfo = pwd.getpwnam("frr")

        if not os.path.exists(cfg_dir):
            # sudo install -m 775 -o frr -g frrvty -d {cfg_dir}
            print(f"create {cfg_dir}")
            os.makedirs(cfg_dir, mode=0o775)
            gid = grp.getgrnam("frrvty").gr_gid
            os.chown(cfg_dir, uinfo.pw_uid, gid)

        # sudo install -m 775 -o frr -g frr -d  {log_dir}
        if not os.path.exists(log_dir):
            print(f"create {log_dir}")
            os.makedirs(log_dir, mode=0o775)
            os.chown(log_dir, uinfo.pw_uid, uinfo.pw_gid)

        self.write_cfg_file(
            f"{cfg_dir}/vtysh.conf", self.vtysh, uinfo.pw_uid, uinfo.pw_gid
        )
        self.write_cfg_file(
            f"{cfg_dir}/daemons", self.daemons, uinfo.pw_uid, uinfo.pw_gid
        )
        self.write_cfg_file(
            f"{cfg_dir}/frr.conf", self.ospf, uinfo.pw_uid, uinfo.pw_gid
        )

    def start(self, net: mininet.net.Mininet) -> None:
        super().start(net)
        self.write_configs()
        # Start frr daemons
        print(f"start router {self.name}")
        self.sendCmd(f"/usr/lib/frr/frrinit.sh start '{self.name}'")

    def stop(self):
        super().stop()
        # Cleanup and stop frr daemons
        print(f"stop router {self.name}")
        self.sendCmd(f"/usr/lib/frr/frrinit.sh stop '{self.name}'")

    def config_frr(self, daemon: str, commands: list[str]) -> bool:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        path = FrrRouter.VTY_DIR.format(node=self.name, daemon=daemon)
        print(f"config_frr Christoffer: path = {path}")
        result = True
        try:
            sock.connect(path)
            msg = b'enable\x00'
            result = result and self._send_frr_cmd(sock, msg)
            msg = b'configure terminal\x00'
            result = result and self._send_frr_cmd(sock, msg)
            for command in commands:
                print(f"sending command {command} to {self.name}")
                msg = (command + '\x00').encode("ascii")
                result = result and self._send_frr_cmd(sock, msg)
            msg = b'end\x00'
            self._send_frr_cmd(sock, msg)
            msg = b'disable\x00'
            self._send_frr_cmd(sock, msg)
        except TimeoutError:
            print("timout connecting to FRR")
            result = False
        sock.close()
        return result

    def _send_frr_cmd(self, sock, msg: bytes) -> bool:
        sock.sendall(msg)
        data = sock.recv(10000)
        #print(f"Christoffer data = {data}")
        size = len(data)
        if size > 0 and data[size-1] == 0:
            return True
        return False

    def write_cfg_file(self, file_path: str, contents: str, uid: int, gid: int) -> None:
        if self.no_frr:
            return

        print(f"write {file_path}")
        with open(file_path, "w") as f:
            f.write(contents)
            f.close()
        os.chmod(file_path, 0o640)
        os.chown(file_path, uid, gid)



class NetxTopo(mininet.topo.Topo):
    """
    Mininet topology object used to build the virtual network.
    """
    def __init__(self, graph: networkx.Graph):
        self.graph = graph
        self.routers: list[FrrRouter] = []
        super().__init__()

    def build(self, *args, **params):
        """
        Build the network according to the information in the networkx.Graph
        """
        # Create routers
        for name in self.graph.nodes:
            node = self.graph.nodes[name]
            ip = node.get("ip")
            ip_intf = None
            ip_addr = None
            if ip is not None:
                ip_intf = format(ip)
                ip_addr = format(ip.ip)
            self.addHost(
                name,
                cls=RouteNode,
                ip=ip_intf)

            frr_router: FrrRouter = FrrRouter(name, ip_addr) 
            self.routers.append(frr_router)
            frr_router.configure(
                ospf=node["ospf"],
                vtysh=node["vtysh"],
                daemons=node["daemons"]
            )

       # Create links between routers
        for name, edge in self.graph.edges.items():
            router1 = name[0]
            router2 = name[1]

            ip1 = edge["ip"][router1]
            intf1 = edge["intf"][router1]

            ip2 = edge["ip"][router2]
            intf2 = edge["intf"][router2]

            print(f"add link between {router1} and {router2} with ips {ip1} and {ip2}")
            self.addLink(
                router1,
                router2,
                intfName1=intf1,
                intfName2=intf2,
                params1={"delay": "1ms"},
                params2={"delay": "1ms"},
                cls=mininet.link.TCLink, 
            )


class FrrSimRuntime:
    """
    Code for the FRR / Mininet / Monitoring functions.
    """
    def __init__(self, topo: NetxTopo, net: mininet.net.Mininet):
        self.graph = topo.graph

        self.routers: dict[str, FrrRouter] = {}

        for router in topo.routers:
            self.routers[router.name] = router
        

        self.net = net

        for name, node in self.graph.nodes.items():
            ip = node.get("ip")
            if ip is not None:
                ip = format(ip)
                self.net.getNodeByName(name).cmd(f"ip addr add {ip} dev loop")

        for name, edge in self.graph.edges.items():
            router1 = name[0]
            router2 = name[1]

            ip1 = edge["ip"][router1]
            intf1 = edge["intf"][router1]

            ip2 = edge["ip"][router2]
            intf2 = edge["intf"][router2]

            self.net.getNodeByName(router1).cmd(f"ip addr add {ip1} dev {intf1}")
            self.net.getNodeByName(router2).cmd(f"ip addr add {ip2} dev {intf2}")

    def start_routers(self) -> None: 
        # Start all nodes
        for router in self.routers.values():
            router.start(self.net)

        # Wait for start to complete.
        for router in self.routers.values():
            router.waitOutput()

    def stop_routers(self):
        for router in self.routers.values():
            router.stop()

        # Wait for commands to complete - important!.
        # Otherwise processes may not shut down.
        for routers in self.routers.values():
            router.waitOutput()