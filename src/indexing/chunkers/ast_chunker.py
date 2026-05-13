import hashlib
import logging
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_typescript as tsts
import tree_sitter_c_sharp as tscs

from .chunk_models import CodeChunk

logger = logging.getLogger(__name__)

# Her dil için hangi node tiplerini "blok" kabul edeceğimizi tanımlarız.
# Neden bu yaklaşım? Çünkü fonksiyon ve sınıf sınırları, bir kodun
# bağlamsal bütünlüğünü koruyan en küçük mimari birimlerdir.
CHUNK_NODE_TYPES = {
    "python":     {"function_definition", "class_definition", "decorated_definition"},
    "typescript": {"function_declaration", "class_declaration", "method_definition",
                   "arrow_function"},
    "csharp":     {"method_declaration", "class_declaration", "constructor_declaration"},
    "go":         {"function_declaration", "method_declaration", "type_declaration"},
    "rust":       {"function_item", "impl_item", "struct_item"},
}

EXT_TO_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
}


class ASTChunker:
    def __init__(self):
        # Her dil için tree-sitter ayrıştırıcısını başlat
        self._parsers: dict[str, Parser] = {
            "python":     self._build_parser(tspython.language()),
            "typescript": self._build_parser(tsts.language_typescript()),
            "csharp":     self._build_parser(tscs.language()),
        }

    def _build_parser(self, lang_obj) -> Parser:
        lang = Language(lang_obj)
        parser = Parser(lang)
        return parser

    def chunk_file(self, file_path: str) -> list[CodeChunk]:
        """
        Bir kaynak dosyayı AST üzerinden mantıksal bloklara böler.
        """
        path = Path(file_path)
        lang = EXT_TO_LANG.get(path.suffix)
        if not lang:
            return []

        parser = self._parsers.get(lang)
        if not parser:
            return []

        source = path.read_bytes()
        tree = parser.parse(source)

        # Dosya seviyesindeki import'ları bir kez çıkar
        file_imports = self._extract_imports(tree.root_node, source, lang)

        chunks: list[CodeChunk] = []
        target_types = CHUNK_NODE_TYPES.get(lang, set())

        self._traverse_iterative(tree.root_node, source, lang, file_path,
                                 target_types, chunks, file_imports)
        return chunks

    def _traverse_iterative(self, root_node, source: bytes, language: str,
                            file_path: str, target_types: set,
                            chunks: list, file_imports: list[str]) -> None:
        stack: list[tuple] = [(root_node, None)]

        while stack:
            node, parent_class = stack.pop()

            if node.type in target_types:
                code = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                name = self._extract_name(node, source)
                chunk_type = "class" if "class" in node.type else "function"
                
                # Chunk içindeki özel call'ları çıkar
                calls = self._extract_calls(node, source, language)
                bases = self._extract_bases(node, source, language) if chunk_type == "class" else []
                config_keys = self._extract_config_usage(node, source, language)

                chunks.append(CodeChunk(
                    chunk_id=hashlib.sha256(
                        f"{file_path}:{node.start_point}".encode()
                    ).hexdigest()[:16],
                    file_path=file_path,
                    language=language,
                    chunk_type=chunk_type,
                    name=name or "anonymous",
                    code=code,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parent_class=parent_class,
                    imports=file_imports,
                    calls=calls,
                    bases=bases,
                    config_keys=config_keys,
                ))

                new_parent = name if chunk_type == "class" else parent_class
                for child in reversed(node.children):
                    stack.append((child, new_parent))
            else:
                for child in reversed(node.children):
                    stack.append((child, parent_class))

    def _extract_name(self, node, source: bytes) -> str | None:
        # Mevcut mantık: ilk identifier'ı al
        for child in node.children:
            if child.type == "identifier":
                return source[child.start_byte:child.end_byte].decode()
        return None

    def _extract_imports(self, root_node, source: bytes, language: str) -> list[str]:
        imports = []
        # Basit bir DFS ile import statement'ları bul
        stack = [root_node]
        while stack:
            node = stack.pop()
            if language == "python" and node.type in ("import_statement", "import_from_statement"):
                imports.append(source[node.start_byte:node.end_byte].decode(errors="replace").strip())
            elif language == "typescript" and node.type == "import_declaration":
                imports.append(source[node.start_byte:node.end_byte].decode(errors="replace").strip())
            elif language == "csharp" and node.type == "using_directive":
                imports.append(source[node.start_byte:node.end_byte].decode(errors="replace").strip())
            
            for child in reversed(node.children):
                stack.append(child)
        return list(set(imports))

    def _extract_calls(self, node, source: bytes, language: str) -> list[str]:
        calls = []
        stack = [node]
        while stack:
            curr = stack.pop()
            # Call node'larını yakala
            is_call = False
            if language == "python" and curr.type == "call":
                is_call = True
            elif language == "typescript" and curr.type == "call_expression":
                is_call = True
            elif language == "csharp" and curr.type == "invocation_expression":
                is_call = True
            
            if is_call:
                # Çağrılan fonksiyonun adını bulmaya çalış (genellikle ilk çocuk identifier veya member_access)
                call_name = self._extract_call_name(curr, source)
                if call_name:
                    calls.append(call_name)
            
            for child in reversed(curr.children):
                stack.append(child)
        return list(set(calls))

    def _extract_call_name(self, node, source: bytes) -> str | None:
        # node.children[0] genellikle çağrılan ifadedir
        if not node.children:
            return None
        func_node = node.children[0]
        # Basit identifier ise
        if func_node.type == "identifier":
            return source[func_node.start_byte:func_node.end_byte].decode(errors="replace")
        # obj.method() şeklinde ise (member_access / attribute)
        # Tree-sitter dilleri farklı isimlendirebilir
        return source[func_node.start_byte:func_node.end_byte].decode(errors="replace")

    def _extract_bases(self, node, source: bytes, language: str) -> list[str]:
        """Sınıfın kalıtım aldığı veya implement ettiği arayüzleri çıkarır."""
        bases = []
        if language == "python":
            # Python: class A(B, C): -> argument_list içinde
            for child in node.children:
                if child.type == "argument_list":
                    for grandchild in child.children:
                        if grandchild.type in ("identifier", "attribute"):
                            bases.append(source[grandchild.start_byte:grandchild.end_byte].decode(errors="replace"))
        elif language == "typescript":
            # TS: class A extends B implements C, D
            for child in node.children:
                if child.type in ("class_heritage", "implements_clause"):
                    for grandchild in child.children:
                        if grandchild.type in ("type_identifier", "heritage_clause"):
                             bases.append(source[grandchild.start_byte:grandchild.end_byte].decode(errors="replace"))
        elif language == "csharp":
            # C#: class A : B, C
            for child in node.children:
                if child.type == "base_list":
                    for grandchild in child.children:
                        if grandchild.type in ("identifier", "generic_name"):
                            bases.append(source[grandchild.start_byte:grandchild.end_byte].decode(errors="replace"))
        return list(set(bases))

    def _extract_config_usage(self, node, source: bytes, language: str) -> list[str]:
        """Kod içindeki konfigürasyon (env, config) kullanımlarını yakalar."""
        configs = []
        code_text = source[node.start_byte:node.end_byte].decode(errors="replace")
        
        import re
        patterns = {
            "python": [r"os\.getenv\([\"'](.*?)[\"']\)", r"os\.environ\[[\"'](.*?)[\"']\]"],
            "typescript": [r"process\.env\.( [a-zA-Z0-9_]+)", r"process\.env\[[\"'](.*?)[\"']\]"],
            "csharp": [r"Configuration\[[\"'](.*?)[\"']\]", r"Environment\.GetEnvironmentVariable\([\"'](.*?)[\"']\)"]
        }
        
        for pattern in patterns.get(language, []):
            matches = re.findall(pattern, code_text)
            configs.extend(matches)
            
        return list(set(configs))

    def _detect_language(self, path: Path) -> str:
        return EXT_TO_LANG.get(path.suffix, "unknown")
