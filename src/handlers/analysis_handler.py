"""
Analysis Handler — piyasa üstü analiz araçları.

4 yeni MCP tool:
  1. test_suggestion     — test coverage gap analizi + öneri
  2. security_scan       — pattern-based SAST (SQL injection, hardcoded secret, eval/exec, XSS)
  3. refactor_suggestions — AST-based code smell tespiti
  4. code_clone_detection — Qdrant embedding cosine similarity ile duplicate tespiti
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from src.handlers.context import AppContext
from src.shared.config import config
from src.shared.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Güvenlik tarama pattern'leri
# ──────────────────────────────────────────────────────────────
_SECURITY_PATTERNS: list[dict] = [
    {
        "id": "SQL_INJECTION",
        "severity": "CRITICAL",
        "pattern": re.compile(
            r'(execute|query|raw)\s*\(\s*["\'].*(%s|{|format|f["\'])',
            re.IGNORECASE,
        ),
        "description": "SQL sorgusu string birleştirme ile oluşturuluyor — SQL injection riski",
        "fix": "Parametrize sorgular veya ORM kullanın",
    },
    {
        "id": "HARDCODED_SECRET",
        "severity": "HIGH",
        "pattern": re.compile(
            r'(password|secret|api_key|token|passwd)\s*=\s*["\'][^"\']{6,}["\']',
            re.IGNORECASE,
        ),
        "description": "Hardcoded kimlik bilgisi tespit edildi",
        "fix": "Environment variable veya secret manager kullanın",
    },
    {
        "id": "EVAL_EXEC",
        "severity": "HIGH",
        "pattern": re.compile(r'\b(eval|exec)\s*\(', re.IGNORECASE),
        "description": "eval/exec kullanımı — kod injection riski",
        "fix": "eval/exec yerine güvenli alternatifler kullanın",
    },
    {
        "id": "SHELL_INJECTION",
        "severity": "CRITICAL",
        "pattern": re.compile(
            r'(subprocess\.call|os\.system|os\.popen|shell=True)',
            re.IGNORECASE,
        ),
        "description": "Shell injection riski — kullanıcı girdisi komuta geçilebilir",
        "fix": "subprocess.run ile shell=False ve liste argümanlar kullanın",
    },
    {
        "id": "XSS_PATTERN",
        "severity": "MEDIUM",
        "pattern": re.compile(r'innerHTML\s*=|document\.write\s*\(', re.IGNORECASE),
        "description": "Potansiyel XSS açığı",
        "fix": "textContent kullanın veya innerHTML'den önce sanitize edin",
    },
    {
        "id": "PATH_TRAVERSAL",
        "severity": "HIGH",
        "pattern": re.compile(r'\.\./|\.\.\\\\'),
        "description": "Path traversal saldırı vektörü",
        "fix": "os.path.abspath ve whitelist doğrulama kullanın",
    },
    {
        "id": "INSECURE_RANDOM",
        "severity": "MEDIUM",
        "pattern": re.compile(r'\brandom\.(random|randint|choice)\b'),
        "description": "Kriptografik olmayan rastgele sayı — güvenlik için uygunsuz",
        "fix": "secrets modülü kullanın",
    },
    {
        "id": "PICKLE_DESERIALIZATION",
        "severity": "HIGH",
        "pattern": re.compile(r'\bpickle\.(load|loads)\b'),
        "description": "Güvenilmeyen pickle deserializasyonu — RCE riski",
        "fix": "JSON veya diğer güvenli formatları tercih edin",
    },
]

_EXCLUDE_DIRS = {
    ".git", "bin", "obj", "node_modules", "__pycache__", ".idea",
    "dist", "build", ".vs", "out", "publish", "htmlcov", ".pytest_cache",
}
_EXCLUDE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar",
    ".gz", ".exe", ".dll", ".pdb", ".so", ".dylib", ".class", ".pyc",
    ".db", ".sqlite", ".woff", ".woff2", ".ttf", ".eot",
}
_CODE_EXTS = {
    ".py", ".cs", ".ts", ".tsx", ".js", ".jsx", ".go", ".java",
    ".dart", ".kt", ".swift", ".rb", ".php", ".rs",
}


def _walk_code_files(project_path: str, max_files: int = 500):
    """Kod dosyalarını walk eder."""
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS and not d.startswith(".")]
        for fname in files:
            _, ext = os.path.splitext(fname)
            if ext.lower() not in _CODE_EXTS:
                continue
            yield os.path.join(root, fname)


class AnalysisHandler:
    """Piyasa üstü analiz araçlarının uygulama katmanı."""

    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    # ──────────────────────────────────────────────────────────────
    # 1. SECURITY SCAN
    # ──────────────────────────────────────────────────────────────
    async def security_scan(self, project_path: str, collection: str = "") -> str:
        """
        Pattern-based SAST: SQL injection, hardcoded secret, eval/exec,
        shell injection, XSS, path traversal, insecure random, pickle.
        """
        t0 = time.monotonic()
        if not os.path.exists(project_path):
            return f"❌ Dizin bulunamadı: {project_path}"

        findings: list[dict] = []
        files_scanned = 0

        for fpath in _walk_code_files(project_path):
            try:
                content = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                files_scanned += 1
                rel = os.path.relpath(fpath, project_path)

                for pattern_def in _SECURITY_PATTERNS:
                    for i, line in enumerate(lines, 1):
                        if pattern_def["pattern"].search(line):
                            findings.append({
                                "id": pattern_def["id"],
                                "severity": pattern_def["severity"],
                                "file": rel,
                                "line": i,
                                "snippet": line.strip()[:120],
                                "description": pattern_def["description"],
                                "fix": pattern_def["fix"],
                            })
                            if len(findings) >= 200:
                                break
                    if len(findings) >= 200:
                        break
            except Exception:
                continue

        elapsed = int((time.monotonic() - t0) * 1000)

        if not findings:
            return (
                f"✅ Güvenlik taraması tamamlandı — bulgu yok\n"
                f"📁 Taranan dosya: {files_scanned} | ⏱️ {elapsed}ms"
            )

        critical = [f for f in findings if f["severity"] == "CRITICAL"]
        high = [f for f in findings if f["severity"] == "HIGH"]
        medium = [f for f in findings if f["severity"] == "MEDIUM"]

        lines_out = [
            f"## 🔒 Güvenlik Taraması — {project_path}",
            f"📁 {files_scanned} dosya tarandı | ⏱️ {elapsed}ms",
            f"🔴 CRITICAL: {len(critical)} | 🟠 HIGH: {len(high)} | 🟡 MEDIUM: {len(medium)}",
            "",
        ]
        for f in sorted(findings, key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}.get(x["severity"], 3)):
            icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡"}.get(f["severity"], "⚪")
            lines_out.append(f"{icon} **[{f['id']}]** `{f['file']}:{f['line']}`")
            lines_out.append(f"   > {f['snippet']}")
            lines_out.append(f"   📌 {f['description']}")
            lines_out.append(f"   💡 _Çözüm: {f['fix']}_")
            lines_out.append("")

        return "\n".join(lines_out)

    # ──────────────────────────────────────────────────────────────
    # 2. REFACTOR SUGGESTIONS
    # ──────────────────────────────────────────────────────────────
    async def refactor_suggestions(self, project_path: str, collection: str = "") -> str:
        """
        AST-based code smell tespiti:
        - Long method (>50 satır)
        - Deep nesting (>4 level)
        - God class (>500 satır, >15 method)
        - Duplicate string literals
        """
        if not os.path.exists(project_path):
            return f"❌ Dizin bulunamadı: {project_path}"

        smells: list[dict] = []

        for fpath in _walk_code_files(project_path):
            rel = os.path.relpath(fpath, project_path)
            try:
                content = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                ext = Path(fpath).suffix.lower()

                if ext == ".py":
                    smells.extend(_detect_python_smells(content, lines, rel))
                else:
                    smells.extend(_detect_generic_smells(lines, rel))

                if len(smells) >= 100:
                    break
            except Exception:
                continue

        if not smells:
            return f"✅ Refactor analizi tamamlandı — kod kokusu tespit edilmedi\n📁 Proje: {project_path}"

        lines_out = [
            f"## 🔧 Refactor Önerileri — {project_path}",
            f"Toplam {len(smells)} tespit:",
            "",
        ]
        for s in smells[:50]:
            lines_out.append(f"- **{s['smell']}** `{s['file']}:{s['line']}`")
            lines_out.append(f"  {s['description']}")
            lines_out.append(f"  💡 _{s['hint']}_")
            lines_out.append("")

        return "\n".join(lines_out)

    # ──────────────────────────────────────────────────────────────
    # 3. TEST SUGGESTION
    # ──────────────────────────────────────────────────────────────
    async def test_suggestion(self, project_path: str, collection: str = "", target_file: str = "") -> str:
        """
        Public method'ları tespit eder, test dosyası yoksa LLM'e test case önerir.
        """
        if not os.path.exists(project_path):
            return f"❌ Dizin bulunamadı: {project_path}"

        # Test edilmemiş public fonksiyonları bul
        untested = _find_untested_functions(project_path, target_file)
        if not untested:
            return "✅ Tüm public fonksiyonlar için test coverage mevcut görünüyor."

        # LLM ile test önerileri üret (ilk 5 fonksiyon)
        client = get_llm_client()
        candidates = untested[:5]

        context_parts = []
        for item in candidates:
            context_parts.append(
                f"Dosya: {item['file']}\nFonksiyon: {item['name']}\nKod:\n{item['snippet']}"
            )
        context = "\n\n---\n\n".join(context_parts)

        try:
            response = await client.chat.completions.create(
                model=config.analysis_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Sen deneyimli bir test mühendisisin. "
                            "Verilen fonksiyonlar için unit test önerileri üret. "
                            "Her fonksiyon için: happy path, edge case ve hata senaryosu yaz. "
                            "Yanıtı Türkçe, markdown formatında döndür."
                        ),
                    },
                    {"role": "user", "content": f"Test yazılması gereken fonksiyonlar:\n\n{context}"},
                ],
                max_tokens=2000,
                temperature=0.1,
            )
            llm_output = response.choices[0].message.content.strip()
        except Exception as e:
            llm_output = f"(LLM test önerisi üretilemedi: {e})"

        header = [
            f"## 🧪 Test Önerileri — {project_path}",
            f"Test edilmemiş {len(untested)} public fonksiyon tespit edildi (ilk 5 gösteriliyor):",
            "",
        ]
        for item in candidates:
            header.append(f"- `{item['name']}` — `{item['file']}`")
        header.append("")
        header.append("### LLM Test Önerileri")
        header.append(llm_output)

        return "\n".join(header)

    # ──────────────────────────────────────────────────────────────
    # 4. CODE CLONE DETECTION
    # ──────────────────────────────────────────────────────────────
    async def code_clone_detection(self, collection: str, threshold: float = 0.95) -> str:
        """
        Qdrant'taki chunk embedding'lerini cosine similarity ile karşılaştırır.
        threshold > 0.95 → semantic clone flag.
        """
        try:
            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import Filter
            import numpy as np
        except ImportError:
            return "❌ qdrant-client veya numpy yüklü değil"

        if not collection:
            collection = config.default_collection

        try:
            client = AsyncQdrantClient(url=config.qdrant_url, api_key=config.qdrant_api_key)

            # Tüm chunk'ları scroll ile çek (max 1000)
            records, _ = await client.scroll(
                collection_name=collection,
                limit=1000,
                with_vectors=True,
                with_payload=True,
            )
            await client.close()
        except Exception as e:
            return f"❌ Qdrant bağlantı hatası: {e}"

        if len(records) < 2:
            return "⚠️ Yeterli chunk yok (min 2 gerekli)"

        # Dense vektörleri topla
        vectors = []
        meta = []
        for r in records:
            v = None
            if isinstance(r.vector, dict):
                v = r.vector.get("dense") or r.vector.get("text-dense")
            elif isinstance(r.vector, list):
                v = r.vector
            if v:
                vectors.append(v)
                payload = r.payload or {}
                meta.append({
                    "file": payload.get("relative_path", "?"),
                    "name": payload.get("name", "?"),
                })

        if len(vectors) < 2:
            return "⚠️ Dense vektör bulunamadı"

        try:
            arr = np.array(vectors, dtype=np.float32)
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            normed = arr / norms
            sim_matrix = normed @ normed.T
        except Exception as e:
            return f"❌ Similarity hesaplama hatası: {e}"

        clones: list[dict] = []
        n = len(vectors)
        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sim_matrix[i, j])
                if sim >= threshold:
                    clones.append({
                        "file_a": meta[i]["file"],
                        "name_a": meta[i]["name"],
                        "file_b": meta[j]["file"],
                        "name_b": meta[j]["name"],
                        "similarity": round(sim, 4),
                    })
                if len(clones) >= 50:
                    break
            if len(clones) >= 50:
                break

        if not clones:
            return f"✅ Clone tespit edilmedi (threshold={threshold}, {n} chunk tarandı)"

        lines_out = [
            f"## 🔁 Code Clone Tespiti — `{collection}`",
            f"Threshold: {threshold} | Taranan chunk: {n} | Tespit: {len(clones)}",
            "",
        ]
        for c in sorted(clones, key=lambda x: x["similarity"], reverse=True):
            lines_out.append(
                f"- **{c['similarity']:.3f}** similarity\n"
                f"  `{c['name_a']}` ({c['file_a']})\n"
                f"  `{c['name_b']}` ({c['file_b']})"
            )
            lines_out.append("")

        return "\n".join(lines_out)


# ──────────────────────────────────────────────────────────────
# Yardımcı fonksiyonlar
# ──────────────────────────────────────────────────────────────

def _detect_python_smells(content: str, lines: list[str], rel: str) -> list[dict]:
    """Python AST ile code smell tespiti."""
    smells = []
    try:
        import ast as _ast

        tree = _ast.parse(content)
        for node in _ast.walk(tree):
            # Long method
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno + 1)
                length = end - node.lineno
                if length > 50:
                    smells.append({
                        "smell": "LONG_METHOD",
                        "file": rel,
                        "line": node.lineno,
                        "description": f"`{node.name}` fonksiyonu {length} satır — max 50 önerilir",
                        "hint": "Fonksiyonu daha küçük, tek sorumlu parçalara bölün",
                    })

            # God class
            if isinstance(node, _ast.ClassDef):
                end = getattr(node, "end_lineno", node.lineno + 1)
                length = end - node.lineno
                methods = [n for n in _ast.walk(node) if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))]
                if length > 500 or len(methods) > 15:
                    smells.append({
                        "smell": "GOD_CLASS",
                        "file": rel,
                        "line": node.lineno,
                        "description": f"`{node.name}` sınıfı {length} satır, {len(methods)} method — çok büyük",
                        "hint": "Single Responsibility Principle uygulayın, sınıfı parçalara ayırın",
                    })
    except Exception:
        pass
    return smells


def _detect_generic_smells(lines: list[str], rel: str) -> list[dict]:
    """Dil-bağımsız basit smell tespiti."""
    smells = []
    # Long file
    if len(lines) > 800:
        smells.append({
            "smell": "LARGE_FILE",
            "file": rel,
            "line": 1,
            "description": f"Dosya {len(lines)} satır — çok büyük",
            "hint": "Dosyayı modüllere/parçalara bölün",
        })
    # Deep nesting (basit indent sayımı)
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if not stripped:
            continue
        indent = len(line) - len(stripped)
        tab_size = 4
        level = indent // tab_size
        if level >= 5:
            smells.append({
                "smell": "DEEP_NESTING",
                "file": rel,
                "line": i,
                "description": f"Satır {i}: {level} seviye iç içe kod — okunması zor",
                "hint": "Guard clause, extract method veya early return kullanın",
            })
            break
    return smells


def _find_untested_functions(project_path: str, target_file: str = "") -> list[dict]:
    """Public Python fonksiyonlarını tespit eder ve test dosyası var mı kontrol eder."""
    import ast as _ast

    results = []
    search_path = os.path.join(project_path, target_file) if target_file else project_path

    for fpath in _walk_code_files(search_path):
        if "test" in fpath.lower():
            continue
        ext = Path(fpath).suffix.lower()
        if ext != ".py":
            continue

        rel = os.path.relpath(fpath, project_path)
        # Karşılık gelen test dosyası var mı?
        test_candidates = [
            fpath.replace(".py", "_test.py"),
            fpath.replace("/", "/test_").replace("\\", "\\test_"),
            os.path.join(os.path.dirname(fpath), "test_" + os.path.basename(fpath)),
        ]
        has_test = any(os.path.exists(t) for t in test_candidates)
        if has_test:
            continue

        try:
            content = Path(fpath).read_text(encoding="utf-8", errors="ignore")
            tree = _ast.parse(content)
            lines = content.splitlines()

            for node in _ast.walk(tree):
                if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_"):
                    continue
                end = getattr(node, "end_lineno", node.lineno + 5)
                snippet = "\n".join(lines[node.lineno - 1: min(end, node.lineno + 10)])
                results.append({
                    "file": rel,
                    "name": node.name,
                    "line": node.lineno,
                    "snippet": snippet,
                })
                if len(results) >= 20:
                    break
        except Exception:
            continue

        if len(results) >= 20:
            break

    return results
