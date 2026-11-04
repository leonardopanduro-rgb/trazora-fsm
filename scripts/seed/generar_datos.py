from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import unicodedata
import uuid

from faker import Faker


TENANTS = ('CLIMALIMA', 'FRIOSUR', 'TECNINORTE')
SERVICES = ('usuarios', 'clientes', 'tecnicos', 'ordenes', 'agenda', 'partes')
AUX = ('jornadas', 'bloques', 'controles', 'marcadores')
NAMESPACE = uuid.UUID('3b933e54-dc3a-4412-b35e-89745dd57a78')
SPECIALTIES = ('INSTALACION', 'MANTENIMIENTO', 'REPARACION')
REASONS = {
    'INSTALACION': ('Montaje y puesta en marcha de equipo split', 'Instalación de unidad de climatización', 'Reemplazo programado de equipo inverter'),
    'MANTENIMIENTO': ('Inspección preventiva de serpentines y drenaje', 'Servicio preventivo de filtros y unidad exterior', 'Revisión de caudal y consumo eléctrico'),
    'REPARACION': ('Diagnóstico de pérdida de rendimiento térmico', 'Revisión de fuga de agua de unidad interior', 'Diagnóstico de apagado intermitente del equipo'),
}

DETAILS = {
    'INSTALACION': ('instalación nueva en ambiente ocupado', 'sustitución de unidad existente', 'puesta en marcha con prueba eléctrica', 'montaje con revisión de drenaje', 'instalación con verificación de soporte'),
    'MANTENIMIENTO': ('control de presión y temperatura', 'revisión de drenaje y filtros', 'verificación de vibración y fijaciones', 'limpieza de serpentines y revisión eléctrica', 'inspección de ventilación y conexiones'),
    'REPARACION': ('el usuario reporta ruido intermitente', 'el usuario reporta enfriamiento insuficiente', 'el usuario reporta condensación anormal', 'el usuario reporta ciclos de apagado', 'el usuario reporta flujo de aire reducido'),
}


SURNAMES = (
    'Quispe','Flores','García','Rodríguez','Huamán','Mamani','Rojas','Torres','Vásquez','Ramos',
    'Chávez','Mendoza','Castillo','Sánchez','Medina','Pérez','Gutiérrez','Cruz','Guerrero','Díaz',
    'Alvarado','Salazar','Vargas','Cárdenas','Espinoza','Delgado','Paredes','Campos','Vega','León',
    'Valdivia','Zapata','Fernández','Palomino','Silva','Aguilar','Romero','Condori','Puma','Huanca',
    'Mejía','Cabrera','Aguirre','Carrasco','Soto','Vilca','Valencia','Núñez','Ponce','Herrera',
    'Solis','Córdova','Tapia','Alarcón','Valverde','López','Arce','Cueva','Cáceres','Benavides',
    'Villegas','Luna','Salinas','Miranda','Araujo','Barrientos','Montoya','Calle','Ibáñez','Contreras',
    'Calderón','Ortiz','Yupanqui','Zegarra','Vera','Castro','Rivera','Luján','Meza','Bautista',
    'Cortez','Román','Guillén','Montalvo','De la Cruz','Pacheco','Castañeda','Reátegui','Arias','Muñoz',
)
NAME_PAIRS = (
    ('María','José'), ('María','Elena'), ('María','Carmen'), ('María','Isabel'),
    ('Ana','María'), ('Ana','Lucía'), ('Luz','María'), ('Rosa','María'),
    ('José','Luis'), ('José','Carlos'), ('José','Antonio'), ('José','María'),
    ('Juan','Carlos'), ('Juan','José'), ('Juan','Manuel'), ('Luis','Alberto'),
    ('Luis','Enrique'), ('Víctor','Manuel'), ('César','Augusto'), ('Jorge','Luis'),
    ('Miguel','Ángel'), ('Carlos','Alberto'), ('Marco','Antonio'), ('Julio','César'),
)
NICKNAMES = {'jose':'pepe','maria':'mary','josefina':'fina','francisco':'paco','carlos':'carlitos','carmen':'carmencita','alejandra':'ale','fernando':'fer','patricia':'pati','mariajose':'majo'}
MAIL_DOMAINS = ('gmail.invalid', 'hotmail.invalid', 'outlook.invalid', 'yahoo.invalid', 'icloud.invalid')
COMPANY_SECTORS = ('Clínica', 'Hotel', 'Restaurante', 'Taller', 'Distribuidora', 'Estudio', 'Centro Médico', 'Consultora', 'Comercial', 'Servicios', 'Instituto', 'Oficinas')



