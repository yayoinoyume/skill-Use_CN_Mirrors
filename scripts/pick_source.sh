#!/usr/bin/env bash
# pick_source.sh — 国内网络环境下的源测速与选择（临时换源，不改任何配置文件）
#
# 用法:
#   pick_source.sh <目标名> [pick|bench]
#     目标名: npm / pypi / go / cargo / github / ubuntu ...（见 data/mirrors.json 的 targets 键，支持别名）
#     pick （默认）: 输出选中源的 URL
#     bench       : 输出各存活源吞吐测速明细（tag 速度 字节每秒）
#
# 阶段一: 官方源+全部候选 并行探测（2秒超时）；官方源活着 → 容差优先直接用官方。
# 阶段二: 官方死了 → 对延迟最低的前 3 名存活源串行真实下载测速（8秒/源，吞吐量定胜负）。
#
# 安全红线:
#   - 带凭据的请求永不走镜像/代理
#   - 代理只对单条命令临时挂，绝不写全局环境变量
#   - 探测输出丢弃到 /dev/null，不留任何临时文件
set -u
TIMEOUT_PROBE=2
TIMEOUT_BENCH=8
FINALISTS=3
UA="cn-mirrors/1.0"

DATA="$(cd "$(dirname "$0")/.." && pwd)/data/mirrors.json"
CFG="$HOME/.config/cn-mirrors/config.json"

command -v curl >/dev/null || { echo "需要 curl" >&2; exit 1; }
command -v python3 >/dev/null || { echo "需要 python3（仅用于读 JSON）" >&2; exit 1; }
[[ -f "$DATA" ]] || { echo "缺少数据文件: $DATA" >&2; exit 1; }

TARGET="${1:?用法: pick_source.sh <目标名> [pick|bench]}"
ACTION="${2:-pick}"

# 候选列表：官方源 + chsrc 镜像 + 用户 xget 节点（应用 targets 覆盖）
CANDIDATES=$(python3 - "$TARGET" "$DATA" "$CFG" << 'PY'
import json, sys
target, data_path, cfg_path = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(data_path))
cfg = {}
try: cfg = json.load(open(cfg_path))
except Exception: pass
t = d['targets'].get(target)
if t is None:
    for k, v in d['targets'].items():
        if target in k.split('/'):
            t = v; break
if t is None:
    sys.exit(23)
xc, tovr = d.get('xget_platforms', {}), (cfg.get('targets') or {}).get(target) or {}
disabled = set(tovr.get('disabled_sources') or [])
pref = tovr.get('preferred_source') or ''
out = []
for s in t['sources']:
    tag = 'official' if s['role'] == 'upstream' else (s.get('code') or s.get('sym') or 'mirror')
    if tag in disabled:
        continue
    out.append({'tag': tag, 'url': s['url'], 'speed_url': s.get('speed_url'),
                'priority': 0 if tag == pref else 1, 'kind': 'direct'})
for node in (cfg.get('xget_nodes') or []):
    for s in t['sources']:
        if s['role'] != 'upstream':
            continue
        for pfx, up in xc.items():
            upn = up.rstrip('/')
            if s['url'].rstrip('/').startswith(upn):
                xurl = node.rstrip('/') + '/' + pfx + s['url'].rstrip('/')[len(upn):]
                out.append({'tag': 'xget', 'url': xurl, 'speed_url': None,
                            'priority': 0 if pref.startswith('xget') else 1, 'kind': 'xget'})
                break
print(json.dumps(out, ensure_ascii=False))
PY
) || { echo "未知目标: $TARGET" >&2; exit 23; }

# 阶段一：并行探测（后台任务无法回传变量，结果统一写入 PROBEFILE 再读回）
PROBEFILE=$(mktemp); CANDFILE=$(mktemp); LIST=$(mktemp); RESULT=$(mktemp)
trap 'rm -f "$CANDFILE" "$PROBEFILE" "$LIST" "$RESULT"' EXIT
python3 -c "
import json,sys
for c in json.loads(sys.argv[1]): print(c['tag'], c['url'])
" "$CANDIDATES" > "$CANDFILE"
probe() {  # $1=tag $2=url
  local r
  r=$(curl -sS -m "$TIMEOUT_PROBE" -o /dev/null -I -L -w "%{http_code} %{time_total}" -A "$UA" "$2" 2>/dev/null) || return
  local code=${r%% *}
  [[ "$code" =~ ^(200|301|302|307|308)$ ]] && echo "$1 ${r#* } $2" >> "$PROBEFILE"
}
pids=()
while read -r tag url; do
  probe "$tag" "$url" & pids+=($!)
done < "$CANDFILE"
for p in "${pids[@]}"; do wait "$p" 2>/dev/null; done

declare -A PROBE
while read -r tag rest; do
  [[ -n "$tag" ]] && PROBE[$tag]="$rest"
done < "$PROBEFILE"

# 阶段二专用: 存活源按延迟排序取前 N
finalists() {
  for tag in "${!PROBE[@]}"; do
    echo "${PROBE[$tag]%% *} $tag"
  done | sort -n | head -n "$FINALISTS"
}

# 官方容差优先
if [[ -n "${PROBE[official]:-}" && "$ACTION" != "bench" ]]; then
  echo "${PROBE[official]#* }"
  exit 0
fi

# 阶段二：串行真实下载测速，吞吐量定胜负
bench_one() {  # $1=url $2=专用测速URL（可空）
  local u="${2:-$1}" r code sp
  r=$(curl -sSL -m "$TIMEOUT_BENCH" -o /dev/null -w "%{http_code} %{speed_download}" \
        --speed-time 15 --speed-limit 10240 -A "$UA" "$u" 2>/dev/null)
  # 退出码28=超时截断，此时 -w 的结果依然有效，只要 r 非空就用
  [[ -z "$r" ]] && { echo 0; return; }
  code=${r%% *}; sp=${r#* }
  [[ "$code" == 2* && -n "$sp" && "$sp" != "0.000" && "$sp" != "0" ]] && echo "$sp" || echo 0
}

finalists > "$LIST"
while read -r tt tag; do
  url=${PROBE[$tag]#* }
  sp=$(python3 -c "
import json,sys
for c in json.loads(sys.argv[1]):
    if c['tag']=='$tag': print(c.get('speed_url') or '')
" "$CANDIDATES")
  echo "$(bench_one "$url" "$sp") $tag" >> "$RESULT"
done < "$LIST"

if [[ "$ACTION" == "bench" ]]; then
  sort -rn "$RESULT"
  exit 0
fi

WINNER=$(sort -rn "$RESULT" | head -1 | cut -d' ' -f2-)
[[ -n "${PROBE[$WINNER]:-}" ]] || exit 2   # 全部测速失败
echo "${PROBE[$WINNER]#* }"
