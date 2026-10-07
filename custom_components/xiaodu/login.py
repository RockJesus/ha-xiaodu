"""Baidu username/password login for the XiaoDu (小度) integration.

Implements the real wappass login protocol captured from the Baidu
passport login page (wappass.baidu.com/wp/api/login, tpl=wimn):

  1. antireplaytoken  -> servertime
  2. viewlog          -> ds / tk
  3. cap/init         -> s / k
  4. RSA-encrypt account (encode64Txt) and password (password+servertime)
  5. moonshadV3 risk-control signature (sig / shaOne / rinfo)
  6. POST /wp/api/login -> BDUSS on success

The moonshad signature algorithm (v3, day-rotating AES keys, screen-obfuscated
md5 plaintext, double base64) was reverse-engineered from the real page JS
(moonshad.js) and verified against captured requests.

A ``BAIDUID`` cookie value (a long-lived Baidu visitor id, e.g. from a browser
that visited baidu.com) is recommended for the account+password mode; without
a trusted BAIDUID Baidu's risk control may demand SMS verification (400023).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
import uuid
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import (
    ERROR_LOGIN_BLOCKED,
)

_LOGGER = logging.getLogger(__name__)

AK = "1e3f2dd1c81f2075171a547893391274"

# RSA modulus (1024-bit) embedded in the passport page bundle (lib_rsa_RSA).
_RSA_MODULUS = int(
    "B3C61EBBA4659C4CE3639287EE871F1F48F7930EA977991C7AFE3CC442FEA49643"
    "212E7D570C853F368065CC57A2014666DA8AE7D493FD47D171C0D894EEE3ED7F99F"
    "6798B7FFD7B5873227038AD23E3197631A8CB642213B9F27D4901AB0D92BFA27542"
    "AE890855396ED92775255C977F5C302F1E7ED4B1E369C12CB6B1822F",
    16,
)
_RSA_E = 0x10001

# moonshadV3 screen-obfuscation substitution table.
_SCREEN_MAP = {
    "a": "3", "b": "4", "c": "5", "d": "9", "e": "8", "f": "7", "g": "1",
    "h": "2", "i": "6", "j": "0", "k": "a", "l": "b", "m": "c", "n": "d",
    "o": "e", "p": "f", "q": "g", "r": "z", "s": "y", "t": "x", "u": "w",
    "v": "v", "w": "u", "x": "o", "y": "p", "z": "q", "0": "s", "1": "t",
    "2": "r", "3": "h", "4": "i", "5": "j", "6": "k", "7": "l", "8": "m",
    "9": "n",
}
# moonshadV3 day-rotating AES keys.
_MOON_KEYS = {
    "OOOO00": "moonshad5moonsh2",
    "OOO00O": "moonshad3moonsh0",
    "OOO000": "moonshad8moonsh6",
    "OOO0OO": "moonshad0moonsh1",
    "O0OOO0": "moonshad1moonsh9",
}
_MOON_VARIANTS = ["OOOO00", "OOO00O", "OOO000", "OOO0OO", "O0OOO0"]

_WAPPASS = "https://wappass.baidu.com"
_PASSPORT = "https://passport.baidu.com"
_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/110 Mobile Safari/537.36"
)
_LOGIN_REFERER = (
    "https://wappass.baidu.com/passport/login?tpl=wimn&u=https%3A%2F%2F"
    "xiaodu.baidu.com%2Fsaiya%2Fsmarthome%2Findex.html"
)
_CAP_INIT_REFERER = (
    "https://wappass.baidu.com/passport/?login&tpl=wimn&adapter=3&subpro=wimn"
    "&regtype=1&u=https%3A%2F%2Fxiaodu.baidu.com%2Fsaiya%2Fsmarthome%2Findex.html%23%2Fpassword_login"
)


class BaiduLoginError(Exception):
    """Base error for the Baidu login flow."""


class BaiduCaptchaRequired(BaiduLoginError):
    """Login requires (or re-requires) a captcha."""

    def __init__(self, codestring: str) -> None:
        super().__init__("captcha required")
        self.codestring = codestring


class BaiduLoginBlocked(BaiduLoginError):
    """Login was blocked by risk control (e.g. SMS verification)."""


class BaiduLogin:
    """Baidu wappass (username/password) login client."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the login client."""
        self.session = session
        self._headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self._fuid: str = self._gen_fuid()

    @staticmethod
    def _gen_fuid() -> str:
        """Generate a fingerprint uid (md5 of random uuid)."""
        return hashlib.md5(uuid.uuid4().hex.encode()).hexdigest()

    @staticmethod
    def _gen_gid() -> str:
        """Generate a passport gid (UUID4, uppercase)."""
        return str(uuid.uuid4()).upper()

    @staticmethod
    def _encode64txt(s: str) -> str:
        """btoa(encodeURIComponent(s) unescaped); for non-ASCII this equals UTF-8 base64."""
        return base64.b64encode(s.encode("utf-8")).decode()

    @staticmethod
    def _rsa_encrypt(plain: str) -> str:
        """Baidu passport JS RSA: chunkSize=64 UTF-16 units, little-endian 16-bit digits, hex out (256 chars)."""
        data = [ord(c) for c in plain]
        while len(data) % 64:
            data.append(0)
        out = ""
        for i in range(0, len(data), 64):
            chunk = data[i:i + 64]
            val = 0
            for j in range(32):
                d = chunk[2 * j] + (chunk[2 * j + 1] << 8)
                val += d << (16 * j)
            out += format(pow(val, _RSA_E, _RSA_MODULUS), "x").zfill(256)
        return out

    @staticmethod
    def _aes_ecb_encrypt(key: str, plaintext: bytes) -> bytes:
        """AES-128-ECB PKCS7 encrypt via cryptography (HA core dependency)."""
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        padded = plaintext + bytes([16 - len(plaintext) % 16]) * (16 - len(plaintext) % 16)
        enc = Cipher(algorithms.AES(key.encode()), modes.ECB()).encryptor()
        return enc.update(padded) + enc.finalize()

    def _moonshad_sig(
        self, params: dict[str, str], now_s: int
    ) -> dict[str, str]:
        """Replicate moonshadV3 signature generation for the login form.

        plaintext = interleave(md5(sorted k=v&...), screen_obfuscation(6 chars))
        sig       = base64(base64(AES-ECB(plaintext, day-key)))
        """
        p = {k: v for k, v in params.items() if v not in ("", None)}
        p["alg"] = "v3"
        p["time"] = str(now_s)
        ser = "&".join(f"{k}={p[k]}" for k in sorted(p))
        md5 = hashlib.md5(ser.encode()).hexdigest()
        sc = "".join(_SCREEN_MAP.get(c, c) for c in "360640")
        plain = "".join(md5[i] + sc[i] for i in range(6)) + md5[6:]
        day = int(now_s // 86400) % 5
        key = _MOON_KEYS[_MOON_VARIANTS[day]]
        ct = self._aes_ecb_encrypt(key, plain.encode())
        sig = base64.b64encode(base64.b64encode(ct)).decode()

        # shaOne: SHA1(md5(ms)) loop until hex starts with "00"
        a = int(time.time() * 1000)
        while True:
            a = hashlib.sha1(hashlib.md5(str(a).encode()).hexdigest().encode()).hexdigest()
            if a.startswith("00"):
                break
        rinfo = '{"fuid": "%s"}' % hashlib.md5(self._fuid.encode()).hexdigest()
        return {
            "sig": sig,
            "shaOne": a,
            "time": str(now_s),
            "alg": "v3",
            "elapsed": "6",
            "rinfo": rinfo,
        }

    async def _get_servertime(self, cookie: str) -> str:
        """GET antireplaytoken -> hex servertime."""
        url = (
            f"{_WAPPASS}/wp/api/security/antireplaytoken?alg=v3&baiduId="
            f"{quote(self._baiduid)}&elapsed=6&fuid={self._fuid}"
        )
        headers = dict(self._headers)
        if cookie:
            headers["Cookie"] = cookie
        async with self.session.get(url, headers=headers, timeout=20) as resp:
            text = await resp.text()
        m = re.search(r'"time"\s*:\s*"?([0-9a-f]+)"?', text)
        if not m:
            raise BaiduLoginError("cannot fetch servertime from Baidu")
        return m.group(1)

    async def _get_viewlog(self, cookie: str) -> tuple[str, str]:
        """GET viewlog (JSONP) -> ds/tk."""
        cb = "jQuery%s_%d" % ("11020058303661639652615", int(time.time() * 1000) - 1000)
        url = f"{_PASSPORT}/viewlog?callback={cb}&ak={AK}&_={int(time.time() * 1000)}"
        headers = dict(self._headers)
        if cookie:
            headers["Cookie"] = cookie
        async with self.session.get(url, headers=headers, timeout=20) as resp:
            text = await resp.text()
        m = re.search(r"\((\{.*\})\)\s*;?\s*$", text, re.S)
        if not m:
            raise BaiduLoginError("cannot parse viewlog response")
        data = json.loads(m.group(1)).get("data", {})
        return data.get("ds", ""), data.get("tk", "")

    async def _get_capinit(self, cookie: str) -> tuple[str, str]:
        """POST cap/init -> s/k (needs the passport Referer)."""
        data = (
            f"_={int(time.time() * 1000)}&refer="
            f"https%3A%2F%2Fwappass.baidu.com%2Fpassport%2F%3Flogin%26tpl%3Dwimn"
            f"%26adapter%3D3%26subpro%3Dwimn%26regtype%3D1%26u%3Dhttps%253A%252F%252F"
            f"xiaodu.baidu.com%252Fsaiya%252Fsmarthome%252Findex.html%2523%252Fpassword_login"
            f"&ak={AK}&ver=2&scene=&ds=&tk=&as=&reinit=0"
        )
        headers = dict(self._headers)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Referer"] = _CAP_INIT_REFERER
        if cookie:
            headers["Cookie"] = cookie
        async with self.session.post(
            f"{_PASSPORT}/cap/init", data=data, headers=headers, timeout=20
        ) as resp:
            text = await resp.text()
        try:
            data = json.loads(text).get("data", {})
        except json.JSONDecodeError as exc:
            raise BaiduLoginError("cannot parse cap/init response") from exc
        return data.get("ds", ""), data.get("tk", "")

    async def login(
        self,
        username: str,
        password: str,
        baiduid: str = "",
        verifycode: str = "",
        codestring: str = "",
    ) -> dict[str, Any]:
        """Perform the wappass login POST.

        ``baiduid`` is a Baidu visitor cookie value (e.g. ``XXXX...:FG=1``)
        that the user copied from a browser. Without a trusted BAIDUID the
        login may be blocked by risk control (400023 SMS verification).

        Returns {"success": True, "bduss": ...} on success.
        """
        self._baiduid = baiduid or (self._gen_gid() + ":FG=1")
        cookie = f"BAIDUID={self._baiduid}" if self._baiduid else ""

        now_ms = int(time.time() * 1000)
        now_s = int(time.time())

        servertime = await self._get_servertime(cookie)
        ds, tk = await self._get_viewlog(cookie)
        s, k = await self._get_capinit(cookie)

        enc_user = await asyncio.to_thread(
            self._rsa_encrypt, self._encode64txt(username)
        )
        enc_pass = await asyncio.to_thread(self._rsa_encrypt, password + servertime)

        gid = self._gen_gid()
        u = "https%3A%2F%2Fxiaodu.baidu.com%2Fsaiya%2Fsmarthome%2Findex.html"
        params: dict[str, str] = {
            "adapter": "3",
            "cv": "170601",
            "gid": gid,
            "isEncrypted": "1",
            "isphone": "0",
            "lang": "zh-cn",
            "logLoginType": "sdk_login",
            "loginmerge": "1",
            "nalogin": "0",
            "subpro": "wimn",
            "suppWapFace": "0",
            "tpl": "wimn",
            "u": u,
            "session_id": f"{gid}-v2-{now_ms - 84440}-login_history",
            "baiduId": self._baiduid,
            "fuid": self._fuid,
            "servertime": servertime,
            "tt": str(now_ms),
            "ds": ds,
            "tk": tk,
            "s": s,
            "k": k,
            "username": enc_user,
            "password": enc_pass,
            "v2Enable": "0",
        }
        sig = await asyncio.to_thread(self._moonshad_sig, params, now_s)
        params.update(sig)

        headers = dict(self._headers)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Referer"] = _LOGIN_REFERER
        if cookie:
            headers["Cookie"] = cookie

        async with self.session.post(
            f"{_WAPPASS}/wp/api/login", data=params, headers=headers, timeout=30
        ) as resp:
            text = await resp.text()

        result = self._parse_json(text)
        err = result.get("errInfo", {})
        no = err.get("no", -1)
        if no in ("0", 0):
            bduss = result.get("data", {}).get("bduss", "")
            if not bduss:
                raise BaiduLoginError("login succeeded but BDUSS was missing")
            return {
                "success": True,
                "bduss": bduss,
                "ptoken": result.get("data", {}).get("ptoken", ""),
            }
        if str(no) == "400023":
            raise BaiduLoginBlocked(
                "百度风控要求短信验证（400023）。请在浏览器登录一次百度账号，"
                "复制 Cookie 中的 BAIDUID 填入本页后重试，或改用 Cookie 登录方式。"
            )
        if str(no) in ("340002", "500001", "500002", "50020", "50021", "50052"):
            raise BaiduCaptchaRequired(
                result.get("data", {}).get("codeString", "")
                or result.get("data", {}).get("codeString2", "")
            )
        msg = err.get("msg") or f"login failed (errNo={no})"
        if str(no) in ("400010", "400011", "400015", "400038", "1") or "密码" in msg:
            raise BaiduLoginError("账号或密码错误")
        raise BaiduLoginError(str(msg))

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """Parse a JSON response into a dict."""
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise BaiduLoginError("unexpected login response from Baidu")
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise BaiduLoginError("invalid login response from Baidu") from exc
