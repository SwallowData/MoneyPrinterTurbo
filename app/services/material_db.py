"""
素材数据库服务 - SQLite CRUD
"""
import json
import os
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple
from contextlib import contextmanager

from loguru import logger

from app.models.material import Material


class MaterialDatabase:
    """素材数据库管理类"""

    def __init__(self, db_path: str = "./storage/materials.db"):
        self.db_path = db_path
        self._ensure_db_dir()
        self._init_db()

    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _cursor(self):
        """上下文管理器：自动管理数据库连接"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_db(self):
        """初始化数据库表"""
        with self._cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS materials (
                    material_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    keywords TEXT DEFAULT '[]',
                    source_url TEXT DEFAULT '',
                    source TEXT DEFAULT 'local',
                    duration REAL,
                    thumbnail_path TEXT,
                    width INTEGER,
                    height INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    use_count INTEGER DEFAULT 0
                )
            """)
            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_materials_keywords
                ON materials(keywords)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_materials_file_type
                ON materials(file_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_materials_source
                ON materials(source)
            """)
        logger.info(f"素材数据库初始化完成: {self.db_path}")

    def insert(self, material: Material) -> bool:
        """插入素材"""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    INSERT INTO materials (
                        material_id, file_path, file_type, description, keywords,
                        source_url, source, duration, thumbnail_path,
                        width, height, created_at, updated_at, use_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    material.material_id,
                    material.file_path,
                    material.file_type,
                    material.description,
                    json.dumps(material.keywords, ensure_ascii=False),
                    material.source_url,
                    material.source,
                    material.duration,
                    material.thumbnail_path,
                    material.width,
                    material.height,
                    material.created_at.isoformat(),
                    material.updated_at.isoformat(),
                    material.use_count,
                ))
            logger.debug(f"素材插入成功: {material.material_id}")
            return True
        except Exception as e:
            logger.error(f"素材插入失败: {e}")
            return False

    def update(self, material: Material) -> bool:
        """更新素材"""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    UPDATE materials SET
                        file_path = ?,
                        file_type = ?,
                        description = ?,
                        keywords = ?,
                        source_url = ?,
                        source = ?,
                        duration = ?,
                        thumbnail_path = ?,
                        width = ?,
                        height = ?,
                        updated_at = ?,
                        use_count = ?
                    WHERE material_id = ?
                """, (
                    material.file_path,
                    material.file_type,
                    material.description,
                    json.dumps(material.keywords, ensure_ascii=False),
                    material.source_url,
                    material.source,
                    material.duration,
                    material.thumbnail_path,
                    material.width,
                    material.height,
                    datetime.now().isoformat(),
                    material.use_count,
                    material.material_id,
                ))
            return True
        except Exception as e:
            logger.error(f"素材更新失败: {e}")
            return False

    def delete(self, material_id: str) -> bool:
        """删除素材"""
        try:
            with self._cursor() as cursor:
                cursor.execute("DELETE FROM materials WHERE material_id = ?", (material_id,))
            return True
        except Exception as e:
            logger.error(f"素材删除失败: {e}")
            return False

    def get_by_id(self, material_id: str) -> Optional[Material]:
        """根据 ID 获取素材"""
        try:
            with self._cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM materials WHERE material_id = ?",
                    (material_id,)
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_material(row)
            return None
        except Exception as e:
            logger.error(f"获取素材失败: {e}")
            return None

    def get_by_path(self, file_path: str) -> Optional[Material]:
        """根据路径获取素材"""
        try:
            with self._cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM materials WHERE file_path = ?",
                    (file_path,)
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_material(row)
            return None
        except Exception as e:
            logger.error(f"获取素材失败: {e}")
            return None

    def search_by_keywords(
        self,
        keywords: List[str],
        file_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[Tuple[Material, float]]:
        """
        根据关键词搜索素材
        返回：(素材, 匹配分数) 列表，按分数降序排列

        匹配策略：简单的关键词重叠计算
        - 完全匹配：+1 分
        - 部分匹配（包含）：+0.5 分
        """
        if not keywords:
            return []

        results = []
        try:
            with self._cursor() as cursor:
                if file_type:
                    cursor.execute(
                        "SELECT * FROM materials WHERE file_type = ?",
                        (file_type,)
                    )
                else:
                    cursor.execute("SELECT * FROM materials")

                rows = cursor.fetchall()
                for row in rows:
                    material = self._row_to_material(row)
                    score = self._calculate_keyword_score(material.keywords, keywords)
                    if score > 0:
                        results.append((material, score))

            # 按分数降序排序
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:limit]

        except Exception as e:
            logger.error(f"关键词搜索失败: {e}")
            return []

    def _calculate_keyword_score(
        self,
        material_keywords: List[str],
        search_keywords: List[str]
    ) -> float:
        """计算关键词匹配分数"""
        if not material_keywords or not search_keywords:
            return 0.0

        score = 0.0
        search_lower = [k.lower() for k in search_keywords]
        mat_lower = [k.lower() for k in material_keywords]

        for s_kw in search_lower:
            for m_kw in mat_lower:
                if s_kw == m_kw:
                    score += 1.0
                elif s_kw in m_kw or m_kw in s_kw:
                    score += 0.5

        return score

    def increment_use_count(self, material_id: str) -> bool:
        """增加素材使用次数"""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    UPDATE materials
                    SET use_count = use_count + 1, updated_at = ?
                    WHERE material_id = ?
                """, (datetime.now().isoformat(), material_id))
            return True
        except Exception as e:
            logger.error(f"更新使用次数失败: {e}")
            return False

    def get_all(self, limit: int = 100, offset: int = 0) -> List[Material]:
        """获取所有素材（分页）"""
        try:
            with self._cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM materials ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                )
                rows = cursor.fetchall()
                return [self._row_to_material(row) for row in rows]
        except Exception as e:
            logger.error(f"获取素材列表失败: {e}")
            return []

    def count(self, file_type: Optional[str] = None) -> int:
        """统计素材数量"""
        try:
            with self._cursor() as cursor:
                if file_type:
                    cursor.execute(
                        "SELECT COUNT(*) FROM materials WHERE file_type = ?",
                        (file_type,)
                    )
                else:
                    cursor.execute("SELECT COUNT(*) FROM materials")
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"统计素材数量失败: {e}")
            return 0

    def _row_to_material(self, row: sqlite3.Row) -> Material:
        """将数据库行转换为 Material 对象"""
        return Material(
            material_id=row["material_id"],
            file_path=row["file_path"],
            file_type=row["file_type"],
            description=row["description"] or "",
            keywords=json.loads(row["keywords"] or "[]"),
            source_url=row["source_url"] or "",
            source=row["source"] or "local",
            duration=row["duration"],
            thumbnail_path=row["thumbnail_path"],
            width=row["width"],
            height=row["height"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            use_count=row["use_count"] or 0,
        )


# 全局单例
_material_db: Optional[MaterialDatabase] = None


def get_material_db(db_path: str = "./storage/materials.db") -> MaterialDatabase:
    """获取素材数据库单例"""
    global _material_db
    if _material_db is None:
        _material_db = MaterialDatabase(db_path)
    return _material_db
