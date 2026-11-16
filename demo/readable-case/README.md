# Читаемый учебный кейс v4

**Локальное предложение v4, не согласованная бизнес-стратегия.** Источники учебные; модельные роли не реальные клиенты. Перевод и пояснения не изменяют Store, права, исторические approvals или awaiting_human. Исходные формулировки и точные refs сохранены отдельно.

Case `test-core`; committed revision 173; snapshot digest `36ca73f5f2f47fceaeefbbb3a365f9390bf8aa16752f7b81de6b7e404b2e3921`.

Порядок: options-comparison.md → STR из точных DEC refs → PRM → EXP → evidence.md. Новая активная STR не заменяет автоматически pinned STR решения.

Точные refs решения DEC-001@4:
```
{
  "basis_refs": [
    {
      "case_id": "test-core",
      "entity_id": "INA-001",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "CLM-001",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "SIM-001",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "SIM-002",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "SIM-003",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "CAL-001",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "CAL-002",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "CAL-003",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "CAL-004",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "RPL-002",
      "revision": 2
    },
    {
      "case_id": "test-core",
      "entity_id": "QST-004",
      "revision": 2
    },
    {
      "case_id": "test-core",
      "entity_id": "CLM-002",
      "revision": 2
    },
    {
      "case_id": "test-core",
      "entity_id": "UXO-001",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "UXJ-001",
      "revision": 2
    },
    {
      "case_id": "test-core",
      "entity_id": "SRC-011",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "SRC-012",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "SRC-013",
      "revision": 1
    }
  ],
  "contract_version": 3,
  "due": "unknown",
  "experiment_ref": {
    "case_id": "test-core",
    "entity_id": "EXP-001",
    "revision": 3
  },
  "metrics": [
    "Unknown real baseline; measure correct completion time and quality before comparing"
  ],
  "option_choice_ref": {
    "case_id": "test-core",
    "entity_id": "APR-002",
    "revision": 1
  },
  "owner": "unassigned",
  "promise_refs": [
    {
      "case_id": "test-core",
      "entity_id": "PRM-001",
      "revision": 3
    }
  ],
  "rejected_refs": [
    {
      "case_id": "test-core",
      "entity_id": "OPT-001",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "OPT-003",
      "revision": 1
    },
    {
      "case_id": "test-core",
      "entity_id": "OPT-004",
      "revision": 1
    }
  ],
  "selected_option_ref": {
    "case_id": "test-core",
    "entity_id": "OPT-002",
    "revision": 1
  },
  "status": "pending",
  "strategy_refs": [
    {
      "case_id": "test-core",
      "entity_id": "STR-001",
      "revision": 3
    },
    {
      "case_id": "test-core",
      "entity_id": "STR-002",
      "revision": 3
    }
  ],
  "triggers": [
    "Actual evidence contradicts the manual-review hypothesis",
    "Privacy permission/budget changes"
  ]
}
```

## Файлы

- [BRF-001-r1.md](BRF-001-r1.md)
- [CAL-001-r1.md](CAL-001-r1.md)
- [CAL-002-r1.md](CAL-002-r1.md)
- [CAL-003-r1.md](CAL-003-r1.md)
- [CAL-004-r1.md](CAL-004-r1.md)
- [CLM-001-r1.md](CLM-001-r1.md)
- [CLM-002-r2.md](CLM-002-r2.md)
- [CLM-002-r3.md](CLM-002-r3.md)
- [DEC-001-r4.md](DEC-001-r4.md)
- [EXP-001-r3.md](EXP-001-r3.md)
- [EXP-001-r4.md](EXP-001-r4.md)
- [INA-001-r1.md](INA-001-r1.md)
- [OBL-001-r1.md](OBL-001-r1.md)
- [OPT-001-r1.md](OPT-001-r1.md)
- [OPT-002-r1.md](OPT-002-r1.md)
- [OPT-003-r1.md](OPT-003-r1.md)
- [OPT-004-r1.md](OPT-004-r1.md)
- [PRM-001-r1.md](PRM-001-r1.md)
- [PRM-001-r3.md](PRM-001-r3.md)
- [QST-001-r1.md](QST-001-r1.md)
- [QST-002-r1.md](QST-002-r1.md)
- [QST-003-r1.md](QST-003-r1.md)
- [QST-004-r2.md](QST-004-r2.md)
- [RPL-001-r1.md](RPL-001-r1.md)
- [RPL-002-r2.md](RPL-002-r2.md)
- [STR-001-r3.md](STR-001-r3.md)
- [STR-001-r5.md](STR-001-r5.md)
- [STR-002-r3.md](STR-002-r3.md)
- [STR-002-r5.md](STR-002-r5.md)
- [capability-delta-proposed.md](capability-delta-proposed.md)
- [evidence.md](evidence.md)
- [known-unknowns.md](known-unknowns.md)
- [options-comparison.md](options-comparison.md)

Русский перевод отсутствует для: нет пропусков.
