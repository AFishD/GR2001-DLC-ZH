# -*- coding: utf-8 -*-
# [hanliu 收编] 原件: gr_tools/lz77_decode.py (逐字复制 (标准 LZO1X 解码器, 全项目解码基准))。原件保留于原处未动。
# 工具链总览见 hanliu/README.md 与 hanliu/tools/__init__.py。
"""Ghost Recon PS2 (SLUS-206.13) IMG 档案压缩格式解码器 — 最终版 (2026-09-10)

== 结论 (经 T01.MIS + D02_REFINERY.BMB 全量验证) ==

GR.IMG / MENU.IMG 档案条目(压缩) = 若干子流串联:
    子流 = {u32 LE payload_len}{u32 LE out_size}{payload_len 字节 payload}
  - out_size = 该子流 **解压后精确长度**; 全部子流 out_size 之和 = 条目表 real 字段
  - 每个子流 payload 末尾有 3 字节尾域 (解码器在耗尽输出后停止, 忽略尾 3 字节)

payload 编码 = **标准 LZO1X** (与 ffmpeg av_lzo1x_decode / lzo1x_decompress_safe 逐位一致):
  - 首字节 x: x > 17 -> 字面量段 (x-17 字节原文), 然后读下一令牌
  - 主循环令牌 x:
      x >= 64  (M2): len = (x>>5)-1+2 (2..9);  back = (b1<<3) + ((x>>2)&7) + 1
      32<=x<64 (M3): len = (x&31==0 ? 扩展 : x&31) + 2;  back = (b2<<6) + (b1>>2) + 1
                     (x&31==0 时: while(b==0) cnt+=255; cnt += 31 + 下一个非零字节)
      16<=x<32 (M1): len = (x&7==0 ? 扩展 : x&7) + 2;  back = (1<<14) + ((x&8)<<11)
                     + (b2<<6) + (b1>>2);  back==1<<14 && len==3 -> 流结束标记
       x<=15 且上一匹配后置字面量数==0 -> 长字面量段: len = (x&15==0 ? 扩展 : x&15)+3
       x<=15 且上一匹配后置字面量数!=0 (M4): len = 2; back = (b1<<2) + (x>>2) + 1
  - 每个匹配后随 x&3 (M2/M4 用令牌低 2 位; M3/M1 用 b1 低 2 位) 字节字面量
  - M3/M1 的第一个 back 参数字节 b1 会覆盖 x (即后置字面量数 = b1 & 3)
  - 匹配拷贝允许重叠 (back < len 时为 RLE 式重复)

之前会话的 "count-layer (c-17 字面量 / c=0x00 转义 / c=1-16 匹配)" 理解是错的:
  - "c-17 字面量" 只对应 LZO1X 的首令牌特例 (x>17)
  - "c=0x00 转义" 是 LZO1X 长字面量扩展 (x&15==0) 的误读
  - 匹配令牌其实是 M1/M2/M3/M4 四种 LZO1X 匹配

用法:
    python lz77_decode.py <stored_file> <out_file> [--info]
或:
    from lz77_decode import decode_entry, decode_substream
"""
import struct
import sys


