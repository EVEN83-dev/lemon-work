# -*- coding: utf-8 -*-
"""
Skill 市场后端 API
==================
提供 Skill 注册、搜索、评分、下载等功能。

主要功能：
1. Skill 注册（用户上传自定义 skill）
2. Skill 搜索/筛选（按名称/分类/评分）
3. Skill 评分系统（用户评分 + 平均分）
4. Skill 下载/安装（复制到本地 skill 目录）

使用方法：
    from core.skill_market import SkillMarket
    
    market = SkillMarket()
    
    # 注册 Skill
    market.register_skill("my_skill", {
        "name": "my_skill",
        "description": "我的自定义 Skill",
        "author": "user",
        "category": "custom",
        "handler": my_handler,
    })
    
    # 搜索 Skill
    skills = market.search_skills("math")
    
    # 评分 Skill
    market.rate_skill("my_skill", 5, "非常好用！")
    
    # 下载 Skill
    market.download_skill("my_skill", "/path/to/skills/")
"""

import os
import json
import shutil
import threading
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================
# Skill 元数据
# ============================================================
@dataclass
class SkillMeta:
    """Skill 元数据"""
    name: str
    description: str
    author: str
    category: str = "general"
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    downloads: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "version": self.version,
            "tags": self.tags,
            "downloads": self.downloads,
            "rating_avg": self.rating_avg,
            "rating_count": self.rating_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ============================================================
# Skill 评分
# ============================================================
@dataclass
class SkillRating:
    """Skill 评分"""
    skill_name: str
    user_id: str
    rating: int  # 1-5 星
    comment: str = ""
    created_at: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "skill_name": self.skill_name,
            "user_id": self.user_id,
            "rating": self.rating,
            "comment": self.comment,
            "created_at": self.created_at,
        }


# ============================================================
# Skill 市场
# ============================================================
def _generate_skill_module(meta: SkillMeta) -> str:
    """从元数据生成最小可注册 skill 模块"""
    tags_str = ", ".join(str(t) for t in meta.tags) if meta.tags else ""
    lines = [
        "from bridge.skills.models import SkillDef, SkillResult",
        "",
        "",
        "def execute(**kwargs) -> SkillResult:",
        "    return SkillResult.ok(output='" + meta.name + " placeholder')",
        "",
        "",
        "def register(registry) -> None:",
        "    registry.register(SkillDef(",
        "        name='" + meta.name + "',",
        "        description='" + meta.description.replace("'", "\\'") + "',",
        "        category='" + meta.category + "',",
        "        handler=execute,",
        "    ))",
    ]
    return "\n".join(lines) + "\n"


