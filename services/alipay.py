import os
from typing import Optional
from alipay import AliPay

ALIPAY_APP_ID = os.getenv("ALIPAY_APP_ID", "")
ALIPAY_PRIVATE_KEY = os.getenv("ALIPAY_PRIVATE_KEY", "")
ALIPAY_PUBLIC_KEY = os.getenv("ALIPAY_PUBLIC_KEY", "")
ALIPAY_NOTIFY_URL = os.getenv("ALIPAY_NOTIFY_URL", "")
IS_SANDBOX = os.getenv("ALIPAY_SANDBOX", "false").lower() == "true"


def _get_client() -> AliPay:
    return AliPay(
        appid=ALIPAY_APP_ID,
        app_notify_url=ALIPAY_NOTIFY_URL,
        app_private_key_string=ALIPAY_PRIVATE_KEY,
        alipay_public_key_string=ALIPAY_PUBLIC_KEY,
        sign_type="RSA2",
        debug=IS_SANDBOX,
    )


def create_qrcode_pay(order_no: str, amount_yuan: str, subject: str) -> Optional[str]:
    """Create an Alipay face-to-face payment, return QR code URL or None."""
    alipay = _get_client()
    result = alipay.api_alipay_trade_precreate(
        out_trade_no=order_no,
        total_amount=amount_yuan,
        subject=subject,
        notify_url=ALIPAY_NOTIFY_URL,
    )
    qr_url = result.get("qr_code")
    return qr_url


def verify_notify(params: dict) -> bool:
    """Verify Alipay async notification signature."""
    sign = params.pop("sign", None)
    if not sign:
        return False
    alipay = _get_client()
    return alipay.verify(params, sign)


def query_trade(order_no: str) -> dict:
    """Query trade status."""
    alipay = _get_client()
    return alipay.api_alipay_trade_query(out_trade_no=order_no)
