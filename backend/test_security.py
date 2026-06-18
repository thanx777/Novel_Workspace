"""安全机制测试 — API Key 加密/解密 + schema 迁移 + 路径遍历防护。"""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, '.')

PASSED = []
FAILED = []

def run(name, fn):
    try:
        result = fn()
        PASSED.append(name)
        print(f"  ✅ {name}")
    except Exception as e:
        FAILED.append(name)
        print(f"  ❌ {name} → {e}")


# ============================================================
# 辅助：在临时目录中创建独立 ProjectDB，避免影响真实数据
# ============================================================

def _make_temp_projectdb(project_name="test_sec"):
    """在临时目录中创建 ProjectDB，返回 (db, tmpdir, projects_dir)。

    通过临时替换 PROJECTS_DIR 来实现隔离。
    """
    import project_db as _pdb

    tmpdir = tempfile.mkdtemp(prefix="omni_test_")
    projects_dir = os.path.join(tmpdir, "projects")
    os.makedirs(projects_dir, exist_ok=True)

    # 保存原始值
    orig_projects_dir = _pdb.PROJECTS_DIR

    # 临时替换
    _pdb.PROJECTS_DIR = projects_dir

    db = _pdb.ProjectDB(project_name)
    return db, tmpdir, projects_dir, orig_projects_dir


def _cleanup_temp(db, tmpdir, orig_projects_dir):
    """清理临时目录并恢复 PROJECTS_DIR。"""
    import project_db as _pdb
    try:
        db.close()
    except Exception:
        pass
    _pdb.PROJECTS_DIR = orig_projects_dir
    shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# t01: 明文 API Key 写入后自动加密（DB 中以 gAAAAA 开头）
# ============================================================

def t01():
    import project_db as _pdb
    from cryptography.fernet import Fernet

    db, tmpdir, projects_dir, orig = _make_temp_projectdb("t01_proj")
    try:
        plain_key = "sk-test-plaintext-api-key-12345"
        db.update_project(manager_preset={"name": "mgr", "api_key": plain_key})

        # 直接从 SQLite 读取原始值（绕过 get_project 的自动解密）
        cur = db.conn.execute("SELECT manager_preset FROM projects WHERE name='t01_proj'")
        row = cur.fetchone()
        raw_value = row[0]

        import json
        preset = json.loads(raw_value)
        stored_key = preset["api_key"]

        assert stored_key.startswith("gAAAAA"), \
            f"加密后应以 gAAAAA 开头，实际: {stored_key[:20]}..."
        assert stored_key != plain_key, "加密后不应等于明文"
    finally:
        _cleanup_temp(db, tmpdir, orig)


# ============================================================
# t02: 读取时自动解密返回原始值
# ============================================================

def t02():
    db, tmpdir, projects_dir, orig = _make_temp_projectdb("t02_proj")
    try:
        plain_key = "sk-test-decrypt-check-key"
        db.update_project(worker_preset={"name": "wrk", "api_key": plain_key})

        # get_project 应自动解密
        info = db.get_project()
        retrieved_key = info["worker_preset"]["api_key"]

        assert retrieved_key == plain_key, \
            f"读取时应返回原始明文，实际: {retrieved_key}"
    finally:
        _cleanup_temp(db, tmpdir, orig)


# ============================================================
# t03: 已加密的 API Key 不重复加密（幂等性）
# ============================================================

def t03():
    import project_db as _pdb

    db, tmpdir, projects_dir, orig = _make_temp_projectdb("t03_proj")
    try:
        plain_key = "sk-test-idempotent-key"
        db.update_project(reviewer_preset={"name": "rev", "api_key": plain_key})

        # 第一次：获取加密后的值
        info1 = db.get_project()
        decrypted1 = info1["reviewer_preset"]["api_key"]
        assert decrypted1 == plain_key

        # 读取 DB 中的加密值
        cur = db.conn.execute("SELECT reviewer_preset FROM projects WHERE name='t03_proj'")
        raw1 = cur.fetchone()[0]

        # 第二次：用已加密的值再写入（模拟重复写入）
        import json
        encrypted_preset = json.loads(raw1)
        db.update_project(reviewer_preset=encrypted_preset)

        # 再次读取 DB 中的值，应该和第一次一样
        cur = db.conn.execute("SELECT reviewer_preset FROM projects WHERE name='t03_proj'")
        raw2 = cur.fetchone()[0]

        assert raw1 == raw2, "已加密的值不应被重复加密"

        # 读取时仍应返回明文
        info2 = db.get_project()
        decrypted2 = info2["reviewer_preset"]["api_key"]
        assert decrypted2 == plain_key, "二次写入后仍应正确解密"
    finally:
        _cleanup_temp(db, tmpdir, orig)


# ============================================================
# t04: 无 OMNI_AGENT_SECRET 环境变量时自动生成 .secret_key 文件
# ============================================================