GEO_WEIGHTS = {
    'CLIMALIMA': {'LIMA': 85, 'CALLAO': 15},
    'FRIOSUR': {'AREQUIPA': 60, 'TACNA': 25, 'MOQUEGUA': 15},
    'TECNINORTE': {'TRUJILLO': 45, 'CHICLAYO': 30, 'PIURA': 25},
}
PERU_SURNAMES = ('Quispe','Huamán','Mamani','Condori','Yupanqui','Vilca','Palomino')
REGIONAL_SURNAMES = {zone: PERU_SURNAMES for weights in GEO_WEIGHTS.values() for zone in weights}
PHONE_FORMATS = {zone: '+51 9XX XXX {tail:03d}' for zone in REGIONAL_SURNAMES}
LEGAL_FORMS = {zone: ('S.A.C.','S.R.L.','E.I.R.L.') for zone in REGIONAL_SURNAMES}

def choose_country(seed: int, tenant_index: int, kind: str, index: int, weights: dict[str, int]) -> str:
    offset = {'usuario': 11, 'cliente': 23, 'tecnico': 37}[kind]
    r = random.Random(seed * 101 + tenant_index * 10000019 + index * 53 + offset)
    return r.choices(list(weights), weights=list(weights.values()))[0]


def parse_geography(values: list[str]) -> dict[str, dict[str, int]]:
    result = {tenant: dict(weights) for tenant, weights in GEO_WEIGHTS.items()}
    seen = set()
    for value in values:
        tenant, separator, entries = value.partition(':')
        if not separator or tenant not in TENANTS or tenant in seen:
            raise ValueError('Perfil geográfico inválido o duplicado')
        seen.add(tenant)
        weights = {}
        for entry in entries.split(','):
            country, equals, raw = entry.partition('=')
            if not equals or country not in GEO_WEIGHTS[tenant] or country in weights or not raw.isdigit() or int(raw) < 1:
                raise ValueError('Peso geográfico inválido')
            weights[country] = int(raw)
        result[tenant] = weights
    return result


def ascii_token(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value.lower())
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in normalized if not unicodedata.combining(c)))


def person(rng: random.Random, country: str, fake: Faker) -> tuple[str, str, str, str]:
    first = fake.first_name().strip()
    second = ''
    if rng.random() < 0.15:
        first, second = rng.choice(NAME_PAIRS)
    last = rng.choice(SURNAMES) if rng.random() < 0.35 else fake.last_name().strip()
    other = rng.choice(SURNAMES) if rng.random() < 0.35 else fake.last_name().strip()
    while other == last:
        other = fake.last_name().strip()
    name = ' '.join(part for part in (first, second, last, other) if part)
    email_first = first + second if second and rng.random() < 0.40 else first
    return name, ascii_token(email_first), ascii_token(last), ascii_token(other)


def company(rng: random.Random, country: str, fake: Faker) -> tuple[str, str]:
    for _ in range(100):
        value = fake.company()
        words = re.findall(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+', value)
        words = [word for word in words if len(word) > 2 and word.lower() not in ('proyectos', 'asociados', 'compañía', 'grupo', 'hijos', 'despacho', 'club', 'laboratorios', 'industrias', 'corporacin', 'del', 'gollum', 'garica')]
        if len(words) >= 2:
            brand = ' '.join(words[:1] if rng.random() < 0.30 else words[:2])
            name = f"{rng.choice(COMPANY_SECTORS)} {brand} {rng.choice(LEGAL_FORMS[country])}"
            return name, ascii_token(brand)
    raise ValueError('No se pudo generar una marca empresarial')


def unique_email(rng: random.Random, used: set[str], first: str = '', last: str = '', other: str = '', business: str = '', sector: str = '') -> str:
    for attempt in range(10000):
        if business:
            stem = f'{sector}{business}' if attempt >= 8 else business
            domain = f'{stem}.invalid'
            local = rng.choice(('contacto', 'ventas', 'administracion', 'operaciones', 'oficina', 'comercial', 'informes', 'servicios'))
            if attempt >= 32:
                local += str(rng.randint(10, 99))
        else:
            domain = rng.choices(MAIL_DOMAINS, weights=(48, 22, 18, 7, 5))[0]
            nick = NICKNAMES.get(first, first)
            local = rng.choice((f'{first}.{last}', f'{first}{last}', f'{first[0]}.{last}', f'{first}_{last}', f'{first}.{other}', f'{nick}.{last}'))
            if rng.random() < 0.20 or attempt >= 12:
                local += f'{rng.randint(65, 99) if rng.random() < 0.55 else rng.randint(0, 24):02d}'
        address = f'{local}@{domain}'
        if len(local) <= 64 and len(domain) <= 253 and len(address) <= 254 and address not in used:
            used.add(address)
            return address
    raise ValueError('No se pudo generar un correo único')


def specialties(seed: int, tenant_index: int, index: int) -> list[str]:
    picker = random.Random(seed * 11 + tenant_index * 100003 + index)
    count = picker.choices((1,2,3), (50,40,10))[0]
    return picker.sample(SPECIALTIES,count)


def identifier(kind: str, tenant: str, index: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f'{kind}/{tenant}/{index}'))


