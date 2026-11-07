# Datos sintéticos de Trazora FSM

Los scripts generan, validan y preparan una carga reproducible de datos sintéticos para los seis microservicios de Trazora FSM. La generación y la validación se ejecutan localmente; el cargador funciona en modo de inspección local salvo que se indique otra opción.

## Requisitos

- Python 3.13.2.
- `Faker==40.1.2` para generación y validación.
- `tzdata==2026.6` en sistemas sin base de zonas horarias IANA, incluido Windows.
- `boto3==1.43.123` para inspección o carga posterior en AWS.

Desde la raíz del repositorio, en PowerShell:

```powershell
python -m venv .venv-seed
.venv-seed\Scripts\Activate.ps1
python -m pip install Faker==40.1.2 tzdata==2026.6
```

Para las funciones AWS, instalar también `python -m pip install boto3==1.43.123`. Faker no proporciona `es_PE` en esta versión: se utilizan proveedores `es_CO` y `es_MX` con adaptación para datos sintéticos peruanos.

## Estructura del conjunto

Cada servicio contiene 37 000 entidades principales, repartidas entre CLIMALIMA (12 334), FRIOSUR (12 333) y TECNINORTE (12 333):

| Servicio | Archivo | Entidad principal |
| --- | --- | --- |
| MS0 Usuarios | `usuarios.jsonl` | USUARIO |
| MS1 Clientes | `clientes.jsonl` | CLIENTE |
| MS2 Técnicos | `tecnicos.jsonl` | TECNICO |
| MS3 Órdenes | `ordenes.jsonl` | ORDEN |
| MS4 Agenda | `agenda.jsonl` | VISITA |
| MS5 Partes | `partes.jsonl` | PARTE |

Los archivos `jornadas.jsonl`, `bloques.jsonl`, `controles.jsonl` y `marcadores.jsonl` contienen registros auxiliares y se contabilizan por separado. `manifest.json` recoge parámetros, conteos y hashes SHA256. Los registros usan claves DynamoDB `PK` y `SK` y mantienen relaciones por tenant.

Las visitas son PROGRAMADA, las órdenes ABIERTA y los partes BORRADOR/PENDIENTE. Solo los técnicos con visitas asignadas están activos; los demás son perfiles sintéticos inactivos. MS2 no dispone de una operación de reactivación, y MS2 y MS4 rechazan respectivamente nuevas jornadas y visitas para técnicos inactivos. La interpretación académica de los perfiles inactivos debe confirmarse con el equipo docente.

Cada tenant tiene un COORDINADOR sintético inactivo sin credenciales, referenciado como creador de órdenes y partes. Esta referencia no permite autenticación ni acredita que las operaciones se hayan realizado mediante las API. Los usuarios no incluyen contraseñas ni registros LOGIN.

Las zonas configuradas son Lima y Callao para CLIMALIMA; Arequipa, Tacna y Moquegua para FRIOSUR; y Trujillo, Chiclayo y Piura para TECNINORTE. La zona individual no se almacena en las entidades: no existe consulta geográfica ni cálculo de distancias. Las distribuciones son supuestos sintéticos, no estadísticas del mercado. Las jornadas usan `America/Lima`; no se modelan feriados, desplazamientos reales ni estacionalidad validada.

## Generación y validación

La fecha inicial debe ser un día laborable. Para conservar visitas futuras y fechas de creación no futuras, el siguiente ejemplo selecciona el próximo día laborable. La carpeta de salida no debe existir.

```powershell
$fechaSeed = (Get-Date).Date.AddDays(1)
while ($fechaSeed.DayOfWeek -in @([DayOfWeek]::Saturday, [DayOfWeek]::Sunday)) {
    $fechaSeed = $fechaSeed.AddDays(1)
}
$fechaSeedTexto = $fechaSeed.ToString('yyyy-MM-dd')
$salidaSeed = Join-Path $env:TEMP 'trazora-fsm-dataset'
python scripts/seed/generar_datos.py --out $salidaSeed --target 37000 --seed 20261104 --start-date $fechaSeedTexto
python scripts/seed/validar_datos.py --input $salidaSeed --target 37000
python scripts/seed/cargar_datos.py --input $salidaSeed --target 37000
```

