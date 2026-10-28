# Auditoria Gemini — leitura do Clear Time

## Pedido ao revisor

Revise o diff desta branch contra main e os arquivos completos relacionados.
Procure erros demonstráveis que possam aceitar um tempo incorreto, rejeitar um
Clear Time válido ou exceder o orçamento por vídeo. Para cada problema, informe
severidade, arquivo/linha, exemplo reproduzível e teste sugerido. Diferencie erro
confirmado de hipótese e melhoria opcional. Não reescreva o projeto.

Regras: somente a linha Clear Time da tela de resultados pode fornecer o tempo
visual; HUD não fornece tempo aceito; números estáveis sem contexto não bastam;
aprovação humana continua obrigatória. Tempos esperados servem para avaliar a
saída, nunca para selecionar leituras do OCR.

## Base e diagnóstico

Base inspecionada: `126158b94dc5f954b00c641fd528ac6f0a848367`.
Artefato original: `gc-ocr-validation-25`, ID `12578948301`, execução
<https://github.com/Gabriel-Sousa-Oliveira/grand-chase-classic-ranking/actions/runs/40141558376>.
Retenção informada pelo GitHub: até 31/10/2026. Baixe antes de expirar.
O relatório original tinha um acerto e dois casos sem consenso.

Reproduzi offline os dois excerpts MP4 desse artefato, sem baixar novamente do
YouTube. O resultado de 1:20 aparecia como `01:'20`, rejeitado pelo parser. No
caso de 3:04, a leitura esparsa dos rótulos omitia o título Results; uma leitura
separada do título recuperou a palavra. Seus dígitos aparecem como `03:'04`.

## Alterações

- Parser contextual de resultados: normalizar apenas um token completo
  `MM:'SS` para a notação já aceita `MM'SS`. Não alterar o parser geral.
- Se existe rótulo de tempo, mas falta Results, tentar um recorte separado do
  título. A segunda leitura precisa corresponder exatamente a Results após
  remover espaços/pontuação. Os dois rótulos continuam obrigatórios.
- Corrigir a referência ausente ao mock `scan` em um teste visual existente.
- Cobrir separador duplicado, entradas incompletas/inválidas, recuperação do
  título, rejeição de outro título e números compactos amarelos.

## Verificação realizada

`cd backend && python -m unittest discover -s tests -q`: **120 testes passaram**.
Antes da correção, o novo teste de `01:'20` falhou, como esperado.

Replay dos excerpts completos de 25 segundos, a 4 FPS, com `_window_frames` e
`_scan_frames(..., 'results_panel', 25, 4, exhaustive=True)`:

| Vídeo | Antes, neste replay | Depois | Quadros concordantes |
| --- | --- | --- | --- |
| DDzlbGAOo2I | sem consenso | 80000 ms (1:20) | 6 |
| tCfudbb88dU | sem consenso | 184000 ms (3:04) | 4 |

O frame de controle `93GrHzU6FmY-frame-035-raw.png` continua retornando 363000 ms
(6:03). O frame `DDzlbGAOo2I-frame-002-raw.png`, sem resultado válido, continua
sem observações. Não alegamos nova validação integral do vídeo de controle.

## Repetir o replay

Instale FFmpeg, Tesseract com idioma eng, `opencv-python-headless==4.10.0.84`
e `numpy<2`. Extraia o artefato original. Na raiz do repositório, execute o código
abaixo com `PYTHONPATH=backend python`, ajustando apenas o caminho `root`.

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from gc_radar.ocr import _window_frames, _scan_frames

root = Path('/caminho/ocr-validation-evidence')
for video_id in ('DDzlbGAOo2I', 'tCfudbb88dU'):
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        frames = _window_frames(root / f'{video_id}-excerpt.mp4',
                                directory, 'replay', 0, 25, 4)
        result, count = _scan_frames(frames, directory, 'results_panel',
                                     25, 4, exhaustive=True)
        print(video_id, result, count)
```

## Limites e pontos para auditar

O replay testa extração de frames, rótulos, leitura dos dígitos, parsing e
consenso denso. Não testa um novo download do YouTube, a seleção automática das
janelas, a publicação nem toda a fila. Os recortes continuam específicos do
layout/idioma suportados. O retry acrescenta uma chamada Tesseract somente
quando o painel tem rótulo de tempo e falta o título. Avaliar falsos positivos
desse retry e seu custo na fila é parte importante da revisão.

Nenhum limite de consenso foi reduzido nesta alteração. Não houve alteração no
banco nem publicação de novos tempos. Esta branch deve ser revisada antes de
integrar e executar em escala.
