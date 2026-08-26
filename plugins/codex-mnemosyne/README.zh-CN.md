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

自动路径直接导入 Mnemosyne SDK。插件同时捆绑一个可选的 `mnemosyne` MCP server：需要手动管理记忆时，Codex 会从插件根目录的 `.mcp.json` 启动它。自动召回和写回不依赖模型主动调用 MCP；即使 MCP 依赖未安装，自动路径仍然可以工作。

MCP 暴露 Mnemosyne 3.12.x 的完整 36 个工具面：记忆写入/混合召回、批处理、统计与
sleep、更新/失效/删除、导入导出、诊断、scratchpad、canonical self-facts、时间三元组、
graph、shared surface、sync、persona 和 hygiene。Mnemosyne 3.12.x 的上游 server 会发布
36 个 schema 但少注册 8 个 handler；插件 bridge 通过上游公开 dispatcher 转发已注册工具，
并独立实现缺失/修正的 handler，不修改用户已安装的 Mnemosyne 包。sync 未配置远端时会返回
`not_configured`，不会伪造同步成功。

## 要求

- 支持 Codex plugin lifecycle hooks，并批准插件信任。
- Hook 使用 Python 3.10+。
- Hook 选择的 Python 环境能够导入 `mnemosyne`。
- 若要启用捆绑 MCP，该环境还需要 `mcp`（通常安装 Mnemosyne 的 MCP extra）。
- 插件本身不要求网络；embedding 和结构化 extraction 是否联网由 Mnemosyne 自己的配置决定。

Hook 入口（`bin/mnemosyne-hook.py`；手动运行也可用 `bin/mnemosyne-hook` 启动器）会
自动选择能够导入 Mnemosyne 的解释器，优先检查 `CODEX_MNEMOSYNE_PYTHON`、插件自己的
`.venv`、Mnemosyne CLI 的 shebang、PATH 中的 Python 和 macOS 常见 Conda 路径。需要
固定解释器时可显式设置：

```bash
export CODEX_MNEMOSYNE_PYTHON=/opt/anaconda3/bin/python
```

请把 Mnemosyne 安装到该解释器环境：

```bash
python3 -m pip install "mnemosyne>=3.11.1,<4"

# 手动 MCP 工具所需（自动 hooks 不需要 mcp）
python3 -m pip install "mnemosyne[mcp]>=3.11.1,<4"
```

如果你使用的是 Mnemosyne 源码 checkout，请先在该环境安装源码，并确保
hook 调用的解释器能够找到它。插件不会捆绑 Mnemosyne 及其可选的
embedding/LLM 依赖；SDK 不可用时会 fail-open。

检查 Codex 实际会使用哪个解释器和 SDK：

```bash
bin/mnemosyne-doctor
```

诊断报告会显示 Python、Mnemosyne 导入路径/版本、bank、状态/数据目录以及已发现的
SDK 方法；它也会显示 MCP 依赖是否可导入。普通 Hook 仍会 fail-open，但 doctor 会明确报告
SDK 是否不可用。

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

启用后重启 Codex 并批准 hooks；新会话才会加载更新后的 MCP server。不要覆盖已有的
`~/.codex/hooks.json`，插件 hooks 应与用户 hooks 合并。更新本地 checkout 时，使用
`read_marketplace_name.py`、`update_plugin_cachebuster.py` 和 `codex plugin add` 的正常插件
更新流程，不要手工改 `~/.codex/config.toml`。

## 配置

插件只读取自己的 `CODEX_MNEMOSYNE_*` 变量，Mnemosyne 的原生变量原样传递。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CODEX_MNEMOSYNE_BANK` | 先读 `MNEMOSYNE_MCP_BANK`，否则 `default` | Mnemosyne bank。 |
| `CODEX_MNEMOSYNE_PYTHON` | 自动探测 | 可选的 Hook Python 解释器路径。 |
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
| `CODEX_MNEMOSYNE_DIAGNOSTICS` | `false` | 在插件状态目录写入不含内容的生命周期诊断 `diagnostics.jsonl`。 |

MCP 使用 Mnemosyne 原生变量 `MNEMOSYNE_MCP_BANK`（若未设置则回退到
`CODEX_MNEMOSYNE_BANK`），因此手动工具与自动 hooks 可以路由到同一 bank。数据库路径仍由
`MNEMOSYNE_DATA_DIR`/`HERMES_HOME` 和 Mnemosyne 自己的 bank resolver 决定。

Codex 官方支持的插件作用域 MCP 配置主要控制启用状态和工具策略，嵌套 `env` 不一定会被
注入 stdio 子进程。因此本插件的 Hook 和 MCP 启动器会额外读取下面这个配置块，并与进程环境
合并（进程环境优先）：

```toml
[plugins."codex-mnemosyne@codex-mnemosyne".mcp_servers.mnemosyne.env]
MNEMOSYNE_MCP_BANK = "coding"
MNEMOSYNE_AUTHOR_ID = "codex"
```

如果手动定义了顶层 MCP server，也接受 `[mcp_servers.mnemosyne.env]`。实际解析到的配置来源
可用 `bin/mnemosyne-doctor` 查看。

Mnemosyne 数据库路径仍由 `MNEMOSYNE_DATA_DIR` 和 Mnemosyne 自己的 bank resolver 决定。插件不绑定任何本机路径。
自动召回会按当前项目路径的稳定 hash 做 channel 过滤，默认不会返回其他项目捕获的记忆；路径本身不会写入 channel 值。

## 隐私与失败策略

- 自动写入前会过滤常见 `secret`、API key、token、password、Bearer 和私钥模式。
- 不保存完整工具输出，也不保存 Codex 注入的 system/context 内容。
- 召回和写回均有限长；短确认语句会跳过。
- Hook 失败采用 fail-open，始终以退出码 `0` 返回，不阻塞 Codex。
- 写入失败会保留在本地 JSONL outbox，后续生命周期事件会重试。
- outbox 是明文文件，请放在受保护的本地目录，不要提交或公开同步。
- 开启诊断后只记录事件名、无路径会话/项目标识、上下文长度、队列计数和 SDK 可用性；不会
  记录 prompt、回答、记忆内容、cwd 或密钥。

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
  | bin/mnemosyne-hook UserPromptSubmit
```

如果所有候选 Python 都没有 Mnemosyne，命令会安全退出且不输出记忆上下文；用
`bin/mnemosyne-doctor` 可以区分“bank 为空”和“SDK 不可用”。

### MCP stdio smoke

插件的 `.mcp.json` 使用 `./bin/mnemosyne-mcp`。它会选择同时能导入 `mnemosyne` 和 `mcp`
的 Python，然后执行 Mnemosyne 原生 stdio MCP server：

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | bin/mnemosyne-mcp
```

## 设计参考

生命周期和队列设计参考了 [memX](https://github.com/NeoLi00/memX) 与 [codex-honcho](https://github.com/plastic-labs/codex-honcho) 的 Codex 集成，同时使用 Mnemosyne 自己的混合召回、去重、实体/事实提取、scope、veracity、trust tier 和 sleep 能力。
