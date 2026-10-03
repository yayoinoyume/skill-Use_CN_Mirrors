# 各生态临时换源命令模板

原则：只改单条命令，不写任何配置。`<源URL>` 来自 `pick_source.sh` 的输出。
镜像同步有延迟：新发布的包在镜像 404 时回退官方源。

## Node.js / npm

```bash
npm install --registry=<源URL> <包名>
# 查看当前 registry: npm config get registry
```

## Python / pip

```bash
pip install --index-url <源URL> <包名>
# 清华/上交等镜像的 simple 页可能带 /web/simple 后缀，直接用 pick 输出的 URL 即可
```

## Go

```bash
GOPROXY=<源URL>,direct go get <包名>
GOPROXY=<源URL>,direct go mod download   # 整个模块树
```

## Rust / cargo

cargo 无命令级 registry 覆盖，用环境变量且仅限单条命令：

```bash
CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse \
CARGO_HOME=/tmp/cargo-mirror-home cargo install <crate名>
# 或下载 .crate 文件直装：
# 用 pick_source.sh rust 得到镜像 URL 后: curl -O <镜像URL>/crates/<name>/<version>/download
```

## Maven / Gradle

```bash
mvn dependency:go-offline -Dmaven.repo.remote=<源URL>
# Gradle 单项目: gradle -DmavenRepoUrl=<源URL> ...（多数构建脚本支持 -P 覆盖，视项目而定）
```

## GitHub（clone / release / raw）

chsrc 无 GitHub 目标。用户配置了 xget 节点时：

```bash
# clone: 把域名换成 xget 节点 + /gh 前缀
git clone https://xget.example.com/gh/owner/repo.git
# release 文件: https://xget.example.com/gh/owner/repo/releases/download/v1.0/file.zip
# raw: https://xget.example.com/gh/owner/repo/raw/main/file.txt
```

未配置节点时可用公共镜像前缀（如 ghfast.top/https://github.com/...），仅限无凭据的公开仓库。

## 容器镜像

```bash
# 拉取后重打 tag，不改 daemon.json（xget: /cr/docker/ 前缀；或国内 registry 镜像）
docker pull <xget节点>/cr/docker/library/alpine:latest
docker tag  <xget节点>/cr/docker/library/alpine:latest alpine:latest
```

## git clone 走代理（最后兜底，仅单条命令）

```bash
https_proxy=http://host:port git clone https://github.com/owner/repo.git
```

## 大文件下载（带看门狗与 .part 规范）

```bash
curl -fL --speed-time 15 --speed-limit 10240 -o file.tar.gz.part <URL> \
  && mv file.tar.gz.part file.tar.gz
rm -f file.tar.gz.part   # 失败时
```
