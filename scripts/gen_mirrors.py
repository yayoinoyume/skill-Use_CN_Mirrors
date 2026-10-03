#!/usr/bin/env python3
"""从 chsrc 源码提取镜像源数据，生成 mirrors.json。

维护者用法：
  python3 gen_mirrors.py --chsrc-dir <chsrc源码目录> --xget-catalog <platform-catalog.js> -o ../data/mirrors.json
  python3 gen_mirrors.py --refresh   # 自动下载 chsrc main 与 xget 平台表后重新生成

只使用 Python 3 标准库。
"""
import argparse
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

CHSRC_TARBALL = "https://codeload.github.com/RubyMetric/chsrc/tar.gz/refs/heads/main"
XGET_CATALOG = "https://raw.githubusercontent.com/xixu-me/Xget/main/src/config/platform-catalog.js"

# 上游提供者符号，不算镜像
UPSTREAM_SYMS = {"UpstreamProvider", "UpstreamProviderPlus"}

# ---------------------------------------------------------------- mirror.c 解析

STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


MIRROR_BLOCK_RE = re.compile(r"\b([A-Z]\w*)\s*=\s*\n?\{", re.M)


def parse_mirrors(c_text: str, mirrors: dict | None = None) -> dict:
    """解析 C 源码中的 MirrorSite_t 定义（mirror.c 与 recipe 文件都可能含），合并进 mirrors。"""
    mirrors = {} if mirrors is None else dict(mirrors)
    text = strip_c_comments(c_text)
    for m in MIRROR_BLOCK_RE.finditer(text):
        sym = m.group(1)
        if sym in UPSTREAM_SYMS or sym in mirrors:
            continue
        # 找配对右括号
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[m.end():i]
        strings = STR_RE.findall(body)
        if len(strings) < 4:
            continue
        urls = [x for x in strings if x.startswith(("http://", "https://")) and "\n" not in x]
        entry = {
            "code": strings[0],
            "abbr": strings[1],
            "name": strings[2],
            "site": strings[3],
            "speed_url": next((u for u in urls if u != strings[3]), None),
        }
        mirrors[sym] = entry
    return mirrors


# ---------------------------------------------------------------- recipe 解析

DISH_RE = re.compile(r'def_(?:sources_only_)?dish\s*\(\s*\w+\s*,\s*"([^"]+)"')
SOURCE_LINE_RE = re.compile(r'\{\s*&(\w+)\s*,\s*"([^"]*)"')
SM_POSTFIX_RE = re.compile(r'chef_set_rest_smURL_with_postfix\s*\(\s*this\s*,\s*"([^"]*)"')
NOTE_RE = re.compile(r'//\s*(.+?)\s*$')


def parse_recipe(path: Path, mirrors: dict) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    dish_m = DISH_RE.search(text)
    if not dish_m:
        return None
    dish = dish_m.group(1)

    # 提取 def_sources_begin() 到 def_sources_end() 之间的源定义
    begin = text.find("def_sources_begin()")
    end = text.find("def_sources_end()")
    if begin == -1 or end == -1:
        return None
    body = text[begin:end]

    sources = []
    notes = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        # 收集行内注释作为备注
        if stripped.startswith("//"):
            note = stripped.lstrip("/ ").strip()
            if note and "&" not in note and "}" not in note:
                notes.append(note)
            continue
        sm = SOURCE_LINE_RE.search(line)
        if not sm:
            inline = NOTE_RE.search(stripped)
            if inline and sources and "&" not in inline.group(1) and "}" not in inline.group(1):
                notes.append(inline.group(1))
            continue
        sym, url = sm.group(1), sm.group(2)
        if not url.startswith("http"):
            continue
        # 行内注释从匹配终点之后找，避免命中 URL 里的 https://
        inline_note = None
        comment_idx = line.find("//", sm.end())
        if comment_idx != -1:
            inline_note = line[comment_idx + 2:].strip().strip("/*").strip() or None
        if sym in UPSTREAM_SYMS:
            sources.append({"role": "upstream", "url": url, "note": inline_note})
        elif sym in mirrors:
            m = mirrors[sym]
            sources.append({
                "role": "mirror",
                "sym": sym,
                "code": m["code"],
                "name": m["name"],
                "url": url,
                "speed_url": m.get("speed_url"),
                "note": inline_note,
            })
        else:
            sources.append({
                "role": "mirror",
                "sym": sym,
                "code": sym.lower(),
                "name": sym,
                "url": url,
                "speed_url": None,
                "note": inline_note,
            })

    if not any(s["role"] == "mirror" for s in sources):
        return None

    # 专用测速后缀：拼在官方源 URL 后（chsrc 的做法）
    sm_postfix = SM_POSTFIX_RE.search(text)
    speed_postfix = sm_postfix.group(1) if sm_postfix else None

    return {"dish": dish, "file": path.name, "speed_postfix": speed_postfix,
            "notes": notes[:10], "sources": sources}


# ---------------------------------------------------------------- xget 目录

