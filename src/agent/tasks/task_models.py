from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional
import time
import uuid

class TaskStatus(Enum):
    """
    Görev ve adımların yaşam döngüsü durumları.
    PLANNED → RETRIEVING → ANALYZING → WAITING_APPROVAL → EXECUTING → VERIFYING → SUMMARIZING → DONE
    Herhangi bir noktada FAILED veya ABORTED olabilir.
    """
    PLANNED = "planned"
    RETRIEVING = "retrieving"
    ANALYZING = "analyzing"
    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SUMMARIZING = "summarizing"
    DONE = "done"
    FAILED = "failed"
    ABORTED = "aborted"

@dataclass
class TaskStep:
    """
    Görev içindeki tek bir adım.
    step_id: Benzersiz tanımlayıcı
    description: Adımın açıklaması (Türkçe destekli)
    status: Mevcut durum
    result: Adımın sonucu
    started_at, completed_at: Unix timestamp
    required_memory: Adım için gerekli bellek tipleri (optional)
    """
    step_id: str
    description: str
    status: TaskStatus = TaskStatus.PLANNED
    result: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    required_memory: List[str] = field(default_factory=list)  # Faz 3: bellek dependency

@dataclass
class Task:
    """
    Ana görev nesnesi.
    Birden fazla TaskStep içerir ve shared context'i yönetir.
    """
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PLANNED
    collection: str = ""
    steps: List[TaskStep] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)  # Adımlar arası paylaşılan state
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, description: str) -> TaskStep:
        """Göreve yeni adım ekler ve döner."""
        step = TaskStep(step_id=str(uuid.uuid4()), description=description)
        self.steps.append(step)
        return step
