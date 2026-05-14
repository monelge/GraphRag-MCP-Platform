from __future__ import annotations

from src.agent.tasks.task_models import Task, TaskStatus
from src.control.evals.runner import EvalRunner
from src.handlers.context import AppContext
from src.handlers.retrieval_handler import RetrievalHandler


class ExecutionHandler:
    """Görev yürütme ve doğrulama araçlarının uygulama katmanı."""

    def __init__(self, ctx: AppContext, retrieval: RetrievalHandler):
        self.ctx = ctx
        self.retrieval = retrieval

    def register_default_handlers(self) -> None:
        """Task orchestrator için varsayılan placeholder handler'ları kaydeder."""
        for status in [
            TaskStatus.PLANNED,
            TaskStatus.RETRIEVING,
            TaskStatus.ANALYZING,
            TaskStatus.EXECUTING,
            TaskStatus.VERIFYING,
            TaskStatus.SUMMARIZING,
        ]:
            self.ctx.orchestrator.register_handler(status, self._dummy_handler)

    async def _dummy_handler(self, task: Task):
        transitions = {
            TaskStatus.PLANNED: TaskStatus.RETRIEVING,
            TaskStatus.RETRIEVING: TaskStatus.ANALYZING,
            TaskStatus.ANALYZING: TaskStatus.WAITING_APPROVAL,
            TaskStatus.EXECUTING: TaskStatus.VERIFYING,
            TaskStatus.VERIFYING: TaskStatus.SUMMARIZING,
            TaskStatus.SUMMARIZING: TaskStatus.DONE,
        }
        next_status = transitions.get(task.status, TaskStatus.DONE)
        return f"{task.status.value} tamamlandı.", next_status

    async def create_agent_task(
        self,
        title: str,
        description: str,
        collection: str,
        steps: list[str] | None = None,
    ) -> str:
        """Yeni bir ajan görevi başlatır. steps verilirse adımlar TaskStep olarak kaydedilir."""
        task = await self.ctx.orchestrator.create_task(title, description, collection, steps)
        lines = [f"🚀 Görev başlatıldı! Task ID: `{task.task_id}`", f"Durum: `{task.status.value}`"]
        if task.steps:
            lines.append(f"\n### Adımlar ({len(task.steps)}):")
            for i, step in enumerate(task.steps, 1):
                lines.append(f"{i}. {step.description} — `{step.status.value}`")
        return "\n".join(lines)

    async def get_task_status(self, task_id: str) -> str:
        """Görev durumunu ve adımlarını döndürür."""
        task = await self.ctx.task_store.get_task(task_id)
        if not task:
            return f"❌ Görev bulunamadı: `{task_id}`"

        lines = [
            f"## 📋 Görev: {task.title}",
            f"**ID:** `{task.task_id}`",
            f"**Durum:** `{task.status.value}`",
            f"**Açıklama:** {task.description}",
            "\n### Adımlar:",
        ]
        for index, step in enumerate(task.steps):
            lines.append(f"{index + 1}. {step.description} — `{step.status.value}`")
        return "\n".join(lines)

    async def approve_task_step(self, task_id: str, feedback: str = "approved") -> str:
        """Onay bekleyen görevi bir sonraki adıma geçirir."""
        return await self.ctx.orchestrator.approve_task(task_id)

    async def complete_task(self, task_id: str, note: str = "") -> str:
        """Görevi herhangi bir durumdan DONE'a çeker (manuel tamamlama)."""
        return await self.ctx.orchestrator.complete_task(task_id, note)

    async def list_agent_tasks(self, collection: str = "", status: str = "") -> str:
        """Kayıtlı görevleri listeler."""
        # Yaygın alias'ları gerçek TaskStatus değerlerine çevir
        _aliases = {
            "in_progress": "executing",
            "inprogress": "executing",
            "running": "executing",
            "pending": "planned",
            "completed": "done",
            "finished": "done",
            "cancelled": "aborted",
            "canceled": "aborted",
            "waiting": "waiting_approval",
        }
        task_status = None
        if status:
            normalized = _aliases.get(status.lower(), status.lower())
            valid_values = {s.value for s in TaskStatus}
            if normalized not in valid_values:
                return (
                    f"❌ Geçersiz status: `{status}`\n"
                    f"Geçerli değerler: {', '.join(f'`{v}`' for v in sorted(valid_values))}\n"
                    f"Yaygın alias'lar: `in_progress`→`executing`, `pending`→`planned`, `completed`→`done`"
                )
            task_status = TaskStatus(normalized)
        tasks = await self.ctx.task_store.list_tasks(collection or None, task_status)
        if not tasks:
            return "ℹ️ Kayıtlı görev bulunamadı."

        lines = ["## 📋 Kayıtlı Görevler\n"]
        for task in tasks[:15]:
            lines.append(f"- `{task.task_id}` | **{task.title}** | `{task.status.value}`")
        return "\n".join(lines)

    async def run_verification_plan(
        self,
        project_path: str,
        run_build: bool = True,
        run_tests: bool = True,
        run_lint: bool = False,
    ) -> str:
        """Proje profilini algılayıp build/test/lint akışını çalıştırır."""
        profile = self.ctx.runtime_manager.detect_profile(project_path)
        profile_name = profile.name if profile and profile.name else "UNKNOWN"
        output = [f"## 🛠️ Doğrulama Planı — {profile_name.upper()}\n"]

        if run_build:
            output.append(f"### 📦 Build ({profile.build_cmd})")
            result = await self.ctx.runtime_manager.run_build(project_path)
            output.append(f"**Durum:** {'✅ Başarılı' if result.success else '❌ Başarısız'}")
            if not result.success:
                output.append(f"```text\n{result.stderr or result.stdout[:500]}\n```")
                return "\n".join(output)

        if run_tests:
            output.append(f"\n### 🧪 Test ({profile.test_cmd})")
            result = await self.ctx.runtime_manager.run_tests(project_path)
            output.append(f"**Durum:** {'✅ Başarılı' if result.success else '❌ Başarısız'}")
            if result.stdout or result.stderr:
                output.append(f"```text\n{(result.stdout + result.stderr)[:1000]}\n```")

        if run_lint:
            output.append(f"\n### 🧹 Lint ({profile.lint_cmd})")
            result = await self.ctx.runtime_manager.run_lint(project_path)
            output.append(f"**Durum:** {'✅ Başarılı' if result.success else '❌ Başarısız'}")

        return "\n".join(output)

    async def run_retrieval_eval(self, dataset_name: str, collection: str) -> str:
        """Retrieval değerlendirmesini mevcut search_code üzerinden çalıştırır."""
        dataset = self.ctx.dataset_manager.load_dataset(dataset_name)
        if not dataset:
            return f"❌ Veri seti bulunamadı: `{dataset_name}`"

        runner = EvalRunner(self.retrieval.search_code)
        results = await runner.run_eval(dataset, collection)
        summary = results["summary"]
        lines = [
            f"## 📊 Retrieval Eval — {dataset_name} ({collection})",
            f"- **Toplam Case:** {summary['total_cases']}",
            f"- **Hit@1:** {summary['hit_at_1']:.1%}",
            f"- **Hit@3:** {summary['hit_at_3']:.1%}",
            f"- **Hit@5:** {summary['hit_at_5']:.1%}",
            f"- **MRR:** {summary['mrr']:.3f}",
            f"- **Ort. Gecikme:** {summary['avg_latency_sec']:.2f}s",
            "\n> Eval tamamlandı. Sistem performansı veri odaklı olarak ölçüldü.",
        ]
        return "\n".join(lines)
