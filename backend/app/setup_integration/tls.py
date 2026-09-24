"""Verified TLS with compatibility for explicitly trusted legacy cluster roots."""
import ssl

from cryptography import x509


def _legacy_cluster_root(ca_pem):
    certificates = x509.load_pem_x509_certificates(ca_pem.encode('ascii'))
    if len(certificates) != 1:
        return False
    certificate = certificates[0]
    if certificate.subject != certificate.issuer:
        return False
    try:
        constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints)
    except x509.ExtensionNotFound:
        return False
    if not constraints.critical or not constraints.value.ca:
        return False
    try:
        certificate.extensions.get_extension_for_class(x509.KeyUsage)
    except x509.ExtensionNotFound:
        return True
    return False


def proxmox_tls_context(ca_pem=''):
    context = ssl.create_default_context(cadata=ca_pem or None)
    if ca_pem and _legacy_cluster_root(ca_pem):
        # PVE cluster roots can omit KeyUsage. Python 3.13 made the optional
        # RFC-strict checks default; retain verified TLS for this explicit anchor
        # while accepting that legacy format, without a failed-request fallback.
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def pinned_tls_context():
    """The caller MUST check the explicit leaf pin before sending application data."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def certificate_fingerprint(der):
    from datetime import datetime, timezone
    from cryptography.hazmat.primitives import hashes
    certificate = x509.load_der_x509_certificate(der)
    now = datetime.now(timezone.utc)
    if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
        raise ssl.SSLError('Certificate outside validity period')
    return certificate.fingerprint(hashes.SHA256()).hex()


def verify_certificate_pin(der, expected):
    import hmac
    if not hmac.compare_digest(certificate_fingerprint(der), expected):
        raise ssl.SSLError('Certificate fingerprint mismatch')
