#!/usr/bin/env python3

import argparse
import json
import time

import mlx.core as mx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple MLX distributed all_sum benchmark")
    parser.add_argument("--backend", default="jaccl")
    parser.add_argument("--elements", type=int, default=8_388_608)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--iters", type=int, default=10)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    group = mx.distributed.init(strict=True, backend=args.backend)

    payload = mx.ones((args.elements,), dtype=mx.float32) * (group.rank() + 1)
    expected = float(sum(range(1, group.size() + 1)))

    for _ in range(args.warmup):
      reduced = mx.distributed.all_sum(payload, group=group)
      mx.eval(reduced)
      mx.synchronize()

    latencies_ms = []
    sample = None
    for _ in range(args.iters):
      start = time.perf_counter()
      reduced = mx.distributed.all_sum(payload, group=group)
      mx.eval(reduced)
      mx.synchronize()
      latencies_ms.append((time.perf_counter() - start) * 1000.0)
      sample = reduced

    observed = float(sample[0].item()) if sample is not None else 0.0
    result = {
        "backend": args.backend,
        "rank": group.rank(),
        "world_size": group.size(),
        "elements": args.elements,
        "tensor_bytes": args.elements * 4,
        "expected_first_value": expected,
        "observed_first_value": observed,
        "min_latency_ms": min(latencies_ms),
        "median_latency_ms": sorted(latencies_ms)[len(latencies_ms) // 2],
        "max_latency_ms": max(latencies_ms),
        "mean_latency_ms": sum(latencies_ms) / len(latencies_ms),
    }
    print(json.dumps(result, sort_keys=True))

    if abs(observed - expected) > 1e-5:
        raise SystemExit(
            f"Unexpected all_sum result on rank {group.rank()}: expected {expected}, got {observed}"
        )


if __name__ == "__main__":
    main()
