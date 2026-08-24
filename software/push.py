"""Send web push alerts to phones that installed the PWA.

Web push needs a VAPID keypair: the private key signs our requests to the
browser's push service, the public key is handed to the page so it can create a
subscription bound to us.
"""

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush

KEY_PATH = Path(__file__).with_name("vapid_private.pem")
SUBS_PATH = Path(__file__).with_name("push_subscriptions.json")
# push services require a contact for the key owner; any mailto works.
VAPID_CLAIMS = {"sub": "mailto:gatan9dragos@gmail.com"}
# push services drop a subscription that has been unsubscribed or expired.
GONE_STATUS = (404, 410)


def _b64(raw):
    """base64url without padding, the encoding every web push field uses."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def load_or_create_key():
    """Return the VAPID private key, generating one on first run."""
    if KEY_PATH.exists():
        return serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)

    key = ec.generate_private_key(ec.SECP256R1())
    KEY_PATH.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    print(f"[push] generated a new VAPID key at {KEY_PATH.name}")
    return key


def public_key_b64(key):
    """The applicationServerKey the browser needs, as base64url."""
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64(raw)


def load_subscriptions():
    """Every phone currently subscribed, or an empty list on first run."""
    if not SUBS_PATH.exists():
        return []
    try:
        return json.loads(SUBS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as error:
        print(f"[push] could not read {SUBS_PATH.name}: {error}")
        return []


def save_subscriptions(subscriptions):
    SUBS_PATH.write_text(json.dumps(subscriptions, indent=2))


def add_subscription(subscription):
    """Store one phone's subscription, ignoring a phone we already have."""
    subscriptions = load_subscriptions()
    endpoints = {item.get("endpoint") for item in subscriptions}
    if subscription.get("endpoint") in endpoints:
        return len(subscriptions)

    subscriptions.append(subscription)
    save_subscriptions(subscriptions)
    print(f"[push] subscribed a phone, {len(subscriptions)} total")
    return len(subscriptions)


def send(payload):
    """Push one alert to every subscribed phone, dropping dead subscriptions."""
    subscriptions = load_subscriptions()
    if not subscriptions:
        print("[push] no phones subscribed, alert not sent")
        return 0

    key_pem = str(KEY_PATH)
    alive = []
    sent = 0
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps(payload),
                vapid_private_key=key_pem,
                vapid_claims=dict(VAPID_CLAIMS),
            )
            alive.append(subscription)
            sent += 1
        except WebPushException as error:
            status = getattr(error.response, "status_code", None)
            if status in GONE_STATUS:
                print("[push] dropping an expired subscription")
                continue
            print(f"[push] send failed: {error}")
            alive.append(subscription)

    if len(alive) != len(subscriptions):
        save_subscriptions(alive)
    print(f"[push] alert sent to {sent} phone(s)")
    return sent
