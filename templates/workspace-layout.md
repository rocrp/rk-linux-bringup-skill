# 工作目录布局模板

> 一块板一个目录。把下面的树复制成你的工作区，四个顶层文档用固定文件名。

## 目录

```
<board>-bringup/
├── AGENTS.md              # 本项目 agent 规则（复制 templates/project-AGENTS.md）
├── board-profile.md       # 板卡档案（复制 templates/board-profile.md）
├── feasibility.md         # 可行性分析（复制 templates/feasibility.md）
├── plan.md                # 实施计划（复制 templates/plan.md）
├── progress.md            # 进度页（复制 templates/progress.md）
├── logs/
│   └── session-01-P0.md   # 会话日志（复制 templates/session-log.md）
├── dts/                   # <board>_v1.dts …
├── evidence/              # YYYYMMDD-<主题>/
├── images/                # 镜像/备份/payload（大文件，不入库）
└── release/               # 对外包（可选）
```

## 初始化

```bash
BOARD=<board>-bringup
mkdir -p "$BOARD"/{logs,dts,evidence,images}
cp <skill>/templates/project-AGENTS.md   "$BOARD/AGENTS.md"
cp <skill>/templates/board-profile.md    "$BOARD/board-profile.md"
cp <skill>/templates/feasibility.md      "$BOARD/feasibility.md"
cp <skill>/templates/plan.md             "$BOARD/plan.md"
cp <skill>/templates/progress.md         "$BOARD/progress.md"
cp <skill>/templates/session-log.md      "$BOARD/logs/session-01-P0.md"
```

## 开工检查

- [ ] 目录是这块板专用的，没有别的板子的文件
- [ ] 四个顶层文档都在，文件名没改
- [ ] `plan.md` 已由人确认定稿（不是"草案"）
- [ ] `AGENTS.md` 已按本项目改过

## 命名

| 对象 | 规则 | 例 |
|---|---|---|
| 目录 | `<board>-bringup` | `rk356x-demo-bringup` |
| 会话日志 | `session-<NN>-<phase>.md`，序号补零 | `session-03-P2.md` |
| dts 版本 | `<board>_v<N>.dts`，微调 `vN_M` | `demo_v2.dts`、`demo_v2_1.dts` |
| 证据目录 | `YYYYMMDD-<主题>` | `20261107-eMMC取证` |
| 镜像 | `<board>-v<N>.img` | `demo-v1.img` |

## 归档

板子完成或放弃后：

```bash
mv "$BOARD" "archive/$(basename "$BOARD")-$(date +%Y%m%d)"
```

不要清空复用。
