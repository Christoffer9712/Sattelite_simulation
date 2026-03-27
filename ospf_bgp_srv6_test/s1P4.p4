#include <core.p4>
#include <v1model.p4>

/*************************************************************************
 * CONSTANTS
 *************************************************************************/
const bit<16> ETHERTYPE_IPv6        = 0x86DD;
const bit<16> ETHERTYPE_TIME_SYNC   = 0x8888;

// IPv6 Next Header values
const bit<8> NEXTHDR_ICMPv6   = 58;
const bit<8> NEXTHDR_SRH      = 43;
const bit<8> NEXTHDR_IPv6     = 41;

// ICMPv6 NDP message types
const bit<8> ICMPV6_RS        = 133;   // Router Solicitation
const bit<8> ICMPV6_RA        = 134;   // Router Advertisement
const bit<8> ICMPV6_NS        = 135;   // Neighbour Solicitation
const bit<8> ICMPV6_NA        = 136;   // Neighbour Advertisement

// Time sync message types
const bit<8> MSG_SYNC_REQ     = 0x01;
const bit<8> MSG_SYNC_REPLY   = 0x02;
const bit<8> MSG_SYNC_ACK     = 0x03;

const bit <8> TLV_TYPE_TIMSTAMP = 0xcc; // Random TLV type value

#define MAX_SIDS 4

typedef bit<128> sid_t;

/*************************************************************************
 * HEADERS
 *************************************************************************/
header ethernet_t {
    bit<48> dstAddr;
    bit<48> srcAddr;
    bit<16> etherType;
}

header ipv6_t {
    bit<4>   version;
    bit<8>   trafficClass;
    bit<20>  flowLabel;
    bit<16>  payloadLen;
    bit<8>   nextHdr;
    bit<8>   hopLimit;
    bit<128> srcAddr;
    bit<128> dstAddr;
}

// ICMPv6 header — we only need type/code to identify NDP messages.
// The body (checksum, body) is left in the packet payload unparsed.
header icmpv6_t {
    bit<8>  icmpType;
    bit<8>  code;
    bit<16> checksum;
}

header srv6h_t {
    bit<8>  nextHdr;
    bit<8>  hdrExtLen;
    bit<8>  routingType;
    bit<8>  segLeft;
    bit<8>  lastEntry;
    bit<8>  flags;
    bit<16> tag;
}

header srv6_list_t {
    bit<128> segmentId;
}

// TLV timestamp to be sent after SRv6 header for traffic
header tlv_timestamp_t {
    bit<8> type;
    bit<8> length;
    bit<48> timestamp;
}

// To syncronise internal clock with external clock
header time_sync_t {
    bit<8> sync_type;
    bit<48> switch_ts;
    bit<48> unix_ts;
    bit<16> padding;    
}

struct headers {
    ethernet_t              ethernet;
    ipv6_t                  ipv6_outer;
    icmpv6_t                icmpv6;     // valid only for ICMPv6 packets
    srv6h_t                 srv6h;
    srv6_list_t[MAX_SIDS]   srv6_list;
    ipv6_t                  ipv6_inner; //
    tlv_timestamp_t         timestamp;
    time_sync_t             time_sync;
}

struct metadata { }

/*************************************************************************
 * PARSER
 *************************************************************************/
parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            ETHERTYPE_IPv6      : parse_ipv6;
            ETHERTYPE_TIME_SYNC : parse_time_sync;
            default             : accept;
        }
    }

    state parse_ipv6 {
        packet.extract(hdr.ipv6_inner);
        transition select(hdr.ipv6_inner.nextHdr) {
            NEXTHDR_ICMPv6 : parse_icmpv6;   // branch for NDP detection
            default        : accept;
        }
    }

    state parse_time_sync {
        packet.extract(hdr.time_sync);
        transition accept;
    }

    // Parse just enough of ICMPv6 to read the type field.
    // The rest of the payload remains untouched in the packet buffer.
    state parse_icmpv6 {
        packet.extract(hdr.icmpv6);
        transition accept;
    }
}

/* Register to store the offset */
register<bit<48>>(1) time_offset_reg;

/*************************************************************************
 * INGRESS
 *************************************************************************/