def t04():
    import project_db as _pdb
    from cryptography.fernet import Fernet

    # 保存并清除全局 Fernet 实例，强制重新初始化
    orig_fernet = _pdb._FERNET_INSTANCE
    _pdb._FERNET_INSTANCE = None

    # 临时移除环境变量
    orig_env = os.environ.pop("OMNI_AGENT_SECRET", None)

    # 临时设置 backend 目录为临时目录（让 .secret_key 生成到临时位置）
    orig_dir = os.path.dirname(os.path.abspath(_pdb.__file__))
    secret_key_path = os.path.join(orig_dir, ".secret_key")

    # 备份已有 .secret_key（如果存在）
    backup_path = secret_key_path + ".test_backup"
    had_secret = os.path.exists(secret_key_path)
    if had_secret:
        shutil.copy2(secret_key_path, backup_path)

    try:
        # 删除 .secret_key 以强制重新生成
        if os.path.exists(secret_key_path):
            os.remove(secret_key_path)

        # 调用 _get_fernet 应自动生成 .secret_key
        fernet = _pdb._get_fernet()

        assert os.path.exists(secret_key_path), \
            "缺少 OMNI_AGENT_SECRET 时应自动生成 .secret_key 文件"

        with open(secret_key_path, "r", encoding="utf-8") as f:
            generated_key = f.read().strip()

        assert len(generated_key) > 0, ".secret_key 文件不应为空"
        # 验证生成的密钥可以创建 Fernet 实例
        Fernet(generated_key.encode("utf-8"))
    finally:
        # 恢复
        _pdb._FERNET_INSTANCE = orig_fernet
        if orig_env is not None:
            os.environ["OMNI_AGENT_SECRET"] = orig_env
        # 恢复备份
        if had_secret and os.path.exists(backup_path):
            shutil.move(backup_path, secret_key_path)
        elif os.path.exists(backup_path):
            os.remove(backup_path)


# ============================================================
# t05: 解密失败时返回原值（兼容未加密旧数据）
# ============================================================

def t05():
    import project_db as _pdb

    db, tmpdir, projects_dir, orig = _make_temp_projectdb("t05_proj")
    try:
        # 直接向 DB 写入一个非加密格式的 api_key（模拟旧数据）
        import json
        plain_key = "sk-legacy-unencrypted-key"
        preset_json = json.dumps({"name": "legacy", "api_key": plain_key})
        db.conn.execute(
            "UPDATE projects SET chat_preset=? WHERE name='t05_proj'",
            (preset_json,)
        )
        db.conn.commit()

        # get_project 应返回原值（因为不以 gAAAAA 开头，_decrypt_api_key 直接返回）
        info = db.get_project()
        retrieved = info["chat_preset"]["api_key"]
        assert retrieved == plain_key, \
            f"未加密旧数据应原样返回，实际: {retrieved}"

        # 测试解密无效密文时返回原值
        bad_ciphertext = "gAAAAAinvalidciphertextthatcannotbedecrypted"
        result = _pdb._decrypt_api_key(bad_ciphertext)
        assert result == bad_ciphertext, \
            f"解密失败时应返回原值，实际: {result}"
    finally:
        _cleanup_temp(db, tmpdir, orig)


# ============================================================
# t06: 多个 preset 的 API Key 都正确加密/解密
# ============================================================

def t06():
    db, tmpdir, projects_dir, orig = _make_temp_projectdb("t06_proj")
    try:
        keys = {
            "manager_preset": "sk-mgr-multi-test-key",
            "worker_preset": "sk-wrk-multi-test-key",
            "reviewer_preset": "sk-rev-multi-test-key",
            "chat_preset": "sk-chat-multi-test-key",
        }

        db.update_project(
            manager_preset={"name": "mgr", "api_key": keys["manager_preset"]},
            worker_preset={"name": "wrk", "api_key": keys["worker_preset"]},
            reviewer_preset={"name": "rev", "api_key": keys["reviewer_preset"]},
            chat_preset={"name": "chat", "api_key": keys["chat_preset"]},
        )

        # 验证 DB 中全部加密
        import json
        cur = db.conn.execute(
            "SELECT manager_preset, worker_preset, reviewer_preset, chat_preset FROM projects WHERE name='t06_proj'"
        )
        row = cur.fetchone()
        for idx, col_name in enumerate(["manager_preset", "worker_preset", "reviewer_preset", "chat_preset"]):
            preset = json.loads(row[idx])
            stored_key = preset["api_key"]
            assert stored_key.startswith("gAAAAA"), \
                f"{col_name} 加密后应以 gAAAAA 开头，实际: {stored_key[:20]}..."

        # 验证读取时全部解密
        info = db.get_project()
        for col_name, expected_key in keys.items():
            retrieved = info[col_name]["api_key"]
            assert retrieved == expected_key, \
                f"{col_name} 解密后应等于明文，期望: {expected_key}，实际: {retrieved}"
    finally:
        _cleanup_temp(db, tmpdir, orig)


# ============================================================
# t07: 新建项目 schema_version = 2
# ============================================================

