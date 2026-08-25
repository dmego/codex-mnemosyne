# codex-mnemosyne

面向 Codex 的 Mnemosyne 原生插件接入层。它通过 Codex 生命周期 hooks 自动召回和写回记忆，不再依赖模型主动调用 Mnemosyne MCP 工具。

## 自动行为

| Hook | 行为 |
| --- | --- |
| `SessionStart` | 注入有限的最近上下文。 |
| `UserPromptSubmit` | 按当前 prompt 召回相关记忆，并通过 `additionalContext` 注入。 |
| `PostToolUse` | 只排队编辑、测试、构建等高信号观察，跳过只读噪声。 |
| `Stop` | 捕获最新的 user/assistant 结果并刷新 outbox。 |
| `PreCompact` | 上下文压缩前刷新 transcript 增量。 |
| `SessionEnd` | 宿主提供 transcript 时做最后一次写回。 |

自动路径直接导入 Mnemosyne SDK。MCP 是可选的：它适合显式搜索、查看、更新、失效、删除、诊断和 consolidation，但自动召回和写回都不需要 MCP。如果没有配置 Mnemosyne MCP server，自动路径仍然可以完整工作。

## 要求

- 支持 Codex plugin lifecycle hooks，并批准插件信任。
- Hook 使用 Python 3.10+。
- Hook 使用的 Python 环境能够导入 `mnemosyne`。
- 插件本身不要求网络；embedding 和结构化 extraction 是否联网由 Mnemosyne 自己的配置决定。

## 本地安装

这个目录是可安装的 plugin source。仓库根目录已经包含 Codex marketplace 清单，可以从 GitHub 或本地 checkout 安装：

仓库中的插件源路径是：`plugins/codex-mnemosyne/`。

```bash
codex plugin marketplace add https://github.com/dmego/codex-mnemosyne.git
codex plugin list --marketplace codex-mnemosyne --available
codex plugin add codex-mnemosyne@codex-mnemosyne

# 或直接使用本地 checkout：
codex plugin marketplace add /Users/dmego/vibeCoding/codex-mnemosyne
codex plugin add codex-mnemosyne@codex-mnemosyne
```

启用后重启 Codex 并批准 hooks。不要覆盖已有的 `~/.codex/hooks.json`，插件 hooks 应与用户 hooks 合并。

## 配置

插件只读取自己的 `CODEX_MNEMOSYNE_*` 变量，Mnemosyne 的原生变量原样传递。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CODEX_MNEMOSYNE_BANK` | 先读 `MNEMOSYNE_MCP_BANK`，否则 `default` | Mnemosyne bank。 |
| `CODEX_MNEMOSYNE_AUTHOR_ID` | `codex` | 作者身份。 |
| `CODEX_MNEMOSYNE_SCOPE` | `global` | 自动写入使用 `global` 或 `session`。 |
| `CODEX_MNEMOSYNE_STATE_DIR` | `PLUGIN_DATA`，否则 `~/.codex/mnemosyne` | Hook outbox 和 cursor，不是 Mnemosyne 数据库。 |
| `CODEX_MNEMOSYNE_RECALL_TOP_K` | `5` | 每次召回的最多条数。 |
| `CODEX_MNEMOSYNE_RECALL_MAX_CHARS` | `6000` | 注入上下文的最大长度。 |
| `CODEX_MNEMOSYNE_AUTO_RECALL` | `true` | 开启 SessionStart/UserPromptSubmit 自动召回。 |
| `CODEX_MNEMOSYNE_AUTO_CAPTURE` | `true` | 开启 Stop/PreCompact/SessionEnd 自动捕获。 |
| `CODEX_MNEMOSYNE_AUTO_TOOL_CAPTURE` | `true` | 开启高信号 PostToolUse 观察。 |
| `CODEX_MNEMOSYNE_EXTRACT` | `false` | 向 Mnemosyne 传递 `extract=True`。 |
| `CODEX_MNEMOSYNE_EXTRACT_ENTITIES` | `false` | 向 Mnemosyne 传递 `extract_entities=True`。 |

Mnemosyne 数据库路径仍由 `MNEMOSYNE_DATA_DIR` 和 Mnemosyne 自己的 bank resolver 决定。插件不绑定任何本机路径。

## 隐私与失败策略

- 自动写入前会过滤常见 `secret`、API key、token、password、Bearer 和私钥模式。
- 不保存完整工具输出，也不保存 Codex 注入的 system/context 内容。
- 召回和写回均有限长；短确认语句会跳过。
- Hook 失败采用 fail-open，始终以退出码 `0` 返回，不阻塞 Codex。
- 写入失败会保留在本地 JSONL outbox，后续生命周期事件会重试。
- outbox 是明文文件，请放在受保护的本地目录，不要提交或公开同步。

## 测试

测试使用临时目录和 fake Mnemosyne 边界，不访问用户真实数据库，也不访问网络：

```bash
cd /Users/dmego/vibeCoding/codex-mnemosyne
PYTHONPATH=src python3 -m unittest discover -v
python3 -m compileall -q src bin
```

## 手动 hook smoke

```bash
printf '%s\n' '{"session_id":"demo","cwd":"/tmp/demo","prompt":"如何处理构建失败？"}' \
  | python3 bin/mnemosyne-hook.py UserPromptSubmit
```

如果当前 Python 环境没有 Mnemosyne，命令会安全退出且不输出记忆上下文。

## 设计参考

生命周期和队列设计参考了 [memX](https://github.com/NeoLi00/memX) 与 [codex-honcho](https://github.com/plastic-labs/codex-honcho) 的 Codex 集成，同时使用 Mnemosyne 自己的混合召回、去重、实体/事实提取、scope、veracity、trust tier 和 sleep 能力。
