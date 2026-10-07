"""Baidu username/password login for the XiaoDu (小度) integration.

Implements the Baidu Passport basic-login flow:
  getapi (token) -> getpublickey (RSA pubkey) -> RSA-encrypt password
  -> POST /v2/api/?login -> BDUSS on success, captcha handling on demand.

RSA encryption uses `cryptography`, which is a core dependency of
Home Assistant, so no extra `requirements` entry is needed.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import (
    PASSPORT_GENIMAGE,
    PASSPORT_GETAPI,
    PASSPORT_GETPUBLICKEY,
    PASSPORT_HOST,
    PASSPORT_LOGIN,
)

_LOGGER = logging.getLogger(__name__)

LOGIN_TPL = "mn"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class BaiduLoginError(Exception):
    """Base error for the Baidu login flow."""


class BaiduCaptchaRequired(BaiduLoginError):
    """Login requires (or re-requires) a captcha."""

    def __init__(self, codestring: str) -> None:
        super().__init__("captcha required")
        self.codestring = codestring


class BaiduLogin:
    """Baidu Passport basic (username/password) login client."""

    def __init__(
        self, session: aiohttp.ClientSession, tpl: str = LOGIN_TPL
    ) -> None:
        """Initialize the login client."""
        self.session = session
        self.tpl = tpl
        self._headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.baidu.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self._gid: str = self._gen_gid()
        self._token: str = ""
        self._rsakey: str = ""
        self._pubkey: str = ""
        self._initialized = False

    @staticmethod
    def _gen_gid() -> str:
        """Generate a passport gid (UUID4, uppercase)."""
        return str(uuid.uuid4()).upper()

    @staticmethod
    def _gen_callback() -> str:
        """Generate a JSONP callback name."""
        return "bd__cbs__" + format(int(time.time() * 1000) % (2**31), "x")

    async def _ensure_initialized(self) -> None:
        """Visit passport once so the session carries base cookies."""
        if self._initialized:
            return
        try:
            async with self.session.get(
                PASSPORT_HOST + "/", headers=self._headers, timeout=10
            ) as resp:
                await resp.read()
        except aiohttp.ClientError:
            pass  # non-fatal; later calls still work without it
        self._initialized = True

    async def fetch_token(self) -> str:
        """Fetch the login token from getapi."""
        await self._ensure_initialized()
        params = {
            "getapi": "",
            "tpl": self.tpl,
            "apiver": "v3",
            "tt": str(int(time.time() * 1000)),
            "class": "login",
            "gid": self._gid,
            "logintype": "basicLogin",
            "callback": self._gen_callback(),
        }
        async with self.session.get(
            PASSPORT_HOST + PASSPORT_GETAPI,
            params=params,
            headers=self._headers,
            timeout=20,
        ) as resp:
            text = await resp.text()
        m = re.search(r'"token"\s*:\s*"([^"]+)"', text)
        if not m:
            raise BaiduLoginError("cannot fetch login token from Baidu Passport")
        self._token = m.group(1)
        return self._token

    async def fetch_public_key(self) -> tuple[str, str]:
        """Fetch the RSA public key and rsakey."""
        await self.fetch_token()
        params = {
            "token": self._token,
            "tpl": self.tpl,
            "apiver": "v3",
            "tt": str(int(time.time() * 1000)),
            "gid": self._gid,
            "callback": self._gen_callback(),
        }
        async with self.session.get(
            PASSPORT_HOST + PASSPORT_GETPUBLICKEY,
            params=params,
            headers=self._headers,
            timeout=20,
        ) as resp:
            text = await resp.text()
        m_key = re.search(r'"key"\s*:\s*"([^"]+)"', text)
        m_pub = re.search(r'"pubkey"\s*:\s*"([^"]+)"', text)
        if not m_key or not m_pub:
            raise BaiduLoginError("cannot fetch RSA public key from Baidu Passport")
        self._rsakey = m_key.group(1)
        self._pubkey = m_pub.group(1).replace("\\n", "\n")
        return self._rsakey, self._pubkey

    @staticmethod
    def _rsa_encrypt(pubkey_pem: str, plaintext: str) -> str:
        """RSA-encrypt (PKCS1 v1.5) and base64-encode the plaintext."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        public_key = serialization.load_pem_public_key(
            pubkey_pem.encode("utf-8")
        )
        ciphertext = public_key.encrypt(
            plaintext.encode("utf-8"), padding.PKCS1v15()
        )
        return base64.b64encode(ciphertext).decode("utf-8")

    async def login(
        self,
        username: str,
        password: str,
        verifycode: str = "",
        codestring: str = "",
    ) -> dict[str, Any]:
        """Perform the login POST.

        Returns {"success": True, "bduss": ..., "displayname": ...} on success.
        Raises BaiduCaptchaRequired when a captcha is needed (or was wrong).
        Raises BaiduLoginError on other failures.
        """
        await self.fetch_public_key()
        encrypted = await asyncio.to_thread(
            self._rsa_encrypt, self._pubkey, password
        )
        data: dict[str, str] = {
            "apiver": "v3",
            "charset": "utf-8",
            "countrycode": "",
            "crypttype": "12",
            "detect": "1",
            "foreignusername": "",
            "gid": self._gid,
            "isPhone": "",
            "logLoginType": "pc_loginBasic",
            "loginmerge": "true",
            "logintype": "basicLogin",
            "mem_pass": "on",
            "quick_user": "0",
            "safeflg": "0",
            "staticpage": "https://www.baidu.com/cache/user/html/v3Jump.html",
            "subpro": "",
            "tpl": self.tpl,
            "u": "https://www.baidu.com/",
            "username": username,
            "password": encrypted,
            "callback": "parent." + self._gen_callback(),
            "rsakey": self._rsakey,
            "token": self._token,
            "tt": str(int(time.time() * 1000)),
            "ppui_logintime": str(1000 + int(time.time()) % 20000),
        }
        if verifycode and codestring:
            data["verifycode"] = verifycode
            data["codestring"] = codestring

        async with self.session.post(
            PASSPORT_HOST + PASSPORT_LOGIN,
            data=data,
            headers=self._headers,
            timeout=30,
        ) as resp:
            text = await resp.text()

        result = self._parse_jsonp(text)
        err = result.get("errInfo", {})
        no = err.get("no", -1)
        if no == 0:
            bduss = result.get("data", {}).get("bduss", "")
            if not bduss:
                raise BaiduLoginError("login succeeded but BDUSS was missing")
            return {
                "success": True,
                "bduss": bduss,
                "displayname": result.get("data", {}).get("displayname", ""),
            }

        codestring_found = self._extract_codestring(text, result)
        if codestring_found:
            raise BaiduCaptchaRequired(codestring_found)

        msg = err.get("msg") or f"login failed (errNo={no})"
        if "密码" in msg or "错误" in msg or no == 1:
            raise BaiduLoginError("账号或密码错误")
        raise BaiduLoginError(str(msg))

    @staticmethod
    def _parse_jsonp(text: str) -> dict[str, Any]:
        """Parse a JSONP payload into a dict."""
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise BaiduLoginError("unexpected login response from Baidu")
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise BaiduLoginError("invalid login response from Baidu") from exc

    @staticmethod
    def _extract_codestring(text: str, result: dict[str, Any]) -> str | None:
        """Try to extract the captcha codestring from a login response."""
        for key in ("codeString", "codestring", "verifyStr", "codeString2"):
            v = result.get(key)
            if not v:
                v = result.get("data", {}).get(key)
            if v:
                return str(v)
        m = re.search(r'codeString["\']?\s*[:=]\s*["\']?([\w%]+)', text)
        if m:
            return m.group(1)
        m = re.search(r'"verifyStr"\s*:\s*"([^"]+)"', text)
        if m:
            return m.group(1)
        return None

    async def download_captcha(self, codestring: str) -> bytes:
        """Download the captcha image bytes for a codestring."""
        url = f"{PASSPORT_HOST}{PASSPORT_GENIMAGE}?{quote(codestring)}"
        async with self.session.get(url, headers=self._headers, timeout=20) as resp:
            return await resp.read()
