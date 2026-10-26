"""promptgarden —— 管理一组提示词变体并比较它们的表现。

设计原则：
1. **同一把尺子**。所有变体跑同一批输入，否则对照没有意义。
2. **离线可用**。不接后端，先在小样本上把话说明白，再去跑昂贵的评测。
3. **一次改一处**。同时改两个变体，就分不清是谁起的作用。

仅依赖 Python 标准库。

用法:
    python promptgarden.py --help
    python promptgarden.py --list --garden garden.json
    python promptgarden.py --run --garden garden.json --inputs inputs.jsonl
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# 花园结构
# ---------------------------------------------------------------------------

# 变体集合：
# {
#   "inputs": ["i1", ...],              # 固定输入集
#   "variants": {
#     "v1": {"prompt": "...", "note": "基线", "runs": {"i1": "输出"}},
#     "v2": {"prompt": "...", "note": "改写", "runs": {"i1": "输出"}},
#   }
# }


def load_garden(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"读不了花园文件 {path}：{e}") from e
    if not isinstance(data, dict):
        raise ValueError("花园文件应该是一个 JSON 对象")
    data.setdefault("variants", {})
    data.setdefault("inputs", [])
    return data


def save_garden(path: str, garden: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(garden, f, ensure_ascii=False, indent=2)


def load_inputs(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except OSError as e:
        raise ValueError(f"读不了输入文件 {path}：{e}") from e
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败：{e}") from e
        return [x for x in data if isinstance(x, dict)]

    rows: list[dict] = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"第 {lineno} 行 JSON 解析失败：{e}") from e
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


# ---------------------------------------------------------------------------
# 对照
# ---------------------------------------------------------------------------

# 输出的相似度：字符集合的 Jaccard
def similarity(a: str, b: str) -> float:
    na, nb = set((a or "").strip()), set((b or "").strip())
    if not na or not nb:
        return 1.0 if na == nb else 0.0
    return len(na & nb) / len(na | nb)


def compare_variants(garden: dict) -> dict:
    """比较各变体在固定输入集上的表现。"""
    variants = garden.get("variants") or {}
    if len(variants) < 2:
        return {"comparable": False,
                "reason": "至少要两个变体才能对照",
                "variants": list(variants)}

    input_ids = garden.get("inputs") or []
    names = sorted(variants)

    # 各变体的输出（按输入 id 取）
    runs: dict[str, dict[str, str]] = {}
    for name in names:
        runs[name] = (variants[name] or {}).get("runs") or {}

    # 覆盖率
    coverage = {}
    for name in names:
        if input_ids:
            covered = sum(1 for i in input_ids if i in runs[name])
            coverage[name] = round(covered / len(input_ids), 4)
        else:
            coverage[name] = 1.0 if runs[name] else 0.0

    # 两两对比
    comparisons: list[dict] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            common = [k for k in (input_ids or list(runs[a])) if k in runs[a] and k in runs[b]]
            sims = [similarity(runs[a][k], runs[b][k]) for k in common]
            avg = sum(sims) / len(sims) if sims else None
            # 输出完全相同的条数
            identical = sum(1 for k in common if runs[a][k] == runs[b][k])
            comparisons.append({
                "a": a, "b": b,
                "common_inputs": len(common),
                "avg_similarity": round(avg, 4) if avg is not None else None,
                "identical": identical,
                "differing": len(common) - identical,
                "coverage_a": coverage[a],
                "coverage_b": coverage[b],
            })

    # 相对基线（第一个变体）的一致度
    baseline = names[0]
    baseline_deltas = []
    for name in names[1:]:
        common = [k for k in (input_ids or list(runs[baseline]))
                  if k in runs[baseline] and k in runs[name]]
        sims = [similarity(runs[baseline][k], runs[name][k]) for k in common]
        avg = sum(sims) / len(sims) if sims else None
        baseline_deltas.append({
            "variant": name,
            "baseline": baseline,
            "avg_similarity": round(avg, 4) if avg is not None else None,
            "compared_inputs": len(common),
            "identical": sum(1 for k in common if runs[baseline][k] == runs[name][k]),
        })

    # 输出长度（长度变化常是改动的副作用）
    lengths = {}
    for name in names:
        vals = [len(v) for v in runs[name].values()]
        lengths[name] = round(sum(vals) / len(vals), 1) if vals else None

    # 提示词之间的差异：改了哪几块
    prompt_diffs = []
    for name in names[1:]:
        prompt_diffs.append({
            "variant": name,
            "baseline": baseline,
            "blocks_changed": compare_prompts(
                (variants[baseline] or {}).get("prompt", ""),
                (variants[name] or {}).get("prompt", "")),
        })

    return {
        "comparable": True,
        "variants": names,
        "input_count": len(input_ids),
        "coverage": coverage,
        "comparisons": comparisons,
        "baseline_deltas": baseline_deltas,
        "avg_output_len": lengths,
        "prompt_diffs": prompt_diffs,
        "summary": {
            "variant_count": len(names),
            "input_count": len(input_ids),
            "avg_similarity": (round(
                sum(c["avg_similarity"] for c in comparisons
                    if c["avg_similarity"] is not None)
                / max(1, len([c for c in comparisons
                              if c["avg_similarity"] is not None])), 4)
                if comparisons else None),
            "incomplete_coverage": [n for n, c in coverage.items() if c < 1.0],
        },
    }


def compare_prompts(old: str, new: str) -> dict:
    """比两版提示词差了几块。

    「块」按对齐后的差异段算：一行被改写算一块，不算两行。
    """
    old_lines = [l for l in (old or "").splitlines() if l.strip()]
    new_lines = [l for l in (new or "").splitlines() if l.strip()]
    old_set, new_set = set(old_lines), set(new_lines)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    changed = sum(1 for tag in matcher.get_opcodes() if tag[0] != "equal")

    return {
        "added": sorted(new_set - old_set),
        "removed": sorted(old_set - new_set),
        "unchanged": len(old_set & new_set),
        "changed_count": changed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render(result: dict) -> str:
    out: list[str] = []
    if not result.get("comparable"):
        out.append(f"没法对照：{result.get('reason', '')}")
        if result.get("variants"):
            out.append(f"现有变体：{', '.join(result['variants'])}")
        return "\n".join(out)

    s = result["summary"]
    out.append("提示词变体对照")
    out.append("=" * 60)
    out.append(f"变体 {s['variant_count']} 个 ｜ 固定输入集 {s['input_count']} 条")
    out.append("")

    out.append("输入集覆盖率：")
    for name, cov in result["coverage"].items():
        flag = "  ★没跑全" if cov < 1.0 else ""
        out.append(f"  {name:<12} {cov:.1%}{flag}")
    out.append("")

    out.append("与基线的差异：")
    for d in result["baseline_deltas"]:
        out.append(f"  {d['baseline']} ↔ {d['variant']}")
        out.append(f"    对比输入 {d['compared_inputs']} 条 ｜ "
                   f"平均相似度 {d['avg_similarity']} ｜ "
                   f"完全相同 {d['identical']} 条")
    out.append("")

    out.append("平均输出长度：")
    for name, ln in result["avg_output_len"].items():
        out.append(f"  {name:<12} {ln}")
    out.append("")

    out.append("提示词本身的改动：")
    for d in result["prompt_diffs"]:
        cd = d["blocks_changed"]
        out.append(f"  {d['baseline']} → {d['variant']}："
                   f"改了 {cd['changed_count']} 块")
        for line in cd["added"]:
            out.append(f"    + {line}")
        for line in cd["removed"]:
            out.append(f"    - {line}")
    out.append("")

    if s["incomplete_coverage"]:
        out.append(f"★ 覆盖率不足的变体：{', '.join(s['incomplete_coverage'])}")
        out.append("  覆盖不全的对照不能当作结论——先把输入集跑齐。")
    out.append("")
    out.append("注：相似度是字符层面的近似，不等于语义等价。")
    return "\n".join(out).rstrip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="promptgarden",
        description="管理一组提示词变体并比较它们的表现（仅依赖标准库）",
        epilog=(
            "花园文件：\n"
            "  {\"inputs\":[\"i1\",\"i2\"],\"variants\":{\"v1\":{\"prompt\":\"...\","
            "\"runs\":{\"i1\":\"...\"}}, \"v2\":{...}}}\n"
            "  python promptgarden.py --garden garden.json --list\n"
            "  python promptgarden.py --garden garden.json --compare\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--garden", required=True, help="花园文件路径")
    ap.add_argument("--list", action="store_true", help="列出变体")
    ap.add_argument("--compare", action="store_true", help="对照各变体")
    ap.add_argument("--add", help="新增变体名")
    ap.add_argument("--prompt", help="新增变体的提示词")
    ap.add_argument("--note", default="", help="变体备注")
    ap.add_argument("--set-inputs", help="从文件读入固定输入集")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    try:
        garden = load_garden(args.garden)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    # 新增变体
    if args.add:
        if not args.prompt:
            print("--add 需要 --prompt。", file=sys.stderr)
            return 2
        garden.setdefault("variants", {})[args.add] = {
            "prompt": args.prompt,
            "note": args.note,
            "runs": {},
        }
        try:
            save_garden(args.garden, garden)
        except OSError as e:
            print(f"写不了花园文件：{e}", file=sys.stderr)
            return 2
        print(f"已新增变体 {args.add}")

    # 设置固定输入集
    if args.set_inputs:
        try:
            rows = load_inputs(args.set_inputs)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        ids = []
        for i, r in enumerate(rows):
            ids.append(str(r.get("id") or f"i{i + 1}"))
        garden["inputs"] = ids
        try:
            save_garden(args.garden, garden)
        except OSError as e:
            print(f"写不了花园文件：{e}", file=sys.stderr)
            return 2
        print(f"已设置固定输入集 {len(ids)} 条")

    variants = garden.get("variants") or {}

    if args.list:
        if args.json:
            print(json.dumps({
                "variants": {k: {"note": (v or {}).get("note", ""),
                                 "prompt_preview": str((v or {}).get("prompt", ""))[:120],
                                 "runs": len((v or {}).get("runs") or {})}
                             for k, v in variants.items()},
                "inputs": garden.get("inputs", []),
            }, ensure_ascii=False, indent=2))
        else:
            out: list[str] = []
            out.append(f"固定输入集：{len(garden.get('inputs') or [])} 条")
            out.append("")
            for name in sorted(variants):
                v = variants[name] or {}
                runs = len(v.get("runs") or {})
                out.append(f"{name}")
                out.append(f"  备注：{v.get('note', '')}")
                out.append(f"  提示词：{str(v.get('prompt', ''))[:100]}")
                out.append(f"  已跑：{runs} 条")
            print("\n".join(out))
        return 0

    if args.compare:
        result = compare_variants(garden)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(render(result))
        return 0

    if not args.add and not args.set_inputs:
        print("需要 --list 或 --compare（--add / --set-inputs 可与它们搭配）。",
              file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
