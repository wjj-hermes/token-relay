"""Restore data from backup via HTTP API.
Usage: python restore_data.py [base_url]
"""
import json
import sys
import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://token-relay-v2-production.up.railway.app"
ADMIN_USER = "admin"
ADMIN_PASS = "Wj123321@"

client = httpx.Client(follow_redirects=True, timeout=30)


def login(username, password):
    resp = client.post(f"{BASE}/login", data={"username": username, "password": password})
    return resp.cookies


def admin_login():
    return login(ADMIN_USER, ADMIN_PASS)


def register_user(username, email, password):
    resp = client.post(f"{BASE}/register", data={
        "username": username, "email": email,
        "password": password, "password2": password,
    })
    return resp.status_code in (200, 302, 303)


def set_balance(cookies, user_id, balance):
    resp = client.post(f"{BASE}/admin/users/{user_id}/set_balance",
                       data={"balance": balance}, cookies=cookies)
    return resp.status_code in (200, 302, 303)


def main():
    with open("backup_20260527.json", "r", encoding="utf-8") as f:
        backup = json.load(f)

    print("=== Restoring data ===")

    # 1. Register users
    print("\n[Users]")
    for user in backup["users"]:
        username = user["用户名"]
        email = user["邮箱"]
        if username == "admin":
            print(f"  Skipping admin (auto-created)")
            continue
        pw = "temp123456"  # temporary password
        ok = register_user(username, email, pw)
        print(f"  Registered {username}: {'OK' if ok else 'FAILED'}")

    # 2. Set balances
    print("\n[Balances]")
    cookies = admin_login()
    for user in backup["users"]:
        if user["用户名"] == "admin":
            continue
        uid = int(user["ID"])
        balance_str = user["余额"].replace(",", "")
        balance = int(balance_str)
        # Find actual user ID by checking admin page
        resp = client.get(f"{BASE}/admin/users", cookies=cookies)
        import re
        for m in re.finditer(r'<td>(\d+)</td>\s*<td>' + re.escape(user["用户名"]) + r'</td>', resp.text):
            actual_id = int(m.group(1))
            ok = set_balance(cookies, actual_id, balance)
            print(f"  Set {user['用户名']} balance to {balance}: {'OK' if ok else 'FAILED'}")
            break

    # 3. Products are auto-seeded, just verify
    print("\n[Products]")
    resp = client.get(f"{BASE}/admin/products", cookies=cookies)
    product_count = resp.text.count("<td>上架</td>") + resp.text.count("<td>下架</td>")
    print(f"  Found {product_count} products (auto-seeded)")

    # 4. Models are auto-seeded, just verify
    print("\n[Models]")
    resp = client.get(f"{BASE}/admin/models", cookies=cookies)
    model_count = len(re.findall(r'<td>上架</td>', resp.text))
    print(f"  Found {model_count} models (auto-seeded)")

    print("\n=== Restore complete ===")


if __name__ == "__main__":
    main()
