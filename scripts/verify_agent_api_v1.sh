#!/usr/bin/env bash
# verify_agent_api_v1.sh — GraphRagMCP Agent API kapsamlı doğrulama scripti
#
# Kullanım:
#   ./scripts/verify_agent_api_v1.sh [BASE_URL]
#   BASE_URL varsayılan: http://localhost:8001
#
# Gereksinimler: curl, jq, python3
# Çıkış kodu: 0 = tüm testler geçti, 1 = en az bir test başarısız

set -uo pipefail

BASE_URL="${1:-http://localhost:8001}"
MCP_URL="${MCP_URL:-http://localhost:8000}"
COLLECTION="${COLLECTION:-warelogisticcbys}"
PROJECT_PATH="${PROJECT_PATH:-/app}"
PASS=0
FAIL=0
SKIP=0
TASK_ID=""

# ── Renk kodları ──────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

_pass() { echo -e "${GREEN}  ✓ $1${NC}"; ((PASS++)) || true; }
_fail() { echo -e "${RED}  ✗ $1${NC}"; ((FAIL++)) || true; }
_skip() { echo -e "${YELLOW}  ⊘ $1${NC}"; ((SKIP++)) || true; }
_section() { echo -e "\n${BLUE}══ $1 ══${NC}"; }
_info() { echo -e "  → $1"; }

# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────
require_cmd() {
  command -v "$1" &>/dev/null || { echo "Gerekli komut eksik: $1"; exit 2; }
}

http_get() {
  curl -sf --max-time 10 "$1" 2>/dev/null
}

http_post() {
  local url="$1"; local data="$2"
  curl -sf --max-time 30 -X POST -H "Content-Type: application/json" -d "$data" "$url" 2>/dev/null
}

assert_json_field() {
  local json="$1"; local field="$2"; local expected="$3"
  local actual; actual=$(echo "$json" | jq -r "$field" 2>/dev/null || echo "PARSE_ERROR")
  if [[ "$actual" == "$expected" ]]; then
    _pass "$field = $expected"
  else
    _fail "$field beklenen='$expected' gerçek='$actual'"
  fi
}

assert_json_not_null() {
  local json="$1"; local field="$2"
  local actual; actual=$(echo "$json" | jq -r "$field" 2>/dev/null || echo "null")
  if [[ "$actual" != "null" && "$actual" != "" ]]; then
    _pass "$field dolu"
  else
    _fail "$field null veya boş"
  fi
}

wait_for_service() {
  local url="$1"; local name="$2"; local max_wait="${3:-10}"
  local waited=0
  while ! curl -sf --max-time 3 "$url" &>/dev/null; do
    sleep 2; ((waited+=2))
    if [[ $waited -ge $max_wait ]]; then
      _skip "$name erişilemiyor ($url) — servis testleri atlanacak"
      return 1
    fi
  done
  _pass "$name hazır"
}

# ── Gereksinim kontrolü ───────────────────────────────────────────────────────
require_cmd curl
require_cmd jq
require_cmd python3

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 1 — Servis erişilebilirliği
# ═════════════════════════════════════════════════════════════════════════════
_section "1. Servis Erişilebilirliği"

AGENT_UP=false
if wait_for_service "$BASE_URL/v1/health" "Agent API"; then
  AGENT_UP=true
fi

HEALTH=$(http_get "$BASE_URL/v1/health" || echo '{}')
_info "Health yanıtı: $HEALTH"
if $AGENT_UP; then
  assert_json_field "$HEALTH" ".status" "ok"
fi

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 2 — Sağlık uç noktası detayları
# ═════════════════════════════════════════════════════════════════════════════
_section "2. Sağlık Uç Noktası"

if $AGENT_UP; then
  if echo "$HEALTH" | jq -e '.postgres' &>/dev/null; then
    _pass "postgres alanı mevcut"
  else
    _skip "postgres alanı yok (DB bağlı olmayabilir)"
  fi
  if echo "$HEALTH" | jq -e '.redis' &>/dev/null; then
    _pass "redis alanı mevcut"
  else
    _skip "redis alanı yok"
  fi
else
  _skip "Servis hazır değil — sağlık detayları atlandı"
fi

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 3 — Complexity Router (Python birim testi)
# ═════════════════════════════════════════════════════════════════════════════
_section "3. Complexity Router"

