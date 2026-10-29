from functools import lru_cache
from ipaddress import ip_address, ip_network

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@lru_cache(maxsize=16)
def trusted_networks(cidrs):
    try:
        return tuple(ip_network(cidr.strip()) for cidr in cidrs if cidr.strip())
    except ValueError as exc:
        raise ImproperlyConfigured('TRUSTED_PROXY_CIDRS must contain valid IP networks.') from exc


def client_ip(meta):
    """Trust one overwritten IP header only from explicitly configured peers.

    Forwarded chains and empty Unix-socket peers are deliberately not trusted.
    Bind Gunicorn to a private TCP listener for the documented Nginx setup.
    """
    peer_text = meta.get('REMOTE_ADDR') or 'unknown'
    try:
        peer = ip_address(peer_text)
    except ValueError:
        return peer_text
    networks = trusted_networks(tuple(settings.TRUSTED_PROXY_CIDRS))
    if any(peer in network for network in networks):
        try:
            return str(ip_address(meta.get('HTTP_X_REAL_IP', '')))
        except ValueError:
            pass
    return str(peer)
