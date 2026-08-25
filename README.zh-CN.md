# codex-mnemosyne

这是一个开源 Codex 插件仓库，把 Mnemosyne 接入 Codex 原生生命周期。

可安装插件位于 [`plugins/codex-mnemosyne`](./plugins/codex-mnemosyne)，仓库根目录本身也是 Codex marketplace，清单位于 [`.agents/plugins/marketplace.json`](./.agents/plugins/marketplace.json)。

## 从 GitHub 安装

```bash
codex plugin marketplace add https://github.com/dmego/codex-mnemosyne.git
codex plugin list --marketplace codex-mnemosyne --available
codex plugin add codex-mnemosyne@codex-mnemosyne
```

本地开发时可以把 GitHub 地址替换为 checkout 路径：

```bash
codex plugin marketplace add /Users/dmego/vibeCoding/codex-mnemosyne
```

然后新建 Codex thread，启用插件并审核/信任插件 hooks。仓库不会修改用户已有的 `~/.codex/hooks.json`。

## 插件内容

- 原生 Codex hooks：自动执行 `SessionStart`/`UserPromptSubmit` 召回，以及 `Stop`/`PreCompact`/`SessionEnd` 写回。
- 仅使用 Python 标准库的 Mnemosyne SDK 适配层，包含上下文限长、secret 过滤、持久 outbox 和 fail-open。
- 用于显式记忆管理流程的 bundled skill。
- 可选 MCP 共存：用于人工深度搜索、修正、失效、删除、诊断和 consolidation。

配置、隐私边界、测试和“自动路径 vs 人工路径”的能力划分见 [`plugins/codex-mnemosyne/README.md`](./plugins/codex-mnemosyne/README.md)。
