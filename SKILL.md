---
name: cn-mirrors
description:
  国内网络环境下的临时换源与下载加速。当依赖/软件下载超时或极慢（npm/pip/go/cargo/maven
  等安装卡住）、git clone GitHub 仓库卡住、需要选择国内镜像源或使用 xget 节点加速、
  下载大文件需要测速选源时使用。只做命令级临时换源，不改任何系统/项目配置文件。
---

默认执行而非讲解：用户表达"帮我装 X / 下载 Y / clone Z"时直接执行并自验，只在该问时才问。

## 核心工作流（下载遇到网络问题时按序执行）

1. **先正常执行下载**，并挂 30 秒探测超时。失败/无进展的判定标准：
   - AI 亲手的 curl 下载：`curl --max-time 30 --speed-time 15 --speed-limit 10240`——30 秒未完成=失败；连续 15 秒平均速度 <10KB/s=无进展（提前掐死）。
   - 包管理器命令：优先用原生参数（npm `--fetch-timeout 30000 --fetch-retries 0`，git `-c http.lowSpeedLimit=10240 -c http.lowSpeedTime=15`），没有合适原生参数的（pip/go/cargo）套外层 `timeout 30`。
   - 判死之后先分类：**网络类失败**（超时/连接拒绝/DNS/HTTP 5xx/429）→ 进换源流程；**协议类失败**（404/401/403/校验失败）→ 不是源的问题，不换源，如实报告（404 多半是包名错，401/403 是凭据问题）。
   - 正常完成则流程结束。
2. **选源**：`scripts/pick_source.sh <目标> [pick|bench]`
   - `pick`：官方源活着 → 直接返回官方 URL（约 2 秒）；官方死了 → 对存活镜像串行真实下载测速（8 秒/源、最多 3 名），输出最快源 URL。
   - `bench`：输出各存活源吞吐明细（Byte/s），用于向用户展示选源依据。
   - 目标名见 `data/mirrors.json` 的 `targets` 键（支持别名，如 `cargo`、`pypi`、`github`）。
3. **用选中的源临时下载**（不写配置），按 `references/temp-switch.md` 的命令模板执行。
4. **失败回退链**：镜像上遇到 404/校验失败（可能是同步延迟）→ 回退官方源 → 官方仍失败且用户配置了代理 → 对单条命令临时挂代理。全部失败则如实告知用户。
5. **重试命令的硬顶**：选好快源后的重试命令，包管理器套 `timeout 300`（防止挂死，非等待判断——判活已在第 1 步的 30 秒内完成）；AI 亲手执行的下载继续用 curl 看门狗（15 秒粒度）+ `--max-time 300`。

## 两阶段测速原理（为什么这样设计）

- 阶段一并行探测只测"谁活着"（2 秒超时），官方源有容差优先权：活着就用官方。
- 阶段二串行测速量真实吞吐（探测测不出"通但极慢"的源；并行测速会抢带宽导致结果失真）。
- 真实下载一律挂看门狗 `curl --speed-time 15 --speed-limit 10240`（连续 15 秒低于 10KB/s 掐断）。超时分两层：探测层 `timeout 30`（判官方源死活，快速进入换源），硬顶层 `timeout 300`（只套在已选好源的重试命令上防挂死）。
- 失败文件不留痕：受控下载写 `.part`，成功才改名，掐断即删。

## 安全红线（必须遵守）

- 带 Authorization/Cookie/token/URL 内嵌凭据的请求**永不**走镜像或代理，强制官方直连。
- 代理只允许 `https_proxy=… <单条命令>` 形式，绝不写全局环境变量、shell 配置或 git config。
- 无校验和的可执行脚本不走镜像；有官方 SHA256 可校验的资产可走镜像。
- 永不永久改源（不碰 sources.list、daemon.json、npm config 等），除非用户明确要求永久换源且知悉后果。

## 用户配置（可选，缺失时只用 chsrc 数据）

`~/.config/cn-mirrors/config.json`：

```json
{
  "xget_nodes": ["https://xget.example.com"],
  "proxies": [{ "type": "http", "url": "http://host:port" }],
  "targets": {
    "npm": { "disabled_sources": ["tencent"], "preferred_source": "npmmirror" }
  }
}
```

- `xget_nodes`：私有 xget 节点列表，按平台前缀映射官方 URL 后与镜像一起进竞速池。
- `proxies`：仅作"竞速池全军覆没后连官方源"的兜底。
- `targets`：按目标禁用/偏好源（`preferred_source` 填源 code 或 `xget`）。

## 数据维护

- `data/mirrors.json` 由 `scripts/gen_mirrors.py` 从 chsrc（换源数据，GPL-3.0）与 xget 平台表（AGPL-3.0）上游提取，勿手改。
- 数据超过 3 个月或 chsrc/xget 有重要更新时：`python3 scripts/gen_mirrors.py --refresh`。

各生态临时换源命令模板见 [references/temp-switch.md](references/temp-switch.md)。