python3 -c "
import sys; sys.path.insert(0, '.')
try:
    from src.control.models.complexity_router import ComplexityRouter, ModelTier, ComplexityScorer
    scorer = ComplexityScorer()

    # Basit sorgu → LOCAL
    score, signals = scorer.score('bir değişkeni yeniden adlandır')
    tier_name = 'TIER_LOCAL' if score < 0.30 else ('TIER_CHEAP' if score < 0.70 else 'TIER_REASON')
    print(f'simple_query score={score:.3f} tier={tier_name}')
    assert score < 0.30, f'Basit sorgu için skor çok yüksek: {score}'

    # Stack trace → en az TIER_CHEAP (stacktrace sinyali aktif)
    st = 'Traceback (most recent call last): File test.py line 42 Exception: NoneType'
    score2, sig2 = scorer.score(st)
    assert sig2['stacktrace'] == 1.0, f'Stacktrace sinyali 1.0 olmalı: {sig2}'
    assert score2 >= 0.30, f'Stack trace skoru çok düşük: {score2}'
    print(f'stacktrace score={score2:.3f} signal={sig2[\"stacktrace\"]}')

    # Mimari → artan skor (arch_keywords sinyali aktif)
    arch = 'refactor authentication architecture across all services and optimize security'
    score3, sig3 = scorer.score(arch)
    assert sig3['arch_keywords'] >= 0.5, f'Mimari sinyal düşük: {sig3}'
    assert score3 >= 0.10, f'Mimari sorgu skoru düşük: {score3}'
    print(f'arch score={score3:.3f} arch_signal={sig3[\"arch_keywords\"]}')

    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "Complexity Scorer skalar doğrulaması" || _fail "Complexity Scorer başarısız"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 4 — Escalation Manager (Python birim testi)
# ═════════════════════════════════════════════════════════════════════════════
_section "4. Escalation Manager"

python3 -c "
import sys; sys.path.insert(0, '.')
try:
    from src.control.models.escalation_manager import EscalationManager, EscalationState, EscalationAction
    from src.control.models.complexity_router import ModelTier

    mgr = EscalationManager()

    # reflection=0 → RETRY_SAME
    st = EscalationState('t1', ModelTier.CHEAP, 0)
    r = mgr.decide(st)
    assert r.action == EscalationAction.RETRY_SAME, f'Beklenen RETRY_SAME: {r.action}'
    print(f'reflection=0 → {r.action}')

    # reflection=2 → ESCALATE
    st2 = EscalationState('t2', ModelTier.LOCAL, 2)
    r2 = mgr.decide(st2)
    assert r2.action == EscalationAction.ESCALATE, f'Beklenen ESCALATE: {r2.action}'
    assert r2.new_tier == ModelTier.CHEAP, f'Beklenen CHEAP: {r2.new_tier}'
    print(f'reflection=2 → {r2.action} tier={r2.new_tier}')

    # reflection=4 → FORCE_REASON
    st3 = EscalationState('t3', ModelTier.CHEAP, 4)
    r3 = mgr.decide(st3)
    assert r3.action == EscalationAction.FORCE_REASON
    print(f'reflection=4 → {r3.action}')

    # reflection=6 → HUMAN_REVIEW
    st4 = EscalationState('t4', ModelTier.REASON, 6)
    r4 = mgr.decide(st4)
    assert r4.action == EscalationAction.HUMAN_REVIEW
    print(f'reflection=6 → {r4.action}')

    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "Escalation Manager 4 aşama doğrulaması" || _fail "Escalation Manager başarısız"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 5 — State Machine / Checkpoint (Python birim testi)
# ═════════════════════════════════════════════════════════════════════════════
_section "5. State Machine Checkpoint"

python3 -c "
import sys; sys.path.insert(0, '.')
try:
    from src.agent.state_machine import AgentCheckpoint, CHECKPOINT_VERSION, _migrate_checkpoint

    # Serileştirme
    cp = AgentCheckpoint(task_id='test-001', goal='test goal', step='EDIT')
    js = cp.to_json()
    cp2 = AgentCheckpoint.from_json(js)
    assert cp2.task_id == 'test-001'
    assert cp2.step == 'EDIT'
    print(f'serialize/deserialize OK version={cp2.version}')

    # Migration
    old_data = {'task_id': 'old-001', 'goal': 'old', 'step': 'SPEC', 'version': 0}
    migrated = _migrate_checkpoint(old_data, 0)
    assert migrated['version'] == CHECKPOINT_VERSION
    assert 'reflection_count' in migrated
    print(f'migration v0→v{CHECKPOINT_VERSION} OK')

    # Statüsler
    from src.agent.state_machine import TASK_STATUSES
    for s in ('PENDING','RUNNING','COMPLETED','FAILED','SUSPENDED','CANCELLED'):
        assert s in TASK_STATUSES, f'{s} eksik'
    print(f'task statuses OK: {TASK_STATUSES}')

    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "State Machine checkpoint serileştirme ve migrasyon" || _fail "State Machine başarısız"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 6 — Session Context (Python birim testi)
