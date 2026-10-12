"""A1 降级模板：模型不可用时，用确定性的规则生成简介、标签、注意事项（BR-26、DEC-03）。

结果可复现：同样的输入总是得到同样的输出。不写具体日期、时刻、人数：描述中含数字的分句直接丢弃，
保证模板输出能通过 BR-22 事实一致校验。
"""
import re

from app.config import TAG_LIBRARY, Settings

# 关键词 → 标签（只用于降级模板；顺序即优先级）
TAG_KEYWORDS = {
    "讲座": ["讲座", "分享", "报告", "讲讲", "沙龙"],
    "竞赛": ["竞赛", "比赛", "大赛", "挑战赛"],
    "志愿服务": ["志愿", "公益", "义工"],
    "文体": ["运动", "体育", "跑", "球", "歌", "舞", "文艺", "演出"],
    "学术": ["学术", "科研", "论文", "研究", "技术"],
    "就业": ["就业", "求职", "面试", "招聘", "实习", "职业"],
    "社团": ["社团", "招新"],
    "培训": ["培训", "课程", "训练营", "教学"],
    "展览": ["展览", "展出", "画展", "作品展"],
}

GENERIC_NOTES = [
    "请按时到场，现场凭组织者公布的签到口令签到",
    "如无法参加，请提前在系统中取消报名，方便候补同学递补",
    "活动期间请遵守现场秩序，爱护公共设施",
]


def generate(title: str, description: str, cfg: Settings) -> dict:
    text = f"{title} {description}"
    tags = [tag for tag, words in TAG_KEYWORDS.items() if any(w in text for w in words)]
    tags = [t for t in tags if t in TAG_LIBRARY][: cfg.tags_max] or ["其他"]

    clauses = [c.strip() for c in re.split(r"[，。；！？,;!?\n]", description) if c.strip()]
    kept = [c for c in clauses if not re.search(r"\d", c)]
    body = "，".join(kept)
    summary = f"{title}：{body}。欢迎感兴趣的同学报名参加，具体时间和地点见活动信息。" if body else \
        f"{title}。欢迎感兴趣的同学报名参加，具体时间和地点见活动信息。"
    return {
        "summary": summary[: cfg.summary_max_len],
        "tags": tags,
        "notes": GENERIC_NOTES[: cfg.notes_max_items],
    }
