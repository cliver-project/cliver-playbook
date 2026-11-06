"""Provider adapter extension point.

``ProviderAdapter`` implementations registered here are selected by the
``oidc.providers.<key>.adapter`` setting. The built-ins (``wechat``, ``alipay``)
are registered when this package is imported; a composing project may call
``register_adapter`` for its own implementation before the first request.
"""

from cliver_playbook.app.user.auth.adapters.registry import (
    adapter_names,
    get_adapter,
    register_adapter,
)
from cliver_playbook.app.user.auth.provider import (
    Identity,
    ProviderAdapter,
    ProviderAdapterError,
    ProviderConfig,
)

__all__ = [
    "Identity",
    "ProviderAdapter",
    "ProviderAdapterError",
    "ProviderConfig",
    "adapter_names",
    "get_adapter",
    "register_adapter",
]
