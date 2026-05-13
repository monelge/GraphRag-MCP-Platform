"""
Memory & Checkpoint Batch Jobs — Periyodik arka plan görevleri.

Faz 3 Özellikleri:
- Memory pruning: Süresi dolan bellek kayıtlarını temizle
- Checkpoint compaction: Eski checkpoint'ları optimize et
- Context compression: Büyük context'leri özetle
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional
from src.storage.episodic_store import EpisodicStore
from src.agent.tasks.task_store import TaskStore
from src.memory.services.memory_compaction import MemoryCompactor

logger = logging.getLogger(__name__)


class BatchJobRunner:
    """
    Bellek ve checkpoint batch işlerini yönetir.
    Sistem kaynağına az yük bindiren şekilde çalışır.
    """
    
    def __init__(
        self, 
        task_store: TaskStore, 
        episodic_store: EpisodicStore
    ):
        self.task_store = task_store
        self.episodic = episodic_store
        self.compactor = MemoryCompactor(episodic_store)
        
        # Metrikler
        self.stats: Dict[str, Any] = {
            "last_run": None,
            "pruned_memories": 0,
            "compacted_checkpoints": 0,
            "total_runs": 0,
        }

    async def run_all_jobs(self, collection: str = "default") -> Dict[str, Any]:
        """
        Tüm batch işlerini sırayla çalıştır.
        
        İşler:
        1. Memory pruning — süresi dolan kayıtları sil
        2. Checkpoint compaction — eski checkpoint'ları temizle
        3. Context compression — (opsiyonel)
        """
        logger.info("🔄 Batch jobs başlıyor...")
        start_time = time.time()
        
        results = {
            "memory_pruning": await self._prune_expired_memories(collection),
            "checkpoint_compaction": await self._compact_checkpoints(),
            "duration_seconds": time.time() - start_time,
        }
        
        self.stats["last_run"] = time.time()
        self.stats["total_runs"] += 1
        
        logger.info(f"✅ Batch jobs tamamlandı ({results['duration_seconds']:.2f}s)")
        return results

    async def _prune_expired_memories(self, collection: str) -> Dict[str, Any]:
        """
        Faz 3: Süresi dolan bellek kayıtlarını 'archived' yap.
        
        Mantık:
        - valid_to < now() → archived
        - status='archived' → remain as-is
        - Silmek yerine archive et (audit trail)
        """
        try:
            logger.info(f"🧹 Memory pruning başlıyor (collection={collection})")
            
            # Not: EpisodicStore'a archive_expired metodu eklenebilir
            # Şu an placeholder — gerçeklerinde:
            # SELECT * FROM qdrant WHERE valid_to < NOW() AND status != 'archived'
            # UPDATE ... SET status = 'archived'
            
            pruned_count = 0  # Placeholder
            logger.info(f"✅ Memory pruning tamamlandı ({pruned_count} archived)")
            
            self.stats["pruned_memories"] += pruned_count
            return {
                "status": "completed",
                "pruned_count": pruned_count,
                "collection": collection
            }
        except Exception as e:
            logger.error(f"Memory pruning hatası: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _compact_checkpoints(self, keep_per_task: int = 10) -> Dict[str, Any]:
        """
        Faz 3: Tüm görevlerin eski checkpoint'larını sil.
        
        Strateji:
        - Her task için son keep_per_task checkpoint'ı sakla
        - Eski olanları sil (compaction)
        - Büyük DB'lerde: batch halinde işle (pagination)
        """
        try:
            logger.info(f"🗜️  Checkpoint compaction başlıyor (keep={keep_per_task})")
            
            total_deleted = 0
            
            # Not: task_store'a list_all_tasks() gibi metodu eklenebilir
            # Şu an placeholder — gerçeklerinde:
            # SELECT DISTINCT task_id FROM tasks
            # For each task: delete_old_checkpoints(task_id, keep_per_task)
            
            logger.info(f"✅ Checkpoint compaction tamamlandı ({total_deleted} deleted)")
            
            self.stats["compacted_checkpoints"] += total_deleted
            return {
                "status": "completed",
                "deleted_count": total_deleted,
                "keep_per_task": keep_per_task
            }
        except Exception as e:
            logger.error(f"Checkpoint compaction hatası: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _compress_large_contexts(self, max_context_size_kb: int = 100) -> Dict[str, Any]:
        """
        Faz 3: Çok büyük context'leri özetlemeyi dene.
        
        Mantık:
        - Context size > max_context_size_kb
        - LLM ile özetleme / summarization
        - Orijinalini backup'la, özeti sakla
        """
        try:
            logger.info(f"📦 Context compression başlıyor (max={max_context_size_kb}KB)")
            
            compressed_count = 0  # Placeholder
            
            logger.info(f"✅ Context compression tamamlandı ({compressed_count} compressed)")
            return {
                "status": "completed",
                "compressed_count": compressed_count,
                "max_size_kb": max_context_size_kb
            }
        except Exception as e:
            logger.error(f"Context compression hatası: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    def get_stats(self) -> Dict[str, Any]:
        """Batch job istatistiklerini döner."""
        return {
            **self.stats,
            "uptime_hours": (time.time() - self.stats["last_run"]) / 3600 if self.stats["last_run"] else 0
        }


class BatchJobScheduler:
    """
    Batch jobları periyodik olarak çalıştıran scheduler.
    
    Not: Gerçek sistemde APScheduler veya Celery kullanılmalı.
    Bu sınıf prototip için basit interval-based scheduling yapar.
    """
    
    def __init__(
        self,
        runner: BatchJobRunner,
        interval_seconds: int = 3600  # Varsayılan: saatlik
    ):
        self.runner = runner
        self.interval = interval_seconds
        self.is_running = False
        self.last_execution: Optional[float] = None

    async def start(self):
        """
        Scheduler'ı başlat (background).
        Not: asyncio.create_task() ile çalıştırılmalı.
        """
        self.is_running = True
        logger.info(f"✅ Batch scheduler başladı (interval={self.interval}s)")
        
        while self.is_running:
            try:
                await self.runner.run_all_jobs()
                self.last_execution = time.time()
                
                # Interval'e kadar bekle
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.error(f"Scheduler hata: {e}")
                await asyncio.sleep(60)  # Hata durumunda kısa bekle

    def stop(self):
        """Scheduler'ı durdur."""
        self.is_running = False
        logger.info("⛔ Batch scheduler durduruldu")

    def get_status(self) -> Dict[str, Any]:
        """Scheduler durumunu döner."""
        return {
            "running": self.is_running,
            "interval_seconds": self.interval,
            "last_execution": self.last_execution,
            "runner_stats": self.runner.get_stats()
        }

