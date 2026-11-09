"""Single-platform ecommerce identity checks; no account or browser access."""
import re
from urllib.parse import urlsplit

ECOMMERCE_PLATFORMS = frozenset({"taobao", "jd"})


def validate_product_url(value, platform):
    """Optional observed canonical product link; never keep tracking/account queries."""
    if value is None:
        return
    if platform != 'jd' or not isinstance(value, str):
        raise ValueError('product_url is only supported for a verified JD product link')
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == 'https' and parts.hostname in {'item.jd.com', 'item.jd.hk'}
                 and parts.port in (None, 443) and not parts.username and not parts.password
                 and re.fullmatch(r'/[0-9]{6,30}\.html', parts.path)
                 and not parts.query and not parts.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('product_url must be a canonical HTTPS JD item URL without query or fragment')


def ecommerce_platform(value):
    if not isinstance(value, str) or value not in ECOMMERCE_PLATFORMS:
        raise ValueError("unsupported ecommerce platform; use taobao or jd")
    return value


def validate_order_platforms(orders, platform):
    """Validate before any write or privacy projection. Missing tags are legacy Taobao only."""
    ecommerce_platform(platform)
    if not isinstance(orders, list):
        raise ValueError("orders must be an array")
    for row in orders:
        if not isinstance(row, dict):
            raise ValueError("each order must be an object")
        # A JD row must be explicit; an untagged historical row cannot be
        # silently reassigned to JD just because the project metadata changed.
        row_platform = row.get("platform", "taobao")
        if not isinstance(row_platform, str) or row_platform not in ECOMMERCE_PLATFORMS or row_platform != platform:
            raise ValueError("order platform differs from this single-platform project; keep the old project and use a new directory")
    return platform
