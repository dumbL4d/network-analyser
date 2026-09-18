"""Static Guided Fix playbooks, reproduced from the original Network Analyser
tool's documented Gudied Fix Playbooks table.

Each device type maps to troubleshooting steps for the ``down`` and
``degraded`` states. These are reference data for real warehouse hardware --
they do not depend on live device status or the incident engine, and should
only be edited with domain input from whoever maintains the real hardware
troubleshooting procedures.
"""

PLAYBOOKS: dict[str, dict[str, list[str]]] = {
    "switch": {
        "down": [
            "Check power LED",
            "Check uplink port LED",
            "Reseat fiber/SFP",
            "Swap SFP/patch cable",
        ],
        "degraded": [
            "Check CRC/FCS errors",
            "Verify speed/duplex settings",
            "Inspect cable condition",
        ],
    },
    "server": {
        "down": [
            "Check power/drive LEDs",
            "Verify cable is seated",
            "Check switch port LED",
            "Ping from same subnet",
        ],
        "degraded": [
            "Check NIC negotiation",
            "Monitor CPU/RAM usage",
            "Run packet loss test",
        ],
    },
    "plc": {
        "down": [
            "Locate the panel",
            "Check power",
            "Verify Ethernet connection",
            "Check switch port LED",
            "Power-cycle if safe to do so",
        ],
        "degraded": [
            "Check cable quality",
            "Verify duplex setting",
        ],
    },
    "ap": {
        "down": [
            "Locate access point by aisle",
            "Check PoE power",
            "Reseat cable",
            "Reboot if power is good",
        ],
        "degraded": [
            "Check for RF interference",
            "Verify RSSI/client count",
            "Reduce channel overlap",
        ],
    },
    "firewall": {
        "down": [
            "Check power/link LEDs",
            "Verify ISP connectivity",
            "Check switch-side ports",
        ],
        "degraded": [
            "Review CPU/session count",
            "Check WAN line quality",
        ],
    },
    "hmi": {
        "down": [
            "Check panel power/backlight",
            "Verify Ethernet connection",
            "Check switch port LED",
        ],
        "degraded": [
            "Check cable quality and duplex setting",
        ],
    },
    "scanner": {
        "down": [
            "Check power indicator/laser",
            "Reseat Ethernet cable",
            "Check switch port LED",
        ],
        "degraded": [
            "Clean scanner lens",
            "Check for misalignment",
        ],
    },
}