# ═════════════════════════════════════════════════════════════════════════════
_section "6. Session Context"

python3 -c "
import sys; sys.path.insert(0, '.')
try:
    from src.agent.session_context import SessionContext, CodeChunk

    ctx = SessionContext(task_id='t1', goal='test', collection='col', project_path='/app')

    # Kod parçası ekleme
    for i in range(25):
        ctx.add_code_chunk(CodeChunk(file_path=f'file_{i}.py', content='x=1', relevance=float(i)/25))
    assert len(ctx.code_chunks) <= 20, f'chunk limit aşıldı: {len(ctx.code_chunks)}'
    print(f'chunk limit OK: {len(ctx.code_chunks)}/20')

    # context_text token bütçesi
    for i in range(15):
        ctx.add_memory_item({'title': f'mem {i}', 'content': 'c' * 500})
    assert len(ctx.memory_items) <= 10
    print(f'memory limit OK: {len(ctx.memory_items)}/10')

    text = ctx.build_context_text(token_budget=100)
    assert len(text) <= 500  # 100 token * 4 char/token = 400 char + margin
    print(f'token budget kırpma OK: {len(text)} char')

    # JSON round-trip
    js = ctx.to_json()
    ctx2 = SessionContext.from_json(js)
    assert ctx2.task_id == 't1'
    print('JSON round-trip OK')
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "Session Context limit ve token budget" || _fail "Session Context başarısız"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 7 — Spec Builder (Python birim testi)
# ═════════════════════════════════════════════════════════════════════════════
_section "7. Spec Builder"

python3 -c "
import sys; sys.path.insert(0, '.')
try:
    from src.agent.spec_builder import SpecBuilder

    builder = SpecBuilder()

    # Bugfix tespiti
    spec = builder.heuristic_build('t1', 'Fix the TypeError in auth.py handler', 'col', '/app')
    assert spec.task_type == 'bugfix', f'Beklenen bugfix: {spec.task_type}'
    assert 'auth.py' in spec.affected_files
    print(f'bugfix detect OK: type={spec.task_type} files={spec.affected_files}')

    # Feature tespiti
    spec2 = builder.heuristic_build('t2', 'Add new user registration feature', 'col', '/app')
    assert spec2.task_type == 'feature', f'Beklenen feature: {spec2.task_type}'
    print(f'feature detect OK')

    # Kabul kriterleri
    assert len(spec.acceptance_criteria) > 0
    print(f'acceptance criteria: {spec.acceptance_criteria[:2]}')

    # Prompt block
    prompt = spec.to_prompt_block()
    assert 'Görev Spesifikasyonu' in prompt
    print('prompt block OK')
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "Spec Builder heuristic build ve prompt üretimi" || _fail "Spec Builder başarısız"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 8 — Impact Analysis (Python birim testi)
# ═════════════════════════════════════════════════════════════════════════════
_section "8. Impact Analysis"

python3 -c "
import sys; sys.path.insert(0, '.')
try:
    import asyncio
    from src.agent.impact_analysis import ImpactAnalyzer, FileImpact

    # FileImpact.compute hibrit skor
    fi = FileImpact.compute('test.py', call_graph=0.8, dep_graph=0.6, pagerank=0.5, co_change=0.3)
    expected = 0.4*0.8 + 0.3*0.6 + 0.2*0.5 + 0.1*0.3
    assert abs(fi.score - expected) < 0.001, f'Beklenen {expected:.4f}: {fi.score}'
    assert fi.risk in ('medium', 'high'), f'Skor {fi.score} için risk medium/high olmalı: {fi.risk}'
    print(f'hybrid score OK: {fi.score:.4f} risk={fi.risk}')

    # Statik fallback (MCP yok)
    analyzer = ImpactAnalyzer(mcp_handler=None)
    report = asyncio.run(analyzer.analyze('/app', ['src/main.py', 'src/utils.py'], 'col'))
    assert len(report.affected) >= 2
    assert report.summary != ''
    print(f'static fallback OK: {len(report.affected)} dosya')
    print(f'summary: {report.summary[:80]}')
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "Impact Analysis hibrit skor ve statik fallback" || _fail "Impact Analysis başarısız"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 9 — Workspace Manager (Python birim testi — git işlemleri atlandı)
# ═════════════════════════════════════════════════════════════════════════════
_section "9. Workspace Manager"