La validación comprueba los hashes, conteos, claves, relaciones, aislamiento por tenant, estados, especialidades, jornadas, bloques y cronología. Para reproducir el conjunto, utilizar las mismas versiones de Python y dependencias, semilla, fecha y parámetros en una segunda carpeta y comparar los hashes de los diez JSONL y del manifiesto. El manifiesto no es una firma. Los datos deben permanecer fuera del repositorio; si se elige una ruta dentro de él, configure una exclusión local antes de generarlos.

La mezcla geográfica se puede ajustar por tenant con pesos enteros positivos, por ejemplo `--perfil-geografico CLIMALIMA:LIMA=80,CALLAO=20`. Solo se admiten zonas configuradas para ese tenant.

## Simulación de carga

La simulación usa SQLite local. La interrupción deliberada devuelve el código 2; la segunda ejecución reanuda y la última lee y verifica los elementos almacenados.

```powershell
$pilotoSeed = Join-Path $env:TEMP 'trazora-fsm-piloto'
$baseSeed = Join-Path $env:TEMP 'trazora-fsm-piloto.sqlite'
python scripts/seed/generar_datos.py --out $pilotoSeed --target 300 --seed 20261104 --start-date $fechaSeedTexto
python scripts/seed/validar_datos.py --input $pilotoSeed --target 300
python scripts/seed/cargar_datos.py --input $pilotoSeed --target 300 --simular $baseSeed --interrumpir-tras 7
python scripts/seed/cargar_datos.py --input $pilotoSeed --target 300 --simular $baseSeed
python scripts/seed/cargar_datos.py --input $pilotoSeed --target 300 --simular $baseSeed --verificar
```

El cargador distingue registros escritos, existentes idénticos y rechazados. Una clave existente con contenido distinto detiene la carga. La verificación recorre páginas y compara el contenido almacenado con el conjunto generado. SQLite no reproduce IAM, Streams, concurrencia distribuida ni la configuración real de DynamoDB.

## Inspección y carga en DynamoDB

La inspección remota requiere `--inspeccionar-aws`, `--stage`, `--region` y `--cuenta`. Consulta STS, describe las tablas y lee sus registros mediante consultas paginadas. Estas operaciones pueden generar costos.

La escritura requiere `--apply`, etapa `dev`, `--revision-permisos-colisiones-streams-cuotas-costos` y `--confirmar-carga ESCRIBIR`. Esas opciones expresan la confirmación del operador; no verifican por sí solas permisos efectivos, cuotas, costos, consumidores de Streams o respaldos. El cargador usa escrituras condicionales, limita por defecto los intentos a cinco por segundo y realiza una lectura posterior. Las escrituras no forman una transacción global y una interrupción puede dejar datos parcialmente cargados; no hay rollback automático.

Antes de una carga, el responsable de infraestructura debe confirmar cuenta, región, tablas y contratos desplegados; revisar permisos, datos existentes, posibles colisiones, cuotas, costos, Streams y recuperación; y ejecutar un piloto autorizado en un entorno aislado. Las claves deterministas pueden coincidir con las de otros conjuntos, incluso si su contenido es distinto. No mezclar conjuntos sin verificar esas colisiones. Una lectura paginada no es una instantánea global frente a escrituras concurrentes.

## Seguridad de los datos

Los correos del dataset usan dominios `.invalid` y los teléfonos peruanos están enmascarados; no son datos de contacto utilizables. Las identidades y empresas son sintéticas, aunque sus nombres podrían coincidir casualmente con nombres reales.

La opción explícita `--vista-visual` genera un archivo `vista_visual.json` independiente con direcciones de apariencia comercial que podrían coincidir con direcciones reales. No debe importarse ni usarse para enviar comunicaciones. El cargador solo procesa los JSONL validados y rechaza dominios comerciales en ellos. La vista no está incluida en los hashes del manifiesto.
