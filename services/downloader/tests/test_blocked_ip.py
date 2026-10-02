"""is_blocked_ip: every address that leads to a private place is refused, public ones are not."""
import ipaddress

import pytest

from app.urlcheck import is_blocked_ip


@pytest.mark.parametrize(
    "address",
    [
        # plain private and special ranges
        "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1",
        "0.0.0.0", "224.0.0.1", "198.18.0.1", "192.0.0.1", "255.255.255.255",
        "::1", "::", "fe80::1", "fc00::1", "ff02::1", "2002::1",
        # IPv6 forms that carry a private IPv4 address (found by the security review)
        "::ffff:127.0.0.1", "::127.0.0.1", "::7f00:1", "::ffff:0:127.0.0.1",
        "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "64:ff9b::a00:1",
        # ranges is_global reports as public
        "fec0::1", "192.88.99.1", "5f00::1",
    ],
)
def test_private_and_embedded_addresses_are_blocked(address):
    assert is_blocked_ip(ipaddress.ip_address(address)), address


@pytest.mark.parametrize(
    "address",
    ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111", "2a00:1450:4001:81b::200e",
     "::ffff:8.8.8.8", "64:ff9b::808:808", "::808:808"],
)
def test_public_addresses_are_allowed(address):
    assert not is_blocked_ip(ipaddress.ip_address(address)), address
