from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional
import time
import uuid

class TaskStatus(Enum):
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
    step_id: str
    description: str
    status: TaskStatus = TaskStatus.PLANNED
    result: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

@dataclass
class Task:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PLANNED
    collection: str = ""
    steps: List[TaskStep] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict) # Shared state between steps
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, description: str):
        step = TaskStep(step_id=str(uuid.uuid4()), description=description)
        self.steps.append(step)
        return step

@dataclass
class TaskCheckpoint:
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    status: TaskStatus = TaskStatus.PLANNED
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
