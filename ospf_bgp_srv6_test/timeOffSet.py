import time
import struct
from scapy.all import (
    Ether, Packet, BitField, XByteField, srp1, sendp, bind_layers, AsyncSniffer, conf
)

IFACE          = "s1-ethUe1"
SYNC_ETYPE     = 0x8888
MSG_SYNC_REQ   = 0x01
MSG_SYNC_REPLY = 0x02
MSG_SYNC_ACK   = 0x03


class SyncHeader(Packet):
    name = "SyncHeader"
    fields_desc = [
        XByteField("msg_type",  0),
        BitField("switch_ts",   0, 48),
        BitField("unix_ts",     0, 48),
        BitField("padding",     0, 16),
    ]

bind_layers(Ether, SyncHeader, type=SYNC_ETYPE)


def unix_ts_ms() -> int:
    """Current unix timestamp in milliseconds — same unit as ingress_global_timestamp"""
    return int(time.time() * 1_000)


def sync_switch(iface: str, retries: int = 3) -> int | None:
    """
    Perform time sync handshake with P4 switch.
    Returns the computed offset (unix_us - switch_us), or None on failure.
    """
    for attempt in range(retries):
        # Step 1: Send sync request
        req = (
            Ether(dst="ff:ff:ff:ff:ff:ff", type=SYNC_ETYPE)
            / SyncHeader(msg_type=MSG_SYNC_REQ, switch_ts=0, unix_ts=0)
        )


        # Start sniffer first
        sniffer = AsyncSniffer(
            iface=iface,
            filter="ether proto 0x8888",
            count=5,
            timeout=5
        )

        conf.use_pcap = True  # Force use of pcap for accurate timestamps, even on Linux
        filter_str = "ether proto 0x8888 and ether[14] == 0x02"
        t_send = unix_ts_ms()

        reply = srp1(
            req,
            iface=iface,
            timeout=2,
            verbose=False,
            filter=filter_str
        )

        t_recv = unix_ts_ms()

        if reply is None or SyncHeader not in reply:
            print(f"Attempt {attempt+1}: no reply")
            continue

        sync = reply[SyncHeader]

        if sync.msg_type != MSG_SYNC_REPLY:
            print(f"Unexpected msg_type: {sync.msg_type:#x}")
            continue
        
        # Estimate unix time at the moment the switch stamped the packet.
        # Use midpoint of send/recv to approximate one-way latency.
        rtt        = t_recv - t_send
        t_at_stamp = t_send + rtt // 2

        switch_ts  = sync.switch_ts // 1_000  # Convert from microseconds to milliseconds
        offset     = t_at_stamp - switch_ts

        print(f"switch_ts : {switch_ts} ms")
        print(f"unix_ts   : {t_at_stamp} ms")
        print(f"offset    : {offset} ms  (rtt={rtt} ms)")

        # Step 3: Send ack with the computed unix timestamp back to the switch
        ack = (
            Ether(dst="ff:ff:ff:ff:ff:ff", type=SYNC_ETYPE)
            / SyncHeader(
                msg_type  = MSG_SYNC_ACK,
                switch_ts = switch_ts,
                unix_ts   = t_at_stamp,
            )
        )

        reply = srp1(
            ack,
            iface=iface,
            timeout=2,
            verbose=False,
            filter="ether proto 0x8888"
        )
        if reply is None:
            print("No ACK reply received")
        else:
            sync = reply[SyncHeader]
            print(f"Received ACK reply: msg_type={sync.msg_type:#x}, switch_ts={sync.switch_ts}, unix_ts={sync.unix_ts}")

        return offset

    print("Sync failed after all retries")
    return None


if __name__ == "__main__":
    offset = sync_switch(IFACE)
    if offset is not None:
        print(f"\nSync complete. Offset stored in switch register.")
        print(f"To convert a switch timestamp: unix_ts = switch_ts + {offset}")


## Flow Summary
#```
#Python                          P4 Switch
#  |                                 |
#  |-- Ether/SyncHeader(type=01) --->|  switch stamps ingress_global_timestamp
#  |<-- SyncHeader(type=02, ts=X) ---|
#  |                                 |
#  | compute offset = unix_mid - X   |
#  |                                 |
#  |-- SyncHeader(type=03, unix=Y) ->|  stores (Y - X) in register
#  |                                 |
#  |  later normal packets           |
#  |<-- INT TLV: offset + switch_ts -|  = corrected unix timestamp