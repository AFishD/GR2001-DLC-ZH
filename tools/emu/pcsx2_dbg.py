# -*- coding: utf-8 -*-
"""pcsx2_dbg.py —— PCSX2 DebugServer (TCP 21512) 与 Pine IPC (TCP 28011) 的 Python 客户端。

DebugServer 来自 https://github.com/hkmodd/PCSX2-MCP （pcsx2-plugin/DebugServer.cpp）：
换行分隔 JSON 请求/响应，支持 pause/resume/step、内存读写、寄存器、断点、反汇编、调用栈。

Pine 是 PCSX2 自带 IPC（Settings → Advanced → Enable Pine IPC，默认端口 28011）：
4 字节长度前缀 + 1 字节命令 + 参数；用于内存读写与存档槽 save/load。

用法示例：
    dbg = DebugServer(); dbg.connect()
    dbg.pause(); print(dbg.read_memory(0x401704, 16)); dbg.resume()
    pine = Pine(); pine.connect(); print(pine.read32(0x401704))
"""
import json
import socket
import struct
import time

DEBUG_PORT = 21512
PINE_PORT = 28011


class DebugServer:
    def __init__(self, host='127.0.0.1', port=DEBUG_PORT, timeout=10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.buf = b''

    def connect(self, retries=20, delay=0.5):
        last = None
        for _ in range(retries):
            try:
                s = socket.create_connection((self.host, self.port), timeout=self.timeout)
                s.settimeout(self.timeout)
                self.sock = s
                self.buf = b''
                return self
            except OSError as e:
                last = e
                time.sleep(delay)
        raise ConnectionError('DebugServer 连接失败 %s:%d (%s)' % (self.host, self.port, last))

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def cmd(self, **payload):
        if not self.sock:
            raise RuntimeError('未连接')
        line = json.dumps(payload, separators=(',', ':')).encode('utf-8') + b'\n'
        self.sock.sendall(line)
        while b'\n' not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('DebugServer 断开')
            self.buf += chunk
        raw, self.buf = self.buf.split(b'\n', 1)
        try:
            return json.loads(raw.decode('utf-8', 'replace'))
        except ValueError:
            return {'raw': raw.decode('utf-8', 'replace')}

    # ---- 便捷封装 -------------------------------------------------------
    def status(self):
        return self.cmd(cmd='status')

    def pause(self):
        return self.cmd(cmd='pause')

    def resume(self):
        return self.cmd(cmd='resume')

    def step(self, cpu='ee'):
        return self.cmd(cmd='step', cpu=cpu)

    def read_memory(self, addr, length):
        """返回 bytes（DebugServer 用 length 参数，最大 65536/次）。"""
        r = self.cmd(cmd='read_memory', address=addr, length=length)
        if isinstance(r, dict) and r.get('hex'):
            return bytes.fromhex(r['hex'])
        return r

    def read_block(self, addr, size, chunk=65536):
        out = bytearray()
        a = addr
        while len(out) < size:
            n = min(chunk, size - len(out))
            out += self.read_memory(a, n)
            a += n
        return bytes(out)

    def write_memory(self, addr, data_hex):
        return self.cmd(cmd='write_memory', address=addr, data=data_hex)

    def read_string(self, addr, max_len=256):
        return self.cmd(cmd='read_string', address=addr, maxLength=max_len)

    def read_registers(self, category=0, cpu='ee'):
        return self.cmd(cmd='read_registers', cpu=cpu, category=category)

    def set_breakpoint(self, addr, condition=None, description=None):
        p = dict(cmd='set_breakpoint', address=addr)
        if condition:
            p['condition'] = condition
        if description:
            p['description'] = description
        return self.cmd(**p)

    def list_breakpoints(self):
        return self.cmd(cmd='list_breakpoints')

    def clear_breakpoints(self):
        return self.cmd(cmd='clear_breakpoints')

    def set_memcheck(self, addr, end=None, type='write', action='break', description=None):
        p = dict(cmd='set_memcheck', address=addr, end=(end if end is not None else addr + 4),
                 type=type, action=action)
        if description:
            p['description'] = description
        return self.cmd(**p)

    def remove_memcheck(self, addr, end=None):
        return self.cmd(cmd='remove_memcheck', address=addr,
                        end=(end if end is not None else addr + 4))

    def disassemble(self, addr, count=10):
        return self.cmd(cmd='disassemble', address=addr, count=count)

    def backtrace(self):
        return self.cmd(cmd='get_backtrace')

    def threads(self):
        return self.cmd(cmd='get_threads')

    def modules(self):
        return self.cmd(cmd='get_modules')

    def evaluate(self, expr):
        return self.cmd(cmd='evaluate', expression=expr)


class Pine:
    """PCSX2 Pine IPC 客户端（内存读写 + 存档槽）。"""

    MSG_READ8, MSG_READ16, MSG_READ32, MSG_READ64 = 0, 1, 2, 3
    MSG_WRITE8, MSG_WRITE16, MSG_WRITE32, MSG_WRITE64 = 4, 5, 6, 7
    MSG_VERSION, MSG_SAVESTATE, MSG_LOADSTATE = 8, 9, 0xA
    MSG_TITLE, MSG_ID, MSG_UUID = 0xB, 0xC, 0xD

    def __init__(self, host='127.0.0.1', port=PINE_PORT, timeout=10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self, retries=20, delay=0.5):
        last = None
        for _ in range(retries):
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                self.sock.settimeout(self.timeout)
                return self
            except OSError as e:
                last = e
                time.sleep(delay)
        raise ConnectionError('Pine 连接失败 %s:%d (%s)' % (self.host, self.port, last))

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _send(self, cmd, payload=b''):
        body = bytes([cmd]) + payload
        self.sock.sendall(struct.pack('<I', len(body) + 4) + body)
        head = self._recv_exact(1)
        if head == b'\xff':
            raise RuntimeError('Pine 命令 0x%02X 失败' % cmd)
        return head

    def _recv_exact(self, n):
        out = b''
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError('Pine 断开')
            out += chunk
        return out

    def read32(self, addr):
        self._send(self.MSG_READ32, struct.pack('<I', addr))
        return struct.unpack('<I', self._recv_exact(4))[0]

    def read8(self, addr):
        self._send(self.MSG_READ8, struct.pack('<I', addr))
        return self._recv_exact(1)[0]

    def read(self, addr, size):
        """逐 4 字节读（Pine 无块读命令）。"""
        out = bytearray()
        a = addr
        while len(out) < size:
            out += struct.pack('<I', self.read32(a))
            a += 4
        return bytes(out[:size])

    def write32(self, addr, value):
        self._send(self.MSG_WRITE32, struct.pack('<II', addr, value))

    def write8(self, addr, value):
        self._send(self.MSG_WRITE8, struct.pack('<I', addr) + bytes([value & 0xFF]))

    def version(self):
        self._send(self.MSG_VERSION)
        size = struct.unpack('<I', self._recv_exact(4))[0]
        return self._recv_exact(size).split(b'\x00')[0].decode('utf-8', 'replace')

    def game_id(self):
        self._send(self.MSG_ID)
        size = struct.unpack('<I', self._recv_exact(4))[0]
        return self._recv_exact(size).split(b'\x00')[0].decode('utf-8', 'replace')

    def uuid(self):
        self._send(self.MSG_UUID)
        size = struct.unpack('<I', self._recv_exact(4))[0]
        return self._recv_exact(size).split(b'\x00')[0].decode('utf-8', 'replace')

    def save_state(self, slot=0):
        return self._send(self.MSG_SAVESTATE, bytes([slot & 0xFF]))

    def load_state(self, slot=0):
        return self._send(self.MSG_LOADSTATE, bytes([slot & 0xFF]))


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'pine':
        p = Pine().connect()
        print('game id:', p.game_id(), 'uuid:', p.uuid())
        print('read32(0x401704) = 0x%08X' % p.read32(0x401704))
    else:
        d = DebugServer().connect()
        print(json.dumps(d.status(), ensure_ascii=False, indent=1)[:800])
