"""Real OpenSSL handshakes for explicit private-CA compatibility and rejection."""
from datetime import datetime, timedelta, timezone
import socket
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.setup_integration.transport import ProxmoxSetupTransport


def root(*, legacy=True, expired=False, is_ca=True):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic cluster CA')])
    now = datetime.now(timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
               .public_key(key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(now - timedelta(days=10))
               .not_valid_after(now + timedelta(days=-1 if expired else 10))
               .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False))
    if not legacy:
        builder = builder.add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
    return key, builder.sign(key, hashes.SHA256())


def pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode('ascii')


def leaf(ca, *, timing='valid', purpose=ExtendedKeyUsageOID.SERVER_AUTH):
    ca_key, ca_cert = ca
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    before, after = {'valid': (-1, 1), 'expired': (-10, -1), 'future': (1, 2)}[timing]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'pve.example.test')]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now + timedelta(days=before)).not_valid_after(now + timedelta(days=after))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('pve.example.test')]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([purpose]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return key, cert


def transport(ca_pem):
    return ProxmoxSetupTransport('https://pve.example.test:8006/api2/json', ca_pem,
        resolver=lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.100.5', 8006))])


def handshake(tmp_path, context, server, hostname='pve.example.test'):
    key, cert = server
    cert_file, key_file = tmp_path/'server.pem', tmp_path/'server.key'
    cert_file.write_text(pem(cert))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_file.chmod(0o600)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_file, key_file)
    cin, cout, sin, sout = (ssl.MemoryBIO() for _ in range(4))
    client = context.wrap_bio(cin, cout, server_hostname=hostname)
    peer = server_context.wrap_bio(sin, sout, server_side=True)
    done = [False, False]
    for _ in range(20):
        for index, endpoint in enumerate((client, peer)):
            if not done[index]:
                try:
                    endpoint.do_handshake()
                    done[index] = True
                except ssl.SSLWantReadError:
                    pass
        sin.write(cout.read())
        cin.write(sout.read())
        if all(done):
            return
    pytest.fail('TLS handshake did not complete')


@pytest.mark.parametrize('legacy', [True, False])
def test_explicit_cluster_ca_completes_verified_handshake(tmp_path, legacy):
    ca = root(legacy=legacy)
    context = transport(pem(ca[1])).context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    handshake(tmp_path, context, leaf(ca))


@pytest.mark.parametrize('failure', ['wrong_ca', 'hostname', 'expired', 'future', 'expired_root', 'client_only'])
def test_legacy_ca_never_bypasses_identity_chain_expiry_or_purpose(tmp_path, failure):
    ca = root(expired=failure == 'expired_root')
    trusted = root() if failure == 'wrong_ca' else ca
    context = transport(pem(trusted[1])).context
    server = leaf(ca, timing=failure if failure in ('expired', 'future') else 'valid',
                  purpose=ExtendedKeyUsageOID.CLIENT_AUTH if failure == 'client_only' else ExtendedKeyUsageOID.SERVER_AUTH)
    with pytest.raises(ssl.SSLCertVerificationError) as error:
        handshake(tmp_path, context, server, 'other.example.test' if failure == 'hostname' else 'pve.example.test')
    assert error.value.verify_code in {
        'wrong_ca': {7, 20, 21}, 'hostname': {62}, 'expired': {10},
        'future': {9}, 'expired_root': {10}, 'client_only': {26},
    }[failure]


def test_other_trust_profiles_keep_default_strict_verification():
    strict = ssl.create_default_context().verify_flags & ssl.VERIFY_X509_STRICT
    assert strict, 'Supported Python runtime must exercise strict verification'
    legacy, modern, not_ca = root(), root(legacy=False), root(is_ca=False)
    for certificates in ('', pem(modern[1]), pem(not_ca[1]), pem(legacy[1]) + pem(modern[1])):
        assert transport(certificates).context.verify_flags & ssl.VERIFY_X509_STRICT
