import p4runtime_sh.shell as sh

# Connect to the switch (gRPC port 9559, device_id=0)
sh.setup(
    device_id=0,
    grpc_addr='127.0.0.1:9559',
    election_id=(0, 1),                        # (high, low) — must be non-zero
    config=sh.FwdPipeConfig(
        'build/myP4info.txt',
        'build/myP4.json'
    )
)

# Add a table entry equivalent
#        const entries = {
#            128w0x00fc0020000000000000000000000002 &&& 128w0xffffffffffffffffffffffffffffffff : srv6_encap_3sid(128w0x00220010000000010000000000000000, 128w0x00220020000000010000000000000000, 128w0x00220030000000010000000000000000, 2);
#            128w0x00fc0020000000000000000000000001 &&& 128w0xffffffffffffffffffffffffffffffff : srv6_encap_2sid(128w0x00220010000000020000000000000000, 128w0x00220030000000010000000000000000, 2);
#            128w0x00fa0000000000000000000000000001 &&& 128w0xffffffffffffffffffffffffffffffff : no_encap(1);
#        }

print("Before inserting table entries...")
for entry in sh.TableEntry('MyIngress.srv6_sid_table').read():
    print(entry)
    print("---")

if True:
    print("Inserting table entries...")
    # Entry 1: fc20::2/128 -> srv6_encap_3sid
    te1 = sh.TableEntry('MyIngress.srv6_sid_table')(action='srv6_encap_3sid')
    te1.match['hdr.ipv6_inner.dstAddr'] = 'fc:20::2/128'   # /128 = exact match via LPM
    te1.action['s1'] = '22:10:0:1::'
    te1.action['s2'] = '22:20:0:1::'
    te1.action['s3'] = '22:30:0:1::'
    te1.action['out_port'] = '2'
    te1.insert()

    te2 = sh.TableEntry('MyIngress.srv6_sid_table')(action='no_encap')
    te2.match['hdr.ipv6_inner.dstAddr'] = 'fa:00::1/128'   # /128 = exact match via LPM
    te2.action['out_port'] = '1'
    te2.insert()


print("After inserting table entries...")
for entry in sh.TableEntry('MyIngress.srv6_sid_table').read():
    print(entry)
    print("---")


# Read all entries in a table
#for entry in sh.TableEntry('srv6_sid_table').read():
#    print(entry)

sh.teardown()