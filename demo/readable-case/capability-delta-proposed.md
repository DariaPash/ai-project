# Предлагаемая дельта возможностей (не бизнес-approval)

**Локальное предложение v4, не согласованная бизнес-стратегия.** Источники учебные; модельные роли не реальные клиенты. Перевод и пояснения не изменяют Store, права, исторические approvals или awaiting_human. Исходные формулировки и точные refs сохранены отдельно.

Исторические CLM-002/EXP могут описывать отказ Apple Speech. Более поздний whisper receipt не меняет их bytes и не означает проверку качества/consent. MCP read/import не автоматический продуктовый экспорт. Нужны новые proposed revisions и реальный H на точный bundle; этот генератор их не создаёт.

Фактически выполнено локальное распознавание whisper.cpp; это не прежний отказ Apple Speech. Числа/отрицания остаются uncertain, listening не выполнен; диаризация, качество русского языка и права на реальные записи не подтверждены.

## Технический receipt EXT-017@1

```
{
  "extractor": "{\"engines\": [{\"engine\": \"whisper.cpp\", \"executable_sha256\": \"0158f0e587b82440865fa2df9b75cf64000a0dbddc53c65d4b3f552c59582ac7\", \"languages\": [\"eng\", \"rus\"], \"model_id\": \"ggerganov/whisper.cpp/ggml-base.bin\", \"model_revision\": \"5359861c739e955e79d9a303bcbc70fb988958b1\", \"model_sha256\": \"60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe\", \"network_during_recognition\": false, \"schema_version\": 1, \"version\": \"v1.9.5\"}], \"implementation\": \"step04-local-media-v1\", \"implementation_sha256\": \"d3dbb3472db378205f22e6fab63eb62c0f005dd760c31081b7e24912aa24dd72\", \"python\": \"3.14.8\"}",
  "source_hash": "a11139d34301d480107e1610ea3ba56dcc06499e663c955001fbf36476ced213",
  "source_ref": {
    "case_id": "test-core",
    "entity_id": "SRC-015",
    "revision": 1
  },
  "warnings": [
    "Actual local whisper.cpp transcription under network denial; no cloud or recognition-time downloads",
    "Numbers and negations remain uncertain without listening verification; no speaker identity or diarization",
    "Base model, greedy decoding; multilingual accuracy not established by a benchmark"
  ]
}
```

**SRC-015@1 → EXT-017@1**; SHA-256 исходных bytes `a11139d34301d480107e1610ea3ba56dcc06499e663c955001fbf36476ced213`; вид `audio`; координаты:
```
{
  "end_ms": 2400,
  "speaker": "unknown",
  "start_ms": 0
}
```

Точная цитата (без перевода):
```
This is a synthetic technical record.
```

**SRC-015@1 → EXT-017@1**; SHA-256 исходных bytes `a11139d34301d480107e1610ea3ba56dcc06499e663c955001fbf36476ced213`; вид `audio`; координаты:
```
{
  "end_ms": 5120,
  "speaker": "unknown",
  "start_ms": 3240
}
```

Точная цитата (без перевода):
```
Retention is 15%
```

**SRC-015@1 → EXT-017@1**; SHA-256 исходных bytes `a11139d34301d480107e1610ea3ba56dcc06499e663c955001fbf36476ced213`; вид `audio`; координаты:
```
{
  "end_ms": 7520,
  "speaker": "unknown",
  "start_ms": 5880
}
```

Точная цитата (без перевода):
```
Do not send the record.
```

## Технический receipt EXT-020@1

```
{
  "extractor": "{\"engine\": \"stdlib\", \"engine_version\": \"stdlib-3.14.8\", \"implementation\": \"step02-parser-v1\", \"implementation_sha256\": \"170747c96c281211df81c084a958c4317f091dc2d4c2d5951a299593d4ce8ceb\", \"python_version\": \"3.14.8\"}",
  "source_hash": "41c48188df9bc99f9999f8666cb319242ffc4aca0730691d87f1c2aabd61866e",
  "source_ref": {
    "case_id": "test-core",
    "entity_id": "SRC-017",
    "revision": 1
  },
  "warnings": []
}
```

**SRC-017@1 → EXT-020@1**; SHA-256 исходных bytes `41c48188df9bc99f9999f8666cb319242ffc4aca0730691d87f1c2aabd61866e`; вид `lines`; координаты:
```
{
  "char_end": 52,
  "char_start": 0,
  "end": 1,
  "start": 1
}
```

Точная цитата (без перевода):
```
Owned synthetic workflow note for the demonstration.
```

**SRC-017@1 → EXT-020@1**; SHA-256 исходных bytes `41c48188df9bc99f9999f8666cb319242ffc4aca0730691d87f1c2aabd61866e`; вид `lines`; координаты:
```
{
  "char_end": 100,
  "char_start": 53,
  "end": 2,
  "start": 2
}
```

Точная цитата (без перевода):
```
Keep source citations when drafting strategies.
```

**SRC-017@1 → EXT-020@1**; SHA-256 исходных bytes `41c48188df9bc99f9999f8666cb319242ffc4aca0730691d87f1c2aabd61866e`; вид `lines`; координаты:
```
{
  "char_end": 178,
  "char_start": 101,
  "end": 3,
  "start": 3
}
```

Точная цитата (без перевода):
```
Local speech transcription now exists, but listening verification is pending.
```

**SRC-017@1 → EXT-020@1**; SHA-256 исходных bytes `41c48188df9bc99f9999f8666cb319242ffc4aca0730691d87f1c2aabd61866e`; вид `lines`; координаты:
```
{
  "char_end": 252,
  "char_start": 179,
  "end": 4,
  "start": 4
}
```

Точная цитата (без перевода):
```
Read-only filesystem MCP is available on the dedicated project directory.
```

**SRC-017@1 → EXT-020@1**; SHA-256 исходных bytes `41c48188df9bc99f9999f8666cb319242ffc4aca0730691d87f1c2aabd61866e`; вид `lines`; координаты:
```
{
  "char_end": 330,
  "char_start": 253,
  "end": 5,
  "start": 5
}
```

Точная цитата (без перевода):
```
Automatic product export remains planned. Business approval is still pending.
```

