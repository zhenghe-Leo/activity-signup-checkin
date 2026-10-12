"""数据库初始化与演示种子数据（NFR-02、AC-29、01-spec §7.1）。

- init_database：数据库已初始化时跳过，不清库。
- reset_database：在一个写事务内删表、重建、导入种子数据（03 §7.3）。
活动时间全部相对 reset 时刻生成，任何时候 reset 后都能演示。种子数据不写操作日志。
"""
from datetime import datetime, time, timedelta, tzinfo

from app import db
from app.clock import to_db
from app.config import Settings
from app.repo import activities, registrations, users

# (id, 名称, 角色, 年级)。名称带上 01-spec 中的编号，演示时与验收标准对应。
ACCOUNTS = [
    (1, "O1 王老师", "organizer", None),
    (2, "S1 李明", "student", "大三"),
    (3, "S2 王芳", "student", "大三"),
    (4, "S3 张伟", "student", "大四"),
    (5, "S4 刘洋", "student", "大二"),
    (6, "S5 陈静", "student", "大四"),
    (7, "S6 赵磊", "student", "大一"),
]
ORGANIZER = 1
S1, S2, S3, S4, S5, S6 = 2, 3, 4, 5, 6, 7

# 01-spec §7.1 第 6 类：普通活动（标题, 地点, 标签, 名额, 距今天数, 开始时刻）
REGULAR = [
    ("人工智能前沿学术讲座", "图书馆报告厅", ["学术", "讲座"], 50, 2, 14),
    ("校友后端面试经验分享", "信息楼 201", ["讲座", "就业"], 80, 3, 19),
    ("社区敬老院志愿服务", "幸福里社区", ["志愿服务"], 15, 4, 9),
    ("校园马拉松", "东区田径场", ["文体"], 300, 5, 8),
    ("摄影社团招新见面会", "学生活动中心 305", ["社团"], 40, 6, 18),
    ("Python 数据分析培训", "实验楼 B402", ["培训", "学术"], 30, 8, 14),
    ("ACM 程序设计竞赛校选赛", "实验楼 A101", ["竞赛"], 60, 9, 9),
    ("春季校园招聘双选会", "体育馆", ["就业"], 500, 12, 9),
    ("书画作品展", "艺术馆一楼", ["展览", "文体"], 200, 15, 10),
]


def seed(conn, now: datetime, tz: tzinfo, demo_activities: bool = True) -> None:
    """demo_activities=False 时只导入账号（自动化测试用，避免演示数据干扰断言）。"""
    for user_id, name, role, grade in ACCOUNTS:
        users.insert_user(conn, user_id, name, role, grade)
    if not demo_activities:
        return

    ts = to_db(now)
    today = now.astimezone(tz).date()

    def day_at(days: int, hour: int) -> datetime:
        return datetime.combine(today + timedelta(days=days), time(hour), tzinfo=tz)

    def add(title, location, tags, capacity, start, *, hours=2, deadline=None, status="PUBLISHED",
            summary="", notes=()):
        fields = {
            "title": title, "location": location, "tags": list(tags), "capacity": capacity,
            "start_at": to_db(start), "end_at": to_db(start + timedelta(hours=hours)),
            "deadline_at": to_db(deadline or start - timedelta(days=1)),
            "summary": summary or f"{title}，欢迎同学们参加。", "notes": list(notes),
        }
        activity_id = activities.insert(conn, fields, ORGANIZER, ts)
        if status != "DRAFT":
            activities.set_published(conn, activity_id, ts)
        return activity_id

    def enroll(activity_id, registered=(), waitlisted=()):
        for sid in registered:
            registrations.insert(conn, activity_id, sid, "REGISTERED", ts)
        for seq, sid in enumerate(waitlisted, start=1):
            registrations.insert(conn, activity_id, sid, "WAITLISTED", ts, wait_seq=seq)

    # 1. 报名中、名额 2、无人报名：名额未满 → 满员进入候补 → 取消后递补（AC-01~03）
    add("【演示】职业规划讲座", "图书馆报告厅", ["讲座", "就业"], 2, day_at(3, 14))

    # 2. 签到窗口内、已有 3 人报名（另有 S4 候补）：签到与重复签到（AC-10~12）
    a2 = add("【演示】数据库原理学术报告", "信息楼 101", ["学术", "讲座"], 3,
             now + timedelta(minutes=10), deadline=now - timedelta(hours=1))
    enroll(a2, registered=(S2, S3, S5), waitlisted=(S4,))

    # 3. 已截止、未开始、已满且有候补：截止后拒绝新报名、允许取消并继续递补（AC-08）
    a3 = add("【演示】校园摄影展志愿者招募", "艺术馆", ["志愿服务", "展览"], 2,
             day_at(1, 10) if day_at(1, 10) > now + timedelta(hours=2) else day_at(2, 10),
             deadline=now - timedelta(hours=1))
    enroll(a3, registered=(S1, S2), waitlisted=(S3,))

    # 4. 草稿：AI 生成与发布（AC-20~22）；简介、标签、注意事项留空
    activities.insert(conn, {
        "title": "Go 后端面试经验分享会", "location": "图书馆报告厅", "capacity": 100,
        "start_at": to_db(day_at(7, 14)), "end_at": to_db(day_at(7, 16)),
        "deadline_at": to_db(day_at(6, 18)),
    }, ORGANIZER, ts)

    # 5. 已取消：S1 的记录随活动取消，出现在 S1 的「我的报名」中（AC-13）
    a5 = add("校园歌手大赛初赛", "大学生活动中心", ["竞赛", "文体"], 100, day_at(5, 19))
    enroll(a5, registered=(S1,))
    reg = registrations.get(conn, a5, S1)
    registrations.cancel(conn, reg["id"], "BY_ACTIVITY", ts)
    registrations.notify(conn, reg["id"], "活动已取消：校园歌手大赛初赛", ts)
    activities.set_cancelled(conn, a5, ts)

    # 6. 普通活动：不同标签和日期，用于搜索与自然语言筛选；其中一个已满（AC-24「仅看有余量」）
    for title, location, tags, capacity, days, hour in REGULAR:
        add(title, location, tags, capacity, day_at(days, hour))
    full = add("AI 前沿讲座（名额已满）", "图书馆报告厅", ["讲座", "学术"], 1, day_at(2, 19))
    enroll(full, registered=(S6,))


def init_database(settings: Settings, now: datetime, demo_activities: bool = True) -> bool:
    """返回 True 表示本次新建；False 表示已存在、已跳过。"""
    settings.db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
    try:
        db.enable_wal(conn)
        with db.write_tx(conn):
            if db.has_schema(conn):
                return False
            db.create_schema(conn)
            seed(conn, now, settings.tz, demo_activities)
        return True
    finally:
        conn.close()


def reset_database(settings: Settings, now: datetime, demo_activities: bool = True) -> None:
    settings.db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
    try:
        db.enable_wal(conn)
        # 删表期间关闭外键检查；PRAGMA foreign_keys 在事务内设置无效，必须在事务外
        conn.execute("PRAGMA foreign_keys = OFF")
        with db.write_tx(conn):
            db.drop_schema(conn)
            db.create_schema(conn)
            seed(conn, now, settings.tz, demo_activities)
        conn.execute("PRAGMA foreign_keys = ON")
    finally:
        conn.close()
