from agentforge.platform.base import Platform


def get_platform(name: str = "vapi") -> Platform:
    if name == "vapi":
        from agentforge.platform.vapi import VapiPlatform

        return VapiPlatform()
    if name == "local":
        from agentforge.platform.local import LocalPlatform

        return LocalPlatform()
    if name == "freya":
        from agentforge.platform.freya import FreyaPlatform

        return FreyaPlatform()
    raise ValueError(f"unknown platform: {name}")
