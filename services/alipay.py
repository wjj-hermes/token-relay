import os
import logging
from alipay import AliPay

logger = logging.getLogger("alipay")

ALIPAY_APP_ID = os.getenv("ALIPAY_APP_ID", "") or "2021006156623714"
ALIPAY_PUBLIC_KEY = os.getenv("ALIPAY_PUBLIC_KEY", "") or "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0CaIaEIJ/dg8CjjUfWWJwqV7QFLLn3rJDlvIcIs9Xst5aVcM7GZ4D6RhLvKZb1l5Q5oFB6gJRi9AcBVSpcl9hvi+EOyD1+cYwzVR8qKA205a4poK5RBqZ1vzlFflD6KmEK4w5NiZqRq62kF2RA+WVr/+1rOJ0kcA9vtco5ptS55rYwlT+7bvpwQPkH+H5GsPNcPTRJt8O7I6gkKTQSVQp+g74GW7zm+ko0/TIAS/Nl60MZl40dhEHRd8VE/b5HXbVQpkKQ5KwQNb5puD6ZMZHGgYs8LOIpfbGnfa2O5/gQqlmWo0B6gh2mfqY5Uysj+ehwtgvvHcm1PLo2YjgzAsbwIDAQAB"
ALIPAY_NOTIFY_URL = os.getenv("ALIPAY_NOTIFY_URL", "") or "https://token-relay-production-2904.up.railway.app/pay/notify"
IS_SANDBOX = os.getenv("ALIPAY_SANDBOX", "false").lower() == "true"

# Load private key: env var -> file
ALIPAY_PRIVATE_KEY = os.getenv("ALIPAY_PRIVATE_KEY", "")
_priv_key_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "keys", "alipay_private_key.pem")
if len(ALIPAY_PRIVATE_KEY) < 1000 and os.path.exists(_priv_key_file):
    with open(_priv_key_file, "r") as f:
        ALIPAY_PRIVATE_KEY = f.read().strip()
    logger.info("Loaded Alipay private key from file")


def _format_key(key: str, key_type: str = "PRIVATE") -> str:
    """Format a key string into proper PEM format.

    Handles keys that may come as:
    - Raw base64 without headers
    - PEM with correct headers
    - PEM with wrong headers (e.g. PKCS#8 PRIVATE KEY instead of RSA PRIVATE KEY)
    - Keys with literal \\n in env vars
    """
    key = key.strip().replace("\r", "")
    # Handle literal \n from environment variables
    key = key.replace("\\n", "\n")

    if "BEGIN" in key and "END" in key:
        return key

    # Raw base64 - add PEM headers with line breaks every 64 chars
    lines = [key[i:i+64] for i in range(0, len(key), 64)]
    body = "\n".join(lines)
    if key_type == "PUBLIC":
        return f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----"
    return f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----"


def _get_client() -> AliPay:
    priv_key = _format_key(ALIPAY_PRIVATE_KEY, "PRIVATE")
    pub_key = _format_key(ALIPAY_PUBLIC_KEY, "PUBLIC")

    logger.info(f"Alipay APPID: {ALIPAY_APP_ID}")
    logger.info(f"Private key first 60 chars: {priv_key[:60]}")
    logger.info(f"Public key first 60 chars: {pub_key[:60]}")

    # Try loading with the SDK directly first
    try:
        return AliPay(
            appid=ALIPAY_APP_ID,
            app_notify_url=ALIPAY_NOTIFY_URL,
            app_private_key_string=priv_key,
            alipay_public_key_string=pub_key,
            sign_type="RSA2",
            debug=IS_SANDBOX,
        )
    except Exception as e1:
        logger.warning(f"First attempt failed ({type(e1).__name__}: {e1}), trying key conversion...")

    # Try converting PKCS#8 to PKCS#1 format using cryptography library
    try:
        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key, Encoding, PrivateFormat, NoEncryption
        )
        from cryptography.hazmat.primitives.asymmetric import rsa

        # Load the private key (handles both PKCS#1 and PKCS#8)
        key_bytes = priv_key.encode()
        private_key = load_pem_private_key(key_bytes, password=None)

        if isinstance(private_key, rsa.RSAPrivateKey):
            # Convert to PKCS#1 PEM format
            pkcs1_pem = private_key.private_bytes(
                encoding=Encoding.PEM,
                format=PrivateFormat.TraditionalOpenSSL,  # PKCS#1
                encryption_algorithm=NoEncryption()
            ).decode()
            logger.info("Successfully converted key to PKCS#1 format")

            return AliPay(
                appid=ALIPAY_APP_ID,
                app_notify_url=ALIPAY_NOTIFY_URL,
                app_private_key_string=pkcs1_pem,
                alipay_public_key_string=pub_key,
                sign_type="RSA2",
                debug=IS_SANDBOX,
            )
    except ImportError:
        logger.error("cryptography library not installed")
    except Exception as e2:
        logger.error(f"Key conversion also failed: {type(e2).__name__}: {e2}")

    # Last resort: try with just the raw base64 (no PEM headers)
    try:
        raw_key = ALIPAY_PRIVATE_KEY.strip().replace("\\n", "").replace("\n", "").replace("\r", "")
        logger.info(f"Trying raw key (first 60 chars): {raw_key[:60]}")
        return AliPay(
            appid=ALIPAY_APP_ID,
            app_notify_url=ALIPAY_NOTIFY_URL,
            app_private_key_string=raw_key,
            alipay_public_key_string=pub_key,
            sign_type="RSA2",
            debug=IS_SANDBOX,
        )
    except Exception as e3:
        logger.error(f"All attempts failed. Last error: {type(e3).__name__}: {e3}")
        raise ValueError(
            f"Cannot load Alipay private key. "
            f"Please ensure ALIPAY_PRIVATE_KEY is a valid RSA private key. "
            f"Original error: {e1}"
        ) from e1


def create_qrcode_pay(order_no: str, amount_yuan: str, subject: str) -> str:
    """Create an Alipay face-to-face payment, return QR code URL or empty string."""
    try:
        alipay = _get_client()
        result = alipay.api_alipay_trade_precreate(
            out_trade_no=order_no,
            total_amount=amount_yuan,
            subject=subject,
            notify_url=ALIPAY_NOTIFY_URL,
        )
        logger.info(f"Alipay precreate result: {result}")
        return result.get("qr_code", "")
    except Exception as e:
        logger.error(f"Alipay error: {type(e).__name__}: {e}")
        # Try without signature verification for debugging
        try:
            import httpx
            import json as _json
            # Make raw API call to see the actual response
            biz_content = _json.dumps({"out_trade_no": order_no, "total_amount": amount_yuan, "subject": subject})
            logger.info(f"Raw biz_content: {biz_content}")
            # Use the SDK's unsigned method
            data = alipay._build_basic_params("alipay.trade.precreate")
            data["biz_content"] = biz_content
            resp = httpx.post(alipay._gateway, data=data)
            logger.info(f"Raw Alipay response: {resp.text}")
        except Exception as e2:
            logger.error(f"Raw call also failed: {e2}")
        return ""


def verify_notify(params: dict) -> bool:
    """Verify Alipay async notification signature."""
    sign = params.pop("sign", None)
    if not sign:
        return False
    try:
        alipay = _get_client()
        return alipay.verify(params, sign)
    except Exception as e:
        logger.error(f"Alipay verify error: {e}")
        return False


def query_trade(order_no: str) -> dict:
    """Query trade status."""
    alipay = _get_client()
    return alipay.api_alipay_trade_query(out_trade_no=order_no)
# deploy
