# -*- coding: utf-8 -*-
"""
代码知识图谱（v0.6.0 新增）
===============================
功能：
- 代码结构分析（类、函数、变量）
- 依赖关系图谱
- 调用关系图
- 继承关系图
- 图谱可视化
- 代码导航

架构：
┌─────────────────────────────────────┐
│      CodeGraphManager                │
│  ┌────────────────────────────────┐ │
│  │ 代码解析器                      │ │
│  │ - Python AST                    │ │
│  │ - JavaScript/TypeScript         │ │
│  │ - Go                            │ │
│  └────────────────────────────────┘ │
│  ┌────────────────────────────────┐ │
│  │ 图数据库                        │ │
│  │ - Node（类/函数/变量）          │ │
│  │ - Edge（依赖/调用/继承）        │ │
│  └────────────────────────────────┘ │
└─────────────────────────────────────┘
"""

import os
import re
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

try:
    import ast
    AST_AVAILABLE = True
except ImportError:
    AST_AVAILABLE = False

from PyQt5.QtCore import QObject, pyqtSignal


# ============================================================
# 图节点类型
# ============================================================

class NodeType(Enum):
    """图节点类型"""
    MODULE = "module"        # 模块
    CLASS = "class"          # 类
    FUNCTION = "function"    # 函数
    METHOD = "method"        # 方法
    VARIABLE = "variable"    # 变量
    IMPORT = "import"        # 导入
    CONSTANT = "constant"    # 常量


class EdgeType(Enum):
    """图边类型"""
    IMPORTS = "imports"            # 导入
    DEFINES = "defines"            # 定义
    CALLS = "calls"                # 调用
    INHERITS = "inherits"          # 继承
    IMPLEMENTS = "implements"      # 实现
    USES = "uses"                  # 使用
    CONTAINS = "contains"          # 包含


# ============================================================
# 图节点
# ============================================================

@dataclass
class GraphNode:
    """图节点"""
    id: str                              # 唯一ID
    name: str                             # 名称
    type: NodeType                        # 类型
    file_path: str                        # 文件路径
    line: int                             # 行号
    column: int = 0                       # 列号
    end_line: int = 0                     # 结束行
    docstring: str = ""                   # 文档字符串
    signature: str = ""                   # 签名（函数）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "file_path": self.file_path,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "docstring": self.docstring,
            "signature": self.signature,
            "metadata": self.metadata,
        }


@dataclass
class GraphEdge:
    """图边"""
    source_id: str        # 源节点ID
    target_id: str        # 目标节点ID
    type: EdgeType        # 边类型
    weight: float = 1.0   # 权重
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type.value,
            "weight": self.weight,
            "metadata": self.metadata,
        }


# ============================================================
# 代码解析器
# ============================================================

