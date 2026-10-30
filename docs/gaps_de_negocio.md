# Gaps de negocio y límites del ejercicio

## 1. Los gaps que el agente intenta cerrar

Un *gap* es la distancia entre cómo funciona hoy el proceso y cómo debería funcionar.

| # | Gap hoy | Consecuencia | Qué aporta el agente |
|---|---|---|---|
| 1 | La liquidación se lee, pero no se entiende (qué es el tope, por qué cambia el impuesto, por qué no hay bono) | Reclamos, desconfianza, consultas repetidas | Explica cada línea en lenguaje simple y con su fuente |
| 2 | Las respuestas están dispersas: contrato, anexos, reglamento, política de bonos, normativa | Cada consulta requiere que una persona de RR.HH. busque y cruce documentos | Recupera la cláusula exacta del documento correcto |
| 3 | Los errores se descubren tarde: el trabajador reclama, si es que reclama, dentro de una ventana corta (5 días hábiles) | Diferencias que se arrastran y se corrigen en el mes siguiente | Verifica cada línea el mismo día de la entrega |
| 4 | RR.HH. dedica tiempo a preguntas repetitivas de bajo valor | Menos tiempo para casos complejos | Resuelve lo repetitivo y deriva lo que requiere criterio humano |
| 5 | La información de remuneraciones es sensible y no puede cruzarse entre personas | Riesgo de filtración si se automatiza mal | Control de acceso por sesión en las tools y en el retriever |

*Para presentar a una clínica real:* cuantifica cada gap con sus datos (consultas por mes, tiempo medio de respuesta, reclamos acogidos). Aquí no se inventan cifras.

## 2. Por qué RAG es la solución aquí (y dónde no lo es)

**RAG encaja** cuando la respuesta depende de texto largo, específico por persona y cambiante: cláusulas de contrato, anexos de bonos, políticas internas. No cabe en un prompt fijo, no se puede calcular y el modelo no lo sabe. Recuperar la cláusula exacta (y citarla) es más barato y más verificable que ajustar un modelo.

**RAG no encaja** para los números: un descuento de AFP se calcula, no se recupera. Por eso hay tools deterministas. Y los valores volátiles (UF, topes, comisiones) viven en una tool con fuente y fecha, no en el vector store.

| Necesidad | Técnica |
|---|---|
| Qué dice mi contrato / mi anexo / la política | RAG |
| Cuánto debería descontarse | Tool de cálculo |
| Cuánto vale el tope hoy | Tool de parámetros |
| Cómo entregar datos solo de esta persona | Filtro de metadata + tools por sesión |
| Que el resultado sea usable por una app | Salida estructurada validada |

## 3. Qué NO cubre este ejercicio (simplificaciones deliberadas)

Para que quepa en una clase, el caso deja fuera lo siguiente. Un sistema real tendría que resolverlo:

- **Isapre y planes en UF:** solo se modela Fonasa (7%).
- **Horas extra, semana corrida, turnos y recargos.**
- **Anticipos, préstamos, cuotas sindicales, APV, cargas familiares.**
- **Licencias médicas y subsidios; vacaciones; finiquitos.**
- **Contratos de honorarios** (boleta y retención).
- **Gratificación Art. 47** (solo Art. 50).
- **Reajustes por IPC o por convenio.**
- **Criterio exacto de la UF** para convertir topes a pesos: se usa la UF del último día del mes de la remuneración (simplificación; confirmar con la Superintendencia de Pensiones).
- **Comisiones de AFP** verificadas para abril de 2026; deben validarse para el mes de cada liquidación.
- **IMM:** una fuente secundaria lo fecha el 1 de enero y otra el 1 de mayo de 2026; se usó la de KPMG (1 de mayo). Verificar.
- **Validez legal:** el agente no certifica nada; solo explica y marca diferencias.
- **Autenticación real y auditoría:** aquí la sesión se simula con un selector.
- **Memoria de conversación:** cada pregunta es independiente.

## 4. Riesgos de un despliegue real

| Riesgo | Mitigación sugerida |
|---|---|
| Alucinación de cifras o cláusulas | Tools para cálculo, citas obligatorias, grounding check, evaluación con casos conocidos |
| Fuga de datos entre trabajadores | Sesión autenticada, filtros en retriever y tools, tests de privacidad |
| Parámetros desactualizados | Versionar con fuente y fecha, alerta de vencimiento |
| Dependencia de un modelo pequeño local | Evaluar con casos reales y comparar con un proveedor externo |
| Datos personales en el LLM | Modelo local u on-premise, minimización de datos, acuerdos de tratamiento |
| El usuario confía ciegamente | Mensajes de alcance, derivación a RR.HH., registro de las consultas |
