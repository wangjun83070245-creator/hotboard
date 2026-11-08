"""dry-run 安全护栏：只允许写隔离测试目录；不联网。

威胁模型（本地、非对抗性多用户以外的误用/误配为主）：
- 误把 --out 指到工程根、正式 data/site/logs/snapshots，或它们的祖先/后代 → 拒绝（包含或被包含都拒）。
- 路径里带 ".."、路径本身或任一祖先是符号链接/目录链接（直接或间接）→ 拒绝，不跟随。
- 输出目录已存在且其中任意位置有符号链接（例如 data/snapshots → 正式快照）→ 拒绝，防止写入/prune 穿透。
- dry-run 期间禁止任何网络连接（socket 连接与 DNS 解析都抛错），且根本不调用采集。
已知限制（竞态）：校验与写入之间存在 TOCTOU 窗口；同一用户的并发进程若在校验后把目录换成链接，
本模块只能在写快照前、prune 前、写页面前再校验一次缩小窗口，不能完全消除（未使用 openat/O_NOFOLLOW 全链路）。
"""
import os
import socket
from contextlib import contextmanager
from pathlib import Path


class UnsafeOutput(ValueError):
    pass


def _components(p):
    """绝对路径从根到自身的每一级（不解析链接）。"""
    parts = Path(p).parts
    for i in range(1, len(parts) + 1):
        yield Path(*parts[:i])


def _overlap(a, b):
    """a、b 为不含链接的绝对路径：相等、a 在 b 下、或 b 在 a 下。"""
    return a == b or b in a.parents or a in b.parents


def validate_out(out, protected):
    """返回校验后的绝对路径；不安全则抛 UnsafeOutput。protected：正式路径列表（工程根、data、site、logs、snapshots…）。"""
    raw = str(out)
    if not raw or "\x00" in raw:
        raise UnsafeOutput("输出路径为空或非法")
    if ".." in Path(raw).parts:
        raise UnsafeOutput("输出路径不能含 ..")
    absout = Path(os.path.abspath(raw))
    for c in _components(absout):
        if os.path.islink(c):
            raise UnsafeOutput(f"输出路径或其祖先是符号链接：{c.name or '/'}")
        if not os.path.lexists(c):
            break
    real = Path(os.path.realpath(absout))
    if real != absout:
        raise UnsafeOutput("输出路径解析后与原路径不一致（有链接）")
    for p in protected:
        pr = Path(os.path.realpath(os.path.abspath(p)))
        for cand in {Path(os.path.abspath(p)), pr}:
            if _overlap(real, cand):
                raise UnsafeOutput("输出路径与正式目录重叠（包含或被包含）")
    if os.path.lexists(absout):
        if not absout.is_dir():
            raise UnsafeOutput("输出路径已存在但不是目录")
        for dirpath, dirnames, filenames in os.walk(absout, followlinks=False):
            for n in dirnames + filenames:
                if os.path.islink(os.path.join(dirpath, n)):
                    raise UnsafeOutput("输出目录内已有符号链接，拒绝写入")
    return absout


@contextmanager
def no_network():
    """dry-run 期间禁止联网；退出时恢复。"""
    def deny(*_a, **_k):
        raise OSError("dry-run: 禁止联网")
    saved = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
    socket.getaddrinfo = deny
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo = saved
