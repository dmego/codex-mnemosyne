# codex-mnemosyne 设计

## 目标

把 Mnemosyne 从 Codex 中的“模型主动调用 MCP 工具”升级为可安装的 Codex 原生插件：在每轮用户输入前自动召回相关记忆，在 agent 响应后自动捕获高信号内容，并保持 MCP 作为需要时的手动深度查询/管理入口。

## 非目标

- 不修改 Mnemosyne Python 包、MCP server 或数据库 schema。
- 不接管 Codex 自带 `~/.codex/memories`，也不把 Codex 原生 Memories 改造成 Mnemosyne 后端。
- 不绑定本机的 Python 路径、数据目录、bank 名称、embedding 服务或 API URL。
- 不把每次 shell 输出、完整 transcript 或秘密凭据写入长期记忆。

## 参考实现与取舍

- `memX` 证明了 Codex plugin manifest + native hooks 可以实现每轮召回和 turn 捕获。
- `codex-honcho` 提供了 transcript 增量游标、PostToolUse 低噪声观察、Stop/PreCompact 写回和本地队列的成熟结构。
- `mem9-claude-plugin` 提供了简单的 SessionStart 自动加载和 Stop 自动保存策略，但它是 Claude-only 且使用云端 Mem9。
- `opencode-mnemosyne` 和 `dsh-Mnemosyne` 分别面向 OpenCode、DeepSeek Harness，不能直接复用宿主接入层。

本项目采用这些实现的生命周期设计，但把后端适配替换为 Mnemosyne SDK；MCP 不参与自动路径，避免模型决策、工具 approval 和 MCP router 延迟影响生命周期。

## 生命周期设计

```text
SessionStart / resume / clear / compact
  -> Mnemosyne.get_context()
  -> 限制条数和字符数
  -> hookSpecificOutput.additionalContext

UserPromptSubmit
  -> Mnemosyne.recall(prompt, top_k)
  -> 过滤空结果、去重、限制字符数
  -> hookSpecificOutput.additionalContext

PostToolUse
  -> 只保留编辑、测试、构建、版本控制写操作等高信号观察
  -> JSONL outbox，禁止网络/LLM 调用

Stop / PreCompact / SessionEnd
  -> 读取 transcript 增量
  -> 丢弃 Codex 注入的 system/context/tool 噪声
  -> 选取最新 user + assistant 结果，长度/秘密过滤
  -> 写入 outbox 并在生命周期允许时 flush
  -> Mnemosyne.remember(...)
```

`Stop` 是主要捕获点；`PreCompact` 负责在上下文压缩前保存增量；`SessionEnd` 作为最后 flush 机会。所有 hook 都 fail-open：Mnemosyne 未安装、配置缺失、数据库锁或 embedding 失败时返回空输出，不阻塞 Codex。

## Mnemosyne 适配

适配层延迟导入 `mnemosyne`，并通过环境变量解析配置：

1. `CODEX_MNEMOSYNE_BANK`
2. `MNEMOSYNE_MCP_BANK`
3. `default`

`MNEMOSYNE_DATA_DIR` 等 Mnemosyne 原生环境变量保持由调用环境决定。每个会话使用稳定的 `session_id`，作者默认为 `codex`，项目通过短目录名写入 metadata 和查询提示，不把绝对路径写进记忆。

自动写入默认使用 `scope=global`、`source=codex-auto`、`trust_tier=EXTERNAL_WRITE`，并支持通过环境变量切换 scope、importance、`extract`、`extract_entities`、`veracity`。Mnemosyne 自带的精确去重、混合 FTS/vector recall、结构化 fact/entity extraction 和 `sleep` consolidation 保持可用；插件不自行复制这些逻辑。

## 低噪声与安全策略

- 召回默认最多 5 条、总长度 6KB；单条记忆最多 1.5KB。
- 自动捕获只保存至少 80 个字符、最多 12KB 的最新 assistant 结果；短确认、纯问候和明显的工具噪声跳过。
- 通过内置正则过滤 API key、token、密码、cookie、Bearer、私钥块等；过滤规则可配置但默认严格。
- PostToolUse 只记录非只读 shell 命令、编辑器工具、测试/构建命令；不记录 Mnemosyne 自身调用。
- outbox 文件放在可配置的 Codex 状态目录，使用原子追加和单进程 lock；写入失败保留队列供下一个 hook 重试。
- hook 输出只在 SessionStart/UserPromptSubmit 返回 `hookSpecificOutput`；写回和观察 hook 不向用户/模型输出日志。

## 插件边界

仓库根目录是 Codex marketplace；可安装插件位于 `plugins/codex-mnemosyne/`：

```text
.agents/plugins/marketplace.json                    # marketplace 清单
plugins/codex-mnemosyne/.codex-plugin/plugin.json   # Codex manifest
plugins/codex-mnemosyne/hooks/hooks.json            # 生命周期映射
plugins/codex-mnemosyne/bin/mnemosyne-hook.py       # stdin JSON -> JSON stdout
plugins/codex-mnemosyne/src/codex_mnemosyne/        # 配置、适配、transcript、队列、格式化
plugins/codex-mnemosyne/skills/mnemosyne-memory/    # 手动深度操作与自动行为说明
plugins/codex-mnemosyne/tests/                     # 不依赖真实 Mnemosyne 服务
```

运行时只依赖 Python 3.10+ 标准库；真实 hook 执行时要求所选 Python 环境可导入 `mnemosyne`。测试通过内存 fake adapter 验证插件契约，不触碰用户数据库。

## 验收标准

1. `plugin.json` 可被 Codex 识别并声明 hooks/skills。
2. SessionStart 和 UserPromptSubmit 对有效记忆返回正确的 `hookSpecificOutput.additionalContext`，空库不产生输出。
3. transcript 解析不会把 `<environment_context>`、工具调用或 system 注入写入记忆。
4. Stop/PreCompact/SessionEnd 只捕获新 assistant 内容，重复 hook 不产生重复 outbox 条目。
5. secrets、短响应、只读工具事件被过滤；Mnemosyne 异常不会让 hook 失败退出。
6. 既有用户 hooks 不会被插件文件覆盖；安装说明明确要求合并/信任 hooks。
7. 单元测试、脚本 smoke 测试和静态编译检查全部通过。
