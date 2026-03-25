"""
Generate QR codes for session attendance URLs.
Returns a base64-encoded PNG for embedding directly in HTML.
"""

import io
import base64
import qrcode
from qrcode.image.pure import PyPNGImage


def generate_qr_base64(url):
    """
    Generate a QR code for the given URL.
    Returns a base64-encoded PNG string suitable for use in an <img> src attribute.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    encoded = base64.b64encode(buffer.read()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"