class CodeParser:
    """代码解析器"""
    
    def __init__(self):
        self._parsers = {
            ".py": self._parse_python,
            ".js": self._parse_javascript,
            ".ts": self._parse_typescript,
            ".go": self._parse_go,
        }
    
    def parse_file(self, file_path: str) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """
        解析文件
        
        Returns:
            (nodes, edges)
        """
        ext = os.path.splitext(file_path)[1].lower()
        parser = self._parsers.get(ext)
        
        if parser:
            return parser(file_path)
        
        return [], []
    
    def _parse_python(self, file_path: str) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """解析 Python 文件"""
        nodes = []
        edges = []
        
        if not AST_AVAILABLE:
            return nodes, edges
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            
            tree = ast.parse(source, filename=file_path)
            
            # 模块节点
            module_id = f"module:{file_path}"
            module_node = GraphNode(
                id=module_id,
                name=os.path.basename(file_path),
                type=NodeType.MODULE,
                file_path=file_path,
                line=1,
            )
            nodes.append(module_node)
            
            # 遍历 AST
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # 类节点
                    class_id = f"class:{file_path}:{node.name}:{node.lineno}"
                    class_node = GraphNode(
                        id=class_id,
                        name=node.name,
                        type=NodeType.CLASS,
                        file_path=file_path,
                        line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                        docstring=ast.get_docstring(node) or "",
                    )
                    nodes.append(class_node)
                    
                    # 模块包含类
                    edges.append(GraphEdge(module_id, class_id, EdgeType.CONTAINS))
                    
                    # 继承关系
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            base_id = f"class:{file_path}:{base.id}:0"
                            edges.append(GraphEdge(class_id, base_id, EdgeType.INHERITS))
                
                elif isinstance(node, ast.FunctionDef):
                    # 函数节点
                    func_id = f"function:{file_path}:{node.name}:{node.lineno}"
                    
                    # 判断是函数还是方法
                    func_type = NodeType.FUNCTION
                    # 简单判断：如果缩进 > 0，可能是方法
                    if hasattr(node, 'col_offset') and node.col_offset > 0:
                        func_type = NodeType.METHOD
                    
                    # 获取签名
                    args = []
                    for arg in node.args.args:
                        args.append(arg.arg)
                    signature = f"{node.name}({', '.join(args)})"
                    
                    func_node = GraphNode(
                        id=func_id,
                        name=node.name,
                        type=func_type,
                        file_path=file_path,
                        line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                        docstring=ast.get_docstring(node) or "",
                        signature=signature,
                    )
                    nodes.append(func_node)
                    
                    # 模块包含函数
                    edges.append(GraphEdge(module_id, func_id, EdgeType.CONTAINS))
                    
                    # 函数调用关系
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            if isinstance(child.func, ast.Name):
                                called_func_id = f"function:{file_path}:{child.func.id}:0"
                                edges.append(GraphEdge(func_id, called_func_id, EdgeType.CALLS))
                
                elif isinstance(node, ast.Import):
                    # 导入节点
                    for alias in node.names:
                        import_id = f"import:{file_path}:{alias.name}:{node.lineno}"
                        import_node = GraphNode(
                            id=import_id,
                            name=alias.name,
                            type=NodeType.IMPORT,
                            file_path=file_path,
                            line=node.lineno,
                        )
                        nodes.append(import_node)
                        edges.append(GraphEdge(module_id, import_id, EdgeType.IMPORTS))
        
        except Exception as e:
            print(f"[CodeGraph] 解析 Python 文件失败: {file_path}: {e}")
        
        return nodes, edges
    
    def _parse_javascript(self, file_path: str) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """解析 JavaScript 文件（简化版）"""
        nodes = []
        edges = []
        
        # 简化解析：使用正则表达式
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            
            # 查找函数定义
            func_pattern = r'function\s+(\w+)\s*\('
            for match in re.finditer(func_pattern, source):
                func_name = match.group(1)
                line = source[:match.start()].count('\n') + 1
                
                func_id = f"function:{file_path}:{func_name}:{line}"
                func_node = GraphNode(
                    id=func_id,
                    name=func_name,
                    type=NodeType.FUNCTION,
                    file_path=file_path,
                    line=line,
                )
                nodes.append(func_node)
            
            # 查找类定义
            class_pattern = r'class\s+(\w+)'
            for match in re.finditer(class_pattern, source):
                class_name = match.group(1)
                line = source[:match.start()].count('\n') + 1
                
                class_id = f"class:{file_path}:{class_name}:{line}"
                class_node = GraphNode(
                    id=class_id,
                    name=class_name,
                    type=NodeType.CLASS,
                    file_path=file_path,
                    line=line,
                )
                nodes.append(class_node)
        
        except Exception as e:
            print(f"[CodeGraph] 解析 JavaScript 文件失败: {file_path}: {e}")
        
        return nodes, edges
    
    def _parse_typescript(self, file_path: str) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """解析 TypeScript 文件（与 JavaScript 类似）"""
        return self._parse_javascript(file_path)
    
    def _parse_go(self, file_path: str) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """解析 Go 文件（简化版）"""
        nodes = []
        edges = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            
            # 查找函数定义
            func_pattern = r'func\s+(\w+)\s*\('
            for match in re.finditer(func_pattern, source):
                func_name = match.group(1)
                line = source[:match.start()].count('\n') + 1
                
                func_id = f"function:{file_path}:{func_name}:{line}"
                func_node = GraphNode(
                    id=func_id,
                    name=func_name,
                    type=NodeType.FUNCTION,
                    file_path=file_path,
                    line=line,
                )
                nodes.append(func_node)
        
        except Exception as e:
            print(f"[CodeGraph] 解析 Go 文件失败: {file_path}: {e}")
        
        return nodes, edges


# ============================================================
# 代码图谱管理器
# ============================================================

