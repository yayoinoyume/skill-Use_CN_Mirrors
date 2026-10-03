# cn-mirrors — 国内网络环境 AI 临时换源技能

一个面向编码 Agent 的技能（skill）：当依赖/软件下载超时或极慢时，自动测速选择最快的源，**以单条命令的方式临时换源**完成下载——不改任何系统或项目配置文件。

数据底座来自两个久经考验的上游：

- [chsrc](https://github.com/RubyMetric/chsrc)（GPL-3.0）：其 recipe 数据提供了 55+ 个换源目标（npm/PyPI/Go/cargo/apt…）对应的官方源与国内镜像列表，以及每个源的专用测速链接；
- [Xget](https://github.com/xixu-me/Xget)（AGPL-3.0）：提供 GitHub/HuggingFace/容器 registry 等约 40 类平台的加速前缀映射，用户可用自建节点参与竞速。

## 它解决什么问题

| 场景 | 没有 cn-mirrors | 有 cn-mirrors |
|---|---|---|
| `npm install` 卡在官方源 | 干等或手动换永久源 | 30 秒判死 → 自动选最快镜像 → 命令级换源重试 |
| `git clone` GitHub 卡住 | 反复重试 | 走用户自建 xget 节点竞速胜出后加速克隆 |
| 镜像上 404（同步延迟） | 换源后仍然失败困惑 | 自动回退官方源，不误判 |

## 安装

把本目录复制到 Agent 的技能目录即可，例如：

```bash
git clone https://github.com/yayoinoyume/skill-Use_CN_Mirrors.git ~/.agents/skills/cn-mirrors
```

运行依赖（全部开箱即用，零安装）：bash、curl、python3（仅用于读 JSON）、GNU coreutils。适用于 Linux 与 WSL2。

## 用户配置（可选）

不配置也能用（官方源 + chsrc 全部镜像竞速）。配置后可加入自建加速节点与代理兜底：

`~/.config/cn-mirrors/config.json`

```json
{
  "xget_nodes": ["https://xget.example.com"],
  "proxies": [{ "type": "http", "url": "http://host:port" }],
  "targets": {
    "npm": { "disabled_sources": ["tencent"], "preferred_source": "npmmirror" }
  }
}
```

- `xget_nodes`：自建 Xget 节点，按平台前缀映射官方 URL 后与镜像一起参与测速竞速；
- `proxies`：仅在所有源全部失败后，作为"临时挂单条命令连官方源"的最后兜底；
- `targets`：按目标禁用某镜像或固定偏好源（`preferred_source` 填源 code 或 `xget`）。

## 工作原理（两阶段测速）

```
下载失败/超时(30s探测层)
        │
        ▼
┌─ 阶段一：并行探测（2s 超时）─────────────┐
│  官方源活着 → 容差优先，直接用官方源        │
│  官方源死了 → 取延迟最低的前 3 名存活镜像   │
└──────────────────┬───────────────────┘
                   ▼
┌─ 阶段二：串行真实下载测速（8s/源）────────┐
│  按吞吐量（Byte/s）选出最快源              │
└──────────────────┬───────────────────┘
                   ▼
        命令级临时换源下载（300s 硬顶防挂死）
```

为什么不只做轻量探测：探测测不出"通但极慢"的源（实测存在 0.8s 响应却只有 136KB/s 的镜像）；为什么阶段二必须串行：并行测速会互相抢带宽，结果失真——与 chsrc 的测速方法论一致。

## 安全红线

- 带凭据（Authorization/Cookie/token）的请求**永不**走镜像或代理；
- 代理只允许挂在单条命令上，绝不写入全局环境变量；
- 无校验和的可执行脚本不走镜像；有官方 SHA256 的资产校验后才使用；
- 永不永久改源（不碰 sources.list、`.npmrc`、`daemon.json` 等）。

## 数据刷新

数据随仓库分发，一般无需手动更新。数据超过 3 个月或 chsrc/xget 有重要更新时：

```bash
python3 scripts/gen_mirrors.py --refresh
```

## 致谢与许可

- 换源数据提取自 [RubyMetric/chsrc](https://github.com/RubyMetric/chsrc)（GPL-3.0）；
- 平台前缀映射提取自 [xixu-me/Xget](https://github.com/xixu-me/Xget)（AGPL-3.0）；
- 本仓库的脚本与文档按同样许可精神开源分发，数据版权归各自上游。

---

## 附：推荐加入 AGENTS.md 的提示词片段

将以下片段加入你的 AGENTS.md（或全局系统提示），能让 Agent 在合适的时机主动、正确地使用本技能：

```markdown
## 国内镜像源（cn-mirrors skill）

- 当依赖/软件下载超时、极慢或 git clone 卡住时，使用 cn-mirrors 技能，不要反复裸重试，
  也不要建议用户永久换源。
- 标准动作：先带 30 秒探测超时正常执行下载 → 失败后运行
  `scripts/pick_source.sh <目标>` 选最快源 → 按临时换源命令模板重试（仅当条命令生效）。
- 换源后镜像 404/校验失败是同步延迟所致，回退官方源重试，不要继续换别的镜像。
- 404/401/403/校验失败等协议类错误不是源的问题：不换源，如实报告。
- 带凭据（token/Authorization）的请求永远直连官方源，禁止走任何镜像或代理。
- 代理只允许 `https_proxy=… <单条命令>` 临时形式，禁止写入环境变量或 git 配置。
- 用户自建 xget 节点与代理保存在 ~/.config/cn-mirrors/config.json，不要把节点地址
  写进代码、文档或提交。
```