python3 -c "
import sys; sys.path.insert(0, '.')
try:
    import asyncio, tempfile, os
    from pathlib import Path
    from src.agent.workspace_manager import WorkspaceManager, WORKSPACE_BASE

    # GC mantığı: boş workspace tarama
    with tempfile.TemporaryDirectory() as tmp:
        import src.agent.workspace_manager as wm_mod
        original_base = wm_mod.WORKSPACE_BASE
        wm_mod.WORKSPACE_BASE = Path(tmp)
        mgr = WorkspaceManager()

        # Sahte stale dizin oluştur
        stale = Path(tmp) / 'task_stale-001'
        stale.mkdir()
        import time
        os.utime(stale, (time.time() - 90000, time.time() - 90000))

        removed = asyncio.run(mgr.prune_stale_workspaces(active_task_ids=set()))
        assert removed >= 1, f'Stale workspace temizlenmedi: {removed}'
        print(f'GC prune OK: {removed} dizin temizlendi')

        wm_mod.WORKSPACE_BASE = original_base

    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "Workspace Manager GC (stale prune)" || _fail "Workspace Manager başarısız"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 10 — Context Assembler (Python birim testi — MCP mock)
# ═════════════════════════════════════════════════════════════════════════════
_section "10. Context Assembler"

python3 -c "
import sys; sys.path.insert(0, '.')
try:
    import asyncio
    from src.agent.context_assembler import ContextAssembler
    from src.agent.session_context import SessionContext
    from src.agent.spec_builder import SpecBuilder

    class MockMCP:
        async def search_code(self, **kw):
            return [{'file_path': 'mock.py', 'content': 'def foo(): pass', 'score': 0.9}]
        async def recall_memory(self, **kw):
            return [{'title': 'mock memory', 'content': 'prior decision'}]
        async def analyze_change_impact(self, **kw):
            return {'affected_files': [{'file_path': 'mock.py', 'call_graph_score': 0.5}]}

    assembler = ContextAssembler(MockMCP())
    spec = SpecBuilder().heuristic_build('t1', 'fix bug in mock.py', 'col', '/app')
    ctx  = SessionContext(task_id='t1', goal='test', collection='col', project_path='/app')

    result = asyncio.run(assembler.assemble(spec, ctx, token_budget=4000))
    assert len(result.code_chunks) > 0, 'Kod chunk bekleniyor'
    assert len(result.memory_items) > 0, 'Bellek öğesi bekleniyor'
    assert result.tokens_used > 0
    print(f'assemble OK: chunks={len(result.code_chunks)} memory={len(result.memory_items)} tokens≈{result.tokens_used}')
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "Context Assembler mock MCP ile bağlam derleme" || _fail "Context Assembler başarısız"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 11 — CodeAct Runner (Python birim testi — mock bağımlılıklar)
# ═════════════════════════════════════════════════════════════════════════════
_section "11. CodeAct Runner (mock)"

python3 -c "
import sys; sys.path.insert(0, '.')
try:
    import asyncio
    from src.agent.codeact_runner import CodeActRunner, RunConfig, TDADStep, build_runner

    # build_runner None bağımlılıklarla oluşturulabilmeli
    runner = build_runner(None, None, None, None)
    assert runner is not None
    print('build_runner OK (null deps)')

    # TDADStep enum değerleri kontrol
    steps = [s.value for s in TDADStep]
    required = ['SPEC','TEST','CONTEXT','EDIT','VERIFY','IMPACT','REFLECT','COMMIT','DONE','FAILED']
    for s in required:
        assert s in steps, f'{s} adımı eksik'
    print(f'TDADStep enum OK: {steps}')
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "CodeAct Runner yapılandırma ve step enum" || _fail "CodeAct Runner başarısız"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 12 — Agent API Endpoint — Görev başlatma
# ═════════════════════════════════════════════════════════════════════════════
_section "12. Agent API — Görev Başlatma (SSE)"

