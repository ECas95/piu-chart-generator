# Investigación y desarrollo del generador

Historia técnica del algoritmo (v362 → v5/variante F). Cada versión nació de un fallo concreto observado al jugar.

## Problema
Dado un chart fuente (SM/SSC, BMS de 5 teclas o NX de PRIME) producir 4 niveles de Single y 4 de Double **sin añadir ni mover notas**: los niveles bajos son subconjuntos del ritmo original; solo se decide qué panel pisa cada nota.

## v362 → v363: giros imposibles
- **Causa:** el plan de pies permitía el mismo pie varias veces seguidas justo después de soltar un hold del otro pie, y en Double la guardia anti-giro estaba apagada. El jugador alterna pies por naturaleza, así que su lectura "natural" divergía y quedaba de espaldas.
- **Corrección:** paridad estricta (el mismo pie dos veces solo en jack sobre el mismo panel o mientras el otro pie sostiene un hold).
- `playability.py`: Viterbi independiente del pie natural. Puerta de aceptación: sin postura >90°, sin pasos dobles <200 ms, máx. 45° en bandas 1-3; reintenta semillas y, si falla, excluye las notas conflictivas (registradas).
- **Nivel:** estimación de un modelo de dificultad nativo congelado (`lib/engine/difficulty_model.py` + `data/official_chart_metrics.json`, 21 vecinos oficiales, validado ±1 contra charts reales); la densidad se reajusta hasta que la estimación cae en la banda.
- `rhythm_extension`: error de tolerancia de rejilla (deriva float32, 1e-4) corregido; rejilla local por nota previa y hueco mínimo de 80 ms (fuentes de DDR llegan a 18-20).

## v2-v3: estudio de charts oficiales
Se analizaron 1.566 charts Single oficiales (Fiesta 2, Prime, Prime 2, XX). Hechos medidos: nunca terminan de espaldas; giros 0 % en niveles 1-5, ~3 % en 6-12 y 11-14 % en 13+; cruces de un paso ~80-88 %; giros en secciones calientes y corcheas, casi nunca en la primera nota de un run; saltos 6-10 %; holds ~18 % en 13+. Scripts en `docs/research/` (`audit_official.py`, `make_profiles.py`) y propuestas de reglas en `REGLAS_CHARTING_PROPUESTAS.md`. Resultado: `TurnBudget` en `musical.py` con objetivos de giros por nivel.

## v3.1: el pie equivocado
Un chart nivel 18 dejaba al jugador de espaldas aunque las estadísticas parecían normales. **Causa:** el compositor seguía los *paneles* de un patrón validado con el *pie* equivocado. **Corrección:** cada patrón guarda su pie por nota (`feet`, `start_foot`, `end_foot`); "seguir" = panel y pie; verificación posterior en `compose()`: toda postura cruzada exige 3 notas antes y 2 después seguidas exactamente o se bloquea y se recompone.

## v4: variantes
`PIU_VARIANT`: **A** segura (cruces solo dentro de patrones), **B** oficial (cruces cuyo contexto de 6 notas aparece ≥5 veces en charts oficiales), **C** fluida (sin cruces, solo giros).

## v5: generador de ArrowVortex
Port de `StreamGenerator.cpp` (paseo aleatorio de pies alternos, dificultad = largo de paso) a `hybrid/vortex.py`, aplicado en vivo desde los pies reales (precalculado se desfasaba: ~45 % seguido frente a 80-97 %). Peso lateral por nivel porque la regla x sola da ~27 % de posturas laterales en pump. Variantes **D** (patrones + vortex) y **E** (vortex solo). **Variante F = E + giros T1-T5** (~1 por 40/24/18 notas según banda, ninguno con huecos <80 ms, nivel ≥6): 0 giros de espaldas, giros 3,1/5,0/5,9 % frente a 1,9/5,8/8,0 % oficial. Es la variante por defecto.

## Double
PumpDoublify del Single generado + puerta de jugabilidad; si falla, se compone el mismo ritmo en 10 paneles.

## Aprendizajes
- Las estadísticas agregadas no ven una postura de espaldas: juzgar siempre con `playability.gate` + `MODEL.estimate`.
- Borrar los directorios de ejecución fallidos antes de repetir (los generadores devuelven un `song.json` existente).
- Los charts generados no tienen revisión humana completa; la jugabilidad no está certificada.
