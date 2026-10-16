"""TLS verification remains enabled; optional certifi augments system roots."""
import ssl
from urllib.request import urlopen


def secure_open(request,timeout=20):
    context=ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(certifi.where())
    except ImportError:
        pass
    return urlopen(request,timeout=timeout,context=context)