def lzo1x_decompress(payload, out_size=None):
    """解码单个子流 payload (LZO1X)。
    out_size: 若提供则作为输出精确长度(到达即停, 验证用); 否则解码到输入耗尽。
    返回 (bytes, err, consumed_ip)。err=None 表示成功。"""
    data = payload
    ip = 0
    n = len(data)
    out = bytearray()

    def GETB():
        nonlocal ip
        if ip >= n:
            raise IndexError('input depleted at ip=%d' % ip)
        b = data[ip]
        ip += 1
        return b

    state = 0
    err = None
    try:
        x = GETB()
        if x > 17:                       # 首令牌: 字面量段
            out += data[ip:ip + (x - 17)]
            ip += x - 17
            x = GETB()
            # 注: x < 16 在此为合法 (长字面量段 len = x+3, LZO1X 标准),
            # 先前版本误标为 corrupt 导致纯字面量流无法解码
        while err is None:
            if out_size is not None and len(out) >= out_size:
                break                    # 已达声明输出长度 (余 3 字节尾域)
            if x > 15:
                if x > 63:
                    # M2: 2 字节匹配, len 2..9, back ≤ 2048
                    cnt = (x >> 5) - 1
                    back = (GETB() << 3) + ((x >> 2) & 7) + 1
                    # x 仍 = 令牌: 后置字面量数 = x & 3
                elif x > 31:
                    # M3/M4: 3 字节匹配, 长度可扩展
                    cnt = x & 31
                    if cnt == 0:
                        while True:
                            x = GETB()
                            if x:
                                cnt += 31 + x
                                break
                            cnt += 255
                    x = GETB()           # b1 覆盖 x (后置字面量数 = b1 & 3)
                    back = (GETB() << 6) + (x >> 2) + 1
                else:
                    # M1: 长距离匹配 (3 字节), back == 1<<14 时为流结束
                    cnt = x & 7
                    if cnt == 0:
                        while True:
                            x = GETB()
                            if x:
                                cnt += 7 + x
                                break
                            cnt += 255
                    back = (1 << 14) + ((x & 8) << 11)
                    x = GETB()
                    back += (GETB() << 6) + (x >> 2)
                    if back == (1 << 14):
                        break            # 流结束标记
            elif not state:
                # 长字面量段 (len = cnt+3, cnt 可扩展) — 旧会话误读为 "c=0x00 转义"
                cnt = x & 15
                if cnt == 0:
                    while True:
                        x = GETB()
                        if x:
                            cnt += 15 + x
                            break
                        cnt += 255
                out += data[ip:ip + cnt + 3]
                ip += cnt + 3
                x = GETB()
                if x > 15:
                    continue
                cnt = 1
                back = (1 << 11) + (GETB() << 2) + (x >> 2) + 1
            else:
                # M4: 紧凑匹配 (state != 0 时遇到 x <= 15)
                cnt = 0
                back = (GETB() << 2) + (x >> 2) + 1
            o = len(out)
            if back > o:
                err = 'INVALID BACK %d at out=%d ip=%d' % (back, o, ip - 1)
                break
            for i in range(cnt + 2):     # 允许重叠拷贝 (back < len => RLE)
                out.append(out[o - back + i])
            state = cnt = x & 3          # 匹配后置字面量
            out += data[ip:ip + cnt]
            ip += cnt
            if out_size is not None and len(out) >= out_size:
                break
            if ip >= n:
                break
            x = GETB()
    except IndexError as e:
        err = str(e)
    return bytes(out), err, ip


def iter_substreams(stored):
    """迭代 {u32 plen}{u32 out_size}{payload} 子流。yield (payload, out_size, frame_off)。"""
    p = 0
    n = len(stored)
    while p + 8 <= n:
        plen, osz = struct.unpack_from('<II', stored, p)
        if plen == 0 or p + 8 + plen > n:
            break
        yield stored[p + 8:p + 8 + plen], osz, p
        p += 8 + plen


def decode_entry(stored, verify=True, log=None):
    """解码完整档案条目 (全部子流)。
    verify=True: 校验每子流输出长度 == out_size。
    返回 (bytes, [(sub_index, out_len, expected, err), ...])

    注: 子流分两类 —
      1) 压缩: plen < osz, payload = LZO1X 流, 以 3 字节 M1 结束标记收尾
         (back == 0x4000 && len == 3, 即 ffmpeg 实现里的 EOF 分支);
      2) 原样存储: plen == osz, 输出 = payload 本身 (身份拷贝)。
    out_size 恒等于该子流精确输出长度; 全部子流之和 = 条目 real。"""
    out_parts = []
    stats = []
    for i, (payload, osz, foff) in enumerate(iter_substreams(stored)):
        if len(payload) == osz:
            out, err, ip = payload, None, len(payload)   # 原样存储子流
        else:
            out, err, ip = lzo1x_decompress(payload, out_size=osz if verify else None)
        if len(out) != osz and osz < (1 << 20):   # 超长 out_size 视为缓冲上限
            err = err or ('out %d != osz %d' % (len(out), osz))
        out_parts.append(out)
        stats.append((i, len(out), osz, err))
        if log is not None and (err or i < 3):
            log.append('sub%3d: out=%d/%d ip=%d/%d err=%s'
                       % (i, len(out), osz, ip, len(payload), err))
    return b''.join(out_parts), stats


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    src, dst = argv[1], argv[2]
    data = open(src, 'rb').read()
    out, stats = decode_entry(data, log=print if '--info' in argv else None)
    open(dst, 'wb').write(out)
    bad = [s for s in stats if s[3]]
    print('%s -> %s: %d substreams, %d bytes decoded, %d errors'
          % (src, dst, len(stats), len(out), len(bad)))
    return 0 if not bad else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
