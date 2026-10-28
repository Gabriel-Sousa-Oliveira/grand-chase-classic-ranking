# Auditoria Gemini — prioridade da fila OCR — 2026-10-28

Revise este pacote autocontido. Identifique bugs reproduzíveis, distinguindo-os
 de hipóteses e escolhas intencionais. Não é necessário autenticar no GitHub.

## Problema

A automação selecionava por video_id dentro da maior categoria. Vídeos já
sem consenso ou com falha voltavam à frente, ocupando o limite de 12 por execução.
O histórico preservado no banco agora permite uma seleção que avance na fila.

## Contrato proposto

- Somente categorias permitidas, sem tempo e nos estados time_required ou
  classification_required são elegíveis.
- A seleção é global ANTES de aplicar o limite de 12: todos os nunca tentados
  precedem qualquer nova tentativa, inclusive entre categorias diferentes.
- Depois vêm menos tentativas, depois a tentativa mais antiga. Histórico legado
  com outcome ou timestamp, mesmo sem contador, conta como uma tentativa.
- Empates: maior backlog da categoria, ordem configurada de categorias, video_id.
- Após selecionar os 12, a execução continua agrupada por categoria; a prioridade
  garante quem entra no lote, não a ordem de início de cada subprocesso.
- No-consensus continua elegível para retry depois dos inéditos, como já ocorria
  neste workflow. A política padrão do CLI (excluí-lo) permanece intacta.
- Limite de 12, lotes de 8, até 4 workers e orçamento por vídeo permanecem iguais.
- A função só consulta dados. Não grava tempos, não aprova candidatos e não muda
  o parser de OCR nem a preservação de tempos implementada no PR #16.

## Validação

- 137 testes do backend passaram, incluindo 6 novos testes.
- Dependências para a suíte: numpy 1.26.4 e opencv-python-headless 4.10.0.84.
- A tentativa inicial na instalação padrão falhou por ausência de cv2; a suíte
  completa passou após instalar as dependências num ambiente isolado.
- Teste de integração executa o bloco real de seleção do workflow em banco
  temporário, verifica limite e prioridade global.
- Simulação SOMENTE LEITURA sobre o snapshot do crawler #200 selecionou 12
  vídeos sem tentativa anterior. Nenhum OCR ao vivo foi executado nesta mudança.
- Blocos Python embutidos no workflow passaram na análise de sintaxe.
- Ainda não foi medida redução de tempo de execução: esta correção evita
  repetição prioritária, não promete acelerar cada vídeo individualmente.

## Pontos para auditoria

Verifique filtros de elegibilidade, prioridade entre categorias, aplicação do
limite antes do agrupamento, rotação das tentativas, compatibilidade dos
metadados e ausência de escrita na função. Assuma o contrato existente de
raw_metadata como objeto JSON válido e timestamps produzidos em UTC.

## Diff completo da implementação e dos testes

