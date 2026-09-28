# AFYEEV Monitor

En Umbrel, abrí App Store → Community App Stores y agregá:

https://github.com/francocorreasosa/umbrel-tempsensing

Si ya tenés esta tienda, actualizá su catálogo y buscá **AFYEEV Monitor** en Franco's Apps.

Después de instalar, abrí la app y configurá la IP privada, el ID y la clave local de tu cargador Tuya 3.5. Umbrel debe poder acceder al cargador por la red local. Reservá su IP en el router para evitar cambios. Las credenciales se guardan en tu equipo; no las publiques en issues.

El monitor solo consulta el cargador y guarda su historial desde la instalación. Incluye potencia, temperatura, sesiones, consumo, exportación CSV y copia SQLite. Los datos persisten al reiniciar o actualizar la app.

La tarifa inicial es UTE Residencial Triple Horario 2026 con IVA: valle 00–07 a $2,98/kWh, punta hábil 17–21 a $14,68/kWh y llano a $6,31/kWh. Incluye feriados UTE de 2026; revisá horarios, precios y feriados en Configuración. El ciclo de facturación es del 7 al 6 y estima únicamente la energía del cargador, sin cargos fijos ni potencia contratada.

El repositorio de desarrollo es privado. Las imágenes Docker son públicas para permitir la instalación desde Umbrel sin credenciales de GitHub.
