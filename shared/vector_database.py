# -*- coding: utf-8 -*-
"""
向量数据库集成（v0.6.0 新增）
================================
功能：
- ChromaDB 向量存储
- 文档向量化（TF-IDF / Sentence Transformers）
- 相似度检索
- 语义搜索
- 知识库持久化

架构：
┌──────────────────────────────────┐
│    VectorDatabaseManager          │
│  ┌──────────────────────────────┐│
│  │ ChromaDB Client              ││
│  │ - create_collection()        ││
│  │ - add_documents()            ││
│  │ - query_similar()            ││
│  └──────────────────────────────┘│
│  ┌──────────────────────────────┐│
│  │ Embedding Models             ││
│  │ - TFIDFVectorizer (内置)     ││
│  │ - SentenceTransformer (可选) ││
│  └──────────────────────────────┘│
└──────────────────────────────────┘
"""

import os
import json
import hashlib
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("[VectorDB] ChromaDB 未安装，使用内置 TF-IDF 向量化器")

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from PyQt5.QtCore import QObject, pyqtSignal

# 内置 TF-IDF 向量化器（v0.5.0 已实现）
# ★ 修复：从 shared.knowledge_base 导入，而不是不存在的 core.memory
try:
    from shared.knowledge_base import TFIDFVectorizer
except ImportError:
    try:
        from knowledge_base import TFIDFVectorizer
    except ImportError:
        # 如果都导入失败，提供一个简单的降级实现
        import math
        import re
        
        class TFIDFVectorizer:
            """简单的 TF-IDF 向量化器降级实现"""
            
            def __init__(self):
                self._vocab = {}
                self._idf = {}
            
            def _tokenize(self, text: str):
                tokens = []
                for ch in text:
                    if '\u4e00' <= ch <= '\u9fff':
                        tokens.append(ch)
                tokens.extend(re.findall(r'[a-zA-Z]+', text.lower()))
                tokens.extend(re.findall(r'\d+', text))
                return tokens
            
            def fit(self, documents):
                doc_count = len(documents)
                self._idf = {}
                for term in set(tokens for doc in documents for tokens in [self._tokenize(doc)]):
                    doc_freq = sum(1 for doc in documents if term in self._tokenize(doc))
                    self._idf[term] = math.log((doc_count + 1) / (doc_freq + 1)) + 1
                return self
            
            def transform(self, documents):
                result = []
                for doc in documents:
                    tokens = self._tokenize(doc)
                    tf = {}
                    for token in tokens:
                        tf[token] = tf.get(token, 0) + 1
                    max_tf = max(tf.values()) if tf else 1
                    vector = []
                    for term, idf_val in self._idf.items():
                        tfidf = (tf.get(term, 0) / max_tf) * idf_val
                        vector.append(tfidf)
                    result.append(vector)
                return result
            
            def embed(self, text: str) -> List[float]:
                vectors = self.transform([text])
                return vectors[0] if vectors else []
            
            def batch_embed(self, texts: List[str]) -> List[List[float]]:
                return self.transform(texts)


# ============================================================
# 向量化模型接口
# ============================================================

class EmbeddingModelInterface:
    """向量化模型接口"""
    
    def embed(self, text: str) -> List[float]:
        """将文本转换为向量"""
        raise NotImplementedError
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量向量化"""
        return [self.embed(t) for t in texts]


# ============================================================
# TF-IDF 向量化模型（内置，无外部依赖）
# ============================================================

class TFIDFEmbeddingModel(EmbeddingModelInterface):
    """基于 TF-IDF 的向量化模型"""

    def __init__(self):
        self.vectorizer = TFIDFVectorizer()
        self._fitted = False
        self._default_docs = [
            "hello world", "test text", "default document",
            "sample input", "example query", "数据查询",
            "文本搜索", "语义匹配", "向量化", "知识库",
        ]
        # 初始 fit，确保 transform 可用
        self.vectorizer.fit(self._default_docs)
        self._fitted = True

    def _sparse_to_dense(self, sparse_vec: dict, dim: int = 256) -> List[float]:
        """将稀疏 TF-IDF 向量转换为固定维度 dense 向量"""
        dense = [0.0] * dim
        for i, (token, val) in enumerate(sorted(sparse_vec.items())):
            if i >= dim:
                break
            dense[i] = val
        return dense

    def embed(self, text: str) -> List[float]:
        """将文本转换为 TF-IDF 向量（dense 格式）"""
        sparse_vec = self.vectorizer.transform(text)
        return self._sparse_to_dense(sparse_vec)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量向量化"""
        return [self.embed(t) for t in texts]


