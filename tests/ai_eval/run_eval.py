"""AI 评测（T3.5、AC-26）：python scripts/manage.py eval --mode fallback | model

- fallback：不调用模型，直接走降级路径（规则解析器、模板），结果确定、可复现；
- model：调用真实的 DeepSeek，需要在 .env 中配置密钥（本脚本不打印密钥）。
结果写入 tests/ai_eval/results/<mode>.json（不含耗时等每次都会变的字段，便于比对两次运行是否一致）。
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

from app.ai import generator, nl_filter
from app.ai.client import AiFailure, DeepSeekClient
from app.clock import to_db
from app.config import TAG_LIBRARY, get_settings
from app.services import content_validator

HERE = Path(__file__).resolve().parent
TARGETS = {"model": {"filter": 0.8}, "fallback": {"filter": 0.5}}
FACT_RULES = {"DATE_MISMATCH", "TIME_MISMATCH", "COUNT_MISMATCH"}


class NoModelClient:
    """降级模式：不访问网络，直接触发降级。"""
    model = None

    def complete_json(self, system, user, temperature):
        raise AiFailure("NO_KEY")


def _norm(cond: dict) -> dict:
    return {k: (sorted(v) if k == "tags" else v) for k, v in cond.items()}


def eval_filter(client, cfg) -> dict:
    spec = json.loads((HERE / "cases_filter.json").read_text(encoding="utf-8"))
    today = date.fromisoformat(spec["today"])
    cases = []
    for case in spec["cases"]:
        r = nl_filter.parse(client, case["query"], today, cfg)
        ok = _norm(r["conditions"]) == _norm(case["expected"])
        cases.append({"id": case["id"], "query": case["query"], "expected": case["expected"],
                      "actual": r["conditions"], "pass": ok, "mode": r["mode"], "reason": r["reason"]})
    passed = sum(c["pass"] for c in cases)
    return {"cases": cases, "passed": passed, "total": len(cases), "accuracy": round(passed / len(cases), 4)}


def _compliant(content: dict, cfg) -> bool:
    return (bool(content["summary"]) and len(content["summary"]) <= cfg.summary_max_len
            and cfg.tags_min <= len(content["tags"]) <= cfg.tags_max
            and all(t in TAG_LIBRARY for t in content["tags"])
            and len(content["notes"]) <= cfg.notes_max_items
            and all(len(n) <= cfg.note_max_len for n in content["notes"]))


def eval_generate(client, cfg) -> dict:
    spec = json.loads((HERE / "cases_generate.json").read_text(encoding="utf-8"))
    cases = []
    for case in spec["cases"]:
        fields = {**case, "start_at": to_db(datetime.fromisoformat(case["start_at"])),
                  "end_at": to_db(datetime.fromisoformat(case["end_at"]))}
        r = generator.generate(client, fields, cfg)
        content = r["content"]
        issues = content_validator.validate(content["summary"], content["notes"], fields, cfg)
        conflicts = [i["message"] for i in issues if i["rule"] in FACT_RULES]
        cases.append({"id": case["id"], "title": case["title"], "mode": r["mode"], "reason": r["reason"],
                      "compliant": _compliant(content, cfg), "conflicts": conflicts, "output": content})
    compliant = sum(c["compliant"] for c in cases)
    return {"cases": cases, "compliant": compliant, "total": len(cases),
            "compliance_rate": round(compliant / len(cases), 4),
            "conflict_count": sum(len(c["conflicts"]) for c in cases)}


def main(mode: str) -> int:
    cfg = get_settings()
    if mode == "model":
        if not cfg.ai_enabled:
            print("[eval] 未配置 DEEPSEEK_API_KEY，无法运行 model 模式；可先运行 --mode fallback。")
            print("       已在 .env 中配置却仍出现此提示时，检查当前终端是否设置了同名环境变量（环境变量优先于 .env）：")
            print("       PowerShell 执行 Test-Path Env:DEEPSEEK_API_KEY 查看，Remove-Item Env:DEEPSEEK_API_KEY 删除")
            return 2
        client = DeepSeekClient(cfg)
    else:
        client = NoModelClient()

    filt, gen = eval_filter(client, cfg), eval_generate(client, cfg)
    target = TARGETS[mode]["filter"]
    print(f"== AI 评测（mode={mode}）==")
    print("-- 自然语言筛选")
    for c in filt["cases"]:
        tag = "PASS" if c["pass"] else "FAIL"
        src = c["mode"] if c["reason"] in (None, "NO_KEY") or mode == "fallback" else f"{c['mode']}/{c['reason']}"
        print(f"  {c['id']} {tag} [{src}] {c['query']}  实际={json.dumps(c['actual'], ensure_ascii=False)}")
    print("-- 内容生成")
    for c in gen["cases"]:
        src = c["mode"] if c["reason"] is None or mode == "fallback" else f"{c['mode']}/{c['reason']}"
        print(f"  {c['id']} {'合规' if c['compliant'] else '不合规'} 冲突 {len(c['conflicts'])} [{src}] {c['title']}"
              + (f"  {c['conflicts']}" if c["conflicts"] else ""))
    print("-- 汇总")
    print(f"  筛选条件解析完全正确率：{filt['passed']}/{filt['total']} = {filt['accuracy']:.1%}"
          f"（目标 ≥ {target:.0%}）{'达标' if filt['accuracy'] >= target else '未达标'}")
    print(f"  生成内容结构合规率：{gen['compliant']}/{gen['total']} = {gen['compliance_rate']:.1%}"
          f"（目标 100%）{'达标' if gen['compliance_rate'] == 1 else '未达标'}")
    print(f"  生成内容事实冲突数：{gen['conflict_count']}（目标 0）{'达标' if gen['conflict_count'] == 0 else '未达标'}")

    out = HERE / "results" / f"{mode}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"mode": mode, "filter": filt, "generate": gen}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"  结果文件：{out.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "fallback"))
