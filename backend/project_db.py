"""
Project Database Module - SQLite 项目数据库

一个项目文件夹 = 一个独立数据库文件，管理:
- projects (项目元数据)
- chapters (章节索引)
- memory_items (记忆条目)
- chat_messages (对话历史)
- stage_runs (阶段运行记录)
"""

import os
import re
import sqlite3
import json
import time
from datetime import datetime
from typing import List, Dict, Optional, Any, Union

# ============================================================
# Fernet 加密密钥管理
# ============================================================

_FERNET_INSTANCE = None


def _set_secret_key_permissions(path: str):
    """设置密钥文件权限为仅所有者可读写（0o600）。Windows 上仅记录警告。"""
    try:
        import stat
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError as e:
        # Windows 上 os.chmod 行为不同，仅记录
        import logging
        logging.getLogger(__name__).debug(f"Cannot set secret_key permissions: {e}")


def _check_secret_key_permissions(path: str):
    """启动时校验密钥文件权限，权限过宽则警告。"""
    if not os.path.exists(path):
        return
    try:
        import stat
        mode = os.stat(path).st_mode
        if mode & stat.S_IRWXG or mode & stat.S_IRWXO:
            import logging
            logging.getLogger(__name__).warning(
                f"[SECURITY] 密钥文件 {path} 权限过宽({oct(mode)})，建议设置为 0600"
            )
    except OSError:
        pass


def _get_fernet():
    """获取 Fernet 加密实例（单例）。

    密钥来源优先级：
    1. 环境变量 NOVEL_WORKSPACE_SECRET
    2. backend/.secret_key 文件
    3. 自动生成新密钥，保存到 .secret_key 并打印提示
    """
    global _FERNET_INSTANCE
    if _FERNET_INSTANCE is not None:
        return _FERNET_INSTANCE

    from cryptography.fernet import Fernet

    secret_key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")

    # 1. 从环境变量读取
    secret = os.environ.get("NOVEL_WORKSPACE_SECRET", "").strip()

    # 2. 从 .secret_key 文件读取
    if not secret and os.path.exists(secret_key_path):
        try:
            with open(secret_key_path, "r", encoding="utf-8") as f:
                secret = f.read().strip()
        except Exception:
            pass

    # 3. 生成新密钥
    if not secret:
        secret = Fernet.generate_key().decode("utf-8")
        try:
            with open(secret_key_path, "w", encoding="utf-8") as f:
                f.write(secret)
            _set_secret_key_permissions(secret_key_path)
            print(f"[SECURITY] 已生成新的加密密钥，保存到 {secret_key_path}")
            print(f"[SECURITY] 建议将以下密钥设置到环境变量 NOVEL_WORKSPACE_SECRET：")
            print(f"[SECURITY]   {secret}")
        except Exception as e:
            print(f"[SECURITY] 无法保存密钥文件: {e}")

    try:
        _FERNET_INSTANCE = Fernet(secret.encode("utf-8") if isinstance(secret, str) else secret)
    except Exception as e:
        print(f"[SECURITY] Fernet 密钥无效，将重新生成: {e}")
        secret = Fernet.generate_key().decode("utf-8")
        try:
            with open(secret_key_path, "w", encoding="utf-8") as f:
                f.write(secret)
            _set_secret_key_permissions(secret_key_path)
        except Exception:
            pass
        _FERNET_INSTANCE = Fernet(secret.encode("utf-8"))

    _check_secret_key_permissions(secret_key_path)
    return _FERNET_INSTANCE


def _encrypt_api_key(key: str, fernet=None) -> str:
    """加密 api_key。如果已经是 Fernet 密文（以 gAAAAA 开头），直接返回。"""
    if not key or not isinstance(key, str):
        return key
    # 已经是加密格式，跳过
    if key.startswith("gAAAAA"):
        return key
    try:
        f = fernet or _get_fernet()
        return f.encrypt(key.encode("utf-8")).decode("utf-8")
    except Exception:
        return key


def _decrypt_api_key(key: str, fernet=None) -> str:
    """解密 api_key。如果解密失败，返回原值（兼容未加密的旧数据）。"""
    if not key or not isinstance(key, str):
        return key
    # 不是加密格式，直接返回
    if not key.startswith("gAAAAA"):
        return key
    try:
        f = fernet or _get_fernet()
        return f.decrypt(key.encode("utf-8")).decode("utf-8")
    except Exception:
        return key

# ============================================================
# 基础路径配置
# ============================================================

WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")
PROJECTS_DIR = os.path.join(WORKSPACE_DIR, "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)

# ============================================================
# 全局认证数据库（auth.db）
# ============================================================

AUTH_DB_PATH = os.path.join(WORKSPACE_DIR, "auth.db")


def _get_auth_conn():
    """获取全局认证数据库连接"""
    os.makedirs(os.path.dirname(AUTH_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(AUTH_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TEXT DEFAULT ''
        )
    """)
    conn.commit()
    return conn


def get_user_by_username(username: str) -> Optional[Dict]:
    """根据用户名查询用户"""
    conn = _get_auth_conn()
    try:
        cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if row:
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
        return None
    finally:
        conn.close()


def create_user(username: str, password_hash: str, role: str = "user") -> int:
    """创建用户"""
    conn = _get_auth_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, role, datetime.now().isoformat())
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def count_users() -> int:
    """统计用户数"""
    conn = _get_auth_conn()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM users")
        return cur.fetchone()[0]
    finally:
        conn.close()


def init_default_admin():
    """初始化默认 admin 用户（仅在 users 表为空时）"""
    if count_users() > 0:
        return
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not admin_password:
        import secrets
        admin_password = secrets.token_urlsafe(16)
    password_hash = pwd_context.hash(admin_password)
    create_user("admin", password_hash, "admin")
    print(f"[AUTH] 已创建默认管理员账户: admin")
    print(f"[AUTH] 密码: {admin_password}")
    print(f"[AUTH] 请通过环境变量 ADMIN_PASSWORD 设置自定义密码")


# ============================================================
# 路径安全
# ============================================================

# 项目名白名单：字母数字、下划线、连字符、中文、书名号、括号、空格
_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fa5《》（）()\[\] ]+$")


class ProjectNameError(ValueError):
    """项目名不合法（含路径遍历攻击或非法字符）"""


def _validate_project_name(project_name: str) -> str:
    """校验并清洗项目名，防止路径遍历攻击。

    规则：
    1. 拒绝空名
    2. 拒绝原始输入中包含路径分隔符或 .. 的（即使 basename 后看似安全）
    3. 用 os.path.basename 剥离作为防御性二次保护
    4. 用白名单正则校验剩余字符

    返回清洗后的安全项目名；不合法则抛出 ProjectNameError。
    """
    if not project_name or not isinstance(project_name, str):
        raise ProjectNameError("项目名不能为空")

    raw = project_name.strip()

    # 第一道防线：原始输入不得包含路径分隔符或 ..
    # 这是最关键的检查 —— 即使 basename 后看似安全，原始输入含分隔符即视为攻击
    if "/" in raw or "\\" in raw or ".." in raw:
        raise ProjectNameError(f"项目名含非法路径字符: {project_name!r}")

    # 第二道防线：basename 剥离（防御性，正常情况下 raw 已无分隔符）
    name = os.path.basename(raw)

    # 三次校验：basename 后仍不应为空或 . 
    if not name or name in (".", ".."):
        raise ProjectNameError(f"非法项目名: {project_name!r}")

    # 白名单校验
    if not _PROJECT_NAME_RE.match(name):
        raise ProjectNameError(
            f"项目名含非法字符: {name!r}（仅允许字母数字、下划线、连字符、中文、书名号、括号、空格）"
        )

    return name


# ============================================================
# 工具函数
# ============================================================

def get_project_dir(project_name: str) -> str:
    """返回项目文件夹路径（自动创建）。

    自动校验项目名，防止路径遍历。
    """
    safe_name = _validate_project_name(project_name)
    d = os.path.join(PROJECTS_DIR, safe_name)
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "chapters"), exist_ok=True)
    os.makedirs(os.path.join(d, "memory"), exist_ok=True)
    return d


def get_project_db_path(project_name: str) -> str:
    """返回项目 SQLite 数据库路径"""
    return os.path.join(get_project_dir(project_name), "project.db")


def get_project_file(project_name: str, filename: str) -> str:
    """返回项目内文件的完整路径"""
    return os.path.join(get_project_dir(project_name), filename)


def get_chapter_path(project_name: str, chapter_index: int) -> str:
    """返回章节文件路径"""
    return os.path.join(get_project_dir(project_name), "chapters", f"第{chapter_index}章.txt")


def read_file_safe(path: str, default: str = "") -> str:
    """安全读取文件"""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception:
        pass
    return default


def write_file_safe(path: str, content: str) -> bool:
    """安全写入文件"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        return False


def fmt_time(timestamp: Optional[float] = None) -> str:
    """格式化时间字符串"""
    t = timestamp or time.time()
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 项目数据库
# ============================================================

class ProjectDB:
    """项目数据库 - 每个项目独立连接"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        title TEXT DEFAULT '',
        genre TEXT DEFAULT '',
        total_chapters INTEGER DEFAULT 0,
        current_stage TEXT DEFAULT 'outline',  -- outline | writing | polish | done
        ai_preset TEXT DEFAULT '',
        execution_mode TEXT DEFAULT 'lite',  -- 已废弃字段（旧 3 模式：lite/standard/full），保留只为不破坏旧 DB
        outline_review_mode TEXT DEFAULT 'manual',  -- auto | manual（默认 manual：人工确认大纲）
        outline_mode TEXT DEFAULT '',  -- 旧字段：full | web_novel | single_chapter（已废弃，见 outline_layers）
        outline_layers TEXT DEFAULT '',  -- JSON: {"L1":true,"L2":true,"L3":true}
        manager_preset TEXT DEFAULT '',
        worker_preset TEXT DEFAULT '',
        reviewer_preset TEXT DEFAULT '',
        chat_preset TEXT DEFAULT '',
        description TEXT DEFAULT '',
        word_count_min INTEGER DEFAULT 3000,
        word_count_max INTEGER DEFAULT 5000,
        max_rounds_writing INTEGER DEFAULT 10,
        max_rounds_outline INTEGER DEFAULT 8,
        created_at TEXT DEFAULT '',
        updated_at TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS chapters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        chapter_index INTEGER NOT NULL,
        title TEXT DEFAULT '',
        summary TEXT DEFAULT '',
        content_path TEXT DEFAULT '',
        status TEXT DEFAULT 'not_started',  -- not_started | in_progress | drafted | reviewed | final
        word_count INTEGER DEFAULT 0,
        prev_text TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        updated_at TEXT DEFAULT '',
        FOREIGN KEY (project_id) REFERENCES projects(id),
        UNIQUE (project_id, chapter_index)
    );

    CREATE TABLE IF NOT EXISTS memory_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        type TEXT DEFAULT '',  -- summary | character | hook | world | memory | etc
        content TEXT DEFAULT '',
        chapter_ref INTEGER DEFAULT 0,
        created_at TEXT DEFAULT '',
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        role TEXT NOT NULL,  -- user | assistant | system
        content TEXT NOT NULL,
        context TEXT DEFAULT '',  -- 当前阶段: outline/writing/polish
        created_at TEXT DEFAULT '',
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    CREATE TABLE IF NOT EXISTS stage_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        stage TEXT NOT NULL,  -- outline | writing | polish
        status TEXT DEFAULT 'pending',  -- pending | running | completed | paused | failed
        started_at TEXT DEFAULT '',
        finished_at TEXT DEFAULT '',
        message TEXT DEFAULT '',
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    CREATE INDEX IF NOT EXISTS idx_chapters_project ON chapters(project_id);
    CREATE INDEX IF NOT EXISTS idx_chapters_index ON chapters(chapter_index);
    CREATE INDEX IF NOT EXISTS idx_memory_project ON memory_items(project_id);
    CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_items(type);
    CREATE INDEX IF NOT EXISTS idx_chat_project ON chat_messages(project_id);
    CREATE INDEX IF NOT EXISTS idx_stage_project ON stage_runs(project_id);
    """

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.db_path = get_project_db_path(project_name)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()
        self._ensure_project_record()

    # ---------------- 内部方法 ----------------

    def _init_schema(self):
        """初始化表结构 + 版本化迁移"""
        self.conn.executescript(self.SCHEMA)

        # 确保 schema_meta 表存在
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # 读取当前 schema_version
        cur = self.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'")
        row = cur.fetchone()
        current_version = int(row[0]) if row else 0

        # 版本化迁移链
        if current_version < 1:
            self._migrate_v0_to_v1()
            self.conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '1')"
            )
            self.conn.commit()
            current_version = 1

        if current_version < 2:
            self._migrate_v1_to_v2()
            self.conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '2')"
            )
            self.conn.commit()

    def _migrate_v0_to_v1(self, conn=None):
        """v0→v1: 添加 chat_preset / outline_mode / outline_layers / word_count / max_rounds 字段"""
        c = conn or self.conn
        try:
            cur = c.execute("PRAGMA table_info(projects)")
            cols = {row[1] for row in cur.fetchall()}
            if "chat_preset" not in cols:
                c.execute("ALTER TABLE projects ADD COLUMN chat_preset TEXT DEFAULT ''")
            if "outline_mode" not in cols:
                c.execute("ALTER TABLE projects ADD COLUMN outline_mode TEXT DEFAULT ''")
            if "outline_layers" not in cols:
                c.execute("ALTER TABLE projects ADD COLUMN outline_layers TEXT DEFAULT ''")
            if "word_count_min" not in cols:
                c.execute("ALTER TABLE projects ADD COLUMN word_count_min INTEGER DEFAULT 3000")
            if "word_count_max" not in cols:
                c.execute("ALTER TABLE projects ADD COLUMN word_count_max INTEGER DEFAULT 5000")
            if "max_rounds_writing" not in cols:
                c.execute("ALTER TABLE projects ADD COLUMN max_rounds_writing INTEGER DEFAULT 10")
            if "max_rounds_outline" not in cols:
                c.execute("ALTER TABLE projects ADD COLUMN max_rounds_outline INTEGER DEFAULT 8")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Migration v0->v1 failed: {e}", exc_info=True)

    def _migrate_v1_to_v2(self, conn=None):
        """v1→v2: 加密 preset JSON 中的明文 api_key"""
        c = conn or self.conn
        try:
            fernet = _get_fernet()
            cur = c.execute("SELECT id, manager_preset, worker_preset, reviewer_preset, chat_preset FROM projects")
            rows = cur.fetchall()
            for row in rows:
                row_id = row[0]
                updated = False
                new_values = {}
                for col_idx, col_name in enumerate(["manager_preset", "worker_preset", "reviewer_preset", "chat_preset"], start=1):
                    raw = row[col_idx]
                    if not raw or not isinstance(raw, str) or not raw.strip():
                        continue
                    try:
                        preset = json.loads(raw)
                        if isinstance(preset, dict) and "api_key" in preset:
                            api_key = preset["api_key"]
                            if api_key and isinstance(api_key, str) and not api_key.startswith("gAAAAA"):
                                preset["api_key"] = _encrypt_api_key(api_key, fernet)
                                new_values[col_name] = json.dumps(preset, ensure_ascii=False)
                                updated = True
                    except (json.JSONDecodeError, Exception) as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Migration v1->v2: failed to parse preset: {e}", exc_info=True)
                if updated:
                    set_clause = ", ".join(f"{k}=?" for k in new_values)
                    values = list(new_values.values()) + [row_id]
                    c.execute(f"UPDATE projects SET {set_clause} WHERE id=?", values)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Migration v1->v2 failed: {e}", exc_info=True)

    def _migrate_outline_layers(self) -> None:
        """把旧 outline_mode 迁移到 outline_layers。"""
        try:
            cur = self.conn.execute("SELECT outline_mode, outline_layers FROM projects WHERE name=?", (self.project_name,))
            row = cur.fetchone()
            if not row:
                return
            old_mode = row[0] or ""
            new_layers = row[1] or ""
            if new_layers:
                return  # 已有，跳过
            if not old_mode:
                return  # 没旧值，留空（get_outline_layers 会默认全开）
            # 旧 → 新
            if old_mode == "full":
                layers = {"L1": True, "L2": True, "L3": True}
            elif old_mode == "web_novel":
                layers = {"L1": False, "L2": True, "L3": True}
            elif old_mode == "single_chapter":
                layers = {"L1": False, "L2": False, "L3": True}
            else:
                layers = {"L1": True, "L2": True, "L3": True}
            self.update_project(outline_layers=json.dumps(layers, ensure_ascii=False))
        except Exception:
            pass

    def _migrate_outline_layers_run(self) -> None:
        pass  # placeholder, real impl below

    def get_presets(self) -> Dict[str, Dict]:
        """获取项目的角色预设：{manager, worker, reviewer, chat}"""
        info = self.get_project()
        return {
            "manager": info.get("manager_preset") or {},
            "worker": info.get("worker_preset") or {},
            "reviewer": info.get("reviewer_preset") or {},
            "chat": info.get("chat_preset") or {},
        }

    def _ensure_project_record(self):
        """确保项目记录存在"""
        cur = self.conn.execute("SELECT id FROM projects WHERE name=?", (self.project_name,))
        row = cur.fetchone()
        now = fmt_time()
        if not row:
            self.conn.execute(
                "INSERT INTO projects (name, title, total_chapters, current_stage, outline_review_mode, execution_mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, '', ?, ?)",
                (self.project_name, self.project_name, 0, "outline", "auto", now, now)
            )
            self.conn.commit()

    def _now(self) -> str:
        return fmt_time()

    def _row_to_dict(self, row) -> Optional[Dict]:
        if row is None:
            return None
        return dict(row)

    def _rows_to_list(self, rows) -> List[Dict]:
        return [dict(r) for r in rows]

    # ---------------- 项目 CRUD ----------------

    def get_project(self) -> Dict:
        """获取项目信息（manager/worker/reviewer/chat_preset 自动解析 JSON，api_key 自动解密）"""
        cur = self.conn.execute("SELECT * FROM projects WHERE name=?", (self.project_name,))
        info = self._row_to_dict(cur.fetchone()) or {}
        for k in ("manager_preset", "worker_preset", "reviewer_preset", "chat_preset"):
            v = info.get(k)
            if isinstance(v, str) and v.strip():
                try:
                    preset = json.loads(v)
                    # 解密 api_key
                    if isinstance(preset, dict) and "api_key" in preset:
                        preset["api_key"] = _decrypt_api_key(preset["api_key"])
                    info[k] = preset
                except Exception: info[k] = {}
            else:
                info[k] = {}
        return info

    def update_project(self, **kwargs) -> bool:
        """更新项目字段（dict 类型字段会自动 JSON 序列化，api_key 自动加密）"""
        if not kwargs:
            return False
        kwargs["updated_at"] = self._now()
        for k in ("manager_preset", "worker_preset", "reviewer_preset", "chat_preset"):
            if k in kwargs and isinstance(kwargs[k], (dict, list)):
                preset = kwargs[k]
                # 加密 api_key
                if isinstance(preset, dict) and "api_key" in preset:
                    preset["api_key"] = _encrypt_api_key(preset["api_key"])
                kwargs[k] = json.dumps(preset, ensure_ascii=False)
        fields = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [self.project_name]
        try:
            self.conn.execute(f"UPDATE projects SET {fields} WHERE name=?", values)
            self.conn.commit()
            return True
        except Exception as e:
            print(f"[DB] update_project error: {e}")
            return False

    def set_stage(self, stage: str) -> bool:
        """设置当前阶段"""
        return self.update_project(current_stage=stage)

    def get_stage(self) -> str:
        """获取当前阶段"""
        project = self.get_project()
        return project.get("current_stage", "outline") or "outline"

    def get_outline_layers(self) -> Dict[str, bool]:
        """获取大纲 3 层开关，默认全开。"""
        self._migrate_outline_layers()
        info = self.get_project()
        v = info.get("outline_layers")
        if isinstance(v, dict):
            return v
        if isinstance(v, str) and v.strip():
            try:
                return json.loads(v)
            except Exception:
                pass
        return {"L1": True, "L2": True, "L3": True}

    def set_outline_layers(self, layers: Dict[str, bool]) -> bool:
        return self.update_project(outline_layers=json.dumps(layers, ensure_ascii=False))

    def set_presets(self, manager: Optional[Dict] = None,
                    worker: Optional[Dict] = None,
                    reviewer: Optional[Dict] = None,
                    chat: Optional[Dict] = None) -> bool:
        """设置项目的角色预设（chat 为 AI 对话模型，用于轻量对话）"""
        data = {}
        if manager is not None:
            data["manager_preset"] = json.dumps(manager, ensure_ascii=False) if manager else ""
        if worker is not None:
            data["worker_preset"] = json.dumps(worker, ensure_ascii=False) if worker else ""
        if reviewer is not None:
            data["reviewer_preset"] = json.dumps(reviewer, ensure_ascii=False) if reviewer else ""
        if chat is not None:
            data["chat_preset"] = json.dumps(chat, ensure_ascii=False) if chat else ""
        if not data:
            return True
        return self.update_project(**data)

    # ---------------- 章节 CRUD ----------------

    def list_chapters(self) -> List[Dict]:
        """获取所有章节列表（按序号排序）"""
        cur = self.conn.execute(
            "SELECT * FROM chapters WHERE project_id=(SELECT id FROM projects WHERE name=?) ORDER BY chapter_index",
            (self.project_name,)
        )
        return self._rows_to_list(cur.fetchall())

    def get_chapter(self, chapter_index: int) -> Optional[Dict]:
        """获取单个章节信息"""
        cur = self.conn.execute(
            "SELECT * FROM chapters WHERE project_id=(SELECT id FROM projects WHERE name=?) AND chapter_index=?",
            (self.project_name, chapter_index)
        )
        row = cur.fetchone()
        if not row:
            return None
        d = self._row_to_dict(row)
        # 读取实际内容（如果文件存在）
        path = d.get("content_path") or get_chapter_path(self.project_name, chapter_index)
        d["content"] = read_file_safe(path, "")
        return d

    def upsert_chapter(self, chapter_index: int, title: str = "", summary: str = "",
                        status: str = "drafted", content: Optional[str] = None,
                        word_count: int = 0, prev_text: str = "") -> bool:
        """插入或更新章节"""
        project = self.get_project()
        project_id = project.get("id", 1)
        now = self._now()
        path = get_chapter_path(self.project_name, chapter_index)

        # 保存内容到磁盘
        if content is not None:
            write_file_safe(path, content)
            if word_count == 0:
                word_count = len(content.replace(" ", "").replace("\n", ""))

        # 更新数据库
        try:
            cur = self.conn.execute(
                "SELECT id FROM chapters WHERE project_id=? AND chapter_index=?",
                (project_id, chapter_index)
            )
            if cur.fetchone():
                self.conn.execute(
                    "UPDATE chapters SET title=?, summary=?, content_path=?, status=?, word_count=?, prev_text=?, updated_at=? WHERE project_id=? AND chapter_index=?",
                    (title, summary, path, status, word_count, prev_text, now, project_id, chapter_index)
                )
            else:
                self.conn.execute(
                    "INSERT INTO chapters (project_id, chapter_index, title, summary, content_path, status, word_count, prev_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (project_id, chapter_index, title, summary, path, status, word_count, prev_text, now, now)
                )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"[DB] upsert_chapter error: {e}")
            return False

    def update_chapter_status(self, chapter_index: int, status: str) -> bool:
        """更新章节状态"""
        project = self.get_project()
        try:
            self.conn.execute(
                "UPDATE chapters SET status=?, updated_at=? WHERE project_id=? AND chapter_index=?",
                (status, self._now(), project.get("id", 1), chapter_index)
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    def delete_chapter(self, chapter_index: int) -> bool:
        """删除章节"""
        project = self.get_project()
        try:
            self.conn.execute(
                "DELETE FROM chapters WHERE project_id=? AND chapter_index=?",
                (project.get("id", 1), chapter_index)
            )
            self.conn.commit()
            # 同时删除文件
            path = get_chapter_path(self.project_name, chapter_index)
            if os.path.exists(path):
                os.remove(path)
            return True
        except Exception:
            return False

    def get_chapter_count(self) -> int:
        """已完成章节数"""
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM chapters WHERE project_id=(SELECT id FROM projects WHERE name=?) AND status IN ('drafted','polished','completed','reviewed','final','revised')",
            (self.project_name,)
        )
        row = cur.fetchone()
        return row[0] if row else 0

    def get_progress(self) -> Dict:
        """获取项目进度摘要"""
        project = self.get_project()
        chapters = self.list_chapters()
        total = project.get("total_chapters", 0) or 0
        done = len([c for c in chapters if c.get("status") in ("drafted", "polished", "completed", "reviewed", "final", "revised")])
        total_words = sum(c.get("word_count", 0) for c in chapters)
        return {
            "total": total,
            "done": done,
            "percent": round(done / total * 100, 1) if total > 0 else 0,
            "total_words": total_words,
            "current_stage": project.get("current_stage", "outline"),
        }

    # ---------------- 记忆 CRUD ----------------

    def list_memory(self, mem_type: str = "") -> List[Dict]:
        """获取记忆条目"""
        project = self.get_project()
        if mem_type:
            cur = self.conn.execute(
                "SELECT * FROM memory_items WHERE project_id=? AND type=? ORDER BY id",
                (project.get("id", 1), mem_type)
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM memory_items WHERE project_id=? ORDER BY type, id",
                (project.get("id", 1),)
            )
        return self._rows_to_list(cur.fetchall())

    def add_memory(self, mem_type: str, content: str, chapter_ref: int = 0) -> int:
        """添加记忆条目"""
        project = self.get_project()
        try:
            cur = self.conn.execute(
                "INSERT INTO memory_items (project_id, type, content, chapter_ref, created_at) VALUES (?, ?, ?, ?, ?)",
                (project.get("id", 1), mem_type, content, chapter_ref, self._now())
            )
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            print(f"[DB] add_memory error: {e}")
            return 0

    def clear_memory_type(self, mem_type: str) -> bool:
        """清除某类型记忆"""
        project = self.get_project()
        try:
            self.conn.execute(
                "DELETE FROM memory_items WHERE project_id=? AND type=?",
                (project.get("id", 1), mem_type)
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    # ---------------- 对话 CRUD ----------------

    def list_chat(self, limit: int = 50) -> List[Dict]:
        """获取对话历史（最新N条，按时间正序）"""
        project = self.get_project()
        cur = self.conn.execute(
            "SELECT * FROM chat_messages WHERE project_id=? ORDER BY id DESC LIMIT ?",
            (project.get("id", 1), limit)
        )
        rows = cur.fetchall()
        return list(reversed(self._rows_to_list(rows)))

    def add_chat(self, role: str, content: str, context: str = "") -> int:
        """添加一条对话"""
        project = self.get_project()
        try:
            cur = self.conn.execute(
                "INSERT INTO chat_messages (project_id, role, content, context, created_at) VALUES (?, ?, ?, ?, ?)",
                (project.get("id", 1), role, content, context, self._now())
            )
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            print(f"[DB] add_chat error: {e}")
            return 0

    def clear_chat(self) -> bool:
        """清空对话历史"""
        project = self.get_project()
        try:
            self.conn.execute("DELETE FROM chat_messages WHERE project_id=?", (project.get("id", 1),))
            self.conn.commit()
            return True
        except Exception:
            return False

    # ---------------- 阶段运行记录 ----------------

    def start_stage_run(self, stage: str) -> int:
        """启动一个阶段"""
        project = self.get_project()
        try:
            cur = self.conn.execute(
                "INSERT INTO stage_runs (project_id, stage, status, started_at) VALUES (?, ?, 'running', ?)",
                (project.get("id", 1), stage, self._now())
            )
            self.conn.commit()
            self.set_stage(stage)
            return cur.lastrowid
        except Exception as e:
            print(f"[DB] start_stage_run error: {e}")
            return 0

    def finish_stage_run(self, stage: str, status: str = "completed", message: str = "") -> bool:
        """完成一个阶段"""
        project = self.get_project()
        try:
            self.conn.execute(
                "UPDATE stage_runs SET status=?, finished_at=?, message=? WHERE project_id=? AND stage=? AND status='running'",
                (status, self._now(), message, project.get("id", 1), stage)
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    def list_stage_runs(self) -> List[Dict]:
        """获取阶段运行记录"""
        project = self.get_project()
        cur = self.conn.execute(
            "SELECT * FROM stage_runs WHERE project_id=? ORDER BY id",
            (project.get("id", 1),)
        )
        return self._rows_to_list(cur.fetchall())

    # ---------------- 文件操作（大纲/人物/记忆原文） ----------------

    def save_outline(self, content: str) -> bool:
        """保存大纲"""
        path = get_project_file(self.project_name, "outline.md")
        ok = write_file_safe(path, content)
        if ok:
            self.update_project(updated_at=self._now())
        return ok

    def save_characters(self, content: str) -> bool:
        """保存人物设定"""
        path = get_project_file(self.project_name, "characters.md")
        ok = write_file_safe(path, content)
        if ok:
            # 同步到 memory_items
            self.clear_memory_type("character")
            self.add_memory("character", f"characters.md 完整内容已保存（{len(content)}字）", 0)
        return ok

    def save_novel_memory(self, content: str) -> bool:
        """保存长篇记忆（novel_memory.md）"""
        path = get_project_file(self.project_name, "memory", "novel_memory.md")
        ok = write_file_safe(path, content)
        if ok:
            self.clear_memory_type("memory")
            self.add_memory("memory", f"novel_memory.md 已更新（{len(content)}字）", 0)
        return ok

    def read_outline(self) -> str:
        return read_file_safe(get_project_file(self.project_name, "outline.md"), "")

    def read_characters(self) -> str:
        return read_file_safe(get_project_file(self.project_name, "characters.md"), "")

    def read_novel_memory(self) -> str:
        return read_file_safe(get_project_file(self.project_name, "memory", "novel_memory.md"), "")

    def read_chapter_content(self, chapter_index: int) -> str:
        """读取章节正文"""
        return read_file_safe(get_chapter_path(self.project_name, chapter_index), "")

    # ---------------- 导出 ----------------

    def to_dict(self) -> Dict:
        """导出完整项目信息（给前端用）"""
        project = self.get_project()
        chapters = self.list_chapters()
        progress = self.get_progress()
        summary_memory = "\n".join(m.get("content", "") for m in self.list_memory("summary"))
        character_memory = "\n".join(m.get("content", "") for m in self.list_memory("character"))

        return {
            "project": project,
            "chapters": chapters,
            "progress": progress,
            "memory_summary": summary_memory,
            "memory_character": character_memory,
            "outline": self.read_outline(),
            "characters": self.read_characters(),
            "chat": self.list_chat(100),
            "stage_runs": self.list_stage_runs(),
        }

    def close(self):
        """关闭连接"""
        try:
            self.conn.close()
        except Exception:
            pass


# ============================================================
# 项目列表管理（projects 目录下的所有项目）
# ============================================================

def list_all_projects() -> List[Dict]:
    """获取所有项目摘要"""
    result = []
    if not os.path.exists(PROJECTS_DIR):
        return result
    for name in sorted(os.listdir(PROJECTS_DIR)):
        p = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(p):
            continue
        db_path = os.path.join(p, "project.db")
        try:
            db = ProjectDB(name)
            info = db.get_project()
            progress = db.get_progress()
            db.close()
            result.append({
                "name": name,
                "title": info.get("title", name),
                "genre": info.get("genre", ""),
                "total_chapters": info.get("total_chapters", 0),
                "chapters_done": progress.get("done", 0),
                "total_words": progress.get("total_words", 0),
                "current_stage": info.get("current_stage", "outline"),
                "created_at": info.get("created_at", ""),
                "updated_at": info.get("updated_at", ""),
                "progress": progress,
            })
        except Exception:
            # 还没初始化的文件夹
            result.append({
                "name": name, "title": name, "genre": "",
                "total_chapters": 0, "current_stage": "outline",
                "created_at": "", "updated_at": "", "progress": {"total": 0, "done": 0, "percent": 0, "total_words": 0, "current_stage": "outline"}
            })
    return result


def create_project(name: str, title: str = "", genre: str = "",
                   total_chapters: int = 0,
                   outline_review_mode: str = "manual",
                   outline_layers: Optional[Dict[str, bool]] = None) -> Dict:
    """创建新项目"""
    # 清理不合法字符（兼容旧逻辑：先做字符级过滤，再用统一校验）
    filtered = "".join(c for c in name if c.isalnum() or c in "_-《》（）()[] ")
    filtered = filtered.strip()
    try:
        safe_name = _validate_project_name(filtered) if filtered else f"project_{int(time.time())}"
    except ProjectNameError:
        safe_name = f"project_{int(time.time())}"

    db = ProjectDB(safe_name)
    db.update_project(
        title=title or safe_name,
        genre=genre,
        total_chapters=total_chapters,
        outline_review_mode=outline_review_mode,
    )
    if outline_layers:
        db.set_outline_layers(outline_layers)
    info = db.get_project()
    info["outline_layers"] = db.get_outline_layers()
    db.close()
    return {"success": True, "name": safe_name, "project": info}


def delete_project(name: str) -> bool:
    """删除项目（删除整个文件夹）。Windows 上 SQLite 文件可能被占用，需要重试。"""
    safe_name = _validate_project_name(name)
    p = os.path.join(PROJECTS_DIR, safe_name)
    if not os.path.exists(p):
        return False
    import shutil
    import time
    # 先尝试关闭可能残留的数据库连接
    try:
        db = ProjectDB(name)
        db.close()
    except Exception:
        pass
    # 重试删除（Windows 上 SQLite 文件可能被短暂锁定）
    for attempt in range(5):
        try:
            shutil.rmtree(p)
            return True
        except Exception as e:
            if attempt < 4:
                time.sleep(0.3)
            else:
                print(f"[DB] delete_project error after retries: {e}")
                # 最后一次尝试：逐个删除文件，跳过被锁定的
                try:
                    for root, dirs, files in os.walk(p, topdown=False):
                        for f in files:
                            fp = os.path.join(root, f)
                            try:
                                os.remove(fp)
                            except Exception:
                                pass
                        for d in dirs:
                            dp = os.path.join(root, d)
                            try:
                                os.rmdir(dp)
                            except Exception:
                                pass
                    try:
                        os.rmdir(p)
                    except Exception:
                        pass
                    return not os.path.exists(p)
                except Exception:
                    return False