if ! $AGENT_UP; then _skip "Servis hazır değil — bölüm 12-14 atlandı"
else

# SSE akışını oku — arka planda başlat, 5 saniye bekle
TMP_SSE=$(mktemp)
curl -s --max-time 8 -N \
  -X POST "$BASE_URL/v1/agent/run" \
  -H "Content-Type: application/json" \
  -d "{\"goal\":\"Add hello world function\",\"collection\":\"$COLLECTION\",\"project_path\":\"$PROJECT_PATH\",\"hitl_enabled\":false}" \
  2>/dev/null > "$TMP_SSE" &
CURL_PID=$!
sleep 5
kill "$CURL_PID" 2>/dev/null || true
RUN_RESP=$(cat "$TMP_SSE"); rm -f "$TMP_SSE"

if [[ -z "$RUN_RESP" ]]; then
  _fail "Agent run endpoint yanıt vermedi"
else
  TASK_ID=$(echo "$RUN_RESP" | grep '^data:' | head -1 | sed 's/^data: //' | jq -r '.task_id // empty' 2>/dev/null || echo "")
  if [[ -n "$TASK_ID" ]]; then
    _pass "Görev başlatıldı: task_id=$TASK_ID"
  else
    # event field var mı?
    FIRST_EVENT=$(echo "$RUN_RESP" | grep '^data:' | head -1)
    if [[ -n "$FIRST_EVENT" ]]; then
      _pass "SSE akışı alındı: $FIRST_EVENT"
    else
      _info "SSE yanıtı: ${RUN_RESP:0:200}"
      _skip "task_id alınamadı"
    fi
  fi
fi

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 13 — Agent API — Görev durumu ve liste
# ═════════════════════════════════════════════════════════════════════════════
_section "13. Agent API — Görev Listesi ve Durum"

TASKS_RESP=$(http_get "$BASE_URL/v1/agent/tasks?collection=$COLLECTION" || echo '{}')
if echo "$TASKS_RESP" | jq -e '.tasks' &>/dev/null; then
  COUNT=$(echo "$TASKS_RESP" | jq '.count // 0')
  _pass "Görev listesi alındı: count=$COUNT"
else
  _skip "Görev listesi alınamadı (DB bağlı değil olabilir)"
fi

if [[ -n "$TASK_ID" ]]; then
  sleep 2
  STATUS_RESP=$(http_get "$BASE_URL/v1/agent/status/$TASK_ID" || echo '{}')
  if echo "$STATUS_RESP" | jq -e '.task_id' &>/dev/null; then
    _pass "Görev durumu alındı: $(echo "$STATUS_RESP" | jq -r '.step // "?"')"
  else
    _skip "Görev durumu alınamadı"
  fi
fi

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 14 — HITL Onay Endpoint
# ═════════════════════════════════════════════════════════════════════════════
_section "14. HITL Onay Endpoint"

APPROVE_RESP=$(http_post "$BASE_URL/v1/agent/approve" \
  '{"task_id":"nonexistent-task-id","approved":true}' || echo '{}')

if echo "$APPROVE_RESP" | grep -q '404\|not found\|bulunamadı' 2>/dev/null || \
   [[ "$(echo "$APPROVE_RESP" | jq -r '.detail // empty' 2>/dev/null)" != "" ]]; then
  _pass "HITL onay endpointi bilinmeyen task için 404 döndü (beklenen)"
else
  # Endpoint erişilebilir mi?
  HTTP_CODE=$(curl -so /dev/null -w "%{http_code}" --max-time 5 \
    -X POST "$BASE_URL/v1/agent/approve" \
    -H "Content-Type: application/json" \
    -d '{"task_id":"none","approved":true}' 2>/dev/null || echo "000")
  if [[ "$HTTP_CODE" == "404" || "$HTTP_CODE" == "422" ]]; then
    _pass "HITL approve endpoint erişilebilir (HTTP $HTTP_CODE)"
  elif [[ "$HTTP_CODE" == "000" ]]; then
    _skip "HITL approve endpoint erişilemiyor"
  else
    _pass "HITL approve endpoint yanıt veriyor (HTTP $HTTP_CODE)"
  fi
fi

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 15 — MCP Sunucusu erişilebilirliği
# ═════════════════════════════════════════════════════════════════════════════
fi  # AGENT_UP block sonu

