import os
import re
import logging
from alipay import AliPay

logger = logging.getLogger("alipay")

ALIPAY_APP_ID = os.getenv("ALIPAY_APP_ID", "")
ALIPAY_PRIVATE_KEY = os.getenv("ALIPAY_PRIVATE_KEY", "")
ALIPAY_PUBLIC_KEY = os.getenv("ALIPAY_PUBLIC_KEY", "")
ALIPAY_NOTIFY_URL = os.getenv("ALIPAY_NOTIFY_URL", "")
IS_SANDBOX = os.getenv("ALIPAY_SANDBOX", "false").lower() == "true"


def _format_key(key: str, key_type: str = "PRIVATE") -> str:
    key = key.strip().replace("\r", "").replace("\\n", "\n")
    if key.startswith("-----"):
        return key
    # Add proper PEM headers with line breaks every 64 chars
    lines = [key[i:i+64] for i in range(0, len(key), 64)]
    body = "\n".join(lines)
    return f"-----BEGIN {key_type} KEY-----\n{body}\n-----END {key_type} KEY-----"


def _get_client() -> AliPay:
    priv_key = _format_key(ALIPAY_PRIVATE_KEY, "PRIVATE")
    pub_key = _format_key(ALIPAY_PUBLIC_KEY, "PUBLIC")
    logger.info(f"Alipay APPID: {ALIPAY_APP_ID}")
    logger.info(f"Private key starts with: {priv_key[:30]}...")
    return AliPay(
        appid=ALIPAY_APP_ID,
        app_notify_url=ALIPAY_NOTIFY_URL,
        app_private_key_string=priv_key,
        alipay_public_key_string=pub_key,
        sign_type="RSA2",
        debug=IS_SANDBOX,
    )


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
