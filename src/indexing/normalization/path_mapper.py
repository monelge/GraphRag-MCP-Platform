from __future__ import annotations

"""Dosya yollarını indeksleme öncesi tutarlı hale getiren yardımcı sınıf."""

from pathlib import Path


class PathMapper:
    """Absolute/relative path farkını normalize ederek tek temsil üretir."""

    def normalize(self, raw_path: str, project_root: str = "") -> str:
        """Path'i slash standardına çevirip mümkünse relative hale getirir."""
        clean_path = (raw_path or "").replace("\\", "/")
        while "//" in clean_path:
            clean_path = clean_path.replace("//", "/")
        if project_root:
            try:
                return self.to_relative(clean_path, project_root)
            except ValueError:
                pass
        return clean_path

    def to_relative(self, path: str, base: str) -> str:
        """Absolute path'i verilen base'e göre relative path'e çevirir."""
        rel = Path(path).resolve(strict=False).relative_to(Path(base).resolve(strict=False))
        return str(rel).replace("\\", "/")

    def is_test_file(self, path: str) -> bool:
        """Path içinde test dizini veya dosya adı paterni varsa True döndürür."""
        lowered = path.lower()
        return any(token in lowered for token in ("/test", "/tests", "_test", ".spec", "/spec"))
