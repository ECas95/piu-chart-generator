# Generación experimental EZ2Dancer / RIO

Estas reglas sirven para generar únicamente los slots previamente autogenerados. Los charts originales no deben participar como destinos de escritura. Los niveles, nombres, modos y ordinales instalados deben conservarse, con hashes de los originales antes/después.

## Musicalidad y progresión

- Construir una rejilla de referencias con los ataques y duraciones de los charts originales de cada canción. No usar los AUTO anteriores como fuente rítmica. Para Single preferir originales Single; para Double, originales Double. Si falta un modo, transferir el ritmo y reconstruir la geometría. Excluir co-op/routine.
- Usar las marcas de tiempo exactas y las cabeceras de split del NX existente. No redondear milisegundos ni adelantar una nota por hacer snap hacia atrás. Una nota creada debe ocupar una fila de la rejilla original y tener un ataque de referencia; un hold debe retener ataque y final de una referencia.
- Elegir ataques por frases de 8 o 16 beats, con prioridad a los acentos recurrentes de los originales y a los comienzos de frase. La carga debe subir y bajar con la fuente, y sus descansos deben mantenerse. Evitar eliminar notas por proximidad de forma global: rompe motivos, contratiempos y resoluciones.
- Calibrar filas/segundo, notas/segundo, ráfagas de 1/4/8 segundos, saltos y holds con charts oficiales del mismo modo/nivel. Las métricas son controles, no una fórmula suficiente para estimar dificultad. Comparar también con el original más cercano de la canción.
- Cuando haya varios AUTO del mismo modo, sus cargas sostenidas deben crecer con el nivel; las versiones fáciles deberían conservar un subconjunto coherente de los ataques de las difíciles. No subir un nivel sólo para obtener números distintos.

## Geometría y pies

- Mantener un estado de ambos pies y los paneles retenidos; buscar con beam search la secuencia completa por frase. Costes: viaje de cada pie, cambios bruscos de postura, repetición rápida del mismo pie, cruces, pérdida de alternancia y giros consecutivos. Reiniciar suavemente después de descansos.
- Resolver saltos como contactos simultáneos de ambos pies; no adjudicar un salto entero a un pie. Evitar triples y brackets en esta primera versión experimental: sólo habilitarlos si se implementa y valida un modelo explícito de contactos posibles.
- Un hold bloquea el pie que lo sostiene hasta su final. No escribir un tap/head encima de BODY/TAIL ni permitir que el mismo pie pise un panel remoto mientras sigue retenido. Rechazar la colisión y buscar otra geometría; nunca solucionarla sobrescribiendo celdas.
- En fáciles, penalizar fuertemente jacks rápidos, cruces y giros. En intermedios, permitir motivos de cruces cortos respaldados por el corpus. En difíciles, no introducir estos recursos sólo para inflar la dificultad: deben seguir el ritmo y disponer de preparación y recuperación.
- En Double modelar los dos pads como una superficie continua, incluyendo los cuatro paneles interiores. Las transiciones entre pads necesitan viajes posibles por pie, no sólo alternancia izquierda/derecha. No generar saltos entre las esquinas exteriores de los dos pads ni desplazamientos grandes durante un hold. Construir las travesías con motivos oficiales compatibles.

## Motivos y variedad

- Los motivos de referencia guardan modo, banda de nivel, intervalos entre beats, lanes y contexto de holds. Una secuencia de 4 taps limpia no garantiza por sí sola que el enlace con la anterior sea cómodo: revalidar entrada y salida con el estado de pies.
- Preferir motivos frecuentes del corpus y transformaciones permitidas: espejo Single (0↔4, 1↔3, 2 fijo), espejo Double (0↔9, 1↔8, 2↔7, 3↔6, 4↔5). No trasladar índices arbitrariamente en Double, porque cambia la distancia física.
- Reusar el motivo en frases musicales repetidas aporta identidad, pero evitar la misma secuencia de 4 paneles repetida indefinidamente. Cambiar motivo o espejo en las variaciones de la fuente; usar semillas estables distintas por canción/slot/versión.

## Validación posterior a la escritura

1. NX20 estructuralmente válido, modo/columnas y nivel del slot conservados.
2. Cabeceras de timing idénticas a la referencia, ataques sobre las mismas filas, ninguna nota fuera de la duración, ninguna nota perdida por una colisión.
3. Holds completos HEAD→BODY→TAIL, sin cuerpo huérfano, sin solapamientos por lane, sin ataques insertados dentro del mismo hold.
4. Máximo de dos contactos simultáneos, contando los holds activos. Modelo de pies viable durante toda la frase.
5. Cargas, jacks, saltos, distribución de paneles y viajes Double dentro de los límites elegidos por nivel, medidos de nuevo sobre los bytes NX escritos.
6. Ningún original modificado. Snapshot del catálogo, archivos AUTO antiguos y manifiesto con SHA-256 para rollback exacto.

El corpus local y los controles automáticos permiten obtener una versión más consistente; la calidad musical y las sensaciones de giro necesitan el feedback de juego solicitado por el usuario.

## Problemas encontrados en `fill_modes.py`

El generador anterior depende de `C:\EZ2AC\PIU\universal_piu_converter_v0_4`, que no existe actualmente. Selecciona el chart con más notas sin distinguir modo ni co-op; una densidad global de 1.0/0.72/0.50 decide la escalera. Valida antes de adelgazar el chart, luego modifica saltos y elimina ataques sin repetir esa validación. El booleano `ok` guardado ya no describe el resultado final. `write_on_grid` hace snap hacia atrás y puede sobrescribir celdas al cruzar un hold. El canónico declara sólo el BPM inicial. La puntuación EZ2 usa un coeficiente negativo para saltos y ráfagas, por lo que esas cargas pueden bajar artificialmente el nivel. Los modelos actuales ignoran cruces, pies, viajes Double, duración de holds y ritmo por frase.