```diff
diff --git a/.github/workflows/ocr-scale.yml b/.github/workflows/ocr-scale.yml
index 60c7d99..5d854c4 100644
--- a/.github/workflows/ocr-scale.yml
+++ b/.github/workflows/ocr-scale.yml
@@ -171,6 +171,8 @@ jobs:
           from concurrent.futures import ThreadPoolExecutor, as_completed
           from pathlib import Path
 
+          from gc_radar.ocr_queue import pending_ocr_videos
+
           MASTER = Path("../data/gc_radar.sqlite3").resolve()
           OUTPUT = Path("../data/last-run.json").resolve()
           DIAGNOSTICS = Path("../data/ocr-diagnostics.json").resolve()
@@ -192,15 +194,6 @@ jobs:
           EVIDENCE.mkdir(parents=True, exist_ok=True)
           SHARDS.mkdir(parents=True, exist_ok=True)
 
-          def pending_ids(connection: sqlite3.Connection, category: str) -> list[str]:
-              return [row[0] for row in connection.execute(
-                  "SELECT video_id FROM candidates WHERE category = ? "
-                  "AND time_ms IS NULL AND status IN "
-                  "('time_required', 'classification_required') "
-                  "ORDER BY video_id",
-                  (category,),
-              )]
-
           def write_checkpoint(summary: dict) -> None:
               temporary = OUTPUT.with_suffix(".tmp")
               temporary.write_text(json.dumps(summary, ensure_ascii=False))
@@ -214,8 +207,10 @@ jobs:
               diagnostic_temporary.replace(DIAGNOSTICS)
 
           with sqlite3.connect(MASTER) as connection:
-              counts = {category: len(pending_ids(connection, category))
-                        for category in ALLOWED}
+              pending = pending_ocr_videos(connection, ALLOWED)
+          counts = {category: sum(item[1] == category for item in pending)
+                    for category in ALLOWED}
+          selected = pending[:MAX_VIDEOS_PER_RUN]
           order_index = {category: index for index, category in enumerate(ALLOWED)}
           ordered = sorted(ALLOWED, key=lambda category: (-counts[category], order_index[category]))
           summary = {
@@ -283,11 +278,10 @@ jobs:
                       if evidence.is_file() and KEEP_EVIDENCE.search(evidence.name):
                           shutil.copy2(evidence, EVIDENCE / evidence.name)
 
-          budget_remaining = MAX_VIDEOS_PER_RUN
           with sqlite3.connect(MASTER) as master:
               for category in ordered:
-                  ids = pending_ids(master, category)[:budget_remaining]
-                  budget_remaining -= len(ids)
+                  ids = [video_id for video_id, selected_category in selected
+                         if selected_category == category]
                   batches = [ids[start:start + BATCH_SIZE]
                              for start in range(0, len(ids), BATCH_SIZE)]
                   stats = {
diff --git a/backend/gc_radar/ocr_queue.py b/backend/gc_radar/ocr_queue.py
new file mode 100644
index 0000000..9147ef4
--- /dev/null
+++ b/backend/gc_radar/ocr_queue.py
@@ -0,0 +1,38 @@
+"""Read-only selection shared by the bounded OCR workflow and its tests."""
+from collections import Counter
+import sqlite3
+from typing import Iterable
+
+
+def pending_ocr_videos(connection: sqlite3.Connection,
+                       categories: Iterable[str]) -> list[tuple[str, str]]:
+    """Order eligible (video_id, category) pairs before applying the run cap.
+
+    Never-attempted videos precede all retries, across categories. Retries
+    prefer fewer attempts, then the oldest attempt. Equal histories prefer
+    the largest category backlog, configured category order, and video ID.
+    An outcome or timestamp also marks legacy rows with no counter as tried.
+    """
+    categories = tuple(dict.fromkeys(categories))
+    if not categories:
+        return []
+    placeholders = ','.join('?' for _ in categories)
+    rows = connection.execute(f"""
+        SELECT video_id, category,
+               COALESCE(CAST(json_extract(raw_metadata, '$.ocr_attempts') AS INTEGER), 0),
+               json_extract(raw_metadata, '$.ocr_attempted_at'),
+               json_extract(raw_metadata, '$.ocr_outcome')
+        FROM candidates WHERE category IN ({placeholders})
+          AND time_ms IS NULL
+          AND status IN ('time_required', 'classification_required')
+    """, categories).fetchall()
+    counts = Counter(row[1] for row in rows)
+    category_order = {category: index for index, category in enumerate(categories)}
+
+    def priority(row):
+        video_id, category, attempts, attempted_at, outcome = row
+        tried = attempts > 0 or attempted_at is not None or outcome is not None
+        return (tried, max(1, attempts) if tried else 0, attempted_at or '',
+                -counts[category], category_order[category], video_id)
+
+    return [(row[0], row[1]) for row in sorted(rows, key=priority)]
diff --git a/backend/tests/test_ocr_queue.py b/backend/tests/test_ocr_queue.py
new file mode 100644
index 0000000..1e471c0
--- /dev/null
+++ b/backend/tests/test_ocr_queue.py
@@ -0,0 +1,91 @@
+import json
+import sqlite3
+import unittest
+from pathlib import Path
+
+from gc_radar.ocr_queue import pending_ocr_videos
+
+
+class OcrQueueTests(unittest.TestCase):
+    def setUp(self):
+        self.db = sqlite3.connect(':memory:')
+        self.addCleanup(self.db.close)
+        self.db.execute('CREATE TABLE candidates (video_id TEXT, category TEXT, '
+                        'time_ms INTEGER, status TEXT, raw_metadata TEXT)')
+
+    def add(self, video_id, category='large', metadata=None, time=None,
+            status='time_required'):
+        self.db.execute('INSERT INTO candidates VALUES (?, ?, ?, ?, ?)',
+                        (video_id, category, time, status, json.dumps(metadata or {})))
+
+    def ids(self):
+        return [video for video, _ in pending_ocr_videos(self.db, ['large', 'small'])]
+
+    def test_new_videos_in_smaller_category_precede_all_retries(self):
+        self.add('a-retry', metadata={'ocr_attempts': 1, 'ocr_outcome': 'error'})
+        self.add('b-retry', metadata={'ocr_attempts': 2, 'ocr_outcome': 'no_consensus'})
+        self.add('z-new', 'small')
+        self.assertEqual(self.ids()[:1], ['z-new'])
+
+    def test_retry_rotation_uses_count_then_oldest_attempt_not_updated_at(self):
+        self.add('many', metadata={'ocr_attempts': 3, 'ocr_attempted_at': '2026-01-01'})
+        self.add('recent', metadata={'ocr_attempts': 1, 'ocr_attempted_at': '2026-10-28'})
+        self.add('old', metadata={'ocr_attempts': 1, 'ocr_attempted_at': '2026-10-01'})
+        self.assertEqual(self.ids(), ['old', 'recent', 'many'])
+        self.db.execute("UPDATE candidates SET raw_metadata = ? WHERE video_id = 'old'",
+                        (json.dumps({'ocr_attempts': 2, 'ocr_attempted_at': '2026-10-28'}),))
+        self.assertEqual(self.ids(), ['recent', 'old', 'many'])
+
+    def test_legacy_outcome_or_timestamp_counts_as_attempt(self):
+        self.add('a-outcome', metadata={'ocr_outcome': 'no_consensus'})
+        self.add('b-timestamp', metadata={'ocr_attempted_at': '2026-01-01'})
+        self.add('z-new')
+        self.assertEqual(self.ids(), ['z-new', 'a-outcome', 'b-timestamp'])
+
+    def test_filters_time_status_and_category_and_accepts_partial_classification(self):
+        self.add('timed', time=80000)
+        self.add('approved', status='approved')
+        self.add('rejected', status='rejected')
+        self.add('review', status='ready_for_review')
+        self.add('unsupported', category='other')
+        self.add('partial', status='classification_required')
+        self.assertEqual(self.ids(), ['partial'])
+        self.assertEqual(pending_ocr_videos(self.db, []), [])
+
+    def test_ties_prefer_backlog_then_configured_category_then_id(self):
+        self.add('z', 'small')
+        self.add('b')
+        self.add('a')
+        self.assertEqual(self.ids(), ['a', 'b', 'z'])
+        self.add('y', 'small')
+        self.assertEqual(self.ids(), ['a', 'b', 'y', 'z'])
+
+    def test_workflow_selects_once_globally_before_regrouping(self):
+        # Execute the actual selection block embedded in the workflow, without
+        # launching OCR, networking, or modifying the production database.
+        import textwrap
+        workflow = Path(__file__).resolve().parents[2] / '.github/workflows/ocr-scale.yml'
+        source = workflow.read_text()
+        start = source.index('          with sqlite3.connect(MASTER) as connection:')
+        end = source.index('          order_index', start)
+        with self.db:
+            for index in range(15):
+                self.add(f'retry-{index}', metadata={'ocr_attempts': 1})
+            self.add('new', 'small')
+        import tempfile
+        with tempfile.NamedTemporaryFile(suffix='.sqlite3') as file:
+            disk = sqlite3.connect(file.name)
+            self.db.backup(disk)
+            disk.close()
+            namespace = dict(sqlite3=sqlite3, MASTER=file.name,
+                             ALLOWED=('large', 'small'), MAX_VIDEOS_PER_RUN=12,
+                             pending_ocr_videos=pending_ocr_videos)
+            exec(textwrap.dedent(source[start:end]), namespace)
+        self.assertEqual(len(namespace['selected']), 12)
+        self.assertEqual(namespace['selected'][0], ('new', 'small'))
+        self.assertEqual(namespace['counts'], {'large': 15, 'small': 1})
+        self.assertNotIn('pending_ids(', source)
+
+
+if __name__ == '__main__':
+    unittest.main()

```