control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    // ------------------------------------------------------------------ //
    // Returns true when the parsed ICMPv6 type is an NDP message.
    // Used as a guard to skip SRH insertion entirely for NDP traffic.
    // ------------------------------------------------------------------ //
    action _nop() { }

    // ------------------------------------------------------------------ //
    // Forward without SRv6 insertion (router → host, or NDP pass-through).
    // ------------------------------------------------------------------ //
    action no_encap(bit<9> out_port) {
        standard_metadata.egress_spec = out_port;
    }

    action mark_to_drop_action(){
        mark_to_drop(standard_metadata);
    }

    // ------------------------------------------------------------------ //
    // NDP forwarding table.
    //
    // Match on icmpv6.icmpType so we can steer each NDP message type to
    // the correct port without touching the packet content at all.
    //
    // Typical two-port deployment (host on port 1, router on port 2):
    //   NS/RS (host→router)  : no_encap(2)
    //   NA/RA (router→host)  : no_encap(1)
    //
    // The control-plane populates this table at start-up.
    // ------------------------------------------------------------------ //
    table ndp_forward {
        key = {
            hdr.icmpv6.icmpType : exact;
            standard_metadata.ingress_port : exact;  // add ingress port as key
        }
        actions = {
            no_encap;
            _nop;
            mark_to_drop_action;
        }
        default_action = mark_to_drop_action();
        const entries = {
            // NS from ue1 (port 1) → forward to router (port 2)
            (ICMPV6_NS, 1) : no_encap(2);
            // NS from router (port 2) → forward to ue1 (port 1)
            (ICMPV6_NS, 2) : no_encap(1);

            // NA from ue1 (port 1) → forward to router (port 2)
            (ICMPV6_NA, 1) : no_encap(2);
            // NA from router (port 2) → forward to ue1 (port 1)
            (ICMPV6_NA, 2) : no_encap(1);

            // RS always goes to router
            (ICMPV6_RS, 1) : no_encap(2);
            // RA always goes to host
            (ICMPV6_RA, 2) : no_encap(1);
        }
    }

    // ------------------------------------------------------------------ //
    // SRv6 insertion actions (host → router direction).
    // ------------------------------------------------------------------ //
    action srv6_encap_1sid(bit<128> s1, bit<9> out_port) {
        hdr.ipv6_outer.setValid();
        hdr.ipv6_outer.version      = 6;
        hdr.ipv6_outer.trafficClass = hdr.ipv6_inner.trafficClass;
        hdr.ipv6_outer.flowLabel    = hdr.ipv6_inner.flowLabel;
        
        hdr.ipv6_outer.payloadLen   = hdr.ipv6_inner.payloadLen + 40 + 24; //ipv6h = 40 bytes, srv6h = 8 + 16*#SIDs
        hdr.ipv6_outer.nextHdr      = NEXTHDR_SRH;
        hdr.ipv6_outer.hopLimit     = 0x40;
        hdr.ipv6_outer.srcAddr      = hdr.ipv6_inner.srcAddr;
        hdr.ipv6_outer.dstAddr      = s1;


        hdr.srv6h.setValid();
        hdr.srv6h.nextHdr     = NEXTHDR_IPv6;
        hdr.srv6h.routingType = 4;
        hdr.srv6h.segLeft     = 0;
        hdr.srv6h.lastEntry   = 0;
        hdr.srv6h.flags       = 0;
        hdr.srv6h.tag         = 0;
        hdr.srv6h.hdrExtLen   = 2;

        hdr.srv6_list[0].setValid();
        hdr.srv6_list[0].segmentId = s1;

        standard_metadata.egress_spec = out_port;
    }

    action srv6_encap_2sid(bit<128> s1, bit<128> s2, bit<9> out_port) {
        hdr.ipv6_outer.setValid();
        hdr.ipv6_outer.version      = 6;
        hdr.ipv6_outer.trafficClass = hdr.ipv6_inner.trafficClass;
        hdr.ipv6_outer.flowLabel    = hdr.ipv6_inner.flowLabel;
        
        hdr.ipv6_outer.payloadLen   = hdr.ipv6_inner.payloadLen + 40 + 8 + 2*16; //ipv6h = 40 bytes, srv6h = 8 + 16*#SIDs
        hdr.ipv6_outer.nextHdr      = NEXTHDR_SRH;
        hdr.ipv6_outer.hopLimit     = 0x40;
        hdr.ipv6_outer.srcAddr      = hdr.ipv6_inner.srcAddr;
        hdr.ipv6_outer.dstAddr      = s2;


        hdr.srv6h.setValid();
        hdr.srv6h.routingType = 4;
        hdr.srv6h.segLeft     = 1;
        hdr.srv6h.lastEntry   = 1;
        hdr.srv6h.flags       = 0;
        hdr.srv6h.tag         = 0;
        hdr.srv6h.hdrExtLen   = 4;
        hdr.srv6h.nextHdr = NEXTHDR_IPv6;

        hdr.srv6_list[0].setValid();
        hdr.srv6_list[0].segmentId = s2;
        hdr.srv6_list[1].setValid();
        hdr.srv6_list[1].segmentId = s1;

        standard_metadata.egress_spec = out_port;
    }

    action srv6_encap_3sid(bit<128> s1, bit<128> s2, bit<128> s3, bit<9> out_port) {
        hdr.ipv6_outer.setValid();
        hdr.ipv6_outer.version      = 6;
        hdr.ipv6_outer.trafficClass = hdr.ipv6_inner.trafficClass;
        hdr.ipv6_outer.flowLabel    = hdr.ipv6_inner.flowLabel;
        
        hdr.ipv6_outer.payloadLen   = hdr.ipv6_inner.payloadLen + 40 + 8 + 3*16; //ipv6h = 40 bytes, srv6h = 8 + 16*#SIDs
        hdr.ipv6_outer.nextHdr      = NEXTHDR_SRH;
        hdr.ipv6_outer.hopLimit     = 0x40;
        hdr.ipv6_outer.srcAddr      = hdr.ipv6_inner.srcAddr;
        hdr.ipv6_outer.dstAddr      = s3;
        
        
        hdr.srv6h.setValid();
        hdr.srv6h.routingType = 4;
        hdr.srv6h.segLeft     = 2;
        hdr.srv6h.lastEntry   = 2;
        hdr.srv6h.flags       = 0;
        hdr.srv6h.tag         = 0;
        hdr.srv6h.hdrExtLen   = 6;
        hdr.srv6h.nextHdr = NEXTHDR_IPv6;

        hdr.srv6_list[0].setValid();
        hdr.srv6_list[0].segmentId = s3;
        hdr.srv6_list[1].setValid();
        hdr.srv6_list[1].segmentId = s2;
        hdr.srv6_list[2].setValid();
        hdr.srv6_list[2].segmentId = s1;

        standard_metadata.egress_spec = out_port;
    }

    // ------------------------------------------------------------------ //
    // srv6_sid_table
    // ------------------------------------------------------------------ //
    table srv6_sid_table {
        key = { hdr.ipv6_inner.dstAddr: lpm; }
        actions = {
            srv6_encap_1sid;
            srv6_encap_2sid;
            srv6_encap_3sid;
            no_encap;
            mark_to_drop_action;
        }
        default_action = mark_to_drop_action();
    }

    // ------------------------------------------------------------------ //
    // action 
    // ------------------------------------------------------------------ //
    action add_timestamp (){
        hdr.timestamp.setValid();
        hdr.timestamp.type = TLV_TYPE_TIMSTAMP;
        hdr.timestamp.length = 6; //timestamp is 6*8 bits (6 bytes)
        bit<64> time_ms = (((bit<64>) standard_metadata.ingress_global_timestamp)*0x418937) >> 32; // Equivalent to divide by 1000
        bit<48> offset;
        time_offset_reg.read(offset, 0);
        hdr.timestamp.timestamp = offset + (bit<48>)time_ms;

        hdr.srv6h.hdrExtLen   = hdr.srv6h.hdrExtLen + 1;  // +8 bytes (1 unit = 8 bytes)
        hdr.ipv6_outer.payloadLen = hdr.ipv6_outer.payloadLen + 8;
    }

    // ------------------------------------------------------------------ //
    // action 
    // ------------------------------------------------------------------ //
    action time_sync_req (){
        hdr.time_sync.sync_type = MSG_SYNC_REPLY;
        hdr.time_sync.switch_ts = standard_metadata.ingress_global_timestamp;
        standard_metadata.egress_spec = standard_metadata.ingress_port;
    }
    
    // Set registry
    action time_sync_ack (){
        bit<48> offset = hdr.time_sync.unix_ts - hdr.time_sync.switch_ts;
        time_offset_reg.write(0, offset);
        standard_metadata.egress_spec = standard_metadata.ingress_port;
    }

    // ------------------------------------------------------------------ //
    // Apply block
    // ------------------------------------------------------------------ //
    apply {
        if (hdr.time_sync.isValid()) {
            if (hdr.time_sync.sync_type == MSG_SYNC_REQ) {
                time_sync_req();
            } else if (hdr.time_sync.sync_type == MSG_SYNC_ACK) {
                time_sync_ack();
            }
        }
        else {
            if (!hdr.ipv6_inner.isValid()) {
                mark_to_drop(standard_metadata);
                return;
            }

            // NDP traffic must be passed through as-is — never push an SRH
            // onto a Neighbour Solicitation/Advertisement or RS/RA, as that
            // would break link-local address resolution on the shared prefix.
            if (hdr.icmpv6.isValid()) {
                if (hdr.icmpv6.icmpType == ICMPV6_NS ||
                    hdr.icmpv6.icmpType == ICMPV6_NA ||
                    hdr.icmpv6.icmpType == ICMPV6_RS ||
                    hdr.icmpv6.icmpType == ICMPV6_RA) {
                    ndp_forward.apply();
                    return;   // done — skip SRH insertion entirely
                }
            }

            // Normal unicast IPv6: apply SRv6 policy.
            srv6_sid_table.apply();
            if(hdr.srv6h.isValid()){
                add_timestamp();
            }
        }
    }
}

/*************************************************************************
 * EGRESS  (minimal)
 *************************************************************************/
control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply { }
}

/*************************************************************************
 * CHECKSUMS
 *************************************************************************/
control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

control MyComputeChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

/*************************************************************************
 * DEPARSER
 *************************************************************************/
control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.time_sync);
        packet.emit(hdr.ipv6_outer);
        // Emit icmpv6 only when it was parsed (i.e. NDP path).
        // For SRH packets icmpv6 is invalid so emit() is a no-op.
        packet.emit(hdr.srv6h);
        packet.emit(hdr.srv6_list[0]);
        packet.emit(hdr.srv6_list[1]);
        packet.emit(hdr.srv6_list[2]);
        packet.emit(hdr.srv6_list[3]);   // needed for 3-SID case
        packet.emit(hdr.timestamp);
        packet.emit(hdr.ipv6_inner);
        packet.emit(hdr.icmpv6);
    }
}

/*************************************************************************
 * SWITCH INSTANTIATION
 *************************************************************************/
V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;