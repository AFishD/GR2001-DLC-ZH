# 状态机导航（nav_briefing.py）

自动把模拟器从开机带到**战役 C01「简介」页**并截图，用于换盘/换补丁后再现同一画面做像素对比。

## 用法

```powershell
python tools\emu\nav_briefing.py --iso work\builds\FINAL\GR_JS_ZH_v22_candidate.iso `
    --out work\analysis\emu\navauto_v22
```

产物：`<out>\001_main_menu.png`、`002_sp_menu.png`、`003_row_campaign.png`、
`004_campaign_gallery.png`、`00X_brief_XX.png`（简介页）等。

## 实测路径（在 v21 / v22 / 英文原盘 / probe P1 / P2 / P3 上各跑通）

1. 开机（厂商 logo/片头，90~200s 不定）→ **主菜单**（6 行：单人游戏/分屏/在线/选项/制作组/影片）
2. Cross → **单人游戏主菜单**（4 行：训练/战术演习/战役/快速任务；默认高亮=战役）
3. Cross → **战役画廊**（两横幅：ISLAND THUNDER / JUNGLE STORM；默认高亮 ISLAND THUNDER，右侧预览“警惕的农夫”）
4. Cross → 播任务过场 FMV（约 5~10s）
5. 自动进入 **简介页**（简介 / 右上 GR-C01 / 任务目标列表 / 地图照片 / 载入进度条）——页面会停留，不要按键

## 状态判定（画面特征，所有抓帧 2100×1106）

| 状态 | 判据 |
|---|---|
| 主菜单 | 黄色高亮像素 9500~9850 且 64×48 灰度模板距离 < 0.10 |
| 简介页 | 黄色像素 6300~6800 且连续 2 帧稳定 |
| 过场/加载 | 黄色像素 ≤500（等待，不按键） |
| 其它 | 继续按 Space/Return 推进或等待 |

中间菜单层级（单人菜单→画廊）之间用 3~4s 经验等待推进；**开机时长差异由“主菜单判定出现”吸收**，
所以不同机器/不同 ISO 的启动时间不会导致错位。

## 实测坑

1. **战役画廊里 Down/Up 是调难度**（右侧新兵/老兵/精英），不是换战役——不要按。
2. 本机 PCSX2 配置里方向键（D-pad）未绑定，PostMessage 注入无效；正好默认高亮就在“战役”，无需方向键。
3. 记忆卡必须挂载：`reference\Mcd001.ps2` → `work\emu_runtime\memcards\Mcd001.ps2`，
   ini `memcard='Mcd001.ps2'`，否则弹读卡/档案对话框干扰。
4. 厂商 logo/片头阶段不要提前按 Cross：脚本只在主菜单被判定后推进。
5. 简介页与训练任务简介页版式相近，但本路径固定进 ISLAND THUNDER 战役的 C01。

## 与“内存钩子”的关系

PCSX2-MCP 的调试钩子在本工程不稳定（JIT 下断点不 halt、内存读取要额外协议），所以状态判定用
**画面特征当软钩子**；识别逻辑独立，若以后能读内存状态（当前界面 id），替换判定即可。
