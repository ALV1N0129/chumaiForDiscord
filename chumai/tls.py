"""TLS setup for talking to SEGA's sites.

chunithm-net-eng.com has been seen serving its certificate without the
intermediate CA. Browsers quietly download the missing intermediate (via the
certificate's "CA Issuers" / AIA URL); Python does not, so verification fails
with "unable to get local issuer certificate".

`add_missing_intermediate` does that AIA fetch ourselves, asynchronously.
(Letting the OS do it, e.g. via `truststore` on Windows, blocks the whole event
loop during the handshake, so the bot stops answering Discord.) The fetched
certificate is only used to build the chain; it must still chain up to a
trusted root, so a forged one is rejected.

Roots come from the system store plus certifi's bundle, since Windows only
installs some roots on demand and Python can't trigger that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncio
import logging
import ssl

import aiohttp
import certifi

if TYPE_CHECKING:
    from cryptography import x509

log = logging.getLogger(__name__)


def _make_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(certifi.where())
    # A fetched intermediate must never act as a trust anchor on its own.
    ctx.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


SSL_CONTEXT = _make_context()
_fixed_hosts: set[tuple[str, int]] = set()


async def _peer_certificate(host: str, port: int) -> x509.Certificate:
    from cryptography import x509  # imported only when needed: ~6MB of memory

    insecure = ssl.create_default_context()
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port, ssl=insecure, server_hostname=host), timeout=20
    )
    try:
        der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    finally:
        writer.close()
    return x509.load_der_x509_certificate(der)


def _load_cert(data: bytes) -> x509.Certificate:
    from cryptography import x509

    if data.lstrip().startswith(b"-----BEGIN"):
        return x509.load_pem_x509_certificate(data)
    return x509.load_der_x509_certificate(data)


async def add_missing_intermediate(host: str, port: int = 443, context: ssl.SSLContext | None = None) -> bool:
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

    """Fetch the issuer of `host`'s certificate via AIA and add it to the context.

    Returns True if a certificate was added (the caller should retry once).
    """
    context = context or SSL_CONTEXT
    if (host, port) in _fixed_hosts:
        return False
    _fixed_hosts.add((host, port))
    try:
        leaf = await _peer_certificate(host, port)
        aia = leaf.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
        urls = [
            d.access_location.value
            for d in aia
            if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS
        ]
        if not urls:
            return False
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(urls[0]) as resp:
                resp.raise_for_status()
                issuer = _load_cert(await resp.read())
        context.load_verify_locations(cadata=issuer.public_bytes(Encoding.PEM).decode())
        log.info("added missing intermediate certificate for %s: %s", host, issuer.subject.rfc4514_string())
        return True
    except Exception:
        log.exception("could not fetch the missing intermediate certificate for %s", host)
        return False
