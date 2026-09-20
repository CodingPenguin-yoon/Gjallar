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