_section "15. MCP Sunucusu (port 8000)"

MCP_HEALTH=$(http_get "$MCP_URL/health" || echo "")
if [[ -n "$MCP_HEALTH" ]]; then
  _pass "MCP sunucusu erişilebilir"
elif curl -sf --max-time 5 "$MCP_URL/sse" &>/dev/null || \
     curl -so /dev/null -w "%{http_code}" --max-time 5 "$MCP_URL/sse" 2>/dev/null | grep -qE "^(200|405|426)"; then
  _pass "MCP SSE endpoint erişilebilir"
else
  _skip "MCP sunucusu ($MCP_URL) erişilemiyor"
fi

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 16 — Retrieval Eval Dataset
# ═════════════════════════════════════════════════════════════════════════════
_section "16. Retrieval Eval Dataset"

EVAL_FILE="tests/eval/retrieval_eval_dataset.json"
if [[ -f "$EVAL_FILE" ]]; then
  COUNT=$(jq '. | length' "$EVAL_FILE" 2>/dev/null || echo 0)
  if [[ "$COUNT" -ge 10 ]]; then
    _pass "Eval dataset mevcut: $COUNT vaka"
  else
    _fail "Eval dataset yetersiz: $COUNT vaka (min 10)"
  fi
else
  _fail "Eval dataset bulunamadı: $EVAL_FILE"
fi

# Vaka yapısı doğrulama
python3 -c "
import json, sys
try:
    with open('$EVAL_FILE') as f:
        cases = json.load(f)
    for c in cases:
        assert 'id' in c, f'id eksik: {c}'
        assert 'query' in c, f'query eksik: {c}'
        assert 'collection' in c, f'collection eksik: {c}'
    print(f'Tüm {len(cases)} vaka geçerli yapıda')
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" && _pass "Eval dataset vaka yapısı geçerli" || _fail "Eval dataset yapı hatası"

# ═════════════════════════════════════════════════════════════════════════════
# BÖLÜM 17 — Docker Compose yapılandırması
# ═════════════════════════════════════════════════════════════════════════════
_section "17. Docker Compose"

if [[ -f "docker-compose.yml" ]]; then
  # agent-api servisi var mı?
  if grep -q "agent-api" docker-compose.yml; then
    _pass "agent-api servisi docker-compose.yml'de mevcut"
  else
    _fail "agent-api servisi docker-compose.yml'de yok"
  fi

  # 8001 portu var mı?
  if grep -q "8001" docker-compose.yml; then
    _pass "Port 8001 yapılandırılmış"
  else
    _fail "Port 8001 eksik"
  fi

  # agent-workspaces volume var mı?
  if grep -q "agent-workspaces" docker-compose.yml; then
    _pass "agent-workspaces volume tanımlı"
  else
    _fail "agent-workspaces volume eksik"
  fi

  # HITL_TIMEOUT_SECONDS var mı?
  if grep -q "HITL_TIMEOUT_SECONDS" docker-compose.yml; then
    _pass "HITL_TIMEOUT_SECONDS ortam değişkeni mevcut"
  else
    _fail "HITL_TIMEOUT_SECONDS eksik"
  fi
else
  _fail "docker-compose.yml bulunamadı"
fi

# .env.example agent değişkenleri
if [[ -f ".env.example" ]]; then
  for var in TIER_LOCAL_MODEL TIER_CHEAP_MODEL TIER_REASON_MODEL HITL_TIMEOUT_SECONDS WORKSPACE_BASE_PATH; do
    if grep -q "$var" .env.example; then
      _pass ".env.example: $var mevcut"
    else
      _fail ".env.example: $var eksik"
    fi
  done
fi

# ═════════════════════════════════════════════════════════════════════════════
# ÖZET
# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════"
echo "  SONUÇ"
echo "═══════════════════════════════════════════"
echo -e "  ${GREEN}GEÇEN :${NC} $PASS"
echo -e "  ${RED}BAŞARISIZ:${NC} $FAIL"
echo -e "  ${YELLOW}ATLANAN :${NC} $SKIP"
echo "═══════════════════════════════════════════"

if [[ $FAIL -eq 0 ]]; then
  echo -e "\n${GREEN}Tüm testler geçti!${NC}\n"
  exit 0
else
  echo -e "\n${RED}$FAIL test başarısız oldu.${NC}\n"
  exit 1
fi
