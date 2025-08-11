import os
import sys
import importlib

# This provides a server and locations where to load extended mcp server capabilities
class MCPServer:
    def __init__(self, config: dict):
        self.config = config
        # _mcp_server_instance has been initialized
        from mcp_x.mcp_server_instance import mcp
        self.mcp = mcp

    def get_mcp(self):
        return self.mcp

    def get_config(self):
        return self.config

    def loads_mcp_capabilities(self):
        if self.get_mcp() is None:
            raise Exception("No mcp loaded")
        # loads dir from config
        for pkg_name, cap_dir in self._mcp_capabilities_dir():
            for filename in os.listdir(cap_dir):
                if filename.endswith('.py'):
                    module_name = filename[:-3]
                    if pkg_name is not None and pkg_name != "":
                        module_name = f"{pkg_name}.{module_name}"
                    module = importlib.import_module(module_name)
                    # set config if module has one
                    if hasattr(module, 'config'):
                        setattr(module, 'config', self.get_config())


    def _mcp_capabilities_dir(self) -> list[tuple[str, str]]:
        dirs: list[tuple[str, str]] = []
        cap_module = sys.modules[self.__module__]
        module_file = cap_module.__file__
        module_dir = os.path.dirname(os.path.abspath(module_file))
        # builtin simple directory
        dirs.append(("mcp_x.simple", f"{module_dir}/simple"))
        # external directories specified by the config
        # mcp_server.config
        external_dirs = self.get_config().get('external_dirs', [])
        for ed in external_dirs:
            if os.path.exists(ed):
                dirs.append(("", str(ed)))
        return dirs