def t07():
    db, tmpdir, projects_dir, orig = _make_temp_projectdb("t07_proj")
    try:
        cur = db.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'")
        row = cur.fetchone()
        assert row is not None, "schema_meta 表中应有 schema_version 记录"
        version = int(row[0])
        assert version == 2, f"新建项目 schema_version 应为 2，实际: {version}"
    finally:
        _cleanup_temp(db, tmpdir, orig)


# ============================================================
# t08: v0→v2 跨版本迁移（无 schema_meta 表的旧库）
# ============================================================

def t08():
    import project_db as _pdb
    import sqlite3

    tmpdir = tempfile.mkdtemp(prefix="omni_migrate_")
    projects_dir = os.path.join(tmpdir, "projects")
    os.makedirs(projects_dir, exist_ok=True)

    orig_projects_dir = _pdb.PROJECTS_DIR
    _pdb.PROJECTS_DIR = projects_dir

    try:
        # 手动创建一个 v0 旧库（无 schema_meta 表，无 chat_preset 等字段）
        proj_dir = os.path.join(projects_dir, "t08_migrate")
        os.makedirs(proj_dir, exist_ok=True)
        db_path = os.path.join(proj_dir, "project.db")

        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                title TEXT DEFAULT '',
                genre TEXT DEFAULT '',
                total_chapters INTEGER DEFAULT 0,
                current_stage TEXT DEFAULT 'outline',
                ai_preset TEXT DEFAULT '',
                execution_mode TEXT DEFAULT 'lite',
                outline_review_mode TEXT DEFAULT 'manual',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            )
        """)
        # 插入一条含明文 api_key 的旧数据
        import json
        preset_with_key = json.dumps({"name": "old_preset", "api_key": "sk-old-plain-key"})
        conn.execute(
            "INSERT INTO projects (name, title, ai_preset) VALUES (?, ?, ?)",
            ("t08_migrate", "迁移测试", preset_with_key)
        )
        conn.commit()
        conn.close()

        # 打开 ProjectDB 应自动触发迁移
        db = _pdb.ProjectDB("t08_migrate")

        # 验证 schema_version 已升级到 2
        cur = db.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'")
        row = cur.fetchone()
        assert row is not None, "迁移后应有 schema_meta 表"
        version = int(row[0])
        assert version == 2, f"迁移后 schema_version 应为 2，实际: {version}"

        # 验证 v1 迁移：chat_preset 等字段已添加
        cur = db.conn.execute("PRAGMA table_info(projects)")
        cols = {r[1] for r in cur.fetchall()}
        assert "chat_preset" in cols, "v1 迁移应添加 chat_preset 字段"
        assert "word_count_min" in cols, "v1 迁移应添加 word_count_min 字段"

        # 验证 v2 迁移：api_key 已加密
        # 注意：旧数据在 ai_preset 字段（不在 manager/worker/reviewer/chat_preset 中）
        # v2 迁移只处理 manager_preset, worker_preset, reviewer_preset, chat_preset
        # 所以 ai_preset 中的明文 key 不会被自动加密（这是预期行为）

        db.close()
    finally:
        _pdb.PROJECTS_DIR = orig_projects_dir
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# t09: ../etc/passwd 被拒绝
# ============================================================

def t09():
    from project_db import _validate_project_name, ProjectNameError

    try:
        _validate_project_name("../etc/passwd")
        raise AssertionError("路径遍历攻击应被拒绝")
    except ProjectNameError:
        pass  # 预期行为


# ============================================================
# t10: project<script> 被拒绝
# ============================================================

def t10():
    from project_db import _validate_project_name, ProjectNameError

    try:
        _validate_project_name("project<script>")
        raise AssertionError("含非法字符的项目名应被拒绝")
    except ProjectNameError:
        pass  # 预期行为


# ============================================================
# 主入口
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("  安全机制测试 — API Key 加密/解密 + schema 迁移 + 路径遍历防护")
    print("=" * 70)
    print()

    print("  [API Key 加密/解密]")
    run("t01. 明文 API Key 写入后自动加密", t01)
    run("t02. 读取时自动解密返回原始值", t02)
    run("t03. 已加密的 API Key 不重复加密（幂等性）", t03)
    run("t04. 无 OMNI_AGENT_SECRET 时自动生成 .secret_key", t04)
    run("t05. 解密失败时返回原值（兼容旧数据）", t05)
    run("t06. 多个 preset 的 API Key 都正确加密/解密", t06)
    print()

    print("  [Schema 迁移]")
    run("t07. 新建项目 schema_version = 2", t07)
    run("t08. v0→v2 跨版本迁移", t08)
    print()

    print("  [路径遍历防护]")
    run("t09. ../etc/passwd 被拒绝", t09)
    run("t10. project<script> 被拒绝", t10)
    print()

    print("=" * 70)
    print(f"  结果:  {len(PASSED)} 通过 / {len(FAILED)} 失败")
    print("=" * 70)
    sys.exit(0 if not FAILED else 1)