def parse_xget_catalog(js_text: str) -> dict:
    """解析 xget 的 PLATFORM_CATALOG，返回 前缀 -> 官方URL"""
    m = re.search(r"export const PLATFORM_CATALOG\s*=\s*\{", js_text)
    if not m:
        raise ValueError("platform-catalog.js 中找不到 PLATFORM_CATALOG")
    depth, i = 0, m.end() - 1
    for i in range(m.end() - 1, len(js_text)):
        if js_text[i] == "{":
            depth += 1
        elif js_text[i] == "}":
            depth -= 1
            if depth == 0:
                break
    body = js_text[m.end():i]
    catalog = {}
    for key, url in re.findall(r"['\"]?([\w-]+)['\"]?\s*:\s*'([^']+)'", body):
        catalog[key] = url
    return catalog


# ---------------------------------------------------------------- 主流程

def load_inputs(chsrc_dir: Path | None, xget_path: Path | None):
    import tarfile
    import tempfile
    tmp = None
    if chsrc_dir is None:
        tmp = tempfile.mkdtemp(prefix="chsrc-")
        tar_path = Path(tmp) / "chsrc.tar.gz"
        print(f"下载 chsrc main ...", file=sys.stderr)
        urllib.request.urlretrieve(CHSRC_TARBALL, tar_path)
        with tarfile.open(tar_path) as tf:
            tf.extractall(tmp)
        chsrc_dir = next((Path(tmp) / d for d in Path(tmp).iterdir() if d.name.startswith("chsrc-")))
    if xget_path is None:
        xget_path = Path(tmp or tempfile.mkdtemp(prefix="xget-")) / "platform-catalog.js"
        print(f"下载 xget 平台表 ...", file=sys.stderr)
        urllib.request.urlretrieve(XGET_CATALOG, xget_path)
    return chsrc_dir, xget_path, tmp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chsrc-dir", type=Path, default=None)
    ap.add_argument("--xget-catalog", type=Path, default=None)
    ap.add_argument("-o", "--output", type=Path, default=Path(__file__).parent.parent / "data" / "mirrors.json")
    ap.add_argument("--refresh", action="store_true", help="联网拉取最新 chsrc 与 xget 数据后生成")
    args = ap.parse_args()

    tmp = None
    if args.refresh:
        args.chsrc_dir = args.xget_catalog = None
    chsrc_dir, xget_path, tmp = load_inputs(args.chsrc_dir, args.xget_catalog)

    try:
        mirror_c = (chsrc_dir / "src" / "framework" / "mirror.c").read_text(encoding="utf-8", errors="replace")
        mirrors = parse_mirrors(mirror_c)
        recipe_dirs = [chsrc_dir / "src" / "recipe" / "lang", chsrc_dir / "src" / "recipe" / "os", chsrc_dir / "src" / "recipe" / "ware"]
        recipe_files = [p for rd in recipe_dirs for p in sorted(rd.rglob("*.c"))
                        if p.name not in ("common.h", "rawstr4c.h") and "rawstr4c" not in p.name]
        for rf in recipe_files:
            mirrors = parse_mirrors(rf.read_text(encoding="utf-8", errors="replace"), mirrors)
        print(f"解析到 {len(mirrors)} 个镜像站定义", file=sys.stderr)

        targets = {}
        for path in recipe_files:
            try:
                t = parse_recipe(path, mirrors)
            except Exception as e:
                print(f"  跳过 {path.name}: {e}", file=sys.stderr)
                continue
            if t:
                targets[t["dish"]] = t

        xget = parse_xget_catalog(xget_path.read_text(encoding="utf-8", errors="replace"))
        print(f"解析到 {len(xget)} 个 xget 平台前缀", file=sys.stderr)

        # 把 chsrc 未覆盖的 xget 平台补成合成目标：
        # 仅当键名不存在、且不与任何现有键的别名段冲突时才创建（chsrc 已覆盖的平台绝不重复/遮蔽）
        rename = {'gh': 'github', 'gl': 'gitlab', 'sf': 'sourceforge', 'hf': 'huggingface',
                  'aosp': 'aosp', 'arxiv': 'arxiv', 'fdroid': 'fdroid', 'jenkins': 'jenkins',
                  'civitai': 'civitai', 'gist': 'gist'}
        existing_segments = {seg for k in targets for seg in k.split('/')}
        for pfx, up in xget.items():
            key = rename.get(pfx, pfx)
            if key in targets or key in existing_segments:
                continue
            targets[key] = {
                'dish': key, 'file': '(xget)', 'speed_postfix': None, 'notes': [f'来自 xget 平台表，前缀 {pfx}'],
                'sources': [{'role': 'upstream', 'url': up + '/', 'note': None}],
            }

        out = {
            "_meta": {
                "description": "国内镜像源数据，由 scripts/gen_mirrors.py 从 chsrc 与 xget 上游提取。勿手改，用 --refresh 更新。",
                "generated_on": __import__("datetime").date.today().isoformat(),
                "chsrc": "https://github.com/RubyMetric/chsrc (GPL-3.0)",
                "xget": "https://github.com/xixu-me/Xget (AGPL-3.0)",
                "target_count": len(targets),
            },
            "targets": targets,
            "xget_platforms": xget,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"写出 {args.output}：{len(targets)} 个换源目标", file=sys.stderr)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
