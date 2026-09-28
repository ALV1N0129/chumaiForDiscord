"""A server that omits its intermediate certificate, like chunithm-net-eng.com."""

import asyncio
import datetime as dt
import ssl

import aiohttp
import pytest
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

from chumai import tls


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject, key, issuer, issuer_key, *, ca, extra=()):
    now = dt.datetime.now(dt.timezone.utc)
    b = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if ca:
        b = b.add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True
        )
    for ext in extra:
        b = b.add_extension(ext, critical=False)
    return b.sign(issuer_key, hashes.SHA256())


def _pki(tmp_path, aia_url, *, intermediate_root_trusted=True):
    k = lambda: ec.generate_private_key(ec.SECP256R1())  # noqa: E731
    root_key, int_key, leaf_key, evil_key = k(), k(), k(), k()
    root = _cert("Test Root", root_key, "Test Root", root_key, ca=True)
    if intermediate_root_trusted:
        inter = _cert("Test Intermediate", int_key, "Test Root", root_key, ca=True)
    else:  # same name, but signed by a root the client does not trust
        inter = _cert("Test Intermediate", int_key, "Evil Root", evil_key, ca=True)
    leaf = _cert(
        "localhost", leaf_key, "Test Intermediate", int_key, ca=False,
        extra=[
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            x509.AuthorityInformationAccess(
                [x509.AccessDescription(AuthorityInformationAccessOID.CA_ISSUERS,
                                        x509.UniformResourceIdentifier(aia_url))]
            ),
        ],
    )
    (tmp_path / "leaf.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "leaf.key").write_bytes(
        leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption())
    )
    return root, inter


async def _run(tmp_path, *, trusted):
    # Plain-HTTP server for the AIA download, on a fixed free port.
    aia_app = web.Application()
    state = {}

    async def aia(request):
        return web.Response(body=state["inter_der"])

    async def index(request):
        return web.Response(text="ok")

    aia_app.router.add_get("/int.der", aia)
    aia_runner = web.AppRunner(aia_app)
    await aia_runner.setup()
    aia_site = web.TCPSite(aia_runner, "127.0.0.1", 0)
    await aia_site.start()
    aia_port = aia_site._server.sockets[0].getsockname()[1]

    root, inter = _pki(tmp_path, f"http://127.0.0.1:{aia_port}/int.der", intermediate_root_trusted=trusted)
    state["inter_der"] = inter.public_bytes(serialization.Encoding.DER)

    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_ctx.load_cert_chain(tmp_path / "leaf.pem", tmp_path / "leaf.key")  # leaf only!
    app = web.Application()
    app.router.add_get("/", index)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 0, ssl_context=server_ctx)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    client_ctx = ssl.create_default_context(cadata=root.public_bytes(serialization.Encoding.PEM).decode())
    client_ctx.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN

    async def fetch():
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=client_ctx)) as s:
            async with s.get(f"https://localhost:{port}/") as r:
                return await r.text()

    try:
        with pytest.raises(aiohttp.ClientConnectorCertificateError):
            await fetch()
        added = await tls.add_missing_intermediate("localhost", port, context=client_ctx)
        try:
            return added, await fetch()
        except aiohttp.ClientConnectorCertificateError:
            return added, None
    finally:
        await runner.cleanup()
        await aia_runner.cleanup()


def test_missing_intermediate_is_fetched(tmp_path):
    added, body = asyncio.run(_run(tmp_path, trusted=True))
    assert added and body == "ok"


def test_forged_intermediate_is_still_rejected(tmp_path):
    added, body = asyncio.run(_run(tmp_path, trusted=False))
    assert added and body is None
