# Codex Model Badges · 会话模型图标

适用于 macOS 和原生 Windows 的 ChatGPT 桌面端里的**本地 Codex 会话**。插件等 Codex 生成标题，再把模型 emoji 加到标题前。切换模型、开启或关闭 Fast 后，如果当前客户端将设置写入本地会话，插件会更新同一段前缀。会话标题正文会保留。

例如同一个会话可以依次显示为：

- ☀️ 整理项目需求
- ☀️ ⚡ 整理项目需求
- 🌍 整理项目需求

| 图标 | 模型或速度 |
| --- | --- |
| ☀️ | GPT-6.1 Sol |
| 🌍 | GPT-6.1 Terra |
| ✨ | GPT-6 Astra |
| 🌞 | GPT-6 Sol |
| 🌙 | GPT-6 Luna |
| 🧩 | 其他模型 |
| ⚡ | Fast |
| 🚀 | Ultrafast |

其他图标的映射可在 `plugins/codex-model-badges/hooks/codex_model_badges.py` 的 `ICONS` 中查看。

## 安装

需要支持本地插件及 Hooks 的 ChatGPT 桌面端、近期版本的 Codex CLI，以及 Python 3.9 或更新版本。

- macOS 版优先使用桌面端自带的 Codex CLI，Hook 用 `python3` 启动。
- Windows 版用原生 Codex 环境运行。请在 PowerShell 中确认 `codex --version` 和 `py -3 --version` 均可用，再重开 ChatGPT 让它读取更新后的环境变量。 [Windows 安装说明](https://learn.chatgpt.com/docs/app/windows)

**从 GitHub 安装**

```sh
codex plugin marketplace add zhanggzzy/codex-model-badges
codex plugin add codex-model-badges@local-model-badges
```

**从 ZIP 安装**

从 [GitHub Releases](https://github.com/zhanggzzy/codex-model-badges/releases/latest) 下载插件 ZIP 并解压。在终端进入解压后的 `codex-model-badges` 目录，运行以下命令。

```sh
codex plugin marketplace add "$PWD"
codex plugin add codex-model-badges@local-model-badges
```

在 macOS 上，如果终端找不到 `codex`，可以将命令中的 `codex` 替换为桌面端内置 CLI 的完整路径 `"/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"`。在 Windows 上，独立 CLI 可以按官方文档安装。 [Windows CLI 安装说明](https://learn.chatgpt.com/docs/enterprise/windows-deployment)

重新打开桌面端，在 Codex 的 **设置 → Hooks** 中审阅并信任这个插件的 Hooks。新建一个本地会话并发送首条消息，等待原生标题出现。也可以在已有会话里发一条消息以纳入监视。

从 v0.1.0 升级时，GitHub 安装可以用 `codex plugin marketplace upgrade local-model-badges` 刷新来源，再重新运行安装命令。ZIP 安装请解压新版，更新插件源目录中的文件并重新运行安装命令。重开桌面端并审阅更新后的 Hooks。

## 更新时机

插件通过本地 Codex App Server 保存标题。运行中的会话写入新设置后，插件通常会在几秒内更新保存的标题。部分桌面版本的侧栏可能缓存旧标题，切换或重新打开该会话可查看。较旧版本可能要等下一轮消息才保存模型或 Fast 设置。监视在会话结束或闲置一小时后停止，下次发送消息时恢复。

插件适用于本地 Codex。普通 ChatGPT Chat、云端会话以及从未打开的历史会话不在监视范围内。会话记录在本机处理，标题操作走本地接口。

## 卸载

```sh
codex plugin remove codex-model-badges@local-model-badges
codex plugin marketplace remove local-model-badges
```

已保存的图标属于会话标题，可通过桌面端的重命名功能移除。

[Codex Hooks](https://learn.chatgpt.com/docs/hooks) · [本地插件打包](https://developers.openai.com/plugins/build/plugins) · [Codex App Server](https://learn.chatgpt.com/docs/app-server)
