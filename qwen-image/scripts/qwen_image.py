#!/usr/bin/env python3
"""Qwen-Image 文生图：调 DashScope 原生接口生成图片并自动下载落盘。

仅依赖 Python 3 标准库。API Key 从环境变量 DASHSCOPE_API_KEY 读取。
"""

import argparse
import datetime
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"


def build_body(args):
    params = {
        "size": args.size,
        "n": args.n,
        "prompt_extend": not args.no_extend,
        "watermark": args.watermark,
    }
    if args.negative:
        params["negative_prompt"] = args.negative
    if args.seed is not None:
        params["seed"] = args.seed
    return {
        "model": args.model,
        "input": {
            "messages": [
                {"role": "user", "content": [{"text": args.prompt}]}
            ]
        },
        "parameters": params,
    }


def call_api(body, key):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"API HTTP {e.code}：{detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"网络错误：{e.reason}", file=sys.stderr)
        sys.exit(1)


def extract_urls(data):
    urls = []
    for choice in data.get("output", {}).get("choices", []):
        for item in choice.get("message", {}).get("content") or []:
            if "image" in item:
                urls.append(item["image"])
    return urls


def download(urls, outdir, stem):
    outdir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, url in enumerate(urls, 1):
        dest = outdir / f"{stem}-{i}.png"
        try:
            with urllib.request.urlopen(url, timeout=120) as resp, open(dest, "wb") as f:
                f.write(resp.read())
        except (urllib.error.URLError, OSError) as e:
            print(f"下载失败（URL 24h 内有效，可手动下载）：{url}\n原因：{e}", file=sys.stderr)
            sys.exit(1)
        saved.append(dest)
    return saved


def main():
    parser = argparse.ArgumentParser(description="Qwen-Image 文生图（DashScope 原生接口）")
    parser.add_argument("prompt", help="正向提示词，支持中文")
    parser.add_argument("--model", default="qwen-image-3.0-pro")
    parser.add_argument("--size", default="2048*2048", help='宽*高，如 2688*1536')
    parser.add_argument("-n", type=int, default=1, help="生成张数")
    parser.add_argument("--negative", help="反向提示词，≤500 字符")
    parser.add_argument("--no-extend", action="store_true", help="关闭提示词智能改写，细节可控")
    parser.add_argument("--watermark", action="store_true", help="加 Qwen-Image 水印")
    parser.add_argument("--seed", type=int, help="随机种子")
    parser.add_argument("--out", help="输出目录，默认 ~/workspace/temp/yyyyMMdd")
    parser.add_argument("--name", default="qwen-image", help="输出文件名前缀")
    args = parser.parse_args()

    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        print(
            "错误：未设置 DASHSCOPE_API_KEY。\n"
            "设置方式：echo 'export DASHSCOPE_API_KEY=sk-xxx' >> ~/.zshrc && source ~/.zshrc\n"
            "API Key 在阿里云百炼控制台获取。",
            file=sys.stderr,
        )
        sys.exit(2)

    data = call_api(build_body(args), key)

    # DashScope 个别错误走 HTTP 200 藏 code 字段，防御性检查
    if data.get("code"):
        print(f"API 错误 {data.get('code')}：{data.get('message')}", file=sys.stderr)
        sys.exit(1)

    urls = extract_urls(data)
    if not urls:
        print(f"响应中没有图片 URL：{json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        sys.exit(1)

    today = datetime.date.today()
    outdir = pathlib.Path(args.out).expanduser() if args.out else (
        pathlib.Path.home() / "workspace" / "temp" / today.strftime("%Y%m%d")
    )
    stem = f"{args.name}-{today.strftime('%Y%m%d-%H%M%S')}"

    saved = download(urls, outdir, stem)
    for path in saved:
        print(f"已保存：{path}")
    usage = data.get("usage") or {}
    if usage:
        print(f"尺寸 {usage.get('width')}x{usage.get('height')}，张数 {usage.get('image_count')}")


if __name__ == "__main__":
    main()
