#!/usr/bin/env python3
"""Smoke-test a locally running vLLM OpenAI-compatible chat API.

Example:
    python test_vllm.py
    python test_vllm.py --prompt 'Giải thích self-attention' --max-tokens 256
    python test_vllm.py --base-url http://localhost:8000/v1 --model Qwen/Qwen3.5-9B
"""

import argparse
import sys
import time
from openai import OpenAI, OpenAIError


def parse_args():
    parser = argparse.ArgumentParser(description="Test Qwen3.5-9B inference using vLLM")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--prompt", default="Giải thích ngắn gọn: vLLM giúp tăng tốc inference LLM như thế nào?")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def main():
    args = parse_args()
    client = OpenAI(base_url=args.base_url, api_key="EMPTY", timeout=args.timeout)

    print(f"Server : {args.base_url}")
    print(f"Model  : {args.model}")
    print(f"Prompt : {args.prompt}\n")

    try:
        models = client.models.list()
        available = [m.id for m in models.data]
        print("[OK] Server reachable")
        print(f"Available models: {available}\n")
        if args.model not in available:
            print(f"[WARNING] Requested model '{args.model}' is not in the model list.")
            print("          Pass --model <exact-name> if the name differs.\n")
    except (OpenAIError, OSError) as exc:
        print(f"[ERROR] Cannot connect to vLLM server: {exc}", file=sys.stderr)
        print("Ensure 'vllm serve ...' is still running and port 8000 is accessible.", file=sys.stderr)
        return 1

    try:
        start = time.perf_counter()
        result = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": args.prompt}],
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        elapsed = time.perf_counter() - start
    except (OpenAIError, OSError) as exc:
        print(f"[ERROR] Inference request failed: {exc}", file=sys.stderr)
        return 1

    message = result.choices[0].message
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        print("=== Reasoning ===")
        print(reasoning.strip())
        print()

    print("=== Model response ===")
    print((message.content or "[empty content]").strip())

    usage = result.usage
    print("\n=== Metrics ===")
    print(f"Latency           : {elapsed:.2f} s (end-to-end)")
    print(f"Finish reason     : {result.choices[0].finish_reason}")
    if usage:
        print(f"Prompt tokens     : {usage.prompt_tokens}")
        print(f"Completion tokens : {usage.completion_tokens}")
        print(f"Total tokens      : {usage.total_tokens}")
        if elapsed > 0:
            print(f"Throughput        : {usage.completion_tokens / elapsed:.2f} output tokens/s (approx.)")
    else:
        print("Token usage unavailable from API response.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
