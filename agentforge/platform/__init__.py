from agentforge.platform.base import Platform


def get_platform(name: str = "vapi", brief: str | None = None) -> Platform:
    """brief: a collections brief id; the local platform then runs that brief's mock backend in-process.
    Vapi/Freya reach the backend over HTTP instead (collections tools_server)."""
    if name == "vapi":
        from agentforge.platform.vapi import VapiPlatform

        return VapiPlatform()
    if name == "local":
        from agentforge.platform.local import LocalPlatform

        if brief:
            from agentforge.domain.collections import brief_dir, collections_tools, load_policy

            return LocalPlatform(run_tool=collections_tools(brief), canonical=load_policy(brief_dir(brief)).canonical)
        return LocalPlatform()
    if name == "freya":
        from agentforge.platform.freya import FreyaPlatform

        return FreyaPlatform()
    raise ValueError(f"unknown platform: {name}")