# ============================================================
# Sentence Transformers 向量化模型（可选，高质量）
# ============================================================

class SentenceTransformerModel(EmbeddingModelInterface):
    """基于 Sentence Transformers 的向量化模型"""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError("Sentence Transformers 未安装")
        
        self.model = SentenceTransformer(model_name)
    
    def embed(self, text: str) -> List[float]:
        """将文本转换为向量"""
        embedding = self.model.encode(text)
        return embedding.tolist()
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量向量化（性能更好）"""
        embeddings = self.model.encode(texts)
        return [e.tolist() for e in embeddings]


# ============================================================
# Ollama 嵌入模型（本地部署，无外部模型依赖）
# ============================================================

class OllamaEmbeddingModel(EmbeddingModelInterface):
    """基于 Ollama API 的向量化模型

    使用本地 Ollama 服务生成文本嵌入，支持 nomic-embed-text 等模型。
    自动降级：Ollama 不可用时回退到 TFIDFEmbeddingModel。
    """

    def __init__(self, model_name: str = "nomic-embed-text",
                 base_url: str = "http://127.0.0.1:11434"):
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests 库未安装，无法使用 Ollama 嵌入模型")
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self._fallback = TFIDFEmbeddingModel()
        # 启动时检查 Ollama 可用性
        self._available = self._check_available()
        if self._available:
            print(f"[OllamaEmbedding] 使用 {model_name} 模型 ({base_url})")
        else:
            print(f"[OllamaEmbedding] Ollama 不可用，降级到 TF-IDF")

    def _check_available(self) -> bool:
        """检查 Ollama 服务和嵌入模型是否可用"""
        try:
            resp = _requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                # 检查目标模型或其基础名称是否已安装
                for name in model_names:
                    if self.model_name in name or name.startswith(self.model_name.split(":")[0]):
                        return True
                print(f"[OllamaEmbedding] 模型 {self.model_name} 未安装，"
                      f"可用模型: {[m.get('name') for m in models[:5]]}")
            return False
        except Exception as e:
            print(f"[OllamaEmbedding] 连接失败: {e}")
            return False

    def embed(self, text: str) -> List[float]:
        """将文本转换为向量（通过 Ollama /api/embeddings）"""
        if not self._available:
            return self._fallback.embed(text)
        try:
            resp = _requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model_name, "prompt": text},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                embedding = data.get("embedding")
                if embedding and isinstance(embedding, list):
                    return embedding
            # 失败降级
            return self._fallback.embed(text)
        except Exception as e:
            print(f"[OllamaEmbedding] 嵌入请求失败: {e}, 降级到 TF-IDF")
            return self._fallback.embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量向量化"""
        if not self._available:
            return self._fallback.embed_batch(texts)
        # Ollama 不支持批量嵌入 API，逐条调用
        results = []
        for text in texts:
            results.append(self.embed(text))
        return results


# ============================================================
# 文档数据结构
# ============================================================

@dataclass
class VectorDocument:
    """向量文档"""
    id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
        }


# ============================================================
# 向量数据库管理器
# ============================================================

