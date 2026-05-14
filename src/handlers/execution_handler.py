from __future__ import annotations

from src.agent.tasks.task_models import TaskStatus
from src.control.evals.runner import EvalRunner
from src.execution.runners.build_runner import BuildRunner
from src.execution.runners.test_runner import TestRunner
from src.handlers.context import AppContext
from src.handlers.retrieval_handler import RetrievalHandler


class ExecutionHandler:
    """Görev yürütme ve doğrulama araçlarının uygulama katmanı."""

    def __init__(self, ctx: AppContext, retrieval: RetrievalHandler):
        self.ctx = ctx
        self.retrieval = retrieval
        self.build_runner = BuildRunner(ctx.runtime_manager)
        self.test_runner = TestRunner(ctx.runtime_manager)

    def register_default_handlers(self) -> None:
        """Eski handler tabanlı akış için no-op uyumluluk bırakılır."""
        return None

    async def create_agent_task(self, title: str, description: str, collection: str, steps=None) -> str:
        task = await self.ctx.orchestrator.create_task(title, description, collection, steps)
        lines = [f"🚀 Görev başlatıldı! Task ID: `{task.task_id}`", f"Durum: `{task.status.value}`"]
        if task.steps:
            lines.append(f"\n### Adımlar ({len(task.steps)}):")
            for index, step in enumerate(task.steps, 1):
                lines.append(f"{index}. {step.description} — `{step.status.value}`")
        return "\n".join(lines)

    async def get_task_status(self, task_id: str) -> str:
        task = await self.ctx.task_store.get_task(task_id)
        if not task:
            return f"❌ Görev bulunamadı: `{task_id}`"
        lines = [
            f"## 📋 Görev: {task.title}",
            f"**ID:** `{task.task_id}`",
            f"**Durum:** `{task.status.value}`",
            f"**Node:** `{task.context.get('current_node')}`",
            f"**Açıklama:** {task.description}",
            "\n### Adımlar:",
        ]
        for index, step in enumerate(task.steps):
            lines.append(f"{index + 1}. {step.description} — `{step.status.value}`")
        return "\n".join(lines)

    async def approve_task_step(self, task_id: str, feedback: str = "approved") -> str:
        result = await self.ctx.orchestrator.approve_task(task_id, feedback)
        if self.ctx.audit_logger:
            self.ctx.audit_logger.log("approval_decision", task_id=task_id, summary=feedback)
        return result

    async def complete_task(self, task_id: str, note: str = "") -> str:
        result = await self.ctx.orchestrator.complete_task(task_id, note)
        if self.ctx.audit_logger:
            self.ctx.audit_logger.log("approval_decision", task_id=task_id, summary=note)
        return result

    async def resume_task(self, task_id: str) -> str:
        """Son checkpoint'ten görevi devam ettirir."""
        checkpoint = await self.ctx.checkpoint_store.get_latest(task_id) if self.ctx.checkpoint_store else None
        if not checkpoint:
            return f"❌ {task_id} için checkpoint bulunamadı."
        task = await self.ctx.task_store.get_task(task_id)
        if not task:
            return f"❌ Görev bulunamadı: {task_id}"
        task.context = checkpoint.task_context
        task.context["current_node"] = checkpoint.current_node
        task.context["resume_from_step"] = checkpoint.step_index
        task.context["file_patches"] = checkpoint.file_patches
        await self.ctx.task_store.save_task(task)
        await self.ctx.orchestrator.run_step(task_id)
        return f"▶️ Görev devam ettiriliyor: `{task_id}` — node: `{checkpoint.current_node}`, adım: {checkpoint.step_index}"

    async def list_agent_tasks(self, collection: str = "", status: str = "") -> str:
        aliases = {
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
            normalized = aliases.get(status.lower(), status.lower())
            valid_values = {item.value for item in TaskStatus}
            if normalized not in valid_values:
                return f"❌ Geçersiz status: `{status}`"
            task_status = TaskStatus(normalized)
        tasks = await self.ctx.task_store.list_tasks(collection or None, task_status)
        if not tasks:
            return "ℹ️ Kayıtlı görev bulunamadı."
        lines = ["## 📋 Kayıtlı Görevler\n"]
        for task in tasks[:15]:
            lines.append(f"- `{task.task_id}` | **{task.title}** | `{task.status.value}` | node=`{task.context.get('current_node')}`")
        return "\n".join(lines)

    async def get_project_state(self, collection: str) -> str:
        """
        PostgreSQL'deki tüm task'ları koleksiyona göre gruplandırarak proje durumu özeti döndürür.
        state.md veya tasks.md dosyalarına bağımlılık olmaksızın kalıcı hafızadan çalışır.
        """
        if not collection:
            return "❌ collection parametresi zorunludur."
        tasks = await self.ctx.task_store.list_tasks(collection=collection)
        if not tasks:
            return f"ℹ️ `{collection}` koleksiyonunda kayıtlı görev bulunamadı."

        by_status: dict[str, list] = {}
        for task in tasks:
            key = task.status.value
            by_status.setdefault(key, []).append(task)

        # Tamamlanan fazlardan faz numarası çıkar (F-001 vb. prefix)
        done_tasks = by_status.get("done", [])
        active_tasks = by_status.get("executing", []) + by_status.get("waiting_approval", []) + by_status.get("retrieving", []) + by_status.get("analyzing", [])
        planned_tasks = by_status.get("planned", [])

        lines = [f"## 🗂️ Proje Durumu — `{collection}`\n"]
        lines.append(f"**Toplam görev:** {len(tasks)} | **Tamamlanan:** {len(done_tasks)} | **Aktif:** {len(active_tasks)} | **Planlanan:** {len(planned_tasks)}\n")

        if active_tasks:
            lines.append("### 🔄 Aktif Görevler")
            for t in active_tasks:
                pending_steps = [s for s in t.steps if s.status.value == "planned"]
                lines.append(f"- **{t.title}** `{t.task_id}` | durum: `{t.status.value}` | bekleyen adım: {len(pending_steps)}")

        if planned_tasks:
            lines.append("\n### 📌 Planlanan Görevler")
            for t in planned_tasks[:5]:
                lines.append(f"- **{t.title}** `{t.task_id}`")

        if done_tasks:
            lines.append(f"\n### ✅ Tamamlanan Görevler ({len(done_tasks)} adet)")
            for t in done_tasks[:10]:
                lines.append(f"- {t.title}")

        return "\n".join(lines)

    async def get_active_phase(self, collection: str) -> str:
        """
        Koleksiyondaki aktif (executing/waiting_approval) veya en son planned görevi döndürür.
        Hangi faz üzerinde çalışıldığını PostgreSQL'den doğrudan okur — dosya okumaya gerek yoktur.
        """
        if not collection:
            return "❌ collection parametresi zorunludur."
        tasks = await self.ctx.task_store.list_tasks(collection=collection)
        if not tasks:
            return f"ℹ️ `{collection}` koleksiyonunda kayıtlı görev bulunamadı."

        # Öncelik: executing > waiting_approval > planned (en son güncellenen)
        priority_order = ["executing", "waiting_approval", "retrieving", "analyzing", "verifying", "planned"]
        active: Task | None = None
        for status_val in priority_order:
            candidates = [t for t in tasks if t.status.value == status_val]
            if candidates:
                active = candidates[0]
                break

        if not active:
            return "ℹ️ Aktif veya planlanan görev bulunamadı."

        lines = [
            f"## 🎯 Aktif Faz — `{collection}`\n",
            f"**Görev:** {active.title}",
            f"**ID:** `{active.task_id}`",
            f"**Durum:** `{active.status.value}`",
            f"**Açıklama:** {active.description[:300]}",
        ]
        if active.steps:
            done_count = sum(1 for s in active.steps if s.status.value == "done")
            lines.append(f"\n### Adımlar ({done_count}/{len(active.steps)} tamamlandı):")
            for i, step in enumerate(active.steps, 1):
                icon = "✅" if step.status.value == "done" else "⏳" if step.status.value in ("executing", "retrieving") else "📌"
                lines.append(f"{i}. {icon} {step.description} — `{step.status.value}`")
        return "\n".join(lines)

    async def run_verification_plan(self, project_path: str, run_build: bool = True, run_tests: bool = True, run_lint: bool = False) -> str:
        profile = self.ctx.runtime_manager.detect_profile(project_path)
        profile_name = profile.name if profile and profile.name else "UNKNOWN"
        output = [f"## 🛠️ Doğrulama Planı — {profile_name.upper()}\n"]
        if run_build:
            output.append(f"### 📦 Build ({profile.build_cmd})")
            result = await self.build_runner.run(project_path)
            output.append(f"**Durum:** {'✅ Başarılı' if result.success else '❌ Başarısız'}")
            if not result.success:
                output.append(f"```text\n{result.stderr or result.stdout[:500]}\n```")
                return "\n".join(output)
        if run_tests:
            output.append(f"\n### 🧪 Test ({profile.test_cmd})")
            result = await self.test_runner.run(project_path)
            output.append(f"**Durum:** {'✅ Başarılı' if result.success else '❌ Başarısız'}")
            if result.stdout or result.stderr:
                output.append(f"```text\n{(result.stdout + result.stderr)[:1000]}\n```")
        if run_lint:
            output.append(f"\n### 🧹 Lint ({profile.lint_cmd})")
            result = await self.ctx.runtime_manager.run_lint(project_path)
            output.append(f"**Durum:** {'✅ Başarılı' if result.success else '❌ Başarısız'}")
        return "\n".join(output)

    async def run_retrieval_eval(self, dataset_name: str, collection: str) -> str:
        dataset = self.ctx.dataset_manager.load_dataset(dataset_name)
        if not dataset:
            return f"❌ Veri seti bulunamadı: `{dataset_name}`"
        runner = EvalRunner(self.retrieval.search_code)
        results = await runner.run_eval(dataset, collection)
        summary = results["summary"]
        return "\n".join(
            [
                f"## 📊 Retrieval Eval — {dataset_name} ({collection})",
                f"- **Toplam Case:** {summary['total_cases']}",
                f"- **Hit@1:** {summary['hit_at_1']:.1%}",
                f"- **Hit@3:** {summary['hit_at_3']:.1%}",
                f"- **Hit@5:** {summary['hit_at_5']:.1%}",
                f"- **MRR:** {summary['mrr']:.3f}",
                f"- **Faithfulness:** {summary['faithfulness']:.3f}",
                f"- **Ort. Gecikme:** {summary['avg_latency_sec']:.2f}s",
            ]
        )