def quota(target: int) -> dict[str, int]:
    return {t: target // 3 + (i < target % 3) for i, t in enumerate(TENANTS)}


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def base(tenant: str, entity: str, suffix: str, **fields: object) -> dict:
    return {'PK': f'TENANT#{tenant}', 'SK': f'{entity}#{suffix}', 'entity_type': entity, **fields}


def generate(out: Path, target: int, seed: int, start_date: str, geography: dict[str, dict[str, int]] | None = None) -> dict:
    if not 3 <= target <= 100000:
        raise ValueError('El objetivo debe estar entre 3 y 100000')
    day = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    if day.weekday() >= 5:
        raise ValueError('La fecha inicial debe ser un día laborable')
    weekdays = [day + timedelta(days=i) for i in range(84) if (day + timedelta(days=i)).weekday() < 5]
    if ((target + 2) // 3) > len(weekdays) * 400 * 3:
        raise ValueError('El objetivo excede la capacidad de la ventana de agenda')
    out.mkdir(parents=True, exist_ok=False)
    handles = {s: (out / f'{s}.jsonl').open('w', encoding='utf-8', newline='\n') for s in (*SERVICES, *AUX)}
    counts: dict[str, Counter] = {s: Counter() for s in handles}
    def write(service: str, tenant: str, item: dict) -> None:
        handles[service].write(json.dumps(item, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n')
        counts[service][tenant] += 1
    used_emails: set[str] = set()
    used_company_names: set[str] = set()
    used_company_domains: set[str] = set()
    geography = geography if geography is not None else parse_geography([])
    geo_counts: dict[str, dict[str, Counter]] = {tenant: {kind: Counter() for kind in ('usuarios','clientes','tecnicos','ordenes')} for tenant in TENANTS}
    try:
        for ti, (tenant, n) in enumerate(quota(target).items()):
            rng = random.Random(seed + 3011 * ti)
            fake_person = Faker('es_CO')
            fake_company = Faker('es_MX')
            fake_person.seed_instance(seed + 50021 * ti)
            fake_company.seed_instance(seed + 60013 * ti)
            pool_size = min(400, n)
            planner = random.Random(seed + 7127 * (ti + 1))
            pool = planner.sample(range(n), pool_size)
            core = set(pool[:max(1, pool_size // 4)])
            slots = [(work_day, tech_index, minute) for work_day in weekdays for tech_index in pool for minute in (780, 930, 1140)]
            slots.sort(key=lambda slot: planner.random() ** (1 / (6 if slot[1] in core else 1)), reverse=True)
            slots = sorted(slots[:n])
            assigned_technicians = {slot[1] for slot in slots}
            workdays_written: set[tuple[str, str]] = set()
            client_pool = max(1, (n * 7) // 10)
            creator = identifier('usuario', tenant, 0)
            geo_weights = geography[tenant]
            client_countries = [choose_country(seed, ti, 'cliente', j, geo_weights) for j in range(n)]
            client_business = [random.Random(seed * 47 + ti * 10000019 + j * 79).random() < 0.58 for j in range(n)]
            client_groups: dict[str, list[int]] = {}
            for index, country in enumerate(client_countries[:client_pool]):
                client_groups.setdefault(country, []).append(index)
            main_country = max(client_groups, key=lambda country: len(client_groups[country]))
            tech_countries = [choose_country(seed, ti, 'tecnico', j, geo_weights) for j in range(n)]
            for index in pool:
                if tech_countries[index] not in client_groups:
                    tech_countries[index] = main_country
            recurring_groups = {zone: [index for index in group if client_business[index]][:max(1, len(group) // 5)] for zone, group in client_groups.items()}
            recurring_sets = {zone: set(group) for zone, group in recurring_groups.items()}
            other_groups = {zone: [index for index in group if index not in recurring_sets[zone]] for zone, group in client_groups.items()}
            customer_rng = random.Random(seed + 9811 * (ti + 1))
            priority_rng = random.Random(seed + 10357 * (ti + 1))
            for i in range(n):
                ids = {kind: identifier(kind, tenant, i) for kind in ('usuario', 'cliente', 'tecnico', 'orden', 'visita', 'parte')}
                created = day - timedelta(days=7 + rng.randint(0, 20), minutes=rng.randint(0, 1439))
                visit_day, tech_index, minute = slots[i]
                visit = visit_day + timedelta(minutes=minute)
                local_date = (visit - timedelta(hours=5)).date().isoformat()
                kind = rng.choice(specialties(seed, ti, tech_index))
                weights = {'INSTALACION': (10, 35, 55), 'MANTENIMIENTO': (45, 40, 15), 'REPARACION': (25, 45, 30)}
                choices = (60, 90) if minute == 930 else (60, 90, 120)
                duration = rng.choices(choices, weights[kind][:len(choices)])[0]
                end = visit + timedelta(minutes=duration)
                assigned_tech = identifier('tecnico', tenant, tech_index)
                country = tech_countries[tech_index]
                options = recurring_groups[country] if customer_rng.random() < 0.50 else other_groups[country]
                assigned_index = customer_rng.choice(options or client_groups[country])
                assigned_client = identifier('cliente', tenant, assigned_index)
                baseline = stamp(day - timedelta(days=372))
                user_country = choose_country(seed, ti, 'usuario', i, geo_weights)
                tech_country = tech_countries[i]
                client_country = client_countries[i]
                user_name, user_first, user_last, user_other = person(rng, user_country, fake_person)
                tech_name, _, _, _ = person(rng, tech_country, fake_person)
                is_business = client_business[i]
                client_name, first, last, other = person(rng, client_country, fake_person)
                brand = ''
                if is_business:
                    for _ in range(10000):
                        client_name, brand = company(rng, client_country, fake_company)
                        if brand in used_company_domains:
                            brand = ascii_token(client_name.split()[0]) + brand
                        if client_name not in used_company_names and brand not in used_company_domains:
                            used_company_names.add(client_name)
                            used_company_domains.add(brand)
                            break
                    else:
                        raise ValueError('No se pudo generar una empresa única')
                user_email = unique_email(rng, used_emails, user_first, user_last, user_other)
                client_email = unique_email(rng, used_emails, first, last, other, business=brand, sector=ascii_token(client_name.split()[0]) if is_business else '')
                user = base(tenant, 'USUARIO', ids['usuario'], tenant_id=tenant, usuario_id=ids['usuario'], nombre=user_name, email_normalizado=user_email, rol='COORDINADOR' if i == 0 else 'TECNICO', estado='INACTIVO', credential_version=0, creado_en=baseline)
                client = base(tenant, 'CLIENTE', ids['cliente'], tenant_id=tenant, cliente_id=ids['cliente'], nombre=client_name[:160], correo=client_email, telefono=PHONE_FORMATS[client_country].format(tail=rng.randint(0,999)), activo=True, creado_en=baseline)
                tech = base(tenant, 'TECNICO', ids['tecnico'], tenant_id=tenant, tecnico_id=ids['tecnico'], nombre=tech_name[:120], especialidades=specialties(seed, ti, i), activo=i in assigned_technicians, creado_en=baseline)
                reason = rng.choice(REASONS[kind])
                if kind == 'REPARACION':
                    detail = {
                        REASONS['REPARACION'][0]: 'el usuario reporta enfriamiento insuficiente',
                        REASONS['REPARACION'][1]: 'el usuario reporta agua cerca de la unidad',
                        REASONS['REPARACION'][2]: 'el usuario reporta ciclos de apagado',
                    }[reason]
                else:
                    detail = rng.choice(DETAILS[kind])
                age = 'antigüedad por confirmar' if kind == 'INSTALACION' else f"equipo con {rng.randint(1,15)} años de antigüedad aproximada"
                site = rng.choice(('oficina', 'comercio', 'almacén', 'clínica')) if client_business[assigned_index] else 'vivienda'
                description = f"{reason}; unidad {rng.choice(('split','inverter','ducto','cassette'))}, capacidad {rng.choice((9000,12000,18000,24000,36000))} BTU/h; {site}; {detail}; {age}"
                priority_weights = {'INSTALACION': (15,75,10), 'MANTENIMIENTO': (35,60,5), 'REPARACION': (8,57,35)}[kind]
                if (visit_day - day).days >= 7:
                    priority_weights = (priority_weights[0], priority_weights[1], 0)
                priority = priority_rng.choices(('BAJA', 'MEDIA', 'ALTA'), priority_weights)[0]
                if priority == 'ALTA':
                    created = day - timedelta(days=7, minutes=priority_rng.randint(0, 1439))
                order = base(tenant, 'ORDEN', ids['orden'], tenant_id=tenant, orden_id=ids['orden'], cliente_id=assigned_client, tipo_servicio=kind, descripcion=description, prioridad=priority, estado='ABIERTA', creada_por=creator, creada_en=stamp(created + timedelta(hours=1)))
                jornada = base(tenant, 'JORNADA', assigned_tech+'#'+local_date, tenant_id=tenant, tecnico_id=assigned_tech, fecha=local_date, zona_horaria='America/Lima', intervalos=[{'inicio':'08:00','fin':'12:00'},{'inicio':'13:00','fin':'17:00'}], actualizado_en=baseline)
                visita = base(tenant, 'VISITA', ids['visita'], tenant_id=tenant, visita_id=ids['visita'], orden_id=ids['orden'], tecnico_id=assigned_tech, inicio=stamp(visit), fin=stamp(end), estado='PROGRAMADA', creada_en=stamp(created + timedelta(hours=3)))
                control = base(tenant, 'CONTROL_ORDEN', ids['orden'], orden_id=ids['orden'], acepta_programaciones=True, visitas_activas=1)
                parte = base(tenant, 'PARTE', ids['parte'], tenant_id=tenant, parte_id=ids['parte'], visita_id=ids['visita'], orden_id=ids['orden'], estado='BORRADOR', diagnostico='', tareas=[], resultado='PENDIENTE', creado_por=creator, creado_en=stamp(created + timedelta(hours=4)), actualizado_en=stamp(created + timedelta(hours=4)), version=1)
                marker = base(tenant, 'VISITA_PARTE', ids['visita'], tenant_id=tenant, visita_id=ids['visita'], parte_id=ids['parte'])
                for label, selected in (('usuarios', user_country), ('clientes', client_country), ('tecnicos', tech_country), ('ordenes', country)):
                    geo_counts[tenant][label][selected] += 1
                for name, row in (('usuarios',user),('clientes',client),('tecnicos',tech),('ordenes',order),('agenda',visita),('partes',parte),('controles',control),('marcadores',marker)):
                    write(name, tenant, row)
                workday_key = (assigned_tech, local_date)
                if workday_key not in workdays_written:
                    write('jornadas', tenant, jornada)
                    workdays_written.add(workday_key)
                cursor = visit
                while cursor < end:
                    slot = stamp(cursor)
                    write('bloques', tenant, base(tenant, 'BLOQUE', assigned_tech+'#'+slot, tenant_id=tenant, tecnico_id=assigned_tech, visita_id=ids['visita']))
                    cursor += timedelta(minutes=30)
    finally:
        for handle in handles.values():
            handle.close()
    manifest = {'schema': 1, 'seed': seed, 'target': target, 'start_date': start_date, 'contact_policy':'invalid_domains_masked_phones', 'geography_weights':geography, 'geography_counts':{t:{k:dict(v) for k,v in values.items()} for t,values in geo_counts.items()}, 'counts':{k:dict(v) for k,v in counts.items()}, 'files':{}}
    for service in handles:
        file = out / f'{service}.jsonl'
        manifest['files'][file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest


def visual_preview(folder: Path, seed: int, size: int = 100) -> None:
    rng = random.Random(seed + 948113)
    sample: list[dict[str, str]] = []
    seen = 0
    for filename, email_field in (('usuarios.jsonl', 'email_normalizado'), ('clientes.jsonl', 'correo')):
        with (folder / filename).open(encoding='utf-8') as source:
            for line in source:
                item = json.loads(line)
                local, domain = item[email_field].split('@')
                brand = domain.removesuffix('.invalid')
                commercial = f'{brand}.com' if domain in MAIL_DOMAINS else f'{brand}.com.pe'
                record = {'nombre': item['nombre'], 'correo': f'{local}@{commercial}'}
                seen += 1
                if len(sample) < size:
                    sample.append(record)
                else:
                    index = rng.randrange(seen)
                    if index < size:
                        sample[index] = record
    result = {'uso': 'SOLO VISTA VISUAL; NO CONTACTAR NI IMPORTAR', 'muestras': sample}
    (folder / 'vista_visual.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--target',type=int,default=37000)
    parser.add_argument('--seed',type=int,default=20261104)
    parser.add_argument('--start-date',default='2026-11-09')
    parser.add_argument('--perfil-geografico',action='append',default=[])
    parser.add_argument('--vista-visual',action='store_true')
    args=parser.parse_args()
    result = generate(args.out,args.target,args.seed,args.start_date,parse_geography(args.perfil_geografico))
    if args.vista_visual:
        visual_preview(args.out, args.seed)
    print(json.dumps(result['counts'],ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
