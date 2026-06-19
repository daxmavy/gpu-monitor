"""Known GPU servers offered in the setup wizard. Users pick which they have
access to; the wizard writes a config with ``user@host`` SSH targets."""

# The servers this build targets. id is stable; host is the SSH hostname.
KNOWN_HOSTS = [
    {
        "id": "brains",
        "name": "Brains",
        "host": "brains.oii.ox.ac.uk",
        "gpus": "2× A100 80GB + 2× L40S",
    },
    {
        "id": "virgil",
        "name": "Virgil",
        "host": "virgil.oii.ox.ac.uk",
        "gpus": "4× H100 80GB",
    },
]

# VPN required to reach the servers (Oxford). Written into the saved config.
KNOWN_VPN = {
    "type": "cisco",
    "binary": "/opt/cisco/secureclient/bin/vpn",
    "app": "/Applications/Cisco/Cisco Secure Client.app",
    "network": "163.1",
    "label": "Cisco Secure Client",
    "gateway": "vpn.ox.ac.uk",
}


def host_by_id(host_id: str) -> dict | None:
    return next((h for h in KNOWN_HOSTS if h["id"] == host_id), None)
