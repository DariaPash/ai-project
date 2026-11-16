"""Documented bridge capability, not a pretend subprocess SDK."""


def probe(config=None, live=False):
    return {
        "adapter": "host_manual_bridge",
        "python_dispatch": False,
        "automatic_model_switch": False,
        "isolated_context": "requires_actual_host_tool_receipt",
        "usage": "unknown unless exposed",
        "network_call_performed": False,
        "limitations": [
            "Leading host must actually invoke a separate context; a configured profile or instruction alone is not execution"
        ],
    }
