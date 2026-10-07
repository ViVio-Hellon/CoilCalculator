"""管理者パスワード ── マスタの置き場所・早見表の枠・マスタの表を**誤って直さない**ための関門

日報管理ツールの `nippou/admin_password.py` と同じ作り(VBA `AuthenticateAdmin` から
引き継いだ役目)。本来の意味でのアクセス制御ではありません ── その端末に触れる人は
ファイルを直接開けます。

    1. この端末で変えてあれば、その値(settings.json に PBKDF2 で撹拌して持つ)
    2. 配布の既定(config/app.json の admin.password_hash。scripts/make_dist.py --admin-password)
    3. どちらも無ければ既定の値(日報管理ツールと同じ。現場が覚えている値)

平文では持ちません。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Optional

from . import app_config, settings_store
from .logging_setup import get_logger

log = get_logger("coilcalc.admin_password")

DEFAULT = "nisk"
SCHEME = "pbkdf2"
ITERATIONS = 200_000
SALT_BYTES = 16
MIN_LENGTH = 4

REFUSE_WRONG = "wrong_password"
REFUSE_TOO_SHORT = "too_short"
REFUSE_MISMATCH = "mismatch"
REFUSE_SAME = "same"


@dataclass
class Result:
    ok: bool = True
    message: str = ""
    reason: str = ""


def _encode(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join([SCHEME, str(iterations), base64.b64encode(salt).decode("ascii"),
                     base64.b64encode(digest).decode("ascii")])


def _matches(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, _digest = stored.split("$")
        if scheme != SCHEME:
            return False
        expected = _encode(password, base64.b64decode(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, stored)


def hashed(password: str) -> str:
    return _encode(str(password), os.urandom(SALT_BYTES))


def _stored() -> Optional[str]:
    value = settings_store.get(settings_store.KEY_ADMIN_PASSWORD)
    if isinstance(value, str) and value.strip():
        return value
    site = (app_config.load().get("admin") or {}).get("password_hash")
    return site if isinstance(site, str) and site.strip() else None


def origin() -> str:
    """どこで決まっているか: terminal / site / default(画面に出す。値そのものは出さない)。"""
    value = settings_store.get(settings_store.KEY_ADMIN_PASSWORD)
    if isinstance(value, str) and value.strip():
        return "terminal"
    return "site" if _stored() else "default"


def verify(password: str) -> bool:
    """合っているか。**照合はここでしかしない。**"""
    stored = _stored()
    if stored is not None:
        return _matches(str(password), stored)
    return hmac.compare_digest(str(password).encode("utf-8"), DEFAULT.encode("utf-8"))


def change(current: str, new: str, confirm: str) -> Result:
    """変える。**いまのパスワードを知っている人だけ。**"""
    if not verify(current):
        log.warning("管理者パスワードの変更に失敗しました(いまの値が違う)")
        return Result(False, "いまのパスワードが違います。", REFUSE_WRONG)
    new = str(new)
    if len(new) < MIN_LENGTH:
        return Result(False, f"新しいパスワードは{MIN_LENGTH}文字以上にしてください。", REFUSE_TOO_SHORT)
    if new != str(confirm):
        return Result(False, "確認用と一致しません。", REFUSE_MISMATCH)
    if verify(new):
        return Result(False, "いまと同じパスワードです。", REFUSE_SAME)
    settings_store.save(settings_store.KEY_ADMIN_PASSWORD, hashed(new))
    log.info("管理者パスワードを変更しました(この端末)")
    return Result(True, "管理者パスワードを変えました(この端末)。")


def reset(current: str) -> Result:
    """この端末で変えた値をやめて、配布の既定(無ければ既定の値)に戻す。"""
    if not verify(current):
        return Result(False, "いまのパスワードが違います。", REFUSE_WRONG)
    settings_store.save(settings_store.KEY_ADMIN_PASSWORD, "")
    log.info("管理者パスワードを戻しました(この端末)")
    return Result(True, "配布の既定のパスワードに戻しました。" if origin() == "site"
                  else "既定のパスワードに戻しました。")