class CodeGraphManager(QObject):
    """
    代码知识图谱管理器
    
    功能：
    - 解析代码文件
    - 构建图谱
    - 查询节点/边
    - 分析依赖关系
    - 代码导航
    """
    
    # 信号
    graph_updated = pyqtSignal()
    node_added = pyqtSignal(dict)
    edge_added = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        
        # 代码解析器
        self.parser = CodeParser()
        
        # 图数据库
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []
        
        # 索引
        self._file_index: Dict[str, List[str]] = defaultdict(list)  # {file_path: [node_ids]}
        self._name_index: Dict[str, List[str]] = defaultdict(list)  # {name: [node_ids]}
    
    def parse_project(self, project_path: str, exclude_dirs: List[str] = None):
        """
        解析整个项目
        
        Args:
            project_path: 项目路径
            exclude_dirs: 排除的目录
        """
        exclude_dirs = exclude_dirs or ['.git', '__pycache__', 'node_modules', 'venv', 'env', 'dist', 'build']
        
        # 遍历项目目录
        for root, dirs, files in os.walk(project_path):
            # 排除目录
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                # 检查文件扩展名
                ext = os.path.splitext(file)[1].lower()
                if ext in self.parser._parsers:
                    file_path = os.path.join(root, file)
                    self.parse_file(file_path)
        
        self.graph_updated.emit()
    
    def parse_file(self, file_path: str):
        """解析单个文件"""
        nodes, edges = self.parser.parse_file(file_path)
        
        # 添加节点
        for node in nodes:
            self.add_node(node)
        
        # 添加边
        for edge in edges:
            self.add_edge(edge)
    
    def add_node(self, node: GraphNode):
        """添加节点"""
        self._nodes[node.id] = node
        
        # 更新索引
        self._file_index[node.file_path].append(node.id)
        self._name_index[node.name].append(node.id)
        
        self.node_added.emit(node.to_dict())
    
    def add_edge(self, edge: GraphEdge):
        """添加边"""
        self._edges.append(edge)
        self.edge_added.emit(edge.to_dict())
    
    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """获取节点"""
        return self._nodes.get(node_id)
    
    def find_nodes_by_name(self, name: str) -> List[GraphNode]:
        """按名称查找节点"""
        node_ids = self._name_index.get(name, [])
        return [self._nodes[nid] for nid in node_ids if nid in self._nodes]
    
    def find_nodes_by_file(self, file_path: str) -> List[GraphNode]:
        """按文件查找节点"""
        node_ids = self._file_index.get(file_path, [])
        return [self._nodes[nid] for nid in node_ids if nid in self._nodes]
    
    def get_outgoing_edges(self, node_id: str, edge_type: EdgeType = None) -> List[GraphEdge]:
        """获取出边"""
        edges = []
        for edge in self._edges:
            if edge.source_id == node_id:
                if edge_type is None or edge.type == edge_type:
                    edges.append(edge)
        return edges
    
    def get_incoming_edges(self, node_id: str, edge_type: EdgeType = None) -> List[GraphEdge]:
        """获取入边"""
        edges = []
        for edge in self._edges:
            if edge.target_id == node_id:
                if edge_type is None or edge.type == edge_type:
                    edges.append(edge)
        return edges
    
    def get_dependencies(self, node_id: str, depth: int = 1) -> Dict[str, List[GraphNode]]:
        """
        获取依赖关系
        
        Args:
            node_id: 节点ID
            depth: 递归深度
        
        Returns:
            {"dependencies": [...], "dependents": [...]}
        """
        dependencies = set()
        dependents = set()
        
        # 递归获取依赖
        def _collect_deps(current_id: str, current_depth: int, is_dependency: bool):
            if current_depth > depth:
                return
            
            if is_dependency:
                edges = self.get_outgoing_edges(current_id, EdgeType.IMPORTS)
                edges += self.get_outgoing_edges(current_id, EdgeType.CALLS)
                
                for edge in edges:
                    if edge.target_id in self._nodes:
                        dependencies.add(self._nodes[edge.target_id])
                        _collect_deps(edge.target_id, current_depth + 1, True)
            
            else:
                edges = self.get_incoming_edges(current_id, EdgeType.IMPORTS)
                edges += self.get_incoming_edges(current_id, EdgeType.CALLS)
                
                for edge in edges:
                    if edge.source_id in self._nodes:
                        dependents.add(self._nodes[edge.source_id])
                        _collect_deps(edge.source_id, current_depth + 1, False)
        
        _collect_deps(node_id, 0, True)
        _collect_deps(node_id, 0, False)
        
        return {
            "dependencies": list(dependencies),
            "dependents": list(dependents),
        }
    
    def get_call_graph(self, func_id: str) -> Dict[str, List[str]]:
        """
        获取函数调用图
        
        Returns:
            {func_id: [called_func_ids]}
        """
        call_graph = defaultdict(list)
        
        def _build_call_graph(current_id: str, visited: Set[str]):
            if current_id in visited:
                return
            
            visited.add(current_id)
            
            # 获取函数调用
            call_edges = self.get_outgoing_edges(current_id, EdgeType.CALLS)
            
            for edge in call_edges:
                call_graph[current_id].append(edge.target_id)
                _build_call_graph(edge.target_id, visited)
        
        _build_call_graph(func_id, set())
        
        return dict(call_graph)
    
    def get_inheritance_tree(self, class_id: str) -> Dict[str, List[str]]:
        """
        获取继承树
        
        Returns:
            {class_id: [parent_class_ids]}
        """
        tree = defaultdict(list)
        
        def _build_inheritance_tree(current_id: str, visited: Set[str]):
            if current_id in visited:
                return
            
            visited.add(current_id)
            
            # 获取父类
            inherit_edges = self.get_outgoing_edges(current_id, EdgeType.INHERITS)
            
            for edge in inherit_edges:
                tree[current_id].append(edge.target_id)
                _build_inheritance_tree(edge.target_id, visited)
        
        _build_inheritance_tree(class_id, set())
        
        return dict(tree)
    
    def search_nodes(self, query: str, node_type: NodeType = None) -> List[GraphNode]:
        """
        搜索节点
        
        Args:
            query: 查询字符串
            node_type: 节点类型过滤
        """
        results = []
        query_lower = query.lower()
        
        for node in self._nodes.values():
            # 名称匹配
            if query_lower in node.name.lower():
                if node_type is None or node.type == node_type:
                    results.append(node)
            
            # 文件路径匹配
            elif query_lower in node.file_path.lower():
                if node_type is None or node.type == node_type:
                    results.append(node)
        
        return results
    
    def clear(self):
        """清空图谱"""
        self._nodes.clear()
        self._edges.clear()
        self._file_index.clear()
        self._name_index.clear()