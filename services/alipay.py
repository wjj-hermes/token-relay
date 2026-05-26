import os
from alipay import AliPay

ALIPAY_APP_ID = os.getenv("ALIPAY_APP_ID", "")
ALIPAY_PRIVATE_KEY = os.getenv("ALIPAY_PRIVATE_KEY", "")
ALIPAY_PUBLIC_KEY = os.getenv("ALIPAY_PUBLIC_KEY", "")
ALIPAY_NOTIFY_URL = os.getenv("ALIPAY_NOTIFY_URL", "")
IS_SANDBOX = os.getenv("ALIPAY_SANDBOX", "false").lower() == "true"


def _format_key(key: str) -> str:
    key = key.strip()
    if key.startswith("-----"):
        return key
    return f"-----BEGIN PRIVATE KEY-----\n{key}\n-----END PRIVATE KEY-----"


def _format_pub_key(key: str) -> str:
    key = key.strip()
    if key.startswith("-----"):
        return key
    return f"-----BEGIN PUBLIC KEY-----\n{key}\n-----END PUBLIC KEY-----"


def _get_client() -> AliPay:
    return AliPay(
        appid=ALIPAY_APP_ID,
        app_notify_url=ALIPAY_NOTIFY_URL,
        app_private_key_string=_format_key(ALIPAY_PRIVATE_KEY),
        alipay_public_key_string=_format_pub_key(ALIPAY_PUBLIC_KEY),
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
        return result.get("qr_code", "")
    except Exception as e:
        print(f"Alipay error: {e}")
        return ""


def verify_notify(params: dict) -> bool:
    """Verify Alipay async notification signature."""
    sign = params.pop("sign", None)
    if not sign:
        return False
    try:
        alipay = _get_client()
        return alipay.verify(params, sign)
    except Exception:
        return False


def query_trade(order_no: str) -> dict:
    """Query trade status."""
    alipay = _get_client()
    return alipay.api_alipay_trade_query(out_trade_no=order_no)
