# PCSX2-MCP 安装与配置（本工作区内）

来源：https://github.com/hkmodd/PCSX2-MCP （MIT；PCSX2 本体为 GPL-3.0）
安装位置（工作区内，已 gitignore）：

```
tools/emu/pcsx2-mcp/PCSX2-MCP-v1.0.0-win64/
  ├─ pcsx2-qt.exe                  ← 带 DebugServer 的 PCSX2（TCP 127.0.0.1:21512）
  ├─ pcsx2-mcp-server/dist/index.js ← MCP 服务器（Node ≥18 运行）
  ├─ pcsx2-mcp-server/node_modules/
  ├─ source/DebugServer.cpp/.h      ← 唯一 PCSX2 修改的源码（GPL 合规）
  └─ setup-mcp.bat
```

## 1) 让本工程使用带 DebugServer 的模拟器

`tools/emu/nav_post.py` 支持 `--source-pcsx2`；
把上面目录传给 run_smoke / nav_post 即可（会自动拷贝到工作区 `work/analysis/emu/runtime_*`）：

```powershell
python tools\emu\nav_post.py --iso <abs iso> --memcard-src Mcd001.ps2 `
  --source-pcsx2 tools\emu\pcsx2-mcp\PCSX2-MCP-v1.0.0-win64 `
  --out work\analysis\emu\nav_mcp --seconds 300
```

DebugServer 启动后日志会出现：`[DebugServer] Listening on 127.0.0.1:21512`。

## 2) Python 直连（本会话实际使用的桥）

`tools/emu/pcsx2_dbg.py` 已实现 DebugServer（21512）与 Pine（28011）客户端：

```python
from tools.emu.pcsx2_dbg import DebugServer, Pine
d = DebugServer().connect()          # 暂停/继续/读内存/寄存器/断点/监视点/反汇编/调用栈
d.set_memcheck(0x1FFE35C, 0x1FFE360, type='write', action='break')   # 写监视点
p = Pine().connect()                 # 内存读写 + 存档槽 save/load
print(p.game_id(), p.uuid())
```

## 3) 给外部 AI 助手挂 MCP（Node ≥18）

- Antigravity/Gemini: `~/.gemini/antigravity/mcp_config.json`
- Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json`
- VS Code: 项目内 `.vscode/mcp.json`

```json
{
  "mcpServers": {
    "pcsx2": {
      "command": "node",
      "args": ["<本工作区绝对路径>/tools/emu/pcsx2-mcp/PCSX2-MCP-v1.0.0-win64/pcsx2-mcp-server/dist/index.js"]
    }
  }
}
```

## 4) 备注

- 本会话的 DSH 运行时不带 MCP 客户端，因此实际调试走第 2 节的 Python 客户端（能力等价）。
- 精简/重建时不要把这些二进制放进 Git：`.gitignore` 已加入 `tools/emu/pcsx2-mcp*/`、`tools/emu/*.zip`。
- 修改模拟器源码请在**本工作区**内克隆上游 PCSX2 并叠加 `source/DebugServer.cpp`，不要改动其它工作区目录。

## 5) 本机安装状态（2026-10-22 夜）

- 发布包已下载并解压到 	ools/emu/pcsx2-mcp/PCSX2-MCP-v1.0.0-win64/（52.3 MB / 4470 文件）；
  pcsx2-qt.exe 内含 DebugServer（字符串 DebugServer / Listening on 127.0.0.1 均在）。
- Node.js LTS 24.22.1 已装（scoop：C:\Users\84363\scoop\apps\nodejs-lts\current\node.exe），
  MCP 服务器可直接运行：
  
ode tools\emu\pcsx2-mcp\PCSX2-MCP-v1.0.0-win64\pcsx2-mcp-server\dist\index.js
- ⚠️ 本自动化（run_smoke / nav_post）写入的是 PCSX2 2.8 系初始化 ini；MCP 包内的 PCSX2 版本不同，
  直接复用该 ini 会启动失败（进程秒退、无日志）。若要把它接进自动化，需要按该版本重写 ini
  （或直接用它自己的 portable 配置目录）。本轮的崩溃定位/修复用的是**标准 PCSX2 + Pine**
  （pcsx2_dbg.py Pine 客户端）与 ELF 内嵌诊断 cave，功能上已满足要求。

## 6) 实测结果（2026-10-23 晨）

修好 Qt 插件目录后（`run_smoke.provision_runtime` 现在会复制
`platforms/ imageformats/ iconengines/ styles/ tls/ generic/ networkinformation/`），
MCP 包内 PCSX2 在本工程里正常运行：

```
[DebugServer] Listening on 127.0.0.1:21512        ← console.txt 实测
DebugServer OK: alive=True pc=0x0017a7b0          ← tools/emu/pcsx2_dbg.py 实测
  read 0x401F20 -> a0ffbd274000bfff3000b37f2000b27f
  guard word 0x401F98 opcode = c87b1608           ← 确认 v14 串守卫补丁在运行内存里
  disasm: addiu sp, -0x60
```

可用能力（已逐个调用验证）：`status / pause / resume / read_memory / write_memory /
read_registers / disassemble / set_breakpoint / set_memcheck(写监视点) / step /
get_backtrace / get_threads`。

注意：
- 该包内 PCSX2 未启用 Pine（28011 拒绝连接），存档/读档请用本工程既有的 F1 PostMessage +
  `.p2s` 解包流程（`work/analysis/emu/*_ram`）。
- `clear_breakpoints` 在该版本上会让 DebugServer 连接断开（客户端会报 ConnectionError），
  用 `remove_breakpoint <addr>` 逐个删即可。
- DebugServer 的写监视点（`set_memcheck type=write`）是后续继续追「写坏字符串对象」的写入者时
  最趁手的工具：命中后 `read_registers` + `get_backtrace` 即可拿到写者 PC。