class SkillMarket:
    """
    Skill 市场 — 管理自定义 Skill 的注册、搜索、评分、下载
    
    存储位置：
        - ~/.lemoncode/skill_market/skills/  — Skill 元数据
        - ~/.lemoncode/skill_market/ratings/ — Skill 评分
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        初始化 Skill 市场
        
        Args:
            storage_path: 存储路径（默认 ~/.lemoncode/skill_market/）
        """
        # 设置存储路径
        if storage_path is None:
            home = os.path.expanduser("~")
            storage_path = os.path.join(home, ".lemoncode", "skill_market")
        
        self.storage_path = storage_path
        self.skills_path = os.path.join(storage_path, "skills")
        self.ratings_path = os.path.join(storage_path, "ratings")
        
        # 确保目录存在
        os.makedirs(self.skills_path, exist_ok=True)
        os.makedirs(self.ratings_path, exist_ok=True)
        
        # 内存缓存
        self._skills: Dict[str, SkillMeta] = {}
        self._ratings: Dict[str, List[SkillRating]] = {}
        self._lock = threading.Lock()
        
        # 加载已有数据
        self._load_all()
    
    # ==================== Skill 注册 ====================
    
    def register_skill(self, skill_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        注册 Skill
        
        Args:
            skill_data: Skill 数据，包含 name/description/author/category 等
        
        Returns:
            Dict: 注册结果
        """
        name = skill_data.get("name", "")
        if not name:
            return {"success": False, "error": "Skill 名称不能为空"}
        
        with self._lock:
            # 创建 SkillMeta
            now = datetime.now().isoformat()
            meta = SkillMeta(
                name=name,
                description=skill_data.get("description", ""),
                author=skill_data.get("author", "unknown"),
                category=skill_data.get("category", "general"),
                version=skill_data.get("version", "1.0.0"),
                tags=skill_data.get("tags", []),
                created_at=now,
                updated_at=now,
            )
            
            # 保存到内存和文件
            self._skills[name] = meta
            self._save_skill(meta)
            
            return {
                "success": True,
                "skill": meta.to_dict(),
            }
    
    def unregister_skill(self, name: str) -> Dict[str, Any]:
        """
        注销 Skill
        
        Args:
            name: Skill 名称
        
        Returns:
            Dict: 注销结果
        """
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"Skill '{name}' 不存在"}
            
            # 从内存和文件删除
            del self._skills[name]
            self._delete_skill(name)
            
            return {"success": True}
    
    # ==================== Skill 搜索 ====================
    
    def search_skills(
        self,
        query: str = "",
        category: str = "",
        author: str = "",
        min_rating: float = 0.0,
        limit: int = 50,
    ) -> List[Dict]:
        """
        搜索 Skill
        
        Args:
            query: 搜索关键词（匹配名称/描述）
            category: 分类筛选
            author: 作者筛选
            min_rating: 最低评分筛选
            limit: 返回数量限制
        
        Returns:
            List[Dict]: Skill 列表
        """
        results = []
        
        with self._lock:
            for meta in self._skills.values():
                # 分类筛选
                if category and meta.category != category:
                    continue
                
                # 作者筛选
                if author and meta.author != author:
                    continue
                
                # 评分筛选
                if meta.rating_avg < min_rating:
                    continue
                
                # 关键词搜索
                if query:
                    query_lower = query.lower()
                    if (query_lower not in meta.name.lower() and
                        query_lower not in meta.description.lower() and
                        query_lower not in " ".join(meta.tags).lower()):
                        continue
                
                results.append(meta.to_dict())
        
        # 按下载量排序
        results.sort(key=lambda x: x.get("downloads", 0), reverse=True)
        
        # 限制数量
        return results[:limit]
    
    def get_skill(self, name: str) -> Optional[Dict]:
        """
        获取 Skill 详情
        
        Args:
            name: Skill 名称
        
        Returns:
            Dict: Skill 详情（包含评分列表）
        """
        with self._lock:
            meta = self._skills.get(name)
            if meta is None:
                return None
            
            result = meta.to_dict()
            result["ratings"] = [r.to_dict() for r in self._ratings.get(name, [])]
            return result
    
    def list_categories(self) -> List[str]:
        """列出所有分类"""
        categories = set()
        with self._lock:
            for meta in self._skills.values():
                categories.add(meta.category)
        return sorted(list(categories))
    
    # ==================== Skill 评分 ====================
    
    def rate_skill(
        self,
        skill_name: str,
        user_id: str,
        rating: int,
        comment: str = "",
    ) -> Dict[str, Any]:
        """
        评分 Skill
        
        Args:
            skill_name: Skill 名称
            user_id: 用户 ID
            rating: 评分（1-5 星）
            comment: 评论
        
        Returns:
            Dict: 评分结果
        """
        # 验证评分
        if not 1 <= rating <= 5:
            return {"success": False, "error": "评分必须在 1-5 之间"}
        
        with self._lock:
            # 检查 Skill 是否存在
            if skill_name not in self._skills:
                return {"success": False, "error": f"Skill '{skill_name}' 不存在"}
            
            # 检查用户是否已评分
            existing_rating = None
            for r in self._ratings.get(skill_name, []):
                if r.user_id == user_id:
                    existing_rating = r
                    break
            
            # 创建评分
            now = datetime.now().isoformat()
            new_rating = SkillRating(
                skill_name=skill_name,
                user_id=user_id,
                rating=rating,
                comment=comment,
                created_at=now,
            )
            
            # 更新或添加评分
            if existing_rating:
                self._ratings[skill_name].remove(existing_rating)
            
            if skill_name not in self._ratings:
                self._ratings[skill_name] = []
            self._ratings[skill_name].append(new_rating)
            
            # 更新平均分
            self._update_rating_avg(skill_name)
            
            # 保存到文件
            self._save_rating(skill_name, new_rating)
            
            return {
                "success": True,
                "rating": new_rating.to_dict(),
            }
    
    def _update_rating_avg(self, skill_name: str):
        """更新 Skill 平均分"""
        ratings = self._ratings.get(skill_name, [])
        if not ratings:
            return
        
        total = sum(r.rating for r in ratings)
        avg = total / len(ratings)
        
        meta = self._skills.get(skill_name)
        if meta:
            meta.rating_avg = round(avg, 2)
            meta.rating_count = len(ratings)
            self._save_skill(meta)
    
    # ==================== Skill 下载 ====================
    
    def download_skill(self, name: str, target_path: str) -> Dict[str, Any]:
        """
        下载 Skill（复制到目标路径）
        
        Args:
            name: Skill 名称
            target_path: 目标路径（目录或文件路径）
        
        Returns:
            Dict: 下载结果
        """
        with self._lock:
            meta = self._skills.get(name)
            if meta is None:
                return {"success": False, "error": "Skill '" + name + "' not found"}
            
            meta.downloads += 1
            self._save_skill(meta)
        
        source_file = os.path.join(self.skills_path, name + ".py")
        source_code = meta.metadata.get("source_code", "") if hasattr(meta, 'metadata') else ""
        
        if not os.path.isdir(target_path):
            os.makedirs(target_path, exist_ok=True)
        
        dest_file = os.path.join(target_path, name + ".py")
        
        if os.path.exists(source_file):
            try:
                shutil.copy2(source_file, dest_file)
            except Exception as e:
                return {
                    "success": False,
                    "error": "Copy failed: " + str(e),
                    "skill": meta.to_dict(),
                    "target_path": target_path,
                }
        elif source_code:
            try:
                with open(dest_file, 'w', encoding='utf-8') as f:
                    f.write(source_code)
            except Exception as e:
                return {
                    "success": False,
                    "error": "Write failed: " + str(e),
                    "skill": meta.to_dict(),
                    "target_path": target_path,
                }
        else:
            generated = _generate_skill_module(meta)
            try:
                with open(dest_file, 'w', encoding='utf-8') as f:
                    f.write(generated)
            except Exception as e:
                return {
                    "success": False,
                    "error": "Generate failed: " + str(e),
                    "skill": meta.to_dict(),
                    "target_path": target_path,
                }
        
        return {
            "success": True,
            "skill": meta.to_dict(),
            "target_path": target_path,
            "installed_file": dest_file,
        }
    
    def install_from_registry(self, registry) -> int:
        """从 SkillsRegistry 同步已注册的 skill 到市场"""
        count = 0
        try:
            for skill in registry.list_skills():
                skill_data = {
                    "name": skill.name,
                    "description": skill.description,
                    "author": "bridge",
                    "category": skill.category,
                    "version": getattr(skill, 'version', '1.0.0'),
                    "tags": getattr(skill.metadata, 'tags', []) if hasattr(skill, 'metadata') else [],
                }
                result = self.register_skill(skill_data)
                if result.get("success"):
                    count += 1
        except Exception:
            pass
        return count
    
    # ==================== 文件操作 ====================
    
    def _save_skill(self, meta: SkillMeta):
        """保存 Skill 元数据到文件"""
        path = os.path.join(self.skills_path, f"{meta.name}.json")
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(meta.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[SkillMarket] 保存 Skill 失败: {e}")
    
    def _delete_skill(self, name: str):
        """删除 Skill 文件"""
        path = os.path.join(self.skills_path, f"{name}.json")
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception as e:
            print(f"[SkillMarket] 删除 Skill 失败: {e}")
    
    def _save_rating(self, skill_name: str, rating: SkillRating):
        """保存评分到文件"""
        path = os.path.join(self.ratings_path, f"{skill_name}_{rating.user_id}.json")
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(rating.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[SkillMarket] 保存评分失败: {e}")
    
    def _load_all(self):
        """加载所有 Skill 和评分"""
        # 加载 Skill
        if os.path.exists(self.skills_path):
            for filename in os.listdir(self.skills_path):
                if filename.endswith('.json'):
                    path = os.path.join(self.skills_path, filename)
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            meta = SkillMeta(**data)
                            self._skills[meta.name] = meta
                    except Exception as e:
                        print(f"[SkillMarket] 加载 Skill 失败 {filename}: {e}")
        
        # 加载评分
        if os.path.exists(self.ratings_path):
            for filename in os.listdir(self.ratings_path):
                if filename.endswith('.json'):
                    path = os.path.join(self.ratings_path, filename)
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            rating = SkillRating(**data)
                            skill_name = rating.skill_name
                            if skill_name not in self._ratings:
                                self._ratings[skill_name] = []
                            self._ratings[skill_name].append(rating)
                    except Exception as e:
                        print(f"[SkillMarket] 加载评分失败 {filename}: {e}")


# ============================================================
# 导出
# ============================================================

__all__ = [
    "SkillMarket",
    "SkillMeta",
    "SkillRating",
]