class VectorDatabaseManager(QObject):
    """
    向量数据库管理器
    
    支持：
    - ChromaDB（推荐）
    - 内置 TF-IDF 向量存储（备用）
    
    功能：
    - 文档向量化存储
    - 相似度检索
    - 语义搜索
    - 集合管理
    """
    
    # 信号
    document_added = pyqtSignal(str)  # (doc_id)
    document_removed = pyqtSignal(str)  # (doc_id)
    search_completed = pyqtSignal(list)  # (results)
    
    def __init__(self, db_path: str = "vector_db", embedding_type: str = "tfidf"):
        super().__init__()
        self.db_path = db_path
        self.embedding_type = embedding_type
        
        # 向量化模型
        if embedding_type == "sentence_transformer" and SENTENCE_TRANSFORMERS_AVAILABLE:
            self.embedding_model = SentenceTransformerModel()
        elif embedding_type == "ollama" and REQUESTS_AVAILABLE:
            try:
                self.embedding_model = OllamaEmbeddingModel()
            except Exception:
                self.embedding_model = TFIDFEmbeddingModel()
        else:
            self.embedding_model = TFIDFEmbeddingModel()
        
        # ChromaDB 客户端
        self.chroma_client = None
        self.collections: Dict[str, Any] = {}
        
        # 内置向量存储（备用）
        self._builtin_store: Dict[str, Dict[str, VectorDocument]] = {}
        
        # 初始化数据库
        self._init_database()
    
    def _init_database(self):
        """初始化向量数据库"""
        if CHROMADB_AVAILABLE:
            try:
                # 创建 ChromaDB 客户端（持久化模式）
                settings = Settings(
                    chroma_db_impl="duckdb+parquet",
                    persist_directory=self.db_path,
                )
                self.chroma_client = chromadb.Client(settings)
                print(f"[VectorDB] ChromaDB 初始化成功: {self.db_path}")
            except Exception as e:
                print(f"[VectorDB] ChromaDB 初始化失败: {e}")
                self.chroma_client = None
        
        # 如果 ChromaDB 不可用，使用内置存储
        if not self.chroma_client:
            print("[VectorDB] 使用内置 TF-IDF 向量存储")
            self._builtin_store = {}
    
    def create_collection(self, collection_name: str, metadata: Dict = None) -> bool:
        """
        创建向量集合
        
        Args:
            collection_name: 集合名称
            metadata: 集合元数据
        
        Returns:
            是否创建成功
        """
        if self.chroma_client:
            try:
                collection = self.chroma_client.create_collection(
                    name=collection_name,
                    metadata=metadata or {},
                )
                self.collections[collection_name] = collection
                print(f"[VectorDB] 集合创建成功: {collection_name}")
                return True
            except Exception as e:
                print(f"[VectorDB] 集合创建失败: {e}")
                return False
        else:
            # 内置存储
            self._builtin_store[collection_name] = {}
            return True
    
    def get_collection(self, collection_name: str) -> Optional[Any]:
        """获取向量集合"""
        if self.chroma_client:
            if collection_name in self.collections:
                return self.collections[collection_name]
            
            try:
                collection = self.chroma_client.get_collection(collection_name)
                self.collections[collection_name] = collection
                return collection
            except Exception:
                return None
        else:
            return self._builtin_store.get(collection_name)
    
    def add_document(self, collection_name: str, document: VectorDocument) -> bool:
        """
        添加文档到集合
        
        Args:
            collection_name: 集合名称
            document: 文档对象
        
        Returns:
            是否添加成功
        """
        collection = self.get_collection(collection_name)
        if not collection:
            # 自动创建集合
            if not self.create_collection(collection_name):
                return False
            collection = self.get_collection(collection_name)
        
        # 向量化文档
        if not document.embedding:
            document.embedding = self.embedding_model.embed(document.content)
        
        if self.chroma_client and collection:
            try:
                collection.add(
                    ids=[document.id],
                    documents=[document.content],
                    embeddings=[document.embedding],
                    metadatas=[document.metadata],
                )
                self.document_added.emit(document.id)
                return True
            except Exception as e:
                print(f"[VectorDB] 添加文档失败: {e}")
                return False
        else:
            # 内置存储
            self._builtin_store[collection_name][document.id] = document
            self.document_added.emit(document.id)
            return True
    
    def add_documents_batch(self, collection_name: str, documents: List[VectorDocument]) -> int:
        """
        批量添加文档
        
        Returns:
            成功添加的文档数量
        """
        success_count = 0
        
        # 批量向量化
        texts = [d.content for d in documents]
        embeddings = self.embedding_model.embed_batch(texts)
        
        for i, doc in enumerate(documents):
            doc.embedding = embeddings[i]
            if self.add_document(collection_name, doc):
                success_count += 1
        
        return success_count
    
    def remove_document(self, collection_name: str, doc_id: str) -> bool:
        """移除文档"""
        collection = self.get_collection(collection_name)
        if not collection:
            return False
        
        if self.chroma_client and collection:
            try:
                collection.delete(ids=[doc_id])
                self.document_removed.emit(doc_id)
                return True
            except Exception:
                return False
        else:
            if doc_id in self._builtin_store[collection_name]:
                del self._builtin_store[collection_name][doc_id]
                self.document_removed.emit(doc_id)
                return True
        
        return False
    
    def query_similar(
        self,
        collection_name: str,
        query: str,
        n_results: int = 5,
        where: Dict = None
    ) -> List[Dict]:
        """
        查询相似文档
        
        Args:
            collection_name: 集合名称
            query: 查询文本
            n_results: 返回结果数量
            where: 元数据过滤条件
        
        Returns:
            相似文档列表 [{id, content, metadata, distance}]
        """
        collection = self.get_collection(collection_name)
        if not collection:
            return []
        
        # 向量化查询
        query_embedding = self.embedding_model.embed(query)
        
        if self.chroma_client and collection:
            try:
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results,
                    where=where,
                )
                
                # 解析结果
                formatted_results = []
                if results and results.get('ids'):
                    for i, doc_id in enumerate(results['ids'][0]):
                        formatted_results.append({
                            'id': doc_id,
                            'content': results['documents'][0][i] if results.get('documents') else '',
                            'metadata': results['metadatas'][0][i] if results.get('metadatas') else {},
                            'distance': results['distances'][0][i] if results.get('distances') else 0.0,
                        })
                
                self.search_completed.emit(formatted_results)
                return formatted_results
            
            except Exception as e:
                print(f"[VectorDB] 查询失败: {e}")
                return []
        else:
            # 内置 TF-IDF 检索
            results = []
            store = self._builtin_store[collection_name]
            
            for doc_id, doc in store.items():
                # 计算余弦相似度
                if doc.embedding:
                    similarity = self._cosine_similarity(query_embedding, doc.embedding)
                    results.append({
                        'id': doc_id,
                        'content': doc.content,
                        'metadata': doc.metadata,
                        'distance': 1.0 - similarity,  # ChromaDB 返回距离（越小越相似）
                    })
            
            # 按相似度排序
            results.sort(key=lambda x: x['distance'])
            return results[:n_results]
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        import math
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def semantic_search(
        self,
        collection_name: str,
        query: str,
        threshold: float = 0.7
    ) -> List[Dict]:
        """
        语义搜索（返回相似度超过阈值的文档）
        
        Args:
            threshold: 相似度阈值（0-1）
        
        Returns:
            符合条件的文档列表
        """
        results = self.query_similar(collection_name, query, n_results=20)
        
        # 过滤低相似度结果
        filtered = []
        for r in results:
            similarity = 1.0 - r['distance']
            if similarity >= threshold:
                r['similarity'] = similarity
                filtered.append(r)
        
        return filtered
    
    def get_collection_stats(self, collection_name: str) -> Dict:
        """获取集合统计信息"""
        collection = self.get_collection(collection_name)
        if not collection:
            return {}
        
        if self.chroma_client and collection:
            try:
                count = collection.count()
                return {
                    'name': collection_name,
                    'count': count,
                    'type': 'chromadb',
                }
            except Exception:
                return {}
        else:
            return {
                'name': collection_name,
                'count': len(self._builtin_store[collection_name]),
                'type': 'builtin',
            }
    
    def list_collections(self) -> List[str]:
        """列出所有集合"""
        if self.chroma_client:
            try:
                collections = self.chroma_client.list_collections()
                return [c.name for c in collections]
            except Exception:
                return list(self.collections.keys())
        else:
            return list(self._builtin_store.keys())
    
    def delete_collection(self, collection_name: str) -> bool:
        """删除集合"""
        if self.chroma_client:
            try:
                self.chroma_client.delete_collection(collection_name)
                if collection_name in self.collections:
                    del self.collections[collection_name]
                return True
            except Exception:
                return False
        else:
            if collection_name in self._builtin_store:
                del self._builtin_store[collection_name]
                return True
        
        return False


# ============================================================
# 向量数据库配置
# ============================================================

VECTOR_DB_CONFIG = {
    "db_path": "vector_db",
    "embedding_type": "tfidf",  # tfidf / sentence_transformer
    "sentence_transformer_model": "all-MiniLM-L6-v2",
    "default_collection": "knowledge_base",
}